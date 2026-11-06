"""Checkpoints (docs/session-checkpoint.md §3): where a packet stands after work
by hand, recorded as a step with worker ``session``, ``studio`` or ``scribe``."""

import json
import os

import pytest

from test_dash_tasks import _new
from work_packet import checkpoint, cli, executor, frontmatter
from work_packet.check import check

OUTLINE = """# Plan

- [x] 1 read the code
- [ ] 2 write the parser
  - [ ] 2a tokens
- [>] 3 tests
"""


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _stepped(name="a"):
    e, pkt = _new(name)
    assert executor.step(pkt.path).code == 0
    return e, pkt


def test_summary_text():
    t = checkpoint.summary_text("  parser\n half done ", "Tokens work.\n\nNext: old", "write tests")
    assert t == "parser half done\n\nTokens work.\n\nNext: write tests\n"
    assert checkpoint.next_of(t) == "write tests"
    assert checkpoint.summary_text("x") == "x\n"
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint.summary_text("  ")


def test_tick():
    new, got, missing = checkpoint.tick(OUTLINE, ["2a", "3", "1", "9"])
    assert "  - [x] 2a tokens" in new and "- [x] 3 tests" in new
    assert "- [ ] 2 write the parser" in new
    assert got == ["1", "2a", "3"] and missing == ["9"]


def test_memento_with():
    old = frontmatter.dump({"resume": "now", "ask": "which?", "item": "2", "size": "big"},
                           "Write the parser.\n")
    meta, body = frontmatter.parse(checkpoint.memento_with(old, "Write the tests."))
    assert meta == {"resume": "now", "size": "big"} and body == "Write the tests.\n"
    assert checkpoint.memento_with("Plain.\n", "Next.") == "Next.\n"


def test_a_checkpoint(tmp_path, fake):
    e, pkt = _stepped()
    with open(os.path.join(pkt.state_dir, "outline.md"), "w") as fp:
        fp.write(OUTLINE)
    before, _ = pkt.load_status()
    out, n = checkpoint.record(pkt, "Parser half done", body="Tokens work.",
                               next_action="Write the tests", ticks=["2a"], by="matt")
    assert out.code == 0 and n == 2
    meta, body = pkt.load_status()
    assert meta["step"] == 2 and meta["state"] == before["state"]
    assert body.splitlines()[0] == "Parser half done"
    assert checkpoint.next_of(body) == "Write the tests"
    # The memento is the next action, keeping resume; result.md is it.
    mm, mb = pkt.load_memento()
    assert mb.strip() == "Write the tests" and mm.get("resume")
    sd = pkt.step_dir(2)
    assert open(os.path.join(sd, "result.md")).read() == open(pkt.memento_path).read()
    # The tick, and its diff.
    assert "- [x] 2a tokens" in open(os.path.join(pkt.state_dir, "outline.md")).read()
    diff = open(os.path.join(sd, "state.diff")).read()
    assert "+++ b/state/outline.md" in diff and "+  - [x] 2a tokens" in diff
    m = json.load(open(os.path.join(sd, "meta.json")))
    assert m["worker"] == "session"
    assert m["checkpoint"] == {"by": "matt", "next": "Write the tests", "ticked": ["2a"]}
    assert checkpoint.last(pkt)["worker"] == "session"
    assert checkpoint.last_by_hand(pkt) is not None
    assert check(pkt.path).errors == []


def test_without_next_the_memento_stays(tmp_path, fake):
    e, pkt = _stepped()
    memento = open(pkt.memento_path).read()
    out, n = checkpoint.record(pkt, "Looked around")
    assert out.code == 0 and open(pkt.memento_path).read() == memento
    assert open(os.path.join(pkt.step_dir(n), "state.diff")).read() == ""


def test_the_scribe_never_moves_the_memento(tmp_path, fake):
    e, pkt = _stepped()
    memento = open(pkt.memento_path).read()
    out, n = checkpoint.record(pkt, "Drafted", next_action="Write the tests", worker="scribe")
    assert out.code == 0 and open(pkt.memento_path).read() == memento
    assert checkpoint.next_of(pkt.load_status()[1]) == "Write the tests"
    assert checkpoint.last_by_hand(pkt) is None


def test_the_scribe_drops_its_draft_after_one_by_hand(tmp_path, fake):
    e, pkt = _stepped()
    checkpoint.record(pkt, "By hand")
    t = checkpoint.last_by_hand(pkt)
    out, n = checkpoint.record(pkt, "Drafted", worker="scribe", after=t - 60)
    assert n is None and "dropped" in out.msg
    out, n = checkpoint.record(pkt, "Drafted", worker="scribe", after=t + 60)
    assert n == 3


def test_missing_ticks_are_named(tmp_path, fake):
    e, pkt = _stepped()
    with open(os.path.join(pkt.state_dir, "outline.md"), "w") as fp:
        fp.write(OUTLINE)
    out, n = checkpoint.record(pkt, "x", ticks=["7"])
    assert out.code == 0 and "not in the outline: 7" in out.msg


