"""A child that stops wakes its sleeping parent (docs/waiting-v1.md §4)."""
import os

import pytest

from conftest import NOW, ROOT, child_wpid
from work_packet import executor, scheduler, waiting
from work_packet.check import check
from work_packet.packet import Packet

LATER = "2099-01-01T00:00:00Z"


def status(pkt):
    return pkt.load_status()[0]


def _set(pkt, **kw):
    meta, body = pkt.load_status()
    meta.update(kw)
    pkt.save_status(meta, body)


def _child(proj):
    return Packet(os.path.join(proj, "packets", child_wpid(ROOT, 2, 0)))


def _entries(proj):
    return [{"name": "demo", "path": proj}]


def test_child_completion_wakes_sleeping_parent(project, fake):
    proj, root = project
    _set(root, state="SLEEPING", wake_at=LATER, children_seen={_child(proj).wpid: "RUNNABLE"})
    child = _child(proj)
    assert executor.step(child.path).code == 0
    assert status(child)["state"] == "COMPLETED"
    st = status(root)
    assert (st["state"], st["wake_at"]) == ("RUNNABLE", None)
    woke = [r for r in root.journal().records if r["type"] == "admin"][-1]
    assert (woke["op"], woke["by"]) == ("wake", "child %s COMPLETED" % child.wpid[:8])
    assert check(proj).issues == []


def test_a_stop_the_parent_has_seen_does_not_wake_it(project):
    proj, root = project
    child = _child(proj)
    _set(child, state="COMPLETED", updated=NOW)
    _set(root, state="SLEEPING", wake_at=LATER, children_seen={child.wpid: "COMPLETED"})
    assert waiting.wake_parent(child) is None
    assert status(root)["state"] == "SLEEPING"
    assert scheduler.due(_entries(proj)) == []


def test_parent_step_records_what_its_prompt_showed(project, fake):
    proj, root = project
    assert executor.step(root.path).code == 0
    assert status(root)["children_seen"] == {_child(proj).wpid: "RUNNABLE"}
    assert check(proj).issues == []


def test_due_finds_a_missed_wake(project):
    """The parent was mid-step when the child stopped, then went to sleep."""
    proj, root = project
    child = _child(proj)
    _set(root, state="SLEEPING", wake_at=LATER, children_seen={child.wpid: "RUNNABLE"})
    _set(child, state="NEEDS_INPUT", reason="which repo?")
    assert [d.wpid for d in scheduler.due(_entries(proj))] == [ROOT]
    assert executor._due(root, status(root), executor.clock.now())


def test_without_children_seen_only_later_stops_count(project):
    proj, root = project
    child = _child(proj)
    _set(child, state="COMPLETED", updated="2026-10-20T00:00:00Z")
    _set(root, state="SLEEPING", wake_at=LATER, updated="2026-10-21T00:00:00Z")
    assert waiting.unseen_stops(root, status(root)) == []
    _set(child, updated="2026-10-22T00:00:00Z")
    assert waiting.unseen_stops(root, status(root)) == [(child.wpid, "COMPLETED")]


def test_running_child_does_not_wake(project):
    proj, root = project
    _set(root, state="SLEEPING", wake_at=LATER, children_seen={})
    assert waiting.wake_parent(_child(proj)) is None
    assert status(root)["state"] == "SLEEPING"


def test_new_projects_may_run_sub_agents_with_room_for_them(tmp_path, fake):
    """waiting-v1 §3: Agent is a default tool, and the default budget grows with it."""
    from work_packet import project
    from work_packet.cli import main
    project.new("subs", "Do it.\n", path=str(tmp_path / "subs"))
    st = project.settings(str(tmp_path / "subs"))
    assert "Agent" in st.allowed_tools and st.step_budget_usd == 3.00
    assert main(["set", "subs", "step_budget_usd=1.5"]) == 0
    assert project.settings(str(tmp_path / "subs")).step_budget_usd == 1.5
    assert main(["deny", "subs", "Agent"]) == 0
    assert main(["set", "subs", "step_budget_usd="]) == 0
    assert project.settings(str(tmp_path / "subs")).step_budget_usd == 1.00


