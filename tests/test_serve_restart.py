"""Restarting wpkd in place, keeping web VS Code (docs/serve-restart-plan.md)."""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from work_packet import ide_launch, project, schema  # noqa: E402
from work_packet.dash import ide_forward, restart  # noqa: E402
from work_packet.sched import home_lease, jobs  # noqa: E402
from work_packet.sched.backends import DONE, RUNNING, local  # noqa: E402

from test_ide import FAKE_IDE, _alive, _pids  # noqa: E402
from test_sched_login import config, wait  # noqa: E402


@pytest.fixture
def short_home(tmp_path, monkeypatch):
    """Unix socket paths are short: keep the home near /tmp."""
    import shutil
    import tempfile
    h = tempfile.mkdtemp(prefix="wpk-rs-")
    monkeypatch.setenv("WPK_HOME", h)
    monkeypatch.delenv(restart.ENV, raising=False)
    yield h
    held = home_lease.read(h)
    if held and held.get("host") == socket.gethostname() and \
            held.get("pid", 0) > 1 and held.get("pid") != os.getpid():
        try:
            os.kill(held["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass
    shutil.rmtree(h, ignore_errors=True)


def _backends(home, tmp_path):
    from work_packet.dash.ide import Backends
    return Backends(home, dict(schema.IDE_DEFAULTS, web=True),
                    argv=[sys.executable, FAKE_IDE, str(tmp_path / "pids")])


# -- the VS Code servers ---------------------------------------------------------


def test_a_detached_server_is_left_running_and_adopted_at_start(short_home, tmp_path):
    a = _backends(short_home, tmp_path)
    be = a.get(a.register("/x"))
    asyncio.run(be.ensure())
    [(pid, kid)] = _pids(tmp_path / "pids")
    lid = ide_launch.current(short_home, be.key)["launch_id"]
    a.detach()                                  # the board restarts
    assert _alive(pid) and os.path.exists(be.pid_path) and os.path.exists(be.sock)
    assert a.servers == {}
    b = _backends(short_home, tmp_path)

    async def adopt():
        got = await b.adopt()
        return got, b.servers[be.key]._idle is not None
    try:
        got, idle = asyncio.run(adopt())
        assert got == [be.key] and idle         # adopted at once, with its idle timer
        assert b.servers[be.key].proc == pid
        assert len(_pids(tmp_path / "pids")) == 1       # not a second server
        cur = ide_launch.current(short_home, be.key)
        assert cur["launch_id"] == lid and not cur.get("ended")
    finally:
        b.stop()
    assert wait(lambda: not _alive(pid) and not _alive(kid), 5)


def test_a_dead_leftover_is_cleared_and_its_launch_ended(short_home, tmp_path):
    a = _backends(short_home, tmp_path)
    be = a.get(a.register("/x"))
    asyncio.run(be.ensure())
    [(pid, kid)] = _pids(tmp_path / "pids")
    a.detach()
    os.killpg(pid, signal.SIGKILL)
    assert wait(lambda: not _alive(pid), 5)
    b = _backends(short_home, tmp_path)
    assert asyncio.run(b.adopt()) == []
    assert not os.path.exists(be.pid_path) and not os.path.exists(be.sock)
    assert ide_launch.current(short_home, be.key).get("ended")


# -- the lease ---------------------------------------------------------------------


def _held_by_me(h):
    with open(home_lease.path(h), "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(),
                   "started": "2026-11-01T00:00:00Z", "expires": "2999-01-01T00:00:00Z"}, fp)


def test_the_lease_of_the_image_before_the_exec_is_taken_over(short_home, monkeypatch):
    _held_by_me(short_home)
    with pytest.raises(home_lease.HomeBusy):    # a normal start never takes it
        home_lease.HomeLease(short_home).acquire()
    monkeypatch.setenv(restart.ENV, "abc")
    got = home_lease.HomeLease(short_home).acquire()
    try:
        assert got.mine["started"] == "2026-11-01T00:00:00Z"
        assert home_lease.read(short_home)["expires"] != "2999-01-01T00:00:00Z"
    finally:
        got.keep()
    assert home_lease.read(short_home)["pid"] == os.getpid()   # keep: the file stays


def test_another_pids_lease_is_not_taken_over(short_home, monkeypatch):
    other = subprocess.Popen(["sleep", "30"])     # the fixture kills the holder after
    try:
        with open(home_lease.path(short_home), "w") as fp:
            json.dump({"host": socket.gethostname(), "pid": other.pid,
                       "expires": "2999-01-01T00:00:00Z"}, fp)
        monkeypatch.setenv(restart.ENV, "abc")
        with pytest.raises(home_lease.HomeBusy):
            home_lease.HomeLease(short_home).acquire()
    finally:
        other.kill()
        other.wait()


# -- forward tokens, requests, the command line ---------------------------------------


def test_forward_tokens_survive_a_restart_and_expired_ones_do_not(tmp_path):
    now = [1000.0]
    a = ide_forward.Tokens(clock=lambda: now[0])
    live = a.issue("k1", 8000, 4242)
    old = a.issue("k2", 8001, "pin")
    a.by_token[old].used = now[0] - ide_forward.IDLE_S + 10
    path = str(tmp_path / "run" / "fwd.json")
    a.save(path)
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    now[0] += 20                                # `old` has gone idle meanwhile
    b = ide_forward.Tokens(clock=lambda: now[0])
    b.load(path)
    assert not os.path.exists(path)
    assert set(b.by_token) == {live}
    f = b.resolve(live)
    assert (f.key, f.port, f.identity) == ("k1", 8000, 4242)


def test_a_request_is_taken_once_and_answered_by_id(short_home):
    rid = restart.request(short_home, force=True, by="me")
    assert restart.take(short_home) == {"id": rid, "force": True, "by": "me",
                                        "at": pytest.approx(time.time(), abs=60)}
    assert restart.take(short_home) == {}               # a bare signal
    assert restart.status(short_home, rid) is None
    restart.set_status(short_home, ["other", rid], "done")
    assert restart.status(short_home, rid)["state"] == "done"
    assert restart.status(short_home, "nope") is None


def test_preflight_names_why_the_code_does_not_load(monkeypatch):
    assert restart.preflight() is None
    monkeypatch.setattr(restart, "PREFLIGHT", "import work_packet.no_such_module")
    assert "no_such_module" in restart.preflight()


def test_the_exec_drops_the_flags_of_the_asking_process(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/bin/wpk", "serve", "--detach", "--port", "9",
                                      "--restart", "--force"])
    assert restart.argv() == [sys.executable, "-m", "work_packet", "serve", "--port", "9"]


