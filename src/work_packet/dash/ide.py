"""Web VS Code under the board's ``/ide/`` (docs/vscode-plan.md §4, V3).

wpkd runs one VS Code server per target, straight from a release it keeps
(``ide_releases``; docs/ide-direct-server-plan.md), or the open-source
``openvscode-server`` (``[ide] backend``). Each listens on a unix socket with no
token and no port of its own, and wpkd proxies ``/ide/<key>/*`` to it. A target is what the board
opens: a packet's workspace file or a folder; ``key`` is a hash of its path.
Every request has already passed the board's ``Guard`` (identity, Host,
Origin), so the board's login is VS Code's.

A server starts on the first request, stops after ``[ide] idle_minutes`` with
no open WebSocket, and stops with the board. At most ``[ide] max_servers`` run
at once; the least recently used idle one makes room. Each runs in a session
of its own: ``code-server`` is a wrapper around a tree of processes, so it is
stopped by signalling the whole group (V0 finding 6). A server keeps the release
it started with; a newer one is used from its next start.
"""

import asyncio
import base64
import binascii
import contextlib
import hashlib
import html
import json
import logging
import os
import re
import signal
import sys
import socket
import subprocess
import time

from .. import ide_launch, ide_ports, ide_releases, ide_stranded, registry

log = logging.getLogger("wpk.dash")

BASE = "/ide"
QUALITY = ide_releases.QUALITY
PLATFORM = "{platform}"     # in a job's argv: the exec host's platform (sched/ide_job.py)
SUN_PATH_MAX = 100          # sockaddr_un.sun_path is 108 bytes; leave room
START_S = 15                # for the socket to appear (the server download comes after)
STOP_S = 5
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "te", "trailer",
       "proxy-authorization", "proxy-authenticate", "content-length", "host", "cookie",
       "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
       "x-real-ip", "via", "x-csrf-token"}
TRUST = (b"&quot;enableWorkspaceTrust&quot;:true", b"&quot;enableWorkspaceTrust&quot;:false")
# Localhost links from the workbench go through the board (port-forward plan §3.1).
SHIM = b'<script src="/static/ide_forward.js"></script>'
# Which tabs are open and seen (docs/collaboration.md §7.4): the presence beacon.
PRESENCE_SHIM = b'<script src="/static/ide_presence.js"></script>'
# The way to the desktop, and its "a window opened" toast (docs/desktop.md §6).
DESK_SHIM = b'<script src="/static/ide_desk.js"></script>'
OPEN = "/__wpk/open"
# Secret storage for the workbench (extension sign-ins), as `code serve-web` gave it
# (docs/ide-direct-server-plan.md §5): the page is told where to POST for its key.
MINT = "/_vscode-cli/mint-key"
SECRET_HALF = "vscode-cli-secret-half"
SERVE_WEB_HALF = os.path.expanduser("~/.vscode/cli/serve-web-key-half")
VIS = "/__wpk/vis"
FORWARD_HOLD_S = 300        # a server whose forwarded page was used this recently is not evicted
KEY = re.compile(r"[0-9a-f]{12}\Z")
COOKIE_ROOT = re.compile(r"(;\s*path=)/(?=\s*(;|$))", re.I)
# Installing a gallery extension in the browser fetches its files through the
# server's /web-extension-resource/<host>/<path>. serve-web 2c33b50 refuses every
# one (403 "Request Forbidden"): it takes the host from a path that still starts
# with "/", so the host is "" and never matches the gallery's. The proxy fetches
# them itself, from the hosts the stock product.json files name.
EXT_RESOURCE = re.compile(r"/ide/[0-9a-f]{12}/(?:[^/]+/)?web-extension-resource/([^/]+)/(.+)\Z")
EXT_HOSTS = re.compile(r"([a-z0-9-]+\.vscode-unpkg\.net|open-vsx\.org)\Z")
EXT_REQUEST_HEADERS = ("x-client-name", "x-client-version", "x-machine-id", "x-client-commit")
EXT_RESPONSE_HEADERS = ("cache-control", "content-type")


class Unforwardable(Exception):
    """A localhost link of this server cannot be forwarded: ``status``, and why."""

    def __init__(self, status, why):
        super().__init__(why)
        self.status = status


class IdeUnavailable(Exception):
    pass


def key_for(path):
    """The server for a target with no packet: a hash of its path."""
    return hashlib.sha256(os.fsencode(os.path.abspath(path))).hexdigest()[:12]


def key_for_packet(wpid):
    """The server of a packet: one per packet, whatever of it is open (its
    workspace, folder, worktree or clone; docs/ide-direct-server-plan.md §1)."""
    return hashlib.sha256(("packet:%s" % wpid).encode()).hexdigest()[:12]


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


def backend_kind(cfg):
    """``"server"`` (VS Code's server from ``ide_releases``) or
    ``"openvscode-server"``. ``"serve-web"`` is the old name of ``"server"``."""
    b = cfg.get("backend") or "server"
    return "openvscode-server" if b == "openvscode-server" else "server"


def command(cfg):
    """openvscode-server's program: ``[ide] code``, else ``openvscode-server``."""
    return cfg.get("code") or "openvscode-server"


def available(cfg, which=None):
    """Why web VS Code cannot run here, or None."""
    import shutil
    if backend_kind(cfg) == "server":
        try:
            ide_releases.platform()
        except ide_releases.ReleaseError as e:
            return str(e)
        return None
    which = which or shutil.which
    code = command(cfg)
    if which(code) is None:
        return "%r is not on PATH (install openvscode-server, or set [ide] code)" % code
    return None


def release_for(home, cfg, plat=None):
    """The release a server starting now runs: ``{commit, version, date}``.
    None and a get started when there is none yet (raise ``IdeWaiting`` then)."""
    r = ide_releases.current(home, cfg, plat)
    if r is None and not cfg.get("release"):
        with contextlib.suppress(ide_releases.ReleaseError, OSError):
            r = ide_releases.seed(home, plat)
    if r is None:
        ide_releases.start_get(home, plat)
    return r


