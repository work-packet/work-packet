"""The IDE's mutually pinned TLS transport (docs/scheduler.md §8.1): the
relay, the job, the proxy, and what must not be reachable."""

import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402

from work_packet import schema  # noqa: E402
from work_packet.sched import ide, ide_job, ide_tls, jobs  # noqa: E402
from test_sched_ide import FAKE_IDE, Pool, config, get_until_up, home, kinds, new  # noqa: E402,F401


def wait_for(path, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        if os.path.exists(path):
            return
        time.sleep(0.05)
    raise AssertionError("%s did not appear" % path)


def mtls_backends(h, tmp_path, poke=None):
    from work_packet.dash.ide import Backends
    cfg = dict(schema.IDE_DEFAULTS, web=True)
    return Backends(h, cfg, argv=[sys.executable, FAKE_IDE, str(tmp_path / "pids")], slot=True,
                    poke=poke, transport="mtls")


# --- certificates and contexts ---------------------------------------------------------

def test_client_cert_is_made_once_and_private(tmp_path):
    h = str(tmp_path)
    key, crt = ide_tls.client_cert(h)
    assert oct(os.stat(key).st_mode & 0o777) == "0o600" and oct(os.stat(os.path.join(h, "ide")).st_mode & 0o777) == "0o700"
    fp = ide_tls.fingerprint(crt)
    assert ide_tls.client_cert(h) == (key, crt) and ide_tls.fingerprint(crt) == fp      # not remade
    assert len(fp) == 64


def test_contexts_are_tls13_and_require_certificates(tmp_path):
    k, c = str(tmp_path / "k"), str(tmp_path / "c")
    ide_tls.make_cert(k, c, 1, "x")
    cl = ide_tls.pinned_client_context(c, k, c)
    sv = ide_tls.pinned_server_context(c, k, c)
    for ctx in (cl, sv):
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3 and ctx.verify_mode == ssl.CERT_REQUIRED
    assert cl.check_hostname is False


def test_openssl_is_found_or_the_error_says_so(monkeypatch):
    monkeypatch.setattr(ide_tls.os, "access", lambda *a: False)
    monkeypatch.setattr(ide_tls.shutil, "which", lambda n: None)
    with pytest.raises(RuntimeError, match="openssl"):
        ide_tls.openssl()


# --- the job's local directory -----------------------------------------------------------

def test_local_dir_skips_nfs_and_long_paths(tmp_path):
    mi = tmp_path / "mountinfo"
    nfs, ok = tmp_path / "nfs", tmp_path / "ok"
    nfs.mkdir()
    ok.mkdir()
    mi.write_text("1 0 0:1 / %s rw - nfs4 srv:/x rw\n2 0 0:2 / %s rw - ext4 /dev/sda rw\n" % (nfs, ok))
    assert ide_job.fstype(str(nfs / "d"), str(mi)) == "nfs4" and ide_job.fstype(str(ok), str(mi)) == "ext4"
    d = ide_job.local_dir({"XDG_RUNTIME_DIR": str(nfs), "TMPDIR": str(ok)}, str(mi))
    assert d.startswith(str(ok)) and oct(os.stat(d).st_mode & 0o777) == "0o700"
    long = tmp_path / ("x" * 100)
    long.mkdir()
    d2 = ide_job.local_dir({"TMPDIR": str(long)}, str(mi))              # too long for a socket: falls through
    assert not d2.startswith(str(long))


# --- the job ---------------------------------------------------------------------------------

def unix_socks():
    """Paths of the unix sockets in local ``wpk-ide-*`` directories (the jobs' own)."""
    out = set()
    for line in open("/proc/net/unix").read().splitlines()[1:]:
        p = line.split()[-1]
        if "/wpk-ide-" in p and p.startswith("/"):
            out.add(p)
    return out


def stop_job(p, pids):
    """End an ide_job the way the scheduler does (SIGTERM, so it stops its server
    and relay), then reap whatever the fake server left: a SIGKILLed job orphans
    both, and they would outlive the test run."""
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    try:
        left = [int(x) for x in open(str(pids)).read().split()]
    except (OSError, ValueError):
        left = []
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


@pytest.fixture
def job(tmp_path):
    """ide_job in mtls mode, serving the fake VS Code on a unix socket."""
    d = tempfile.mkdtemp(prefix="wpk-srv-")
    os.chmod(d, 0o700)
    home_ = tempfile.mkdtemp(prefix="wpk-home-")
    key, crt = ide_tls.client_cert(home_)
    import shutil
    shutil.copy(crt, os.path.join(d, "client.crt"))
    before = unix_socks()
    p = subprocess.Popen([sys.executable, "-m", "work_packet.sched.ide_job", d, "--transport", "mtls", "--",
                          sys.executable, FAKE_IDE, str(tmp_path / "pids"), "{sock}", "/ide/k"],
                         env=dict(os.environ, TMPDIR="/tmp"))
    wait_for(os.path.join(d, "endpoint"))
    port = int(open(os.path.join(d, "endpoint")).read().strip().rpartition(":")[2])

    class J:
        dir, proc, pk, pc, port_, home = d, p, key, crt, port, home_
        socks = sorted(unix_socks() - before)         # this job's own (the server's) sockets
    yield J
    stop_job(p, tmp_path / "pids")
    import shutil as sh
    sh.rmtree(d, ignore_errors=True)
    sh.rmtree(home_, ignore_errors=True)


def test_the_job_publishes_only_public_files_and_keeps_its_key_local(job):
    names = sorted(os.listdir(job.dir))
    assert names == ["client.crt", "endpoint", "fingerprint", "server.crt"]
    assert ide_tls.fingerprint(os.path.join(job.dir, "server.crt")) == open(os.path.join(job.dir, "fingerprint")).read().strip()
    for n in names:
        assert "PRIVATE KEY" not in open(os.path.join(job.dir, n)).read()


def test_a_pinned_client_reaches_the_server_and_nobody_else_does(job):
    ctx = ide_tls.pinned_client_context(job.pc, job.pk, os.path.join(job.dir, "server.crt"))
    s = socket.create_connection(("127.0.0.1", job.port_), timeout=5)
    t = ctx.wrap_socket(s, server_hostname="x")
    t.sendall(b"GET /ide/k/ HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    data = b""
    while True:
        chunk = t.recv(65536)
        if not chunk:
            break
        data += chunk
    assert data.startswith(b"HTTP/1.1 200") and b'<pre id="seen">' in data
    # plaintext: nothing
    s = socket.create_connection(("127.0.0.1", job.port_), timeout=5)
    s.sendall(b"GET /ide/k/ HTTP/1.1\r\nHost: x\r\n\r\n")
    s.settimeout(5)
    try:
        got = s.recv(100)
    except (ConnectionError, socket.timeout):
        got = b""
    assert b"HTTP/1." not in got
    # a different client certificate: refused
    k2, c2 = str(job.proc.pid) + ".k", str(job.proc.pid) + ".c"
    k2, c2 = os.path.join(job.dir, "..", os.path.basename(k2)), os.path.join(job.dir, "..", os.path.basename(c2))
    ide_tls.make_cert(k2, c2, 1, "other")
    try:
        ctx2 = ide_tls.pinned_client_context(c2, k2, os.path.join(job.dir, "server.crt"))
        s = socket.create_connection(("127.0.0.1", job.port_), timeout=5)
        with pytest.raises((ssl.SSLError, ConnectionError)):
            t2 = ctx2.wrap_socket(s, server_hostname="x")
            t2.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            if not t2.recv(100):
                raise ConnectionError("closed")
    finally:
        for f in (k2, c2):
            os.unlink(f)


def test_the_servers_own_socket_is_private_and_not_in_the_shared_dir(job):
    # the shared server dir has no socket; the fake's socket is in the job's local 0700 dir
    assert not any(os.path.exists(os.path.join(job.dir, n)) for n in ("s", "sock"))
    assert job.socks and all(oct(os.stat(os.path.dirname(p)).st_mode & 0o777) == "0o700" for p in job.socks)
    assert all(not p.startswith(job.dir) for p in job.socks)


def test_sigterm_ends_the_job_and_cleans_up(job):
    assert job.socks
    job.proc.send_signal(signal.SIGTERM)
    job.proc.wait(30)
    assert sorted(os.listdir(job.dir)) == ["client.crt"]                # endpoint, cert, fingerprint removed
    for p in job.socks:
        assert not os.path.exists(os.path.dirname(p))                  # the local dir (socket, key) is gone
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", job.port_), timeout=2)  # no listener outlives the job


def test_the_job_ends_with_the_server(job):
    """Kill the server (its process group): the relay notices and the job exits, cleaned up."""
    out = subprocess.run(["pgrep", "-f", "fake_ide.py"], capture_output=True, text=True).stdout.split()
    mine = [int(p) for p in out if _is_child_of(int(p), job.proc.pid)]
    assert mine
    for p in mine:
        os.kill(p, signal.SIGKILL)
    assert job.proc.wait(30) is not None
    assert not os.path.exists(os.path.join(job.dir, "endpoint"))


def _is_child_of(pid, parent):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return int(f.read().rsplit(")", 1)[1].split()[1]) == parent
    except (OSError, ValueError, IndexError):
        return False


def test_a_restarted_job_has_a_new_certificate_and_key(tmp_path):
    fps = []
    for _ in range(2):
        d = tempfile.mkdtemp(prefix="wpk-srv-")
        h = str(tmp_path / "h")
        _, crt = ide_tls.client_cert(h)
        import shutil
        shutil.copy(crt, os.path.join(d, "client.crt"))
        p = subprocess.Popen([sys.executable, "-m", "work_packet.sched.ide_job", d, "--transport", "mtls", "--",
                              sys.executable, FAKE_IDE, str(tmp_path / "pids"), "{sock}", "/ide/k"])
        wait_for(os.path.join(d, "endpoint"))
        fps.append(open(os.path.join(d, "fingerprint")).read())
        stop_job(p, tmp_path / "pids")
        shutil.rmtree(d, ignore_errors=True)
    assert fps[0] != fps[1]


def test_ide_job_tcp_mode_is_unchanged(tmp_path):
    d = tempfile.mkdtemp(prefix="wpk-srv-")
    p = subprocess.Popen([sys.executable, "-m", "work_packet.sched.ide_job", d, "--", sys.executable, FAKE_IDE,
                          str(tmp_path / "pids"), "-", "/ide/k", "--host", "127.0.0.1", "--port", "{port}"])
    try:
        wait_for(os.path.join(d, "endpoint"))
        assert os.listdir(d) == ["endpoint"]
    finally:
        stop_job(p, tmp_path / "pids")


# --- the proxy, end to end -----------------------------------------------------------------------

def test_proxy_to_a_job_over_mtls(home, tmp_path):
    from work_packet.dash.app import create_app
    config(home, jobs=2, ide={"slot": True, "transport": "mtls"})
    pool = Pool(home)
    try:
        bs = mtls_backends(home, tmp_path, poke=pool.poke.set)
        key = bs.register("/x", size="look")
        c = TestClient(create_app(home, ide_backend=bs), base_url="http://127.0.0.1:7878")
        c.__enter__()
        r, seen = get_until_up(c, "/ide/%s/" % key)
        echoed = json.loads(r.text.split('<pre id="seen">')[1].split("</pre>")[0])
        assert "vscode-tkn" not in json.dumps(echoed)                     # no token to leak
        sdir = os.path.join(home, "ide", "servers", key)
        assert not os.path.exists(os.path.join(sdir, "token"))
        host, port = ide.endpoint(key, home)
        # the only way in over TCP is the pinned handshake
        s = socket.create_connection((host, port), timeout=5)
        s.sendall(b"GET /ide/%s/ HTTP/1.1\r\nHost: x\r\n\r\n" % key.encode())
        s.settimeout(5)
        try:
            got = s.recv(100)
        except (ConnectionError, socket.timeout):
            got = b""
        assert b"HTTP/1." not in got
        with c.websocket_connect("ws://127.0.0.1:7878/ide/%s/x" % key,
                                 headers={"origin": "http://127.0.0.1:7878"}) as ws:
            first = json.loads(ws.receive_text())
            assert "vscode-tkn" not in (first["cookie"] or "")
            ws.send_text("hello")
            assert ws.receive_text() == "hello"
            ws.send_bytes(b"\x00\x01binary")
            assert ws.receive_bytes() == b"\x00\x01binary"
        body = c.post("/ide/%s/echo" % key, content=b"x" * 3_000_000).content
        assert body == b"x" * 3_000_000
        assert kinds(home) == ["ide"] and jobs.all(home)[0].size == "look"
        from work_packet import ide_launch
        cur = ide_launch.current(home, key)                 # the launch record works over mtls too
        assert cur["backend"] == "job" and cur["host"] == socket.gethostname() and cur["pid"]
        fp1 = open(os.path.join(sdir, "fingerprint")).read()
        # key material: the home has wpkd's client key and no other private key
        keys = []
        for root, _, files in os.walk(home):
            for n in files:
                try:
                    if "PRIVATE KEY" in open(os.path.join(root, n), errors="replace").read():
                        keys.append(os.path.relpath(os.path.join(root, n), home))
                except OSError:
                    pass
        assert keys == ["ide/client.key"] and oct(os.stat(os.path.join(home, "ide", "client.key")).st_mode & 0o777) == "0o600"
        # a board restart re-attaches through the files on disk
        c.__exit__(None, None, None)
        bs2 = mtls_backends(home, tmp_path, poke=pool.poke.set)
        c2 = TestClient(create_app(home, ide_backend=bs2), base_url="http://127.0.0.1:7878")
        with c2:
            assert c2.get("/ide/%s/" % key).status_code == 200
            # a job restart: a new fingerprint, which wpkd follows
            bs2.get(key)._stop_now()
            pool.poke.set()
            deadline = time.time() + 30
            while jobs.all(home) and time.time() < deadline:
                time.sleep(0.1)
            assert jobs.all(home) == [] and ide.endpoint(key, home) is None
            r2, _ = get_until_up(c2, "/ide/%s/" % key)
            assert open(os.path.join(sdir, "fingerprint")).read() != fp1
            bs2.get(key)._stop_now()
            pool.poke.set()
    finally:
        pool.close()


def test_a_server_with_a_different_certificate_is_refused_by_the_proxy(home, tmp_path):
    """wpkd trusts only the certificate the job wrote to the user's own directory."""
    from work_packet.dash.ide import MtlsJobBackend
    cfg = dict(schema.IDE_DEFAULTS, web=True)
    be = MtlsJobBackend(home, cfg, "k1", argv=[sys.executable, FAKE_IDE, "x"])
    from work_packet.dash.ide import private_dirs
    private_dirs(home, "k1")
    ide_tls.client_cert(home)
    d = be.dir
    # an impostor with its own certificate listens; the published server.crt is a different one
    ik, ic = os.path.join(d, "imp.key"), os.path.join(d, "imp.crt")
    ide_tls.make_cert(ik, ic, 1, "impostor")
    ok, oc = os.path.join(d, "real.key"), os.path.join(d, "server.crt")
    ide_tls.make_cert(ok, oc, 1, "real")
    _, client_crt = ide_tls.client_cert(home)
    import threading
    srv_ctx = ide_tls.pinned_server_context(ic, ik, client_crt)
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(5)
    port = ls.getsockname()[1]

    def accept():
        try:
            c, _ = ls.accept()
            srv_ctx.wrap_socket(c, server_side=True).close()
        except Exception:                      # noqa: BLE001
            pass
    threading.Thread(target=accept, daemon=True).start()
    with open(os.path.join(d, "endpoint"), "w") as f:
        f.write("127.0.0.1:%d\n" % port)
    assert be._connectable() is False


# --- config ---------------------------------------------------------------------------------------

def test_the_transport_setting_is_validated():
    ok = schema.validate_config({"sched": {"ide": {"transport": "mtls"}}})
    assert not [p for p in ok if p.level == "error"]
    ok = schema.validate_config({"sched": {"ide": {"transport": "tcp-token"}}})
    assert not [p for p in ok if p.level == "error"]
    bad = schema.validate_config({"sched": {"ide": {"transport": "carrier-pigeon"}}})
    assert any("sched.ide.transport" in p.field for p in bad if p.level == "error")


def test_tcp_token_stays_the_default(home, tmp_path):
    from work_packet.dash.ide import Backends, JobBackend, MtlsJobBackend
    cfg = dict(schema.IDE_DEFAULTS, web=True)
    for transport, cls in (("tcp-token", JobBackend), ("mtls", MtlsJobBackend)):
        bs = Backends(home, cfg, argv=[sys.executable, FAKE_IDE, str(tmp_path / "p")], slot=True, transport=transport)
        key = bs.register("/z")
        assert type(bs.get(key)) is cls
    assert Backends(home, cfg, slot=True).transport == "tcp-token"


# --- an IDE job gets node_env, like a step -------------------------------------------------------

def test_an_ide_job_runs_under_node_env_and_the_size_env():
    from work_packet.sched import config as sconfig
    from work_packet.sched.backends import Task
    from work_packet.sched.backends.slurm import Slurm
    c = sconfig.load(raw={"sched": {"backend": "slurm", "node_env": "source /site/node-env.sh",
                                    "sizes": {"sim": {"cpus": 2, "env": "module load x"}}}})
    t = Task("j", "ide", "p", "w", "/x", sconfig.size(c, "sim"), "/h/j.log", argv=["python", "-m", "m", "a b"],
             name="n")
    assert Slurm(c).submit_argv(t)[-1] == "source /site/node-env.sh && module load x && exec python -m m 'a b'"
    c2 = sconfig.load(raw={"sched": {"backend": "slurm"}})
    t.size = sconfig.size(c2, "look")
    assert Slurm(c2).submit_argv(t)[-1] == "exec python -m m 'a b'"
