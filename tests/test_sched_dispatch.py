"""The dispatcher with the local backend and the fake model (plan Q1.13-Q1.18)."""

import json
import os
import signal
import threading
import time

import pytest
import tomli_w

from work_packet import executor, journal, project, registry
from work_packet.cli import main
from work_packet.packet import Packet
from work_packet.sched import authz, control, events, jobs
from work_packet.sched.backends.local import Local
from work_packet.sched.dispatcher import Dispatcher

ME = authz.principal_cli()


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    h = os.environ["WPK_HOME"]
    yield h
    for r in jobs.all(h):                  # never leave a step running
        if r.ref and r.backend == "local":
            try:
                os.killpg(int(r.ref.split(":")[0]), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, ValueError):
                pass


def new(name, sizes=None):
    plan = project.new(name, "Read state/count.md (0 if missing), add one.")
    if sizes:
        project.set_values(plan.path, [("sizes", ",".join(sizes))], "test")
    return plan, Packet(os.path.join(plan.path, "packets", plan.root))


def write_config(h, d):
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "wb") as fp:
        tomli_w.dump(d, fp)


def wait(cond, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def until_idle(d, timeout=30):
    """Reap (start nothing) until no job is left."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        d.reap()
        if not jobs.all(d.h):
            return
        time.sleep(0.05)
    raise AssertionError("jobs still running: %s" % jobs.all(d.h))


def evs(h, type):
    return [e for e in events.read(h) if e["type"] == type]


def model_pid(pkt, step=1):
    p = os.path.join(pkt.step_dir(step), "model.pid")
    try:
        return int(open(p).read())
    except (OSError, ValueError):
        return None


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    st = open("/proc/%d/stat" % pid).read()
    return st[st.rindex(")") + 2] != "Z"


# --- filling slots -------------------------------------------------------------------

def test_slot_refilled_within_a_second(home, fake, tmp_path, monkeypatch):
    log = str(tmp_path / "fake.log")
    monkeypatch.setenv("WPK_FAKE_LOG", log)
    fake(behavior="slow")
    new("p1")
    new("p2")
    d = Dispatcher(jobs=1)
    subs = []
    real = d.backend.submit

    def submit(task):
        subs.append(time.time())
        return real(task)
    d.backend.submit = submit
    stop, poke = threading.Event(), threading.Event()
    t = threading.Thread(target=d.run, args=(stop, poke), kwargs={"max_wait": 5})
    t.start()
    try:
        assert wait(lambda: len(subs) == 2 and not jobs.all(home))
    finally:
        stop.set()
        poke.set()
        t.join(30)
    ends = [float(line.split()[1]) for line in open(log) if line.startswith("end")]
    assert subs[1] - ends[0] < 1.0
    assert [e["type"] for e in events.read(home)][0] == "wpkd_start"
    assert evs(home, "wpkd_stop")


def test_finished_events_and_report(home):
    _, root = new("demo")
    got = []
    d = Dispatcher(report=got.append)
    d.pass_once()
    until_idle(d)
    assert root.load_status()[0]["step"] == 1
    assert got[0].code == 0 and "step 1 committed" in got[0].msg
    f = evs(home, "finished")[0]
    assert (f["project"], f["wpid"], f["step"], f["size"], f["code"]) == \
        ("demo", root.wpid, 1, "look", 0)
    s = evs(home, "submitted")[0]
    assert s["cls"] == "normal" and s["by"] == "wpkd"
    assert os.listdir(jobs.jobs_dir(home)) == []          # record and log removed


# --- halt and stop -------------------------------------------------------------------

def test_drain_lets_the_running_step_commit(home, fake, tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_FAKE_LOG", str(tmp_path / "fake.log"))
    fake(behavior="slow")
    _, a = new("aaa")
    _, b = new("bbb")
    d = Dispatcher(jobs=1)
    d.pass_once()
    assert len(jobs.all(home)) == 1
    assert control.set_mode("drain", ME, "lunch").code == 0
    until_idle(d)
    states = sorted((a.load_status()[0]["step"], b.load_status()[0]["step"]))
    assert states == [0, 1]                               # one committed, one never started
    d.pass_once()
    assert jobs.all(home) == []
    assert len(evs(home, "submitted")) == 1


def test_stop_kills_and_does_not_count(home, fake):
    _, root = new("demo")
    fake(fault="hang")
    d = Dispatcher()
    d.pass_once()
    assert wait(lambda: model_pid(root) is not None)
    pid = model_pid(root)
    out = control.set_mode("stop", ME, "spending too much")
    assert out.code == 0 and "cancelled 1 job" in out.msg
    until_idle(d, timeout=40)
    assert not alive(pid)                                 # the model went with the step
    meta = root.load_status()[0]
    assert (meta["step"], meta["attempts"]) == (0, 0)
    assert jobs.lost(root.wpid, home)["reason"].startswith("stopped: spending")
    assert control.set_mode("run", ME).code == 0
    fake(fault=None)
    d.pass_once()
    sub = evs(home, "submitted")[-1]
    assert sub["lost"].startswith("stopped")
    until_idle(d)
    assert jobs.lost(root.wpid, home) is None
    recs = journal.read(root.journal_path).records
    failed = [r for r in recs if r["type"] == "step-failed"]
    assert len(failed) == 1 and failed[0]["counted"] is False
    assert "spending too much" in failed[0]["why"]
    starts = [r for r in recs if r["type"] == "step-start"]
    assert [s["attempt"] for s in starts] == [1, 1]       # the retry is attempt 1 again
    assert root.load_status()[0]["step"] == 1


def test_halt_survives_a_restart(home):
    new("demo")
    control.set_mode("drain", ME)
    d = Dispatcher()
    assert d.pass_once() == ([], [])
    assert Dispatcher().pass_once() == ([], [])
    control.set_mode("run", ME)
    assert len(Dispatcher().pass_once()[1]) == 1


def test_restart_adopts_a_running_job(home, fake):
    _, root = new("demo")
    fake(fault="hang")
    d1 = Dispatcher()
    d1.pass_once()
    assert wait(lambda: model_pid(root) is not None)
    rec = jobs.all(home)[0]
    del d1                                                # wpkd dies; its step runs on
    d2 = Dispatcher(backend=Local())
    d2.adopt()
    assert [r.id for r in d2.live()] == [rec.id]
    assert d2.pass_once()[1] == []                        # no second step
    out = control.set_mode("stop", ME, "test over")
    assert out.code == 0
    until_idle(d2, timeout=40)
    assert evs(home, "finished")[-1]["job"] == rec.id


def test_kill_after_term(home, fake, monkeypatch):
    """A step that ignores SIGTERM gets SIGKILL after KILL_AFTER_S."""
    from work_packet.sched import dispatcher
    monkeypatch.setattr(dispatcher, "KILL_AFTER_S", 0)
    _, root = new("demo")
    fake(fault="hang")
    d = Dispatcher()
    d.pass_once()
    assert wait(lambda: model_pid(root) is not None)
    mpid = model_pid(root)
    rec = jobs.all(home)[0]
    pid = int(rec.ref.split(":")[0])
    os.kill(pid, signal.SIGSTOP)                          # cannot act on the TERM
    control.set_mode("stop", ME, "test")
    until_idle(d, timeout=20)
    assert not alive(pid)
    assert wait(lambda: not alive(mpid))                  # the model went with it


# --- pending jobs, sizes, run next ------------------------------------------------------

def test_pause_cancels_a_pending_job(home, fakelocal):
    _, root = new("demo")
    d = Dispatcher(backend=fakelocal)
    _, subs = d.pass_once()
    assert len(subs) == 1 and jobs.all(home)[0].state == "PENDING"
    assert main(["pause", root.wpid]) == 0               # its own backend: marks it
    assert jobs.all(home)[0].cancel
    d.pass_once()                                        # wpkd's backend withdraws it
    assert fakelocal.cancelled == [("f1", False)]
    d.pass_once()
    assert jobs.all(home) == []
    assert evs(home, "cancelled")[0]["why"] == "packet no longer runnable"


def test_reaper_cancels_pending_job_of_a_paused_packet(home, fakelocal):
    _, root = new("demo")
    d = Dispatcher(backend=fakelocal)
    d.pass_once()
    assert executor.admin(root, "pause").code == 0        # by hand, around wpkd
    d.pass_once()
    assert fakelocal.cancelled == [("f1", False)]
    d.pass_once()
    assert jobs.all(home) == [] and d.pass_once() == ([], [])


def test_pending_jobs_hold_room_and_lost_jobs_retry_uncounted(home, fakelocal):
    write_config(home, {"sched": {"jobs": 1}})
    _, a = new("aaa")
    _, b = new("bbb")
    d = Dispatcher(backend=fakelocal)
    d.pass_once()
    assert len(jobs.all(home)) == 1                       # the pending one holds the slot
    assert d.pass_once()[1] == []
    first = jobs.all(home)[0]
    fakelocal.start(first.ref)
    d.pass_once()
    assert jobs.all(home)[0].state == "RUNNING" and evs(home, "started")
    fakelocal.lose(first.ref, "preempted")
    _, subs = d.pass_once()
    assert evs(home, "lost")[0]["why"] == "preempted"
    assert [s.wpid for s in subs] == [first.wpid]         # same packet, head of the line
    assert subs[0].lost == "preempted"
    assert fakelocal.tasks()[-1].lost == "preempted"


def test_max_pending_event_once(home, fakelocal):
    from datetime import timedelta
    from work_packet import clock
    new("demo")
    t = [clock.now()]
    d = Dispatcher(backend=fakelocal, now=lambda: t[0])
    d.pass_once()
    t[0] += timedelta(minutes=31)
    d.pass_once()
    d.pass_once()
    assert len(evs(home, "pending_long")) == 1


def test_run_next_is_used_once(home, fakelocal):
    write_config(home, {"sched": {"jobs": 1}})
    _, a = new("aaa")
    _, b = new("bbb")
    control.set_prio("aaa", "high", ME)
    assert control.run_next(b.wpid, ME).code == 0
    d = Dispatcher(backend=fakelocal)
    _, subs = d.pass_once()
    assert subs[0].project == "bbb"
    assert "packets" not in registry.get("bbb")           # used up
    fakelocal.finish(subs[0].ref)
    _, subs = d.pass_once()
    assert subs[0].project == "aaa"                       # high goes first again


def test_size_from_the_memento_for_one_step(home, fake):
    write_config(home, {"sched": {"sizes": {"sim": {"cpus": 8, "mem": "32G"}}}})
    fake(behavior="sized")
    _, root = new("demo", sizes=["look", "sim"])
    d = Dispatcher()
    for _ in range(4):
        d.pass_once()
        until_idle(d)
    sizes = [e["size"] for e in evs(home, "submitted")]
    assert sizes == ["look", "sim", "look", "sim"]
    assert root.load_status()[0]["state"] == "COMPLETED"
    prompt = open(os.path.join(root.state_dir, "prompt-1.md")).read()
    assert "## Job sizes" in prompt and "`sim`: 8 cores, 32G" in prompt


def test_disallowed_size_is_refused(home, fake):
    """A size the project does not allow fails the memento's check; the model is
    nudged with the allowed list (the fake then writes no size) or the step fails."""
    write_config(home, {"sched": {"sizes": {"sim": {"cpus": 8, "mem": "32G"}}}})
    fake(behavior="sized")
    _, root = new("demo")                                 # only look
    d = Dispatcher()
    d.pass_once()
    until_idle(d)
    recs = journal.read(root.journal_path).records
    why = [r for r in recs if r["type"] == "step-nudge"][0]["why"]
    assert "size: 'sim' is not one of this project's sizes: look" in why
    assert "next_size" not in root.load_status()[0]
    prompt = open(os.path.join(root.step_dir(1), "prompt.md")).read()
    assert "## Job sizes" not in prompt                  # one size: no section


def test_status_next_size_is_written_and_cleared(home, fake):
    write_config(home, {"sched": {"sizes": {"sim": {"cpus": 8}}}})
    fake(behavior="sized")
    _, root = new("demo", sizes=["look", "sim"])
    d = Dispatcher()
    d.pass_once()
    until_idle(d)
    assert root.load_status()[0]["next_size"] == "sim"
    d.pass_once()
    until_idle(d)
    assert "next_size" not in root.load_status()[0]
    from work_packet.check import check
    assert [i for i in check(home).issues if i.level == "error"] == []


def test_tick_honours_halt_and_hold(home, capsys):
    new("aaa")
    new("bbb")
    control.hold("aaa", ME)
    assert main(["tick"]) == 0
    assert "bbb" in capsys.readouterr().out
    control.set_mode("drain", ME)
    assert main(["tick"]) == 0
    assert "0 steps" in capsys.readouterr().err