def waiting_for_release(cfg, plat=None):
    """Why a server cannot start yet, with no release here."""
    hold = cfg.get("release")
    failed = ide_releases.last_failure(plat)
    if failed and not ide_releases.getting(plat):
        return "getting VS Code's server failed (%s); it is tried again" % failed[1]
    if hold:
        return "getting VS Code's server %s ([ide] release)" % hold
    return "getting VS Code's server (about 70 MB; once per release)"


def desk_view(home, cfg, wpid):
    """Packet ``wpid``'s web VS Code, for its page: None when none runs here,
    else ``{key, pid, commit, version, started, agents, terminals, newer}``;
    ``newer`` is the version a restart would bring, or None."""
    if backend_kind(cfg) != "server":
        return None
    own = key_for_packet(wpid)
    for key in [own] + [k for k in ide_stranded.desk_keys(home, wpid) if k != own]:
        srv = ide_stranded.servers(key)
        if not srv:
            continue
        cur = ide_launch.current(home, key) or {}
        kids = ide_stranded._children()
        main = next((x for x in srv if x["pid"] == cur.get("server_pid")), None) or \
            max(srv, key=lambda x: (ide_stranded.agents_under(x["pid"], kids), x["start"]))
        r = ide_releases.find(home, main["commit"]) or \
            ide_releases.info(os.path.join(ide_releases.SERVE_WEB_CACHE, main["commit"])) or {}
        version = r.get("version") or cur.get("version") or main["commit"][:7]
        new = ide_releases.current(home, cfg)
        newer = new["version"] if new and new["commit"] != main["commit"] and \
            ide_releases.vkey(new["version"]) >= ide_releases.vkey(version) else None
        return dict(ide_stranded.inside(main["pid"], kids), key=key, pid=main["pid"],
                    commit=main["commit"], version=version, newer=newer,
                    started=ide_stranded.started_at(main["pid"]))
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
        self._fwd_http = None
        self.forwarded = float("-inf")      # when a forwarded page was last used
        self.stranded = []          # servers of this desk no tab reaches (ide_stranded)
        self.server_pid = None      # the server-main we proxy to, when found in /proc
        self._busy_logged = False

    # -- the process ---------------------------------------------------------

    def program(self, release):
        """The server's program: the release's ``code-server``, or openvscode-server."""
        if backend_kind(self.cfg) == "server":
            return ide_releases.binary(self.home, release["commit"])
        return command(self.cfg)

    def argv(self, release=None):
        if self._argv is not None:
            return list(self._argv) + [self.sock, self.base]
        return [self.program(release),
                "--socket-path", self.sock, "--server-base-path", self.base,
                "--without-connection-token", "--accept-server-license-terms",
                "--server-data-dir", self.data]

    def _release(self):
        """The release to start, or raise ``IdeWaiting`` while it is got."""
        if self._argv is not None or backend_kind(self.cfg) != "server":
            return None
        r = release_for(self.home, self.cfg)
        if r is None:
            raise IdeGetting(waiting_for_release(self.cfg))
        return r

    def _connectable(self):
        return _answers(self.sock)

    # -- one server per desk (docs/ide-direct-server-plan.md §2) --------------

    def _scans(self):
        """VS Code's own server is found in /proc by its WPK_IDE_KEY; a fake
        or openvscode-server is known by ``serve.pid`` only."""
        return self._argv is None and backend_kind(self.cfg) == "server"

    def _live(self):
        """This desk's servers on this host, each with ``answers`` and ``agents``."""
        if not self._scans():
            return []
        kids = ide_stranded._children()
        out = []
        for srv in ide_stranded.servers(self.key):
            srv["answers"] = bool(srv["socket"]) and _answers(srv["socket"])
            srv["agents"] = ide_stranded.agents_under(srv["pid"], kids)
            out.append(srv)
        return out

    def _find(self):
        """Take over a server of this desk that is running already: the one with
        agents in it, else the newest. True when there is one. ``IdeStuck`` when
        one runs but does not answer: a second is never started beside it."""
        live = self._live()
        up = [s for s in live if s["answers"]]
        if not up:
            if live:
                raise IdeStuck("VS Code's server for this desk (pid %d) is running but "
                               "does not answer" % live[-1]["pid"], [s["pid"] for s in live])
            return False
        best = max(up, key=lambda s: (s["agents"], s["start"]))
        self._take(best)
        return True

    def _take(self, srv):
        if srv["socket"] != self.sock:
            log.info("VS Code's server %s: using pid %d on %s, past serve-web", self.key,
                     srv["pid"], srv["socket"])
        self._use_socket(srv["socket"])
        leader = self._pidfile()
        self.proc = leader if leader and srv["socket"] == socket_path(self.home, self.key) \
            and _alive(leader) else srv["pid"]
        self.server_pid = srv["pid"]
        cur = ide_launch.current(self.home, self.key) or {}
        rel = "%s-%s" % (QUALITY, srv["commit"])
        if cur.get("launch_id") and cur.get("launch_id") == srv.get("launch") and \
                not cur.get("ended"):
            if cur.get("server_pid") != srv["pid"] or cur.get("release") != rel:
                ide_launch.update(self.home, self.key, cur["launch_id"], server_pid=srv["pid"],
                                  release=rel)
        else:           # a server whose launch we have no record of: give it one
            lid = ide_launch.start(self.home, self.key, self._target(), "local")
            ide_launch.update(self.home, self.key, lid, pid=srv["pid"], server_pid=srv["pid"],
                              release=rel, adopted=True)

    def _use_socket(self, path):
        if path != self.sock:
            self.sock = path
            self._http = None           # the client is bound to a socket

    def _pidfile(self):
        try:
            with open(self.pid_path) as fp:
                return int(fp.read().split()[0])
        except (OSError, ValueError, IndexError):
            return None

    @contextlib.contextmanager
    def _starting(self):
        """Only one board starts this desk's server at a time (the lock is not
        inherited: a server is found by its WPK_IDE_KEY, not by the lock)."""
        import fcntl
        private_dirs(self.home, self.key)
        with open(os.path.join(self.dir, "start.lock"), "a") as fp:
            end = time.monotonic() + START_S
            while True:
                try:
                    fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > end:
                        raise IdeUnavailable("another board is starting this desk's server")
                    time.sleep(0.1)
            try:
                yield
            finally:
                fcntl.flock(fp, fcntl.LOCK_UN)

    async def ensure(self):
        """The backend is up (started now, or already)."""
        async with self._lock:
            if self.running() and self._connectable():
                return
            if self.proc is None and await asyncio.get_running_loop().run_in_executor(
                    None, self._adopt):
                log.info("using VS Code's server %s left by an earlier board, pid %d",
                         self.key, self.proc)
            else:
                await asyncio.get_running_loop().run_in_executor(None, self._start_one)
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

    def _start_one(self):
        """Start the server, unless one of this desk's is found running now."""
        if not self._scans():
            return self._start()
        with self._starting():
            if self._find():
                return
            self._start()

    def _start(self):
        rel = self._release()
        self._use_socket(socket_path(self.home, self.key))
        self.server_pid = None
        private_dirs(self.home, self.key)
        private_dir(os.path.dirname(self.sock))
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.sock)
        out = open(self.log_path, "ab")
        lid = ide_launch.start(self.home, self.key, self._target(), "local")
        argv = self.argv(rel)
        try:
            self.proc = subprocess.Popen(self.with_desktop(argv), stdin=subprocess.DEVNULL,
                                         stdout=out,
                                         stderr=subprocess.STDOUT, start_new_session=True,
                                         env=dict(os.environ, **ide_launch.env(lid, self.key)))
        except OSError as e:
            ide_launch.update(self.home, self.key, lid, ended=time.time())
            raise IdeUnavailable("cannot start %s: %s" % (argv[0], e)) from None
        finally:
            out.close()
        with open(self.pid_path, "w") as fp:
            fp.write("%d\n" % self.proc.pid)
        extra = {"release": "%s-%s" % (QUALITY, rel["commit"]), "version": rel["version"]} \
            if rel else {}
        ide_launch.update(self.home, self.key, lid, pid=self.proc.pid, **extra)
        log.info("started VS Code's server %s%s, pid %d", self.key,
                 " (%s)" % rel["version"] if rel else "", self.proc.pid)

    def _target(self):
        try:
            with open(os.path.join(self.dir, "target")) as fp:
                return fp.read()
        except OSError:
            return ""

    # -- the desktop (docs/desktop.md) ---------------------------------------

    desk_ok = True              # this kind of server can carry a desktop

    def with_desktop(self, argv):
        """``argv`` under xproxy when ``[desktop] enabled``: the server, and all
        it starts, gets a DISPLAY. Its settings are read now, at each start."""
        from .. import desktop
        try:
            cfg = desktop.load_config(self.home)
        except registry.ConfigError:
            return argv
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(self.dir, desktop.STATE))
        if not (cfg.get("enabled") and self.desk_ok):
            return argv
        desktop.write_conf(self.dir, cfg, title=desktop.label(self.home, self.key, self._target()),
                           cwd=desktop.workdir(self._target()))
        return desktop.wrap(self.dir, self.key, argv)

    def desk_state(self):
        """xproxy's report while it serves, else None."""
        from .. import desktop
        return desktop.live(self.dir) if self.desk_ok else None

    async def desk_connect(self):
        """A byte stream to the desktop's VNC (xproxy starts X on it)."""
        st = self.desk_state()
        if st is None:
            raise IdeUnavailable("no desktop: the server isn't running with one")
        return await asyncio.open_unix_connection(st["vnc"])

    def running(self):
        p = self.proc
        if p is None:
            return False
        if isinstance(p, int):
            return _alive(p)
        return p.poll() is None

    def _adopt(self):
        """A server an earlier board started (and did not stop: it crashed) is
        still answering on our socket: take it over, so it stops when idle.
        VS Code's own server is found by its WPK_IDE_KEY, wherever it listens
        (one serve-web started has its own socket)."""
        if self._scans():
            if self._find():
                return True
            self._end_serve_web()
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
        # The agents in its terminals are in sessions of their own, out of the
        # group: found now, while their servers still are, ended after it.
        left = ide_stranded.targets([s["pid"] for s in ide_stranded.servers(self.key)])
        # The group wpkd started (xproxy, the server's wrapper): ours, or the one
        # serve.pid names when the server was taken over (serve-web's launcher).
        groups = [g for g in {pid, self._pidfile()} if g and _leads(g)]
        for g in groups:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(g, signal.SIGTERM)
        if not _wait(p, STOP_S):
            for g in groups:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(g, signal.SIGKILL)
            _wait(p, STOP_S)
        if left:
            ide_stranded.end(left)
        self.server_pid = None
        with contextlib.suppress(OSError):
            os.unlink(self.pid_path)
        cur = ide_launch.current(self.home, self.key)
        if cur is not None and cur.get("pid") == pid and not cur.get("ended"):
            ide_launch.update(self.home, self.key, cur["launch_id"], ended=time.time())
        log.info("stopped VS Code's server %s", self.key)

    def detach(self):
        """Let go of the server and leave it running, with its pid file and
        socket, for the image an in-place restart execs into to adopt."""
        if self._idle is not None:
            self._idle.cancel()
        self.proc = None

    async def adopt(self):
        """At the board's start: take over a server an earlier board left
        (restarted or crashed), so its idle timer runs even if no tab comes
        back. A dead one's files are cleared and its launch ended."""
        async with self._lock:
            if self.proc is not None:
                return self.running()
            try:
                found = self._adopt()
            except IdeUnavailable as e:         # stuck: its page offers to end it
                log.warning("VS Code's server %s: %s", self.key, e)
                return False
            if found:
                log.info("using VS Code's server %s left by an earlier board, pid %d",
                         self.key, self.proc)
                self.last = self._clock()
                if self._idle is None or self._idle.done():
                    self._idle = asyncio.ensure_future(self._idle_loop())
                return True
            self._clear_leftover()
            return False

    def _end_serve_web(self):
        """A ``code serve-web`` launcher an older wpk left, with no server under
        it: ended, not taken over (it would start one of its own choosing)."""
        pid = self._pidfile()
        if not (pid and _alive(pid) and _leads(pid)):
            return
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as fp:
                argv = fp.read().split(b"\0")
        except OSError:
            return
        if b"serve-web" not in argv:
            return
        log.info("VS Code's server %s: ending the old serve-web launcher %d", self.key, pid)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGTERM)
        if not _wait(pid, STOP_S):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            os.unlink(self.pid_path)

    def end(self):
        """End this desk's server(s), and the agents in them, now: Restart, or a
        stuck server. Blocking."""
        if self.proc is None and self._scans():
            with contextlib.suppress(IdeUnavailable):
                self._find()
        self._stop_now()
        rest = ide_stranded.servers(self.key) if self._scans() else []
        if rest:
            ide_stranded.end(ide_stranded.targets([s["pid"] for s in rest]))
        with contextlib.suppress(OSError):
            os.unlink(self.pid_path)

    def _clear_leftover(self):
        try:
            with open(self.pid_path) as fp:
                pid = int(fp.read().split()[0])
        except (OSError, ValueError, IndexError):
            return
        if _alive(pid):
            return                       # not answering on our socket: not ours to touch
        for p in (self.pid_path, self.sock):
            with contextlib.suppress(OSError):
                os.unlink(p)
        cur = ide_launch.current(self.home, self.key)
        if cur is not None and cur.get("pid") == pid and not cur.get("ended"):
            ide_launch.update(self.home, self.key, cur["launch_id"], ended=time.time())

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
            if self._scans():
                await asyncio.get_running_loop().run_in_executor(None, self.check_split)
            if self.clients == 0 and self._clock() - self.last > limit:
                loop = asyncio.get_running_loop()
                if await loop.run_in_executor(None, self._busy):
                    continue        # an agent works in it: idle is not unused
                await loop.run_in_executor(None, self._stop_now)

    def _busy(self):
        """An agent (claude, codex) runs in this desk's server: idle stop leaves
        it be (docs/ide-direct-server-plan.md §6)."""
        if not self._scans():
            return False
        kids = ide_stranded._children()
        n = sum(ide_stranded.agents_under(s["pid"], kids) for s in ide_stranded.servers(self.key))
        if n and not self._busy_logged:
            log.info("VS Code's server %s is idle, but %d agent session(s) run in it: "
                     "it keeps running", self.key, n)
        self._busy_logged = bool(n)
        return bool(n)

    def release(self):
        """The release this launch runs (``stable-<commit>``), or None."""
        return (ide_launch.current(self.home, self.key) or {}).get("release")

    def check_split(self):
        """Look for servers of this desk no tab reaches (``self.stranded``)."""
        try:
            got = ide_stranded.stranded(self.key, self.release(), keep_pid=self.server_pid)
        except OSError:
            return
        new = {s["pid"] for s in got} - {s["pid"] for s in self.stranded}
        for s in got:
            if s["pid"] in new:
                log.warning("VS Code's server %s: server %d (%s) is stranded, with %d "
                            "agent session(s) in it", self.key, s["pid"], s["commit"][:7],
                            len(s["agents"]))
        self.stranded = got

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

    # -- localhost links (port-forward plan §3.4) ----------------------------

    def forward_identity(self):
        """What a forward token is bound to: this server process. A new one has
        other ports, so its tokens die with it. None when it is not running."""
        if not self.running():
            return None
        return self.proc if isinstance(self.proc, int) else self.proc.pid

    def forward(self, port):
        """``(client, origin, extensions)`` for a request to ``localhost:<port>``
        where this server runs; raises ``Unforwardable``. Checked on every request."""
        import httpx
        host, why = ide_ports.check(port)
        if host is None:
            raise Unforwardable(403, why)
        if self._fwd_http is None:
            self._fwd_http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
        return self._fwd_http, "http://%s:%d" % ("[%s]" % host if ":" in host else host,
                                                port), {}


