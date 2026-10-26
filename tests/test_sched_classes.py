"""Priority classes and aging (docs/scheduler.md §3.1, §3.2)."""

from work_packet.sched import classes

W = "11111111-2222-3333-4444-555555555555"
H = 3600


def test_effective_order():
    assert classes.effective({}, W) == ("normal", "default")
    assert classes.effective({"priority": "low"}, W) == ("low", "project")
    e = {"priority": "low", "packets": {W: {"priority": "urgent"}}}
    assert classes.effective(e, W) == ("urgent", "packet")
    # another packet of the same project has the project's class
    assert classes.effective(e, W.replace("1", "9"))[0] == "low"
    # a packet table without a priority (only a size) falls back too
    assert classes.effective({"packets": {W: {"size": "sim"}}}, W) == ("normal", "default")


def test_aging_steps_and_cap():
    a = 4 * H
    assert classes.aged("low", 3 * H, a) == "low"
    assert classes.aged("low", 4 * H, a) == "normal"
    assert classes.aged("low", 8 * H, a) == "high"
    assert classes.aged("low", 100 * H, a) == "high"            # never above high
    assert classes.aged("background", 4 * H, a) == "low"
    assert classes.aged("background", 12 * H, a) == "high"
    assert classes.aged("normal", 4 * H, a) == "high"
    assert classes.aged("high", 100 * H, a) == "high"
    assert classes.aged("urgent", 0, a) == "urgent"
    assert classes.aged("low", 100 * H, 0) == "low"              # aging off


def test_urgent_never_passed_by_aged_work():
    from work_packet.sched import gates, queue
    from work_packet.sched.config import Size
    look = Size("look", 1)
    old = queue.Item("a", W, "/x", "RUNNABLE", "2026-01-01T00:00:00Z", "background",
                     "project", classes.aged("background", 1000 * H, 4 * H), look, "default")
    new = queue.Item("b", W.replace("1", "2"), "/y", "RUNNABLE", "2026-10-21T17:59:00Z",
                     "urgent", "packet", "urgent", look, "default")
    projs = {"a": queue.Project("a", {}, ["look"]), "b": queue.Project("b", {}, ["look"])}
    got = queue.order([old, new], gates.Usage(), projs)
    assert [i.project for i in got] == ["b", "a"]
    assert old.aged == "high"
