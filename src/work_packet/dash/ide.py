"""Web VS Code under the board's ``/ide/`` (docs/vscode-plan.md §4, V3).

wpkd runs one ``code serve-web`` (or the open-source ``openvscode-server``,
``[ide] backend``) per target, each on a unix socket with no token and no port
of its own, and proxies ``/ide/<key>/*`` to it. A target is what the board
opens: a packet's workspace file or a folder; ``key`` is a hash of its path.
Every request has already passed the board's ``Guard`` (identity, Host,
Origin), so the board's login is VS Code's.

A server starts on the first request, stops after ``[ide] idle_minutes`` with
no open WebSocket, and stops with the board. At most ``[ide] max_servers`` run
at once; the least recently used idle one makes room. Each runs in a session
of its own: ``code`` is a wrapper around a tree of processes, so it is stopped
by signalling the whole group (V0 finding 6).
"""

import asyncio
import contextlib
import hashlib
import logging
import os
import re
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
KEY = re.compile(r"[0-9a-f]{12}\Z")
COOKIE_ROOT = re.compile(r"(;\s*path=)/(?=\s*(;|$))", re.I)


class IdeUnavailable(Exception):
    pass


def key_for(path):
    """The server for a target: a packet's workspace file, or a folder."""
    return hashlib.sha256(os.fsencode(os.path.abspath(path))).hexdigest()[:12]


def server_dir(home, key):
    return os.path.join(home, "ide", "servers", key)


def socket_path(home, key, env=None):
    """``$WPK_HOME/ide/servers/<key>/serve.sock`` when it fits in ``sun_path``,
    else a short private directory named after the home (V0 finding 1)."""
    env = os.environ if env is None else env
    p = os.path.join(server_dir(home, key), "serve.sock")
    if len(os.fsencode(p)) <= SUN_PATH_MAX:
        return p
    tag = hashlib.sha256(os.fsencode(os.path.abspath(home))).hexdigest()[:8]
    run = env.get("XDG_RUNTIME_DIR")
    if run and os.path.isdir(run):
        return os.path.join(run, "wpk-ide-" + tag, key + ".sock")
    return os.path.join("/tmp", "wpk-ide-%d-%s" % (os.getuid(), tag), key + ".sock")


def private_dir(d):
    """Make ``d`` (0700, ours) or refuse: the backend has no token of its own."""
    os.makedirs(d, mode=0o700, exist_ok=True)
    st = os.lstat(d)
    if st.st_uid != os.getuid() or st.st_mode & 0o077 or not os.path.isdir(d) \
            or os.path.islink(d):
        raise IdeUnavailable("%s must be a directory only you can open (mode 0700)" % d)


def private_dirs(home, key):
    """``ide/``, ``ide/servers/`` and the server's own directory, each 0700
    (makedirs does not apply the mode to the ones in between)."""
    for d in (os.path.join(home, "ide"), os.path.join(home, "ide", "servers"),
              server_dir(home, key)):
        private_dir(d)


COMMANDS = {"serve-web": "code", "openvscode-server": "openvscode-server"}


def command(cfg):
    """The program that runs the backend: ``[ide] code``, else the backend's own."""
    return cfg.get("code") or COMMANDS.get(cfg.get("backend") or "serve-web", "code")


def available(cfg, which=None):
    """Why web VS Code cannot run here, or None."""
    import shutil
    which = which or shutil.which
    code = command(cfg)
    if which(code) is None:
        what = "openvscode-server" if cfg.get("backend") == "openvscode-server" else "VS Code"
        return "%r is not on PATH (install %s, or set [ide] code)" % (code, what)
    return None


