"""A display for an IDE server, started on demand (docs/desktop.md §0, §4).

    python -m work_packet.sched.xproxy --conf C --state DIR [--key K] -- <server argv>

Wraps the IDE server: it picks a free display ``:N``, listens on its X
sockets (the file and the abstract one), and starts the server with
``DISPLAY=:N``, ``XAUTHORITY`` and ``[desktop.env]`` (``--conf``, written by
wpkd). No X server runs yet. The first X client, or the first viewer on
``<priv>/vnc``, starts Xvnc on a hidden display ``:M`` and the window
manager; each connection is then spliced to it byte for byte. Ancillary data
(``SCM_RIGHTS``) does not cross the splice, so Xvnc runs without MIT-SHM, whose
shared-memory segments come back as fds; clients fall back to the socket. When nothing
has been connected through the proxy for ``idle_min``, Xvnc stops; the next
client starts it again. When the server exits, so does the proxy.

Only connections from this uid are accepted (``SO_PEERCRED``); the hidden
display also needs the job's MIT cookie, and Xvnc's own VNC socket is 0600
in the 0700 private directory, so only the proxy reaches it.

``<state>/desktop.json`` says where the viewer socket is (``vnc``), whether X
runs, who is connected, and which ``[desktop.apps]`` can start here
(``launchers``); ``desktop.env.json`` the environment applied. The board asks
for an app by a file in ``<state>/desktop.run/``; it starts in the server's
own environment, in the project's folder (``cwd``).
If Xvnc can't be found or the display can't be set up, the server runs
without one and ``desktop.json`` says why: a display never stops the IDE.
"""

import argparse
import asyncio
import json
import os
import secrets
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time

CHUNK = 65536
X_DIR = "/tmp/.X11-unix"
LOCK_DIR = "/tmp"
BASE = 20                       # leave the low displays to real X servers
START_S = 15.0
COOKIE = b"MIT-MAGIC-COOKIE-1"
FAMILY_WILD = 65535
UCRED = struct.Struct("3i")


def xauth_entry(display, cookie):
    """One Xauthority record: any host, display ``display``, an MIT cookie."""
    def field(b):
        return struct.pack(">H", len(b)) + b
    return struct.pack(">H", FAMILY_WILD) + field(b"") + field(str(display).encode()) + \
        field(COOKIE) + field(cookie)


def write_xauth(path, displays, cookie):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        for d in displays:
            f.write(xauth_entry(d, cookie))
    os.replace(tmp, path)


SHIMS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop_bin")


def install_shims(priv, conf, src=SHIMS):
    """``browser = "client"`` (§5.4): copy the ``xdg-mime`` shim to ``<priv>/bin``
    (a copy keeps its mode, and outlives an upgrade of wpk). Returns the
    directory to put first on ``PATH``, or None."""
    if (conf.get("browser") or "client") != "client" or not os.path.isdir(src):
        return None
    out = os.path.join(priv, "bin")
    os.makedirs(out, exist_ok=True)
    for n in os.listdir(src):
        dst = os.path.join(out, n)
        shutil.copyfile(os.path.join(src, n), dst)
        os.chmod(dst, 0o755)
    return out


def apply_env(environ, conf, display, xauthority, key=None, shims=None):
    """The server's environment: ``DISPLAY``, ``XAUTHORITY``, the ``shims``
    first on ``PATH``, ``[desktop.env]`` (literal values; ``{display}`` is the
    one substitution), then ``unset``."""
    env = dict(environ)
    env["DISPLAY"] = ":%d" % display
    env["XAUTHORITY"] = xauthority
    if shims:
        env["PATH"] = shims + (":" + env["PATH"] if env.get("PATH") else "")
    if key:
        env["WPK_DESKTOP"] = "/desk/%s/" % key
    applied = {}
    for k, v in (conf.get("env") or {}).items():
        applied[k] = env[k] = str(v).replace("{display}", ":%d" % display)
    for k in conf.get("unset") or ():
        env.pop(k, None)
        applied.pop(k, None)
    return env, applied


