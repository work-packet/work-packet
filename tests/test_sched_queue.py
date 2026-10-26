"""Order, fair share, sizes, backfill and room (docs/scheduler.md §3.3, §5.2, §6.2).

Most tests plan over synthetic items with ``gates.plan``; the dispatcher's
own tests are in test_sched_dispatch.py.
"""

import uuid
from datetime import datetime, timedelta, timezone

from work_packet import schema
from work_packet.sched import gates, queue
from work_packet.sched.config import Limits, Size

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
LOOK = Size("look", 1, 4096)
SIM = Size("sim", 8, 32768)


def wp(project, n):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, "%s-%d" % (project, n)))


def item(project, n=0, cls="normal", size=LOOK, waited_min=1, nxt=False, aged=None):
    due = NOW - timedelta(minutes=waited_min)
    return queue.Item(project, wp(project, n), "/p/%s/%d" % (project, n), "RUNNABLE",
                      schema.format_timestamp(due), cls, "project", aged or cls, size,
                      "default", next=nxt, waited_s=waited_min * 60.0)


def ctx(projs, cores=0, mem=0, jobs=0, usage=None, mode="run", backfill_min=10,
        spare=LOOK):
    ps = {}
    for p in projs:
        if isinstance(p, queue.Project):
            ps[p.name] = p
        else:
            ps[p] = queue.Project(p, {}, ["look", "sim"])
    return gates.Ctx(cfg={}, now=NOW, mode={"mode": mode}, limits=Limits(cores, mem, jobs),
                     usage=usage or gates.Usage(), projs=ps, backfill_for_s=backfill_min * 60,
                     spare=spare)


def plan(items, c, limit=None):
    return gates.plan(items, c, queue.order, limit)


def names(started):
    return [(i.project, i.wpid) for i in started]


def test_strict_class_order():
    items = [item("a", 0, "low", waited_min=600), item("b", 0, "normal", waited_min=5),
             item("c", 0, "high", waited_min=1), item("d", 0, "urgent", waited_min=0)]
    start, why = plan(items, ctx("abcd", jobs=2))
    assert [i.project for i in start] == ["d", "c"]
    assert why[("b", wp("b", 0))].code == "room"
    assert why[("a", wp("a", 0))].code == "room"


def test_fair_share_between_projects():
    many = [item("a", n, waited_min=100 - n) for n in range(40)]
    one = [item("b", 0, waited_min=1)]                 # due last of all
    start, _ = plan(many + one, ctx("ab", cores=4))
    assert len(start) == 4
    assert [i.project for i in start].count("b") == 1  # b gets its turn
    assert [i.project for i in start][:2] == ["a", "b"]


def test_weight():
    ps = [queue.Project("a", {}, ["look"], weight=3.0), queue.Project("b", {}, ["look"])]
    items = [item("a", n, waited_min=100 - n) for n in range(10)] + \
        [item("b", n, waited_min=50 - n) for n in range(10)]
    start, _ = plan(items, ctx(ps, cores=8))
    got = [i.project for i in start]
    assert got.count("a") == 6 and got.count("b") == 2


def test_oldest_first_within_a_project():
    items = [item("a", 0, waited_min=5), item("a", 1, waited_min=50), item("a", 2, waited_min=20)]
    start, _ = plan(items, ctx("a", jobs=3))
    assert [i.wpid for i in start] == [wp("a", 1), wp("a", 2), wp("a", 0)]


def test_run_next_goes_first():
    items = [item("a", 0, "urgent", waited_min=60), item("b", 0, "low", nxt=True)]
    start, _ = plan(items, ctx("ab", jobs=1))
    assert start[0].project == "b"


def test_backfill_then_stop_after_backfill_for():
    used = gates.Usage()
    used.add("x", 4, 0, "look")                        # 4 of 8 cores taken elsewhere
    big = item("a", 0, "high", SIM, waited_min=5)
    smalls = [item("b", n, "normal", waited_min=3) for n in range(6)]
    start, why = plan([big] + smalls, ctx("abx", cores=8, usage=used))
    assert len(start) == 4 and all(i.project == "b" for i in start)    # backfilled
    assert why[big.key].code == "room"
    used = gates.Usage()
    used.add("x", 4, 0, "look")
    big = item("a", 0, "high", SIM, waited_min=11)     # past backfill_for
    start, why = plan([big] + smalls, ctx("abx", cores=8, usage=used))
    assert start == []
    assert why[big.key].code == "room"
    assert why[smalls[0].key].code == "backfill"
    assert "waiting behind a" in why[smalls[0].key].text


