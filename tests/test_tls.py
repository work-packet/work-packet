"""Tailscale certificates for the tailnet listener (server.md S1b, vscode-plan.md V4)."""

import os
import signal
import ssl
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("starlette")

from work_packet import schema                                       # noqa: E402
from work_packet.dash import tls                                     # noqa: E402

from test_server import OWNER, FakeTailscaled, _free_port            # noqa: E402

DOMAIN = "a9550.tn.ts.net"


def make_pair(d, days, name=DOMAIN):
    """A self-signed certificate and key for ``name``: (cert PEM, key PEM)."""
    k, c = os.path.join(d, "k.pem"), os.path.join(d, "c.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
                    "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", k, "-out", c,
                    "-days", str(days), "-subj", "/CN=" + name,
                    "-addext", "subjectAltName=DNS:" + name],
                   check=True, capture_output=True)
    return open(c).read(), open(k).read()


@pytest.fixture
def ts():
    f = FakeTailscaled(ips=["127.0.0.2"], whois={"127.0.0.1": (OWNER, None)})
    yield f
    f.close()


def test_split_pair_either_order(tmp_path):
    cert, key = make_pair(str(tmp_path), 90)
    for body in (key + cert, cert + key):
        c, k = tls.split_pair(body.encode())
        assert c.strip() == cert.strip() and k.strip() == key.strip()
    with pytest.raises(tls.TlsError):
        tls.split_pair(cert.encode())


def test_fetch_store_reuse_and_renew(tmp_path, ts):
    home = str(tmp_path / "home")
    cert, key = make_pair(str(tmp_path), 90)
    ts.pair = (key + cert).encode()
    cp, kp, new = tls.ensure(home, DOMAIN, ts.path)
    assert new and open(cp).read().strip() == cert.strip()
    assert os.stat(kp).st_mode & 0o777 == 0o600
    assert os.stat(tls.tls_dir(home)).st_mode & 0o777 == 0o700
    tls.context(cp, kp)
    n = len(ts.calls)
    assert tls.ensure(home, DOMAIN, ts.path)[2] is False          # 90 days left: kept
    assert len(ts.calls) == n
    # 20 days left: fetched again
    cert2, key2 = make_pair(str(tmp_path), 20)
    os.makedirs(str(tmp_path / "x"), exist_ok=True)
    open(cp, "w").write(cert2)
    open(kp, "w").write(key2)
    assert tls.ensure(home, DOMAIN, ts.path)[2] is True
    assert open(cp).read().strip() == cert.strip()


def test_renewal_failure_keeps_a_working_certificate(tmp_path, ts):
    home = str(tmp_path / "home")
    cert, key = make_pair(str(tmp_path), 20)                       # due for renewal
    ts.pair = (key + cert).encode()
    tls.fetch(home, DOMAIN, ts.path)
    ts.pair = None                                                  # tailscaled says no
    cp, kp, new = tls.ensure(home, DOMAIN, ts.path)
    assert new is False and open(cp).read().strip() == cert.strip()


def test_not_the_operator(tmp_path, ts):
    with pytest.raises(tls.TlsError, match="tailscale set --operator"):
        tls.ensure(str(tmp_path / "home"), DOMAIN, ts.path)


def test_config_accepts_tls_tailscale():
    assert schema.validate_config({"server": {"tls": "tailscale"}}) == []
    assert schema.validate_config({"server": {"tls": "acme"}})


def _url_list(cmd, env):
    r = subprocess.run(cmd + ["url"], env=env, capture_output=True, text=True)
    return r.stdout.split()


def test_wpk_dash_serves_https_on_the_tailnet(tmp_path, ts):
    cert, key = make_pair(str(tmp_path), 90)
    ts.pair = (key + cert).encode()
    port = _free_port()
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('[server]\ntls = "tailscale"\n')
    env = dict(os.environ, WPK_HOME=str(home), WPK_TAILSCALE_SOCKET=ts.path)
    cmd = [sys.executable, "-c", "import sys; from work_packet.cli import main; sys.exit(main())"]
    p = subprocess.Popen(cmd + ["dash", "--tailnet", "--port", str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        urls = []
        while time.time() < deadline and not any(u.startswith("https") for u in urls):
            time.sleep(0.2)
            urls = _url_list(cmd, env)
        want = "https://%s:%d/" % (DOMAIN, port)
        assert want in urls
        assert "http://127.0.0.1:%d/" % port in urls             # loopback stays http
        ca = str(tmp_path / "c.pem")
        ctx = ssl.create_default_context(cafile=ca)
        # 127.0.0.2 stands in for the tailnet address; the name is the certificate's
        import http.client
        conn = http.client.HTTPSConnection("127.0.0.2", port, context=ctx, timeout=10)
        conn.sock = ctx.wrap_socket(__import__("socket").create_connection(("127.0.0.2", port)),
                                    server_hostname=DOMAIN)
        conn.request("GET", "/", headers={"host": "%s:%d" % (DOMAIN, port)})
        r = conn.getresponse()
        body = r.read().decode()
        assert r.status == 200 and OWNER in body
        # conn stays open (keep-alive, as a browser tab does): shutdown must not wait on it
        # plain http on the tailnet address is not served
        with pytest.raises(Exception):
            urllib.request.urlopen("http://127.0.0.2:%d/healthz" % port, timeout=3).read()
    finally:
        p.send_signal(signal.SIGTERM)
        try:
            out, err = p.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            raise AssertionError("did not stop on SIGTERM: " + err[-2000:])
    assert p.returncode == 0, err


def test_wpk_dash_without_a_certificate_does_not_fall_back_to_http(tmp_path, ts):
    port = _free_port()
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('[server]\ntls = "tailscale"\n')
    env = dict(os.environ, WPK_HOME=str(home), WPK_TAILSCALE_SOCKET=ts.path)
    cmd = [sys.executable, "-c", "import sys; from work_packet.cli import main; sys.exit(main())"]
    p = subprocess.Popen(cmd + ["dash", "--tailnet", "--port", str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not _url_list(cmd, env):
            time.sleep(0.2)
        time.sleep(1.0)
        urls = _url_list(cmd, env)
        assert urls == ["http://127.0.0.1:%d/" % port]               # loopback only
    finally:
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=20)
    assert "tailscale set --operator" in err