def peer(sock):
    """``(pid, uid)`` of the process at the other end of a unix socket."""
    pid, uid, _ = UCRED.unpack(sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, UCRED.size))
    return pid, uid


def comm(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except OSError:
        return "?"


def _free(n, x_dir, lock_dir):
    return not (os.path.exists(os.path.join(lock_dir, ".X%d-lock" % n))
                or os.path.exists(os.path.join(x_dir, "X%d" % n)))


def allocate(x_dir=X_DIR, lock_dir=LOCK_DIR, base=BASE, tries=200, abstract=True):
    """Take a free display: its lock file (as an X server writes it) and its
    sockets, bound and listening. Returns ``(n, [sockets], lock path)``."""
    if not os.path.isdir(x_dir):
        os.makedirs(x_dir, exist_ok=True)
        os.chmod(x_dir, 0o1777)
    for n in range(base, base + tries):
        if not _free(n, x_dir, lock_dir):
            continue
        lock = os.path.join(lock_dir, ".X%d-lock" % n)
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        except FileExistsError:
            continue
        os.write(fd, b"%10d\n" % os.getpid())
        os.close(fd)
        socks = []
        try:
            path = os.path.join(x_dir, "X%d" % n)
            names = (["\0" + path] if abstract else []) + [path]
            for name in names:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                socks.append(s)
                s.bind(name)
                s.listen(64)
                s.setblocking(False)
            os.chmod(path, 0o777)       # as an X server's: the uid check is the gate
            return n, socks, lock
        except OSError:
            for s in socks:
                s.close()
            _unlink(lock, os.path.join(x_dir, "X%d" % n))
    raise OSError("no free X display in :%d-:%d" % (base, base + tries - 1))


def _unlink(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


def pick_wm(conf, which=shutil.which):
    """``[desktop] wm``: fvwm | xfwm4 | xfce | none; ``auto``: the first found."""
    want = conf.get("wm") or "auto"
    if want == "auto":
        for w in ("fvwm", "xfwm4"):
            if which(w):
                return w
        return "none"
    if want == "xfce":
        return "xfce" if which("xfce4-session") else "none"
    return want if want == "none" or which(want) else "none"


FVWM = """\
Style * ClickToFocus, DecorateTransient
DesktopSize 1x1
EdgeScroll 0 0
TitleStyle Centered
AddToMenu RootMenu "%(title)s" Title
+ "Terminal" Exec exec xterm
+ "" Nop
+ "Refresh" Refresh
Mouse 1 R A Menu RootMenu
Mouse 3 R A Menu RootMenu
"""


def wm_argv(wm, priv, title):
    if wm == "fvwm":
        cfg = os.path.join(priv, "fvwm.cfg")
        with open(cfg, "w") as f:
            f.write(FVWM % {"title": title.replace('"', "'")})
        return ["fvwm", "-f", cfg]
    if wm == "xfwm4":
        return ["xfwm4", "--compositor=off", "--sm-client-disable"]
    if wm == "xfce":
        return ["dbus-run-session", "xfce4-session"] if shutil.which("dbus-run-session") \
            else ["xfce4-session"]
    return None


class Proxy:
    def __init__(self, conf, state_dir, priv, key=None, x_dir=X_DIR, lock_dir=LOCK_DIR,
                 base=BASE, abstract=True, clock=time.monotonic):
        self.conf = conf
        self.state_dir = state_dir
        self.priv = priv
        self.key = key
        self.x_dir, self.lock_dir, self.base, self.abstract = x_dir, lock_dir, base, abstract
        self.clock = clock
        self.xdir = os.path.join(priv, "x")
        os.makedirs(self.xdir, mode=0o700, exist_ok=True)
        self.vnc = os.path.join(priv, "vnc")
        self.rfb = os.path.join(self.xdir, "rfb")
        self.xauth = os.path.join(self.xdir, "xauth")
        self.cookie = secrets.token_bytes(16)
        self.n, self.socks, self.lock = allocate(x_dir, lock_dir, base, abstract=abstract)
        write_xauth(self.xauth, [self.n], self.cookie)
        self.xvnc = self.wm = self.extra = None
        self.wm_name = None
        self.m = None
        self.x = "stopped"
        self.clients = {}           # id -> app name
        self.viewers = 0
        self.last = clock()
        self.since = None
        self.why = None
        self._start_lock = None
        self._servers = []
        self.started = 0
        self.env = None             # the server's environment: apps start with it
        self.launched = []          # apps started from the menu, until they exit

    # -- the Apps menu ---------------------------------------------------------

    def launchers(self, which=shutil.which):
        """The ``[desktop.apps]`` whose program is on this host's PATH."""
        out = []
        for name, a in sorted((self.conf.get("apps") or {}).items()):
            try:
                argv = shlex.split(a.get("cmd") or "")
            except ValueError:
                continue
            if argv and which(argv[0]):
                out.append({"name": name, "label": a.get("label") or name})
        return out

    def launch(self, name):
        """Start app ``name`` on the display, as a terminal in the IDE would."""
        a = (self.conf.get("apps") or {}).get(name)
        if not a or name not in {x["name"] for x in self.launchers()}:
            return None
        cwd = self.conf.get("cwd")
        if not (cwd and os.path.isdir(cwd)):
            cwd = None
        log = open(os.path.join(self.xdir, "apps.log"), "ab")
        try:
            p = subprocess.Popen(["sh", "-c", a["cmd"]], stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, env=self.env or dict(os.environ),
                                 cwd=cwd)
        except OSError:
            return None
        finally:
            log.close()
        self.launched.append(p)
        return p

    def take_requests(self):
        """Start what the board asked for in ``desktop.run/`` (each file once)."""
        d = os.path.join(self.state_dir, "desktop.run")
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
        except OSError:
            names = []
        for n in names:
            p = os.path.join(d, n)
            try:
                with open(p) as f:
                    want = json.load(f).get("app")
            except (OSError, ValueError):
                want = None
            _unlink(p)
            if want:
                self.launch(want)
        self.launched = [p for p in self.launched if p.poll() is None]

    async def request_loop(self, every=0.5):
        while True:
            await asyncio.sleep(every)
            self.take_requests()

    # -- state -----------------------------------------------------------------

    def publish(self):
        rec = {"display": ":%d" % self.n, "x": self.x, "clients": len(self.clients),
               "viewers": self.viewers, "apps": sorted(set(self.clients.values())),
               "vnc": self.vnc, "pid": os.getpid(), "since": self.since,
               "wm": self.wm_name if self.xvnc else None, "started": self.started,
               "why": self.why, "launchers": self.launchers(), "at": time.time()}
        _write_json(os.path.join(self.state_dir, "desktop.json"), rec)

    # -- the X server ------------------------------------------------------------

    def _free_hidden(self):
        n = self.n + 1
        while not _free(n, self.x_dir, self.lock_dir):
            n += 1
        return n

    def _start_x(self):
        """Blocking: start Xvnc and the WM. Returns once Xvnc accepts clients."""
        m = self._free_hidden()
        _unlink(self.rfb)
        r, w = os.pipe()
        xvnc = self.conf.get("xvnc") or "Xvnc"
        argv = [xvnc, ":%d" % m, "-displayfd", str(w), "-rfbunixpath", self.rfb,
                "-rfbunixmode", "0600", "-rfbport", "-1", "-auth", self.xauth,
                "-SecurityTypes", "None", "-nolisten", "tcp",
                # The proxy splices bytes, not SCM_RIGHTS: an fd-passing extension
                # (MIT-SHM 1.2's segments) would leave the client waiting on an fd forever.
                "-extension", "MIT-SHM",
                "-geometry", str(self.conf.get("geometry") or "1600x1000"), "-depth", "24",
                "-AlwaysShared", "-desktop", self.conf.get("title") or "wpk"]
        log = open(os.path.join(self.xdir, "xvnc.log"), "ab")
        try:
            p = subprocess.Popen(argv, pass_fds=(w,), stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT)
        finally:
            os.close(w)
            log.close()
        got, end = b"", time.monotonic() + START_S
        try:
            while not got.endswith(b"\n") and time.monotonic() < end:
                c = os.read(r, 16)
                if not c:
                    break
                got += c
        finally:
            os.close(r)
        if not got.strip().isdigit():
            p.terminate()
            p.wait(5)
            raise OSError("Xvnc did not start (see %s)" % os.path.join(self.xdir, "xvnc.log"))
        self.m = int(got)
        write_xauth(self.xauth, [self.n, self.m], self.cookie)
        self.xvnc = p
        env = dict(os.environ, DISPLAY=":%d" % self.m, XAUTHORITY=self.xauth)
        env.update({k: str(v) for k, v in (self.conf.get("env") or {}).items()})
        self.wm_name = pick_wm(self.conf)
        wm = wm_argv(self.wm_name, self.xdir, self.conf.get("title") or "wpk")
        wlog = open(os.path.join(self.xdir, "wm.log"), "ab")
        try:
            if wm:
                self.wm = subprocess.Popen(wm, stdin=subprocess.DEVNULL, stdout=wlog,
                                           stderr=subprocess.STDOUT, env=env)
            if shutil.which("vncconfig"):     # the clipboard between Xvnc and the viewer
                self.extra = subprocess.Popen(["vncconfig", "-nowin"], stdin=subprocess.DEVNULL,
                                              stdout=wlog, stderr=subprocess.STDOUT, env=env)
        except OSError:
            pass
        finally:
            wlog.close()

    def _stop_x(self):
        for p in (self.extra, self.wm, self.xvnc):
            if p is not None and p.poll() is None:
                p.terminate()
        for p in (self.extra, self.wm, self.xvnc):
            if p is None:
                continue
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        self.extra = self.wm = self.xvnc = None
        if self.m is not None:      # an Xvnc killed hard leaves these behind
            _unlink(os.path.join(self.lock_dir, ".X%d-lock" % self.m),
                    os.path.join(self.x_dir, "X%d" % self.m))
        self.m = None
        self.x = "stopped"
        self.since = None

    def running(self):
        return self.xvnc is not None and self.xvnc.poll() is None

    async def ensure_x(self):
        async with self._start_lock:
            if self.running():
                return
            if self.xvnc is not None:            # it died: tidy up first
                await asyncio.get_running_loop().run_in_executor(None, self._stop_x)
            self.x = "starting"
            self.publish()
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._start_x)
            except OSError as e:
                self.x, self.why = "failed", str(e)
                self.publish()
                raise
            self.x, self.why, self.since = "running", None, time.time()
            self.started += 1
            self.publish()

    # -- connections -------------------------------------------------------------

    def _ours(self, writer):
        sock = writer.get_extra_info("socket")
        try:
            pid, uid = peer(sock)
        except OSError:
            return None
        return pid if uid == os.getuid() else None

    async def _splice(self, reader, writer, up):
        ur, uw = up
        t1 = asyncio.ensure_future(_pump(reader, uw))
        t2 = asyncio.ensure_future(_pump(ur, writer))
        try:
            await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (t1, t2):
                t.cancel()
            await asyncio.gather(t1, t2, return_exceptions=True)

    async def on_client(self, reader, writer):
        pid = self._ours(writer)
        if pid is None:
            writer.close()
            return
        cid = object()
        self.clients[cid] = comm(pid)
        self.last = self.clock()
        try:
            await self.ensure_x()
            up = await asyncio.open_unix_connection(os.path.join(self.x_dir, "X%d" % self.m))
            self.publish()
            await self._splice(reader, writer, up)
        except OSError:
            writer.close()
        finally:
            del self.clients[cid]
            self.last = self.clock()
            self.publish()

    async def on_viewer(self, reader, writer):
        if self._ours(writer) is None:
            writer.close()
            return
        self.viewers += 1
        self.last = self.clock()
        try:
            await self.ensure_x()
            up = await asyncio.open_unix_connection(self.rfb)
            self.publish()
            await self._splice(reader, writer, up)
        except OSError:
            writer.close()
        finally:
            self.viewers -= 1
            self.last = self.clock()
            self.publish()

    async def idle_loop(self, every=15.0):
        limit = 60.0 * float(self.conf.get("idle_min") or 20)
        while True:
            await asyncio.sleep(min(every, limit / 4))
            if self.xvnc is not None and not self.running():
                async with self._start_lock:           # Xvnc died by itself
                    await asyncio.get_running_loop().run_in_executor(None, self._stop_x)
                    self.publish()
            elif self.running() and not self.clients and not self.viewers and \
                    self.clock() - self.last > limit:
                async with self._start_lock:
                    if not self.clients and not self.viewers:
                        await asyncio.get_running_loop().run_in_executor(None, self._stop_x)
                        self.publish()

    async def serve(self):
        self._start_lock = asyncio.Lock()
        for s in self.socks:
            self._servers.append(await asyncio.start_unix_server(self.on_client, sock=s))
        _unlink(self.vnc)
        old = os.umask(0o077)
        try:
            self._servers.append(await asyncio.start_unix_server(self.on_viewer, path=self.vnc))
        finally:
            os.umask(old)
        self.publish()

    def close(self):
        for srv in self._servers:
            srv.close()
        for s in self.socks:
            s.close()
        self._stop_x()
        _unlink(self.lock, os.path.join(self.x_dir, "X%d" % self.n), self.vnc)
        self.x = "ended"
        try:
            self.publish()
        except OSError:
            pass


async def _pump(r, w):
    try:
        while True:
            data = await r.read(CHUNK)
            if not data:
                break
            w.write(data)
            await w.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        try:
            w.close()
        except Exception:                      # noqa: BLE001
            pass


def _write_json(path, rec):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(rec, f, sort_keys=True)
    os.replace(tmp, path)


def load_conf(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def unavailable(conf):
    """Why there can be no display here, or None."""
    xvnc = conf.get("xvnc") or "Xvnc"
    if not shutil.which(xvnc):
        return "%s is not installed on %s (TigerVNC's Xvnc)" % (xvnc, socket.gethostname())
    return None


async def run(conf, state_dir, key, argv, priv=None, **kw):
    """Start the server under a display; returns its exit status."""
    from .ide_job import local_dir
    own = priv is None
    why = unavailable(conf)
    proxy = None
    env = dict(os.environ)
    if why is None:
        try:
            priv = priv or local_dir()
            proxy = Proxy(conf, state_dir, priv, key, **kw)
            await proxy.serve()
            env, applied = apply_env(os.environ, conf, proxy.n, proxy.xauth, key,
                                     shims=install_shims(priv, conf))
            proxy.env = env
            _write_json(os.path.join(state_dir, "desktop.env.json"),
                        {"display": ":%d" % proxy.n, "env": applied,
                         "unset": list(conf.get("unset") or ())})
        except OSError as e:
            why, proxy = "no display: %s" % e, None
    if proxy is None:
        _write_json(os.path.join(state_dir, "desktop.json"),
                    {"x": "unavailable", "why": why, "at": time.time()})
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, env=env)
    loop = asyncio.get_running_loop()

    def stop():
        if child.poll() is None:
            child.terminate()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop)
    loops = [asyncio.ensure_future(proxy.idle_loop()),
             asyncio.ensure_future(proxy.request_loop())] if proxy else []
    try:
        code = await loop.run_in_executor(None, child.wait)
    finally:
        for t in loops:
            t.cancel()
        if proxy is not None:
            proxy.close()
        if own and priv:
            shutil.rmtree(priv, ignore_errors=True)
    return code


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--" not in argv:
        print("usage: python -m work_packet.sched.xproxy --conf C --state DIR [--key K] "
              "-- <server argv>", file=sys.stderr)
        return 2
    i = argv.index("--")
    ap = argparse.ArgumentParser(prog="python -m work_packet.sched.xproxy")
    ap.add_argument("--conf", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--key")
    a = ap.parse_args(argv[:i])
    return asyncio.run(run(load_conf(a.conf), a.state, a.key, argv[i + 1:]))


if __name__ == "__main__":
    sys.exit(main())