class Backend:
    """The VS Code server for one target, started on demand."""

    def __init__(self, home, cfg, key, argv=None, clock=time.monotonic):
        self.home = home
        self.cfg = cfg
        self.key = key
        self.base = "%s/%s" % (BASE, key)
        self.dir = server_dir(home, key)
        self.sock = socket_path(home, key)
        self.data = os.path.join(home, "ide", "data")     # shared: extensions, machine settings
        self.log_path = os.path.join(self.dir, "serve.log")
        self.pid_path = os.path.join(self.dir, "serve.pid")
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
            return list(self._argv) + [self.sock, self.base]
        # openvscode-server is VS Code's own server: the same flags, no subcommand.
        sub = [] if self.cfg.get("backend") == "openvscode-server" else ["serve-web"]
        return [command(self.cfg)] + sub + [
            "--socket-path", self.sock, "--server-base-path", self.base,
            "--without-connection-token", "--accept-server-license-terms",
            "--server-data-dir", self.data]

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
                log.info("using VS Code's server %s left by an earlier board, pid %d",
                         self.key, self.proc)
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
        private_dirs(self.home, self.key)
        private_dir(os.path.dirname(self.sock))
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
        log.info("started VS Code's server %s, pid %d", self.key, self.proc.pid)

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
        log.info("stopped VS Code's server %s", self.key)

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

    def url(self, path):
        return "http://localhost" + path

    def headers(self, headers):
        return upstream_headers(headers)

    async def ws_connect(self, path, host, hdrs):
        from websockets.asyncio.client import unix_connect
        # The Host goes in the URI: websockets sends it from there (V0 finding 2).
        return await unix_connect(self.sock, "ws://%s%s" % (host, path), additional_headers=hdrs,
                                  max_size=None, open_timeout=10)

    def client(self):
        import httpx
        if self._http is None:
            self._http = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=self.sock),
                                           timeout=httpx.Timeout(60.0, connect=5.0))
        return self._http


class IdeWaiting(IdeUnavailable):
    """The server's job has no room or has not started yet: the page waits."""


WAIT_S = 3                  # a job-backed server: how long a request waits before the waiting page


class JobBackend(Backend):
    """VS Code's server in a scheduler job (docs/scheduler.md §8; plan Q5.1-Q5.2):
    asked for through ``sched/ide.py``, reached over TCP at the ``endpoint`` the
    job writes, with a connection token only wpkd and the job can read."""

    def __init__(self, home, cfg, key, argv=None, clock=time.monotonic, poke=None, by=None):
        super().__init__(home, cfg, key, argv=argv, clock=clock)
        self.poke = poke or (lambda: None)
        self.by = by
        self.token_path = os.path.join(self.dir, "token")
        self._ep = None

    def token(self):
        try:
            with open(self.token_path) as fp:
                return fp.read().strip()
        except FileNotFoundError:
            import secrets
            fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fp:
                fp.write(secrets.token_hex(24))
            return self.token()

    def job_argv(self):
        import sys
        tok = ["--host", "0.0.0.0", "--port", "{port}", "--connection-token-file",
               self.token_path]
        if self._argv is not None:
            srv = list(self._argv) + ["-", self.base] + tok
        else:
            sub = [] if self.cfg.get("backend") == "openvscode-server" else ["serve-web"]
            srv = [command(self.cfg)] + sub + tok + [
                "--server-base-path", self.base, "--accept-server-license-terms",
                "--server-data-dir", self.data]
        return [sys.executable, "-m", "work_packet.sched.ide_job", self.dir, "--"] + srv

    def size(self):
        try:
            with open(os.path.join(self.dir, "size")) as fp:
                return fp.read().strip() or None
        except OSError:
            return None

    def record(self):
        from ..sched import jobs
        return next((r for r in jobs.all(self.home) if r.kind == "ide" and r.wpid == self.key),
                    None)

    def endpoint(self):
        from ..sched import ide
        return ide.endpoint(self.key, self.home)

    def running(self):
        """Its job exists (pending or running): it counts against max_servers."""
        return self.record() is not None

    def _connectable(self):
        ep = self.endpoint()
        if ep is None:
            return False
        try:
            socket.create_connection(ep, timeout=0.5).close()
        except OSError:
            return False
        if ep != self._ep and self._http is not None:
            self._http = None           # a new job, a new address
        self._ep = ep
        return True

    def state(self):
        from ..sched import ide
        rec = self.record()
        if rec is None:
            if os.path.exists(ide.req_path(self.key, self.home)):
                return "waiting for room in the pool (an IDE goes first in line)"
            return "not asked for"
        if rec.state == "PENDING":
            return "its job %s is waiting in the batch queue" % rec.ref
        return "VS Code is starting in job %s" % rec.ref

    async def ensure(self):
        from ..sched import ide
        async with self._lock:
            if not self._connectable():
                if self.record() is None and not os.path.exists(ide.req_path(self.key,
                                                                             self.home)):
                    await asyncio.get_running_loop().run_in_executor(None, self._start)
                else:
                    self.poke()
                end = self._clock() + WAIT_S
                while not self._connectable():
                    if self._clock() > end:
                        raise IdeWaiting(self.state())
                    await asyncio.sleep(0.1)
            self.proc = "job"
            self.last = self._clock()
            if self._idle is None or self._idle.done():
                self._idle = asyncio.ensure_future(self._idle_loop())

    def _start(self):
        from ..sched import authz, ide
        private_dirs(self.home, self.key)
        self.token()
        ide.request(self.key, self.size(), self.job_argv(), self.by or authz.principal_cli(),
                    self._target(), self.home)
        self.poke()
        log.info("asked for a job for VS Code's server %s", self.key)

    def _target(self):
        try:
            with open(os.path.join(self.dir, "target")) as fp:
                return fp.read()
        except OSError:
            return ""

    def _adopt(self):
        return False

    def _stop_now(self):
        from ..sched import control, ide
        self.proc = None
        ide.withdraw(self.key, self.home)
        got = control.cancel_jobs(lambda r: r.kind == "ide" and r.wpid == self.key, "wpkd",
                                  "IDE idle or closed", h=self.home, lost=False)
        if got:
            self.poke()
            log.info("stopped the job of VS Code's server %s", self.key)

    def stop(self):
        """With the board: the job keeps running; the next wpkd re-attaches."""
        if self._idle is not None:
            self._idle.cancel()

    def client(self):
        import httpx
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
        return self._http

    def url(self, path):
        host, port = self._ep or self.endpoint()
        return "http://%s:%d%s" % (host, port, path)

    def headers(self, headers):
        out = [(k, v) for k, v in upstream_headers(headers) if k != "cookie"]
        c = _cookies(headers.get("cookie"))
        out.append(("cookie", "; ".join(x for x in (c, "vscode-tkn=" + self.token()) if x)))
        return out

    async def ws_connect(self, path, host, hdrs):
        from websockets.asyncio.client import connect
        ep = self._ep or self.endpoint()
        sock = socket.create_connection(ep, timeout=10)
        sock.setblocking(False)
        hdrs = [(k, v) for k, v in hdrs if k.lower() != "cookie"] + [
            ("cookie", "; ".join(x for x in (dict(hdrs).get("cookie"),
                                             "vscode-tkn=" + self.token()) if x))]
        return await connect("ws://%s%s" % (host, path), sock=sock, additional_headers=hdrs,
                             max_size=None, open_timeout=10)


