"""Sleep for the period named in state/period.md, counting wakes (E4)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def run(prompt, fault, model):
    wakes = int((common.read(".pending/state/wakes.md", "0") or "0").strip()) + 1
    common.write(".pending/state/wakes.md", "%d\n" % wakes)
    period = (common.read("state/period.md", "in 10 days") or "").strip()
    common.finish({"resume": period}, "Count this wake, then sleep again.\n",
                  "Wake %d; sleeping %s.\n" % (wakes, period), fault)
    return "wake %d" % wakes