class IdeWaiting(IdeUnavailable):
    """The server's job has no room or has not started yet: the page waits."""


class IdeGetting(IdeWaiting):
    """No VS Code release here yet: one is being got."""


class IdeStuck(IdeUnavailable):
    """The desk's server runs but does not answer: the page offers to end it."""

    def __init__(self, msg, pids=()):
        super().__init__(msg)
        self.pids = list(pids)


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

    transport = "tcp-token"         # ide_job --transport

    def listen_argv(self, fake):
        """Where the server listens, in its argv (``fake``: tests' fake server,
        which takes ``<socket> <base>`` first)."""
        tok = ["--host", "0.0.0.0", "--port", "{port}", "--connection-token-file",
               self.token_path]
        return ["-", self.base] + tok if fake else tok

    def _prepare(self):
        """What the job needs from wpkd before it is asked for."""
        self.token()

    def job_argv(self, launch_id=None, release=None):
        import sys
        if self._argv is not None:
            srv = list(self._argv) + self.listen_argv(True)
        else:
            # The release is on the filesystem the exec host shares with wpkd
            # (beside ide/servers/), for the host's platform: ide_job fills in
            # {platform}, and gets that build when it is not there yet.
            prog = ide_releases.binary(self.home, release["commit"], PLATFORM) \
                if release else self.program(release)
            srv = [prog] + self.listen_argv(False) + [
                "--server-base-path", self.base, "--accept-server-license-terms",
                "--server-data-dir", self.data]
        srv = self.with_desktop(srv)
        opts = ["--transport", self.transport] if self.transport != "tcp-token" else []
        if launch_id:
            opts += ["--launch", launch_id]
            if self.cfg.get("sessions", True):     # watch its sessions, there
                opts += ["--collect", str(self.cfg.get("sessions_poll_s") or 5)]
        return [sys.executable, "-m", "work_packet.sched.ide_job", self.dir] + opts + ["--"] + srv

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
        self._prepare()
        if not os.path.exists(ide.req_path(self.key, self.home)):    # else asked already
            rel = self._release()
            lid = ide_launch.start(self.home, self.key, self._target(), "job")
            if rel:
                ide_launch.update(self.home, self.key, lid, release="%s-%s" % (
                    QUALITY, rel["commit"]), version=rel["version"])
            ide.request(self.key, self.size(), self.job_argv(lid, rel),
                        self.by or authz.principal_cli(), self._target(), self.home,
                        launch=lid)
        self.poke()
        log.info("asked for a job for VS Code's server %s (%s)", self.key, self.transport)

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

    desk_ok = False             # a plaintext port carries only VS Code (mtls carries both)

    def forward_identity(self):
        return None

    def forward(self, port):
        # The extension's port is on the exec host's loopback; this transport
        # reaches only the server's own plaintext port.
        raise Unforwardable(501, 'forwarding localhost links needs [sched.ide] transport = '
                                 '"mtls"; this board uses "tcp-token"')

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


