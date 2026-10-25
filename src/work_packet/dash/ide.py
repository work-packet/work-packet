"""Web VS Code under the board's ``/ide/`` (docs/vscode-plan.md §4, V3).

wpkd runs ``code serve-web`` on a unix socket with no token and no port of
its own, and proxies ``/ide/*`` to it. Every request has already passed the
board's ``Guard`` (identity, Host, Origin), so the board's login is VS Code's.

The backend starts on the first request, stops after ``[ide] idle_minutes``
with no open WebSocket, and stops with the board. It runs in a session of its
own: ``code`` is a wrapper around a tree of processes, so it is stopped by
signalling the whole group (V0 finding 6).
"""

import asyncio
import contextlib
import hashlib
import logging
import os
import signal
import socket
import subprocess
import time

log = logging.getLogger("wpk.dash")

BASE = "/ide"
SUN_PATH_MAX = 100          # sockaddr_un.sun_path is 108 bytes; leave room
START_S = 15                # for the socket to appear (the server download comes after)
STOP_S = 5
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "te", "trailer",
       "proxy-authorization", "proxy-authenticate", "content-length", "host", "cookie",
       "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
       "x-real-ip", "via", "x-csrf-token"}
TRUST = (b"&quot;enableWorkspaceTrust&quot;:true", b"&quot;enableWorkspaceTrust&quot;:false")


class IdeUnavailable(Exception):
    pass


def socket_path(home, env=None):
    """``$WPK_HOME/ide/serve.sock`` when it fits in ``sun_path``, else a short
    private directory named after the home (V0 finding 1)."""
    env = os.environ if env is None else env
    p = os.path.join(home, "ide", "serve.sock")
    if len(os.fsencode(p)) <= SUN_PATH_MAX:
        return p
    tag = hashlib.sha256(os.fsencode(os.path.abspath(home))).hexdigest()[:8]
    run = env.get("XDG_RUNTIME_DIR")
    if run and os.path.isdir(run):
        return os.path.join(run, "wpk-ide-" + tag, "serve.sock")
    return os.path.join("/tmp", "wpk-ide-%d-%s" % (os.getuid(), tag), "serve.sock")


def private_dir(d):
    """Make ``d`` (0700, ours) or refuse: the backend has no token of its own."""
    os.makedirs(d, mode=0o700, exist_ok=True)
    st = os.lstat(d)
    if st.st_uid != os.getuid() or st.st_mode & 0o077 or not os.path.isdir(d) \
            or os.path.islink(d):
        raise IdeUnavailable("%s must be a directory only you can open (mode 0700)" % d)


def available(code="code", which=None):
    """Why web VS Code cannot run here, or None."""
    import shutil
    which = which or shutil.which
    exe = which(code)
    if exe is None:
        return "%r is not on PATH (install VS Code, or set [ide] code)" % code
    return None


class Backend:
    """One ``serve-web`` for every packet, started on demand."""

    def __init__(self, home, cfg, argv=None, clock=time.monotonic):
        self.home = home
        self.cfg = cfg
        self.sock = socket_path(home)
        self.data = os.path.join(home, "ide", "data")
        self.log_path = os.path.join(home, "ide", "serve.log")
        self.pid_path = os.path.join(home, "ide", "serve.pid")
        self._argv = argv           # tests: a fake backend
        self._clock = clock
        self.proc = None            # the Popen, or an int pid adopted from an earlier board
        self.clients = 0
        self.last = clock()
        self._lock = asyncio.Lock()
        self._idle = None
        self._http = None

    # -- the process ---------------------------------------------------------

    def argv(self):
        if self._argv is not None:
            return list(self._argv) + [self.sock]
        return [self.cfg.get("code") or "code", "serve-web", "--socket-path", self.sock,
                "--server-base-path", BASE, "--without-connection-token",
                "--accept-server-license-terms", "--server-data-dir", self.data]

    def _connectable(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(0.5)
            s.connect(self.sock)
            return True
        except OSError:
            return False
        finally:
            s.close()

    async def ensure(self):
        """The backend is up (started now, or already)."""
        async with self._lock:
            if self.running() and self._connectable():
                return
            if self.proc is None and self._adopt():
                log.info("using VS Code's server left by an earlier board, pid %d", self.proc)
            else:
                await asyncio.get_running_loop().run_in_executor(None, self._start)
            end = self._clock() + START_S
            while not self._connectable():
                if not self.running():
                    code, self.proc = getattr(self.proc, "returncode", None), None
                    raise IdeUnavailable("VS Code's server exited (%s); see %s"
                                         % (code, self.log_path))
                if self._clock() > end:
                    self._stop_now()
                    raise IdeUnavailable("VS Code's server did not start in %d s; see %s"
                                         % (START_S, self.log_path))
                await asyncio.sleep(0.1)
            self.last = self._clock()
            if self._idle is None or self._idle.done():
                self._idle = asyncio.ensure_future(self._idle_loop())

    def _start(self):
        private_dir(os.path.dirname(self.sock))
        private_dir(os.path.join(self.home, "ide"))
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.sock)
        out = open(self.log_path, "ab")
        try:
            self.proc = subprocess.Popen(self.argv(), stdin=subprocess.DEVNULL, stdout=out,
                                         stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            raise IdeUnavailable("cannot start %s: %s" % (self.argv()[0], e)) from None
        finally:
            out.close()
        with open(self.pid_path, "w") as fp:
            fp.write("%d\n" % self.proc.pid)
        log.info("started VS Code's server, pid %d", self.proc.pid)

    def running(self):
        p = self.proc
        if p is None:
            return False
        if isinstance(p, int):
            return _alive(p)
        return p.poll() is None

    def _adopt(self):
        """A server an earlier board started (and did not stop: it crashed) is
        still answering on our socket: take it over, so it stops when idle."""
        try:
            with open(self.pid_path) as fp:
                pid = int(fp.read().split()[0])
        except (OSError, ValueError, IndexError):
            return False
        if not (_alive(pid) and self._connectable()):
            return False
        try:
            if os.getpgid(pid) != pid:      # not the leader of the group we started
                return False
        except OSError:
            return False
        self.proc = pid
        return True

    def _stop_now(self):
        p, self.proc = self.proc, None
        if p is None:
            return
        pid = p if isinstance(p, int) else p.pid
        if isinstance(p, int) and not _alive(pid) or not isinstance(p, int) and \
                p.poll() is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGTERM)
        if not _wait(p, STOP_S):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
            _wait(p, STOP_S)
        with contextlib.suppress(OSError):
            os.unlink(self.pid_path)
        log.info("stopped VS Code's server")

    def stop(self):
        """With the board. Call it on the board's event loop thread."""
        if self._idle is not None:
            self._idle.cancel()
        self._stop_now()
        with contextlib.suppress(OSError):
            os.unlink(self.sock)

    async def _idle_loop(self):
        limit = 60.0 * float(self.cfg.get("idle_minutes") or 60)
        while self.proc is not None:
            await asyncio.sleep(min(30.0, limit / 4))
            if self.clients == 0 and self._clock() - self.last > limit:
                await asyncio.get_running_loop().run_in_executor(None, self._stop_now)

    # -- proxying ------------------------------------------------------------

    def client(self):
        import httpx
        if self._http is None:
            self._http = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=self.sock),
                                           timeout=httpx.Timeout(60.0, connect=5.0))
        return self._http


