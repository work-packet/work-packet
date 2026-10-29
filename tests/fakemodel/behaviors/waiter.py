"""Spawn children a and b and sleep with the resume in state/period.md; a child
(its instruction says CHILD) finishes at once; a woken parent records the wake."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

CHILD = "CHILD: finish at once.\n"


def run(prompt, fault, model):
    if "CHILD: finish at once." in prompt:
        common.finish({"resume": "done"}, "", "Child done.\n", fault)
        return "child"
    if common.read("state/spawned.md"):
        common.write(".pending/state/woke.md", "woke\n")
        common.finish({"resume": "in 10 days"}, "Sleep.\n", "Woke.\n", fault)
        return "woke"
    common.write(".pending/state/spawned.md", "yes\n")
    period = (common.read("state/period.md", "wait children") or "").strip()
    common.finish({"resume": period, "spawn": [
        {"name": "a", "instruction": CHILD}, {"name": "b", "instruction": CHILD}]},
        "Wait for the children.\n", "Spawned a and b; %s.\n" % period, fault)
    return "spawned"
