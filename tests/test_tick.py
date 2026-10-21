import json
import os
import socket

import pytest

from work_packet import project, registry, scheduler
from work_packet.check import check
from work_packet.cli import main
from work_packet.packet import Packet


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return os.environ["WPK_HOME"]


def new(name, **kw):
    plan = project.new(name, "Read state/count.md (0 if missing), add one.", **kw)
    return plan, Packet(os.path.join(plan.path, "packets", plan.root))


def _set(pkt, **kw):
    meta, body = pkt.load_status()
    meta.update(kw)
    pkt.save_status(meta, body)


def test_until_idle_runs_prototype_to_completion(home, capsys):
    """E1 through the scheduler: E5's `wpk new` then `wpk tick`."""
    assert main(["new", "demo", "--prompt", "Count to 8."]) == 0
    assert main(["tick", "--until-idle"]) == 0
    e = registry.get("demo")
    pdir = os.path.join(e["path"], "packets")
    states = {w: Packet(os.path.join(pdir, w)).load_status()[0]["state"]
              for w in os.listdir(pdir)}
    assert sorted(states.values()) == ["COMPLETED", "COMPLETED"]
    child = [w for w in states if w != e["root"]][0]
    assert open(os.path.join(pdir, child, "state", "p.md")).read() == "Hello World\n"
    assert open(os.path.join(pdir, e["root"], "state", "count.md")).read() == "8\n"
    assert check(home).issues == []
    err = capsys.readouterr().err
    assert "9 steps: 9 committed, 0 failed, 0 skipped" in err


def test_one_tick_runs_step_one(home, capsys):
    """E5, second half: `wpk new` then `wpk tick` runs step 1."""
    _, root = new("demo")
    assert main(["tick"]) == 0
    assert root.load_status()[0]["step"] == 1
    assert "demo %s: step 1 committed" % root.wpid[:8] in capsys.readouterr().out


def test_max_steps(home):
    _, root = new("demo")
    res = scheduler.tick(registry.entries(), until_idle=True, max_steps=3)
    assert len(res.ran) == 3 and root.load_status()[0]["step"] == 3


def test_oldest_due_first_across_projects(home, capsys):
    _, a = new("aaa")
    _, b = new("bbb")
    _, c = new("ccc")
    _set(a, updated="2026-10-21T17:00:00Z")
    _set(b, state="SLEEPING", wake_at="2026-10-21T16:00:00Z", resume_expr="in 1 hour")
    _set(c, state="SLEEPING", wake_at="2026-10-21T19:00:00Z", resume_expr="in 1 hour")
    got = [d.project for d in scheduler.due(registry.entries())]
    assert got == ["bbb", "aaa"]                 # ccc is not due yet
    assert main(["tick", "--dry-run"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in out] == ["bbb", "aaa"]
    assert a.load_status()[0]["step"] == 0       # dry run ran nothing
    res = scheduler.tick(registry.entries(), jobs=1)
    assert [r.due.project for r in res.ran] == ["bbb", "aaa"]


def test_leased_and_paused_are_skipped(home):
    _, a = new("aaa")
    _, b = new("bbb")
    _, c = new("ccc")
    with open(a.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 1,
                   "attempt": 1, "expires": "2999-01-01T00:00:00Z"}, fp)
    _set(b, state="PAUSED", reason="by hand")
    assert [d.project for d in scheduler.due(registry.entries())] == ["ccc"]
    res = scheduler.tick(registry.entries(), until_idle=True)
    assert {r.due.project for r in res.ran} == {"ccc"}
    assert a.load_status()[0]["step"] == 0


def test_project_filter(home, capsys):
    _, a = new("aaa")
    _, b = new("bbb")
    assert main(["tick", "--project", "bbb"]) == 0
    assert (a.load_status()[0]["step"], b.load_status()[0]["step"]) == (0, 1)
    assert main(["tick", "--project", "nope"]) == 4


def test_jobs_bound_concurrency(home, fake, tmp_path, monkeypatch):
    log = str(tmp_path / "fake.log")
    monkeypatch.setenv("WPK_FAKE_LOG", log)
    fake(behavior="slow")
    for n in ("p1", "p2", "p3", "p4", "p5"):
        new(n)
    res = scheduler.tick(registry.entries(), jobs=2)
    assert res.count(0) == 5
    events = sorted((float(t), kind) for kind, t in
                    (line.split() for line in open(log)))
    live = peak = 0
    for _, kind in events:
        live += 1 if kind == "start" else -1
        peak = max(peak, live)
    assert peak == 2


def test_failing_packet_until_idle_stops(home, fake):
    _, root = new("demo")
    fake(fault="crash")
    res = scheduler.tick(registry.entries(), until_idle=True)
    assert res.count(1) == 3                       # max_attempts, then FAILED
    assert root.load_status()[0]["state"] == "FAILED"


def test_e4_through_tick(home, fake, monkeypatch):
    _, root = new("demo")
    fake(behavior="sleeper")
    with open(os.path.join(root.state_dir, "period.md"), "w") as fp:
        fp.write("in 10 days\n")
    scheduler.tick(registry.entries(), until_idle=True)
    assert root.load_status()[0]["wake_at"] == "2026-10-31T18:00:00Z"
    monkeypatch.setenv("WPK_NOW", "2026-10-31T17:59:59Z")
    assert scheduler.tick(registry.entries(), until_idle=True).ran == []
    monkeypatch.setenv("WPK_NOW", "2026-10-31T18:00:00Z")
    res = scheduler.tick(registry.entries(), until_idle=True)
    assert len(res.ran) == 1
    assert open(os.path.join(root.state_dir, "wakes.md")).read() == "2\n"
