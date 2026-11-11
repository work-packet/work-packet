"""``python -m work_packet.hookcmd``: Claude Code's hook events in a packet folder
(docs/collaboration.md §4.3), replayed from sanitized real payloads
(``tests/data/hooks``, docs/collaboration-spike.md)."""

import io
import json
import os
import subprocess

import pytest

from work_packet import hookcmd, presence, schema, sessionhooks
from work_packet.check import check
from work_packet.packet import Packet

from test_packet_layout import new_here
from test_setup import git, home, source                       # noqa: F401

DATA = os.path.join(os.path.dirname(__file__), "data", "hooks")
SID = "00000000-0000-4000-8000-000000000001"


def payload(name, folder):
    d = json.load(open(os.path.join(DATA, name + ".json")))
    d["cwd"] = str(folder)
    d["transcript_path"] = d["transcript_path"].replace("@HOME@", "/nowhere")
    return d


def fire(name, folder, env=None, event=None):
    d = payload(name, folder)
    event = event or d["hook_event_name"]
    env = dict(env or {}, CLAUDE_CODE_ENTRYPOINT="claude-vscode", CLAUDE_PID="4242")
    assert hookcmd.main([event], io.StringIO(json.dumps(d)), env) == 0


@pytest.fixture
def pkt(home, source):
    plan = new_here(source)
    return source, plan.path, Packet(os.path.join(plan.path, "runs", plan.root))


def _rec(proj):
    return presence.get(proj, "claude-" + SID)


def test_a_session_from_start_to_end(pkt):
    folder, proj, root = pkt
    fire("SessionStart", folder)
    r = _rec(proj)
    assert r["turn"] == "waiting" and r["via"] == "ide-desktop" and r["pid"] == 4242
    assert r["wpid"] == root.wpid and r["session"] == SID
    fire("UserPromptSubmit", folder)
    assert _rec(proj)["turn"] == "working"
    fire("PermissionRequest", folder)
    r = _rec(proj)
    assert r["turn"] == "blocked" and r["tool"] == "Bash"
    fire("Notification-permission_prompt", folder)
    assert _rec(proj)["turn"] == "blocked"
    fire("PreToolUse", folder, event="PostToolUse")           # approved: it works again
    r = _rec(proj)
    assert r["turn"] == "working" and r["tool"] == ""
    fire("Stop", folder)
    assert _rec(proj)["turn"] == "waiting"
    fire("Notification-idle_prompt", folder)
    assert _rec(proj).get("idle_since")
    assert presence.attended(proj)[0]
    fire("SessionEnd", folder)
    assert not presence.attended(proj)[0]
    recs = [r for r in root.journal().records if r["type"].startswith("session-")]
    assert [r["type"] for r in recs] == ["session-start", "session-end"]
    for r in recs:
        assert schema.validate_journal_record(r) == []
        assert r["actor"] == {"kind": "claude", "via": "ide-desktop", "session": SID}
    assert check(proj).issues == []


def test_background_agents_are_not_your_turn(pkt):
    """A turn that ends with subagents still running (Claude's Stop names them in
    ``background_tasks``) is still work: not "waiting for you", even when the
    prompt has been idle a minute. The turn it takes when they finish ends in a
    Stop with none left, and then it waits for you."""
    folder, proj, _ = pkt
    fire("SessionStart", folder)
    fire("UserPromptSubmit", folder)
    d = payload("Stop", folder)
    d["background_tasks"] = [
        {"id": "a1", "type": "subagent", "status": "running", "agent_type": "general-purpose",
         "description": "SENTINEL-TASK do not store"},
        {"id": "a2", "type": "subagent", "status": "running"},
        {"id": "a3", "type": "subagent", "status": "completed"}]
    env = {"CLAUDE_CODE_ENTRYPOINT": "claude-vscode"}
    assert hookcmd.main(["Stop"], io.StringIO(json.dumps(d)), env) == 0
    r = _rec(proj)
    assert r["turn"] == "working" and r["background"] == "2 background agents"
    assert "SENTINEL" not in open(presence.path(proj, "claude-" + SID)).read()
    fire("PreToolUse", folder, event="PostToolUse")          # a subagent's tool
    fire("Notification-idle_prompt", folder)
    r = _rec(proj)
    assert r["turn"] == "working" and not r.get("idle_since")
    fire("Stop", folder)                                      # none left
    r = _rec(proj)
    assert r["turn"] == "waiting" and r["background"] == ""
    fire("Notification-idle_prompt", folder)
    assert _rec(proj)["turn"] == "waiting" and _rec(proj).get("idle_since")
    assert hookcmd.background([{"type": "shell", "status": "running"},
                               {"type": "subagent", "status": "running"}]) \
        == "2 background tasks"


def test_nothing_said_reaches_a_file(pkt, tmp_path):
    folder, proj, root = pkt
    for name in sorted(os.listdir(DATA)):
        fire(name[:-5], folder)
    for base in (str(folder), os.environ["WPK_HOME"]):
        for dirpath, _, files in os.walk(base):
            if ".git" in dirpath.split(os.sep):
                continue
            for n in files:
                p = os.path.join(dirpath, n)
                try:
                    text = open(p, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                assert "SENTINEL" not in text, p


def test_where_it_runs():
    assert hookcmd.via({"CLAUDE_CODE_ENTRYPOINT": "claude-vscode", "WPK_IDE_LAUNCH": "L-1"}) \
        == "ide-web"
    assert hookcmd.via({"CLAUDE_CODE_ENTRYPOINT": "claude-vscode"}) == "ide-desktop"
    assert hookcmd.via({"CLAUDE_CODE_ENTRYPOINT": "cli"}) == "terminal"


def test_a_runner_step_is_left_alone(pkt):
    folder, proj, root = pkt
    fire("SessionStart", folder, env={"WPK_STEP": "3"})
    assert _rec(proj) is None


def test_outside_a_packet_and_bad_input(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    d = payload("SessionStart", tmp_path)
    assert hookcmd.main(["SessionStart"], io.StringIO(json.dumps(d)), {}) == 0
    assert hookcmd.main(["SessionStart"], io.StringIO("{ nope"), {}) == 0
    assert hookcmd.main(["Bogus"], io.StringIO("{}"), {}) == 0
    log = open(tmp_path / "home" / "logs" / "hook.log").read()
    assert "did not parse" in log and "unknown hook event" in log


def test_installed_hooks_run_it(pkt):
    """What Claude Code runs: the command the installer wrote, as a process."""
    folder, proj, root = pkt
    assert sessionhooks.status(str(folder)) == "installed"      # written when it was made
    hooks = json.load(open(os.path.join(folder, sessionhooks.REL)))["hooks"]
    cmd = hooks["SessionStart"][0]["hooks"][0]["command"]
    env = dict(os.environ, CLAUDE_CODE_ENTRYPOINT="cli")
    env.pop("WPK_STEP", None)
    subprocess.run(cmd, shell=True, input=json.dumps(payload("SessionStart", folder)),
                   text=True, env=env, check=True, timeout=30)
    assert _rec(proj)["via"] == "terminal"