class MtlsJobBackend(JobBackend):
    """The job-backed server over **mutually pinned TLS** (docs/scheduler.md §8.1):
    VS Code's server listens on a unix socket in the job; ``ide_relay`` accepts
    only wpkd's client certificate and splices to it. Nothing listens in plaintext
    on the exec host, and there is no connection token to leak: the certificates
    are the authentication, and both travel only through the user's own 0700
    directory."""

    transport = "mtls"

    def __init__(self, home, cfg, key, argv=None, clock=time.monotonic, poke=None, by=None):
        super().__init__(home, cfg, key, argv=argv, clock=clock, poke=poke, by=by)
        self._ctx = None
        self._pin = None            # the job certificate's fingerprint the context was made for
        self._fwd = {}              # port -> client: httpx pools by host and port, not by SNI

    def listen_argv(self, fake):
        if fake:
            return ["{sock}", self.base]
        return ["--socket-path", "{sock}", "--without-connection-token"]

    def _prepare(self):
        """Publish wpkd's (public) client certificate for the job to pin."""
        import shutil
        from ..sched import ide_tls
        _, crt = ide_tls.client_cert(self.home)
        dst = os.path.join(self.dir, "client.crt")
        shutil.copyfile(crt, dst + ".tmp")
        os.chmod(dst + ".tmp", 0o600)
        os.replace(dst + ".tmp", dst)

    def _context(self):
        """The TLS context pinned to the job's current certificate, or None."""
        from ..sched import ide_tls
        server_crt = os.path.join(self.dir, "server.crt")
        try:
            fp = ide_tls.fingerprint(server_crt)
        except (OSError, ValueError):
            return None
        if self._ctx is None or self._pin != fp:
            key, crt = ide_tls.client_cert(self.home)
            self._ctx = ide_tls.pinned_client_context(crt, key, server_crt)
            self._pin, self._http, self._fwd = fp, None, {}     # a new job, a new certificate
        return self._ctx

    def _connectable(self):
        import ssl
        ep = self.endpoint()
        ctx = self._context() if ep else None
        if ep is None or ctx is None:
            return False
        try:                          # a real handshake: the port may be open before the relay serves
            s = socket.create_connection(ep, timeout=1.0)
            try:
                ctx.wrap_socket(s, server_hostname=ep[0]).close()
            except BaseException:
                s.close()
                raise
        except (OSError, ssl.SSLError):
            return False
        if ep != self._ep and self._http is not None:
            self._http = None
        if ep != self._ep:
            self._fwd = {}
        self._ep = ep
        return True

    def client(self):
        import httpx
        if self._http is None:
            self._http = httpx.AsyncClient(verify=self._context(), timeout=httpx.Timeout(60.0, connect=5.0))
        return self._http

    def forward_identity(self):
        """The job's certificate: a new job is new processes, with other ports."""
        return self._pin if self._context() is not None else None

    def forward(self, port):
        """Through the relay, with the port in the TLS server name; the relay
        checks the port (``ide_ports``) on the exec host."""
        import httpx
        try:
            with open(os.path.join(self.dir, "features")) as fp:
                ok = "fwd-sni" in fp.read().split()
        except OSError:
            ok = False
        if not ok:
            raise Unforwardable(501, "this IDE job's relay is older than forwarding; "
                                     "close the IDE and open it again to restart its job")
        ep, ctx = self._ep or self.endpoint(), self._context()
        if ep is None or ctx is None:
            raise Unforwardable(502, "the IDE's job is not running")
        if port not in self._fwd:
            self._fwd[port] = httpx.AsyncClient(verify=ctx, timeout=httpx.Timeout(60.0, connect=5.0))
        return self._fwd[port], "https://%s:%d" % ep, {"sni_hostname": "p%d.fwd.wpk" % port}

    def url(self, path):
        host, port = self._ep or self.endpoint()
        return "https://%s:%d%s" % (host, port, path)

    desk_ok = True

    async def desk_connect(self):
        """Through the relay, with ``vnc.wpk`` as the TLS server name."""
        if self.desk_state() is None:
            raise IdeUnavailable("no desktop: the job's server isn't running with one")
        try:
            with open(os.path.join(self.dir, "features")) as fp:
                ok = "vnc-sni" in fp.read().split()
        except OSError:
            ok = False
        if not ok:
            raise IdeUnavailable("this IDE job's relay is older than the desktop; close the "
                                 "IDE and open it again to restart its job")
        ep, ctx = self._ep or self.endpoint(), self._context()
        if ep is None or ctx is None:
            raise IdeUnavailable("the IDE's job is not running")
        return await asyncio.open_connection(ep[0], ep[1], ssl=ctx, server_hostname="vnc.wpk")

    def headers(self, headers):
        return upstream_headers(headers)

    async def ws_connect(self, path, host, hdrs):
        from websockets.asyncio.client import connect
        ep = self._ep or self.endpoint()
        sock = socket.create_connection(ep, timeout=10)
        sock.setblocking(False)
        # The browser's Host goes in the URI (as for the unix socket); the certificate is the check.
        return await connect("wss://%s%s" % (host, path), sock=sock, ssl=self._context(),
                             server_hostname=ep[0], additional_headers=hdrs, max_size=None,
                             open_timeout=10)


