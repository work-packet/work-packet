"""Localhost links from web VS Code (port-forward plan, beside docs/vscode-plan.md §4).

An extension (or a terminal link) opens ``http://localhost:<port>/...``. In
the browser that is the laptop, not the host where VS Code's server runs, so
the workbench's shim (``ide_forward.js``) sends the link to
``/ide/<key>/__wpk/open?u=<url>`` instead. That answers 303 to
``/fwd/<token>/<path>``, and ``/fwd/`` proxies to the port where the server
runs: on wpkd's host directly, or through the job's relay (``ide_relay``) with
the port in the TLS server name.

A forwarded page is untrusted content, served as ``/sc/`` is
(``dash/guard.py``): a sandboxed opaque origin, no cookies, GET and HEAD only,
and the token in the path is the only check. A token is bound to the server's
process (or the job's certificate), and dies with it: a new server's ports
belong to other processes.
"""

import contextlib
import json
import os
import re
import secrets
import threading
import time
import urllib.parse

from .ide import HOP, IdeUnavailable, IdeWaiting, Unforwardable

PREFIX = "/fwd/"
IDLE_S = 3600
TTL_S = 12 * 3600
LOOPBACK = ("localhost", "127.0.0.1", "::1")
# The headers of every /fwd/ answer (dash/guard.py adds them). The upstream's own
# CSP is kept: both apply. allow-modals: window.print().
CSP = ("sandbox allow-scripts allow-forms allow-modals allow-popups allow-downloads; "
       "frame-ancestors 'none'")
HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"referrer-policy", b"no-referrer"),      # the token is in the path: never send it on
    # an opaque origin reads its own answers (fetch("completed")) only with CORS;
    # with no credentials, "*" gives nothing to anyone without the token
    (b"access-control-allow-origin", b"*"),
]
# No nosniff of ours: the page is an opaque origin, so every answer is checked
# as cross-origin, and with nosniff Chrome's ORB blocks a mislabelled script or
# stylesheet the page loads fine on its own origin (vscode-print serves a script
# as application/json and a stylesheet as text/plain). The upstream's own stays.
# What the guard drops from upstream before adding HEADERS:
DROP = {b"set-cookie", b"referrer-policy", b"access-control-allow-origin",
        b"access-control-allow-credentials"}
SELF_ORIGIN = re.compile(rb"https?://(?:localhost|127\.0\.0\.1|\[::1\]):(\d+)(?![\d])", re.I)
UPSTREAM_LOCATION = re.compile(r"https?://(localhost|127\.0\.0\.1|\[::1\]):(\d+)(/[^#]*)?(#.*)?\Z",
                               re.I)


class Forward:
    """What a token opens: ``port`` where server ``key`` runs, while it is ``identity``."""

    def __init__(self, key, port, identity, now):
        self.key, self.port, self.identity = key, port, identity
        self.issued = self.used = now


class Tokens:
    """token -> ``Forward``; idle and total lifetimes. Thread-safe."""

    def __init__(self, idle_s=IDLE_S, ttl_s=TTL_S, clock=time.time):
        self.idle_s, self.ttl_s, self.clock = idle_s, ttl_s, clock
        self.lock = threading.Lock()
        self.by_token = {}

    def _live(self, f, now):
        return now - f.used < self.idle_s and now - f.issued < self.ttl_s

    def issue(self, key, port, identity):
        """A token for ``(key, port, identity)``: the live one, or a new one."""
        now = self.clock()
        with self.lock:
            for t, f in list(self.by_token.items()):
                if not self._live(f, now):
                    del self.by_token[t]
                elif (f.key, f.port, f.identity) == (key, port, identity):
                    f.used = now
                    return t
            tok = secrets.token_urlsafe(24)
            self.by_token[tok] = Forward(key, port, identity, now)
            return tok

    def resolve(self, token):
        """The ``Forward`` of a live token, else None (an expired one is dropped)."""
        now = self.clock()
        with self.lock:
            f = self.by_token.get(token or "")
            if f is None:
                return None
            if not self._live(f, now):
                del self.by_token[token]
                return None
            f.used = now
            return f

    def revoke(self, token):
        with self.lock:
            self.by_token.pop(token, None)

    def save(self, path):
        """Write the live tokens for the image an in-place restart execs into
        (restart.py); ``load`` takes them back. Owner-only: they are bearer keys."""
        from .. import fsutil
        now = self.clock()
        with self.lock:
            rows = [{"token": t, "key": f.key, "port": f.port, "identity": f.identity,
                     "issued": f.issued, "used": f.used}
                    for t, f in self.by_token.items() if self._live(f, now)]
        if not rows:
            return
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fsutil.atomic_write(path, json.dumps(rows) + "\n")
        os.chmod(path, 0o600)

    def load(self, path):
        """The tokens ``save`` left, still live; the file is removed either way."""
        try:
            with open(path) as fp:
                rows = json.load(fp)
        except (OSError, ValueError):
            rows = []
        with contextlib.suppress(OSError):
            os.unlink(path)
        now = self.clock()
        with self.lock:
            for r in rows if isinstance(rows, list) else ():
                try:
                    f = Forward(r["key"], int(r["port"]), r["identity"], 0)
                    f.issued, f.used = float(r["issued"]), float(r["used"])
                    tok = str(r["token"])
                except (KeyError, TypeError, ValueError):
                    continue
                if self._live(f, now):
                    self.by_token[tok] = f


def saved_path(home):
    """Where the forward tokens wait across an in-place restart."""
    return os.path.join(home, "run", "fwd-tokens.json")


TOKENS = Tokens()