def test_force_needs_restart(short_home, capsys):
    from work_packet.cli import main
    assert main(["serve", "--force"]) != 0
    assert "--force goes with --restart" in capsys.readouterr().err
    assert main(["serve", "--restart", "--stop"]) != 0


# -- an adopted step that is our child ---------------------------------------------


def test_an_adopted_step_that_is_our_child_is_reaped_with_its_code():
    from work_packet import procs
    pid = os.posix_spawn(sys.executable, [sys.executable, "-c",
                                          "import time; time.sleep(0.5); raise SystemExit(3)"],
                         os.environ)
    ref = "%d:%s" % (pid, procs._stat(pid)["start"])
    be = local.Local()                          # the new image: no Popen for it
    assert be.poll([ref])[ref].state == RUNNING
    assert wait(lambda: procs.zombie(pid), 5)
    st = be.poll([ref])[ref]
    assert (st.state, st.code) == (DONE, 3)
    with pytest.raises(ProcessLookupError):     # reaped, not left a zombie
        os.kill(pid, 0)


# -- end to end: a real wpkd ---------------------------------------------------------


def _serve(*extra, timeout=90):
    return subprocess.run([sys.executable, "-m", "work_packet", "serve"] + list(extra),
                          capture_output=True, text=True, timeout=timeout, env=os.environ)


