"""Serving the board on loopback and on the tailnet (server.md §2.2).

Each listener is its own uvicorn server with its own ``Guard``, all in one
event loop. The loopback one starts at once. The tailnet one waits for
tailscaled, binds this node's tailnet addresses, and rebinds if they change.
"""

import asyncio
import contextlib
import getpass
import json
import logging
import os
import secrets
import signal
import socket

import uvicorn

from .. import clock, fsutil, registry, schema
from .app import create_app
from .guard import Guard, is_loopback
from .tailscale import Tailnet

log = logging.getLogger("wpk.dash")

WAIT_S = 5          # poll for tailscaled while it is not up
WATCH_S = 30        # poll for address changes once bound


class ServeError(Exception):
    pass


def load_secret(home):
    """``server.secret``: the CSRF key, made on first use, readable only by you."""
    path = os.path.join(home, "server.secret")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path) as fp:
            return bytes.fromhex(fp.read().strip())
    with os.fdopen(fd, "w") as fp:
        fp.write(secrets.token_hex(32) + "\n")
    return load_secret(home)


def state_path(home):
    return os.path.join(home, "server.json")


def read_state(home):
    """``server.json`` if the server that wrote it is still running, else None."""
    try:
        with open(state_path(home)) as fp:
            st = json.load(fp)
        os.kill(int(st["pid"]), 0)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return st


GRACE_S = 3


def _url(host, port, scheme="http"):
    return "%s://%s:%d/" % (scheme, "[%s]" % host if ":" in host else host, port)


def _bind(ip, port):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if fam == socket.AF_INET6:
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        s.bind((ip, port))
        s.listen(128)
    except OSError:
        s.close()
        raise
    return s


