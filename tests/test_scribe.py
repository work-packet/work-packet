"""The scribe (docs/session-checkpoint.md §4.2): a status drafted from the end of a
session's transcript when it ends or goes idle, off until ``sessions_scribe``."""

import json
import os

import pytest

from test_dash_tasks import _new
from work_packet import checkpoint, clock, executor, ide_sessions, registry, scribe

REPLY = '{"status": "Grammar done", "body": "Wrote the rules.", "next": "Error recovery"}'
ON = {"sessions_scribe": True, "scribe_idle_s": 1800}


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _claude_lines(path):
    rows = [
        {"type": "user", "message": {"content": "Finish the grammar"}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Writing it now."},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/grammar.py",
                                                            "old_string": "SECRET"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "SECRET"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
    ]
    with open(path, "w") as fp:
        for r in rows:
            fp.write(json.dumps(r) + "\n")


def _session(pkt, tmp_path, sid="abcdef12-3456", live=False, work=60.0, active=None):
    """A stored record of a session of ``pkt``, ``work`` seconds after its last step."""
    t0 = checkpoint.last(pkt)["t"]
    path = str(tmp_path / ("%s.jsonl" % sid))
    _claude_lines(path)
    h = registry.home()
    ide_sessions._save_cur(h, "claude", sid, {"files": {path: {}}})
    ide_sessions.write(h, {"harness": "claude", "session_id": sid,
                           "attribution": ide_sessions.CONFIRMED, "project": "a",
                           "wpid": pkt.wpid, "live": live, "last_work_t": t0 + work,
                           "last_activity_t": t0 + (active if active is not None else work)})
    return t0 + work


def _stepped():
    e, pkt = _new("a")
    assert executor.step(pkt.path).code == 0
    return e, pkt


def test_tail_keeps_words_and_targets_not_output(tmp_path):
    p = tmp_path / "s.jsonl"
    _claude_lines(str(p))
    t = scribe.tail("claude", [str(p)])
    assert t.splitlines() == ["Person: Finish the grammar", "Agent: Writing it now.",
                              "(tool Edit src/grammar.py)", "Agent: Done."]
    assert "SECRET" not in t


def test_codex_tail(tmp_path):
    p = tmp_path / "r.jsonl"
    rows = [{"type": "event_msg", "payload": {"type": "user_message", "message": "Fix it"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell",
                                                  "arguments": json.dumps({"command": ["pytest", "-q"]})}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch",
                                                  "input": "*** Begin Patch\n*** Update File: a.py\n"}},
            {"type": "event_msg", "payload": {"type": "agent_message", "message": "Fixed."}}]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert scribe.tail("codex", [str(p)]).splitlines() == [
        "Person: Fix it", "(tool shell pytest -q)", "(tool apply_patch a.py)", "Agent: Fixed."]


def test_parse():
    assert scribe.parse("sure:\n" + REPLY) == {"status": "Grammar done", "body": "Wrote the rules.",
                                               "next": "Error recovery", "asked": ""}
    assert scribe.parse("no") is None and scribe.parse('{"status": ""}') is None


def test_off_until_turned_on(tmp_path, fake):
    e, pkt = _stepped()
    t = _session(pkt, tmp_path)
    assert scribe.pass_once(registry.home(), {}, now=t + 10, ask=lambda *a: (REPLY, 0.0)) == []
    assert pkt.load_status()[0]["step"] == 1


def test_an_ended_session_gets_a_status(tmp_path, fake):
    e, pkt = _stepped()
    memento = open(pkt.memento_path).read()
    t = _session(pkt, tmp_path)
    prompts = []

    def ask(prompt, home):
        prompts.append(prompt)
        return REPLY, 0.002
    got = scribe.pass_once(registry.home(), ON, now=t + 10, ask=ask, wait=True)
    assert len(got) == 1 and "(tool Edit src/grammar.py)" in prompts[0]
    meta, body = pkt.load_status()
    assert meta["step"] == 2 and body.startswith("Grammar done\n\nWrote the rules.")
    assert checkpoint.next_of(body) == "Error recovery"
    assert open(pkt.memento_path).read() == memento         # D1: never the scribe
    m = json.load(open(os.path.join(pkt.step_dir(2), "meta.json")))
    assert m["worker"] == "scribe" and m["cost_usd"] == 0.002
    # Once: claimed, and the step is newer than the work now.
    assert scribe.pass_once(registry.home(), ON, now=t + 20, ask=ask, wait=True) == []


