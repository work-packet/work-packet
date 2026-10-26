"""Count like add_one, asking for ``size: sim`` for the step after each odd count
(docs/scheduler-plan.md T-c). ``WPK_FAKE_SIZE`` names another size."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

INSTRUCTION = "Read state/count.md (0 if missing), add one and write it back.\n"


def run(prompt, fault, model):
    raw = (common.read(".pending/state/count.md", "0") or "0").strip()
    count = int(raw or 0) + 1
    common.write(".pending/state/count.md", "%d\n" % count)
    common.write(".pending/state/prompt-%d.md" % count, prompt)
    meta = {"resume": "now" if count < 4 else "done"}
    if count % 2 == 1:
        meta["size"] = os.environ.get("WPK_FAKE_SIZE", "sim")
    common.finish(meta, INSTRUCTION if count < 4 else "", "Count is %d.\n" % count, fault)
    return "count %d" % count
