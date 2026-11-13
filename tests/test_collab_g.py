"""Closing the gaps (docs/collaboration-plan.md G): sessions the hooks name,
and the rest of the G slices."""

import os
import shutil
import time

import pytest

from test_dash_tasks import _new
from work_packet import hookcmd, ide_sessions, presence, registry, views
from work_packet.dash import data

CLAUDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ide_sessions",
                      "claude_vscode.jsonl")
SID = "7f3c1a2e-0b5d-4c6e-9f10-2a3b4c5d6e7f"


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


# --- G2: tokens for desktop and terminal sessions ----------------------------------

def test_the_hook_keeps_the_transcript_path(tmp_path, fake):
    e, _ = _new("a")
    tp = str(tmp_path / "t.jsonl")
    env = {"CLAUDE_CODE_ENTRYPOINT": "cli"}
    hookcmd._apply("SessionStart", {"session_id": SID, "cwd": e["path"],
                                    "transcript_path": tp}, env)
    assert presence.get(e["path"], "claude-" + SID)["transcript"] == tp
    hookcmd._apply("UserPromptSubmit", {"session_id": "s2" * 5, "cwd": e["path"],
                                        "transcript_path": "relative.jsonl"}, env)
    assert "transcript" not in presence.get(e["path"], "claude-" + "s2" * 5)


def test_a_desktop_session_is_read_from_its_transcript(tmp_path, fake):
    e, _ = _new("a")
    tp = str(tmp_path / "t.jsonl")
    shutil.copy(CLAUDE, tp)
    h = registry.home()
    now = time.time()
    presence.beat(e["path"], "claude-" + SID, now, kind="claude", via="ide-desktop",
                  session=SID, turn="working", wpid=e["root"], transcript=tp)
    assert ide_sessions.hook_pass(h, now) == 1
    r = ide_sessions.read(h, "claude", SID)
    assert r["attribution"] == "hook" and r["project"] == "a" and r["wpid"] == e["root"]
    assert r["client"] == "vscode-ext" and r["live"]
    assert ide_sessions.total(r["usage"]) == 686
    rows = ide_sessions.project_view(h, "a")
    assert rows and rows[0]["tokens"] == 686 and rows[0]["process"] == "running"
    ide_sessions._CACHE.clear()
    day = ide_sessions.epoch("2026-11-04T12:00:00.000Z")         # the fixture's day
    assert data.session_spend(h, day)["tokens"] == 686
    # nothing new: counted once
    ide_sessions.hook_pass(h, now + 5)
    assert ide_sessions.total(ide_sessions.read(h, "claude", SID)["usage"]) == 686
    # it ends: one last read, then it is left alone
    presence.end(e["path"], "claude-" + SID, now + 10)
    assert ide_sessions.hook_pass(h, now + 10) == 1
    assert not ide_sessions.read(h, "claude", SID)["live"]
    assert ide_sessions.hook_pass(h, now + 15) == 0


def test_web_sessions_are_left_to_their_launch(tmp_path, fake):
    e, _ = _new("a")
    tp = str(tmp_path / "t.jsonl")
    shutil.copy(CLAUDE, tp)
    h = registry.home()
    presence.beat(e["path"], "claude-" + SID, None, kind="claude", via="ide-web",
                  session=SID, transcript=tp)
    assert ide_sessions.hook_pass(h) == 0
    presence.beat(e["path"], "claude-" + SID, None, via="terminal")
    ide_sessions.write(h, {"harness": "claude", "session_id": SID,
                           "attribution": "confirmed", "project": "a"})
    assert ide_sessions.hook_pass(h) == 0                   # a collector has it


def test_a_hook_pass_with_nothing_new_writes_nothing(tmp_path, fake, monkeypatch):
    e, _ = _new("a")
    tp = str(tmp_path / "t.jsonl")
    shutil.copy(CLAUDE, tp)
    h = registry.home()
    now = time.time()
    presence.beat(e["path"], "claude-" + SID, now, kind="claude", via="terminal",
                  session=SID, turn="working", wpid=e["root"], transcript=tp)
    assert ide_sessions.hook_pass(h, now) == 1
    writes = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: writes.append(b) or real(a, b))
    assert ide_sessions.hook_pass(h, now + 5) == 1
    assert writes == []


