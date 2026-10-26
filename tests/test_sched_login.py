"""wpkd on a login node: the unix listener, the home lease, wpk serve, wpk url,
wpk sched doctor (docs/scheduler.md §7.1; plan Q4.6, Q4.7)."""

import json
import os
import signal
import socket
import subprocess
import sys
import time

import pytest
import tomli_w

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from work_packet import project  # noqa: E402
from work_packet.cli import main  # noqa: E402
from work_packet.sched import home_lease  # noqa: E402

FAKEBATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebatch")


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    # unix socket paths are short: keep the home near /tmp
    import tempfile
    h = tempfile.mkdtemp(prefix="wpk-login-")
    monkeypatch.setenv("WPK_HOME", h)
    monkeypatch.chdir(tmp_path)
    yield h
    held = home_lease.read(h)
    if held and held.get("host") == socket.gethostname() and \
            held.get("pid", 0) > 1 and held.get("pid") != os.getpid():
        try:
            os.kill(held["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass


def config(h, **server):
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "wb") as fp:
        tomli_w.dump({"server": dict({"listen": "unix", "port": free_port()}, **server)}, fp)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait(cond, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_home_lease_names_the_holder(home, monkeypatch):
    with open(home_lease.path(home), "w") as fp:
        json.dump({"host": "login2", "pid": 4242, "started": "2026-10-26T00:00:00Z",
                   "expires": "2999-01-01T00:00:00Z"}, fp)
    with pytest.raises(home_lease.HomeBusy) as e:
        home_lease.HomeLease(home).acquire()
    assert "host login2, pid 4242" in str(e.value)
    from work_packet.dash.runner import Runner, RunnerBusy
    with pytest.raises(RunnerBusy, match="login2"):
        Runner(home).acquire()


def test_stale_home_lease_is_taken_over(home):
    with open(home_lease.path(home), "w") as fp:
        json.dump({"host": "login2", "pid": 4242, "expires": "2020-01-01T00:00:00Z"}, fp)
    lease = home_lease.HomeLease(home).acquire()
    got = home_lease.read(home)
    assert (got["host"], got["pid"]) == (socket.gethostname(), os.getpid())
    assert lease.refresh() is True
    lease.release()
    assert home_lease.read(home) is None


def test_lease_taken_over_stops_the_refresher(home):
    lease = home_lease.HomeLease(home).acquire()
    with open(home_lease.path(home), "w") as fp:
        json.dump({"host": "login2", "pid": 1, "expires": "2999-01-01T00:00:00Z"}, fp)
    assert lease.refresh() is False                       # it is someone else's now
    lease.release()
    assert home_lease.read(home)["host"] == "login2"      # and left alone


def _serve(home, *extra):
    return subprocess.run([sys.executable, "-m", "work_packet", "serve"] + list(extra),
                          capture_output=True, text=True, timeout=60, env=os.environ)


def test_serve_ensure_twice_starts_one_on_a_unix_socket(home, capsys):
    import httpx
    config(home)
    project.new("demo", "Read state/count.md (0 if missing), add one.")
    r1 = _serve(home, "--ensure")
    assert r1.returncode == 0 and "wpkd started" in r1.stderr, r1.stderr
    held = home_lease.live(home)
    r2 = _serve(home, "--ensure")
    assert r2.returncode == 0 and "wpkd is running (host %s, pid %d)" % (
        socket.gethostname(), held["pid"]) in r2.stderr
    assert _serve(home, "--detach").returncode == 4           # already running
    sock = os.path.join(home, "run", "wpkd.sock")
    assert wait(lambda: os.path.exists(sock))
    assert oct(os.stat(os.path.dirname(sock)).st_mode & 0o777) == "0o700"
    c = httpx.Client(transport=httpx.HTTPTransport(uds=sock), base_url="http://localhost:7878")
    assert wait(lambda: c.get("/healthz").status_code == 200)
    page = c.get("/sched")
    assert page.status_code == 200 and "Scheduler" in page.text
    port = json.load(open(os.path.join(home, "server.json")))["port"]
    with pytest.raises(OSError):                             # no TCP listener
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    assert main(["url"]) == 0
    out = capsys.readouterr().out
    assert "ssh -N -L %d:%s " % (port, sock) in out
    os.kill(held["pid"], signal.SIGTERM)
    assert wait(lambda: home_lease.read(home) is None)
    assert not os.path.exists(sock)
    assert os.path.exists(os.path.join(home, "log", "wpkd.log"))


def test_unix_guard_accepts_the_forwarded_host(home):
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard
    import getpass
    project.new("demo", "Read state/count.md (0 if missing), add one.")
    g = Guard(create_app(home), "unix", b"k" * 32, local_user=getpass.getuser())
    c = TestClient(g, base_url="http://localhost:9999")      # the laptop's -L port
    assert c.get("/").status_code == 200
    c = TestClient(g, base_url="http://evil.example:9999")
    assert c.get("/").status_code == 421
    r = TestClient(g, base_url="http://localhost:9999").post(
        "/sched/mode", data={"mode": "halt"}, headers={"origin": "http://localhost:9999"},
        follow_redirects=False)
    assert r.status_code == 403                              # CSRF still applies


def test_doctor_with_the_fake_farm(home, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("WPK_FAKEBATCH_DIR", str(tmp_path / "fb"))
    project.new("demo", "Read state/count.md (0 if missing), add one.")
    with open(os.path.join(home, "config.toml"), "wb") as fp:
        tomli_w.dump({"server": {"listen": "unix"}, "sched": {
            "backend": "slurm", "node_env": "export PATH=%s:$PATH" % os.path.dirname(
                sys.executable), "slurm": {"bin": FAKEBATCH}}}, fp)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")            # no claude here
    code = main(["sched", "doctor"])
    out = capsys.readouterr().out
    assert "slurm commands found" in out
    assert "the home and 1 project are visible from a node" in out
    assert "wpk found on the node" in out
    assert "claude is not on the node's PATH" in out and code == 1
    assert "the node's clock agrees" in out
    with open(os.path.join(home, "config.toml"), "wb") as fp:
        tomli_w.dump({"sched": {"backend": "slurm", "slurm": {"bin": str(tmp_path)}}}, fp)
    assert main(["sched", "doctor"]) == 1
    assert "batch commands not found: sbatch" in capsys.readouterr().out
