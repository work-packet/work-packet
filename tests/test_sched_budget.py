"""The budget: periods, pace, ceilings by class, estimates, reservations, the
quota windows and project caps (docs/scheduler.md §4; plan Q2)."""

import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import tomli_w

from work_packet import project, schema
from work_packet.packet import Packet
from work_packet.sched import budget, events, gates, jobs, queue
from work_packet.sched import config as sconfig
from work_packet.sched.config import Limits, Size
from work_packet.sched.dispatcher import Dispatcher

UTC = timezone.utc
NOON = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)          # a Wednesday


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    budget._CACHE.clear()
    return os.environ["WPK_HOME"]


def new(name, **settings):
    plan = project.new(name, "Read state/count.md (0 if missing), add one.")
    if settings:
        project.set_values(plan.path, [(k, str(v)) for k, v in settings.items()], "test")
    return plan, Packet(os.path.join(plan.path, "packets", plan.root))


def write_config(h, d):
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "wb") as fp:
        tomli_w.dump(d, fp)


def meta(pkt, n, end, cost=None, tokens=None, quota=None, failed=None):
    name = "%04d" % n + (".failed-%d" % failed if failed else "")
    d = os.path.join(pkt.steps_dir, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w") as fp:
        json.dump({"step": n, "end": schema.format_timestamp(end), "cost_usd": cost,
                   "tokens": tokens or {}, "quota": quota}, fp)


def bcfg(**kw):
    b = {"measure": "usd", "amount": 100.0, "period": "day", "tz": "UTC",
         "default_step": 0.01}
    b.update(kw)
    return sconfig.load(raw={"sched": {"budget": b}})


def item(project_, wpid, cls="normal"):
    return queue.Item(project_, wpid, "/x", "RUNNABLE", "2026-10-21T11:00:00Z", cls, "project",
                      cls, Size("look", 1), "default")


def make(cfg, now, entries, records=(), projs=None, limits=None, h=None):
    projs = projs if projs is not None else queue.projects(entries, cfg)
    return budget.Budget(cfg, now, entries, list(records), projs, limits, h)


# --- periods and pace --------------------------------------------------------------

def test_period_bounds_dst_and_month_end():
    ny = ZoneInfo("America/New_York")
    t = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)            # the day DST ends
    s, e = budget.period_bounds("day", t, ny)
    assert (s.isoformat(), (e - s).total_seconds()) == ("2026-11-01T04:00:00+00:00", 25 * 3600)
    s, e = budget.period_bounds("week", t, ny)
    assert s == datetime(2026, 10, 26, 4, tzinfo=UTC) and e == datetime(2026, 11, 2, 5,
                                                                        tzinfo=UTC)
    s, e = budget.period_bounds("month", datetime(2026, 10, 31, 23, 59, tzinfo=UTC), UTC)
    assert (s, e) == (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))
    s, e = budget.period_bounds("month", datetime(2026, 12, 31, 12, tzinfo=UTC), UTC)
    assert e == datetime(2027, 1, 1, tzinfo=UTC)


def test_pace_straight_and_shaped():
    s, e = budget.period_bounds("day", NOON, UTC)
    assert budget.fraction(s, e, NOON) == 0.5
    assert budget.fraction(s, e, s - timedelta(hours=1)) == 0.0
    ws, we = budget.period_bounds("week", NOON, UTC)
    weekdays = {"weekday": [1, 1, 1, 1, 1, 0, 0]}
    # Wednesday noon: 2.5 of 5 working days
    assert abs(budget.fraction(ws, we, NOON, weekdays, UTC) - 0.5) < 1e-9
    sat = datetime(2026, 10, 24, 12, tzinfo=UTC)
    assert budget.fraction(ws, we, sat, weekdays, UTC) == 1.0
    hours = {"hour": [0] * 9 + [1] * 8 + [0] * 7}            # 09:00-17:00 only
    assert abs(budget.fraction(s, e, NOON, hours, UTC) - 3 / 8) < 1e-9


# --- spend ---------------------------------------------------------------------------

def test_each_measure_spent(home):
    _, a = new("aaa")
    meta(a, 1, NOON - timedelta(hours=1), cost=2.0,
         tokens={"input_tokens": 100, "cache_creation_input_tokens": 1000,
                 "cache_read_input_tokens": 10000, "output_tokens": 50})
    meta(a, 2, NOON - timedelta(hours=2), cost=1.0, failed=1)          # failed counts
    meta(a, 3, NOON - timedelta(days=1), cost=50.0)                    # yesterday
    from work_packet import registry
    es = registry.entries()
    assert make(bcfg(), NOON, es).windows[0].spent == 3.0
    t = make(bcfg(measure="tokens", amount=1e6), NOON, es).windows[0]
    assert t.spent == 100 + 1000 + 50 + 0.1 * 10000
    w = make(bcfg(period="week"), NOON, es).windows[0]
    assert w.spent == 53.0


