"""PreToolUse hook: refuse an Edit or Write of a file the executor owns.

A step may write only inside ``.pending/``; a change to ``state/`` or the
other committed files throws the whole step away (``executor._check``).
The protocol says so, yet steps 13, 22 and 28 of the dv-solve trial each
read ``state/outline.md`` or the like and then edited that same path, and
lost their work. Refusing the call at once, with the path to use instead,
lets the step carry on. Exit status 2 blocks the call and shows the message
to the model.

The packet is the nearest directory above the file that holds both
``journal.jsonl`` and ``.pending``. Bash writes are not checked.

The studio's agent (docs/studio-plan.md P0.3) works between steps, with no
``.pending/``: ``WPK_PROTECT`` lists (``os.pathsep``) what wpk keeps (the
``.work-packet`` directory, or a legacy project's ``packets/`` and
``project.toml``), and every edit under one is refused unless it is under
``WPK_PROTECT_ALLOW`` inside it (a child packet's ``work/``).

Standalone on purpose, like ``bghook.py``. Any error lets the call through.
"""

import json
import os
import sys

TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
OWNED = ("state", "status.md", "memento.md", "journal.jsonl", "children", "identity")

MSG = ("wpk: %s is committed and owned by the executor; changing it throws this "
       "step away. Make the change to %s instead (Read that copy first if you "
       "have not). Write only inside .pending/.")
STUDIO_MSG = ("wpk: %s is the run's record, kept by wpk; the studio does not change it. "
              "Write in the packet folder (%s) instead.")


def _under(p, root):
    root = os.path.normpath(root)
    return p == root or p.startswith(root + os.sep)


def _packet(path):
    d = os.path.dirname(path)
    while True:
        if (os.path.isfile(os.path.join(d, "journal.jsonl"))
                and os.path.isdir(os.path.join(d, ".pending"))):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def blocked(event):
    """The message refusing this call, or None."""
    if not isinstance(event, dict) or event.get("tool_name") not in TOOLS:
        return None
    inp = event.get("tool_input")
    p = isinstance(inp, dict) and (inp.get("file_path") or inp.get("notebook_path"))
    if not isinstance(p, str) or not p:
        return None
    p = os.path.normpath(os.path.join(event.get("cwd") or os.getcwd(), p))
    allow = os.environ.get("WPK_PROTECT_ALLOW")
    for guard in filter(None, (os.environ.get("WPK_PROTECT") or "").split(os.pathsep)):
        rp, rg = os.path.realpath(p), os.path.realpath(guard)
        ra = os.path.realpath(allow) if allow else None
        if _under(rp, rg) and not (ra and _under(ra, rg) and _under(rp, ra)):
            return STUDIO_MSG % (p, allow or event.get("cwd") or os.getcwd())
    pkt = _packet(p)
    if pkt is None:
        return None
    rel = os.path.relpath(p, pkt)
    if rel.split(os.sep)[0] not in OWNED:
        return None
    return MSG % (rel, os.path.join(".pending", rel))


def main():
    try:
        msg = blocked(json.load(sys.stdin))
    except Exception:
        return 0
    if msg:
        sys.stderr.write(msg + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