# --- G3: checkpoints from sessions -------------------------------------------------

def test_a_scribe_draft_is_offered_and_accepted(tmp_path, fake):
    from test_dash_tasks import _client, _flash
    from work_packet import checkpoint
    e, pkt = _new("a", paused=True)
    out, _ = checkpoint.record(pkt, "parser half done", body="Split the lexer out.",
                               next_action="finish the parser", worker="scribe", by="scribe")
    assert out.code == 0
    d = checkpoint.draft_of(pkt)
    assert d["status"] == "parser half done" and d["body"] == "Split the lexer out."
    assert d["next"] == "finish the parser"
    c = _client()
    board = c.get("/b/main").text
    assert "draft checkpoint" in board and 'value="accept-draft"' in board
    page = c.get("/p/a/%s" % pkt.wpid).text
    assert "Draft checkpoint" in page and "Split the lexer out.</textarea>" in page
    r = c.post("/p/a/%s/act" % pkt.wpid, data={"action": "accept-draft", "back": "/b/main"},
               follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    assert checkpoint.last(pkt)["worker"] == "session"
    assert checkpoint.draft_of(pkt) is None
    assert "finish the parser" in open(pkt.memento_path).read()
    assert "draft checkpoint" not in c.get("/b/main").text
    r = c.post("/p/a/%s/act" % pkt.wpid, data={"action": "accept-draft"},
               follow_redirects=False)
    assert not _flash(r)[1]                                 # nothing left to accept


def test_compaction_nudges_for_a_checkpoint(tmp_path, fake):
    from work_packet import checkpoint
    e, pkt = _new("a", paused=True)
    from work_packet import clock
    at = clock.now().timestamp() - 60                       # the journal's clock (WPK_NOW)
    rec = presence.beat(e["path"], "claude-" + SID, at, kind="claude", session=SID)
    assert hookcmd.compact_nudge(e["path"], e["root"], rec) == hookcmd.NUDGE
    checkpoint.record(pkt, "where it stands", by="me")
    assert hookcmd.compact_nudge(e["path"], e["root"], rec) == ""
    env = {"CLAUDE_CODE_ENTRYPOINT": "cli"}
    rec2, say = hookcmd.handle("SessionStart", {"session_id": SID, "cwd": e["path"],
                                                "source": "compact"}, env)
    assert say == ""                                        # recorded since it started


def test_an_ended_desktop_session_is_due_for_the_scribe(tmp_path, fake):
    from work_packet import scribe
    now = time.time()
    rec = {"harness": "claude", "session_id": SID, "attribution": "hook", "project": "a",
           "wpid": "x", "last_work_t": now - 60, "last_activity_t": now - 60, "live": False}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scribe, "packet_of", lambda r, h=None: None)   # stops before the packet
        assert scribe.due(registry.home(), now, {}, [rec]) == []
    # the condition itself: ended, so it doesn't wait for scribe_idle_s
    assert rec["attribution"] in (ide_sessions.CONFIRMED, ide_sessions.HOOK)


# --- G4: watchers on the board -----------------------------------------------------

