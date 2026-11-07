"""Localhost links from web VS Code (port-forward plan): the port check, the
workbench shim, the open endpoint, and the sandboxed /fwd/ proxy."""

import os
import socket
import subprocess
import sys
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from work_packet import ide_ports  # noqa: E402
from work_packet.dash import ide_forward  # noqa: E402
from work_packet.dash.ide import SHIM, rewrite_workbench  # noqa: E402

from test_ide import _alive, _pids, _web_client, short_home  # noqa: E402,F401

SAME = {"sec-fetch-site": "same-origin"}


# --- which ports (ide_ports) --------------------------------------------------------

TCP_HEAD = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"


def _row(addr, port, uid, inode, st="0A"):
    return ("   0: %s:%04X 00000000:0000 %s 00000000:00000000 00:00000000 00000000 %5d        0 %d "
            "1 0000000000000000 100 0 0 10 0\n" % (addr, port, st, uid, inode))


def fake_proc(tmp_path, v4=(), v6=(), own=()):
    p = tmp_path / "proc"
    (p / "net").mkdir(parents=True)
    (p / "net" / "tcp").write_text(TCP_HEAD + "".join(_row(*r) for r in v4))
    (p / "net" / "tcp6").write_text(TCP_HEAD + "".join(_row(*r) for r in v6))
    (p / "self" / "fd").mkdir(parents=True)
    for i, ino in enumerate(own):
        os.symlink("socket:[%d]" % ino, p / "self" / "fd" / str(i + 3))
    return str(p)


LO4, ANY4, NODE4 = "0100007F", "00000000", "0A01A8C0"           # 127.0.0.1, 0.0.0.0, 192.168.1.10
LO6, ANY6 = "00000000000000000000000001000000", "0" * 32
MAPPED_LO = "0000000000000000FFFF00000100007F"                      # ::ffff:127.0.0.1


def test_a_port_of_this_uid_on_loopback_is_forwarded(tmp_path):
    proc = fake_proc(tmp_path, v4=[(LO4, 4000, 1000, 11)])
    assert ide_ports.check(4000, 1000, proc) == ("127.0.0.1", None)


@pytest.mark.parametrize("v4, v6, want", [
    ([(ANY4, 4000, 1000, 11)], [], "127.0.0.1"),
    ([], [(LO6, 4000, 1000, 11)], "::1"),
    ([], [(ANY6, 4000, 1000, 11)], "::1"),
    ([], [(MAPPED_LO, 4000, 1000, 11)], "127.0.0.1"),
    ([(LO4, 4000, 1000, 11)], [(LO6, 4000, 1000, 12)], "127.0.0.1"),     # IPv4 first
])
def test_wildcard_and_ipv6_binds(tmp_path, v4, v6, want):
    assert ide_ports.check(4000, 1000, fake_proc(tmp_path, v4, v6)) == (want, None)


@pytest.mark.parametrize("v4, v6, own, why", [
    ([], [], (), "nothing listens"),
    ([(LO4, 4000, 1000, 11, "01")], [], (), "nothing listens"),         # a connection, not a listener
    ([(LO4, 4001, 1000, 11)], [], (), "nothing listens"),
    ([(NODE4, 4000, 1000, 11)], [], (), "nothing listens"),            # not reachable on loopback
    ([(LO4, 4000, 2000, 11)], [], (), "another user"),
    # ours on ::1, another user's on 127.0.0.1: a connect could reach theirs
    ([(LO4, 4000, 2000, 11)], [(LO6, 4000, 1000, 12)], (), "another user"),
    ([(LO4, 4000, 1000, 11)], [], (11,), "wpk's own"),
])
def test_refused_ports_say_why(tmp_path, v4, v6, own, why):
    host, got = ide_ports.check(4000, 1000, fake_proc(tmp_path, v4, v6, own))
    assert host is None and why in got


def test_without_proc_nothing_is_forwarded(tmp_path):
    host, why = ide_ports.check(4000, 1000, str(tmp_path / "none"))
    assert host is None and "Linux" in why
    assert ide_ports.check(0, 1000, str(tmp_path))[0] is None


