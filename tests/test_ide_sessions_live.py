"""Real harnesses under a stand-in editor (docs/vscode-monitor-plan.md §4.6).

Run with ``WPK_LIVE=1 pytest -m live tests/test_ide_sessions_live.py -s``. It
spends a few cents of haiku. Codex is skipped unless it can log in (``codex
login status``)."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

from work_packet import ide_launch
from work_packet import ide_sessions as s

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("WPK_LIVE") != "1", reason="WPK_LIVE=1")]

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, "fake_harness.py")
KEY = "0123456789ab"

# What the Claude extension runs: stream-json in and out, entrypoint claude-vscode.
CLAUDE = r'''
import json, subprocess, sys, time
p = subprocess.Popen(["claude", "-p", "--input-format", "stream-json", "--output-format",
                      "stream-json", "--verbose", "--model", "haiku"],
                     stdin=subprocess.PIPE, stdout=open(sys.argv[1], "w"),
                     env=dict(__import__("os").environ, CLAUDE_CODE_ENTRYPOINT="claude-vscode"))
p.stdin.write((json.dumps({"type": "user", "message": {"role": "user", "content":
               "Reply with exactly: SENTINEL-OK"}}) + "\n").encode())
p.stdin.flush()
while True:
    time.sleep(60)          # stdin stays open: the session stays live, as in the editor
'''


def _launch(tmp_path):
    home = str(tmp_path / "home")
    os.makedirs(ide_launch.server_dir(home, KEY))
    lid = ide_launch.start(home, KEY, str(tmp_path), "local", now=time.time() - 5)
    ide_launch.record_open(home, KEY, "p", "W1", "me")
    return home, lid


def _server(tmp_path, lid, children):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(children))
    return subprocess.Popen([sys.executable, FAKE, "server", str(spec)], cwd=str(tmp_path),
                            env=dict(os.environ, WPK_IDE_LAUNCH=lid, WPK_IDE_KEY=KEY),
                            start_new_session=True)


@pytest.mark.skipif(shutil.which("claude") is None, reason="no claude")
def test_a_real_claude_session_in_the_editor(tmp_path):
    home, lid = _launch(tmp_path)
    script = tmp_path / "ext.py"
    script.write_text(CLAUDE)
    out = tmp_path / "out.jsonl"
    srv = _server(tmp_path, lid, [{"argv": [sys.executable, str(script), str(out)]}])
    try:
        c = s.Collector(home, ide_launch.current(home, KEY), root=srv.pid)
        deadline, rec = time.time() + 120, None
        while time.time() < deadline:
            c.pass_once()
            recs = s.records(home)
            rec = recs[0] if recs else None
            if rec and rec.get("last_event") == s.TURN_END and rec.get("usage_reported"):
                break
            time.sleep(1)
        print(json.dumps(rec, indent=1))
        assert rec is not None and rec["attribution"] == "confirmed"
        assert rec["client"] == "vscode-ext" and rec["live"] is True
        assert rec["model"].startswith("claude-haiku") and s.total(rec["usage"]) > 0
        assert rec["project"] == "p" and rec["wpid"] == "W1"
        for root, _, files in os.walk(s.sessions_dir(home)):
            for f in files:
                assert b"SENTINEL" not in open(os.path.join(root, f), "rb").read()
    finally:
        os.killpg(srv.pid, signal.SIGTERM)
        srv.wait()


def _codex_ok():
    if shutil.which("codex") is None:
        return False
    p = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
    return p.returncode == 0 and "not logged in" not in (p.stdout + p.stderr).lower()


@pytest.mark.skipif(not _codex_ok(), reason="codex is not logged in here")
def test_a_real_codex_session_in_the_editor(tmp_path):
    home, lid = _launch(tmp_path)
    child = {"argv": ["bash", "-c", "codex exec --skip-git-repo-check "
                      "'Reply with exactly: SENTINEL-OK' </dev/null >/dev/null 2>&1; sleep 600"]}
    srv = _server(tmp_path, lid, [child])
    try:
        c = s.Collector(home, ide_launch.current(home, KEY), root=srv.pid)
        deadline, rec = time.time() + 180, None
        while time.time() < deadline:
            c.pass_once()
            recs = s.records(home)
            rec = recs[0] if recs else None
            if rec and rec.get("last_event") == s.TURN_END:
                break
            time.sleep(1)
        print(json.dumps(rec, indent=1))
        assert rec is not None and rec["attribution"] == "confirmed" and rec.get("model")
    finally:
        os.killpg(srv.pid, signal.SIGTERM)
        srv.wait()