class Backends:
    """One ``Backend`` per target, under ``/ide/<key>/``. A target is registered
    when the board opens it; its directory remembers the path, so a page
    reloaded after the board restarts still finds its server."""

    def __init__(self, home, cfg, argv=None, clock=time.monotonic, slot=False, poke=None,
                 transport="tcp-token"):
        """``slot``: servers run in scheduler jobs (``JobBackend``); ``poke`` wakes
        the dispatcher when one is asked for. ``transport`` (``[sched.ide]``): how
        wpkd reaches a job's server, ``tcp-token`` or ``mtls`` (``MtlsJobBackend``)."""
        self.home = home
        self.cfg = cfg
        self._argv = argv           # tests: a fake backend
        self._clock = clock
        self.slot = slot
        self.poke = poke
        self.transport = transport
        self.servers = {}
        self._lock = asyncio.Lock()

    async def restart(self, key):
        """End desk ``key``'s server and start it again, on the newest release."""
        be = self.get(key)
        if be is None:
            raise IdeUnavailable("no VS Code server %s" % key)
        async with be._lock:
            await asyncio.get_running_loop().run_in_executor(None, be.end)
        await self.ensure(be)
        return be

    async def keep_releases(self, first_s=60):
        """Get each new VS Code release ahead of time, every ``[ide] check_hours``,
        and drop the ones no desk runs (docs/ide-direct-server-plan.md §3)."""
        hours = float(self.cfg.get("check_hours") or 0)
        if not self.cfg.get("web") or backend_kind(self.cfg) != "server" or hours <= 0:
            return
        await asyncio.sleep(first_s)
        loop = asyncio.get_running_loop()
        while True:
            try:
                await loop.run_in_executor(None, self.update_releases)
            except Exception:           # noqa: BLE001: offline, a bad archive: next time
                log.warning("VS Code's releases: %s", sys.exc_info()[1])
            await asyncio.sleep(hours * 3600)

    def update_releases(self):
        if not self.cfg.get("release"):
            r = ide_releases.check(self.home)
            log.info("VS Code's newest release is %s (%s)", r["version"], r["commit"][:7])
        cur = ide_releases.current(self.home, self.cfg)
        keep = {cur["commit"]} if cur else set()
        keep |= {s["commit"] for s in ide_stranded.all_servers()}
        gone = ide_releases.gc(self.home, keep)
        if gone:
            log.info("removed VS Code release(s) no desk runs: %s",
                     " ".join(c[:7] for c in gone))

    def register(self, path, size=None, project=None, wpid=None, by=None):
        """The key of the server that opens ``path``, its directory made. Blocking:
        call it off the loop. A packet (``wpid``) has one server, whatever of it
        ``path`` is: the page opens ``path`` in it through its URL.
        ``size``: the job size for a server in a slot (the Open menu's choice).
        ``project``, ``wpid``, ``by``: who is opening it, kept in ``opens.jsonl``
        so a harness session in the editor can be tied to its packet."""
        key = key_for_packet(wpid) if wpid else key_for(path)
        if wpid:
            key = self._legacy(key, wpid) or key
        try:
            return self._register(key, path, size)
        finally:
            if project or wpid or by:
                ide_launch.record_open(self.home, key, project, wpid, by)

    def _legacy(self, key, wpid):
        """A desk this packet opened before desks were per packet (keyed by a
        path), whose server still runs: it keeps serving the packet until it
        stops, so its terminals and sessions are not left behind (§7)."""
        if self.slot or backend_kind(self.cfg) != "server" or ide_stranded.servers(key):
            return None
        best = None
        for k in ide_stranded.desk_keys(self.home, wpid):
            if k == key:
                continue
            srv = ide_stranded.servers(k)
            if srv:
                n = sum(ide_stranded.agents_under(x["pid"]) for x in srv)
                if best is None or n > best[0]:
                    best = (n, k)
        return best and best[1]

    def _register(self, key, path, size):
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
                cls = MtlsJobBackend if self.transport == "mtls" else JobBackend
                be = cls(self.home, self.cfg, key, argv=self._argv, clock=self._clock,
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
                now = self._clock()
                loop = asyncio.get_running_loop()
                idle = [b for b in others
                        if b.clients == 0 and now - b.forwarded > FORWARD_HOLD_S and
                        not await loop.run_in_executor(None, b._busy)]
                if not idle:
                    raise IdeUnavailable("%d VS Code servers are in use, by tabs or agent "
                                         "sessions ([ide] max_servers); close one and reload"
                                         % len(others))
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

    def detach(self):
        """An in-place restart: every server is left running, for the next
        image to adopt (``adopt``). Job servers are left anyway."""
        for b in self.servers.values():
            b.detach()
        self.servers.clear()

    async def adopt(self):
        """Take over the local servers an earlier board left running: their
        idle timers and ``max_servers`` count from now. Returns their keys."""
        if self.slot:
            return []                   # job servers re-attach through their records
        root = os.path.join(self.home, "ide", "servers")
        try:
            keys = sorted(k for k in os.listdir(root) if KEY.match(k)
                          and os.path.exists(os.path.join(root, k, "serve.pid")))
        except OSError:
            return []
        got = []
        for k in keys:
            be = self.get(k)
            if be is not None and await be.adopt():
                got.append(k)
        return got


def _leads(pid):
    """``pid`` runs and leads its own process group (one wpkd started)."""
    try:
        return os.getpgid(pid) == pid
    except OSError:
        return False


def _answers(path):
    """Something accepts connections on unix socket ``path``."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.connect(path)
        return True
    except OSError:
        return False
    finally:
        s.close()


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
            if fp.read().rpartition(")")[2].split()[0] != "Z":
                return True
    except (OSError, IndexError):
        return True
    # An adopted server is our child after an in-place restart (restart.py), with
    # no Popen to reap it.
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
    return False


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


def server_half(home, serve_web=SERVE_WEB_HALF):
    """The server's half of the workbench's secret key: serve-web's own when it
    left one (so what it stored still opens), else one made here. 32 bytes."""
    p = os.path.join(home, "ide", "secret-half")
    with contextlib.suppress(OSError, ValueError):
        with open(p) as fp:
            raw = base64.b64decode(fp.read().strip(), validate=True)
        if len(raw) == 32:
            return raw
    raw = None
    with contextlib.suppress(OSError, ValueError, binascii.Error):
        with open(serve_web) as fp:
            got = json.load(fp)
        raw = base64.urlsafe_b64decode(got + "=" * (-len(got) % 4))
        if len(raw) != 32:
            raw = None
    raw = raw or os.urandom(32)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fp:
        fp.write(base64.b64encode(raw).decode() + "\n")
    os.replace(p + ".tmp", p)
    return raw


def _client_half(header):
    """The browser's half (the HttpOnly cookie), or None."""
    for c in (header or "").split(";"):
        k, _, v = c.strip().partition("=")
        if k == SECRET_HALF and v:
            with contextlib.suppress(ValueError, binascii.Error):
                raw = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))
                if len(raw) == 32:
                    return raw
    return None


