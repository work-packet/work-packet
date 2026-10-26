"""Checks ahead of every route of the board (server.md §2.1, §4).

``Guard`` wraps the board once per listener. On the loopback listener the
caller is the local user; on the tailnet listener tailscaled says who it is,
and only logins in ``allow`` get in. On both: the ``Host`` header must name
this machine (DNS rebinding), and a request that can change something must
come from the board's own origin and carry the CSRF token.
"""

import hashlib
import hmac
import ipaddress
import logging
import urllib.parse

import anyio

log = logging.getLogger("wpk.dash")

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")
FORM_MAX = 1 << 20
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
]
IDE_PREFIX = "/ide/"
IDE_HEADERS = (b"x-content-type-options", b"referrer-policy")
# Set by a proxy in front of us. On the loopback listener they mean the
# request did not start on this machine (e.g. `tailscale serve` to 127.0.0.1).
PROXY_HEADERS = (b"forwarded", b"x-forwarded-for", b"x-forwarded-host", b"x-real-ip",
                 b"via")


def csrf_token(secret):
    return hmac.new(secret, b"csrf", hashlib.sha256).hexdigest()


def split_host(value):
    """``Host`` header to ``(name, port or None)``; name lower-cased, IPv6 unbracketed."""
    value = value.strip().lower()
    if value.startswith("["):
        name, _, rest = value[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else None
    else:
        name, sep, port = value.rpartition(":")
        if not sep:
            name, port = value, None
    if port is not None and not port.isdigit():
        return None, None
    return name, int(port) if port else None


def is_loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


class Guard:
    def __init__(self, app, kind, secret, tailnet=None, allow=(), extra_hosts=(),
                 local_user=None):
        assert kind in ("loopback", "tailnet", "unix")
        if kind == "tailnet" and tailnet is None:
            raise ValueError("the tailnet listener needs tailscaled")
        self.app = app
        self.kind = kind
        self.tailnet = tailnet
        self.allow = tuple(allow)
        self.extra_hosts = tuple(h.lower() for h in extra_hosts)
        self.local_user = local_user
        self.token = csrf_token(secret)

    # -- the checks -------------------------------------------------------

    def host_names(self):
        names = set(LOOPBACK_NAMES) | set(self.extra_hosts)
        if self.tailnet is not None:
            names |= self.tailnet.names() | {ip.lower() for ip in self.tailnet.ips()}
        return names

    def host_ok(self, host, scope):
        name, port = split_host(host or "")
        if not name or name not in self.host_names():
            return False
        if self.kind == "unix":       # reached by ssh -L: the laptop's port is not ours
            return name in LOOPBACK_NAMES or name in self.extra_hosts
        default = 443 if scope.get("scheme") in ("https", "wss") else 80
        server = scope.get("server") or (None, None)
        return (port or default) == server[1]

    def allowed(self):
        if self.allow:
            return self.allow
        owner = self.tailnet.owner()
        return (owner,) if owner else ()

    def who(self, client):
        """The caller's login, or ``(None, why)``."""
        if not client:
            return None, "no peer address"
        got = self.tailnet.whois(client[0], client[1])
        if got is None:
            return None, "%s is not a user's device on this tailnet" % client[0]
        login, node = got
        if login not in self.allowed():
            return None, "%s (%s) is not allowed" % (login, node)
        return login, None

    def origin_ok(self, origin, host, scope):
        if not origin or origin == "null":
            return False
        u = urllib.parse.urlsplit(origin)
        want = {"ws": "http", "wss": "https"}.get(scope.get("scheme"), scope.get("scheme", "http"))
        return u.scheme == want and u.netloc.lower() == host.lower()

    # -- ASGI ---------------------------------------------------------------

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] not in ("http", "websocket"):
            return await _refuse(send, 403, "not served here", scope)
        ws = scope["type"] == "websocket"
        headers = scope["headers"]
        host = _header(headers, b"host")
        if not self.host_ok(host, scope):
            return await _refuse(send, 421, "unknown host name: %r" % (host,), scope)

        if self.kind in ("loopback", "unix"):     # unix: only this user can connect (0700)
            if any(k in PROXY_HEADERS or k.startswith(b"tailscale-") for k, _ in headers):
                return await _refuse(send, 403, "this board was reached through a proxy; "
                                     "use its tailnet address instead", scope)
            user = self.local_user
        else:
            user, why = await anyio.to_thread.run_sync(self.who, scope.get("client"))
            if user is None:
                log.warning("refused: %s", why)
                return await _refuse(send, 403, "not allowed: %s" % why, scope)
        scope.setdefault("state", {})["user"] = user
        scope["state"]["csrf"] = self.token       # the pages put it in every form
        scope["state"]["listener"] = self.kind

        if ws:
            # A WebSocket is not covered by the same-origin policy, so the Origin
            # must match; the app checks the CSRF token in the first message
            # (docs/dash-tasks.md §5.5).
            if not self.origin_ok(_header(headers, b"origin"), host, scope):
                log.warning("refused a WebSocket to %s: Origin %r does not match Host %r",
                            scope.get("path"), _header(headers, b"origin"), host)
                return await _refuse(send, 403, "cross-origin WebSocket refused", scope)
            return await self.app(scope, receive, send)

        ide = scope.get("path", "").startswith(IDE_PREFIX)
        if scope["method"] not in SAFE_METHODS:
            if not self.origin_ok(_header(headers, b"origin"), host, scope):
                return await _refuse(send, 403, "cross-origin request refused", scope)
        if scope["method"] not in SAFE_METHODS and not ide:
            # Web VS Code's own requests carry no token; the Origin check above
            # is what stops another site (docs/vscode-plan.md §4.1).
            receive, token = await self._token(headers, receive, scope)
            if not (token and hmac.compare_digest(token, self.token)):
                return await _refuse(send, 403, "missing or wrong CSRF token", scope)

        # 'self' covers ws: and wss: in CSP 3, but older Safari wants them named:
        # the shell's WebSocket goes to this same host (docs/dash-tasks.md §5).
        ws_src = ("; connect-src 'self' ws://%s wss://%s" % (host, host)).encode()
        extra = [(k, v + ws_src if k == b"content-security-policy" else v)
                 for k, v in SECURITY_HEADERS]
        if ide:     # VS Code sends its own CSP, and frames its own pages
            extra = [(k, v) for k, v in SECURITY_HEADERS if k in IDE_HEADERS]

        async def send_with_headers(msg):
            if msg["type"] == "http.response.start":
                have = {k.lower() for k, _ in msg.get("headers", [])}
                msg = dict(msg, headers=list(msg.get("headers", [])) +
                           [(k, v) for k, v in extra if k not in have])
            await send(msg)

        await self.app(scope, receive, send_with_headers)

    async def _token(self, headers, receive, scope=None):
        """The CSRF token from the header or a urlencoded form; and a ``receive``
        that replays the body if it had to be read."""
        token = _header(headers, b"x-csrf-token")
        ctype = _header(headers, b"content-type").split(";")[0].strip().lower()
        if not token and ctype == "multipart/form-data":
            # an upload form: its action URL carries the token (the body is a file)
            qs = urllib.parse.parse_qs(((scope or {}).get("query_string") or b"").decode("latin-1"))
            token = (qs.get("csrf") or [None])[0]
        if token or ctype != "application/x-www-form-urlencoded":
            return receive, token
        body, more = b"", True
        while more:
            msg = await receive()
            if msg["type"] != "http.request":
                return receive, None
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
            if len(body) > FORM_MAX:
                return receive, None
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        token = (urllib.parse.parse_qs(body.decode("latin-1")).get("csrf") or [None])[0]
        return replay, token


def _header(headers, name):
    for k, v in headers:
        if k == name:
            return v.decode("latin-1")
    return ""


async def _refuse(send, status, why, scope):
    if scope["type"] != "http":
        if scope["type"] == "websocket":   # the page cannot show why; the log can
            log.warning("refused a WebSocket to %s: %s", scope.get("path"), why)
        return await send({"type": "websocket.close", "code": 1008})
    body = ("%d %s\n" % (status, why)).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(body)).encode())] + SECURITY_HEADERS})
    await send({"type": "http.response.body", "body": body})
