"""The daily focus brief and the end of the day (docs/collaboration.md §9.4, §9.5):
built from the board's own data, no model call, kept per day."""

import time
from datetime import datetime

import pytest

from test_dash_tasks import _client, _flash, _new
from work_packet import brief, checkpoint, cli, executor, planning, registry, scheduler


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _home():
    return registry.home()


def test_focus_is_scored_and_explained(fake, monkeypatch):
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "asker")
    ea, pa = _new("asking")
    scheduler.tick([ea], until_idle=True)               # a question for you
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "add_one")
    eb, pb = _new("later-one")
    executor.admin(pb, "pause")
    planning.set_(eb, {"priority": "later"})
    ec, pc = _new("hot")
    executor.admin(pc, "pause")
    today = datetime.now().date().isoformat()
    planning.set_(ec, {"priority": "now", "due": today, "due_kind": "hard"})
    b = brief.build(_home())
    order = [f["project"] for f in b["focus"]]
    assert order[0] == "hot" and order.index("asking") < order.index("later-one")
    hot = b["focus"][0]
    assert "now" in hot["why"] and "due today" in hot["why"]
    assert "answering it lets the runner go on" in b["focus"][1]["why"]
    assert b["needs"].get("question") == 1
    md = open(brief.path(_home(), b["day"], "md")).read()
    assert "## Suggested focus" in md and "1. **hot**" in md
    assert brief.days(_home()) == [b["day"]]


def test_not_today_and_repeats(fake):
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    h = _home()
    day = datetime.now().date().isoformat()
    brief.say(h, day, "a", "not today")
    assert "a" not in [f["project"] for f in brief.build(h)["focus"]]
    # suggested on the two briefs before, untouched since: ask instead of suggesting
    import json
    for d in ("2026-01-01", "2026-01-02"):
        json.dump({"day": d, "t": time.time() - 3600, "focus": [{"project": "b"}]},
                  open(brief.path(h, d), "w"))
    e2, p2 = _new("b")
    executor.admin(p2, "pause")
    b = brief.build(h)
    assert "b" not in [f["project"] for f in b["focus"]]
    assert any(x["project"] == "b" and "still" in x["text"] for x in b["housekeeping"])


def test_due_and_the_board_loop(tmp_path):
    h = str(tmp_path)
    monday_9 = datetime(2026, 11, 9, 9, 0).timestamp()
    monday_8 = datetime(2026, 11, 9, 8, 0).timestamp()
    saturday = datetime(2026, 11, 7, 9, 0).timestamp()
    assert brief.due(h, {}, monday_9) and not brief.due(h, {}, monday_8)
    assert not brief.due(h, {}, saturday) and brief.due(h, {"weekends": True}, saturday)
    assert not brief.due(h, {"off": True}, monday_9)
    assert brief.due(h, {"time": "07:15"}, monday_8)


def test_cli_brief_and_shutdown(fake, capsys):
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    checkpoint.record(pkt, "half done", next_action="write the tests")
    assert cli.main(["brief"]) == 0
    assert "Focus" in capsys.readouterr().out
    assert cli.main(["shutdown"]) == 0
    out = capsys.readouterr().out
    assert "a: write the tests" in out                  # ready for the night shift


def test_desk_brief_and_shutdown_pages(fake):
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    checkpoint.record(pkt, "half done", next_action="write the tests")
    c = _client()
    assert "No brief for" in c.get("/brief").text
    r = c.post("/brief/build", data={"back": "/"}, follow_redirects=False)
    assert _flash(r)[1]
    page = c.get("/").text
    assert "<strong>Today</strong>" in page and "not today" in page
    r = c.post("/brief/feedback", data={"project": "a", "kind": "not today", "back": "/"},
               follow_redirects=False)
    assert _flash(r)[1]
    assert "Suggested focus" in c.get("/brief").text
    page = c.get("/shutdown").text
    assert "Load the night shift" in page and 'value="a" checked' in page
    r = c.post("/shutdown/handoff", data={"project": ["a"]}, follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    rec = pkt.journal().records[-1]
    assert rec["type"] == "handoff" and rec["defer"] is True


def test_a_session_hears_todays_focus(fake):
    from work_packet import briefing
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    brief.build(_home())
    text = briefing.briefing(e["path"], pkt.wpid)
    assert "Today's focus on the board: a" in text


def test_config():
    from work_packet import schema
    bad = [p.field for p in schema.validate_config({"focus": {"time": "8", "off": "yes"}})
           if p.level == "error"]
    assert bad == ["focus.time", "focus.off"]
    assert schema.validate_config({"focus": {"time": "07:45", "weekends": True}}) == []
