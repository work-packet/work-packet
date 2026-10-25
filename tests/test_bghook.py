"""bghook.py: background Bash calls are refused."""

import json
import subprocess
import sys

from work_packet import bghook
from work_packet.harness import claude


def run(event):
    return subprocess.run([sys.executable, claude.BGHOOK], input=json.dumps(event),
                          capture_output=True, text=True)


def test_background_bash_is_blocked():
    p = run({"tool_name": "Bash", "tool_input": {"command": "make", "run_in_background": True}})
    assert p.returncode == 2 and "background tasks are not available" in p.stderr


def test_foreground_and_junk_pass():
    assert run({"tool_name": "Bash", "tool_input": {"command": "make"}}).returncode == 0
    assert subprocess.run([sys.executable, claude.BGHOOK], input="not json",
                          capture_output=True, text=True).returncode == 0
    assert not bghook.blocked(None)


def test_settings_always_carry_the_guard():
    hooks = json.loads(claude.hook_settings(0, None))["hooks"]
    assert list(hooks) == ["PreToolUse"] and hooks["PreToolUse"][0]["matcher"] == "Bash"
    assert set(json.loads(claude.hook_settings(1000, "/m"))["hooks"]) == {"PreToolUse", "PostToolUse"}
