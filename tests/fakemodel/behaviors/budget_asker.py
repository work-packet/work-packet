"""Ask for a bigger step budget with ``sets``, then finish."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ASK = [
    {"id": "budget", "q": "Raise the step budget to $5, or split the item?",
     "recommend": "raise budget", "choices": ["raise budget", "split smaller"],
     "sets": {"raise budget": {"step_budget_usd": 5.0}}},
    {"id": "time", "q": "Allow 60m per step?", "recommend": "yes",
     "sets": {"step_timeout": "60m"}},
]


def run(prompt, fault, model):
    if "## Hand-off" in prompt:
        common.finish({"resume": "done"}, "", "Done.\n", fault)
        return "answered"
    common.finish({"resume": "now", "ask": ASK}, "Act on the answers.\n",
                  "Asked for a budget.\n", fault)
    return "asked"