@pytest.mark.skipif(not os.path.exists("/proc/net/tcp"), reason="Linux only")
def test_real_listeners():
    child = subprocess.Popen([sys.executable, "-c", "import socket, sys, time\n"
                              "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1)\n"
                              "print(s.getsockname()[1], flush=True); time.sleep(60)"],
                             stdout=subprocess.PIPE, text=True)
    try:
        port = int(child.stdout.readline())
        assert ide_ports.check(port) == ("127.0.0.1", None)
        mine = socket.socket()
        mine.bind(("127.0.0.1", 0))
        mine.listen(1)
        try:
            host, why = ide_ports.check(mine.getsockname()[1])
            assert host is None and "wpk's own" in why
        finally:
            mine.close()
    finally:
        child.kill()
        child.wait()
    assert "nothing listens" in ide_ports.check(port)[1]       # closed: refused from then on


# --- links, redirects, tokens -----------------------------------------------------------

def test_parse_link():
    p = ide_forward.parse_link
    assert p("http://localhost:40731/s/?a=1#f") == (40731, "/s/?a=1#f")
    assert p("http://127.0.0.1:8000") == (8000, "/")
    assert p("https://[::1]:8443/x") == (8443, "/x")
    assert p("http://LOCALHOST/") == (80, "/")
    assert p("http://localhost:0/") is None
    for bad in ("http://example.com:80/", "file:///etc/passwd", "javascript:alert(1)",
                "http://localhost:99999/", "http://localhost:x/", "", None,
                "http://localhost.evil.com/"):
        assert p(bad) is None, bad


def test_rewrite_location():
    r = ide_forward.rewrite_location
    assert r("/x", 4000, "/fwd/t") == "/fwd/t/x"
    assert r("http://localhost:4000/y#top", 4000, "/fwd/t") == "/fwd/t/y#top"
    assert r("http://127.0.0.1:4000", 4000, "/fwd/t") == "/fwd/t/"
    assert r("http://localhost:5000/y", 4000, "/fwd/t") == "http://localhost:5000/y"
    assert r("https://example.com/", 4000, "/fwd/t") == "https://example.com/"
    assert r("//example.com/", 4000, "/fwd/t") == "//example.com/"
    assert r("next", 4000, "/fwd/t") == "next"


def test_tokens_are_reused_and_expire():
    now = [1000.0]
    t = ide_forward.Tokens(idle_s=60, ttl_s=300, clock=lambda: now[0])
    a = t.issue("k", 4000, 77)
    assert t.issue("k", 4000, 77) == a
    assert t.issue("k", 4001, 77) != a and t.issue("k", 4000, 78) != a
    assert t.resolve(a).port == 4000
    now[0] += 59
    assert t.resolve(a) is not None                     # used: idle time starts again
    now[0] += 61
    assert t.resolve(a) is None                         # idle too long
    b = t.issue("k", 4000, 77)
    for _ in range(6):
        now[0] += 55
        t.resolve(b)
    assert t.resolve(b) is None                         # 12 h (here 300 s) in all
    c = t.issue("k", 4000, 77)
    t.revoke(c)
    assert t.resolve(c) is None and t.resolve(None) is None


def test_rewrite_html():
    h = ide_forward.rewrite_html
    assert h(b'<base href="http://localhost:4000/s/">', 4000, "/fwd/t") == b'<base href="/fwd/t/s/">'
    assert h(b'"HTTP://127.0.0.1:4000" http://[::1]:4000/x', 4000, "/fwd/t") == b'"/fwd/t" /fwd/t/x'
    for other in (b"http://localhost:40000/", b"http://localhost:400/", b"http://example.com:4000/",
                  b"ws://localhost:4000/"):
        assert h(other, 4000, "/fwd/t") == other


def test_rewrite_workbench():
    page = b'<meta x="&quot;enableWorkspaceTrust&quot;:true"><script src=a></script><script>'
    got = rewrite_workbench(page, True, True)
    assert got.count(SHIM) == 1 and got.index(SHIM) < got.index(b"<script src=a>")
    assert b"enableWorkspaceTrust&quot;:false" in got
    assert SHIM not in rewrite_workbench(page, True, False)
    assert rewrite_workbench(page, False, True).count(b":true") == 1
    assert rewrite_workbench(b"<p>no script</p>", False, True) == b"<p>no script</p>"


