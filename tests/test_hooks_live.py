"""Live: a real Claude Code session in a packet folder reports to the board through
the hooks the board installed (docs/collaboration.md §4.3, plan C2).

    WPK_LIVE=1 pytest -m live -s tests/test_hooks_live.py

Plumbing only, so the cheapest model will do. A permission prompt needs an
interactive session: that is the manual check in docs/collaboration-plan.md §4.6.
"""

import os
import shutil
import subprocess

import pytest

from work_packet import presence, sessionhooks
from work_packet.packet import Packet

from test_packet_layout import new_here
from test_setup import git, home, source                       # noqa: F401

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("WPK_LIVE") != "1", reason="set WPK_LIVE=1"),
    pytest.mark.skipif(shutil.which("claude") is None, reason="no claude on PATH"),
]


def test_a_real_session_reports_its_turns(home, source):
    plan = new_here(source)
    root = Packet(os.path.join(plan.path, "runs", plan.root))
    assert sessionhooks.status(str(source)) == "installed"
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "WPK_STEP"))}
    r = subprocess.run(["claude", "-p", "--model", "haiku", "Reply with the word ok."],
                       cwd=str(source), env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    assert os.listdir(os.path.join(plan.path, "presence")), "no presence record: no hooks ran"
    kinds = [x["type"] for x in root.journal().records if x["type"].startswith("session-")]
    assert kinds == ["session-start", "session-end"], kinds
    assert presence.records(plan.path, ttl=None) == []          # ended with the session


def test_a_real_session_is_briefed_and_gets_notes(home, source):
    from work_packet import notes
    plan = new_here(source)
    root = Packet(os.path.join(plan.path, "runs", plan.root))
    notes.add(root, "The magic word for this packet is PERIWINKLE.", "board")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "WPK_STEP"))}
    r = subprocess.run(["claude", "-p", "--model", "haiku",
                        "Without using any tools: what is the name of the work packet you "
                        "are in, and what is the magic word in the note from the board? "
                        "Answer in one line."],
                       cwd=str(source), env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    assert "sr" in r.stdout and "PERIWINKLE" in r.stdout.upper(), r.stdout
