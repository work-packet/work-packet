"""Sign in with a Unix account: a code, a drop file, a signed cookie
(docs/unix-login.md).

The login page shows a code. Whoever creates a file of that name in
``$WPK_HOME/login/`` (mode 1733: anyone may create, nobody else may list,
nobody may rename or delete another's file) is the user who owns the file,
as the kernel or the NFS server says. The browser that asked for the code
then gets a session cookie for that user.
"""

import base64
import hashlib
import hmac
import html
import os
import pwd
import secrets
import stat
import threading
import time
import urllib.parse

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"     # no 0/O, 1/I/L, U
CODE_LEN = 8                                          # ~39 bits
CODE_TTL_S = 600
MAX_PENDING = 256
DROP_MODE = 0o1733


def drop_dir(home):
    return os.path.join(home, "login")


def ensure_drop_dir(home):
    """Make ``login/`` (1733) and clear files left from codes that are gone."""
    d = drop_dir(home)
    os.makedirs(d, exist_ok=True)
    os.chmod(d, DROP_MODE)
    now = time.time()
    for name in os.listdir(d):
        p = os.path.join(d, name)
        try:
            if now - os.lstat(p).st_mtime > CODE_TTL_S:
                os.unlink(p)
        except OSError:
            pass
    return d


def reachable_by_others(home):
    """``None`` if other users can reach ``login/``, else the directory that stops them."""
    d = os.path.abspath(drop_dir(home))
    path = d
    while True:
        try:
            mode = os.stat(path).st_mode
        except OSError:
            return path
        if not mode & stat.S_IXOTH:
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def new_code():
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
    return raw[:4] + "-" + raw[4:]


def normal_code(text):
    """A code as typed (any case, with or without the dash) to its canonical form."""
    raw = "".join(c for c in (text or "").upper() if c.isalnum())
    if len(raw) != CODE_LEN or any(c not in CODE_ALPHABET for c in raw):
        return None
    return raw[:4] + "-" + raw[4:]


def drop(home, code):
    """``wpk login``: create the drop file for ``code`` in ``home``'s ``login/``."""
    c = normal_code(code)
    if c is None:
        raise ValueError("%r is not a sign-in code (like K7QF-29XA)" % code)
    path = os.path.join(drop_dir(home), c)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    os.close(fd)
    return path


def dropped_by(home, code):
    """The user who created ``login/<code>``, ``None`` if there is no such file
    yet; raises ``ValueError`` if a file is there but proves nothing."""
    d = drop_dir(home)
    try:
        names = os.listdir(d)       # also refreshes an NFS client's view of the directory
    except OSError:
        return None
    if code not in names:
        return None
    p = os.path.join(d, code)
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return None
    try:
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("login/%s is not a plain file" % code)
        if st.st_nlink != 1:
            raise ValueError("login/%s has more than one link" % code)
        try:
            return pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            raise ValueError("login/%s belongs to uid %d, who has no name here"
                             % (code, st.st_uid)) from None
    finally:
        try:
            os.unlink(p)
        except OSError:
            pass


class Pending:
    """Codes this server has shown, by the nonce in the asking browser's cookie."""

    def __init__(self, home, clock=time.time):
        self.home = home
        self.clock = clock
        self._lock = threading.Lock()
        self._by_nonce = {}         # nonce -> (code, issued)

    def start(self):
        now = self.clock()
        with self._lock:
            self._expire(now)
            while len(self._by_nonce) >= MAX_PENDING:
                del self._by_nonce[next(iter(self._by_nonce))]
            nonce = secrets.token_urlsafe(24)
            code = new_code()
            self._by_nonce[nonce] = (code, now)
        return nonce, code

    def code(self, nonce):
        with self._lock:
            self._expire(self.clock())
            got = self._by_nonce.get(nonce or "")
        return got[0] if got else None

    def poll(self, nonce):
        """``(user, None)`` once the drop file is there; ``(None, None)`` while
        waiting; ``(None, why)`` if the code is gone or the file proves nothing."""
        code = self.code(nonce)
        if code is None:
            return None, "that code has expired"
        try:
            user = dropped_by(self.home, code)
        except ValueError as e:
            self.forget(nonce)
            return None, str(e)
        if user is not None:
            self.forget(nonce)
        return user, None

    def forget(self, nonce):
        with self._lock:
            self._by_nonce.pop(nonce, None)

    def _expire(self, now):
        for n in [n for n, (_, t) in self._by_nonce.items() if now - t > CODE_TTL_S]:
            del self._by_nonce[n]


# -- the session cookie -------------------------------------------------------

def session_key(secret):
    return hmac.new(secret, b"session", hashlib.sha256).digest()