# --- through the board (a server on wpkd's host) ----------------------------------

def _up(c, be, tmp_path):
    r = c.get("/ide/%s/?folder=/x" % be.key)
    assert r.status_code == 200
    return r, int(open(str(tmp_path / "pids") + ".port").read())


def _open(c, be, url, **headers):
    import urllib.parse
    return c.get("/ide/%s/__wpk/open?u=%s" % (be.key, urllib.parse.quote(url, safe="")),
                 headers=dict(SAME, **headers), follow_redirects=False)


def test_the_shim_goes_on_the_workbench_page_only(short_home, tmp_path):
    for trust in (False, True):
        c, be, origin, tok = _web_client(short_home, tmp_path, workspace_trust=trust)
        try:
            r, _ = _up(c, be, tmp_path)
            assert r.text.count(SHIM.decode()) == 1
            assert r.text.index(SHIM.decode()) < r.text.index("<script>/* workbench */")
            assert SHIM.decode() not in c.get("/ide/%s/other" % be.key).text
            js = c.get("/static/ide_forward.js")
            assert js.status_code == 200 and "__wpk/open" in js.text
        finally:
            be.stop()
            c.__exit__(None, None, None)


def test_forward_off_restores_todays_behaviour(short_home, tmp_path):
    c, be, origin, tok = _web_client(short_home, tmp_path, forward=False)
    try:
        r, port = _up(c, be, tmp_path)
        assert SHIM.decode() not in r.text
        assert _open(c, be, "http://localhost:%d/" % port).status_code == 404
        tok_ = ide_forward.TOKENS.issue(be.key, port, be.forward_identity())
        assert c.get("/fwd/%s/" % tok_).status_code == 404
    finally:
        be.stop()
        c.__exit__(None, None, None)


def test_a_localhost_link_is_forwarded_sandboxed(short_home, tmp_path):
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        _, port = _up(c, be, tmp_path)
        r = _open(c, be, "http://localhost:%d/s/?a=1#frag" % port)
        assert r.status_code == 303
        loc = r.headers["location"]
        assert loc.startswith("/fwd/") and loc.endswith("/s/?a=1#frag")
        base = loc[:loc.index("/s/")]
        assert _open(c, be, "http://127.0.0.1:%d/" % port).headers["location"] == base + "/"

        be.forwarded = float("-inf")
        r = c.get(base + "/s/?a=1", headers={"cookie": "wpk-session=secret"})
        assert r.status_code == 200
        assert '<pre id="host">localhost:%d</pre>' % port in r.text   # the Host a dev server expects
        assert '<pre id="path">/s/?a=1</pre>' in r.text
        assert '<pre id="cookie">None</pre>' in r.text               # the board's cookies stay here
        assert be.forwarded > float("-inf")
        csp = r.headers.get_list("content-security-policy")
        assert any(v.startswith("sandbox allow-scripts") and "allow-modals" in v for v in csp)
        assert "img-src 'self'" in csp                              # the page's own CSP still applies
        assert "set-cookie" not in r.headers
        assert r.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in r.headers
        assert r.headers["referrer-policy"] == "no-referrer"
        assert "x-content-type-options" not in r.headers            # ORB: see ide_forward.DROP
        css = c.get(base + "/s/style.css")
        assert css.status_code == 200 and "color: red" in css.text  # a relative link resolves
        assert c.head(base + "/s/").status_code == 200
        assert c.get(base + "/redir", follow_redirects=False).headers["location"] == base + "/x"
        assert c.get(base + "/abs", follow_redirects=False).headers["location"] == base + "/y#top"
        assert c.get(base + "/nope").status_code == 404
        # a page that names its own origin (vscode-print's <base href>) stays on the board
        r = c.get(base + "/b/")
        assert '<base href="%s/b/">' % base in r.text and 'href="%s/x"' % base in r.text
        assert 'href="http://localhost:%d1/"' % port in r.text           # another port: left alone
        assert int(r.headers["content-length"]) == len(r.content)
        # read-only, and nothing without a live token
        assert c.post(base + "/s/", headers=origin, content=b"x").status_code == 405
        assert c.get("/fwd/nope/s/").status_code == 403
        with pytest.raises(Exception):
            with c.websocket_connect(base + "/s/"):
                pass
        # the server stops: its tokens die with it (another process may get the port)
        be.stop()
        assert c.get(base + "/s/").status_code in (403, 410)
        assert c.get(base + "/s/").status_code == 403                # revoked
    finally:
        be.stop()
        c.__exit__(None, None, None)


