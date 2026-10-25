"""Ask two structured questions, one of which grants Bash; then record the answers."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ASK = [
    {"id": "bash", "q": "Allow Bash for builds and tests?", "recommend": "yes",
     "grants": ["Bash"]},
    {"id": "cadence", "q": "One commit per item, or per sub-item?", "recommend": "per item",
     "choices": ["per item", "per sub-item"]},
]


def run(prompt, fault, model):
    if "## Hand-off" in prompt:
        part = prompt.split("## Hand-off", 1)[1].split("\n## ", 1)[0]
        common.write(".pending/state/answer.md", part.strip() + "\n")
        common.finish({"resume": "done"}, "", "Wrote the answers.\n", fault)
        return "answered"
    common.finish({"resume": "now", "ask": ASK}, "Act on the answers.\n",
                  "Asked two questions.\n", fault)
    return "asked"