def secret_cookies(base, half=None):
    """The Set-Cookie values that tell the page where its key is (and give the
    browser its half when it has none), scoped to this server."""
    out = ["vscode-secret-key-path=%s%s; SameSite=Strict; Path=%s" % (base, MINT, base)]
    if half is not None:
        out.append("%s=%s; SameSite=Strict; HttpOnly; Max-Age=2592000; Path=%s"
                   % (SECRET_HALF, base64.urlsafe_b64encode(half).decode(), base))
    return out


def mints(backend):
    """The board answers ``mint-key`` for VS Code's own server (openvscode-server
    keeps its secrets its own way)."""
    return backend_kind(backend.cfg) == "server"


async def mint_key(backend, request):
    """``POST <base>/_vscode-cli/mint-key``: the 32-byte key, SHA-256 of the
    server's half and the browser's (serve-web's recipe)."""
    from starlette.responses import Response
    if request.method != "POST":
        return Response(status_code=405)
    srv = await asyncio.get_running_loop().run_in_executor(None, server_half, backend.home)
    half = _client_half(request.headers.get("cookie"))
    new = half is None
    half = half or os.urandom(32)
    resp = Response(hashlib.sha256(srv + half).digest(), media_type="application/octet-stream")
    resp.raw_headers += [(b"set-cookie", c.encode("latin-1"))
                         for c in secret_cookies(backend.base, half if new else None)]
    return resp


