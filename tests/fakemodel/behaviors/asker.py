"""Ask a question, then act on the answer in the hand-off note (long-running.md §1).

Without a "## Hand-off" section in the prompt it asks which colour to use.
With one, it writes the hand-off section to state/answer.md and finishes.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

QUESTION = "Which colour: red or blue? I recommend blue."
AFTER = "Write the colour from the hand-off note to state/answer.md, then finish.\n"


def run(prompt, fault, model):
    if "## Hand-off" in prompt:
        part = prompt.split("## Hand-off", 1)[1].split("\n## ", 1)[0]
        common.write(".pending/state/answer.md", part.strip() + "\n")
        common.finish({"resume": "done"}, "", "Wrote the answer.\n", fault)
        return "answered"
    common.finish({"resume": "now", "ask": QUESTION}, AFTER, "Asked which colour.\n", fault)
    return "asked"
