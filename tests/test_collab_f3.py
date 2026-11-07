"""Deadlines and reporting (docs/collaboration.md §9.3, §9.5, §9.6; plan F3):
your time, estimates against actuals, the forecast and at risk, dates from
forges, board milestones, the weekly review, standup and status, calendar fit."""

import json
import os
import time
from datetime import date, datetime, timedelta

import pytest

from test_dash_tasks import _client, _flash, _new
from work_packet import (brief, executor, forecast, forges, icsfeed, inbox, journal,
                         layout, milestones, notify, planning, presence, registry, reviews,
                         schema, timelog, watch)
from work_packet.dash import data


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _parked(name="dv"):
    e, pkt = _new(name)
    executor.admin(pkt, "pause")
    return e, pkt


def _epoch(y, m, d, hh=12):
    return datetime(y, m, d, hh).timestamp()


def _ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _tasks(pkt, n=3, hours=48, start=None):
    """``n`` finished tasks of ``hours`` each in the packet's journal."""
    t = start or _epoch(2026, 9, 1)
    for i in range(n):
        journal.append(pkt.journal_path, {"type": "handoff", "t": _ts(t), "by": "me",
                                          "from": "PAUSED", "to": "RUNNABLE",
                                          "instruction": "task %d" % i, "batch": i + 1})
        journal.append(pkt.journal_path, {"type": "commit-begin", "t": _ts(t + hours * 3600),
                                          "step": i + 1, "decision": {"state": "COMPLETED"}})
        t += (hours + 1) * 3600


def _outline(pkt, done=2, total=4):
    os.makedirs(os.path.join(pkt.path, "state"), exist_ok=True)
    with open(os.path.join(pkt.path, "state", "outline.md"), "w") as fp:
        fp.write("# Plan\n\n" + "".join("- [%s] %d step\n" % ("x" if i < done else " ", i)
                                        for i in range(total)))


def _config(text):
    p = os.path.join(registry.home(), "config.toml")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as fp:
        fp.write(text)


# --- F3a: your time, estimates against actuals --------------------------------------

def test_the_ledger_counts_a_person_once(fake):
    e, _ = _parked()
    p, t = e["path"], _epoch(2026, 10, 21, 10)
    presence.beat(p, "claude-a", t, kind="claude", by="me", turn="working")
    presence.beat(p, "ide-web-x", t + 60, kind="ide-web", by="me", visible=True)
    presence.beat(p, "claude-a", t + 120, kind="claude", by="me", turn="working")
    assert timelog.spent(p) == {"me": 120.0}            # two sources, counted once
    presence.beat(p, "claude-a", t + 1000, kind="claude", by="me")   # after a gap: nothing
    presence.beat(p, "ide-web-x", t + 1100, kind="ide-web", by="me", visible=False)
    presence.beat(p, "claude-a", t + 1150, kind="claude", by="me", idle_since=t + 1150)
    presence.end(p, "claude-a", t + 1200)
    assert timelog.spent(p) == {"me": 120.0}
    presence.beat(p, "claude-a", t + 1260, kind="claude", by="me", turn="working")
    assert timelog.spent(p)["me"] == 120.0              # after an end: starts afresh
    presence.beat(p, "claude-a", t + 1320, kind="claude", by="me", turn="working")
    assert timelog.spent(p)["me"] == 180.0
    assert timelog.days(p) == ["2026-10-21"] and timelog.hours(5400) == "1.5h"


def test_estimates_against_actuals(fake):
    e, _ = _parked()
    assert planning.estimate_hours("2d") == 16 and planning.estimate_hours("1w") == 40
    assert planning.estimate_hours("x") is None
    assert planning.working_days(date(2026, 10, 16), date(2026, 10, 20)) == 3   # Fri-Tue
    for d in (19, 20):
        timelog.add(e["path"], "me", _epoch(2026, 10, d, 10))
        timelog.add(e["path"], "me", _epoch(2026, 10, d, 10) + 240)
    planning.set_(e, {"estimate": "1d"})
    a = planning.actuals(e, _epoch(2026, 10, 21))
    assert a["days"] == 3 and a["over"] and a["you"] == 480
    assert planning.actuals_text(a) == "so far 3 working days: you 8m"
    page = _client().get("/p/dv/%s" % e["root"]).text
    assert 'id="actuals"' in page and "estimate 1d" in page
    lines = brief._estimates(registry.home(), [{"name": "dv", "plan": planning.get(e)}],
                             _epoch(2026, 10, 21))
    assert lines and "you estimated 1d" in lines[0]["text"]


