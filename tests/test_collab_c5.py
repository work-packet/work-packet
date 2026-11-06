"""Turnover both ways (docs/collaboration.md §5.5, §7.1-§7.3, W5): a session is told
about its packet, gets the board's notes, records a checkpoint even while a step
runs, and a runner step's conversation can be picked up by hand."""

import io
import json
import os

import pytest

from test_dash_tasks import _client, _new
from test_hookcmd import payload
from test_packet_layout import new_here
from test_setup import git, home, source                       # noqa: F401
from work_packet import briefing, checkpoint, cli, hookcmd, notes, scheduler
from work_packet.packet import Packet


@pytest.fixture
def pkt(home, source):
    plan = new_here(source)
    return source, plan.path, Packet(os.path.join(plan.path, "runs", plan.root))


def _say(name, folder, capsys, event=None, **env):
    d = payload(name, folder)
    env = dict(env, CLAUDE_CODE_ENTRYPOINT="claude-vscode")
    capsys.readouterr()
    assert hookcmd.main([event or d["hook_event_name"]], io.StringIO(json.dumps(d)), env) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


def test_a_session_is_told_about_its_packet(pkt, capsys):
    folder, proj, root = pkt
    checkpoint.record(root, "parser half done", next_action="write the tests", by="me")
    notes.add(root, "the node 3 failures are a known infra problem", "me@h")
    text = _say("SessionStart", folder, capsys)
    assert "**sr**" in text and "Count in state/count.md." in text
    assert "parser half done" in text and "Next: write the tests" in text
    assert "1 note from the board" in text and "/wpk-checkpoint" in text
    assert len(text) <= briefing.MAX


def test_notes_reach_each_session_once(pkt, capsys):
    folder, proj, root = pkt
    _say("SessionStart", folder, capsys)
    assert _say("UserPromptSubmit", folder, capsys) == ""
    notes.add(root, "use the uvm_info macro", "me@h")
    got = _say("UserPromptSubmit", folder, capsys)
    assert "use the uvm_info macro" in got and "(me)" in got
    assert _say("UserPromptSubmit", folder, capsys) == ""          # shown once
    assert [n["text"] for n in notes.queued(root)] == ["use the uvm_info macro"]   # runner too


def test_after_compaction_no_second_briefing(pkt, capsys):
    folder, proj, root = pkt
    d = payload("SessionStart", folder)
    d["source"] = "compact"
    capsys.readouterr()
    hookcmd.main(["SessionStart"], io.StringIO(json.dumps(d)), {"CLAUDE_CODE_ENTRYPOINT": "cli"})
    assert capsys.readouterr().out == ""


def test_the_cli_finds_the_packet_from_the_folder(pkt, monkeypatch, capsys):
    folder, proj, root = pkt
    monkeypatch.delenv("WPK_WPID", raising=False)
    (folder / "sub").mkdir()
    monkeypatch.chdir(folder / "sub")
    assert cli.main(["checkpoint", "-m", "from a subfolder"]) == 0
    assert root.load_status()[1].startswith("from a subfolder")
    assert cli.main(["note", ".", "-m", "hello"]) == 0
    assert [n["text"] for n in notes.queued(root)] == ["hello"]
    monkeypatch.chdir("/")
    assert cli.main(["checkpoint", "-m", "nowhere"]) != 0
    assert "which packet" in capsys.readouterr().err


def test_handoff_gives_a_packet_you_started_its_instruction(home, tmp_path, monkeypatch):
    from work_packet import project, setup
    monkeypatch.chdir(tmp_path)
    plan = project.new("m", None)                       # made without an instruction
    root = Packet(os.path.join(plan.path, "packets", plan.root))
    assert cli.main(["handoff", "m", "-m", "Count to three in state/count.md."]) == 0
    meta, _ = root.load_status()
    assert meta["state"] == "RUNNABLE"
    assert setup.instruction(setup.target("m"))[0].startswith("Count to three")


def test_continue_a_runner_step(fake, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    e, pkt = _new("a")
    scheduler.tick([e], until_idle=True)
    meta = json.load(open(os.path.join(pkt.path, "steps", "0001", "meta.json")))
    page = _client().get("/p/a/%s/0001" % pkt.wpid).text
    assert "Continue this conversation yourself" in page
    assert "claude --resume %s --fork-session" % meta["session_id"] in page
    assert "--permission-mode plan" in page


def test_desk_reply_to_a_waiting_session(fake, monkeypatch, tmp_path):
    import time
    from work_packet import presence
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WPK_NOW")
    e, pkt = _new("a")
    presence.beat(e["path"], "claude-s", time.time() - 2000, kind="claude", via="ide-web",
                  session="s", turn="waiting")
    c = _client()
    page = c.get("/").text
    assert ">YOUR TURN<" in page and 'form="reply-' in page
    r = c.post("/p/a/%s/act" % pkt.wpid, data={"action": "note", "note": "try seed 7",
                                               "back": "overview"}, follow_redirects=False)
    assert r.status_code == 303
    assert briefing.new_notes(e["path"], pkt.wpid, "s").endswith("try seed 7")