def test_too_big_does_not_block_backfill():
    big = item("a", 0, "high", SIM, waited_min=60)
    start, why = plan([big, item("b")], ctx("ab", cores=4))
    assert why[big.key].code == "too_big"
    assert names(start) == [("b", wp("b", 0))]


def test_no_starvation_of_a_big_job():
    """Look steps arrive every minute and run 5 minutes; a sim waits for 8 cores.
    Backfill lets looks past it for backfill_for (10 min), then the cores drain to it."""
    running, queued = [], []                          # running: (end minute, Item)
    sim = item("s", 0, "normal", SIM, waited_min=0)   # due at minute 0
    started_at = None
    for minute in range(50):
        running = [(e, i) for e, i in running if e > minute]
        look = item("l", minute, "normal", waited_min=-minute)    # due on arrival
        queued.append(look)
        for q in queued + [sim]:
            q.waited_s = (minute * 60.0 - (schema.parse_timestamp(q.due) - NOW)
                          .total_seconds())
        usage = gates.Usage()
        for _, i in running:
            usage.add_item(i)
        start, _ = plan(queued + ([sim] if started_at is None else []), ctx("ls", cores=8,
                                                                            usage=usage))
        for i in start:
            running.append((minute + 5, i))
            if i is sim:
                started_at = minute
            else:
                queued.remove(i)
    assert started_at is not None and 10 <= started_at <= 10 + 5
    assert len(queued) < 50                           # and the looks kept moving


def test_spare_room_for_background():
    bg = item("a", 0, "background")
    start, _ = plan([bg], ctx("a", cores=2))
    assert len(start) == 1
    used = gates.Usage()
    used.add("x", 1, 0, "look")
    start, why = plan([item("a", 0, "background")], ctx("ax", cores=2, usage=used))
    assert start == [] and why[bg.key].code == "spare"
    # normal work may take that last core
    start, _ = plan([item("a", 1, "normal")], ctx("ax", cores=2, usage=used))
    assert len(start) == 1


def test_each_pool_limit_binds():
    items = [item("a", n, size=LOOK, waited_min=10 - n) for n in range(8)]
    for kw, n in (({"cores": 3}, 3), ({"mem": 3 * 4096}, 3), ({"jobs": 2}, 2),
                  ({"cores": 5, "mem": 4 * 4096, "jobs": 6}, 4)):
        start, why = plan(items, ctx("a", **kw))
        assert len(start) == n, kw
        assert all(r.code == "room" for r in why.values())


def test_project_max_cores():
    p = queue.Project("a", {}, ["look"], max_cores=2)
    items = [item("a", n, waited_min=10 - n) for n in range(4)] + [item("b")]
    start, why = plan(items, ctx([p, "b"], cores=16))
    assert [i.project for i in start].count("a") == 2
    assert "b" in [i.project for i in start]
    assert why[("a", wp("a", 2))].code == "project_cores"


def test_mode_and_hold_gate_first():
    p = queue.Project("a", {"sched": "hold", "sched_by": "unix:me"}, ["look"], hold=True)
    start, why = plan([item("a"), item("b")], ctx([p, "b"], jobs=4))
    assert names(start) == [("b", wp("b", 0))]
    assert why[("a", wp("a", 0))].code == "hold"
    start, why = plan([item("b")], ctx("b", mode="drain"))
    assert start == [] and why[("b", wp("b", 0))].code == "mode"


def test_choose_size():
    from work_packet.sched import config as sconfig
    cfg = sconfig.load(raw={"sched": {"sizes": {"sim": {"cpus": 8, "mem": "32G"}}}})
    w = wp("a", 0)
    proj = queue.Project("a", {"size": "sim", "packets": {w: {"size": "look"}}}, ["look", "sim"])
    assert queue.choose_size(cfg, proj, w, "sim")[:2] == (sconfig.size(cfg, "sim"), "memento")
    assert queue.choose_size(cfg, proj, w, None)[1] == "packet"
    assert queue.choose_size(cfg, proj, wp("a", 1), None)[1] == "project"
    bare = queue.Project("b", {}, ["look"])
    s, where, notes = queue.choose_size(cfg, bare, w, "sim")      # not allowed here
    assert (s.name, where) == ("look", "default") and "no longer allows" in notes[0]
    odd = queue.Project("c", {"size": "huge"}, ["look"])
    s, where, notes = queue.choose_size(cfg, odd, w, None)
    assert s.name == "look" and "not in [sched.sizes]" in notes[0]
