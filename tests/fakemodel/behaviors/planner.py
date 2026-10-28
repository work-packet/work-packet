"""Keeps a plan in state/outline.md and works through it, one change a step
(docs/plan-tree.md). ``WPK_FAKE_PAD`` adds that many bytes of notes to the
outline, so the prompt no longer shows it and the board must undo diffs."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

PLANS = [
    ("1", "- [>] 1 Survey the code\n- [ ] 2 Build it\n"),
    ("2", "- [x] 1 Survey the code\n- [>] 2 Build it; [ ] 2a parser; [ ] 2b page\n"),
    ("2a", "- [x] 1 Survey the code\n- [>] 2 Build it; [x] 2a parser; [>] 2b page\n"
           "  - checks: pytest\n"),
    ("2b", "- [x] 1 Survey the code\n- [x] 2 Build it; [x] 2a parser; [x] 2b page\n"
           "  - checks: pytest\n"),
]
NEXT = "- [x] 1 Second batch\n"


def run(prompt, fault, model):
    cur = common.read(".pending/state/outline.md")
    pad = int(os.environ.get("WPK_FAKE_PAD") or 0)
    tail = "\n## Notes\n\n" + "x" * pad + "\n" if pad else ""
    if "batch two" in common.instruction():
        common.write(".pending/state/outline.md", NEXT + tail)
        common.finish({"resume": "done", "item": "1"}, "", "Step (batch 2).\n", fault)
        return "batch 2"
    i = 0 if cur is None else 1 + next(k for k, (_, t) in enumerate(PLANS)
                                       if cur.startswith(t))
    item, text = PLANS[i]
    common.write(".pending/state/outline.md", text + tail)
    last = i == len(PLANS) - 1
    common.finish({"resume": "done" if last else "now", "item": item},
                  "" if last else "Go on.\n", "Step %d.\n" % (i + 1), fault)
    return "plan %d" % i
