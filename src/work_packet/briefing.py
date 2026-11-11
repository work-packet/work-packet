"""What a Claude session in a packet is told, by its hooks (docs/collaboration.md
§7.1, §7.2).

- ``briefing``: at SessionStart, a short orientation built from what the board
  already knows (the packet's name and brief, where it stands, what comes next,
  open questions, the runner's state), so every session starts oriented.
- ``new_notes``: on each prompt, the notes left for the packet (from the board,
  the phone, another project) that this session has not been shown yet. Each
  session sees a note once; the runner still gets it at its next step.

Read-only apart from ``mailbox/.seen``. Called from ``hookcmd``, so it stays cheap.
"""

import json
import os
import time

from . import frontmatter, layout, notes

MAX = 1500
SEEN = ".seen"


def _first(text, n=200):
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            return ln if len(ln) <= n else ln[:n - 1] + "…"
    return ""


def _next_of(body):
    for ln in (body or "").splitlines():
        if ln.startswith("Next:"):
            return ln[5:].strip()
    return ""


def briefing(proj, wpid, name=None):
    """The SessionStart text for a session in ``proj`` (at most ``MAX`` chars)."""
    from .packet import Packet
    pkt = Packet(os.path.join(layout.runs_dir(proj), wpid))
    try:
        meta, body = pkt.load_status()
    except (OSError, frontmatter.FrontMatterError):
        return ""
    name = name or meta.get("project") or ""
    brief = ""
    try:
        with open(os.path.join(proj, "prompt.md"), encoding="utf-8") as fp:
            brief = _first(fp.read())
    except OSError:
        pass
    if not brief:
        try:
            brief = _first(pkt.load_memento()[1])
        except (OSError, frontmatter.FrontMatterError):
            pass
    st = meta.get("state")
    runner = {"RUNNABLE": "queued for the runner (it waits while you work here)",
              "SLEEPING": "asleep until %s" % meta.get("wake_at"),
              "NEEDS_INPUT": "asking: %s" % (meta.get("reason") or "a question"),
              "PAUSED": "not with the runner (%s)" % (meta.get("reason") or "paused"),
              "COMPLETED": "the runner finished its last task",
              "FAILED": "the runner failed: %s" % (meta.get("reason") or "")}.get(st, st or "?")
    lines = ["You are working in the work packet **%s** (wpk; id %s)." % (name, wpid[:8])]
    if brief:
        lines.append("Brief: %s" % brief)
    where = _first(body)
    if where:
        lines.append("Where it stands (as of %s): %s" % (meta.get("updated") or "?", where))
    nxt = _next_of(body)
    if nxt:
        lines.append("Next: %s" % nxt)
    lines.append("Runner: %s." % runner)
    waiting = len(notes.read_inbox(notes.inbox(pkt)))
    if waiting:
        lines.append("%d note%s from the board will come with your next prompt." % (
            waiting, "" if waiting == 1 else "s"))
    try:                                    # the morning brief's one line (§9.4)
        from . import brief, registry
        focus = brief.focus_line(registry.home())
        if focus:
            lines.append(focus + ".")
    except Exception:                       # noqa: BLE001: a briefing never fails for it
        pass
    lines.append("When you have changed things, record where it stands with /wpk-checkpoint; "
                 "/wpk-handoff hands the next part to the runner.")
    out = "\n".join(lines)
    return out if len(out) <= MAX else out[:MAX - 1] + "…"


def _seen(pkt):
    p = os.path.join(notes.inbox(pkt), SEEN)
    out = set()
    try:
        with open(p, encoding="utf-8") as fp:
            for ln in fp:
                parts = ln.split()
                if len(parts) >= 2:
                    out.add((parts[0], parts[1]))
    except OSError:
        pass
    return out


def new_notes(proj, wpid, session, now=None):
    """The notes this session has not been shown, as one text (or ""); marks them
    shown to it in ``mailbox/.seen`` (``<id> session:<sid> <epoch>``)."""
    from .packet import Packet
    now = time.time() if now is None else now
    pkt = Packet(os.path.join(layout.runs_dir(proj), wpid))
    who = "session:%s" % session
    seen = _seen(pkt)
    fresh = [n for n in notes.queued(pkt) if (n["id"], who) not in seen]
    if not fresh:
        return ""
    d = notes.inbox(pkt)
    with open(os.path.join(d, SEEN), "a", encoding="utf-8") as fp:
        fp.write("".join("%s %s %d\n" % (n["id"], who, now) for n in fresh))
    out = ["Notes left for this packet on the wpk board (the runner gets them too):"]
    for n in fresh:
        out.append("- %s%s: %s" % (n.get("t") or "", " (%s)" % n["by"].split("@")[0]
                                    if n.get("by") else "", n["text"].strip()))
    return "\n".join(out)


def hook_output(event, text):
    """The JSON a hook prints to give the session ``text`` as added context."""
    return json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                              "additionalContext": text}})


BOARD_NOTES_LINES = 40


def dispatch_context(proj, wpid=None, take=True):
    """More for SessionStart, outside ``MAX`` (docs/agent-dispatch.md §4.2, §6.2):
    the kickoff a dispatch left for the first session (taken, so only one session
    gets it), and the notes for this packet's board and for you: the board's in
    full when short, else a pointer to `wpk context`."""
    from . import ide, registry
    out = []
    kick = ide.take_kickoff(proj) if take else None
    if kick and kick.strip():
        out.append("## Your task in this packet\n\nThe session that made this packet handed "
                   "it this to work on. Start on it with the user's first message (they may "
                   "just say go), unless that asks for something else:\n\n" + kick.strip())
    board = None
    try:
        e = next((x for x in registry.entries() if os.path.realpath(x["path"])
                  == os.path.realpath(proj)), None)
        board = registry.board_of(e) if e else None
    except Exception:                       # noqa: BLE001  notes are a nicety
        pass
    lines = []
    bn = registry.notes(board).strip() if board else ""
    if bn and bn.count("\n") < BOARD_NOTES_LINES:
        lines.append("## Board notes (%s)\n\n%s" % (board, bn))
    elif bn:
        lines.append("Board notes (%s): %d lines; `wpk context` shows them." % (
            board, bn.count("\n") + 1))
    gn = registry.notes(None).strip()
    if gn:
        lines.append("Your notes for agents: %d lines; `wpk context` shows them (and the "
                     "repos you named with [[repo]])." % (gn.count("\n") + 1))
    return "\n\n".join(out + lines)