# --- F3b: forecast and at risk -------------------------------------------------------

def test_a_forecast_from_history(fake):
    e, pkt = _parked()
    assert forecast.forecast(e, data.card(e)) is None   # nothing known to be left
    _tasks(pkt, n=3, hours=10)
    _outline(pkt, done=2, total=4)
    fc = forecast.forecast(e, data.card(e), now=1000.0)
    assert fc["why"][0].startswith("2 of 4 plan items for the runner")
    assert fc["low"] == 1000 + 5 * 3600 and fc["high"] == 1000 + 5 * 3600   # all 10h: no spread
    assert forecast.spread([1, 2]) == (1.125, 2.25)
    assert forecast.spread([1, 2, 3, 4, 5]) == (2, 4)


def test_at_risk_reasons(fake):
    today = date(2026, 10, 21)
    now = _epoch(2026, 10, 21)
    fc = {"low": now, "high": _epoch(2026, 10, 26), "why": []}
    assert forecast.at_risk("2026-10-23", None, fc, {}, today, now).startswith("forecast")
    assert forecast.at_risk("2026-10-30", None, fc, {}, today, now) is None
    upd = datetime.fromtimestamp(now - 3 * 86400).astimezone()
    mine = {"ball": {"who": "you"}, "root": {"updated": upd}}
    assert forecast.at_risk("2026-10-22", None, None, mine, today, now) == "yours for 3 days"
    blk = {"plan": {"blocked_by": ["dma-bug", "spi"]}}
    assert forecast.at_risk("2026-10-25", None, None, blk, today, now, done={"spi"}) == \
        "blocked by dma-bug"
    assert forecast.at_risk("2026-10-20", None, fc, blk, today, now) is None   # overdue


def test_at_risk_on_the_board_the_desk_and_the_brief(fake):
    e, pkt = _parked()
    _tasks(pkt, n=3, hours=48)
    _outline(pkt, done=0, total=4)
    planning.set_(e, {"due": "2026-10-21", "due_kind": "hard"})   # WPK_NOW's day
    cols, _ = data.board()
    [c] = [c for v in cols.values() for c in v]
    assert c["due_eff"] == "2026-10-21" and c["forecast"] and c["at_risk"].startswith("forecast")
    page = _client().get("/").text
    assert "AT RISK" in page and "Hand it off now" in page and "at risk: forecast" in page
    [it] = [i for i in notify.items(cols) if i["type"] == "decision"]
    assert it["project"] == "dv" and "at risk: forecast" in it["text"]
    pts, why = brief.score(c, date(2026, 10, 21), _epoch(2026, 10, 21))
    assert any(w.startswith("at risk") for w in why)
    assert "at risk" in _client().get("/b/main").text


# --- F3c: dates from forges ----------------------------------------------------------

def test_an_issue_milestone_becomes_a_proposed_date(fake):
    i = forges._brief({"number": 7, "title": "t", "html_url": "u", "state": "open",
                       "milestone": {"title": "v1.2", "due_on": "2026-12-01T08:00:00Z"}})
    assert i["milestone"] == {"title": "v1.2", "due": "2026-12-01"}
    assert forges._brief({"number": 7, "title": "t", "html_url": "u",
                          "state": "open"})["milestone"] is None
    e, _ = _parked()
    s = watch.load_state({"board": "main", "name": "w"})
    iid = watch.propose_date("dv", i, "gh:o/r#7", s)
    assert iid and watch.propose_date("dv", i, "gh:o/r#7", s) is None      # once
    d = inbox.get(registry.home(), iid)
    assert d["source"] == "date" and d["ref"]["date"] == "2026-12-01"
    c = _client()
    assert "Use this date" in c.get("/backlog").text
    r = c.post("/inbox/%s/accept" % iid, follow_redirects=False)
    msg, ok = _flash(r)
    assert ok, msg
    p = planning.get(e)
    assert p["due"] == "2026-12-01" and p["due_kind"] == "soft"
    assert inbox.get(registry.home(), iid) is None


# --- F3d: milestones -----------------------------------------------------------------

