"""The slurm backend against the fake batch system (plan Q4.1-Q4.5, T-d)."""

import json
import os
import sys
import time
from datetime import timedelta

import pytest
import tomli_w

from work_packet import clock, executor, journal, project, registry
from work_packet.packet import Packet
from work_packet.sched import authz, config as sconfig, control, events, explain, jobs
from work_packet.sched.backends import DONE, LOST, PENDING, RUNNING, Task
from work_packet.sched.backends.slurm import Slurm, cpu_seconds
from work_packet.sched.config import Size
from work_packet.sched.dispatcher import Dispatcher, job_name

FAKEBATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebatch")
BIN = os.path.dirname(sys.executable)


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fb = str(tmp_path / "fakebatch")
    monkeypatch.setenv("WPK_FAKEBATCH_DIR", fb)
    h = os.environ["WPK_HOME"]
    config(h)
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


def config(h, **sched):
    d = {"backend": "slurm", "poll": "1s", "node_env": "export PATH=%s:$PATH" % BIN,
         "slurm": {"bin": FAKEBATCH, "account": "dv", "partition": "batch"},
         "sizes": {"sim": {"cpus": 8, "mem": "32G", "time": "4h", "partition": "big",
                           "extra": ["--exclusive"]}}}
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


def test_submit_argv_per_size(home):
    cfg = sconfig.load(home)
    b = Slurm(cfg, home)
    task = Task("j1", "step", "p", "w", "/proj/packets/w", sconfig.size(cfg, "look"), "/h/j1.log",
                step=3, name="wpk:abcd1234:w:3")
    argv = b.submit_argv(task)
    assert argv[:8] == ["--parsable", "-J", "wpk:abcd1234:w:3", "-t", "2:05:00", "-c", "1",
                        "--mem"]
    assert argv[8:] == ["4096M", "-p", "batch", "--account", "dv", "-o", "/h/j1.log", "--wrap",
                        "export PATH=%s:$PATH && exec wpk step /proj/packets/w" % BIN]
    task.size, task.lost = sconfig.size(cfg, "sim"), "preempted"
    argv = b.submit_argv(task)
    assert argv[argv.index("-t") + 1] == "4:00:00" and argv[argv.index("-c") + 1] == "8"
    assert argv[argv.index("-p") + 1] == "big" and "--exclusive" in argv
    assert argv[-1].endswith("wpk step /proj/packets/w --lost preempted")
    assert "--constraint" not in argv
    task.size = sconfig._size("c", {"cpus": 2, "constraint": "avx512&ib"})
    argv = b.submit_argv(task)
    assert argv[argv.index("--constraint") + 1] == "avx512&ib"


def test_sacct_formats():
    assert cpu_seconds("01:02.500") == 62.5
    assert cpu_seconds("1:00:00") == 3600
    assert cpu_seconds("2-01:00:00") == 2 * 86400 + 3600
    st = Slurm._ended(["7", "COMPLETED", "0:0", "2026-10-26T10:00:00", "2026-10-26T10:05:00",
                       "04:10.250"])
    assert (st.state, st.code, st.cpu_s) == (DONE, 0, 250.25) and st.started.endswith("Z")
    assert Slurm._ended(["7", "FAILED", "1:0", "", "", ""]).code == 1
    t = Slurm._ended(["7", "TIMEOUT", "0:15", "", "", ""])
    assert t.state == DONE and t.counted and t.reason == "timeout"
    for state, why in (("PREEMPTED", "preempted"), ("NODE_FAIL", "node failure")):
        s = Slurm._ended(["7", state, "0:0", "", "", ""])
        assert (s.state, s.counted, s.reason) == (LOST, False, why)
    c = Slurm._ended(["7", "CANCELLED by 0", "0:15", "", "", ""])
    assert c.state == LOST and not c.counted and "by 0" in c.reason
    assert Slurm._ended(["7", "PENDING", "0:0", "", "", ""]).state == PENDING


def test_low_cpu_flag(home):
    from work_packet.sched.backends import JobState
    from work_packet.sched.gates import Usage  # noqa: F401
    _, root = new("demo")
    d = Dispatcher()
    now = clock.now()
    rec = jobs.JobRecord(id="j1", backend="slurm", kind="step", project="demo", wpid=root.wpid,
                         path=root.path, by="wpkd", size="sim", cpus=8, step=1, ref="1",
                         started=(now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    jobs.save(rec, home)
    d._ended(rec, JobState(DONE, code=0, cpu_s=30.0), now)
    f = evs(home, "finished")[-1]
    assert f["low_cpu"] is True and f["wall_s"] == 600
    ch = explain.core_hours(home, now - timedelta(days=1))
    assert ch["by_size"]["sim"]["core_h"] == pytest.approx(8 * 600 / 3600)
    assert ch["low_cpu"][0]["job"] == "j1"


def test_remote_lease_freed_when_the_job_ends(home):
    from work_packet.sched.backends import JobState
    _, root = new("demo")
    with open(root.lease_path, "w") as fp:
        json.dump({"host": "node17", "pid": 4242, "step": 1, "attempt": 1,
                   "expires": "2999-01-01T00:00:00Z"}, fp)
    rec = jobs.JobRecord(id="j2", backend="slurm", kind="step", project="demo", wpid=root.wpid,
                         path=root.path, by="wpkd", step=1, ref="9")
    jobs.save(rec, home)
    Dispatcher()._ended(rec, JobState(LOST, reason="node failure", counted=False), clock.now())
    assert not os.path.exists(root.lease_path)
    assert "removed the lease of job 9" in journal.read(root.journal_path).records[-1]["msg"]
    from work_packet import scheduler
    assert [d.wpid for d in scheduler.due(registry.entries())] == [root.wpid]
