"""Presence on the board and in the scheduler (docs/collaboration.md §4.2, §5):
the runner waits while you work on a project, a hand-off made while you are there
starts at once, and web VS Code tabs report themselves."""

import json
import os
import time

import pytest

from test_dash_tasks import _client, _new
from test_ide import _web_client, short_home                  # noqa: F401
from test_setup import git, home, source                       # noqa: F401
from work_packet import executor, ide_launch, presence, scheduler, sessionhooks, views
from work_packet.dash import data


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _here(e, kind="claude", **kw):
    presence.beat(e["path"], "%s-test" % kind, kind=kind, via="ide-web", **kw)


def test_the_runner_waits_while_you_are_there(fake):
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    _here(e)
    assert executor.admin(pkt, "resume", defer=True).code == 0     # "after I leave"
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["step"] == 0
    card = data.card(e)
    assert card["column"] == "Working: you" and card["driver"] == "you"
    assert "VS Code (web)" in card["ball"]["text"]
    presence.end(e["path"], "claude-test")                         # you left
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["step"] > 0


def test_a_hand_off_while_you_are_there_starts(fake, monkeypatch):
    monkeypatch.delenv("WPK_NOW")                      # presence is wall-clock time
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    _here(e)
    time.sleep(1.1)                                    # the hand-off is after you came
    assert executor.admin(pkt, "handoff", note="go").code == 0
    assert pkt.journal().records[-1]["defer"] is False
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["step"] > 0


def test_you_coming_holds_work_handed_off_before(fake):
    e, pkt = _new("a")                                 # RUNNABLE from its creation
    _here(e)
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["step"] == 0


def test_cli_after_me(fake):
    from work_packet import cli
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    assert cli.main(["handoff", "a", "-m", "later", "--after-me"]) == 0
    assert pkt.journal().records[-1]["defer"] is True


def test_the_board_shows_you_and_the_hooks(fake):
    e, pkt = _new("a")
    _here(e, turn="blocked")
    c = _client()
    board = c.get("/b/main").text
    assert "you · VS Code (web) · Claude ×1 (1 blocked)" in board
    page = c.get("/p/a/%s" % pkt.wpid).text
    assert "you have it" in page


def test_packet_folder_hooks_on_the_page(home, source):
    from test_ide import _board_client
    from test_packet_layout import new_here
    plan = new_here(source)
    c, origin, tok = _board_client("loopback")
    page = c.get("/p/sr/" + plan.root).text
    assert "Claude Code hooks in the folder" not in page        # installed: nothing to say
    sessionhooks.uninstall(str(source))
    page = c.get("/p/sr/" + plan.root).text
    assert "not installed" in page and ">Install<" in page
    r = c.post("/p/sr/%s/act" % plan.root, headers=origin,
               data={"csrf": tok, "action": "hooks"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=1" in r.headers["location"]
    assert sessionhooks.status(str(source)) == "installed"
    # the board's switch takes them out of every packet folder, and back
    r = c.post("/sessions/hooks", headers=origin, data={"csrf": tok, "on": "0"},
               follow_redirects=False)
    assert "ok=1" in r.headers["location"]
    assert sessionhooks.status(str(source)) == "missing"
    c.post("/sessions/hooks", headers=origin, data={"csrf": tok, "on": "1"})
    assert sessionhooks.status(str(source)) == "installed"
    # desktop: the open itself is presence for a while
    c.post("/p/sr/ide", headers=origin, data={"csrf": tok, "wpid": plan.root, "go": "desktop"})
    assert [r["kind"] for r in presence.live(plan.path)] == ["ide-desktop"]


def test_web_tabs_report_themselves(fake, short_home, tmp_path):   # short_home wins
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        e, pkt = _new("w")
        ide_launch.record_open(short_home, be.key, "w", pkt.wpid, "me")
        r = c.get("/ide/%s/?folder=/x" % be.key)
        assert "/static/ide_presence.js" in r.text
        assert c.get("/static/ide_presence.js").status_code == 200
        url = "/ide/%s/__wpk/vis" % be.key
        r = c.post(url, headers=dict(origin, **{"content-type": "application/json"}),
                   content=json.dumps({"tab": "abc123", "visible": True}))
        assert r.status_code == 204
        recs = presence.live(e["path"])
        assert [(x["kind"], x["visible"], x["wpid"]) for x in recs] == [("ide-web", True, pkt.wpid)]
        assert c.post(url, headers=origin, content=json.dumps({"tab": "../x"})).status_code == 400
        c.post(url, headers=origin, content=json.dumps({"tab": "abc123", "gone": True}))
        assert presence.live(e["path"]) == []
    finally:
        be.stop()
        c.__exit__(None, None, None)


def test_views_with_presence():
    meta = {"state": "RUNNABLE", "lifecycle": "open"}
    here = [{"kind": "shell", "via": "shell"}]
    assert views.driver(meta, {"step": 2}, here) == "you + runner"
    assert views.column(meta, {"step": 2}, here) == "Working: agent"
    assert views.column(meta, None, here) == "Working: you"
    asks = {"state": "NEEDS_INPUT", "reason": "which?", "lifecycle": "open"}
    assert views.ball(asks, None, here)["kind"] == "question"     # still yours to answer


def test_doctor_and_wpk_hooks(home, source, capsys):
    from test_packet_layout import new_here
    from work_packet import cli, setup
    new_here(source)
    tg = setup.target("sr")
    ck = {c.id: c for c in setup.readiness(tg, tools=False)}
    assert ck["work.hooks"].level == "ok"
    assert cli.main(["hooks", "remove", "sr"]) == 0
    ck = {c.id: c for c in setup.readiness(tg, tools=False)}
    assert ck["work.hooks"].level == "warn" and ck["work.hooks"].fix == ["wpk hooks install sr"]
    missing = {c.id for c in setup.missing(list(ck.values()))}
    assert "work.hooks" not in missing                             # never blocks a hand-off
    assert cli.main(["hooks", "install", "sr"]) == 0
    assert cli.main(["hooks", "status", "sr"]) == 0
    assert capsys.readouterr().out.rstrip().endswith(": installed")