def test_ledger_sees_a_new_step(home):
    from work_packet import registry
    _, a = new("aaa")
    meta(a, 1, NOON - timedelta(hours=1), cost=2.0)
    assert len(budget.ledger(registry.entries())) == 1
    meta(a, 2, NOON - timedelta(minutes=5), cost=3.0)
    got = budget.ledger(registry.entries())
    assert [r.cost for r in got] == [2.0, 3.0]
    assert make(bcfg(), NOON, registry.entries()).windows[0].spent == 5.0


# --- gates by class -------------------------------------------------------------------

def _spent(home, a, cost):
    for d in os.listdir(a.steps_dir) if os.path.isdir(a.steps_dir) else ():
        import shutil
        shutil.rmtree(os.path.join(a.steps_dir, d))
    meta(a, 1, NOON - timedelta(hours=1), cost=cost)
    budget._CACHE.clear()        # rewritten in place within one clock tick


def _open(home, cost, now=NOON, **kw):
    """Which classes may start an ``aaa`` step (estimate: default_step, $0.01)
    when ``spend`` has spent ``cost`` today."""
    from work_packet import registry
    for name in ("aaa", "spend"):
        if registry.get(name) is None:
            new(name)
    e = registry.get("spend")
    sp = Packet(os.path.join(e["path"], "packets", e["root"]))
    _spent(home, sp, cost)
    a = registry.get("aaa")["root"]
    b = make(bcfg(**kw), now, registry.entries(), h=home)
    return {c: b.gate(item("aaa", a, c)) is None
            for c in ("urgent", "high", "normal", "low", "background")}


def test_gates_close_in_order_and_reopen(home):
    # noon, $100 a day: pace 50, slack 10 -> background 40, low 50, normal 60, high 95
    assert _open(home, 30) == dict(urgent=True, high=True, normal=True, low=True, background=True)
    assert _open(home, 45)["background"] is False and _open(home, 45)["low"] is True
    got = _open(home, 55)
    assert (got["low"], got["normal"]) == (False, True)
    got = _open(home, 65)
    assert (got["normal"], got["high"]) == (False, True)
    got = _open(home, 96)
    assert (got["high"], got["urgent"]) == (False, True)
    assert _open(home, 100)["urgent"] is False
    # the next day the period starts again: yesterday's $100 no longer counts
    nxt = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
    got = _open(home, 100, now=nxt)
    assert got["high"] and got["normal"] and got["low"]
    gs = [e["cls"] for e in events.read(home) if e["type"] == "gate"]
    assert gs == ["background", "low", "normal", "high", "urgent"]    # once each


def test_urgent_may_spend_to_the_hard_cap(home):
    assert _open(home, 100, hard_cap=120.0)["urgent"] is True
    assert _open(home, 119.999, hard_cap=120.0)["urgent"] is False     # + its estimate


def test_gate_reason_and_clears_at(home):
    from work_packet import registry
    _, a = new("aaa")
    _, sp = new("spend")
    _spent(home, sp, 55)
    b = make(bcfg(), NOON, registry.entries())
    r = b.gate(item("aaa", a.wpid, "low"))
    assert r.code == "budget" and "low waits until pace reaches $55.01" in r.text
    # pace reaches 55.01 at 55.01% of the day: 13:12:08
    assert r.clears_at == "2026-10-21T13:12:08Z"
    r = b.gate(item("aaa", a.wpid, "background"))
    assert r.clears_at == "2026-10-21T15:36:08Z"                       # pace 65.01


# --- estimates and reservations -------------------------------------------------------

def test_estimates_from_history_and_fallback(home):
    from work_packet import registry
    _, a = new("aaa")
    _, b = new("bbb")
    for n, c in enumerate([0.1, 0.2, 0.3, 0.4, 0.5], 1):
        meta(a, n, NOON - timedelta(hours=10 - n), cost=c)
    bud = make(bcfg(), NOON, registry.entries())
    assert abs(bud.estimate(item("aaa", a.wpid)) - 0.4) < 1e-9          # p75 of the packet
    child = "%s-0000-4000-8000-000000000000" % a.wpid[:8]
    assert abs(bud.estimate(item("aaa", child)) - 0.4) < 1e-9           # the project's
    assert bud.estimate(item("bbb", b.wpid)) == 0.01                    # default_step
    bud = make(bcfg(default_step=0.0), NOON, registry.entries())
    assert bud.estimate(item("bbb", b.wpid)) == 0.50                    # built-in default


