"""Which loopback ports web VS Code may forward (port-forward plan §3.5).

A link to ``http://localhost:<port>/`` opened from web VS Code is forwarded
to that port on the host where the IDE runs: wpkd's own host, or the exec
host through ``ide_relay``. On a shared node other users' loopback servers
are one ``connect()`` away, so only a port whose listening socket belongs to
**this user's uid** is forwarded, and never one of the checking process's
own (the board's listeners, the relay's port).

Linux only: it reads ``/proc/net/tcp`` and ``tcp6``. Elsewhere nothing is
forwarded, and the reason says so.
"""

import ipaddress
import os

LISTEN = "0A"


def _addr(hexaddr):
    """``/proc/net/tcp*``'s address column to an ``ipaddress`` object."""
    if len(hexaddr) == 8:                    # IPv4: one little-endian word
        return ipaddress.IPv4Address(int(hexaddr, 16).to_bytes(4, "little"))
    words = [hexaddr[i:i + 8] for i in range(0, 32, 8)]
    return ipaddress.IPv6Address(b"".join(int(w, 16).to_bytes(4, "little") for w in words))


def listeners(port, proc="/proc"):
    """``[(address, uid, inode)]`` of the LISTEN sockets on ``port``."""
    out = []
    for name in ("tcp", "tcp6"):
        try:
            with open(os.path.join(proc, "net", name)) as fp:
                lines = fp.read().splitlines()[1:]
        except OSError:
            continue
        for ln in lines:
            f = ln.split()
            if len(f) < 10 or f[3] != LISTEN:
                continue
            host, _, p = f[1].partition(":")
            if int(p, 16) != port:
                continue
            out.append((_addr(host), int(f[7]), f[9]))
    return out


def _target(a):
    """The address to connect to for a socket bound to ``a``, or None if it
    is not reachable on loopback (a bind to the node's own network address)."""
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    if a.is_loopback:
        return str(a)
    if a.is_unspecified:
        return "127.0.0.1" if a.version == 4 else "::1"
    return None


def own_inodes(proc="/proc"):
    """The socket inodes this process holds."""
    d = os.path.join(proc, "self", "fd")
    out = set()
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        try:
            link = os.readlink(os.path.join(d, n))
        except OSError:
            continue
        if link.startswith("socket:["):
            out.add(link[len("socket:["):-1])
    return out


def check(port, uid=None, proc="/proc"):
    """``(host, None)``: forward to ``host:port``; or ``(None, why)``.

    Every loopback or wildcard listener on the port must be ``uid``'s (else
    a connect could reach another user's), at least one must exist, and none
    may be this process's own. Called before every forwarded connection: a
    port that is closed and taken by someone else is refused from then on."""
    if not 1 <= port <= 65535:
        return None, "port %d is out of range" % port
    if not os.path.exists(os.path.join(proc, "net", "tcp")):
        return None, "forwarding needs Linux (/proc/net/tcp); this host has none"
    uid = os.getuid() if uid is None else uid
    found = [(t, u, ino) for a, u, ino in listeners(port, proc)
             for t in [_target(a)] if t is not None]
    if not found:
        return None, "nothing listens on localhost:%d" % port
    if any(u != uid for _, u, _ in found):
        return None, "localhost:%d belongs to another user" % port
    if own_inodes(proc) & {ino for _, _, ino in found}:
        return None, "localhost:%d is wpk's own port (the board's or the relay's)" % port
    v4 = [t for t, _, _ in found if ":" not in t]
    return (v4 or [found[0][0]])[0], None