def _alive(pid):
    """Running (a zombie is not: it has exited and waits for its parent)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open("/proc/%d/stat" % pid) as fp:
            return fp.read().rpartition(")")[2].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _wait(p, timeout):
    """Wait for a Popen or a pid (not our child: poll) to end; True if it did."""
    if not isinstance(p, int):
        try:
            p.wait(timeout)
            return True
        except subprocess.TimeoutExpired:
            return False
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _alive(p):
            return True
        time.sleep(0.05)
    return False


def _cookies(header):
    """Only VS Code's own cookies go to it (V0 finding 3)."""
    keep = [c.strip() for c in (header or "").split(";")
            if c.strip().startswith("vscode-")]
    return "; ".join(keep)


def upstream_headers(headers):
    """The request headers that go to the backend: Host as sent (it builds its
    URLs from it, V0 finding 2), VS Code's cookies, and nothing a proxy adds."""
    out = [(k, v) for k, v in headers.items() if k.lower() not in HOP]
    out.append(("host", headers.get("host", "localhost")))
    c = _cookies(headers.get("cookie"))
    if c:
        out.append(("cookie", c))
    return out


async def proxy_http(backend, request):
    from starlette.background import BackgroundTask
    from starlette.responses import PlainTextResponse, Response, StreamingResponse
    try:
        await backend.ensure()
    except IdeUnavailable as e:
        return PlainTextResponse("503 %s\n" % e, status_code=503)
    backend.last = backend._clock()
    url = "http://localhost" + request.url.path + \
        ("?" + request.url.query if request.url.query else "")
    hc = backend.client()
    req = hc.build_request(request.method, url, headers=upstream_headers(request.headers),
                           content=request.stream())
    try:
        r = await hc.send(req, stream=True)
    except Exception as e:          # httpx's transport errors
        return PlainTextResponse("502 VS Code's server: %s\n" % e, status_code=502)
    out = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in r.headers.multi_items()
           if k.lower() not in ("connection", "keep-alive", "transfer-encoding",
                                "content-length")]
    if r.headers.get("content-type", "").startswith("text/html") and \
            not backend.cfg.get("workspace_trust", False):
        body = (await r.aread()).replace(*TRUST)
        await r.aclose()
        resp = Response(body, status_code=r.status_code)
        resp.raw_headers = out + [(b"content-length", str(len(body)).encode())]
        return resp
    resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code,
                             background=BackgroundTask(r.aclose))
    resp.raw_headers = out
    return resp


async def proxy_ws(backend, websocket):
    from websockets.asyncio.client import unix_connect
    try:
        await backend.ensure()
    except IdeUnavailable as e:
        log.warning("web VS Code: %s", e)
        return await websocket.close(1011)
    path = websocket.url.path + ("?" + websocket.url.query if websocket.url.query else "")
    # The Host goes in the URI: websockets sends it from there (V0 finding 2).
    host = websocket.headers.get("host") or "localhost"
    hdrs = [(k, v) for k, v in upstream_headers(websocket.headers)
            if k.lower() in ("cookie", "origin", "user-agent", "accept-language")]
    try:
        up = await unix_connect(backend.sock, "ws://%s%s" % (host, path),
                                additional_headers=hdrs, max_size=None,
                                open_timeout=10)
    except Exception as e:
        log.warning("web VS Code: WebSocket to the server failed: %s", e)
        return await websocket.close(1011)
    await websocket.accept()
    backend.clients += 1

    async def down():
        async for m in up:
            if isinstance(m, bytes):
                await websocket.send_bytes(m)
            else:
                await websocket.send_text(m)

    async def upstream():
        while True:
            m = await websocket.receive()
            if m["type"] == "websocket.disconnect":
                return
            backend.last = backend._clock()
            if m.get("bytes") is not None:
                await up.send(m["bytes"])
            elif m.get("text") is not None:
                await up.send(m["text"])

    tasks = [asyncio.ensure_future(down()), asyncio.ensure_future(upstream())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        backend.clients -= 1
        backend.last = backend._clock()
        await up.close()
        with contextlib.suppress(Exception):
            await websocket.close()