def cookie_path(value, base):
    """VS Code sets its cookies on ``Path=/``; scope them to this server's
    ``/ide/<key>`` so two servers do not overwrite each other's secret half."""
    return COOKIE_ROOT.sub(lambda m: m.group(1) + base, value)


def ext_resource_url(path):
    """``/ide/<key>/<quality-commit>/web-extension-resource/<host>/<path>`` ->
    ``https://<host>/<path>``, for a gallery host only (``EXT_RESOURCE``);
    else None."""
    m = EXT_RESOURCE.match(path)
    if not m or not EXT_HOSTS.match(m.group(1).lower()) or \
            ".." in m.group(2).split("/"):
        return None
    return "https://%s/%s" % (m.group(1).lower(), m.group(2))


async def ext_resource(url, headers, transport=None):
    """What VS Code's server would have sent for ``url``: its body, status,
    Cache-Control and Content-Type."""
    import httpx
    from starlette.responses import PlainTextResponse, Response
    send = {k: headers[k] for k in EXT_REQUEST_HEADERS if k in headers}
    try:
        async with httpx.AsyncClient(transport=transport, follow_redirects=True,
                                     timeout=httpx.Timeout(60.0, connect=10.0)) as hc:
            r = await hc.get(url, headers=send)
    except Exception as e:          # httpx's transport errors
        log.warning("extension resource %s: %s", url, e)
        return PlainTextResponse("502 %s: %s\n" % (url, e), status_code=502)
    if r.status_code != 200:
        return PlainTextResponse(r.text or "Request failed with status %d" % r.status_code,
                                 status_code=r.status_code)
    return Response(r.content, headers={k: r.headers[k] for k in EXT_RESPONSE_HEADERS
                                        if k in r.headers})


WAITING = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5"><title>Waiting for room · VS Code</title></head>
<body style="font: 15px system-ui, sans-serif; margin: 3em; color: #444">
<h1 style="font-size: 20px">Waiting for room</h1>
<p>This VS Code runs in a job of the pool: %(why)s.</p>
<p>The page reloads every 5 s until it is up. <a href="/sched">The pool</a></p>
</body></html>
"""

GETTING = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5"><title>Getting VS Code</title></head>
<body style="font: 15px system-ui, sans-serif; margin: 3em; color: #444">
<h1 style="font-size: 20px">Getting VS Code</h1>
<p>The board is %(why)s.</p>
<p>The page reloads every 5 s until it is up.</p>
</body></html>
"""

STUCK = """<!doctype html><html><head><meta charset="utf-8"><title>VS Code is not answering</title></head>
<body style="font: 15px system-ui, sans-serif; margin: 3em; color: #444">
<h1 style="font-size: 20px">VS Code is not answering</h1>
<p>%(why)s. The board does not start a second one beside it: its terminals and
agent sessions would be cut off from you.</p>
<form method="post" action="%(base)s/__wpk/restart">
<input type="hidden" name="back" value="%(back)s">
<p>Ending it also ends what runs in its terminals.
<button>End it and start VS Code again</button></p>
</form>
<p><a href="%(back)s">Try again</a></p>
</body></html>
"""
RESTART = "/__wpk/restart"

GONE = ("404 this VS Code page is not open on the board; open it again from "
        "the project's page\n")


