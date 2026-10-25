"""S1: the board on the tailnet (docs/server.md). A fake tailscaled answers
the LocalAPI on a unix socket, so no test needs Tailscale."""

import hashlib
import http.server
import json
import os
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.applications import Starlette          # noqa: E402
from starlette.responses import PlainTextResponse     # noqa: E402
from starlette.routing import Route                   # noqa: E402
from starlette.testclient import TestClient           # noqa: E402

from work_packet import project, registry, schema     # noqa: E402
from work_packet.dash.app import create_app           # noqa: E402
from work_packet.dash.guard import Guard, csrf_token, split_host  # noqa: E402
from work_packet.dash.tailscale import Tailnet        # noqa: E402

OWNER = "me@example.com"
SECRET = b"k" * 32
HOST = "a9550:7878"


class FakeTailscaled:
    """``/localapi/v0/status`` and ``/whois`` from dicts; ``whois`` maps peer IP
    to ``(login, tags)``."""

    def __init__(self, ips=("100.64.0.1",), whois=None):
        self.dir = tempfile.mkdtemp(prefix="wpk-ts")      # short: unix socket paths are limited
        self.path = os.path.join(self.dir, "s")
        self.ips = list(ips)
        self.whois = dict(whois or {})
        self.calls = []
        self.pair = None            # key + certificate PEM for /cert/<domain>?type=pair
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                fake.calls.append(u.path)
                if u.path.startswith("/localapi/v0/cert/"):        # S1b: raw PEM, or 403
                    data = fake.pair or b"access denied\n"
                    self.send_response(200 if fake.pair else 403)
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if u.path == "/localapi/v0/status":
                    body = fake.status()
                elif u.path == "/localapi/v0/whois":
                    addr = urllib.parse.parse_qs(u.query)["addr"][0]
                    ip = addr.rsplit(":", 1)[0].strip("[]")
                    body = fake.who(ip)
                else:
                    body = None
                data = json.dumps(body).encode() if body else b"not found"
                self.send_response(200 if body else 404)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

            def get_request(self):
                sock, _ = super().get_request()
                return sock, ("local", 0)

        self.server = Server(self.path, Handler)
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def status(self):
        return {"BackendState": "Running", "TailscaleIPs": self.ips,
                "Self": {"DNSName": "a9550.tn.ts.net.", "UserID": 7, "Tags": None},
                "CertDomains": ["a9550.tn.ts.net"],
                "User": {"7": {"ID": 7, "LoginName": OWNER}}}

    def who(self, ip):
        if ip not in self.whois:
            return None
        login, tags = self.whois[ip]
        return {"UserProfile": {"LoginName": login},
                "Node": {"Name": "laptop.tn.ts.net.", "Tags": tags}}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture
def ts():
    f = FakeTailscaled(whois={"100.64.0.9": (OWNER, None),
                              "100.64.0.10": ("other@example.com", None),
                              "100.64.0.11": ("me@example.com", ["tag:ci"])})
    yield f
    f.close()