def test_overview_lists_stalled_requests_and_stuck_sleepers(tmp_path, fake, monkeypatch):
    """waiting-v1 §5.3: what nobody is working on shows in Needs attention."""
    import subprocess
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient
    from conftest import _new_packet
    from work_packet import project, registry, requests, setup
    from work_packet.dash.app import create_app
    monkeypatch.setattr(setup, "run_fix", lambda cmd, cwd=None: subprocess.CompletedProcess(
        cmd, 1, "", "no clones in tests"))
    project.new("asker", "Do it.\n", path=str(tmp_path / "asker"))
    root = Packet(registry.resolve("asker"))
    os.makedirs(os.path.join(root.state_dir, "requests"))
    with open(requests.brief_path(root.state_dir, "lib"), "w") as fp:
        fp.write("---\ntitle: Fix lib\nto: worker\nrepo:\n  - name: lib\n    from: /nowhere/lib\n"
                 "---\n## Task\nIt.\n\n## Done when\nDone.\n")
    requests.send(root, "lib")
    worker = Packet(registry.resolve("worker"))
    assert worker.load_status()[0]["state"] == "PAUSED"
    kid = _new_packet(os.path.dirname(root.path), child_wpid(root.wpid, 1, 0), "asker", "x\n",
                      parent=root.wpid, spawn_key="%s:1:0" % root.wpid)
    _set(kid, state="COMPLETED")
    _set(root, state="SLEEPING", wake_at=LATER, children=[kid.wpid],
         children_seen={kid.wpid: "RUNNABLE"})
    client = TestClient(create_app())
    page = client.get("/").text
    assert "REQUEST" in page and "request <code>lib</code>" in page
    assert "nobody is working on it" in page
    assert 'action="/p/worker/%s/act"' % worker.wpid in page
    assert "ASLEEP" in page and "<code>%s</code> is COMPLETED" % kid.wpid[:8] in page
    r = client.post("/p/worker/%s/act" % worker.wpid,
                    data={"action": "handoff", "back": "overview"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?")
    assert r.headers["location"].endswith("#attention")
    assert worker.load_status()[0]["state"] == "RUNNABLE"
    r = client.post("/p/asker/%s/act" % root.wpid, data={"action": "wake", "back": "overview"},
                    follow_redirects=False)
    assert "ok=1" in r.headers["location"] and status(root)["state"] == "RUNNABLE"
    page = client.get("/").text
    assert "REQUEST" not in page and "ASLEEP" not in page


def _waiter(proj, root, fake, period):
    fake(behavior="waiter")
    with open(os.path.join(root.state_dir, "period.md"), "w") as fp:
        fp.write(period + "\n")
    return executor.step(root.path)


def _kids(root):
    return [Packet(os.path.join(os.path.dirname(root.path), w))
            for w in status(root)["children"]]


def test_wait_all_wakes_when_every_child_stopped(tmp_path, fake):
    from conftest import make_project
    proj, root = make_project(tmp_path)
    assert _waiter(proj, root, fake, "wait a, b").code == 0
    st = status(root)
    a, b = _kids(root)
    assert (st["state"], st["wait_mode"], st["waiting_on"]) == ("SLEEPING", "all",
                                                                [a.wpid, b.wpid])
    assert executor.step(a.path).code == 0 and status(a)["state"] == "COMPLETED"
    assert status(root)["state"] == "SLEEPING"           # b still runs
    assert ROOT not in [d.wpid for d in scheduler.due(_entries(proj))]
    assert executor.step(b.path).code == 0
    assert status(root)["state"] == "RUNNABLE"
    assert executor.step(root.path).code == 0
    st = status(root)
    assert "waiting_on" not in st and "wait_mode" not in st
    assert check(proj).issues == []


def test_wait_any_wakes_on_the_first(tmp_path, fake):
    from conftest import make_project
    proj, root = make_project(tmp_path)
    assert _waiter(proj, root, fake, "wait any children, at most in 2 hours").code == 0
    st = status(root)
    assert (st["state"], st["wait_mode"]) == ("SLEEPING", "any")
    assert st["resume_expr"] == "wait any children, at most in 2 hours"
    a, b = _kids(root)
    assert executor.step(a.path).code == 0
    assert status(root)["state"] == "RUNNABLE"


def test_wait_on_an_unknown_name_fails_the_attempt(tmp_path, fake):
    from conftest import make_project
    proj, root = make_project(tmp_path)
    out = _waiter(proj, root, fake, "wait a, nope")
    assert out.code == 1 and "no child spawned with that name" in out.msg
    assert status(root)["children"] == []


def test_wait_request_counts_results_that_are_back(tmp_path, fake, monkeypatch):
    from work_packet import requests
    from conftest import make_project
    proj, root = make_project(tmp_path)
    _set(root, state="SLEEPING", wake_at=LATER,
         waiting_on=["request:lib"], wait_mode="all")
    assert not waiting.satisfied(root, status(root))
    e = {"id": "lib", "state": "delivered", "from": {"wpid": ROOT}}
    monkeypatch.setattr(requests, "get", lambda w, rid, h=None: e if rid == "lib" else None)
    assert waiting.satisfied(root, status(root))
    _set(root, waiting_on=["request:lib", "request:other"])
    assert not waiting.satisfied(root, status(root))
    _set(root, wait_mode="any")
    assert waiting.satisfied(root, status(root))
