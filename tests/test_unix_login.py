"""Signing in with a Unix account on the network listener (docs/unix-login.md)."""

import getpass
import os
import re
import ssl
import subprocess
import shutil

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.applications import Starlette          # noqa: E402
from starlette.responses import PlainTextResponse     # noqa: E402
from starlette.routing import Route                   # noqa: E402
from starlette.testclient import TestClient           # noqa: E402

from work_packet import schema                        # noqa: E402
from work_packet.dash import login                    # noqa: E402
from work_packet.dash.guard import Guard, csrf_token  # noqa: E402

SECRET = b"k" * 32
ME = getpass.getuser()
BASE = "https://board.example:7878"


def _app():
    async def page(request):
        return PlainTextResponse("page for %s, token %s" % (request.state.user,
                                                             request.state.csrf))

    async def act(request):
        return PlainTextResponse("did it as %s" % request.state.user)
    return Starlette(routes=[Route("/", page), Route("/p/x", page),
                             Route("/act", act, methods=["POST"])])


def _client(tmp_path, allow=(), owner=ME):
    home = str(tmp_path / "home")
    os.makedirs(home, exist_ok=True)
    login.ensure_drop_dir(home)
    gate = login.Gate(home, SECRET, 7878, owner, allow)
    g = Guard(_app(), "network", SECRET, gate=gate, names=["board.example"])
    return TestClient(g, base_url=BASE, follow_redirects=False), gate, home


def _code(text):
    return re.search(r'class="code">([A-Z0-9-]+)<', text).group(1)


def _sign_in(c, home):
    r = c.get("/login")
    login.drop(home, _code(r.text))
    return c.get("/login")


# -- the drop file -------------------------------------------------------------

def test_drop_dir_mode(tmp_path):
    d = login.ensure_drop_dir(str(tmp_path))
    assert os.stat(d).st_mode & 0o7777 == 0o1733


def test_dropped_by_names_the_owner_and_eats_the_file(tmp_path):
    home = str(tmp_path)
    login.ensure_drop_dir(home)
    assert login.dropped_by(home, "ABCD-EFGH") is None
    p = login.drop(home, "abcd efgh")                 # any case, any separator
    assert p.endswith("ABCD-EFGH")
    assert login.dropped_by(home, "ABCD-EFGH") == ME
    assert not os.path.exists(p)


def test_symlinks_and_hard_links_prove_nothing(tmp_path):
    home = str(tmp_path)
    d = login.ensure_drop_dir(home)
    other = tmp_path / "mine"
    other.write_text("x")
    os.symlink(other, os.path.join(d, "AAAA-BBBB"))
    with pytest.raises(ValueError, match="not a plain file"):
        login.dropped_by(home, "AAAA-BBBB")
    os.link(other, os.path.join(d, "CCCC-DDDD"))
    with pytest.raises(ValueError, match="more than one link"):
        login.dropped_by(home, "CCCC-DDDD")


def test_bad_codes_are_refused():
    assert login.normal_code("K7QF-29XA") == "K7QF-29XA"
    for bad in ("", "K7QF-29X", "K7QF-29XA0", "../../etc", "K7QF-29XO"):
        assert login.normal_code(bad) is None


# -- the session cookie ----------------------------------------------------------

def test_cookie_signs_and_expires():
    key = login.session_key(SECRET)
    v = login.sign(key, "alice", 1, now=1000)
    assert login.verify(key, v, now=1000) == "alice"
    assert login.verify(key, v, now=1000 + 86401) is None
    assert login.verify(login.session_key(b"x" * 32), v, now=1000) is None
    forged = login.sign(key, "alice", 1, now=1000).replace(
        login.sign(key, "alice", 1, now=1000).split(".")[0], "Ym9i")    # "bob"
    assert login.verify(key, forged, now=1000) is None
    assert login.verify(key, "junk") is None


# -- the Guard -------------------------------------------------------------------

def test_signed_out_goes_to_login_with_next(tmp_path):
    c, _, _ = _client(tmp_path)
    r = c.get("/p/x?tab=log")
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=/p/x%3Ftab%3Dlog"
    assert c.post("/act").status_code == 401


def test_sign_in_end_to_end(tmp_path):
    c, gate, home = _client(tmp_path)
    r = c.get("/login?next=/p/x")
    assert r.status_code == 200 and "wpk login" in r.text
    assert "no-store" in r.headers["cache-control"]
    code = _code(r.text)
    assert c.get("/login?next=/p/x").status_code == 200       # still waiting: same code
    assert _code(c.get("/login").text) == code
    login.drop(home, code)
    r = c.get("/login?next=/p/x")
    assert r.status_code == 303 and r.headers["location"] == "/p/x"
    cookie = [v for k, v in r.headers.multi_items() if k == "set-cookie"
              and v.startswith("wpk_s_7878=")][0]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    r = c.get("/")
    assert r.status_code == 200 and r.text.startswith("page for %s" % ME)
    assert csrf_token(SECRET) not in r.text                    # the per-user token instead
    assert gate.csrf(ME) in r.text