def test_milestones_and_the_burn_down(fake):
    e, pkt = _parked()
    _outline(pkt, done=1, total=3)
    c = _client()
    r = c.post("/b/main/milestones", data={"op": "add", "name": "rtl-freeze",
                                           "date": "2026-11-20", "title": "RTL freeze"},
               follow_redirects=False)
    assert _flash(r)[1]
    with pytest.raises(milestones.MilestoneError):
        milestones.add("main", "rtl-freeze", "2026-11-21")
    with pytest.raises(milestones.MilestoneError):
        milestones.add("main", "Bad Name", "2026-11-21")
    page = c.get("/b/main").text
    assert 'id="milestones"' in page and 'name="milestone"' in page and "rtl-freeze" in page
    planning.set_(e, {"milestone": "rtl-freeze"})
    with pytest.raises(planning.PlanError):
        planning.set_(e, {"milestone": "Not a name"})
    cols, _ = data.board()
    [card] = [x for v in cols.values() for x in v]
    assert card["due_eff"] == "2026-11-20" and card["due_kind"] == "soft"
    assert card["due"].startswith("rtl-freeze ")
    cards = [x for v in cols.values() for x in v]
    t = _epoch(2026, 10, 21)
    assert milestones.snap(cards, now=t) == 1 and milestones.snap(cards, now=t) == 0
    assert milestones.snap(cards, now=t + 86400) == 1
    rows = milestones.snaps("main", "rtl-freeze")
    assert rows[0]["runner"] == 2 and rows[0]["projects"] == 1
    assert milestones.chart(milestones.get("main", "rtl-freeze"), rows)["total"]
    page = c.get("/b/main").text
    assert "<svg class=\"burn\"" in page and "left: 2 for the runner" in page
    r = c.post("/b/main/milestones", data={"op": "remove", "name": "rtl-freeze"},
               follow_redirects=False)
    assert _flash(r)[1] and milestones.of_board("main") == []


# --- F3e: weekly review, standup, status ---------------------------------------------

def test_the_weekly_review(fake):
    e, pkt = _parked()
    other, opkt = _parked("old")
    executor.mark(pkt, "done")                          # at WPK_NOW, a Wednesday
    now = _epoch(2026, 10, 22)
    timelog.add(other["path"], "me", now - 100)
    timelog.add(other["path"], "me", now)
    r = reviews.weekly(now=now)
    assert [d["project"] for d in r["done"]] == ["dv"]
    assert os.path.exists(reviews.review_path(registry.home(), r["week"], "md"))
    md = reviews.render_weekly(r)
    assert "## Done" in md and "**dv**: done" in md and "**old**" in md
    c = _client()
    page = c.get("/review").text
    assert "Review" in page and "Keep a copy" in page and r["week"] in page
    assert c.get("/review/1999-W01").status_code == 404
    r2 = c.post("/review/tidy", data={"old": "someday"}, follow_redirects=False)
    assert _flash(r2)[1] and planning.get(other)["priority"] == "someday"
    r3 = c.post("/reports/keep", data={"kind": "review", "back": "/review"},
                follow_redirects=False)
    assert _flash(r3)[1] and reviews.kept()


def test_when_the_review_is_due(fake):
    h = registry.home()
    fri = _epoch(2026, 10, 23, 17)
    assert reviews.review_due(h, {}, fri)
    assert not reviews.review_due(h, {}, _epoch(2026, 10, 23, 15))
    assert not reviews.review_due(h, {"review": False}, fri)
    assert reviews.review_due(h, {"review_day": "thu", "review_time": "09:00"},
                              _epoch(2026, 10, 22, 10))
    _parked()
    assert "wrote this week's review" in reviews.tick(h, {}, fri)
    assert not reviews.review_due(h, {}, fri)