class Backends:
    """One ``Backend`` per target, under ``/ide/<key>/``. A target is registered
    when the board opens it; its directory remembers the path, so a page
    reloaded after the board restarts still finds its server."""

    def __init__(self, home, cfg, argv=None, clock=time.monotonic, slot=False, poke=None):
        """``slot``: servers run in scheduler jobs (``JobBackend``); ``poke`` wakes
        the dispatcher when one is asked for."""
        self.home = home
        self.cfg = cfg
        self._argv = argv           # tests: a fake backend
        self._clock = clock
        self.slot = slot
        self.poke = poke
        self.servers = {}
        self._lock = asyncio.Lock()

    def register(self, path, size=None):
        """The key for ``path``, its directory made. Blocking: call it off the loop.
        ``size``: the job size for a server in a slot (the Open menu's choice)."""
        key = key_for(path)
        private_dirs(self.home, key)
        if self.slot:
            sz = os.path.join(server_dir(self.home, key), "size")
            with open(sz + ".tmp", "w") as fp:
                fp.write(size or "")
            os.replace(sz + ".tmp", sz)
        t = os.path.join(server_dir(self.home, key), "target")
        try:
            with open(t) as fp:
                if fp.read() == os.path.abspath(path):
                    return key
        except OSError:
            pass
        with open(t + ".tmp", "w") as fp:
            fp.write(os.path.abspath(path))
        os.replace(t + ".tmp", t)
        return key

    def get(self, key):
        """The server for ``key``, or None if the board never opened it."""
        if not KEY.match(key or ""):
            return None
        be = self.servers.get(key)
        if be is None:
            if not os.path.isfile(os.path.join(server_dir(self.home, key), "target")):
                return None
            if self.slot:
                be = JobBackend(self.home, self.cfg, key, argv=self._argv, clock=self._clock,
                                poke=self.poke)
            else:
                be = Backend(self.home, self.cfg, key, argv=self._argv, clock=self._clock)
            self.servers[key] = be
        return be

    def target(self, key):
        try:
            with open(os.path.join(server_dir(self.home, key), "target")) as fp:
                return fp.read()
        except OSError:
            return None

    async def ensure(self, be):
        """``be`` is up; to start it, stop the least recently used idle server
        when ``[ide] max_servers`` already run."""
        if be.running():
            return await be.ensure()
        async with self._lock:
            limit = int(self.cfg.get("max_servers") or 8)
            others = [b for b in self.servers.values() if b is not be and b.running()]
            while len(others) >= limit:
                idle = [b for b in others if b.clients == 0]
                if not idle:
                    raise IdeUnavailable("%d VS Code servers are in use ([ide] max_servers); "
                                         "close one and reload" % len(others))
                lru = min(idle, key=lambda b: b.last)
                log.info("stopping VS Code's server %s to make room", lru.key)
                await asyncio.get_running_loop().run_in_executor(None, lru._stop_now)
                others.remove(lru)
            await be.ensure()

    def running(self):
        return [b for b in self.servers.values() if b.running()]

    def stop(self):
        """With the board. Call it on the board's event loop thread."""
        for b in self.servers.values():
            b.stop()


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


