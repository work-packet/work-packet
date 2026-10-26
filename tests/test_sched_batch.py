"""Backend behaviour shared by slurm and lsf, against the fake batch system
(plan Q4 test list, run for both backends so they cannot drift: Q6)."""

import json
import os
import sys
import time
from datetime import timedelta

import pytest
import tomli_w

from work_packet import clock, executor, journal, project
from work_packet.packet import Packet
from work_packet.sched import authz, config as sconfig, control, events, explain, jobs
from work_packet.sched.backends import PENDING, RUNNING, Task
from work_packet.sched.backends import get as get_backend
from work_packet.sched.dispatcher import Dispatcher, job_name

FAKEBATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebatch")
BIN = os.path.dirname(sys.executable)
SUBMIT = {"slurm": "sbatch", "lsf": "bsub"}
CANCEL = {"slurm": "scancel", "lsf": "bkill"}
POLL = {"slurm": "squeue", "lsf": "bjobs"}
NODE_FAIL = {"slurm": "node failure", "lsf": "job state UNKWN"}


@pytest.fixture(params=["slurm", "lsf"])
def backend(request):
    return request.param


@pytest.fixture
def home(fake, tmp_path, monkeypatch, backend):
    monkeypatch.chdir(tmp_path)
    fb = str(tmp_path / "fakebatch")
    monkeypatch.setenv("WPK_FAKEBATCH_DIR", fb)
    h = os.environ["WPK_HOME"]
    config(h, backend)
    yield h
    import signal
    for n in os.listdir(os.path.join(fb, "jobs")) if os.path.isdir(os.path.join(fb, "jobs")) else ():
        if n.endswith(".json"):
            j = json.load(open(os.path.join(fb, "jobs", n)))
            if j.get("pid"):
                try:
                    os.killpg(j["pid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


def config(h, backend, **sched):
    d = {"backend": backend, "poll": "1s", "node_env": "export PATH=%s:$PATH" % BIN,
         "slurm": {"bin": FAKEBATCH, "account": "dv", "partition": "batch"},
         "lsf": {"bin": FAKEBATCH, "project": "dv-agents", "queue": "normal"}}
    d.update(sched)
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "wb") as fp:
        tomli_w.dump({"sched": d}, fp)


def rules(*rs):
    d = os.environ["WPK_FAKEBATCH_DIR"]
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rules.json"), "w") as fp:
        json.dump(list(rs), fp)


def calls(name):
    p = os.path.join(os.environ["WPK_FAKEBATCH_DIR"], "calls.log")
    return [c for c in (json.loads(x) for x in open(p)) if c[0] == name]


def new(name):
    plan = project.new(name, "Read state/count.md (0 if missing), add one.")
    return plan, Packet(os.path.join(plan.path, "packets", plan.root))


def evs(h, type):
    return [e for e in events.read(h) if e["type"] == type]


def until(d, cond, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        d.reap()
        if cond():
            return True
        time.sleep(0.1)
    raise AssertionError("timed out; jobs: %s" % jobs.all(d.h))


def idle(d, timeout=40):
    until(d, lambda: not jobs.all(d.h), timeout)


def test_steps_run_to_completion_on_the_farm(home, backend):
    _, root = new("demo")
    d = Dispatcher()
    for _ in range(12):
        d.pass_once()
        idle(d)
        if root.load_status()[0]["state"] == "COMPLETED":
            break
    assert root.load_status()[0]["state"] == "COMPLETED"
    subs = calls(SUBMIT[backend])
    assert subs and all(("--account" if backend == "slurm" else "-P") in c for c in subs)
    f = evs(home, "finished")[0]
    assert f["code"] == 0 and f["wall_s"] is not None and f["cpu_s"] is not None
    assert len(calls(POLL[backend])) >= len(subs)
    ch = explain.core_hours(home)
    assert ch["by_size"]["look"]["jobs"] == len(evs(home, "finished"))


def test_a_pending_job_holds_room(home, backend):
    config(home, backend, jobs=1)
    rules({"match": "*", "pend_s": 999})
    new("aaa")
    new("bbb")
    d = Dispatcher()
    d.pass_once()
    d.pass_once()
    assert len(jobs.all(home)) == 1 and jobs.all(home)[0].state == "PENDING"
    assert len(calls(SUBMIT[backend])) == 1


def test_pending_long_once(home):
    rules({"match": "*", "pend_s": 999})
    new("demo")
    t = [clock.now()]
    d = Dispatcher(now=lambda: t[0])
    d.pass_once()
    t[0] += timedelta(minutes=31)
    d.pass_once()
    d.pass_once()
    assert len(evs(home, "pending_long")) == 1


@pytest.mark.parametrize("rule", [{"preempt_after_s": 0.5}, {"node_fail": True}])
def test_farm_failures_retry_uncounted(home, fake, rule, backend):
    why = "preempted" if "preempt_after_s" in rule else NODE_FAIL[backend]
    fake(fault="hang")
    _, root = new("demo")
    rules(dict(rule, match="*"))
    d = Dispatcher()
    d.pass_once()
    idle(d)
    assert evs(home, "lost")[0]["why"] == why
    assert jobs.lost(root.wpid, home)["reason"] == why
    rules()
    fake(fault=None)
    _, subs = d.pass_once()
    assert subs and subs[0].lost == why and subs[0].wpid == root.wpid
    idle(d)
    m = root.load_status()[0]
    assert m["step"] == 1 and m["attempts"] == 0
    recs = journal.read(root.journal_path).records
    failed = [r for r in recs if r["type"] == "step-failed"]
    assert all(r.get("counted") is False for r in failed)


def test_timeout_counts(home, fake):
    fake(fault="hang")
    _, root = new("demo")
    rules({"match": "*", "timeout_s": 1})
    d = Dispatcher()
    d.pass_once()
    idle(d)
    assert evs(home, "lost") == [] and jobs.lost(root.wpid, home) is None
    assert evs(home, "finished")[0]["how"] == "timeout"
    rules()
    fake(fault=None)
    d.pass_once()
    idle(d)
    recs = journal.read(root.journal_path).records
    failed = [r for r in recs if r["type"] == "step-failed"]
    assert len(failed) == 1 and "counted" not in failed[0]


def test_submit_failure_backs_off_and_recovers(home, backend):
    rules({"match": "*", "submit_fails": 1})
    new("demo")
    t = [clock.now()]
    d = Dispatcher(now=lambda: t[0])
    assert d.pass_once()[1] == []
    assert evs(home, "backend_down") and jobs.all(home) == []
    assert explain.snapshot(home)["backend_down"]["type"] == "backend_down"
    assert d.pass_once()[1] == []                         # backing off: no sbatch
    assert len(calls(SUBMIT[backend])) == 1
    t[0] += timedelta(seconds=31)
    assert len(d.pass_once()[1]) == 1
    assert evs(home, "backend_up") and explain.snapshot(home)["backend_down"] is None


def test_restart_adopts_and_cancels_the_paused(home, fake, backend):
    config(home, backend, jobs=2)
    fake(fault="hang")
    _, a = new("aaa")
    _, b = new("bbb")
    rules({"match": "*:%s:*" % b.wpid, "pend_s": 999})
    d1 = Dispatcher()
    d1.pass_once()
    until(d1, lambda: {r.wpid: r.state for r in jobs.all(home)} ==
          {a.wpid: RUNNING, b.wpid: PENDING})
    del d1
    assert executor.admin(b, "pause").code == 0           # while wpkd was down
    bref = [r.ref for r in jobs.all(home) if r.wpid == b.wpid][0]
    d2 = Dispatcher()
    d2.adopt()                                            # reaps: b's packet is PAUSED
    until(d2, lambda: [r.wpid for r in jobs.all(home)] == [a.wpid])
    assert any(c[-1] == bref for c in calls(CANCEL[backend]))
    assert evs(home, "cancelled")[-1]["wpid"] == b.wpid
    assert d2.pass_once()[1] == []                        # a is still running: no second job
    assert control.set_mode("stop", authz.principal_cli(), "done").code == 0
    idle(d2)


def test_a_job_without_a_record_is_adopted(home, fake):
    fake(fault="hang")
    _, root = new("demo")
    cfg = sconfig.load(home)
    b = get_backend(cfg, home)
    ref = b.submit(Task("x", "step", "demo", root.wpid, root.path, sconfig.size(cfg, "look"),
                        os.path.join(home, "sched", "jobs", "x.log"), step=1,
                        name=job_name(home, root.wpid, 1)))
    b.submit(Task("y", "step", "other", root.wpid, root.path, sconfig.size(cfg, "look"),
                  os.path.join(home, "sched", "jobs", "y.log"), step=1, name="someone-else"))
    d = Dispatcher()
    d.adopt()
    recs = jobs.all(home)
    assert [(r.ref, r.wpid, r.step) for r in recs] == [(ref, root.wpid, 1)]
    assert evs(home, "adopted")[0]["ref"] == ref
    assert d.pass_once()[1] == []
    assert control.set_mode("stop", authz.principal_cli(), "done").code == 0
    idle(d)


