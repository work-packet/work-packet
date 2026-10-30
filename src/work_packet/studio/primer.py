"""The studio agent's primer (docs/studio-plan.md S1.7): built for every turn.

The guide (``prompts/studio.md``), then what is true now: the packet and the
folder, the canvas (each artifact's kind and path), the other files of a
known kind, and the files the person changed since the agent's last turn.
Kept under ``BUDGET`` characters: long lists are cut with a count.
"""

import os

from .. import fsutil
from . import kinds

GUIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "prompts", "studio.md")
BUDGET = 12000
LIST_MAX = 40


def _cut(items, n=LIST_MAX):
    return items[:n], max(0, len(items) - n)


def build(entry, wpid, state, files=(), yours=(), memento=None, datasets=None):
    """The primer text. ``state``: ``model.state()``; ``files``: the folder's
    files (relative paths); ``yours``: the changes the person made since the
    agent's last turn ([{path, change}]); ``memento``: the packet's
    instruction, for context; ``datasets``: the kernel's ``datasets`` (the
    folder's tables with their columns), or None when not known."""
    try:
        out = [fsutil.read_text(GUIDE).rstrip(), ""]
    except OSError:
        out = []
    out += ["## This studio", "",
            "- Packet %s in project %s." % (wpid, entry["name"]),
            "- Your working folder (cwd): %s" % state["folder"], ""]
    if memento:
        text = memento.strip()
        out += ["## The packet's instruction", "", text[:2000] + (
            "\n…" if len(text) > 2000 else ""), ""]
    out += ["## The canvas", ""]
    if state["canvas"]:
        shown, more = _cut(state["canvas"])
        for a in shown:
            out.append("- %s (%s)%s" % (a["path"], a.get("kind") or "file",
                                         ", open" if a["path"] in state["layout"]["open"] else ""))
        if more:
            out.append("- … and %d more" % more)
    else:
        out.append("Nothing is pinned yet.")
    pinned = {a["path"] for a in state["canvas"]}
    known = sorted(f for f in files if f not in pinned and kinds.kind_of(f))
    if known:
        shown, more = _cut(known)
        out += ["", "Other files the canvas can show: " + ", ".join(shown) + (
            " and %d more" % more if more else "") + "."]
    if datasets:
        out += ["", "## Data", ""]
        shown, more = _cut(list(datasets), 20)
        for d in shown:
            head = d["path"] + (" (table %s)" % d["table"] if d.get("table") else "")
            if d.get("error"):
                out.append("- %s: %s" % (head, d["error"]))
                continue
            cols = ", ".join("%s %s" % (c["name"], c["type"].lower()) for c in d["columns"][:30])
            if len(d["columns"]) > 30:
                cols += ", … (%d columns)" % len(d["columns"])
            rows = " %s rows;" % d["rows"] if d.get("rows") is not None else ""
            out.append("- %s:%s %s" % (head, rows, cols))
        if more:
            out.append("- … and %d more" % more)
    out += ["", "## Changed by the person since your last turn", ""]
    if yours:
        shown, more = _cut(list(yours))
        for c in shown:
            out.append("- %s %s%s" % (c["path"], c["change"],
                                       " (from %s)" % c["from"] if c.get("from") else ""))
        if more:
            out.append("- … and %d more" % more)
    else:
        out.append("Nothing.")
    text = "\n".join(out) + "\n"
    if len(text) > BUDGET:
        text = text[:BUDGET - 40] + "\n… (the primer was cut to its budget)\n"
    return text