def test_estimate_capped_at_step_budget(home):
    from work_packet import registry
    _, a = new("aaa", step_budget_usd=0.25)
    for n in range(1, 4):
        meta(a, n, NOON - timedelta(hours=n), cost=2.0)
    bud = make(bcfg(), NOON, registry.entries())
    assert bud.estimate(item("aaa", a.wpid)) == 0.25


def test_reservations_rebuilt_from_job_records(home):
    from work_packet import registry
    _, a = new("aaa")
    meta(a, 1, NOON - timedelta(hours=1), cost=1.0)
    recs = [jobs.JobRecord(id="j%d" % i, backend="local", kind="step", project="aaa",
                           wpid=a.wpid, path=a.path, by="wpkd") for i in range(3)]
    bud = make(bcfg(), NOON, registry.entries(), recs)
    assert bud.windows[0].reserved == 3.0
    # an IDE job reserves nothing
    recs.append(jobs.JobRecord(id="ide", backend="local", kind="ide", project="aaa",
                               wpid=a.wpid, path=a.path, by="wpkd"))
    assert make(bcfg(), NOON, registry.entries(), recs).windows[0].reserved == 3.0


def test_plan_reserves_as_it_starts(home):
    """Three steps fit under the normal ceiling one at a time, not all at once."""
    from work_packet import registry
    _, a = new("aaa", step_budget_usd=50)
    meta(a, 1, NOON - timedelta(hours=1), cost=19.0)        # p75 of one step: 19
    cfg = bcfg(amount=100.0, slack=0.0)                    # normal: pace 50
    es = registry.entries()
    projs = queue.projects(es, cfg)
    ctx = gates.Ctx(cfg=cfg, now=NOON, mode={"mode": "run"}, limits=Limits(), usage=gates.Usage(),
                    projs=projs, budget=make(cfg, NOON, es, projs=projs))
    items = [item("aaa", a.wpid)] + [item("aaa", "%s-0000-4000-8000-00000000000%d"
                                          % (a.wpid[:8], i)) for i in range(3)]
    start, why = gates.plan(items, ctx, queue.order)
    assert len(start) == 1                                  # 19 + 19 + 19 > 50
    assert all(r.code == "budget" for r in why.values())


# --- quota -------------------------------------------------------------------------------

def _quota(seven, five, end, resets7, resets5):
    return {"seven_day": {"first": seven[0], "last": seven[1], "resets_at": resets7},
            "five_hour": {"first": five[0], "last": five[1], "resets_at": resets5}}


def test_five_hour_gate_blocks_while_week_is_open(home):
    from work_packet import registry
    _, a = new("aaa")
    t7 = int((NOON + timedelta(days=3, hours=12)).timestamp())    # week half gone
    t5 = int((NOON + timedelta(hours=1)).timestamp())             # 4 of 5 hours gone
    meta(a, 1, NOON - timedelta(minutes=10), quota=_quota((0.10, 0.12), (0.50, 0.58), NOON,
                                                          t7, t5))
    cfg = bcfg(measure="quota", amount=0.6, slack=0.06, period="week")
    bud = make(cfg, NOON, registry.entries())
    week, five = bud.windows
    assert (week.name, five.name) == ("seven_day", "five_hour")
    assert week.spent == 0.12 and five.spent == 0.58
    assert bud.gate(item("aaa", a.wpid, "normal")) is not None   # 5h: pace .48 + .06
    r = bud.gate(item("aaa", a.wpid, "normal"))
    assert "five-hour window" in r.text
    w = bud.windows[0]                                        # the week alone is open
    assert w.spent + w.reserved + bud.estimate(item("aaa", a.wpid)) <= bud.ceiling("normal", w)
    assert bud.gate(item("aaa", a.wpid, "high")) is not None  # .58 + est > .57 (95%)
    cfg = bcfg(measure="quota", amount=0.9, slack=0.06, period="week")
    assert make(cfg, NOON, registry.entries()).gate(item("aaa", a.wpid, "high")) is None