def test_another_browser_cannot_pick_up_the_session(tmp_path):
    c, _, home = _client(tmp_path)
    code = _code(c.get("/login").text)
    login.drop(home, code)
    r = TestClient(c.app, base_url=BASE, follow_redirects=False).get("/login")
    assert r.status_code == 200 and _code(r.text) != code


def test_owner_can_change_things_and_sign_out(tmp_path):
    c, gate, home = _client(tmp_path)
    _sign_in(c, home)
    hdr = {"origin": BASE, "x-csrf-token": gate.csrf(ME)}
    assert c.post("/act", headers=hdr).text == "did it as %s" % ME
    assert c.post("/act", headers={"origin": BASE,
                                   "x-csrf-token": csrf_token(SECRET)}).status_code == 403
    r = c.post("/logout", headers=hdr)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/").status_code == 303


def test_allowed_colleague_is_read_only(tmp_path):
    c, gate, _ = _client(tmp_path, allow=["bob"], owner="matt")
    c.cookies.set(gate.session_cookie, login.sign(gate.key, "bob", 1))
    assert c.get("/").text.startswith("page for bob")
    r = c.post("/act", headers={"origin": BASE, "x-csrf-token": gate.csrf("bob")})
    assert r.status_code == 403 and "read-only" in r.text
    assert c.get("/ide/x/").status_code == 403


def test_names_not_allowed_are_signed_out(tmp_path):
    c, gate, _ = _client(tmp_path, allow=[], owner="matt")
    c.cookies.set(gate.session_cookie, login.sign(gate.key, "bob", 1))
    assert c.get("/").status_code == 303            # e.g. bob was taken off allow


def test_a_drop_by_someone_not_allowed_is_refused(tmp_path):
    c, gate, home = _client(tmp_path, owner="someone-else")  # we are not the owner
    r = _sign_in(c, home)
    assert r.status_code == 200 and "%s may not use this board" % ME in r.text
    assert c.get("/").status_code == 303


def test_host_and_port_are_checked(tmp_path):
    c, _, _ = _client(tmp_path)
    assert TestClient(c.app, base_url="https://evil.example:7878").get("/").status_code == 421
    assert c.get("/", headers={"host": "board.example:7879"}).status_code == 421


def test_next_stays_on_the_board():
    for bad in ("//evil.example/", "https://evil.example/", "/\\evil", ""):
        assert login.safe_next(bad) == "/"
    assert login.safe_next("/p/x?a=1") == "/p/x?a=1"


# -- config ----------------------------------------------------------------------

@pytest.mark.parametrize("server, field", [
    ({"listen": "network", "tls": "self-signed"}, "server.listen"),       # auth not unix
    ({"listen": "network", "auth": "unix"}, "server.tls"),                # tls off
    ({"auth": "unix", "tailnet": True}, "server.auth"),
    ({"tls": "files"}, "server.tls"),                                     # no paths
    ({"session_days": 0}, "server.session_days"),
])
def test_config_errors(server, field):
    errs = schema.validate_config({"server": server})
    assert any(e.field == field for e in errs), errs


def test_config_ok():
    assert not schema.validate_config({"server": {
        "listen": "network", "auth": "unix", "tls": "self-signed", "allow": ["bob"]}})


# -- the certificate ---------------------------------------------------------------

@pytest.mark.skipif(not shutil.which("openssl"), reason="needs openssl")
def test_self_signed_covers_the_names(tmp_path):
    from work_packet.dash import tls
    cp, kp = tls.self_signed(str(tmp_path), ["board.example", "10.1.2.3"])
    assert os.stat(kp).st_mode & 0o777 == 0o600
    out = subprocess.run(["openssl", "x509", "-in", cp, "-noout", "-ext", "subjectAltName"],
                         capture_output=True, text=True).stdout
    assert "DNS:board.example" in out and "IP Address:10.1.2.3" in out
    tls.context(cp, kp)
    assert tls.self_signed(str(tmp_path), ["board.example"]) == (cp, kp)   # kept
    before = os.stat(cp).st_mtime_ns
    tls.self_signed(str(tmp_path), ["board.example", "other.example"])       # new name
    assert os.stat(cp).st_mtime_ns != before
    assert isinstance(ssl.create_default_context(), ssl.SSLContext)
