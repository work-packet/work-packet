"""Serving the board on loopback and on the tailnet (server.md §2.2), or on
every address with a Unix sign-in (docs/unix-login.md).

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
TLS_RECORD = 0x16   # a TLS handshake record: what a ClientHello starts with
SNIFF_S = 10        # how long a new connection may take to send its first byte
HEAD_MAX = 16384    # a plain-http request head we read to redirect it


async def _redirect_plain(conn, host, port):
    """A plain-http request on the https port: answer 308 to the same path
    on ``https://<host>:<port>`` (the certificate's name, not the request's
    Host: an address or another name would fail the certificate anyway)."""
    reader, writer = await asyncio.open_connection(sock=conn)
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), SNIFF_S)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError,
            ConnectionError, OSError):
        writer.close()
        return
    parts = head.split(b"\r\n", 1)[0].split(b" ")
    path = parts[1].decode("latin-1") if len(parts) == 3 else "/"
    if not path.startswith("/") or path.startswith("//"):
        path = "/"                  # an absolute-form or odd target: the board's root
    loc = "https://%s%s%s" % (host, "" if port == 443 else ":%d" % port, path)
    body = ("This board is https only: %s\n" % loc).encode()
    writer.write(b"HTTP/1.1 308 Permanent Redirect\r\nlocation: %s\r\n"
                 b"content-type: text/plain; charset=utf-8\r\ncontent-length: %d\r\n"
                 b"connection: close\r\n\r\n%s" % (loc.encode("latin-1"), len(body), body))
    with contextlib.suppress(ConnectionError, OSError):
        await writer.drain()
    writer.close()


async def _first_byte(conn):
    """The connection's first byte, left unread (b"" if it closed)."""
    loop = asyncio.get_running_loop()
    ready = loop.create_future()
    loop.add_reader(conn.fileno(), lambda: ready.done() or ready.set_result(None))
    try:
        await asyncio.wait_for(ready, SNIFF_S)
    finally:
        loop.remove_reader(conn.fileno())
    return conn.recv(1, socket.MSG_PEEK)


async def _serve_https_or_redirect(srv, socks, host, port):
    """Serve ``srv`` (a uvicorn server with TLS) on ``socks``, accepting the
    connections here: TLS goes to uvicorn's own protocol, plain http gets a
    redirect to https (uvicorn alone would just drop it)."""
    import functools
    loop = asyncio.get_running_loop()
    conns = set()

    async def one(conn):
        try:
            first = await _first_byte(conn)
            if not first:
                conn.close()
            elif first[0] == TLS_RECORD:
                c = srv.config
                proto = functools.partial(c.http_protocol_class, config=c,
                                          server_state=srv.server_state,
                                          app_state=srv.lifespan.state)
                await loop.connect_accepted_socket(proto, conn, ssl=c.ssl)
            else:
                await _redirect_plain(conn, host, port)
        except (asyncio.TimeoutError, ConnectionError, OSError, ValueError):
            conn.close()

    async def accept(sock):
        sock.setblocking(False)
        while True:
            conn, _ = await loop.sock_accept(sock)
            t = asyncio.ensure_future(one(conn))
            conns.add(t)
            t.add_done_callback(conns.discard)

    serving = asyncio.ensure_future(srv.serve(sockets=[]))
    acceptors = []
    try:
        while not srv.started and not serving.done():       # its config, TLS and protocol
            await asyncio.sleep(0.02)
        if srv.started:
            acceptors = [asyncio.ensure_future(accept(s)) for s in socks]
        await serving
    finally:
        for t in acceptors + list(conns):
            t.cancel()
        await asyncio.gather(*acceptors, *conns, return_exceptions=True)
        for s in socks:
            s.close()


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


def sock_path(home):
    return os.path.join(home, "run", "wpkd.sock")