def test_the_open_endpoint_refuses(short_home, tmp_path):
    c, be, origin, tok = _web_client(short_home, tmp_path)
    mine = socket.socket()
    mine.bind(("127.0.0.1", 0))
    mine.listen(1)
    try:
        _, port = _up(c, be, tmp_path)
        url = "http://localhost:%d/" % port
        # only from the workbench itself: a cross-site page cannot send you to a local app
        assert c.get("/ide/%s/__wpk/open?u=%s" % (be.key, url),
                     follow_redirects=False).status_code == 403
        assert _open(c, be, url, **{"sec-fetch-site": "cross-site"}).status_code == 403
        for bad in ("http://example.com/", "file:///etc/passwd", "http://localhost:0/"):
            assert _open(c, be, bad).status_code == 400, bad
        r = _open(c, be, "http://localhost:%d/" % mine.getsockname()[1])     # the board's own
        assert r.status_code == 403 and "wpk's own" in r.text
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        p = free.getsockname()[1]
        free.close()
        r = _open(c, be, "http://localhost:%d/" % p)
        assert r.status_code == 403 and "nothing listens" in r.text
    finally:
        mine.close()
        be.stop()
        c.__exit__(None, None, None)


def test_a_page_in_use_keeps_its_server_from_eviction(short_home, tmp_path):
    import asyncio
    from work_packet.dash.ide import IdeUnavailable
    from test_ide import _backends
    bs = _backends(short_home, tmp_path, max_servers=1)
    a, b = bs.get(bs.register("/a")), bs.get(bs.register("/b"))

    async def run():
        await bs.ensure(a)
        a.forwarded = a._clock()
        with pytest.raises(IdeUnavailable):
            await bs.ensure(b)
        a.forwarded = float("-inf")
        await bs.ensure(b)
        assert not a.running() and b.running()
    try:
        asyncio.run(run())
    finally:
        a.stop()
        b.stop()


def test_network_listener_open_is_the_owners_and_fwd_needs_no_login(short_home, tmp_path):
    import json
    from starlette.testclient import TestClient
    from work_packet.dash import login
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard
    from test_ide import _backend
    open(os.path.join(short_home, "config.toml"), "w").write(
        "[ide]\nweb = true\ncode = %s\n" % json.dumps(sys.executable))
    be = _backend(short_home, tmp_path)
    secret = b"k" * 32
    login.ensure_drop_dir(short_home)
    gate = login.Gate(short_home, secret, 7878, "matt", ["bob"])
    g = Guard(create_app(short_home, ide_backend=be.mgr), "network", secret, gate=gate,
              names=["board.example"])
    try:
        with TestClient(g, base_url="https://board.example:7878", follow_redirects=False) as c:
            c.cookies.set(gate.session_cookie, login.sign(gate.key, "bob", 1))
            r = c.get("/ide/%s/__wpk/open?u=http://localhost:1/" % be.key, headers=SAME)
            assert r.status_code == 403 and be.proc is None          # not the owner: nothing starts
            c.cookies.set(gate.session_cookie, login.sign(gate.key, "matt", 1))
            assert c.get("/ide/%s/?folder=/x" % be.key).status_code == 200
            port = int(open(str(tmp_path / "pids") + ".port").read())
            loc = c.get("/ide/%s/__wpk/open?u=http://localhost:%d/s/" % (be.key, port),
                        headers=SAME).headers["location"]
            c.cookies.clear()                                         # a sandboxed page sends none
            r = c.get(loc)
            assert r.status_code == 200 and "localhost:%d" % port in r.text
            assert c.get("/fwd/nope/s/").status_code == 403
    finally:
        be.stop()
