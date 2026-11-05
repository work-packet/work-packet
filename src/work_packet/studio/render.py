"""The render service (docs/studio-plan.md P0.4): pages to PNG and PDF through a
headless Chrome.

One browser per server, started on first use and stopped when idle, driven
over the DevTools protocol (CDP) by the small client here: no Playwright, no
Node (decision D10). The browser is ``[studio] chrome`` or the first of
``BROWSERS`` on ``PATH``; with none, ``find_browser`` returns None and the
studio says renders are off (it works without them).

``Browser.render(url, ...)`` opens the page in a new tab at a viewport size,
waits for it to load and then for ``window.__studioReady`` (a page that
renders late sets it to ``false`` first and ``true`` when done; a page that
never sets it is ready at load), and gives back what was asked: a PNG of the
page or of one element, a PDF, the value of a script, and the console errors
and exceptions it logged. ``Queue`` runs renders one at a time, only the newest
request per artifact, and keeps each artifact's last good result.
"""

import base64
import itertools
import json
import logging
import os
import queue as queuemod
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import Future

from .. import registry, schema

log = logging.getLogger("wpk")

BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
FLAGS = ("--headless=new", "--remote-debugging-port=0", "--no-first-run",
         "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars", "--mute-audio",
         "--disable-extensions", "--disable-background-networking", "--disable-sync",
         "--metrics-recording-only", "--password-store=basic")
LISTENING = re.compile(r"DevTools listening on (ws://\S+)")
START_TIMEOUT_S = 20
READY_JS = "window.__studioReady === undefined || window.__studioReady === true"


class RenderError(Exception):
    """A render that could not be done: no browser, a timeout, a CDP error."""


def config(home=None):
    """``[studio]`` over ``schema.STUDIO_DEFAULTS``; the defaults if unreadable."""
    try:
        got = registry.load_config_file(home).get("studio") or {}
    except registry.ConfigError:
        got = {}
    return dict(schema.STUDIO_DEFAULTS, **got)


def find_browser(cfg=None):
    """The browser's path: ``[studio] chrome`` (a path or a name on PATH), else
    the first of ``BROWSERS`` on PATH; None when there is none."""
    cfg = cfg if cfg is not None else config()
    want = (cfg.get("chrome") or "").strip()
    for name in ([want] if want else BROWSERS):
        p = shutil.which(name) if not os.path.isabs(name) else (
            name if os.access(name, os.X_OK) else None)
        if p:
            return p
    return None


