"""The console's agent (docs/console.md, C2): echo the question.

``sleep`` in the question makes it wait 30 s first, to be cancelled;
``propose`` makes it propose two slash commands, one read-only.
"""

import os
import time


def run(prompt, fault, model):
    if "sleep" in prompt:
        time.sleep(30)
    if "propose" in prompt:
        return "It looks stuck. Here is its state:\n\n    /show\n\nTo stop it:\n`/pause`\n"
    return "You asked: %s [model %s, cwd %s]" % (prompt.strip(), model, os.getcwd())