def key_of(path):
    """``/ide/<key>/...`` -> ``<key>``."""
    parts = path.split("/", 3)
    return parts[2] if len(parts) > 2 else ""


def cookie_path(value, base):
    """VS Code sets its cookies on ``Path=/``; scope them to this server's
    ``/ide/<key>`` so two servers do not overwrite each other's secret half."""
    return COOKIE_ROOT.sub(lambda m: m.group(1) + base, value)


WAITING = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5"><title>Waiting for room · VS Code</title></head>
<body style="font: 15px system-ui, sans-serif; margin: 3em; color: #444">
<h1 style="font-size: 20px">Waiting for room</h1>
<p>This VS Code runs in a job of the pool: %(why)s.</p>
<p>The page reloads every 5 s until it is up. <a href="/sched">The pool</a></p>
</body></html>
"""

GONE = ("404 this VS Code page is not open on the board; open it again from "
        "the project's page\n")


async def proxy_http(backends, request):
    from starlette.background import BackgroundTask
    from starlette.responses import PlainTextResponse, Response, StreamingResponse
    backend = backends.get(key_of(request.url.path))
    if backend is None:
        return PlainTextResponse(GONE, status_code=404)
    try:
        await backends.ensure(backend)
    except IdeWaiting as e:
        from starlette.responses import HTMLResponse
        return HTMLResponse(WAITING % {"why": str(e).replace("<", "&lt;")}, status_code=503,
                            headers={"retry-after": "5"})
    except IdeUnavailable as e:
        return PlainTextResponse("503 %s\n" % e, status_code=503)
    backend.last = backend._clock()
    url = backend.url(request.url.path + ("?" + request.url.query if request.url.query else ""))
    hc = backend.client()
    req = hc.build_request(request.method, url, headers=backend.headers(request.headers),
                           content=request.stream())
    try:
        r = await hc.send(req, stream=True)
    except Exception as e:          # httpx's transport errors
        return PlainTextResponse("502 VS Code's server: %s\n" % e, status_code=502)
    out = [(k.encode("latin-1"),
            (cookie_path(v, backend.base) if k.lower() == "set-cookie" else v)
            .encode("latin-1"))
           for k, v in r.headers.multi_items()
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


async def proxy_ws(backends, websocket):
    backend = backends.get(key_of(websocket.url.path))
    if backend is None:
        return await websocket.close(1008)
    try:
        await backends.ensure(backend)
    except IdeUnavailable as e:
        log.warning("web VS Code: %s", e)
        return await websocket.close(1011)
    path = websocket.url.path + ("?" + websocket.url.query if websocket.url.query else "")
    host = websocket.headers.get("host") or "localhost"
    hdrs = [(k, v) for k, v in upstream_headers(websocket.headers)
            if k.lower() in ("cookie", "origin", "user-agent", "accept-language")]
    try:
        up = await backend.ws_connect(path, host, hdrs)
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
        # First, before any await: if this task is cancelled while it cleans up
        # (the board stopping, a test client closing), the count must still drop.
        backend.clients -= 1
        backend.last = backend._clock()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await up.close()
        with contextlib.suppress(Exception):
            await websocket.close()
