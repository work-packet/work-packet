"""One step that writes state/plan.md and finishes with a completion report.

``WPK_FAKE_REPORT_PATHS``: the deliverables it lists, comma-separated
(default ``state/plan.md``). ``WPK_FAKE_OUTLINE``: written as
state/outline.md, ``\n`` for newlines. The fault ``no-report`` leaves the report out.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def run(prompt, fault, model):
    common.write(".pending/state/plan.md", "# Plan\n\nTwo phases.\n")
    if os.environ.get("WPK_FAKE_OUTLINE"):
        common.write(".pending/state/outline.md",
                     os.environ["WPK_FAKE_OUTLINE"].replace("\\n", "\n") + "\n")
    paths = os.environ.get("WPK_FAKE_REPORT_PATHS", "state/plan.md").split(",")
    common.finish({"resume": "done"}, "", "Polished the plan; done.\n", "no-report")
    if fault != "no-report":
        text = common.report("Chose a two-phase rollout.", [(p, "the plan") for p in paths if p])
        common.write(".pending/report.md", text.replace(
            "## Decisions\nnone", "## Decisions\n- Two phases, because the cutover is risky."))
    return "reported"
