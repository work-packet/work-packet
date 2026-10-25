"""pathhook.py: Edit and Write of the executor's files are refused."""

import json
import subprocess
import sys

from work_packet import pathhook
from work_packet.harness import claude


def packet(tmp_path):
    (tmp_path / "journal.jsonl").write_text("")
    (tmp_path / ".pending" / "state").mkdir(parents=True)
    (tmp_path / "state").mkdir()
    return tmp_path


def run(event):
    return subprocess.run([sys.executable, claude.PATHHOOK], input=json.dumps(event),
                          capture_output=True, text=True)


def test_edit_of_state_is_blocked_with_the_pending_path(tmp_path):
    p = packet(tmp_path)
    r = run({"tool_name": "Edit", "cwd": str(p),
             "tool_input": {"file_path": str(p / "state" / "outline.md")}})
    assert r.returncode == 2
    assert "state/outline.md is committed" in r.stderr and ".pending/state/outline.md" in r.stderr


def test_new_file_and_relative_path_are_blocked(tmp_path):
    p = packet(tmp_path)
    m = pathhook.blocked({"tool_name": "Write", "cwd": str(p),
                          "tool_input": {"file_path": "state/notes/5a.md"}})
    assert ".pending/state/notes/5a.md" in m
    assert pathhook.blocked({"tool_name": "Write", "cwd": str(p),
                             "tool_input": {"file_path": "memento.md"}})


def test_pending_work_and_elsewhere_pass(tmp_path):
    p = packet(tmp_path)
    for f in (p / ".pending" / "state" / "outline.md", p / ".pending" / "memento.md",
              p / "work" / "repo" / "state" / "x.c", tmp_path.parent / "elsewhere.md"):
        assert pathhook.blocked({"tool_name": "Edit", "cwd": str(p),
                                 "tool_input": {"file_path": str(f)}}) is None
    assert pathhook.blocked({"tool_name": "Bash", "tool_input": {"command": "x"}}) is None
    assert pathhook.blocked(None) is None
    assert subprocess.run([sys.executable, claude.PATHHOOK], input="not json",
                          capture_output=True, text=True).returncode == 0


def test_settings_carry_the_path_guard():
    pre = json.loads(claude.hook_settings(0, None))["hooks"]["PreToolUse"]
    assert pre[1]["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert "pathhook.py" in pre[1]["hooks"][0]["command"]
