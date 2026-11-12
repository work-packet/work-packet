"""PreToolUse hook: refuse a Bash call that asks to run in the background, and
in a packet wpk delivers (``WPK_DELIVER`` set: docs/agent-dispatch.md §5.4), a
``git push``: wpk pushes the branch itself when the packet completes.

A step ends with the model's turn, so a background task's result never
reaches it: steps 16 and 17 of the dv-solve trial each started a check in
the background, ended the turn to wait for it and never wrote a memento
(docs/experiments/dvs-enh-steps.md). Exit status 2 blocks the call and
shows the message to the model.

Standalone on purpose, like ``ctxhook.py``. Any error lets the call through.
"""

import json
import os
import re
import sys

MSG = ("wpk: background tasks are not available in a step: the step ends with "
       "your turn, so a background task's result never reaches you. Run the "
       "command in the foreground with a timeout, sending long output to a "
       "file.")


PUSH_MSG = ("wpk: do not push from a step: wpk delivers this packet's branch itself "
            "when it completes ([deliver] %s). Commit your work on the branch you are on "
            "and carry on.")
# `git push`, `git -C dir push`, `git --no-pager push`: at the start of a command.
_PUSH = re.compile(r"(?:^|[;&|(`\n]|\$\()\s*(?:\S+=\S*\s+)*git"
                   r"(?:\s+(?:-[Cc]\s+\S+|--?[\w-]+(?:=\S+)?))*\s+push\b")


def blocked(event):
    inp = event.get("tool_input") if isinstance(event, dict) else None
    return isinstance(inp, dict) and bool(inp.get("run_in_background"))


def pushes(event):
    inp = event.get("tool_input") if isinstance(event, dict) else None
    cmd = inp.get("command") if isinstance(inp, dict) else None
    return isinstance(cmd, str) and bool(_PUSH.search(cmd))


def main(environ=None):
    env = os.environ if environ is None else environ
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    if blocked(event):
        sys.stderr.write(MSG + "\n")
        return 2
    if env.get("WPK_DELIVER") and pushes(event):
        sys.stderr.write(PUSH_MSG % env["WPK_DELIVER"] + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
