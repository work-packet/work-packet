"""Fault points for crash tests (stage1-plan §7).

``WPK_FAULT_AT=<point>`` makes the executor ``SIGKILL`` itself when it
reaches that point; ``<point>@<step>`` only at that step.
"""

import os
import signal

POINTS = ("after-model", "after-commit-begin", "mid-spawn", "after-state-swap-1",
          "after-state-swap-2", "after-memento", "after-status", "before-cleanup")

_step = None


def at_step(n):
    global _step
    _step = n


def point(name):
    want = os.environ.get("WPK_FAULT_AT")
    if not want:
        return
    pt, _, step = want.partition("@")
    if pt == name and (not step or (_step is not None and int(step) == _step)):
        os.kill(os.getpid(), signal.SIGKILL)