def test_watchers_are_added_edited_and_removed_from_the_board(tmp_path, fake):
    from test_dash_tasks import _client, _flash
    from work_packet import watch
    from work_packet.tomlio import load_toml
    h = registry.home()
    registry.new_board("dv", h=h)
    c = _client()
    assert "Add a watcher" in c.get("/b/dv").text
    form = {"op": "save", "name": "issues", "repos": "github:acme/rtl, github:acme/*",
            "labels": "wpk", "dir": str(tmp_path / "iss"), "every": "30m", "pr": "draft",
            "hold": "1", "enabled": "1"}
    r = c.post("/b/dv/watch", data=form, follow_redirects=False)
    assert _flash(r) == ("added the watcher issues", True)
    [w] = watch.find("dv", h)
    assert w["repos"] == ["github:acme/rtl", "github:acme/*"] and w["labels"] == ["wpk"]
    assert w["every"] == "30m" and w["pr"] == "draft" and w["hold"] and not w["propose"]
    # a key the form doesn't show survives an edit
    p = os.path.join(h, "boards", "dv.toml")
    d = load_toml(p)
    d["watch"][0]["query"] = "is:open"
    from work_packet.tomlio import save_toml
    save_toml(p, d)
    r = c.post("/b/dv/watch", data=dict(form, was="issues", name="dv-issues", propose="1",
                                        enabled=""), follow_redirects=False)
    assert _flash(r)[1]
    [w] = watch.find("dv", h)
    assert w["name"] == "dv-issues" and w["propose"] and not w["enabled"]
    assert w["query"] == "is:open" and load_toml(p)["name"] == "dv"
    page = c.get("/b/dv").text
    assert "dv-issues" in page and "to the Inbox" in page
    # checked like [[watch]]; nothing written when it doesn't pass
    r = c.post("/b/dv/watch", data=dict(form, name="bad", repos="acme/rtl"),
               follow_redirects=False)
    assert not _flash(r)[1] and "repos" in _flash(r)[0]
    r = c.post("/b/dv/watch", data=dict(form, name="dv-issues"), follow_redirects=False)
    assert "already" in _flash(r)[0]
    r = c.post("/b/dv/watch", data={"op": "remove", "name": "dv-issues"},
               follow_redirects=False)
    assert _flash(r)[1] and not [x for x in watch.watchers(h) if x["board"] == "dv"]
    assert "watch" not in load_toml(p)


def test_main_gets_a_board_file_for_its_first_watcher(tmp_path, fake):
    from work_packet import watch
    h = registry.home()
    watch.save("main", {"name": "w", "repos": ["github:a/b"], "dir": str(tmp_path)}, h=h)
    assert [x["name"] for x in watch.find("main", h)] == ["w"]
    with pytest.raises(watch.WatchError):
        watch.save("nope", {"name": "w", "repos": ["github:a/b"], "dir": "x"}, h=h)


# --- G5: Desk and board odds and ends ----------------------------------------------

def test_a_checkpoint_with_a_next_action_starts_a_task(tmp_path, fake):
    from work_packet import checkpoint
    e, pkt = _new("a", paused=True)
    checkpoint.record(pkt, "lexer done", by="me")                   # no next: same task
    assert [t["n"] for t in data.tasks(e, data.tree(e)) if t["kind"] == "task"] == [1]
    checkpoint.record(pkt, "parser done", next_action="write the tests", by="me")
    ts = [t for t in data.tasks(e, data.tree(e)) if t["kind"] == "task"]
    assert [t["instruction"] for t in ts] == ["", "write the tests"]
    assert ts[0]["state"] == "COMPLETED" and ts[1]["steps"] == []
    # a hand-off right after it names the same task, rather than an empty one
    from work_packet import executor
    out = executor.admin(pkt, "continue", instruction="write the tests and the docs")
    assert out.code == 0, out.msg
    ts = [t for t in data.tasks(e, data.tree(e)) if t["kind"] == "task"]
    assert [t["instruction"] for t in ts] == ["", "write the tests and the docs"]


def test_desk_rows_offer_open_and_next(tmp_path, fake, monkeypatch):
    from test_dash_tasks import _client
    from work_packet import planning
    e, pkt = _new("a", paused=True)
    presence.beat(e["path"], "shell-1", None, kind="shell", by="me")    # you: In progress
    page = _client().get("/").text
    i = page.index('id="running"')
    assert "openmenu" in page[i:page.index("Coming up", i)]
    # rotting while parked: a STALE row with Plan and Hand off
    presence.end(e["path"], "shell-1")
    monkeypatch.setattr(planning, "ROT_DAYS", {k: -1 for k in planning.ROT_DAYS})
    page = _client().get("/").text
    assert ">STALE<" in page and "untouched for" in page and "/p/a/compose" in page