def test_standup_and_status(fake):
    e, pkt = _parked()
    planning.set_(e, {"blocked_by": "dma-bug"})
    now = _epoch(2026, 10, 21)
    y = reviews.last_working_day(date.fromtimestamp(now))
    timelog.add(e["path"], "me", _epoch(y.year, y.month, y.day, 10))
    timelog.add(e["path"], "me", _epoch(y.year, y.month, y.day, 10) + 200)
    s = reviews.standup(now=now)
    assert s["yesterday"][0]["project"] == "dv" and "worked on it" in s["yesterday"][0]["lines"][0]
    assert s["blocked"] == [{"project": "dv", "text": "waits on dma-bug"}]
    assert reviews.last_working_day(date(2026, 10, 19)) == date(2026, 10, 16)
    c = _client()
    assert "Yesterday" in c.get("/standup").text
    milestones.add("main", "m1", "2026-12-01")
    planning.set_(e, {"milestone": "m1"})
    page = c.get("/status/main/m1").text
    assert "Status: main · m1" in page and "| dv |" in page
    assert c.get("/status/nope").status_code == 404
    assert c.get("/status/main/nope").status_code == 404
    r = c.post("/reports/keep", data={"kind": "status", "name": "main-m1",
                                      "back": "/status/main/m1"}, follow_redirects=False)
    assert _flash(r)[1] and any(k.startswith("status-main-m1-") for k in reviews.kept())


# --- F3f: calendar fit -------------------------------------------------------------

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261021T100000Z
DTEND:20261021T110000Z
SUMMARY:Sync\\, weekly
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Berlin:20261021T150000
DURATION:PT30M
SUMMARY:Review
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261021
DTEND;VALUE=DATE:20261022
SUMMARY:All day
END:VEVENT
BEGIN:VEVENT
DTSTART:20261021T120000Z
DTEND:20261021T130000Z
STATUS:CANCELLED
SUMMARY:Gone
END:VEVENT
BEGIN:VEVENT
DTSTART:20261021T160000Z
DTEND:20261021T170000Z
TRANSP:TRANSPARENT
SUMMARY:Free
END:VEVENT
END:VCALENDAR
"""


def test_parse_an_ics_feed():
    evs = icsfeed.parse(ICS)
    assert [e["title"] for e in evs] == ["Sync, weekly", "Review"]
    assert evs[1]["start"].utcoffset() == timedelta(hours=2)            # Berlin, summer time
    assert (evs[1]["end"] - evs[1]["start"]) == timedelta(minutes=30)
    t = datetime(2026, 10, 21, 10, 30).replace(tzinfo=evs[0]["start"].tzinfo).timestamp()
    assert icsfeed.busy(evs, t)["title"] == "Sync, weekly"
    before = t - 3600 - 45 * 60                                        # 08:45Z
    f = icsfeed.fit(evs, before, items=5)
    assert f["minutes"] == 75 and f["fits"] == 5
    assert icsfeed.fit(evs, t, 1) is None


def test_meetings_in_the_brief_and_pushes_wait(fake, tmp_path):
    p = tmp_path / "cal.ics"
    p.write_text(ICS)
    _config('[calendar]\nics = "%s"\n' % p)
    h = registry.home()
    assert icsfeed.source(h) == str(p) and len(icsfeed.events(h)) == 2
    b = brief.build(h, now=_epoch(2026, 10, 21, 6))
    assert b["calendar"]["meetings"]
    assert "## Today's calendar" in brief.render(b) and "Sync, weekly" in brief.render(b)
    e, pkt = _parked()
    from work_packet import scheduler
    pkt2 = _new("q")[1]
    sent = []
    cols, _ = data.board()
    item = {"key": "k", "type": "question", "project": "q", "text": "which?", "since": 0,
            "url": "/p/q"}
    import work_packet.notify as nmod
    orig = nmod.items
    nmod.items = lambda cols, now=None: [item]
    try:
        cfg = {"ntfy_url": "http://x/t"}
        out = notify.tick(h, cols, cfg, now=1000, send=lambda *a, **k: sent.append(a),
                          busy={"title": "Sync"})
        assert out["held"] == ["k"] and not sent
        out = notify.tick(h, cols, cfg, now=1060, send=lambda *a, **k: sent.append(a))
        assert out["pushed"] == ["k"] and sent
    finally:
        nmod.items = orig


def test_config_keys():
    good = {"focus": {"review": False, "review_day": "thu", "review_time": "09:30"},
            "calendar": {"ics": "https://x/cal.ics"}}
    assert not [p for p in schema.validate_config(good) if p.level == "error"]
    bad = {"focus": {"review_day": "someday", "review_time": "9"}, "calendar": {"ics": 3}}
    fields = {p.field for p in schema.validate_config(bad) if p.level == "error"}
    assert {"focus.review_day", "focus.review_time", "calendar.ics"} <= fields
