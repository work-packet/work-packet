"""A TLS 1.3 relay in front of a unix socket, for an IDE job (docs/scheduler.md §8.1).

    python -m work_packet.sched.ide_relay --sock S --client-cert C --key-dir LOCAL --publish-dir DIR

Listens on a free TCP port with a required client certificate: only wpkd's
(``--client-cert``) is accepted; plain HTTP, or any other peer, fails the TLS
handshake. After the handshake the stream is spliced byte for byte to the unix
socket, so HTTP and WebSocket upgrades pass through unchanged.

A connection whose TLS server name is ``p<port>.fwd.wpk`` is spliced instead
to ``localhost:<port>`` on this host: a page an extension serves, forwarded to
the browser (port-forward plan §3.4). Only a port this user listens on, and not
the relay's own, is reached (``ide_ports.check``, before every connection);
otherwise the relay answers the request itself with a 403 or 502 saying why.
Any other server name goes to the unix socket, as before. ``features`` in the
publish directory tells wpkd this relay knows the rule.

The job's key is made in ``--key-dir`` (local to the node, 0700) and never
leaves it. ``--publish-dir`` (the shared server directory) gets only the public
``server.crt``, its ``fingerprint``, ``features``, and, last, ``endpoint``
(``host:port``).
It exits on SIGTERM, or when nothing answers on the socket any more.
"""
import argparse
import asyncio
import os
import re
import signal
import socket
import sys

from . import ide_tls
from .. import ide_ports

CHUNK = 65536
FORWARD = re.compile(r"p(\d{1,5})\.fwd\.wpk\Z")
FEATURES = "fwd-sni\n"


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


def _sni(sslobj, name, ctx):
    """Remember the server name for ``_handle`` (the handshake goes on)."""
    sslobj.wpk_name = name


async def _answer(reader, writer, status, why):
    """An HTTP answer of the relay's own, after reading the request's head
    (closing on unread data would reset the connection and lose the answer)."""
    try:
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError,
            ConnectionError, OSError):
        pass
    body = (why + "\n").encode()
    writer.write(b"HTTP/1.1 %s\r\ncontent-type: text/plain; charset=utf-8\r\n"
                 b"content-length: %d\r\nconnection: close\r\n\r\n%s"
                 % (status.encode(), len(body), body))
    try:
        await writer.drain()
    except (ConnectionError, OSError):
        pass
    writer.close()


async def _open_forward(reader, writer, port):
    """A connection to ``localhost:<port>`` here, or None (answered already)."""
    host, why = ide_ports.check(port)
    if host is None:
        await _answer(reader, writer, "403 Forbidden", why)
        return None
    try:
        return await asyncio.open_connection(host, port)
    except OSError as e:
        await _answer(reader, writer, "502 Bad Gateway", "localhost:%d: %s" % (port, e))
        return None


async def _handle(sock_path, reader, writer):
    so = writer.get_extra_info("ssl_object")
    m = FORWARD.match(getattr(so, "wpk_name", None) or "")
    try:
        if m:
            up = await _open_forward(reader, writer, int(m.group(1)))
            if up is None:
                return
            ur, uw = up
        else:
            ur, uw = await asyncio.open_unix_connection(sock_path)
    except OSError:
        writer.close()
        return
    t1 = asyncio.ensure_future(_pump(reader, uw))
    t2 = asyncio.ensure_future(_pump(ur, writer))
    try:
        await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (t1, t2):
            t.cancel()
        await asyncio.gather(t1, t2, return_exceptions=True)


def _publish(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


async def _watch(sock_path, stop, interval=1.0, misses=3):
    bad = 0
    while not stop.is_set():
        await asyncio.sleep(interval)
        try:
            _, w = await asyncio.open_unix_connection(sock_path)
            w.close()
            bad = 0
        except OSError:
            bad += 1
            if bad >= misses:
                stop.set()


async def serve(sock_path, client_crt, key_dir, publish_dir, host="0.0.0.0", port=0):
    os.makedirs(key_dir, mode=0o700, exist_ok=True)
    os.chmod(key_dir, 0o700)
    key, crt = os.path.join(key_dir, "server.key"), os.path.join(key_dir, "server.crt")
    ide_tls.make_cert(key, crt, ide_tls.SERVER_DAYS, "wpk-ide-relay")
    ctx = ide_tls.pinned_server_context(crt, key, client_crt)
    ctx.sni_callback = _sni
    stop = asyncio.Event()
    srv = await asyncio.start_server(lambda r, w: _handle(sock_path, r, w), host, port, ssl=ctx)
    port = srv.sockets[0].getsockname()[1]
    with open(crt) as f:
        _publish(os.path.join(publish_dir, "server.crt"), f.read())
    _publish(os.path.join(publish_dir, "fingerprint"), ide_tls.fingerprint(crt) + "\n")
    _publish(os.path.join(publish_dir, "features"), FEATURES)
    _publish(os.path.join(publish_dir, "endpoint"), "%s:%d\n" % (socket.gethostname(), port))
    watcher = asyncio.ensure_future(_watch(sock_path, stop))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        for n in ("endpoint", "features"):
            try:
                os.unlink(os.path.join(publish_dir, n))
            except OSError:
                pass
        srv.close()
        await srv.wait_closed()
        watcher.cancel()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m work_packet.sched.ide_relay")
    ap.add_argument("--sock", required=True)
    ap.add_argument("--client-cert", required=True)
    ap.add_argument("--key-dir", required=True)
    ap.add_argument("--publish-dir", required=True)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args(argv)
    asyncio.run(serve(a.sock, a.client_cert, a.key_dir, a.publish_dir, a.host, a.port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