def rewrite_workbench(body, trust_off, shim, presence=False, desk=False):
    """VS Code's HTML: the workspace-trust prompt off (V0 finding 4), and on the
    workbench page the localhost-link shim ahead of its first script, so it wraps
    ``window.open`` before ``workbench.js`` loads (port-forward plan §3.1), and
    the presence beacon (docs/collaboration.md §7.4)."""
    if trust_off:
        body = body.replace(*TRUST)
    add = (SHIM if shim else b"") + (PRESENCE_SHIM if presence else b"") + \
        (DESK_SHIM if desk else b"")
    if add:
        i = body.find(b"<script")
        if i >= 0:
            body = body[:i] + add + body[i:]
    return body


async def restart_page(backends, backend, request):
    """``POST <base>/__wpk/restart`` from the not-answering page: end the desk's
    server(s), start it again, back to the page that was asked for."""
    from starlette.responses import RedirectResponse, Response
    if request.method != "POST":
        return Response(status_code=405)
    form = await request.form()
    back = str(form.get("back") or "")
    if not (back == backend.base or back.startswith(backend.base + "/")) or "\\" in back:
        back = backend.base + "/"
    async with backend._lock:
        await asyncio.get_running_loop().run_in_executor(None, backend.end)
    log.warning("VS Code's server %s: ended from its page, to start again", backend.key)
    return RedirectResponse(back, status_code=303)


async def proxy_http(backends, request):
    from starlette.background import BackgroundTask
    from starlette.responses import PlainTextResponse, Response, StreamingResponse
    backend = backends.get(key_of(request.url.path))
    if backend is None:
        return PlainTextResponse(GONE, status_code=404)
    if request.url.path == backend.base + OPEN:
        from . import ide_forward
        return await ide_forward.open_link(backends, backend, request)
    if request.url.path == backend.base + VIS:
        return await visibility(backend, request)
    if request.url.path == backend.base + MINT and mints(backend):
        return await mint_key(backend, request)
    if request.url.path == backend.base + RESTART:
        return await restart_page(backends, backend, request)
    ext = ext_resource_url(request.scope.get("raw_path", b"").decode("latin-1")
                           or request.url.path)
    if ext and request.method in ("GET", "HEAD"):
        return await ext_resource(ext, request.headers)
    try:
        await backends.ensure(backend)
    except IdeWaiting as e:
        from starlette.responses import HTMLResponse
        page = GETTING if isinstance(e, IdeGetting) else WAITING
        return HTMLResponse(page % {"why": html.escape(str(e))}, status_code=503,
                            headers={"retry-after": "5"})
    except IdeStuck as e:
        from starlette.responses import HTMLResponse
        back = request.url.path + ("?" + request.url.query if request.url.query else "")
        return HTMLResponse(STUCK % {"why": html.escape(str(e)), "base": backend.base,
                                     "back": html.escape(back)}, status_code=503)
    except IdeUnavailable as e:
        return PlainTextResponse("503 %s\n" % e, status_code=503)
    backend.last = backend._clock()
    url = backend.url(request.url.path +
                      ("?" + request.url.query if request.url.query else ""))
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
    trust_off = not backend.cfg.get("workspace_trust", False)
    page = request.url.path == backend.base + "/"
    if page and mints(backend) and r.status_code == 200:
        half = None if _client_half(request.headers.get("cookie")) else os.urandom(32)
        out += [(b"set-cookie", c.encode("latin-1")) for c in secret_cookies(backend.base, half)]
    shim = page and backend.cfg.get("forward", True)
    from .. import sessionhooks
    beacon = page and sessionhooks.enabled(backend.cfg, backend.home)
    desk = page and backend.desk_state() is not None
    if r.headers.get("content-type", "").startswith("text/html") and (
            trust_off or shim or beacon or desk):
        body = await r.aread()
        body = rewrite_workbench(body, trust_off, shim, beacon, desk)
        await r.aclose()
        resp = Response(body, status_code=r.status_code)
        # aread() decoded the body: it goes out as it is now
        resp.raw_headers = [(k, v) for k, v in out if k.lower() != b"content-encoding"] + \
            [(b"content-length", str(len(body)).encode())]
        return resp
    resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code,
                             background=BackgroundTask(r.aclose))
    resp.raw_headers = out
    return resp


TAB = re.compile(r"[a-z0-9]{1,16}\Z")


async def visibility(backend, request):
    """``POST /ide/<key>/__wpk/vis`` from the presence beacon: ``{tab, visible, gone}``.
    The tab's presence record goes to the project the server was opened for."""
    from starlette.responses import Response
    if request.method != "POST":
        return Response(status_code=405)
    try:
        d = json.loads((await request.body())[:1024] or b"{}")
        tab = str(d.get("tab") or "")
    except (ValueError, AttributeError):
        return Response(status_code=400)
    if not TAB.match(tab):
        return Response(status_code=400)
    from .. import ide_launch, presence, registry
    project, wpid = ide_launch.packet_of(backend.home, backend.key)
    e = registry.get(project, backend.home) if project else None
    if e is None:
        return Response(status_code=204)
    src = "ide-web-%s-%s" % (backend.key, tab)
    if d.get("gone"):
        presence.end(e["path"], src)
        return Response(status_code=204)
    visible = bool(d.get("visible"))
    cur = ide_launch.current(backend.home, backend.key) or {}
    user = (request.scope.get("state") or {}).get("user")
    presence.beat(e["path"], src, kind="ide-web", via="ide-web", attached=True,
                  visible=visible, active=time.time() if visible else None, wpid=wpid,
                  launch=cur.get("launch_id"), by=user if isinstance(user, str) else None)
    return Response(status_code=204)


async def proxy_ws(backends, websocket):
    backend = backends.get(key_of(websocket.url.path))
    if backend is None:
        return await websocket.close(1008)
    try:
        await backends.ensure(backend)
    except IdeUnavailable as e:
        log.warning("web VS Code: %s", e)
        return await websocket.close(1011)
    path = websocket.url.path + \
        ("?" + websocket.url.query if websocket.url.query else "")
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
