"""A child that stops wakes its sleeping parent (docs/waiting-v1.md §4)."""
import os

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
