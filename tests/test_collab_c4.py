"""The Desk (docs/collaboration.md §4.3, §8.1, §8.4): typed items from the sessions
you drive, snoozes, "since you were last here", the timeline and the session cost."""

import json
import os
import time

import pytest

from test_dash_tasks import _client, _flash, _new
from work_packet import attention, checkpoint, executor, presence, scheduler, views
from work_packet.dash import data

T = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _claude(proj, turn, at, **kw):
    """A session whose turn became ``turn`` at ``at``."""
    presence.beat(proj, "claude-s", at, kind="claude", via="ide-desktop", session="s",
                  turn=turn, **kw)


@pytest.mark.parametrize("turn,age,want", [
    ("blocked", 30, []), ("blocked", 200, ["blocked"]),
    ("waiting", 600, []), ("waiting", 1000, ["your turn"]),
    ("working", 1000, []), ("working", 4000, ["stale"])])
def test_session_items(tmp_path, turn, age, want):
    proj = str(tmp_path)
    _claude(proj, turn, T, tool="Bash")
    got = attention.session_items(proj, T + age)
    assert [x["type"] for x in got] == want
    if want == ["blocked"]:
        assert got[0]["text"] == "Claude (VS Code) wants to run Bash"


def test_a_visible_tab_means_you_see_it(tmp_path):
    proj = str(tmp_path)
    _claude(proj, "blocked", T)
    presence.beat(proj, "ide-web-k-t", T + 290, kind="ide-web", visible=True, active=T + 290)
    assert attention.session_items(proj, T + 300) == []
    presence.beat(proj, "ide-web-k-t", T + 295, visible=False)
    assert [x["type"] for x in attention.session_items(proj, T + 300)] == ["blocked"]


def test_snooze(tmp_path):
    home = str(tmp_path)
    k = attention.key("a", {"type": "blocked", "source": "claude-s", "since": T})
    attention.snooze(home, "me", k, T + 3600, now=T)
    assert k in attention.snoozes(home, "me", T + 10)
    assert attention.snoozes(home, "me", T + 3601) == {}
    assert attention.snoozes(home, "you", T + 10) == {}               # per person
    assert attention.until_of("1h", T) == T + 3600
    assert attention.until_of("change", T) > T + 300 * 86400


def test_visits(tmp_path):
    home = str(tmp_path)
    assert attention.since(home, "me", T) is None
    attention.visit(home, "me", T)
    assert attention.since(home, "me", T + 60) is None                 # the same sitting
    attention.visit(home, "me", T + 60)
    assert attention.since(home, "me", T + 7200) == T + 60             # back later
    attention.visit(home, "me", T + 7200)
    assert attention.since(home, "me", T + 7300) == T + 60             # a reload


def test_timeline_names_every_actor(fake):
    e, pkt = _new("a")
    scheduler.tick([e], until_idle=True)
    executor.admin(pkt, "continue", instruction="More.", by="bob@h", force=True)
    executor.admin(pkt, "pause", by="bob@h")
    checkpoint.record(pkt, "half done", by="alice@h")
    executor.mark(pkt, "done", by="bob@h")
    with open(pkt.journal_path, "a") as fp:
        fp.write(json.dumps({"type": "session-start", "t": "2026-10-21T18:05:00Z",
                             "by": "carol", "session": "s",
                             "actor": {"kind": "claude", "via": "ide-web", "session": "s"}}) + "\n")
    tl = views.timeline(pkt)
    got = [(x["actor"], x["kind"]) for x in tl]
    assert ("bob", "done") in got and ("alice (VS Code)", "checkpoint") in got
    assert ("runner", "step") in got and ("bob", "handoff") in got
    assert ("Claude (VS Code (web))", "session-start") in got
    assert [x["t"] for x in tl] == sorted((x["t"] for x in tl), reverse=True)
    late = max(x["t"] for x in tl if x["kind"] == "step")
    assert all(x["t"] > late for x in views.timeline(pkt, since=late))


def test_the_desk(fake, monkeypatch):
    monkeypatch.delenv("WPK_NOW")                       # presence and visits: wall-clock
    e, pkt = _new("a")
    _new("b")
    now = time.time()
    _claude(e["path"], "blocked", now - 300, tool="Bash")
    c = _client()
    page = c.get("/").text
    assert ">BLOCKED<" in page and "wants to run Bash" in page and "Reviews" in page
    # snooze it: it goes, and says so
    k = [a["key"] for a in data.overview(*_ov()).get("attention") if a["kind"] == "blocked"][0]
    r = c.post("/attention/snooze", data={"item": k + "@@1h", "back": "/"},
               follow_redirects=False)
    assert _flash(r) == ("snoozed for an hour", True)
    page = c.get("/").text
    assert ">BLOCKED<" not in page and "(1 snoozed)" in page
    # since you were last here: the page's beacon notes the visit; a later one lists
    # what happened in between
    assert c.post("/attention/visit").status_code == 204
    home = os.environ["WPK_HOME"]
    me = [n for n in os.listdir(os.path.join(home, "attention")) if n.endswith(".visit.json")]
    p = os.path.join(home, "attention", me[0])
    json.dump({"last": now - 7200, "since": None}, open(p, "w"))
    executor.mark(pkt, "autonomy", autonomy="manual", by="me@h")
    page = c.get("/").text
    assert "Since you were last here" in page and "set autonomy to manual" in page