class _Conn:
    """One CDP websocket: commands by id, with or without a target session;
    events go to the waiting ``wait_event`` or are kept per session."""

    def __init__(self, url, timeout_s):
        from websockets.sync.client import connect
        self.cm = connect(url, max_size=None, open_timeout=timeout_s, origin=None)
        self.ws = self.cm.__enter__()       # websockets 17 wants it used as a context
        self.ids = itertools.count(1)
        self.events = []
        self.lock = threading.Lock()

    def close(self):
        try:
            self.cm.__exit__(None, None, None)
        except Exception:                     # noqa: BLE001  (already gone)
            pass

    def call(self, method, params=None, session=None, timeout_s=30):
        i = next(self.ids)
        msg = {"id": i, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        with self.lock:
            self.ws.send(json.dumps(msg))
            end = time.monotonic() + timeout_s
            while True:
                m = self._recv(end, method)
                if m.get("id") == i:
                    if "error" in m:
                        raise RenderError("%s: %s" % (method, m["error"].get("message")))
                    return m.get("result") or {}
                if "method" in m:
                    self.events.append(m)

    def wait_event(self, name, session, timeout_s):
        """The first event ``name`` of ``session``, kept or still to come."""
        end = time.monotonic() + timeout_s
        with self.lock:
            while True:
                for k, ev in enumerate(self.events):
                    if ev.get("method") == name and ev.get("sessionId") == session:
                        return self.events.pop(k)
                m = self._recv(end, name)
                if "method" in m:
                    self.events.append(m)

    def take_events(self, session):
        with self.lock:
            mine = [e for e in self.events if e.get("sessionId") == session]
            self.events = [e for e in self.events if e.get("sessionId") != session]
        return mine

    def _recv(self, end, what):
        left = end - time.monotonic()
        if left <= 0:
            raise RenderError("timed out waiting for %s" % what)
        try:
            return json.loads(self.ws.recv(timeout=left))
        except TimeoutError:
            raise RenderError("timed out waiting for %s" % what) from None
        except Exception as ex:               # noqa: BLE001  (the browser went away)
            raise RenderError("the browser connection failed: %s" % ex) from None


class Browser:
    """A headless browser, started on first use (``ensure``), stopped by
    ``reap`` once idle for ``idle_s`` or by ``stop``. Thread-safe."""

    def __init__(self, exe=None, home=None, idle_s=None, timeout_s=30):
        cfg = config(home)
        self.exe = exe or find_browser(cfg)
        self.home = home or registry.home()
        self.idle_s = idle_s if idle_s is not None else cfg["render_idle_minutes"] * 60
        self.timeout_s = timeout_s
        self.proc = None
        self.conn = None
        self.used = 0.0
        self.lock = threading.RLock()

    @property
    def available(self):
        return self.exe is not None

    def profile_dir(self):
        return os.path.join(self.home, "run", "render-profile")

    def ensure(self):
        with self.lock:
            if self.proc is not None and self.proc.poll() is None and self.conn is not None:
                return self.conn
            self.stop()
            if not self.exe:
                raise RenderError("no browser for renders: set [studio] chrome, or put "
                                  "chromium or google-chrome on PATH")
            os.makedirs(self.profile_dir(), exist_ok=True)
            argv = [self.exe] + list(FLAGS) + ["--user-data-dir=" + self.profile_dir(),
                                               "about:blank"]
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
            url = self._listening(p)
            self.proc, self.conn = p, _Conn(url, self.timeout_s)
            threading.Thread(target=_drain, args=(p.stderr,), daemon=True).start()
            self.used = time.monotonic()
            return self.conn

    def _listening(self, p):
        out = []
        found = {}

        def read():
            for ln in p.stderr:
                out.append(ln)
                m = LISTENING.search(ln)
                if m:
                    found["url"] = m.group(1)
                    return
        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(START_TIMEOUT_S)
        if "url" not in found:
            _kill(p)
            raise RenderError("the browser did not start: %s" % "".join(out[-5:]).strip())
        return found["url"]

    def stop(self):
        with self.lock:
            if self.conn is not None:
                try:
                    self.conn.call("Browser.close", timeout_s=3)
                except RenderError:
                    pass
                self.conn.close()
            if self.proc is not None:
                _kill(self.proc)
            self.proc = self.conn = None

    def reap(self, now=None):
        """Stop the browser if it has been idle for ``idle_s``. True if it did."""
        with self.lock:
            if self.proc is None:
                return False
            if (now if now is not None else time.monotonic()) - self.used < self.idle_s:
                return False
            self.stop()
            return True

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def render(self, url, png=None, pdf=None, selector=None, full_page=True, width=1200,
               height=800, script=None, ready_timeout_s=15, headers=None, thumb=None,
               thumb_scale=0.3, parts_h=None, max_h=None):
        """Render ``url``. ``png``/``pdf``: files to write. ``selector``: the PNG is
        of that element only. ``script``: a JavaScript expression evaluated once
        ready; its value is returned. ``headers``: sent with every request of
        the page. ``thumb``: also write the same picture at ``thumb_scale`` there.
        ``parts_h``: a full page taller than this is also cut into parts
        (``png`` with ``.1.png``, ``.2.png``, ...); ``max_h``: the full page is
        cut off below this. Returns ``{ready, png, pdf, value, errors, size,
        thumb, parts}``; ``ready`` False when the page never said so (the render
        is taken anyway)."""
        with self.lock:
            conn = self.ensure()
            self.used = time.monotonic()
            tid = conn.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            try:
                sid = conn.call("Target.attachToTarget",
                                {"targetId": tid, "flatten": True})["sessionId"]
                return self._render(conn, sid, url, png, pdf, selector, full_page, width,
                                    height, script, ready_timeout_s, headers=headers,
                                    thumb=thumb, thumb_scale=thumb_scale, parts_h=parts_h,
                                    max_h=max_h)
            finally:
                try:
                    conn.call("Target.closeTarget", {"targetId": tid}, timeout_s=5)
                except RenderError:
                    pass
                self.used = time.monotonic()

    def _render(self, conn, sid, url, png, pdf, selector, full_page, width, height, script,
                ready_timeout_s, headers=None, thumb=None, thumb_scale=0.3, parts_h=None,
                max_h=None):
        for m in ("Page.enable", "Runtime.enable", "Log.enable"):
            conn.call(m, session=sid)
        if headers:
            conn.call("Network.enable", session=sid)
            conn.call("Network.setExtraHTTPHeaders", {"headers": dict(headers)}, session=sid)
        conn.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
            session=sid)
        nav = conn.call("Page.navigate", {"url": url}, session=sid)
        if nav.get("errorText"):
            raise RenderError("could not load %s: %s" % (url, nav["errorText"]))
        conn.wait_event("Page.loadEventFired", sid, self.timeout_s)
        ready = self._wait_ready(conn, sid, ready_timeout_s)
        out = {"ready": ready, "png": None, "pdf": None, "value": None, "errors": [],
               "thumb": None, "parts": []}
        if script:
            out["value"] = self._eval(conn, sid, script)
        m = conn.call("Page.getLayoutMetrics", session=sid)
        cs = m.get("cssContentSize") or m.get("contentSize") or {}
        out["size"] = (int(cs.get("width") or width), int(cs.get("height") or height))
        if png:
            clip = None
            if selector:
                r = self._eval(conn, sid, "(() => { const e = document.querySelector(%s); "
                               "if (!e) return null; const r = e.getBoundingClientRect(); "
                               "return [r.left + scrollX, r.top + scrollY, r.width, r.height]; })()"
                               % json.dumps(selector))
                if not r:
                    raise RenderError("no element matches %s" % selector)
                clip = {"x": r[0], "y": r[1], "width": max(r[2], 1), "height": max(r[3], 1)}
            elif full_page:
                h = out["size"][1] if not max_h else min(out["size"][1], max_h)
                clip = {"x": 0, "y": 0, "width": out["size"][0], "height": h}

            def shot(c, scale, path):
                args = {"format": "png", "captureBeyondViewport": bool(c)}
                if c:
                    args["clip"] = dict(c, scale=scale)
                elif scale != 1:
                    args["clip"] = {"x": 0, "y": 0, "width": width, "height": height,
                                    "scale": scale}
                data = conn.call("Page.captureScreenshot", args, session=sid,
                                 timeout_s=60)["data"]
                _write(path, base64.b64decode(data))
            shot(clip, 1, png)
            out["png"] = png
            if thumb:
                shot(clip, thumb_scale, thumb)
                out["thumb"] = thumb
            if parts_h and clip and not selector and clip["height"] > parts_h:
                root, _ = os.path.splitext(png)
                y, n = 0, 0
                while y < clip["height"]:
                    n += 1
                    part = "%s.%d.png" % (root, n)
                    shot({"x": 0, "y": y, "width": clip["width"],
                          "height": min(parts_h, clip["height"] - y)}, 1, part)
                    out["parts"].append(part)
                    y += parts_h
        if pdf:
            data = conn.call("Page.printToPDF", {"printBackground": True},
                             session=sid, timeout_s=60)["data"]
            _write(pdf, base64.b64decode(data))
            out["pdf"] = pdf
        out["errors"] = _errors(conn.take_events(sid))
        return out

    def _wait_ready(self, conn, sid, timeout_s):
        end = time.monotonic() + timeout_s
        while True:
            if self._eval(conn, sid, READY_JS) is True:
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(0.05)

    def _eval(self, conn, sid, expr):
        r = conn.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True}, session=sid)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RenderError("script failed: %s" % ((d.get("exception") or {}).get(
                "description") or d.get("text")))
        return (r.get("result") or {}).get("value")


