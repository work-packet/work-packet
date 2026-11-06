"""Your planning fields, the Backlog and quick capture (docs/collaboration.md §9.2,
§9.6): in the card, never overwritten by the board, and followed by the runner's
scheduler when the project sets no class of its own."""

import os
from datetime import date

import pytest

from test_dash_tasks import _client, _flash, _new
from work_packet import card as cardmod, cli, inbox, livecard, planning, registry, scheduler
from work_packet.sched import classes


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def test_validate():
    assert planning.validate({"priority": "now", "due": "2026-11-14", "rank": "3",
                              "blocked_by": "a, b", "estimate": "2d"}) == {
        "priority": "now", "due": "2026-11-14", "rank": 3, "blocked_by": ["a", "b"],
        "estimate": "2d"}
    assert planning.validate({"due": ""}) == {"due": None}
    for bad in ({"priority": "urgent"}, {"due": "Friday"}, {"estimate": "soon"},
                {"rank": "x"}, {"colour": "red"}):
        with pytest.raises(planning.PlanError):
            planning.validate(bad)


def test_it_lives_in_the_card_and_survives_a_rebuild(fake):
    e, pkt = _new("a")
    planning.set_(e, {"priority": "later", "due": "2026-12-01", "area": "dv"}, by="me")
    livecard.update_project(registry.get("a"))         # the board rebuilds the card
    got = planning.get(e)
    assert got["priority"] == "later" and got["due"] == "2026-12-01" and got["area"] == "dv"
    meta = cardmod.load(planning.path_of(e)).meta
    assert meta["plan"]["priority"] == "later" and meta["name"]
    planning.set_(e, {"due": ""})
    assert planning.get(e)["due"] is None
    rec = pkt.journal().records[-1]
    assert rec["type"] == "admin" and rec["op"] == "plan" and rec["changes"] == {"due": None}


def test_now_has_a_limit(fake):
    es = [_new(n)[0] for n in ("a", "b", "c", "d")]
    for e in es[:3]:
        planning.set_(e, {"priority": "now"}, entries=registry.entries())
    with pytest.raises(planning.PlanError, match="already in now"):
        planning.set_(es[3], {"priority": "now"}, entries=registry.entries())
    planning.set_(es[3], {"priority": "now"}, entries=registry.entries(), force=True)
    assert planning.get(es[3])["priority"] == "now"


def test_the_runner_follows_your_priority():
    assert planning.sched_class({"priority": "now"}) == "high"
    assert planning.sched_class({"priority": "someday"}) == "low"
    today = date(2026, 11, 6)
    assert planning.sched_class({"priority": "next", "due": "2026-11-07"}, today) == "high"
    assert planning.sched_class({"priority": "later", "due": "2026-11-07"}, today) == "normal"
    assert planning.sched_class({"priority": "next", "due": "2026-12-07"}, today) == "normal"


def test_scheduler_class_from_the_plan(fake):
    e, pkt = _new("a")
    assert classes.effective(e, pkt.wpid) == ("normal", "default")
    planning.set_(e, {"priority": "now"})
    assert classes.effective(registry.get("a"), pkt.wpid) == ("high", "plan")


def test_texts_and_rot():
    today = date(2026, 11, 6)                          # a Friday
    assert planning.due_text({"due": "2026-11-06"}, today) == "due today"
    assert planning.due_text({"due": "2026-11-09"}, today) == "due Mon"
    assert planning.due_text({"due": "2026-11-04"}, today) == "overdue 2 days"
    assert planning.due_text({"due": "2026-12-06"}, today) == "due in 30 days"
    assert planning.rotting({"priority": "now"}, 1000, 1000 + 4 * 86400)["days"] == 4
    assert planning.rotting({"priority": "next"}, 1000, 1000 + 4 * 86400) is None


def test_cli(fake, capsys):
    e, pkt = _new("a")
    assert cli.main(["plan", "a", "--priority", "now", "--due", "2026-11-20",
                     "--due-kind", "hard"]) == 0
    assert planning.get(e)["due_kind"] == "hard"
    capsys.readouterr()
    assert cli.main(["plan", "a"]) == 0
    assert "priority:  now" in capsys.readouterr().out
    assert cli.main(["plan", "a", "--due", "someday"]) != 0
    assert cli.main(["todo", "look", "at", "the", "flaky", "seed"]) == 0
    assert [d["text"] for d in inbox.items(registry.home())] == ["look at the flaky seed"]


def test_board_backlog_and_capture(fake):
    e, pkt = _new("a")
    c = _client()
    r = c.post("/p/a/plan", data={"priority": "now", "due": "2026-11-20", "back": "/backlog"},
               follow_redirects=False)
    assert _flash(r)[1] and r.headers["location"].startswith("/backlog")
    page = c.get("/backlog").text
    now = page.split('id="now"')[1].split('id="next"')[0]
    assert ">a</strong>" in now
    board = c.get("/b/main").text
    assert 'class="prio prio-now"' in board and "Plan ▾" in board
    assert "Focus:" in c.get("/").text
    r = c.post("/inbox", data={"text": "check the DMA wrap", "back": "/"},
               follow_redirects=False)
    assert _flash(r)[1]
    [d] = inbox.items(registry.home())
    assert "check the DMA wrap" in c.get("/b/main").text           # the Inbox column
    r = c.post("/inbox/%s/accept" % d["id"], follow_redirects=False)
    assert r.headers["location"].startswith("/new?") and "check+the+DMA+wrap" in \
        r.headers["location"]
    assert inbox.items(registry.home()) == []
    r = c.post("/p/a/plan", data={"priority": "bogus"}, follow_redirects=False)
    assert not _flash(r)[1]