def _board(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    project.new("demo", "Read state/count.md (0 if missing), add one.")
    return create_app()


def _client(app, kind, ts=None, peer="100.64.0.9", host=HOST, **kw):
    g = Guard(app, kind, SECRET, tailnet=Tailnet(ts.path) if ts else None,
              local_user="alice", **kw)
    return TestClient(g, base_url="http://" + host, client=(peer, 50000))


# -- who gets in ------------------------------------------------------------

def test_owner_gets_the_board_with_security_headers(tmp_path, monkeypatch, ts):
    r = _client(_board(tmp_path, monkeypatch), "tailnet", ts).get("/")
    assert r.status_code == 200
    assert OWNER in r.text                                  # shown in the header
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert "<script>" not in r.text                         # CSP: no inline script
    assert "server" not in r.headers


@pytest.mark.parametrize("peer, why", [
    ("100.64.0.10", "other@example.com"),                   # another login
    ("100.64.0.11", "not a user's device"),                 # a tagged node
    ("100.64.0.99", "not a user's device"),                 # unknown to tailscaled
])
def test_others_are_refused(tmp_path, monkeypatch, ts, peer, why):
    r = _client(_board(tmp_path, monkeypatch), "tailnet", ts, peer=peer).get("/")
    assert r.status_code == 403 and why in r.text
    assert r.headers["x-frame-options"] == "DENY"


def test_allow_list_replaces_the_owner(tmp_path, monkeypatch, ts):
    app = _board(tmp_path, monkeypatch)
    allow = ["other@example.com"]
    assert _client(app, "tailnet", ts, peer="100.64.0.10", allow=allow).get("/").status_code == 200
    assert _client(app, "tailnet", ts, peer="100.64.0.9", allow=allow).get("/").status_code == 403


def test_tailscaled_down_refuses_tailnet_but_not_loopback(tmp_path, monkeypatch, ts):
    app = _board(tmp_path, monkeypatch)
    ts.close()
    r = _client(app, "tailnet", ts, host="localhost:7878").get("/")   # tailnet names are gone too
    assert r.status_code == 403
    r = _client(app, "loopback", ts, peer="127.0.0.1", host="127.0.0.1:7878").get("/")
    assert r.status_code == 200 and "alice" in r.text


def test_whois_is_cached_per_peer(tmp_path, monkeypatch, ts):
    c = _client(_board(tmp_path, monkeypatch), "tailnet", ts)
    for _ in range(3):
        assert c.get("/healthz").status_code == 200
    assert ts.calls.count("/localapi/v0/whois") == 1


# -- host names and proxies ---------------------------------------------------

@pytest.mark.parametrize("host, code", [
    ("a9550:7878", 200), ("A9550.tn.ts.net:7878", 200), ("100.64.0.1:7878", 200),
    ("localhost:7878", 200),
    ("evil.example:7878", 421),                             # DNS rebinding
    ("a9550:7879", 421),                                    # wrong port
    ("a9550", 421),                                         # implies port 80
    ("", 421),
])
def test_host_check(tmp_path, monkeypatch, ts, host, code):
    c = _client(_board(tmp_path, monkeypatch), "tailnet", ts)
    assert c.get("/healthz", headers={"host": host}).status_code == code


def test_split_host():
    assert split_host("A9550:7878") == ("a9550", 7878)
    assert split_host("[fd7a::1]:7878") == ("fd7a::1", 7878)
    assert split_host("[fd7a::1]") == ("fd7a::1", None)
    assert split_host("x:y") == (None, None)


@pytest.mark.parametrize("header", ["X-Forwarded-For", "Forwarded", "Tailscale-User-Login",
                                    "Via"])
def test_loopback_refuses_proxied_requests(tmp_path, monkeypatch, header):
    c = _client(_board(tmp_path, monkeypatch), "loopback", peer="127.0.0.1",
                host="127.0.0.1:7878")
    assert c.get("/healthz").status_code == 200
    r = c.get("/healthz", headers={header: "x"})
    assert r.status_code == 403 and "proxy" in r.text


# -- requests that change things --------------------------------------------

def _echo_app():
    async def act(request):
        form = urllib.parse.parse_qs((await request.body()).decode())
        return PlainTextResponse("did %s as %s" % (form["what"][0], request.state.user))
    return Starlette(routes=[Route("/act", act, methods=["POST"])])


@pytest.mark.parametrize("headers, data, code", [
    ({}, {"what": "x"}, 403),                                            # no Origin
    ({"origin": "http://evil.example"}, {"what": "x"}, 403),             # cross-site
    ({"origin": "http://a9550:7878"}, {"what": "x"}, 403),               # no token
    ({"origin": "http://a9550:7878"}, {"what": "x", "csrf": "nope"}, 403),
    ({"origin": "http://a9550:7878"}, {"what": "x", "csrf": csrf_token(SECRET)}, 200),
    ({"origin": "http://a9550:7878", "x-csrf-token": csrf_token(SECRET)}, {"what": "x"}, 200),
    ({"origin": "null", "x-csrf-token": csrf_token(SECRET)}, {"what": "x"}, 403),
])
def test_post_needs_origin_and_token(ts, headers, data, code):
    r = _client(_echo_app(), "tailnet", ts).post("/act", headers=headers, data=data)
    assert r.status_code == code, r.text
    if code == 200:
        assert r.text == "did x as %s" % OWNER                           # body replayed


def _snapshot(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fp:
                out[p] = hashlib.sha256(fp.read()).hexdigest()
    return out


def test_get_routes_change_nothing(tmp_path, monkeypatch, ts):
    app = _board(tmp_path, monkeypatch)
    c = _client(app, "tailnet", ts)
    entry = registry.get("demo")
    before = _snapshot(str(tmp_path))
    for path in ("/", "/healthz", "/static/live.js", "/p/demo",
                 "/p/demo/" + entry["root"], "/p/nope"):
        assert c.get(path).status_code in (200, 404), path
    assert _snapshot(str(tmp_path)) == before


# -- config --------------------------------------------------------------------

@pytest.mark.parametrize("server, field", [
    ({"port": "x"}, "server.port"),
    ({"port": 70000}, "server.port"),
    ({"tailnet": "yes"}, "server.tailnet"),
    ({"auth": "pam"}, "server.auth"),
    ({"auth": "none", "tailnet": True}, "server.auth"),
    ({"allow": "me"}, "server.allow"),
    ({"tls": "acme"}, "server.tls"),
    ({"bogus": 1}, "server.bogus"),
])
def test_server_config_errors(server, field):
    probs = [p for p in schema.validate_config({"server": server}) if p.level == "error"]
    assert [p.field for p in probs] == [field]


def test_server_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path))
    assert registry.load_server_config() == schema.SERVER_DEFAULTS
    (tmp_path / "config.toml").write_text("[server]\ntailnet = true\nport = 9000\n")
    cfg = registry.load_server_config()
    assert cfg["tailnet"] is True and cfg["port"] == 9000 and cfg["loopback"] is True


