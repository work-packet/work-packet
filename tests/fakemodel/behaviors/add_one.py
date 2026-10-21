"""prototype/sub: add one to state/count.md until it is 8, then spawn hello.

A packet whose instruction mentions Hello World does the child's part
instead, so one behaviour runs the whole scenario (E1).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

INSTRUCTION = "Read state/count.md (0 if missing), add one and write it back.\n"
HELLO = 'Write "Hello World" to state/p.md, then finish.\n'


def run(prompt, fault, model):
    if "Hello World" in common.instruction():
        common.write(".pending/state/p.md", "Hello World\n")
        common.finish({"resume": "done"}, "", "Wrote Hello World to state/p.md.\n", fault)
        return "wrote p.md"
    raw = (common.read(".pending/state/count.md", "0") or "0").strip()
    count = int(raw or 0) + 1
    common.write(".pending/state/count.md", "%d\n" % count)
    if count < 8:
        common.finish({"resume": "now"}, INSTRUCTION,
                      "Count is %d (model %s); continuing.\n" % (count, model), fault)
    else:
        common.finish({"resume": "done", "spawn": [
            {"name": "hello", "instruction": HELLO}]}, "",
            "Count reached %d; spawned hello.\n" % count, fault)
    return "count %d" % count
