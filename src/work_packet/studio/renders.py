"""Renders of the studio's artifacts (docs/studio-plan.md S3.1, S3.4, S3.5).

The same pictures serve as version thumbnails, what the agent looks at
(``wpk studio look``) and, later, comment crops: one renderer (the design
§5.3). A document, chart or table is rendered by loading its studio frame
page (``.../studio/frame/<doc|chart|table>?path=...&render=1``) in the
headless browser (``render.py``) through the dash's **render listener**: a
loopback port only the renderer and wpk's own commands know (a secret
header, ``$WPK_HOME/run/render.json``), which serves the studio's frame,
data and static routes, read-only, as the person who has the studio. An
image is its own render.

Each render is kept in ``<run dir>/studio/renders/<key>/`` (``full.png``,
``thumb.png``, ``full.N.png`` parts for a tall page, ``info.json``), where
``key`` is a hash of the file and what it reads (a chart's data, a saved
query's files): the same content is rendered once. ``info.json`` has the
**checks** run in the page (``CHECK_JS``): overflow, text outside a chart,
broken images, Vega warnings, console errors.
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
import urllib.parse

from .. import fsutil, layout
from . import kinds

RENDER_V = 1
KINDS = {"document": "doc", "chart": "chart", "table": "table"}
WIDTH = 960
PART_H = 1400
MAX_H = 12000
HEADER = "x-wpk-render"
USER_HEADER = "x-wpk-render-user"
LOOK_DIR = os.path.join(".studio", "look")

# Runs in the rendered page once it is ready: the cheap checks (§5.3). The
# ``__studioChecks`` name is how the fake browser in the tests knows it.
CHECK_JS = r"""(() => { const __studioChecks = [];
  const add = (check, what) => { if (__studioChecks.length < 20 &&
    !__studioChecks.some((c) => c.what === what)) __studioChecks.push({check, what}); };
  const name = (e) => e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") +
    (e.className && typeof e.className === "string" ? "." + e.className.trim().split(/\s+/)[0] : "");
  const root = document.documentElement, W = root.clientWidth;
  if (root.scrollWidth > W + 2) add("overflow", "the page is wider than its window (" +
    root.scrollWidth + "px for " + W + "px)");
  document.querySelectorAll("main *").forEach((e) => {
    if (e.closest("svg")) return;
    const cs = getComputedStyle(e);
    if (["auto", "scroll", "hidden", "clip"].includes(cs.overflowX) && e.scrollWidth > e.clientWidth + 2)
      add("overflow", name(e) + " is wider than its box (" + e.scrollWidth + "px for " + e.clientWidth + "px)" +
        (e.textContent ? ": " + JSON.stringify(e.textContent.trim().slice(0, 50)) : ""));
  });
  document.querySelectorAll("img").forEach((i) => {
    if (i.complete && i.naturalWidth === 0) add("broken-image", "image " + (i.getAttribute("src") || "") + " did not load");
  });
  document.querySelectorAll("svg").forEach((s) => {
    const r = s.getBoundingClientRect();
    s.querySelectorAll("text").forEach((t) => {
      const b = t.getBoundingClientRect();
      if (b.width && (b.left < r.left - 1 || b.right > r.right + 1 || b.top < r.top - 1 || b.bottom > r.bottom + 1))
        add("clipped-text", JSON.stringify(t.textContent.slice(0, 60)) + " runs outside the chart");
    });
  });
  (window.__studioWarnings || []).forEach((w) => add("vega", String(w)));
  return __studioChecks; })()"""


class RenderUnavailable(Exception):
    """No renders here: no browser, or no render listener; the message says why."""


def render_dir(entry, wpid):
    return os.path.join(layout.run_dir(entry["path"], wpid), "studio", "renders")


def _sha(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fp:
            for chunk in iter(lambda: fp.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


_QUOTED = re.compile(r"'((?:[^']|'')+)'")


def deps(folder, rel, kind):
    """The folder paths a render of ``rel`` reads besides ``rel`` itself: a
    chart's data (and what a ``.sql`` it names reads), a saved query's files
    (the quoted paths in it that are files)."""
    out = []

    def sql_files(r):
        try:
            text = fsutil.read_text(os.path.join(folder, r))
        except OSError:
            return []
        got = []
        for m in _QUOTED.finditer(text):
            p = os.path.normpath(m.group(1).replace("''", "'"))
            if not p.startswith("..") and not os.path.isabs(p) and \
                    os.path.isfile(os.path.join(folder, p)):
                got.append(p)
        return got
    if kind == "chart":
        from . import chart
        try:
            spec = chart.load(os.path.join(folder, rel))
            for d in chart._datas(spec):
                p = chart.resolve(rel, d["url"])
                out.append(p)
                if p.lower().endswith(".sql"):
                    out += sql_files(p)
        except (chart.ChartError, OSError, ValueError, KeyError):
            pass
    elif kind == "table" and rel.lower().endswith(".sql"):
        out = sql_files(rel)
    return sorted(set(out) - {rel})


def key(folder, rel, kind):
    """The render's content key: the file, what it reads, how it is drawn."""
    parts = [RENDER_V, kind, rel, _sha(os.path.join(folder, rel))]
    parts += [[d, _sha(os.path.join(folder, d))] for d in deps(folder, rel, kind)]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:32]