def test_a_queued_instruction_can_be_changed(tmp_path, fake):
    from test_dash_tasks import _client, _flash
    e, pkt = _new("a")                                          # queued for the runner
    c = _client()
    page = c.get("/p/a/compose").text
    assert 'value="requeue"' in page and "Read state/count.md" in page
    r = c.post("/p/a/compose", data={"action": "requeue", "instruction": "Count to two."},
               follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    assert open(pkt.memento_path).read() == "Count to two.\n"
    assert any(r.get("op") == "requeue" for r in pkt.journal().records)
    r = c.post("/p/a/compose", data={"action": "requeue", "instruction": " "},
               follow_redirects=False)
    assert not _flash(r)[1]
    from work_packet import executor
    executor.admin(pkt, "pause")
    assert executor.requeue(pkt, "x").code != 0                  # not queued any more
    assert 'value="requeue"' not in c.get("/p/a/compose").text


def test_a_long_wait_is_journalled_once(tmp_path, fake):
    from work_packet import attention, views
    e, pkt = _new("a", paused=True)
    T = time.time()
    presence.beat(e["path"], "claude-" + SID, T - 1000, kind="claude", via="ide-desktop",
                  session=SID, turn="waiting", by="me")
    assert attention.log_waits(e["path"], e["root"], T - 500, 900) == 0     # not yet
    assert attention.log_waits(e["path"], e["root"], T, 900) == 1
    assert attention.log_waits(e["path"], e["root"], T + 60, 900) == 0      # once
    [r] = [r for r in pkt.journal().records if r["type"] == "turn-waiting"]
    assert r["session"] == SID
    ev = [x for x in views.timeline(pkt) if x["kind"] == "waiting"]
    assert ev and ev[0]["text"].startswith("waited for you since")
    # a new turn, a new wait
    presence.beat(e["path"], "claude-" + SID, T + 100, turn="working")
    presence.beat(e["path"], "claude-" + SID, T + 200, turn="waiting")
    assert attention.log_waits(e["path"], e["root"], T + 1200, 900) == 1


# --- G6: the Inbox ----------------------------------------------------------------

from test_requests import req                                       # noqa: E402,F401


def test_an_inbox_item_snoozed_until_its_project_moves(tmp_path, fake):
    from work_packet import checkpoint, inbox
    h = registry.home()
    e, pkt = _new("a", paused=True)
    d = inbox.add(h, "also fix the reset", project="a")
    T = time.time()
    os.utime(pkt.journal_path, (T - 100, T - 100))
    assert inbox.snooze(h, d["id"], T + 365 * 86400, change=True, now=T)
    assert inbox.get(h, d["id"])["until"] <= T + inbox.CHANGE_MAX_S
    assert d["id"] not in [x["id"] for x in inbox.items(h, T + 10)]
    checkpoint.record(pkt, "moved on", by="me")
    os.utime(pkt.journal_path, (T + 20, T + 20))
    assert d["id"] in [x["id"] for x in inbox.items(h, T + 30)]       # it moved
    # an item with no project: only the time counts
    d2 = inbox.add(h, "a thought")
    inbox.snooze(h, d2["id"], T + 3600, change=True, now=T)
    assert "change_at" not in inbox.get(h, d2["id"])
    assert d2["id"] not in [x["id"] for x in inbox.items(h, T + 10)]


def test_decline_a_request_from_the_inbox(req, tmp_path):
    from test_dash_tasks import _client, _flash
    from work_packet import inbox, requests
    from work_packet.packet import Packet
    e = requests.send(req, "reg", by="me")
    worker = Packet(registry.resolve("worker"))
    if worker.load_status()[0]["state"] != "PAUSED":
        from work_packet import executor
        executor.admin(worker, "pause")
    [r] = inbox.requests()
    assert r["from_wpid"] == req.wpid
    c = _client()
    assert "Decline ▾" in c.get("/backlog").text
    resp = c.post("/inbox/request/decline", data={"from": req.wpid, "id": r["id"],
                                                  "reason": "not this quarter"},
                  follow_redirects=False)
    assert _flash(resp)[1], _flash(resp)
    assert requests.get(req.wpid, r["id"])["state"] == "delivered"
    got = [n["text"] for n in __import__("work_packet").notes.queued(req)]
    assert any("declined" in t and "not this quarter" in t for t in got)
    assert worker.load_status()[0].get("lifecycle") == "dropped"
    assert inbox.requests() == []
    resp = c.post("/inbox/request/decline", data={"from": req.wpid, "id": r["id"]},
                  follow_redirects=False)
    assert not _flash(resp)[1]


# --- G7: split ----------------------------------------------------------------------

from test_setup import git, home, source                            # noqa: E402,F401


def test_a_split_links_your_tools_points_back_and_can_be_removed(home, source):
    from test_collab_c7 import _packet, _run
    from test_dash_tasks import _client, _flash
    from work_packet import split
    os.makedirs(source / "packages" / "tool")                    # untracked tools
    e = _packet(source)
    name = split.make(e, "Add a NOTES file.")
    tree = os.path.join(home, "splits", name)
    assert os.path.islink(os.path.join(tree, "packages"))
    assert git(tree, "status", "--porcelain") == ""              # excluded, not new files
    s = registry.get(name)
    c = _client()
    assert 'split of <a href="/p/dv#split">dv</a>' in c.get("/b/main").text
    with pytest.raises(split.SplitError, match="first"):
        split.remove(s)                                          # still open
    _run(name)
    open(os.path.join(tree, "NOTES.md"), "w").write("notes\n")
    split.land(s)
    page = c.get("/p/%s" % name).text
    assert 'value="remove"' in page
    r = c.post("/p/%s/split" % name, data={"op": "remove"}, follow_redirects=False)
    msg, ok = _flash(r)
    assert ok and "branch wpk/%s deleted" % name in msg, msg
    assert not os.path.exists(tree) and registry.get(name) is None
    assert os.path.isfile(os.path.join(home, "splits", "removed", name + ".journal.jsonl"))
    assert "wpk/%s" % name not in git(source, "branch", "--list")
    assert (source / "NOTES.md").read_text() == "notes\n"        # what it brought in stays
    texts = [x["text"] for x in views.timeline(_root_pkt(e))]
    assert any("removed the split" in t for t in texts)


def test_a_dropped_split_keeps_its_branch(home, source):
    from test_collab_c7 import _packet, _run
    from work_packet import split
    e = _packet(source)
    s = registry.get(split.make(e, "Try something."))
    _run(s["name"])
    split.drop(s)
    assert "kept" in split.remove(s)
    assert "wpk/%s" % s["name"] in git(source, "branch", "--list")


def _root_pkt(e):
    from work_packet import layout
    from work_packet.hookcmd import _root
    from work_packet.packet import Packet
    return Packet(layout.run_dir(e["path"], _root(e["path"])))


# --- G8: the forecast ---------------------------------------------------------------

def test_your_share_is_laid_on_working_days():
    from datetime import datetime
    from work_packet import forecast
    fri = datetime(2026, 11, 6, 18, 0).timestamp()
    assert datetime.fromtimestamp(forecast.add_working(fri, 1)) == datetime(2026, 11, 9, 18, 0)
    assert datetime.fromtimestamp(forecast.add_working(fri, 0.25)).weekday() == 0   # Sat -> Mon
    wed = datetime(2026, 11, 4, 9, 0).timestamp()
    assert datetime.fromtimestamp(forecast.add_working(wed, 3)) == datetime(2026, 11, 9, 9, 0)


def test_your_own_answer_times_once_you_have_enough(monkeypatch):
    from work_packet import forecast
    mine = [(3600.0, "alice")] * forecast.OWN_MIN
    theirs = [(86400.0, "bob")] * 10
    monkeypatch.setattr(forecast, "_history", lambda e: ([], mine + theirs))
    monkeypatch.setattr(forecast, "left", lambda e: None)
    card = {"ball": {"who": "you", "kind": "question"}, "root": {"owner": "alice@h"}}
    fc = forecast.forecast({"path": "/x", "root": "r"}, card, now=1_800_000_000.0)
    assert fc["yours"] == (3600.0, 3600.0)
    card["root"]["owner"] = "carol"                           # no answers of her own
    fc = forecast.forecast({"path": "/x", "root": "r"}, card, now=1_800_000_000.0)
    assert fc["yours"][1] == 86400.0
    # pooled over the board: the same rule
    forecast._cache.clear()
    monkeypatch.setattr(forecast.registry, "entries", lambda h=None: [{"path": "/x", "root": "r"}])
    assert set(forecast.board_history("/h", 0.0, "alice")[1]) == {3600.0}
    assert 86400.0 in forecast.board_history("/h", 1.0, "carol")[1]
