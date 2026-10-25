"""PreToolUse hook: refuse a Bash call that asks to run in the background.

A step ends with the model's turn, so a background task's result never
reaches it: steps 16 and 17 of the dv-solve trial each started a check in
the background, ended the turn to wait for it and never wrote a memento
(docs/experiments/dvs-enh-steps.md). Exit status 2 blocks the call and
shows the message to the model.

Standalone on purpose, like ``ctxhook.py``. Any error lets the call through.
"""

import json
import sys

MSG = ("wpk: background tasks are not available in a step: the step ends with "
       "your turn, so a background task's result never reaches you. Run the "
       "command in the foreground with a timeout, sending long output to a "
       "file.")


def blocked(event):
    inp = event.get("tool_input") if isinstance(event, dict) else None
    return isinstance(inp, dict) and bool(inp.get("run_in_background"))


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    if blocked(event):
        sys.stderr.write(MSG + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
