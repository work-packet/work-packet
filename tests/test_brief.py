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


# --- the brief by a model (briefagent.py, docs/focus-brief-review.md) -----------------------

def _reply(**kw):
    import json
    d = {"headline": "Two decisions, then the release.", "yesterday": [], "decide": [],
         "close_out": [], "uncommitted": [], "focus": [], "housekeeping": []}
    d.update(kw)
    return "Here it is:\n" + json.dumps(d)


def test_the_model_writes_the_brief_from_a_bundle(fake, monkeypatch):
    import json
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "asker")
    ea, pa = _new("asking")
    scheduler.tick([ea], until_idle=True)
    seen = {}

    def ask(prompt, **kw):
        seen["prompt"], seen["kw"] = prompt, kw
        return _reply(
            decide=[{"project": "asking", "question": "Ship it?", "options": ["yes", "no"],
                     "waiting": "2 days", "recommend": "yes"},
                    {"project": "made-up", "question": "Invented?"}],
            close_out=[{"project": "nope", "action": "merge"}],
            focus=[{"theme": "the asker", "projects": ["asking", "ghost"], "why": "it blocks",
                    "first_action": "answer it"}],
            housekeeping=[{"project": "", "text": "five packets will not read"}]), 0.12

    h = _home()
    b = brief.build(h, ask=ask)
    bundle = json.load(open(brief.path(h, b["day"], "bundle.json")))
    assert [p["project"] for p in bundle["packets"]] == ["asking"]
    assert bundle["packets"][0]["questions"][0]["q"]          # the question, in full
    assert "asking" in seen["prompt"] and seen["kw"]["model"] == "sonnet"
    a = b["agent"]
    assert [x["project"] for x in a["decide"]] == ["asking"]   # made-up is dropped
    assert a["close_out"] == [] and a["cost"] == 0.12
    assert a["focus"][0]["projects"] == ["asking"]             # ghost is dropped
    assert b["focus"][0]["project"] == "asking" and b["focus"][0]["next"] == "answer it"
    md = open(brief.path(h, b["day"], "md")).read()
    assert "## Decide" in md and "Ship it? Options: yes / no." in md
    assert "1. **the asker** (asking): it blocks · First: answer it" in md
    assert brief.days(h) == [b["day"]]                         # the bundle is not a day
    assert "Today's focus on the board: asking" in brief.focus_line(h)
    brief.say(h, b["day"], "asking", "not today")              # filtered, no new model call
    b2 = brief.apply_feedback(h)
    assert b2["focus"] == [] and b2["agent"]["focus"] == []


def test_a_failed_model_leaves_the_scored_brief(fake):
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    h = _home()
    b = brief.build(h, ask=lambda prompt, **kw: ("not json at all", 0.01))
    assert "agent" not in b and b["agent_error"] == "the model's answer was not JSON"
    assert [f["project"] for f in b["focus"]] == ["a"]
    assert "this is the scored one" in open(brief.path(h, b["day"], "md")).read()
    b = brief.build(h, ask=lambda prompt, **kw: (_reply(headline="", focus=[
        {"theme": "x", "projects": ["nobody"]}]), 0.0))
    assert b["agent_error"] == "the model's answer named nothing on the board"
    called = []
    brief.build(h, ask=lambda prompt, **kw: called.append(1) or ("", 0.0), agent=False)
    assert called == []


def test_session_digest(tmp_path):
    import json
    from work_packet import briefagent

    def write(name, rows):
        d = tmp_path / "projects" / "-x"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / name, "w") as fp:
            for r in rows:
                fp.write(json.dumps(r) + "\n")

    t0 = datetime(2026, 11, 8, 10, 0).timestamp()

    def at(m):
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + m * 60))
    base = {"entrypoint": "cli", "cwd": "/w/proj/sub", "sessionId": "s1"}
    write("s1.jsonl", [
        dict(base, type="user", timestamp=at(0), message={"content": "fix the CI"}),
        dict(base, type="assistant", timestamp=at(3),
             message={"content": [{"type": "text", "text": "Fixed. Push it?"}]}),
        dict(base, type="user", timestamp=at(4),
             message={"content": [{"type": "tool_result", "content": "x"}]}),
        dict(base, type="user", timestamp=at(200), message={"content": "next: docs"}),
        dict(base, type="assistant", timestamp=at(205),
             message={"content": [{"type": "text", "text": "Docs done."}]})])
    write("s2.jsonl", [dict(base, entrypoint="sdk-cli", type="user", timestamp=at(1),
                            message={"content": "a runner step"})])
    got = briefagent.sessions(t0 - 1, claude_dir=str(tmp_path))
    assert len(got) == 1
    s = got[0]
    assert s["prompts"] == ["fix the CI", "next: docs"] and s["last_reply"] == "Docs done."
    assert s["minutes"] == 9                         # the 196-minute gap is not work
    assert briefagent.project_of("/w/proj/sub", [{"name": "p", "path": "/w/proj"},
                                                 {"name": "q", "path": "/w/pro"}]) == "p"


def test_git_state(tmp_path):
    import subprocess
    from work_packet import briefagent
    r = tmp_path / "repo"
    r.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(r)] + list(a), check=True,
                                    capture_output=True)
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "one")
    assert briefagent.git_state([str(tmp_path / "nothing")]) == []
    got = briefagent.git_state([str(tmp_path)])       # the repo one level down
    assert got and got[0]["unpushed"][0]["upstream"] is None    # a branch never pushed
    (r / "new.txt").write_text("x")
    s = briefagent.repo_state(str(r))
    assert s["uncommitted"] == 1 and s["files"] == ["new.txt"]