class _Server(uvicorn.Server):
    """A uvicorn server that leaves signals to us, so several can share a loop."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield

    def install_signal_handlers(self):
        pass


class Board:
    def __init__(self, cfg, home=None, host=None, tailnet=None, runner=None):
        """``cfg`` is the ``[server]`` table with defaults filled in. ``host``
        replaces both listeners with one on that address. ``runner`` (a
        ``dash.runner.Runner``) runs steps in this process; the board pokes it."""
        self.cfg = cfg
        self.home = home or registry.home()
        self.port = cfg["port"]
        self.host = host
        self.runner = runner
        from .shells import Shells
        self.shells = Shells()
        from .. import ide as ide_cfg
        from .ide import Backend
        self.ide = Backend(self.home, ide_cfg.load_config(self.home))
        self.app = create_app(home, runner=runner, shells=self.shells, ide_backend=self.ide)
        self.secret = load_secret(self.home)
        self.user = getpass.getuser()
        want_tn = cfg["tailnet"] if host is None else not is_loopback(host)
        self.tailnet = (tailnet or Tailnet()) if want_tn else None
        if want_tn and cfg["auth"] != "tailscale":
            raise ServeError("auth = %r cannot listen beyond this machine; "
                             "use auth = \"tailscale\"" % cfg["auth"])
        self.urls = {"loopback": [], "tailnet": []}
        self._stop = None

    def guard(self, kind):
        return Guard(self.app, kind, self.secret, tailnet=self.tailnet,
                     allow=self.cfg["allow"], extra_hosts=self.cfg["extra_hosts"],
                     local_user=self.user)

    def _start(self, kind, socks, tls=None):
        """``tls``: ``(cert, key)`` paths for an https listener."""
        kw = dict(ssl_certfile=tls[0], ssl_keyfile=tls[1]) if tls else {}
        srv = _Server(uvicorn.Config(self.guard(kind), log_level="warning",
                                     lifespan="off", proxy_headers=False,
                                     server_header=False,
                                     # an idle TLS keep-alive (a browser tab) would
                                     # otherwise hold shutdown open for good
                                     timeout_graceful_shutdown=GRACE_S, **kw))
        return srv, asyncio.ensure_future(srv.serve(sockets=socks))

    def _write_state(self):
        fsutil.atomic_write(state_path(self.home), json.dumps({
            "pid": os.getpid(), "started": schema.format_timestamp(clock.now()),
            "port": self.port, "urls": self.urls["loopback"] + self.urls["tailnet"],
            "runner": self.runner is not None,
        }, indent=1) + "\n")

    def _cert(self):
        """``((cert, key, fetched now, domain), None)`` or ``(None, why)``."""
        from . import tls as tls_mod
        try:
            name = tls_mod.domain(self.tailnet)
            cp, kp, new = tls_mod.ensure(self.home, name, self.tailnet.sock)
            tls_mod.context(cp, kp)
        except tls_mod.TlsError as e:
            return None, str(e)
        if new:
            log.warning("fetched the certificate for %s", name)
        return (cp, kp, new, name), None

    async def _tailnet(self, ips_only=None):
        """Keep a server on this node's tailnet addresses (or ``ips_only``)."""
        bound, srv, task, waiting = None, None, None, False
        tls, tls_why = None, None
        try:
            while not self._stop.is_set():
                if ips_only:
                    ips = ips_only
                else:
                    self.tailnet.status(fresh=True)
                    ips = self.tailnet.ips()
                if self.cfg.get("tls") == "tailscale":
                    got, why = await asyncio.get_running_loop().run_in_executor(
                        None, self._cert)
                    if why and why != tls_why:
                        log.warning("no https on the tailnet yet: %s", why)
                    tls_why = why
                    if got is None:
                        ips = []        # never fall back to plain http
                    elif got[2] or got[:2] != (tls or (None, None))[:2]:
                        tls, bound = got, None          # new certificate: rebind
                if ips != bound:
                    if srv:
                        srv.should_exit = True
                        await task
                        srv, bound, self.urls["tailnet"] = None, None, []
                        log.warning("tailnet addresses changed; rebinding")
                    socks = []
                    for ip in ips:
                        try:
                            socks.append(_bind(ip, self.port))
                        except OSError as e:
                            log.warning("cannot listen on %s:%d: %s", ip, self.port, e)
                    if socks:
                        srv, task = self._start("tailnet", socks, tls[:2] if tls else None)
                        bound, waiting = ips, False
                        if tls:         # only the certificate's name matches it
                            self.urls["tailnet"] = [_url(tls[3], self.port, "https")]
                        else:
                            names = sorted(self.tailnet.names(), key=len) \
                                if not ips_only else []
                            hosts = names + [s.getsockname()[0] for s in socks]
                            self.urls["tailnet"] = [_url(h, self.port) for h in hosts]
                        self._write_state()
                        log.warning("on the tailnet: %s", " ".join(self.urls["tailnet"]))
                    elif not waiting:
                        log.warning("waiting for tailscaled (%s)", "no tailnet address"
                                    if not ips else "bind failed")
                        waiting = True
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), WATCH_S if srv else WAIT_S)
        finally:
            if srv:
                srv.should_exit = True
                await task

    async def run(self, ready=None):
        self._stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)
        tasks, servers = [], []
        try:
            if self.host is not None and self.tailnet is not None:
                tasks.append(asyncio.ensure_future(self._tailnet([self.host])))
            else:
                if self.host is not None or self.cfg["loopback"]:
                    ip = self.host or "127.0.0.1"
                    try:
                        sock = _bind(ip, self.port)
                    except OSError as e:
                        raise ServeError("cannot listen on %s:%d: %s" % (ip, self.port, e))
                    servers.append(self._start("loopback", [sock]))
                    self.urls["loopback"] = [_url(ip, self.port)]
                if self.tailnet is not None:
                    tasks.append(asyncio.ensure_future(self._tailnet()))
            if self.runner is not None:
                self.runner.start()
            self._write_state()
            if ready:
                ready(self)
            await self._stop.wait()
        finally:
            self._stop.set()
            self.shells.shutdown()
            self.ide.stop()             # on the loop: it cancels the idle task
            for srv, _ in servers:
                srv.should_exit = True
            await asyncio.gather(*tasks, *(t for _, t in servers), return_exceptions=True)
            if self.runner is not None:
                if self.runner.busy:
                    log.warning("waiting for running steps to finish")
                await loop.run_in_executor(None, self.runner.stop)
            with contextlib.suppress(OSError):
                if (read_state(self.home) or {}).get("pid") == os.getpid():
                    os.unlink(state_path(self.home))
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)

    def stop(self):
        if self._stop is not None:
            self._stop.set()
