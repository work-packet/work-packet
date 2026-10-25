"""A small client for tailscaled's LocalAPI (server.md §2).

The LocalAPI is HTTP over a unix socket. ``whois`` and ``status`` answer any
local user, so none of this needs root.
"""

import http.client
import json
import os
import socket
import threading
import time
import urllib.parse

SOCKET = "/var/run/tailscale/tailscaled.sock"
WHOIS_TTL_S = 60
WHOIS_MISS_TTL_S = 5     # a device that just joined is not refused for long
STATUS_TTL_S = 30


def socket_path():
    return os.environ.get("WPK_TAILSCALE_SOCKET") or SOCKET


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("local-tailscaled.sock", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def get(path, sock=None, timeout=5):
    """GET ``path`` from the LocalAPI: the parsed JSON, or None on any failure."""
    conn = _UnixConnection(sock or socket_path(), timeout)
    try:
        conn.request("GET", path, headers={"Sec-Tailscale": "localapi"})
        r = conn.getresponse()
        body = r.read()
        if r.status != 200:
            return None
        return json.loads(body)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


class Tailnet:
    """This node's view of the tailnet, cached: its addresses, names, owner and peers."""

    def __init__(self, sock=None, clock=time.monotonic):
        self.sock = sock
        self._clock = clock
        self._lock = threading.Lock()
        self._status = (None, -1e9)
        self._whois = {}

    def status(self, fresh=False):
        with self._lock:
            st, t = self._status
        if fresh or self._clock() - t > STATUS_TTL_S:
            st = get("/localapi/v0/status?peers=false", self.sock)
            if st is not None and st.get("BackendState") != "Running":
                st = None
            with self._lock:
                self._status = (st, self._clock())
        return st

    def ips(self):
        st = self.status()
        return list((st or {}).get("TailscaleIPs") or [])

    def names(self):
        """Host names this node answers to: MagicDNS short name, FQDN, cert domains."""
        st = self.status() or {}
        out = set()
        fq = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".").lower()
        if fq:
            out.update((fq, fq.split(".")[0]))
        out.update(d.lower() for d in st.get("CertDomains") or [])
        return out

    def owner(self):
        """The login name of the user who owns this node, or None (tagged, or down)."""
        st = self.status() or {}
        me = st.get("Self") or {}
        if me.get("Tags"):
            return None
        u = (st.get("User") or {}).get(str(me.get("UserID")))
        return (u or {}).get("LoginName")

    def whois(self, ip, port):
        """``(login, node)`` for a peer, or None if it is not a user's node on the tailnet."""
        now = self._clock()
        with self._lock:
            hit = self._whois.get(ip)
        if hit and now - hit[1] < (WHOIS_TTL_S if hit[0] else WHOIS_MISS_TTL_S):
            return hit[0]
        host = "[%s]" % ip if ":" in ip else ip
        d = get("/localapi/v0/whois?addr=" + urllib.parse.quote("%s:%d" % (host, port)),
                self.sock)
        who = None
        if d:
            node, user = d.get("Node") or {}, d.get("UserProfile") or {}
            if not node.get("Tags") and user.get("LoginName"):
                who = (user["LoginName"], (node.get("Name") or "").rstrip("."))
        with self._lock:
            self._whois[ip] = (who, now)
        return who