def test_agent_config():
    from work_packet import schema
    bad = [p.field for p in schema.validate_config(
        {"focus": {"agent": "yes", "model": "", "budget_usd": 0}}) if p.level == "error"]
    assert bad == ["focus.model", "focus.budget_usd", "focus.agent"]
    assert schema.validate_config({"focus": {"agent": False, "model": "opus",
                                             "budget_usd": 1, "sessions": True}}) == []


def test_answer_and_close_out_from_the_brief_page(fake, monkeypatch):
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "asker")
    ea, pa = _new("asking")
    scheduler.tick([ea], until_idle=True)
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "add_one")
    eb, pb = _new("finished")
    executor.admin(pb, "pause")
    brief.build(_home(), ask=lambda prompt, **kw: (_reply(
        decide=[{"project": "asking", "question": "Red or blue?", "recommend": "blue"}],
        close_out=[{"project": "finished", "action": "read the report, mark done"}],
        focus=[{"theme": "colours", "projects": ["asking"], "why": "w"}]), 0.0))
    c = _client()
    page = c.get("/brief").text
    assert 'action="/p/asking/%s/act"' % pa.wpid in page and 'name="a.q1"' in page
    assert "read the report, mark done" in page        # (a plain ask has no recommend)
    assert page.count("## Decide") == 0 and page.count(">Decide<") == 1   # drawn once, by the page
    assert "to decide" in c.get("/").text
    r = c.post("/p/asking/%s/act" % pa.wpid, data={"action": "answer", "a.q1": "blue",
                                                  "back": "/brief"}, follow_redirects=False)
    assert r.headers["location"].startswith("/brief"), r.headers
    assert pa.load_status()[0]["state"] != "NEEDS_INPUT"
    r = c.post("/p/finished/%s/act" % pb.wpid, data={"action": "done", "back": "/brief"},
               follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    page = c.get("/brief").text
    assert "No open question on the board now" in page and "(done)" in page


def test_proposed_runs_ticked_and_started(fake, monkeypatch):
    e, pkt = _new("ci-fix")
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["state"] == "COMPLETED"
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "asker")
    ea, pa = _new("asking")
    scheduler.tick([ea], until_idle=True)
    h = _home()
    b = brief.build(h, ask=lambda prompt, **kw: (_reply(runs=[
        {"project": "ci-fix", "title": "Push the fix", "instruction": "Push abc123.\nCheck CI.",
         "why": "main is red", "outward": True},
        {"project": "asking", "title": "no", "instruction": "it has a question"},  # Decide's
        {"project": "ghost", "title": "no", "instruction": "x"}]), 0.0))
    assert [r["project"] for r in b["agent"]["runs"]] == ["ci-fix"]
    assert b["agent"]["runs"][0]["instruction"] == "Push abc123.\nCheck CI."
    assert "## Proposed runs" in open(brief.path(h, b["day"], "md")).read()
    c = _client()
    page = c.get("/brief").text
    assert 'name="run" value="0"' in page and "Push abc123." in page and "⇡" in page
    r = c.post("/brief/run", data={"day": b["day"]}, follow_redirects=False)
    assert not _flash(r)[1]                                    # nothing ticked
    r = c.post("/brief/run", data={"day": b["day"], "run": "0",
                                   "text.0": "Push abc123 to origin.\nCheck CI."},
               follow_redirects=False)
    assert _flash(r)[1] and "handed off: ci-fix" in _flash(r)[0], _flash(r)
    assert pkt.load_status()[0]["state"] == "RUNNABLE"
    rec = [x for x in pkt.journal().records if x.get("type") == "handoff"][-1]
    assert "Proposed by the focus brief" in str(rec)
    run = brief.load(h, b["day"])["agent"]["runs"][0]["launched"]
    assert run["edited"] and run["instruction"].startswith("Push abc123 to origin.")
    page = c.get("/brief").text
    assert "handed off" in page and "disabled" in page
    got = brief.launch(h, b["day"], {0: ""})
    assert got[0][1].msg == "already handed off"


def test_the_page_says_while_the_model_writes(fake, monkeypatch):
    """Rebuild (and the board's loop) save the scored brief at once and the model's in a
    thread; meanwhile the page shows a progress bar and reloads when it is in, and the model's replaces it."""
    import threading
    from work_packet import briefagent
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "asker")
    ea, pa = _new("asking")
    scheduler.tick([ea], until_idle=True)
    go, asked = threading.Event(), threading.Event()

    def ask(prompt, **kw):
        asked.set()
        go.wait(10)
        return _reply(headline="The model's one."), 0.1
    monkeypatch.setattr(briefagent, "ask", ask)
    h = _home()
    b = brief.maybe_build(h, {"time": "00:00", "weekends": True})
    assert b and not b.get("agent")                  # the scored one, saved at once
    assert asked.wait(10) and brief.writing()
    assert not brief.build_soon(h)                   # one at a time
    page = _client().get("/brief").text
    assert "The model is writing today's brief" in page and "<progress" in page
    go.set()
    for _ in range(100):
        if brief.writing() is None:
            break
        time.sleep(0.05)
    assert brief.writing() is None
    assert brief.load(h, b["day"])["agent"]["headline"] == "The model's one."
    assert "The model is writing" not in _client().get("/brief").text