def test_while_a_step_runs_it_is_a_note(tmp_path, fake):
    """docs/collaboration.md §5.5: no lease, no status change; the step sees a note."""
    from work_packet import notes
    from work_packet.lease import Lease
    e, pkt = _stepped()
    before = pkt.load_status()
    lease = Lease(pkt.lease_path, 2, 1, 60).acquire()
    try:
        out, n = checkpoint.record(pkt, "parser half done", next_action="write tests",
                                   by="alice@h")
        assert out.code == executor.OK and n is None and "left as a note" in out.msg
        assert pkt.load_status() == before
        [note] = notes.queued(pkt)
        assert "alice's checkpoint" in note["text"] and "Next: write tests" in note["text"]
        rec = pkt.journal().records[-1]
        assert rec["type"] == "note" and "parser half done" in rec["msg"]
        out, n = checkpoint.record(pkt, "x", worker="scribe")        # the scribe: refused
        assert out.code == executor.LEASED and n is None
    finally:
        lease.release()


def test_the_command(tmp_path, fake, monkeypatch, capsys):
    e, pkt = _stepped()
    monkeypatch.setenv("WPK_WPID", pkt.wpid)
    body = tmp_path / "body.md"
    body.write_text("What changed.\n")
    assert cli.main(["checkpoint", "-m", "Half done", "--body", str(body),
                     "--next", "Finish it"]) == 0
    _, b = pkt.load_status()
    assert b.startswith("Half done\n\nWhat changed.") and "Next: Finish it" in b
    monkeypatch.delenv("WPK_WPID")
    assert cli.main(["checkpoint", "-m", "x"]) != 0
    assert "which packet" in capsys.readouterr().err


# --- the dash (docs/session-checkpoint.md §5) ----------------------------------------

def test_the_card_says_where_it_stands(tmp_path, fake):
    from test_dash_tasks import _client
    from work_packet import clock, ide_sessions, registry
    e, pkt = _stepped()
    checkpoint.record(pkt, "Parser half done", next_action="Write the tests")
    c = _client()
    html = c.get("/b/main").text
    assert '<div class="stat" title="Parser half done">' in html
    assert "Next: Write the tests" in html and 'class="asof">as of ' in html
    assert "session active" not in html
    # A session of the packet worked after the checkpoint: the card says so.
    now = clock.now().timestamp()
    ide_sessions.write(registry.home(), {
        "harness": "claude", "session_id": "abcdef12-3456", "attribution": "confirmed",
        "project": "a", "wpid": pkt.wpid, "live": False, "last_activity_t": now + 5,
        "last_work_t": now + 5, "edit_ts": [now - 3600, now + 1, now + 5]})
    html = c.get("/b/main").text
    assert "session active" in html and "2 edits since" in html


def test_the_memento_is_next_while_the_runner_has_it(tmp_path, fake):
    from work_packet.dash import data
    from work_packet import registry
    e, pkt = _stepped()
    meta, _ = pkt.load_status()
    _, mb = pkt.load_memento()
    card = data.card(registry.get("a"))
    want = mb.strip().splitlines()[0] if meta["state"] in ("RUNNABLE", "SLEEPING") else None
    assert card["intent"] == want


def test_update_status_on_the_packet_page(tmp_path, fake):
    from test_dash_tasks import _client
    e, pkt = _stepped()
    c = _client()
    html = c.get("/p/a/" + pkt.wpid).text
    assert 'id="checkpoint"' in html and 'value="checkpoint"' in html
    r = c.post("/p/a/%s/act" % pkt.wpid, data={"action": "checkpoint", "status": "Reviewed",
                                               "next": "Merge it", "body": "Looks fine."},
               follow_redirects=False)
    assert r.status_code == 303
    _, body = pkt.load_status()
    assert body.startswith("Reviewed\n\nLooks fine.") and "Next: Merge it" in body
    assert pkt.load_memento()[1].strip() == "Merge it"
    html = c.get("/p/a/" + pkt.wpid).text
    assert 'value="Reviewed"' in html and 'value="Merge it"' in html
    r = c.post("/p/a/%s/act" % pkt.wpid, data={"action": "checkpoint", "status": " "},
               follow_redirects=False)
    assert "status+line" in r.headers["location"]


def test_sessions_count_their_work():
    from work_packet import ide_sessions as s
    st = s.new_state("claude")

    def said(tool, ts):
        s.claude_feed(st, {"type": "assistant", "sessionId": "abcdef12-3456", "timestamp": ts,
                           "message": {"content": [{"type": "tool_use", "name": tool}]}})
    said("Read", "2026-11-06T10:00:00Z")
    assert st["last_work_t"] is None and st["edit_ts"] == []
    said("Edit", "2026-11-06T10:01:00Z")
    said("Bash", "2026-11-06T10:02:00Z")
    assert st["counts"] == {s.READ: 1, s.EDIT: 1, s.SHELL: 1}
    assert len(st["edit_ts"]) == 1 and st["last_work_t"] == s.epoch("2026-11-06T10:02:00Z")
    rec = s.clean({"harness": "claude", "session_id": "abcdef12-3456", "counts": st["counts"],
                   "edit_ts": st["edit_ts"], "last_work_t": st["last_work_t"]})
    assert rec["counts"] == st["counts"] and rec["edit_ts"] == st["edit_ts"]