def frame_path(entry, wpid, rel, kind):
    return "/p/%s/%s/studio/frame/%s?path=%s&render=1" % (
        urllib.parse.quote(entry["name"]), wpid, KINDS[kind], urllib.parse.quote(rel))


def info(entry, wpid, k):
    try:
        with open(os.path.join(render_dir(entry, wpid), k, "info.json"), encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return None


def checks_of(res):
    """The checks of a render result: the page's, then console errors."""
    got = res.get("value")
    out = [c for c in got if isinstance(c, dict) and c.get("check")] if isinstance(got, list) \
        else []
    for e in res.get("errors") or []:
        out.append({"check": "console", "what": str(e)[:300]})
    if not res.get("ready", True):
        out.append({"check": "not-ready", "what": "the page did not finish drawing in time"})
    return out[:20]


class Service:
    """The dash's renderer: one browser (``render.Queue``), the render
    listener's URL and secret. ``install`` makes it the process's."""

    def __init__(self, home, browser=None, base_url=None, secret=None):
        self.home = home
        self.secret = secret or secrets.token_urlsafe(32)
        self.base_url = base_url
        self._browser = browser
        self._queue = None
        self.lock = threading.Lock()

    def browser(self):
        from . import render
        with self.lock:
            if self._browser is None:
                self._browser = render.Browser(home=self.home)
            if self._queue is None:
                self._queue = render.Queue(self._browser)
            return self._browser, self._queue

    def available(self):
        """None, or why there are no renders."""
        if not self.base_url:
            return "the board has no render listener"
        b, _ = self.browser()
        if not b.available:
            return "no headless browser: install Google Chrome or Chromium, or set " \
                   "[studio] chrome"
        return None

    def stop(self):
        if self._browser is not None:
            self._browser.stop()

    def render(self, entry, wpid, rel, user, wait=True, timeout_s=120):
        """The render of ``rel`` as it is now: its ``info`` (``key``, ``png``,
        ``thumb``, ``parts``, ``checks``, ``size``), from the cache when the
        content was rendered before. ``wait`` False: queue it and return None
        (or the cached info). An image is its own render; other kinds have none."""
        from . import model
        folder = model.folder(entry, wpid)
        k_ = kinds.kind_of(rel)
        if k_ is None:
            return None
        if k_.name == "image":
            return {"key": None, "kind": "image", "rel": rel, "png": os.path.join(folder, rel),
                    "thumb": os.path.join(folder, rel), "parts": [], "checks": []}
        if k_.name not in KINDS:
            return None
        k = key(folder, rel, k_.name)
        got = info(entry, wpid, k)
        if got is not None:
            return got
        why = self.available()
        if why:
            raise RenderUnavailable(why)
        d = os.path.join(render_dir(entry, wpid), k)
        tmp = d + ".tmp-%s" % secrets.token_hex(4)
        os.makedirs(tmp, exist_ok=True)
        _, q = self.browser()
        fut = q.submit(k, self.base_url + frame_path(entry, wpid, rel, k_.name),
                       png=os.path.join(tmp, "full.png"), thumb=os.path.join(tmp, "thumb.png"),
                       parts_h=PART_H, max_h=MAX_H, width=WIDTH, height=800, script=CHECK_JS,
                       headers={HEADER: self.secret, USER_HEADER: user}, ready_timeout_s=20)

        def store(f):
            try:
                res = f.result()
            except Exception as ex:             # noqa: BLE001  (kept as the render's failure)
                shutil.rmtree(tmp, ignore_errors=True)
                return {"key": k, "error": str(ex)}
            if res is None:                     # superseded by a newer render of the same key
                shutil.rmtree(tmp, ignore_errors=True)
                return info(entry, wpid, k)
            inf = {"key": k, "kind": k_.name, "rel": rel, "at": time.time(),
                   "size": list(res.get("size") or ()), "checks": checks_of(res),
                   "parts": [os.path.basename(p) for p in res.get("parts") or []]}
            fsutil.atomic_write(os.path.join(tmp, "info.json"), json.dumps(inf, indent=1) + "\n")
            try:
                os.replace(tmp, d)
            except OSError:                     # rendered twice at once: keep the first
                shutil.rmtree(tmp, ignore_errors=True)
            return info(entry, wpid, k)
        if not wait:
            fut.add_done_callback(store)
            return None
        try:
            fut.result(timeout_s)
        except Exception:                       # noqa: BLE001  (store says what went wrong)
            pass
        got = store(fut)
        if got is None or got.get("error"):
            raise RenderUnavailable("the render failed: %s" % ((got or {}).get("error")
                                                             or "no result"))
        return got

    def look(self, project, wpid, rel, part=None):
        """For ``wpk studio look``: render ``rel`` (as the studio's owner) and
        copy the pictures into the folder's ``.studio/look/`` (the agent can
        always read there). ``{files, checks, size, parts}``."""
        from .. import archived
        from . import model
        entry = archived.get(project, self.home)
        st = model.state(entry, wpid)
        if not st["open"]:
            raise RenderUnavailable("the studio of %s is not open" % wpid[:8])
        rel = model._artifact(st["folder"], rel)
        if not os.path.isfile(os.path.join(st["folder"], rel)):
            raise RenderUnavailable("no file %s in the studio's folder" % rel)
        got = self.render(entry, wpid, rel, st["taken_by"])
        if got is None:
            raise RenderUnavailable("%s has no picture: the studio renders documents, "
                                    "charts, tables and images" % rel)
        out_dir = os.path.join(st["folder"], LOOK_DIR)
        os.makedirs(out_dir, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", rel)
        if got.get("kind") == "image":
            return {"files": [rel], "checks": [], "size": None, "parts": 0}
        d = os.path.join(render_dir(entry, wpid), got["key"])
        names = got.get("parts") or []
        if part is None:
            srcs = names or ["full.png"]
        elif 1 <= part <= max(len(names), 1):
            srcs = [names[part - 1]] if names else ["full.png"]
        else:
            n = max(len(names), 1)
            raise RenderUnavailable("%s has %d part%s" % (rel, n, "" if n == 1 else "s"))
        files = []
        for src in srcs:
            dst = "%s%s.png" % (stem, "" if src == "full.png" else "." + src.split(".")[1])
            shutil.copyfile(os.path.join(d, src), os.path.join(out_dir, dst))
            files.append(os.path.join(LOOK_DIR, dst).replace(os.sep, "/"))
        return {"files": files, "checks": got.get("checks") or [], "size": got.get("size"),
                "parts": len(got.get("parts") or [])}


_SERVICE = None


def install(svc):
    global _SERVICE
    _SERVICE = svc
    return svc


def current():
    return _SERVICE


def listener_file(home):
    return os.path.join(home, "run", "render.json")


def write_listener(home, url, secret):
    p = listener_file(home)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    old = os.umask(0o077)
    try:
        fsutil.atomic_write(p, json.dumps({"url": url, "secret": secret,
                                           "pid": os.getpid()}) + "\n")
    finally:
        os.umask(old)
    os.chmod(p, 0o600)


def read_listener(home):
    try:
        with open(listener_file(home), encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return None