def test_quota_window_reset_means_nothing_used(home):
    from work_packet import registry
    _, a = new("aaa")
    past = int((NOON - timedelta(hours=1)).timestamp())
    meta(a, 1, NOON - timedelta(hours=2), quota=_quota((0.5, 0.9), (0.5, 0.9), NOON, past, past))
    bud = make(bcfg(measure="quota", amount=0.6), NOON, registry.entries())
    assert [w.spent for w in bud.windows] == [0.0, 0.0]
    assert bud.windows[0].start == NOON - timedelta(hours=1)     # the new window began
    assert bud.gate(item("aaa", a.wpid, "low")) is not None       # pace is near 0 so far
    assert bud.gate(item("aaa", a.wpid, "high")) is None


def test_stale_quota_reading(home):
    from work_packet import registry
    _, a = new("aaa")
    later = int((NOON + timedelta(days=2)).timestamp())
    meta(a, 1, NOON - timedelta(hours=7), quota=_quota((0.1, 0.1), (0.1, 0.1), NOON, later,
                                                       later))
    cfg = bcfg(measure="quota", amount=0.6)
    running = [jobs.JobRecord(id="j", backend="local", kind="step", project="aaa", wpid=a.wpid,
                              path=a.path, by="wpkd")]
    bud = make(cfg, NOON, registry.entries(), running)
    assert bud.windows[0].stale == "the reading is 7h old"
    r = bud.gate(item("aaa", a.wpid, "normal"))
    assert r is not None and "7h old" in r.text
    assert bud.gate(item("aaa", a.wpid, "high")) is None
    assert bud.gate(item("aaa", a.wpid, "urgent")) is None
    # with nothing running, one step may go to read it again
    bud = make(cfg, NOON, registry.entries())
    assert bud.gate(item("aaa", a.wpid, "normal")) is None
    assert bud.gate(item("aaa", a.wpid, "background")) is not None


# --- project caps and the dispatcher -----------------------------------------------------

def test_project_over_daily_cap_is_held(home, fakelocal):
    from work_packet import clock
    now = clock.now()
    _, a = new("aaa", budget_usd_per_day=1.0)
    _, b = new("bbb", budget_usd_per_day=1.0)
    meta(a, 1, now - timedelta(minutes=30), cost=1.5)
    d = Dispatcher(backend=fakelocal)
    _, subs = d.pass_once()
    assert [s.project for s in subs] == ["bbb"]
    m = a.load_status()[0]
    assert m["state"] == "PAUSED" and m["reason"] == \
        "limit: budget_usd_per_day $1.00 reached ($1.50 today)"
    cap = [e for e in events.read(home) if e["type"] == "cap"]
    assert len(cap) == 1 and cap[0]["project"] == "aaa"


def test_max_steps_per_hour(home, fakelocal):
    from work_packet import clock
    now = clock.now()
    _, a = new("aaa", max_steps_per_hour=2)
    meta(a, 1, now - timedelta(minutes=50), cost=0.1)
    meta(a, 2, now - timedelta(minutes=10), cost=0.1)
    Dispatcher(backend=fakelocal).pass_once()
    assert "max_steps_per_hour 2 reached" in a.load_status()[0]["reason"]


def test_budget_stops_real_steps(home, fake, monkeypatch):
    """End to end: each step costs $0.30 of a $1.00 day; normal work stops at pace
    plus slack, with the reason on the queue."""
    monkeypatch.setenv("WPK_FAKE_COST", "0.30")
    write_config(home, {"sched": {"budget": {"measure": "usd", "amount": 1.0, "period": "day",
                                             "tz": "UTC", "slack": 0.1}}})
    _, a = new("aaa")
    d = Dispatcher()
    for _ in range(10):
        d.pass_once()
        while jobs.all(home):
            d.reap()
    # 18:00: pace .75, normal ceiling .85; steps are $0.30 (estimate p75 of history)
    spent = sum(r.cost for r in budget.ledger([{"name": "aaa", "path": a.path.rsplit(
        "/packets/", 1)[0]}]))
    assert abs(spent - 0.60) < 1e-9
    from work_packet.sched import explain
    snap = explain.snapshot(home)
    assert snap["queue"][0]["waiting"] == "budget"
    assert snap["budget"]["windows"][0]["spent"] == pytest.approx(0.6)
    assert os.path.exists(os.path.join(sconfig.sched_dir(home), "spend.json"))
    text = "\n".join(explain.lines(snap))
    assert "budget: usd: spent $0.60 of $1.00, pace $0.75" in text
    assert "normal     ceiling $0.85, room $0.25" in text
    assert "background ceiling $0.65, room $0.05" in text
    assert "budget: normal waits until pace reaches" in text
