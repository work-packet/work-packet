"""A budget provider (design E6): amount, period and spend from a plugin's reading,
plus the local spend since its as_of; the route filter; blocked and stale readings."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from work_packet import schema
from work_packet.sched import budget, queue
from work_packet.sched import config as sconfig
from work_packet.sched.config import Size

from test_sched_budget import NOON, new  # noqa: F401  (fixtures: home, fake)
from test_sched_budget import home  # noqa: F401

UTC = timezone.utc
DAY = (datetime(2026, 10, 21, tzinfo=UTC), datetime(2026, 10, 22, tzinfo=UTC))


def reading(**kw):
    d = dict(amount=100.0, spent=20.0, period_start=DAY[0], period_end=DAY[1], tz="UTC",
             as_of=NOON - timedelta(hours=3))
    d.update(kw)
    return budget.BudgetReading(**d)


class Portal(budget.BudgetProvider):
    def __init__(self):
        self.r, self.raise_ = reading(), None

    def read(self):
        if self.raise_:
            raise self.raise_
        return self.r


@pytest.fixture
def portal(monkeypatch):
    from work_packet import plugins
    p = Portal()
    monkeypatch.setattr(plugins, "loaded", lambda g: {"portal": p} if g == budget.GROUP else {})
    return p


def step(pkt, n, start, cost, account="me", host="api.example.com"):
    d = os.path.join(pkt.steps_dir, "%04d" % n)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w") as fp:
        json.dump({"step": n, "start": schema.format_timestamp(start),
                   "end": schema.format_timestamp(start + timedelta(minutes=5)),
                   "cost_usd": cost, "route": {"account": account, "host": host}}, fp)


def pcfg(**kw):
    b = {"measure": "provider", "provider": "portal", "period": "day", "tz": "UTC",
         "default_step": 0.01}
    b.update(kw)
    return sconfig.load(raw={"sched": {"budget": b}})


def item(project_, wpid, cls="normal"):
    return queue.Item(project_, wpid, "/x", "RUNNABLE", "2026-10-21T11:00:00Z", cls, "project",
                      cls, Size("look", 1), "default")


def make(cfg, h, now=NOON):
    from work_packet import registry
    es = registry.entries()
    return budget.Budget(cfg, now, es, [], queue.projects(es, cfg), None, h)


def test_reading_round_trip(home, portal):
    portal.r = reading(stage="80%", notes=["over plan"], url="https://portal/x")
    d = budget.refresh(home, "portal", NOON)
    assert d["error"] is None and d["read_at"] == "2026-10-21T12:00:00Z"
    got = budget.load_reading(home)
    assert got["reading"] == portal.r and got["provider"] == "portal"


def test_spent_is_reading_plus_local_since_as_of(home, portal):
    _, a = new("aaa")
    step(a, 1, NOON - timedelta(hours=4), 5.0)            # before as_of: in the reading
    step(a, 2, NOON - timedelta(hours=1), 3.0)            # after: only wpk knows it
    step(a, 3, NOON - timedelta(minutes=30), 2.0, account="other")
    portal.r = reading(spent=37.0)
    budget.refresh(home, "portal", NOON)
    b = make(pcfg(), home)
    w = b.windows[0]
    assert (w.start, w.end, w.stale) == (DAY[0], DAY[1], None)
    assert b.amount == 100.0 and b.measure == "usd" and w.spent == 42.0
    b = make(pcfg(route="me@*"), home)
    assert b.windows[0].spent == 40.0
    d = b.describe()
    assert d["measure"] == "usd" and d["provider"]["name"] == "portal"
    assert d["provider"]["reading"]["spent"] == 37.0
    # pace at noon 50, slack 10, estimate $1 (step budget): low (50) opens, background (40) not
    assert b.gate(item("aaa", a.wpid, "low")) is None
    assert b.gate(item("aaa", a.wpid, "background")).code == "budget"


def test_blocked_holds_every_class(home, portal):
    _, a = new("aaa")
    portal.r = reading(blocked=True, stage="100%")
    budget.refresh(home, "portal", NOON)
    r = make(pcfg(), home).gate(item("aaa", a.wpid, "urgent"))
    assert r.code == "budget" and "portal says new calls are refused (100%)" in r.text


def test_needs_login_keeps_reading_but_is_stale(home, portal):
    _, a = new("aaa")
    budget.refresh(home, "portal", NOON)
    portal.raise_ = budget.NeedsLogin("token expired")
    d = budget.refresh(home, "portal", NOON + timedelta(minutes=5))
    assert d["needs_login"] and d["error"] == "token expired" and d["reading"] == portal.r
    b = make(pcfg(), home)
    assert b.windows[0].stale == "token expired" and b.amount == 100.0
    assert "waits for a fresh reading" in b.gate(item("aaa", a.wpid, "normal")).text
    assert b.gate(item("aaa", a.wpid, "high")) is None
    assert make(pcfg(), home).describe()["provider"]["needs_login"] is True


def test_old_reading_is_stale(home, portal):
    budget.refresh(home, "portal", NOON - timedelta(hours=7))
    assert make(pcfg(), home).windows[0].stale == "the reading is 7h old"


def test_no_reading_lets_high_through(home, portal):
    _, a = new("aaa")
    b = make(pcfg(), home)
    assert "no reading yet" in b.windows[0].stale
    assert b.gate(item("aaa", a.wpid, "high")) is None
    assert b.gate(item("aaa", a.wpid, "normal")).code == "budget"


def test_provider_failure_is_recorded(home, portal):
    portal.raise_ = RuntimeError("portal 503")
    d = budget.refresh(home, "portal", NOON)
    assert d["error"] == "portal 503" and d["reading"] is None
    d = budget.refresh(home, "missing", NOON)
    assert "not loaded" in d["error"]


def test_schema(home):
    from work_packet.schema import _validate_budget
    assert _validate_budget({"measure": "provider", "provider": "portal", "route": "a@*"}) == []
    errs = _validate_budget({"measure": "provider"})
    assert [e.split(":")[0] for e in map(str, errs)] and "needs provider" in str(errs)
    assert "provider" in str(_validate_budget({"measure": "nope"}))


def test_gate_for_needs_a_provider_name(home):
    class Ctx:
        cfg, limits, projs, now = pcfg(provider=""), None, {}, NOON
    assert budget.gate_for(Ctx, [], home, entries=[]) is None
    Ctx.cfg = pcfg()
    assert budget.gate_for(Ctx, [], home, entries=[]) is not None



# --- wpkd's cadence (Poller) -----------------------------------------------------------

class Counting(Portal):
    def __init__(self):
        super().__init__()
        self.reads, self.checks, self.says = 0, 0, False

    def changed(self):
        self.checks += 1
        return self.says

    def read(self):
        self.reads += 1
        return super().read()


def test_poller_cadence(home, monkeypatch):
    from work_packet import plugins
    p = Counting()
    monkeypatch.setattr(plugins, "loaded", lambda g: {"portal": p} if g == budget.GROUP else {})
    cfg, t = pcfg(), NOON
    assert budget.Poller(home).poll(pcfg(measure="usd", amount=1.0), t) is False
    pl = budget.Poller(home)
    assert pl.poll(cfg, t) is True and p.reads == 1           # first: read at once
    assert pl.poll(cfg, t + timedelta(minutes=1)) is False and p.checks == 0
    assert pl.poll(cfg, t + timedelta(minutes=6)) is False and p.checks == 1
    p.says = True
    assert pl.poll(cfg, t + timedelta(minutes=12)) is True and p.reads == 2
    p.says = False
    # a restarted wpkd reads the cache's tried_at: no read at once
    assert budget.Poller(home).poll(cfg, t + timedelta(minutes=13)) is False
    assert pl.poll(cfg, t + timedelta(minutes=73)) is True and p.reads == 3   # hourly
    # after an error, retry at the changed() cadence without asking changed()
    p.raise_ = budget.Unavailable("down")
    assert pl.poll(cfg, t + timedelta(minutes=140)) is True
    n = p.checks
    assert pl.poll(cfg, t + timedelta(minutes=146)) is True and p.checks == n
    assert budget.load_reading(home)["error"] == "down"


def test_wpkd_reads_the_provider(home, monkeypatch):
    import threading
    from work_packet.sched.dispatcher import Dispatcher
    from work_packet import plugins
    p = Counting()
    monkeypatch.setattr(plugins, "loaded", lambda g: {"portal": p} if g == budget.GROUP else {})
    d = Dispatcher(home, cfg=pcfg())
    stop, poke = threading.Event(), threading.Event()
    monkeypatch.setattr(d, "fill", lambda *a, **k: stop.set())
    d.run(stop, poke, max_wait=0.1)
    assert p.reads == 1 and budget.load_reading(home)["provider"] == "portal"