def _ov():
    cols, broken = data.board()
    side = data.side(None, cols, broken)
    return cols, broken, side, {}


def test_board_filter(fake):
    from work_packet import registry
    _new("a")
    _new("b")                                       # both queued: under Coming up
    registry.new_board("other")
    registry.move("b", "other")
    c = _client()
    page = c.get("/?board=other").text
    assert 'class="on" href="/?board=other"' in page
    assert ">b</strong>" in page and ">a</strong>" not in page
    page = c.get("/?board=nope").text                       # unknown: every board
    assert ">a</strong>" in page and ">b</strong>" in page


def test_packet_page_timeline(fake):
    e, pkt = _new("a")
    scheduler.tick([e], until_idle=True)
    page = _client().get("/p/a/%s" % pkt.wpid).text
    assert 'id="timeline"' in page and "<strong>runner</strong>" in page


def test_session_spend(tmp_path, monkeypatch):
    """Only the tokens spent today count, not a session's whole life
    (docs/session-cost-plan.md S4); priced by the model."""
    from work_packet import session_usage
    from work_packet.ide_sessions import hour_of
    now = time.time()
    session_usage.put(str(tmp_path), {"harness": "claude", "session_id": "s1-aaaaaaaa"}, {
        hour_of(now): {"claude-sonnet-5": {"input_tokens": 1000, "output_tokens": 500}},
        hour_of(now - 3 * 86400): {"claude-sonnet-5": {"input_tokens": 9}}})
    got = data.session_spend(str(tmp_path), now)
    assert got["tokens"] == 1500
    assert got["usd"] == pytest.approx((1000 * 2.0 + 500 * 10.0) / 1e6)


def test_columns_take_drops(fake):
    """board.js drags a card onto Done, Parked or Working: agent (§8.2): the page
    gives it the columns and each card's root."""
    e, pkt = _new("a")
    page = _client().get("/b/main").text
    for col in ("Done", "Parked", "Working: agent"):
        assert 'data-col="%s"' % col in page
    assert 'data-root="%s"' % pkt.wpid in page


def test_codex_sessions_need_you_too(tmp_path):
    """Codex's presence (written by the session collector) gives the same items
    (docs/agent-state-plan.md A2)."""
    proj = str(tmp_path)
    presence.beat(proj, "codex-c", T, kind="codex", via="vscode", session="c", turn="waiting")
    got = attention.session_items(proj, T + 1000)
    assert [x["text"] for x in got] == ["Codex (VS Code) is waiting for you"]
    assert attention.log_waits(proj, "W" * 26, T + 1000) in (0, 1)   # never raises


def test_agents_chip(tmp_path):
    """The card's and packet page's chip (docs/agent-state-plan.md A3): the most
    urgent turn first, and a packet sees only its own sessions."""
    e = {"path": str(tmp_path)}
    assert data.agents(e, now=T) is None
    presence.beat(e["path"], "codex-c", T, kind="codex", via="vscode", session="c",
                  turn="working", wpid="W1")
    got = data.agents(e, now=T + 120)
    assert got["turn"] == "working" and got["text"] == "Codex · working"
    assert got["title"] == "Codex (VS Code): working for 2m"
    _claude(e["path"], "blocked", T + 60, tool="Bash", wpid="W2")
    got = data.agents(e, now=T + 120)
    assert got["turn"] == "blocked" and got["text"] == "2 agents · needs OK"
    assert "Claude (VS Code): wants to run Bash for 1m" in got["title"]
    assert data.agents(e, "W1", now=T + 120)["text"] == "Codex · working"
    presence.end(e["path"], "codex-c", T + 130)
    assert data.agents(e, "W1", now=T + 140) is None


def test_the_board_and_packet_page_show_the_chip(fake, monkeypatch):
    monkeypatch.delenv("WPK_NOW")                       # presence: wall-clock
    e, pkt = _new("a")
    now = time.time()
    presence.beat(e["path"], "codex-c", now - 30, kind="codex", via="vscode", session="c",
                  turn="working", wpid=pkt.wpid)
    c = _client()
    board = c.get("/b/main").text
    assert '<span class="agent working"' in board and "Codex · working" in board
    page = c.get("/p/a/%s" % pkt.wpid).text
    assert '<span class="agent working"' in page and "Codex (VS Code): working for" in page