def _bind_unix(path):
    """A unix socket only this user can reach: its directory is 0700."""
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)              # one wpkd per home (wpkd.lease): a leftover file
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(path)
        os.chmod(path, 0o600)
        s.listen(128)
    except OSError:
        s.close()
        raise
    return s


def ssh_line(home, port=7878):
    """How to reach a unix-socket board from a laptop (docs/scheduler.md §7.1)."""
    return "ssh -N -L %d:%s %s@%s" % (port, sock_path(home), getpass.getuser(),
                                      socket.getfqdn())


def _url(host, port, scheme="http"):
    return "%s://%s:%d/" % (scheme, "[%s]" % host if ":" in host else host, port)


def host_names(extra=()):
    """This host's names and addresses, as a browser might put them in ``Host``."""
    import subprocess
    names = {socket.gethostname(), socket.getfqdn()} | set(extra)
    for n in list(names):
        with contextlib.suppress(OSError, UnicodeError):
            names |= {a[4][0] for a in socket.getaddrinfo(n, None)}
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        names |= set(out.stdout.split())
    return {n.lower() for n in names if n and not n.startswith("127.") and n != "::1"}


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
        from .ide import Backends
        from ..sched import config as sconfig, ide as side
        try:
            scfg = sconfig.load(self.home)
            slot = side.enabled(scfg)
            transport = (scfg.get("ide") or {}).get("transport") or "tcp-token"
        except registry.ConfigError:
            slot, transport = False, "tcp-token"
        self.ide = Backends(self.home, ide_cfg.load_config(self.home), slot=slot,
                            poke=runner.poke if runner is not None else None, transport=transport)
        from .agent import Agents
        self.agents = Agents(self.home)
        self.app = create_app(home, runner=runner, shells=self.shells, ide_backend=self.ide,
                              agents=self.agents)
        from ..studio import renders
        self.renders = renders.install(renders.Service(self.home))
        self.secret = load_secret(self.home)
        self.user = getpass.getuser()
        self.network = cfg["auth"] == "unix" and (
            cfg.get("listen") == "network" if host is None else not is_loopback(host))
        want_tn = not self.network and (cfg["tailnet"] if host is None
                                         else not is_loopback(host))
        self.tailnet = (tailnet or Tailnet()) if want_tn else None
        if want_tn and cfg["auth"] != "tailscale":
            raise ServeError("auth = %r cannot listen beyond this machine; "
                             "use auth = \"tailscale\" (or \"unix\" with TLS: "
                             "docs/unix-login.md)" % cfg["auth"])
        if self.network and cfg.get("tls") not in ("self-signed", "files"):
            raise ServeError("the network listener needs tls = \"self-signed\" or \"files\": "
                             "a session cookie must not cross the network in clear")
        self.gate = None
        if self.network:
            from ..sched import authz
            from .login import Gate
            self.gate = Gate(self.home, self.secret, self.port, authz.home_owner(self.home),
                             cfg["allow"], cfg.get("session_days", 30))
        self.urls = {"loopback": [], "tailnet": [], "network": []}
        from .events import Collector
        self.events = Collector(self.home)
        self.sock = None
        self.names = set()
        self._stop = self._close = None
        # An in-place restart asked for (docs/serve-restart-plan.md):
        # {"ids": request ids to answer, "force": do not wait for steps}.
        self.restart = None
        self.restarted = None           # the ids this image was exec'd for
        self._closing = False           # past the point where a restart can be called off

    def guard(self, kind):
        return Guard(self.app, kind, self.secret, tailnet=self.tailnet,
                     allow=self.cfg["allow"], extra_hosts=self.cfg["extra_hosts"],
                     local_user=self.user, gate=self.gate if kind == "network" else None,
                     names=self.names if kind == "network" else ())

    def _start(self, kind, socks, tls=None, redirect_to=None):
        """``tls``: ``(cert, key)`` paths for an https listener. ``redirect_to``:
        with ``tls``, the host name plain-http requests are sent to, on https."""
        kw = dict(ssl_certfile=tls[0], ssl_keyfile=tls[1]) if tls else {}
        srv = _Server(uvicorn.Config(self.guard(kind), log_level="warning",
                                     lifespan="off", proxy_headers=False,
                                     server_header=False,
                                     # an idle TLS keep-alive (a browser tab) would
                                     # otherwise hold shutdown open for good
                                     timeout_graceful_shutdown=GRACE_S, **kw))
        if tls and redirect_to:
            return srv, asyncio.ensure_future(
                _serve_https_or_redirect(srv, socks, redirect_to, self.port))
        return srv, asyncio.ensure_future(srv.serve(sockets=socks))

    def _start_render(self):
        """The studio's render listener (dash/render_gate.py): loopback, a port
        of its own, for the headless browser and ``wpk studio look``."""
        from ..studio import renders
        from .render_gate import RenderGate
        sock = _bind("127.0.0.1", 0)
        port = sock.getsockname()[1]
        srv = _Server(uvicorn.Config(RenderGate(self.app, self.renders), log_level="warning",
                                     lifespan="off", proxy_headers=False, server_header=False,
                                     timeout_graceful_shutdown=GRACE_S))
        self.renders.base_url = "http://127.0.0.1:%d" % port
        renders.write_listener(self.home, self.renders.base_url, self.renders.secret)
        return srv, asyncio.ensure_future(srv.serve(sockets=[sock]))

    def _write_state(self):
        fsutil.atomic_write(state_path(self.home), json.dumps({
            "pid": os.getpid(), "started": schema.format_timestamp(clock.now()),
            "port": self.port,
            "urls": self.urls["network"] + self.urls["loopback"] + self.urls["tailnet"],
            "auth": self.cfg["auth"] if self.network else None,
            "runner": self.runner is not None, "sock": self.sock,
            "host": socket.gethostname(), "poke": "SIGUSR1",
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

    def _network_tls(self):
        from . import tls as tls_mod
        try:
            if self.cfg.get("tls") == "files":
                cp = os.path.expanduser(self.cfg["tls_cert"])
                kp = os.path.expanduser(self.cfg["tls_key"])
            else:
                cp, kp = tls_mod.self_signed(self.home, self.names)
            tls_mod.context(cp, kp)
        except tls_mod.TlsError as e:
            raise ServeError(str(e))
        return cp, kp

    def _start_network(self):
        """Every address (or ``--host``), https only, sign-in required."""
        from .login import ensure_drop_dir
        self.names = host_names(self.cfg["extra_hosts"])
        if self.host is not None:
            self.names.add(self.host.lower())
        tls = self._network_tls()
        ensure_drop_dir(self.home)
        socks = []
        for ip in ([self.host] if self.host else ["0.0.0.0", "::"]):
            try:
                socks.append(_bind(ip, self.port))
            except OSError as e:
                if ip == "::" and socks:        # no IPv6 here: IPv4 is enough
                    continue
                for s_ in socks:
                    s_.close()
                raise ServeError("cannot listen on %s:%d: %s" % (ip, self.port, e))
        fqdn = socket.getfqdn()
        self.urls["network"] = [_url(self.host or fqdn, self.port, "https")]
        return self._start("network", socks, tls, redirect_to=self.host or fqdn)

    async def _tailnet(self, ips_only=None):
        """Keep a server on this node's tailnet addresses (or ``ips_only``)."""
        bound, srv, task, waiting = None, None, None, False
        tls, tls_why = None, None
        try:
            while not self._close.is_set():
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
                        srv, task = self._start("tailnet", socks, tls[:2] if tls else None,
                                                redirect_to=tls[3] if tls else None)
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
                    await asyncio.wait_for(self._close.wait(), WATCH_S if srv else WAIT_S)
        finally:
            if srv:
                srv.should_exit = True
                await task

    async def run(self, ready=None):
        from . import ide_forward, restart
        self._stop = asyncio.Event()
        # Set once the servers close: a restart waiting for its steps sets _stop
        # first and still serves, on the tailnet too.
        self._close = asyncio.Event()
        self.restarted = restart.restarted()
        loop = asyncio.get_running_loop()
        if os.environ.get("WPK_DEBUG_LOOP"):   # log each callback that holds the loop
            loop.set_debug(True)                # (docs/cpu-plan.md P0)
            loop.slow_callback_duration = float(os.environ["WPK_DEBUG_LOOP"]) \
                if os.environ["WPK_DEBUG_LOOP"].replace(".", "", 1).isdigit() else 0.05
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._on_stop)
        loop.add_signal_handler(signal.SIGUSR2, self._on_restart)
        # SIGUSR1: look for due packets now (`wpk start --go`, `wpk handoff`;
        # sched/home_lease.poke). server.json says so, so an older wpkd, for
        # which SIGUSR1 would be fatal, is never sent it.
        loop.add_signal_handler(signal.SIGUSR1, self._on_poke)
        if self.restarted is not None:
            ide_forward.TOKENS.load(ide_forward.saved_path(self.home))
        else:                           # a stop ended them; a crash leaves the file
            with contextlib.suppress(OSError):
                os.unlink(ide_forward.saved_path(self.home))
        tasks, servers = [], []
        try:
            if self.network:
                servers.append(self._start_network())
            elif self.host is not None and self.tailnet is not None:
                tasks.append(asyncio.ensure_future(self._tailnet([self.host])))
            else:
                if self.host is None and self.cfg.get("listen") == "unix":
                    path = sock_path(self.home)
                    try:
                        sock = _bind_unix(path)
                    except OSError as e:
                        raise ServeError("cannot listen on %s: %s" % (path, e))
                    servers.append(self._start("unix", [sock]))
                    self.sock = path
                    self.urls["loopback"] = ["http://localhost:%d/ (after: %s)"
                                             % (self.port, ssh_line(self.home, self.port))]
                elif self.host is not None or self.cfg["loopback"]:
                    ip = self.host or "127.0.0.1"
                    try:
                        sock = _bind(ip, self.port)
                    except OSError as e:
                        raise ServeError("cannot listen on %s:%d: %s" % (ip, self.port, e))
                    servers.append(self._start("loopback", [sock]))
                    self.urls["loopback"] = [_url(ip, self.port)]
                if self.tailnet is not None:
                    tasks.append(asyncio.ensure_future(self._tailnet()))
            try:
                servers.append(self._start_render())
            except OSError as e:
                log.warning("the studio will have no renders: cannot listen on loopback: %s", e)
            try:            # before the runner, so its steps inherit DFM_EVENT_SINK
                await self.events.start()
            except OSError as e:
                log.warning("DFM runs will not show: cannot listen on %s: %s",
                            self.events.path, e)
            if self.runner is not None:
                self.runner.start()
            self._write_state()
            tasks.append(asyncio.ensure_future(self._adopt_ide()))
            if self.restarted is not None:
                log.warning("restarted in place (pid %d)", os.getpid())
                restart.set_status(self.home, self.restarted, "done")
            if ready:
                ready(self)
            await self._stop.wait()
            await self._wait_steps()
        finally:
            self._stop.set()
            self._close.set()
            self._closing = True
            restarting = self.restart is not None
            self.shells.shutdown()
            self.agents.shutdown()
            if restarting:              # left running, for the next image to adopt
                self.ide.detach()
                with contextlib.suppress(OSError):
                    ide_forward.TOKENS.save(ide_forward.saved_path(self.home))
            else:
                self.ide.stop()         # on the loop: it cancels the idle task
            await self.events.stop()
            for srv, _ in servers:
                srv.should_exit = True
            await asyncio.gather(*tasks, *(t for _, t in servers), return_exceptions=True)
            if self.runner is not None:
                if restarting:
                    await loop.run_in_executor(None, lambda: self.runner.stop(release=False))
                else:
                    if self.runner.busy:
                        log.warning("waiting for running steps to finish")
                    await loop.run_in_executor(None, self.runner.stop)
            with contextlib.suppress(OSError):
                if not restarting and (read_state(self.home) or {}).get("pid") == os.getpid():
                    os.unlink(state_path(self.home))
            if self.sock:
                with contextlib.suppress(OSError):
                    os.unlink(self.sock)
            from ..studio import renders
            with contextlib.suppress(OSError):
                if (renders.read_listener(self.home) or {}).get("pid") == os.getpid():
                    os.unlink(renders.listener_file(self.home))
            self.renders.stop()
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGUSR2, signal.SIGUSR1):
                loop.remove_signal_handler(sig)
            # Ignored, not fatal, from here on: an exec to restart keeps that
            # until the new image handles it, and server.json may still say poke.
            signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    def stop(self):
        if self._stop is not None:
            self._stop.set()

    # -- restarting in place (docs/serve-restart-plan.md) ----------------------

    def _on_stop(self):
        """SIGINT/SIGTERM: a stop, even during a restart that waits for steps."""
        if self.restart is not None and not self._closing:
            from . import restart
            log.warning("stopping instead of restarting")
            restart.set_status(self.home, self.restart["ids"], "failed",
                               "wpkd was stopped instead")
            self.restart = None
        self._stop.set()

    def _on_poke(self):
        if self.runner is not None:
            self.runner.poke()

    def _on_restart(self):
        asyncio.ensure_future(self._restart_request())

    async def _restart_request(self):
        """SIGUSR2: restart in place once the new code loads. A request file
        (``wpk serve --restart``) may say ``force``; a bare signal waits."""
        from . import restart
        req = await asyncio.get_running_loop().run_in_executor(None, restart.take, self.home)
        rid, force = req.get("id"), bool(req.get("force"))
        if self.restart is not None:            # one is under way: join it
            self.restart["ids"].append(rid)
            if force and not self.restart["force"]:
                self.restart["force"] = True
                log.warning("restarting now: not waiting for running steps (--force)")
                if self.runner is not None:
                    self.runner.abandon()
            return
        if self._stop.is_set():
            restart.set_status(self.home, [rid], "failed", "wpkd is stopping")
            return
        why = await asyncio.get_running_loop().run_in_executor(None, restart.preflight)
        if why:
            log.error("not restarting: the code on disk does not load: %s", why)
            restart.set_status(self.home, [rid], "failed",
                               "the code on disk does not load: %s" % why)
            return
        if self._stop.is_set() or self.restart is not None:
            return
        self.restart = {"ids": [rid], "force": force}
        log.warning("restarting in place%s", " now (--force)" if force else "")
        self._stop.set()

    async def _adopt_ide(self):
        """The VS Code servers an earlier board left (an in-place restart, or a
        crash) are ours again at once, not when a tab next asks for one."""
        try:
            got = await self.ide.adopt()
        except Exception:                       # noqa: BLE001: the board still serves
            log.exception("taking over VS Code's servers failed")
            return
        if got:
            log.warning("took over %d VS Code server(s) left running: %s",
                        len(got), " ".join(got))

    async def _wait_steps(self):
        """Before a restart closes anything: start no new step and wait for the
        running ones, still serving, unless ``force`` (then the next image adopts
        them). Returns at once on a stop: the stop waits as it always has."""
        from . import restart
        r = self.runner
        if self.restart is None or r is None:
            return
        r.halt()
        if self.restart["force"]:
            r.abandon()
        said = None
        while self.restart is not None and r.alive:
            n = r.running()
            if n != said:
                if n:
                    log.warning("restart: waiting for %d running step(s)", n)
                restart.set_status(self.home, self.restart["ids"], "waiting",
                                   "%d running step(s)" % n)
                said = n
            await asyncio.sleep(0.25)