def test_a_live_session_waits_until_idle(tmp_path, fake):
    e, pkt = _stepped()
    t = _session(pkt, tmp_path, live=True)
    assert scribe.due(registry.home(), t + 60, ON) == []
    assert len(scribe.due(registry.home(), t + 1801, ON)) == 1


def test_no_draft_when_nothing_changed_since(tmp_path, fake):
    e, pkt = _stepped()
    t = _session(pkt, tmp_path, work=-60.0, active=60.0)    # its work was before the step
    assert scribe.due(registry.home(), t + 3600, ON) == []


def test_a_checkpoint_by_hand_wins(tmp_path, fake, monkeypatch):
    e, pkt = _stepped()
    t = _session(pkt, tmp_path)
    r = scribe.due(registry.home(), t + 10, ON)[0]

    def ask(prompt, home):          # the person records one while the model drafts
        checkpoint.record(pkt, "By hand")
        return REPLY, 0.0
    monkeypatch.setattr(checkpoint, "last_by_hand", lambda p: t + 5)
    assert scribe.scribe(registry.home(), r, ask) is None
    assert pkt.load_status()[1].startswith("By hand")


def test_draft_from_session_on_the_packet_page(tmp_path, fake, monkeypatch):
    from test_dash_tasks import _client
    e, pkt = _stepped()
    c = _client()
    r = c.post("/p/a/%s/checkpoint/draft" % pkt.wpid)
    assert "no session" in r.json()["error"]
    _session(pkt, tmp_path)
    monkeypatch.setattr(scribe, "ask_model", lambda prompt, home: (REPLY, 0.0))
    assert 'id="cp-draft"' in c.get("/p/a/" + pkt.wpid).text
    r = c.post("/p/a/%s/checkpoint/draft" % pkt.wpid)
    assert r.json() == {"status": "Grammar done", "body": "Wrote the rules.",
                        "next": "Error recovery", "asked": ""}
    assert pkt.load_status()[0]["step"] == 1                 # nothing recorded


def test_the_boards_switch(tmp_path, fake):
    from test_dash_tasks import _client
    h = registry.home()
    assert not scribe.enabled(h, {}) and scribe.enabled(h, {"sessions_scribe": True})
    e, pkt = _stepped()
    _session(pkt, tmp_path)
    c = _client()
    html = c.get("/p/a/" + pkt.wpid).text
    assert "Status drafts when a session ends: <strong>off</strong>" in html
    r = c.post("/sessions/scribe", data={"on": "1", "back": "/p/a/%s" % pkt.wpid},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/p/a/")
    assert scribe.enabled(h, {})                        # the switch beats config.toml
    html = c.get("/p/a/" + pkt.wpid).text
    assert "<strong>on</strong>" in html
    c.post("/sessions/scribe", data={"on": "0"}, follow_redirects=False)
    assert not scribe.enabled(h, {"sessions_scribe": True})


def test_a_question_left_open_in_a_session(fake):
    """The scribe keeps the question a session ended on; the focus brief's bundle
    carries it, and a later draft without one clears it."""
    import json
    from test_dash_tasks import _new
    from work_packet import briefagent, executor, registry
    e, pkt = _new("asks")
    executor.admin(pkt, "pause")
    assert scribe.parse('{"status": "s", "asked": "Ship it: yes or no?"}')["asked"] == \
        "Ship it: yes or no?"
    scribe.record_ask(pkt, "s1", "Ship it: yes or no?")
    scribe.record_ask(pkt, "s2", "")                       # nothing to keep, nothing written
    assert [a["q"] for a in scribe.open_asks(pkt)] == ["Ship it: yes or no?"]
    b = briefagent.gather(registry.home(), 0, 2e9)
    p = [x for x in b["packets"] if x["project"] == "asks"][0]
    assert p["session_questions"][0]["q"] == "Ship it: yes or no?"
    scribe.record_ask(pkt, "s1", "")                       # answered in the session
    assert scribe.open_asks(pkt) == []
    assert json.load(open(os.path.join(pkt.path, scribe.ASKS))) == {}
