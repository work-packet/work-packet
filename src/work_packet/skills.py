"""The ``wpk-*`` skills for Claude Code and Codex: ``wpk-checkpoint``
(docs/session-checkpoint.md §4.1), ``wpk-handoff``, ``wpk-note`` and ``wpk-done``
(docs/collaboration.md §11).

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

Run it in the packet's folder (or anywhere under it): it finds the packet from
there, or from `$WPK_WPID` when that is set. If it says it cannot tell which
packet, say that this session is not in a work packet and stop.

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

Leave out `--next` and `--tick` when they do not apply. If a runner step is
running, it is left as a note that step sees. Tell the user the status you
recorded, in one line.
"""

# The other verbs a session needs (docs/collaboration.md §11): hand the next part to
# the runner, leave it a note, mark the packet done.
MORE = {
    "wpk-handoff": """---
name: wpk-handoff
description: Hand the next part of the current work packet to the wpk runner, which works on it on its own. Use when the user says to hand off, give it to the runner, or let the runner do the rest.
---
{mark}

# Hand off to the runner

Run these in the packet's folder. First check where it stands with `{wpk} show .`.

1. Write the instruction: what the runner should do next, in a few lines, as for
   a colleague who has not seen this session: the goal, what is done, what is
   left, where things are. If you have not recorded where it stands yet, run
   /wpk-checkpoint first.
2. If the state is COMPLETED (the runner finished its last task):
   `{wpk} next . -m "<instruction>"`. Otherwise: `{wpk} handoff . -m "<instruction>"`.
   Add `--after-me` to `handoff` when the user wants it to start only once they
   stop working on it (otherwise it starts now, beside them).
3. Tell the user, in one line, what you handed off.

If it refuses because of uncommitted changes or missing setup, say what it said
and ask the user what to do; do not force it.
""",
    "wpk-note": """---
name: wpk-note
description: Leave a note for the wpk runner working on the current work packet; it reaches the running step or the next one. Use when the user wants to tell the runner something without stopping it.
---
{mark}

# Leave the runner a note

In the packet's folder: `{wpk} note . -m "<note>"`. Keep it to what the runner
needs to know or do differently. Tell the user it was sent.
""",
    "wpk-todo": """---
name: wpk-todo
description: Capture a to-do into the wpk board's Inbox, linked to the current work packet, without stopping what you are doing. Use when the user says to note something for later, or you find a follow-up worth its own packet.
---
{mark}

# Capture a to-do

`{wpk} todo "<one line: what, and why it matters>"`, in the packet's folder (it
links the item to the packet). Don't start on it; tell the user it is captured.
""",
    "wpk-done": """---
name: wpk-done
description: Mark the current work packet done on the wpk board (it leaves the active views; it can be reopened). Use only when the user says the work is finished.
---
{mark}

# Mark the packet done

Only when the user says so. Record where it stands first (/wpk-checkpoint) if
this session changed things. Then, in the packet's folder:
`{wpk} done . -m "<one line: how it ended>"`. Tell the user it is marked done.
""",
}


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


def texts():
    """``{skill name: SKILL.md text}`` for every skill wpk installs."""
    wpk = command()[:-len(" checkpoint")]
    out = {NAME: text()}
    for name, t in MORE.items():
        out[name] = t.replace("{mark}", MARK).replace("{wpk}", wpk)
    return out


def install(environ=None):
    """Write or refresh the skills in each folder. Returns the paths written.
    Never raises: a skill is a convenience, the editor opens without it."""
    out = []
    for d in dirs(environ):
        for name, want in texts().items():
            path = os.path.join(d, name, "SKILL.md")
            try:
                if os.path.isfile(path):
                    old = fsutil.read_text(path)
                    if old == want or MARK not in old:
                        continue            # current, or someone made it their own
                os.makedirs(os.path.dirname(path), exist_ok=True)
                fsutil.atomic_write(path, want)
                out.append(path)
            except OSError:
                continue
    return out