def _sig(key, body):
    return base64.urlsafe_b64encode(
        hmac.new(key, body.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def sign(key, user, days, now=None):
    exp = int((time.time() if now is None else now) + days * 86400)
    u = base64.urlsafe_b64encode(user.encode()).decode().rstrip("=")
    body = "%s.%d" % (u, exp)
    return body + "." + _sig(key, body)


def verify(key, value, now=None):
    """The user a cookie names, or ``None`` if it is forged or expired."""
    try:
        u, exp, sig = (value or "").split(".")
        body = "%s.%s" % (u, exp)
        if not hmac.compare_digest(sig, _sig(key, body)):
            return None
        if int(exp) < (time.time() if now is None else now):
            return None
        return base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None


def cookie_names(port):
    return "wpk_s_%d" % port, "wpk_l_%d" % port


def read_cookie(headers, name):
    for k, v in headers:
        if k != b"cookie":
            continue
        for part in v.decode("latin-1").split(";"):
            n, _, val = part.strip().partition("=")
            if n == name:
                return val
    return None


def set_cookie(name, value, max_age):
    return ("%s=%s; Max-Age=%d; Path=/; Secure; HttpOnly; SameSite=Lax"
            % (name, value, max_age)).encode()


# -- the gate the Guard asks ----------------------------------------------------

def safe_next(value):
    """Where to go after signing in: a path on this board, nothing else."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


class Gate:
    """Who holds a session on the network listener, and the sign-in itself."""

    def __init__(self, home, secret, port, owner, allow=(), days=30, clock=time.time):
        self.home = home
        self.secret = secret
        self.key = session_key(secret)
        self.owner = owner
        self.allow = tuple(allow)
        self.days = days
        self.clock = clock
        self.session_cookie, self.pending_cookie = cookie_names(port)
        self.pending = Pending(home, clock)

    def may_sign_in(self, user):
        return user == self.owner or user in self.allow

    def user_of(self, headers):
        user = verify(self.key, read_cookie(headers, self.session_cookie), self.clock())
        return user if user and self.may_sign_in(user) else None

    def csrf(self, user):
        return hmac.new(self.secret, b"csrf|" + user.encode(), hashlib.sha256).hexdigest()

    def session_header(self, user):
        return set_cookie(self.session_cookie, sign(self.key, user, self.days, self.clock()),
                          self.days * 86400)

    def clear_headers(self, *names):
        return [(b"set-cookie", set_cookie(n, "", 0)) for n in names]

    def login(self, headers, query):
        """``GET /login``: ``(status, extra headers, html or None)``. Called in a thread:
        it may look at the drop directory."""
        qs = _parse_qs(query)
        nxt = safe_next(qs.get("next"))
        if self.user_of(headers):
            return 303, [(b"location", nxt.encode())], None
        nonce = read_cookie(headers, self.pending_cookie)
        note = None
        code = self.pending.code(nonce)
        if code is not None:
            user, why = self.pending.poll(nonce)
            if user is not None and self.may_sign_in(user):
                return 303, [(b"location", nxt.encode()),
                             (b"set-cookie", self.session_header(user))] + \
                    self.clear_headers(self.pending_cookie), None
            if user is not None:
                note = ("%s may not use this board: it is %s's, and %s is not in "
                        "[server] allow" % (user, self.owner, user))
            elif why:
                note = why
            else:
                return 200, [], self.page(code, nxt)
        nonce, code = self.pending.start()
        return 200, [(b"set-cookie", set_cookie(self.pending_cookie, nonce, CODE_TTL_S))], \
            self.page(code, nxt, note)

    def page(self, code, nxt, note=None):
        drop_path = os.path.join(os.path.abspath(drop_dir(self.home)), code)
        return LOGIN_PAGE.format(
            code=_esc(code), owner=_esc(self.owner), touch=_esc("touch " + drop_path),
            refresh=_esc("/login?next=" + urllib.parse.quote(nxt, safe="/")),
            note=('<p class="note">%s</p>' % _esc(note)) if note else "",
            other="" if not self.allow else
            '<p class="muted">Not %s? Use <code>wpk login %s --home %s</code> or the '
            'second line; you get read-only access.</p>'
            % (_esc(self.owner), _esc(code), _esc(os.path.abspath(self.home))))


def _parse_qs(query):
    q = urllib.parse.parse_qs((query or b"").decode("latin-1"))
    return {k: v[0] for k, v in q.items()}


def _esc(s):
    return html.escape(s, quote=True)


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="2; url={refresh}">
<title>Sign in · work-packet</title>
<style>
:root {{ color-scheme: light dark; --fg:#1d1f23; --bg:#f6f6f4; --card:#fff; --muted:#6b6f76;
        --line:#dcdcd8; --code:#eef0f3; --warn:#9a3b00; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fg:#e6e6e3; --bg:#17181a; --card:#202124;
        --muted:#9a9ea5; --line:#34363a; --code:#2a2c30; --warn:#ffb27a; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg);
        font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:560px; margin:12vh auto; padding:0 16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:24px; }}
h1 {{ font-size:18px; margin:0 0 4px; }}
.code {{ font:600 28px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing:2px;
        margin:16px 0; }}
pre {{ background:var(--code); border-radius:6px; padding:10px 12px; overflow-x:auto;
        font:13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; margin:6px 0; }}
.muted {{ color:var(--muted); font-size:13px; }}
.note {{ color:var(--warn); }}
</style></head>
<body><main><div class="card">
<h1>Sign in to {owner}'s board</h1>
<p class="muted">Prove who you are from any shell on the cluster. This page carries on by itself.</p>
{note}
<div class="code">{code}</div>
<pre>wpk login {code}</pre>
<p class="muted">or, without wpk:</p>
<pre>{touch}</pre>
{other}
<p class="muted">Only run this for a code shown in your own browser. The code lasts 10 minutes.</p>
</div></main></body></html>
"""