def split(path):
    """``/fwd/<token>/<rest>`` to ``(token, rest)``, else ``(None, None)``."""
    if not path.startswith(PREFIX):
        return None, None
    token, _, rest = path[len(PREFIX):].partition("/")
    return (token or None), rest


def parse_link(u):
    """A localhost link to ``(port, path?query#fragment)``, else None."""
    try:
        p = urllib.parse.urlsplit(u or "")
        port = p.port
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or (p.hostname or "").lower() not in LOOPBACK:
        return None
    if port is None:
        port = 443 if p.scheme == "https" else 80
    if not 1 <= port <= 65535:
        return None
    rest = (p.path or "/") + ("?" + p.query if p.query else "") + \
        ("#" + p.fragment if p.fragment else "")
    return port, rest


def rewrite_location(value, port, base):
    """An upstream redirect to its own origin, or to a root path, stays under ``base``."""
    m = UPSTREAM_LOCATION.match(value)
    if m and int(m.group(2)) == port:
        return base + (m.group(3) or "/") + (m.group(4) or "")
    if value.startswith("/") and not value.startswith("//"):
        return base + value
    return value


def rewrite_html(body, port, base):
    """The page's own origin, written out in its HTML, under ``base``: vscode-print
    sets ``<base href="http://localhost:<port>/<session>/">``, so even its
    relative links would leave the board. URLs a script builds are not reached."""
    return SELF_ORIGIN.sub(lambda m: base.encode() if int(m.group(1)) == port else m.group(0),
                           body)


def _refused(status, why):
    from starlette.responses import PlainTextResponse
    return PlainTextResponse("%d %s\n" % (status, why), status_code=status)


async def open_link(backends, backend, request):
    """``GET /ide/<key>/__wpk/open?u=<url>``: the owner's click (the guard
    keeps ``/ide/`` to the owner), from the workbench itself; 303 to ``/fwd/``."""
    from starlette.responses import RedirectResponse
    if not backend.cfg.get("forward", True):
        return _refused(404, "forwarding localhost links is off ([ide] forward = false)")
    if request.method not in ("GET", "HEAD"):
        return _refused(405, "GET only")
    # A cross-site page must not send you to a GET on a local app (CSRF on it).
    if request.headers.get("sec-fetch-site") != "same-origin":
        return _refused(403, "a localhost link opens from web VS Code only")
    link = parse_link(request.query_params.get("u"))
    if link is None:
        return _refused(400, "not a localhost http(s) link: %r" % request.query_params.get("u"))
    port, rest = link
    try:
        await backends.ensure(backend)
    except (IdeWaiting, IdeUnavailable) as e:
        return _refused(503, "VS Code's server is not up: %s" % e)
    try:
        backend.forward(port)
    except Unforwardable as e:
        return _refused(e.status, str(e))
    identity = backend.forward_identity()
    if identity is None:
        return _refused(503, "VS Code's server is not running")
    tok = TOKENS.issue(backend.key, port, identity)
    return RedirectResponse(PREFIX + tok + rest, status_code=303)


async def proxy_forward(backends, request):
    """``/fwd/<token>/<rest>`` to ``localhost:<port><rest>`` where the server runs."""
    from starlette.background import BackgroundTask
    from starlette.responses import StreamingResponse
    token = request.path_params["token"]
    f = request.scope.get("state", {}).get("forward") or TOKENS.resolve(token)
    if f is None:
        return _refused(403, "no such forwarded page, or it has expired; "
                             "open the link again from VS Code")
    if request.method not in ("GET", "HEAD"):
        return _refused(405, "a forwarded page is read-only")
    be = backends.get(f.key)
    if be is None or be.forward_identity() != f.identity:
        TOKENS.revoke(token)
        return _refused(410, "the VS Code server this page came from has stopped; "
                             "open the link again from VS Code")
    try:
        hc, origin, ext = be.forward(f.port)
    except Unforwardable as e:
        return _refused(e.status, str(e))
    base = PREFIX + token
    raw = (request.scope.get("raw_path") or request.url.path.encode()).decode("latin-1")
    rest = raw[len(base):] or "/"
    qs = request.scope.get("query_string", b"").decode("latin-1")
    headers = [(k, v) for k, v in request.headers.items()
               if k.lower() not in HOP and k.lower() not in ("origin", "referer")]
    # Dev servers refuse a Host they do not know (DNS rebinding): it is localhost to them.
    headers.append(("host", "localhost:%d" % f.port))
    req = hc.build_request(request.method, origin + rest + ("?" + qs if qs else ""),
                           headers=headers, extensions=ext)
    be.last = be.forwarded = be._clock()
    try:
        r = await hc.send(req, stream=True)
    except Exception as e:          # httpx's transport errors
        return _refused(502, "localhost:%d did not answer: %s" % (f.port, e))
    out = []
    for k, v in r.headers.multi_items():
        k = k.lower()
        if k in ("connection", "keep-alive", "transfer-encoding", "content-length"):
            continue
        if k == "location":
            v = rewrite_location(v, f.port, base)
        out.append((k.encode("latin-1"), v.encode("latin-1")))
    if r.headers.get("content-type", "").startswith("text/html"):
        from starlette.responses import Response
        body = rewrite_html(await r.aread(), f.port, base)
        await r.aclose()
        resp = Response(body, status_code=r.status_code)
        # aread() decoded the body: it goes out as it is now
        resp.raw_headers = [(k, v) for k, v in out if k != b"content-encoding"] + \
            [(b"content-length", str(len(body)).encode())]
        return resp
    resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code,
                             background=BackgroundTask(r.aclose))
    resp.raw_headers = out
    return resp