def _errors(events):
    """Console errors, uncaught exceptions and error log entries (CSP refusals
    among them) from a page's events."""
    out = []
    for e in events:
        p = e.get("params") or {}
        if e["method"] == "Runtime.consoleAPICalled" and p.get("type") == "error":
            out.append(" ".join(str(a.get("value", a.get("description", "")))
                                for a in p.get("args") or []))
        elif e["method"] == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails") or {}
            out.append((d.get("exception") or {}).get("description") or d.get("text") or "?")
        elif e["method"] == "Log.entryAdded" and (p.get("entry") or {}).get("level") == "error":
            ent = p["entry"]
            out.append((ent.get("text") or "?") + (" (%s)" % ent["url"] if ent.get("url") else ""))
    return out


def _write(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp-%d" % os.getpid()
    with open(tmp, "wb") as fp:
        fp.write(data)
    os.replace(tmp, path)


def _drain(fp):
    try:
        for _ in fp:
            pass
    except (OSError, ValueError):
        pass


def _kill(p):
    import signal
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.wait(5)


class Queue:
    """Renders one at a time on one ``Browser``; per artifact ``key`` only the
    newest request runs (an older one waiting is dropped: its future gets
    None), and ``last(key)`` is the last result that worked."""

    def __init__(self, browser):
        self.browser = browser
        self.lock = threading.Lock()
        self.pending = {}               # key -> (kwargs, Future)
        self.order = queuemod.Queue()
        self.good = {}
        self.thread = None

    def submit(self, key, url, **kw):
        fut = Future()
        with self.lock:
            old = self.pending.get(key)
            self.pending[key] = ((url, kw), fut)
            if old is not None:
                old[1].set_result(None)         # superseded before it ran
            else:
                self.order.put(key)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._work, daemon=True,
                                               name="studio-render")
                self.thread.start()
        return fut

    def last(self, key):
        return self.good.get(key)

    def _work(self):
        while True:
            try:
                key = self.order.get(timeout=1)
            except queuemod.Empty:
                with self.lock:
                    if not self.pending:
                        self.thread = None
                        return
                continue
            with self.lock:
                job = self.pending.pop(key, None)
            if job is None:
                continue
            (url, kw), fut = job
            try:
                res = self.browser.render(url, **kw)
            except Exception as ex:             # noqa: BLE001  (the future carries it)
                fut.set_exception(ex)
                continue
            self.good[key] = res
            fut.set_result(res)
