"""The ``wpk-checkpoint`` skill for Claude Code and Codex (docs/session-checkpoint.md §4.1).

A session in an editor the board opened for a packet (``WPK_WPID`` set) runs it to
record where the packet stands: the model already has the session's context, so
its status is the best one and costs no extra call. Installed for the user, in
``$CLAUDE_CONFIG_DIR/skills`` (else ``~/.claude/skills``) and ``$CODEX_HOME/skills``
(else ``~/.codex/skills``), when the board opens VS Code for a packet. A skill
someone edited (no longer carrying ``MARK``) is left alone.
"""

import os
import shlex
import shutil
import sys

from . import fsutil

NAME = "wpk-checkpoint"
MARK = "<!-- written by work-packet; edits are overwritten unless you delete this line -->"

SKILL = """---
name: wpk-checkpoint
description: Record where the current work packet stands (status, what changed, next action) so the wpk board shows it. Use when the user asks to checkpoint, save status or update the packet's status, and before ending a session that changed things in a packet.
---
{mark}

# Checkpoint the work packet

This session belongs to a work packet when the environment variable `WPK_WPID` is
set. Check it first (`echo "$WPK_WPID"`). If it is empty, say that this session is
not linked to a packet and stop.

1. **Status line**: where the work stands now, one line, at most about 80
   characters. Say what is true now, not what you did ("Parser done; error
   recovery half written", not "Worked on the parser").
2. **Body**: two to six short lines: what changed in this session, decisions
   made, open questions. Plain text.
3. **Next action**: one line, only if it is clear. It also becomes the
   instruction the packet's next autonomous step starts from, so leave it out
   when you are unsure.
4. **Plan items**: if the packet has `state/outline.md` (under `$WPK_PACKET`) and
   you finished items in it, note their ids (like `2a`).

Then record it, with the body on stdin:

```
{cmd} -m "<status line>" --next "<next action>" --tick <id> --body - <<'EOF'
<body>
EOF
```

Leave out `--next` and `--tick` when they do not apply. If it says a step is
running, tell the user to try again when that step ends. Tell the user the
status you recorded, in one line.
"""


def command():
    """How the skill runs ``wpk checkpoint``: ``wpk`` if it is on the PATH, else
    this Python's ``-m work_packet``."""
    if shutil.which("wpk"):
        return "wpk checkpoint"
    return "%s -m work_packet checkpoint" % shlex.quote(sys.executable)


def dirs(environ=None):
    """Where the skill goes: Claude Code's and Codex's user skill folders, or
    ``$WPK_SKILLS_DIRS`` (``os.pathsep``-separated; the tests set it)."""
    env = os.environ if environ is None else environ
    if env.get("WPK_SKILLS_DIRS"):
        return env["WPK_SKILLS_DIRS"].split(os.pathsep)
    home = os.path.expanduser("~")
    claude = env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    codex = env.get("CODEX_HOME") or os.path.join(home, ".codex")
    return [os.path.join(claude, "skills"), os.path.join(codex, "skills")]


def text():
    return SKILL.replace("{mark}", MARK).replace("{cmd}", command())


def install(environ=None):
    """Write or refresh the skill in each folder. Returns the paths written.
    Never raises: a skill is a convenience, the editor opens without it."""
    want, out = text(), []
    for d in dirs(environ):
        path = os.path.join(d, NAME, "SKILL.md")
        try:
            if os.path.isfile(path):
                old = fsutil.read_text(path)
                if old == want or MARK not in old:
                    continue                # current, or someone made it their own
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fsutil.atomic_write(path, want)
            out.append(path)
        except OSError:
            continue
    return out