# -- the real thing: `wpk dash --tailnet` in a subprocess --------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url, host=None):
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_wpk_dash_on_loopback_and_tailnet(tmp_path):
    # 127.0.0.2 stands in for the tailnet address; connections to it come from 127.0.0.1.
    ts = FakeTailscaled(ips=["127.0.0.2"], whois={"127.0.0.1": (OWNER, None)})
    port = _free_port()
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, WPK_HOME=str(home), WPK_TAILSCALE_SOCKET=ts.path)
    cmd = [sys.executable, "-c", "import sys; from work_packet.cli import main; sys.exit(main())"]
    p = subprocess.Popen(cmd + ["dash", "--tailnet", "--port", str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        urls = []
        while time.time() < deadline and not any("127.0.0.2" in u for u in urls):
            time.sleep(0.2)
            r = subprocess.run(cmd + ["url"], env=env, capture_output=True, text=True)
            urls = r.stdout.split()
        assert "http://127.0.0.1:%d/" % port in urls
        assert "http://a9550.tn.ts.net:%d/" % port in urls
        assert "http://127.0.0.2:%d/" % port in urls

        assert _get("http://127.0.0.1:%d/healthz" % port)[0] == 200
        code, body = _get("http://127.0.0.2:%d/" % port, host="a9550:%d" % port)
        assert code == 200 and OWNER in body
        assert _get("http://127.0.0.2:%d/" % port, host="evil.example:%d" % port)[0] == 421
        st = os.stat(home / "server.secret")
        assert st.st_mode & 0o077 == 0
    finally:
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=20)
        ts.close()
    assert p.returncode == 0, err
    assert not (home / "server.json").exists()
    r = subprocess.run(cmd + ["url"], env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "not running" in r.stderr


def test_board_forms_carry_the_token_the_guard_wants(tmp_path, monkeypatch):
    import re
    from work_packet import registry
    from work_packet.packet import Packet
    app = _board(tmp_path, monkeypatch)
    e = registry.get("demo")
    c = _client(app, "loopback", peer="127.0.0.1", host="127.0.0.1:7878")
    page = c.get("/p/demo/" + e["root"]).text            # RUNNABLE: the Pause form
    token = re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)
    assert token == csrf_token(SECRET)
    r = c.post("/p/demo/%s/act" % e["root"], headers={"origin": "http://127.0.0.1:7878"},
               data={"csrf": token, "action": "pause"}, follow_redirects=False)
    assert r.status_code == 303
    assert Packet(os.path.join(e["path"], "packets", e["root"])).load_status()[0]["state"] \
        == "PAUSED"