def _started(h):
    with open(os.path.join(h, "server.json")) as fp:
        return json.load(fp)["started"]


def test_restart_keeps_vscode_and_the_pid_waits_for_steps_or_not(
        fake, short_home, tmp_path, monkeypatch):
    """One slow test of the whole path: a VS Code server and a step that hangs
    survive ``--restart --force``; the same pid serves after; ``--stop`` still
    stops the server."""
    monkeypatch.chdir(tmp_path)
    config(short_home)
    a = _backends(short_home, tmp_path)         # a server an earlier board left
    be = a.get(a.register(str(tmp_path)))
    asyncio.run(be.ensure())
    [(ide, kid)] = _pids(tmp_path / "pids")
    a.detach()
    fake(fault="hang")
    project.new("demo", "Read state/count.md (0 if missing), add one.")
    r = _serve("--detach")
    assert r.returncode == 0, r.stderr
    pid = home_lease.live(short_home)["pid"]
    log = os.path.join(short_home, "log", "wpkd.log")
    assert wait(lambda: "took over 1 VS Code server" in open(log).read())
    assert wait(lambda: any(j.ref for j in jobs.all(short_home)))
    [job] = jobs.all(short_home)
    step = int(job.ref.split(":")[0])
    before = _started(short_home)

    r = _serve("--restart", "--wait", "2")             # waits for the hung step
    assert r.returncode == 0, r.stderr
    assert "waiting for 1 running step(s)" in r.stderr
    assert "still waiting for its running steps" in r.stderr
    assert _started(short_home) == before

    r = _serve("--restart", "--force")
    assert r.returncode == 0 and "restarted (pid %d)" % pid in r.stderr, r.stderr
    assert home_lease.live(short_home)["pid"] == pid
    assert "restarted in place (pid %d)" % pid in open(log).read()
    assert _alive(ide) and _alive(kid) and _alive(step)
    assert open(log).read().count("took over 1 VS Code server") == 2
    assert [j.id for j in jobs.all(short_home)] == [job.id]      # adopted, not re-run

    from work_packet.cli import main
    assert main(["sched", "halt"]) == 0          # no second attempt after the kill
    os.killpg(step, signal.SIGKILL)             # the new image reaps its old child
    assert wait(lambda: not os.path.exists("/proc/%d" % step))

    r = _serve("--stop")
    assert r.returncode == 0, r.stderr
    assert wait(lambda: not _alive(ide) and not _alive(kid), 10)


def test_a_restart_waiting_for_steps_still_serves_on_the_tailnet():
    """A restart sets _stop and waits for its steps, still serving: the
    tailnet listener closed at once, leaving only loopback up."""
    from work_packet.dash import server

    class Srv:
        should_exit = False

    async def go():
        b = object.__new__(server.Board)
        b._stop, b._close = asyncio.Event(), asyncio.Event()
        b.cfg, b.port, b.urls = {}, 0, {"tailnet": []}
        b._write_state = lambda: None
        started = []

        def start(kind, socks, tls=None, redirect_to=None):
            srv = Srv()

            async def serve():
                while not srv.should_exit:
                    await asyncio.sleep(0.01)
                for s in socks:
                    s.close()
            started.append(srv)
            return srv, asyncio.ensure_future(serve())
        b._start = start
        t = asyncio.ensure_future(b._tailnet(["127.0.0.1"]))
        await asyncio.sleep(0.1)
        b._stop.set()                       # the restart: waiting for steps
        await asyncio.sleep(0.1)
        assert started and not started[0].should_exit and not t.done()
        b._close.set()                      # now the servers close
        await asyncio.wait_for(t, 5)
        assert started[0].should_exit
    asyncio.run(go())
