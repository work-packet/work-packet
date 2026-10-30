"""The content origin (docs/studio-plan.md P0.6, decision D9).

What the studio shows but did not write itself (pages the agent made, a deck
tool's dev server, HTML inside documents) is never served on the board's own
origin, where its scripts could read the CSRF token and act as you. It is
served under ``/sc/<token>/<path>`` with ``Content-Security-Policy: sandbox
...``: an opaque origin with no cookies and no access to the board, framed by
the studio in ``<iframe sandbox="allow-scripts">``.

A token is a random capability for one directory (a studio's packet folder),
issued when the studio opens and revoked when it closes or expires. The
guard checks it in place of a login (``dash/guard.py``): a sandboxed frame
sends no cookies. Tokens live in this process only; the studio page asks for
one each time it loads.
"""

import mimetypes
import os
import secrets
import threading
import time

TTL_S = 12 * 3600
PREFIX = "/sc/"
# The headers of every /sc/ response (dash/guard.py adds them).
CSP = ("sandbox allow-scripts allow-popups allow-downloads; default-src 'self' data: blob: "
       "'unsafe-inline'; frame-ancestors 'self'; form-action 'none'; base-uri 'none'")
HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),      # the token is in the path: never send it on
    (b"cache-control", b"no-store"),
]


class Tokens:
    """token -> (root directory, expiry). Thread-safe."""

    def __init__(self, ttl_s=TTL_S, clock=time.time):
        self.ttl_s = ttl_s
        self.clock = clock
        self.lock = threading.Lock()
        self.by_token = {}

    def issue(self, root, ttl_s=None):
        tok = secrets.token_urlsafe(24)
        with self.lock:
            self.by_token[tok] = (os.path.realpath(root), self.clock() + (ttl_s or self.ttl_s))
        return tok

    def resolve(self, token):
        """The root directory of a live token, else None (an expired one is dropped)."""
        with self.lock:
            got = self.by_token.get(token or "")
            if got is None:
                return None
            if got[1] <= self.clock():
                del self.by_token[token]
                return None
            return got[0]

    def revoke(self, token):
        with self.lock:
            self.by_token.pop(token, None)

    def revoke_root(self, root):
        """Every token for ``root`` (the studio closed)."""
        root = os.path.realpath(root)
        with self.lock:
            for t in [t for t, (r, _) in self.by_token.items() if r == root]:
                del self.by_token[t]


TOKENS = Tokens()


def split(path):
    """``/sc/<token>/<rest>`` to ``(token, rest)``, else ``(None, None)``."""
    if not path.startswith(PREFIX):
        return None, None
    token, _, rest = path[len(PREFIX):].partition("/")
    return (token or None), rest


def file_for(root, rest):
    """The file under ``root`` that ``rest`` names, following no link out of
    it and into no dot-directory (``.work-packet``, ``.git``, ``.studio``); a
    directory gives its ``index.html``. None if there is none."""
    rest = rest or "index.html"
    if "\0" in rest or any(p.startswith(".") for p in rest.split("/") if p):
        return None
    p = os.path.realpath(os.path.join(root, *[x for x in rest.split("/") if x]))
    if p != root and not p.startswith(root + os.sep):
        return None
    if os.path.isdir(p):
        p = os.path.join(p, "index.html")
    return p if os.path.isfile(p) else None


def media_type(path):
    t, _ = mimetypes.guess_type(path)
    if t is None:
        return "application/octet-stream"
    return t + ("; charset=utf-8" if t.startswith("text/") or t in (
        "application/javascript", "application/json", "image/svg+xml") else "")
