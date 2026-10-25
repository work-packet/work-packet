"""Notes from a packet's owner, sent at any time (docs/interaction.md §6a).

A note waits in the packet's inbox, ``mailbox/<id>.json`` (the
``mailbox/`` reserved in spec §4), until a step that saw it commits. A step
sees it in its prompt, or mid-step from the PostToolUse hook
(``ctxhook.py``). Each attempt records what it saw in
``steps/NNNN/notes.seen``, one ``<id> <how> <time>`` line per note.
"""

import json
import os
import time

from . import fsutil
from .schema import format_timestamp

SEEN = "notes.seen"
TEXT_MAX = 8000


def inbox(pkt):
    return os.path.join(pkt.path, "mailbox")


def add(pkt, text, by):
    """Queue a note; returns it."""
    text = (text or "").strip()
    if not text:
        raise ValueError("the note is empty")
    if len(text) > TEXT_MAX:
        raise ValueError("the note is over %d characters" % TEXT_MAX)
    from . import clock
    now = clock.now()
    # The id sorts by time; the nanosecond counter orders notes sent within a second.
    note = {"id": "%s-%x" % (now.strftime("%Y%m%dT%H%M%S"), time.time_ns()),
            "t": format_timestamp(now), "by": by, "text": text}
    d = inbox(pkt)
    os.makedirs(d, exist_ok=True)
    fsutil.atomic_write(os.path.join(d, note["id"] + ".json"), json.dumps(note) + "\n")
    return note


def queued(pkt):
    """The notes in the inbox, oldest first."""
    return read_inbox(inbox(pkt))


def read_inbox(d):
    out = []
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as fp:
                note = json.load(fp)
        except (OSError, ValueError):
            continue
        if isinstance(note, dict) and isinstance(note.get("text"), str):
            note.setdefault("id", n[:-5])
            out.append(note)
    return out


def seen(sd):
    """{id: (how, time)} from a step folder's ``notes.seen``; the first line wins."""
    out = {}
    try:
        with open(os.path.join(sd, SEEN), encoding="utf-8") as fp:
            for line in fp:
                f = line.split()
                if len(f) >= 2 and f[0] not in out:
                    out[f[0]] = (f[1], f[2] if len(f) > 2 else None)
    except OSError:
        pass
    return out


def mark(sd, notes, how, t):
    with open(os.path.join(sd, SEEN), "a", encoding="utf-8") as fp:
        for n in notes:
            fp.write("%s %s %s\n" % (n["id"], how, t))


def section(notes):
    """The step prompt's "Notes from the owner", or ""."""
    if not notes:
        return ""
    out = ["## Notes from the owner", "",
           "Sent while the task was running. They take precedence over the instruction "
           "below where they differ. Record anything that should last (in `env.md` or the "
           "outline), since a note is shown only until a step that saw it commits.", ""]
    for n in notes:
        out.append("- %s, %s:" % (n.get("by") or "the owner", n.get("t") or ""))
        out += ["  " + ln if ln else "" for ln in n["text"].splitlines()]
    return "\n".join(out) + "\n\n"


def of_step(sd, pkt, records=()):
    """The notes a step folder saw: [{id, how, at, by, t, text}]. The text comes
    from the inbox or, once committed, from the ``commit-begin`` decision."""
    s = seen(sd)
    if not s:
        return []
    known = {n["id"]: n for n in queued(pkt)}
    for r in records:
        if isinstance(r, dict) and r.get("type") == "commit-begin":
            for n in (r.get("decision") or {}).get("notes") or ():
                if isinstance(n, dict) and n.get("id"):
                    known.setdefault(n["id"], n)
    out = []
    for i, (how, at) in s.items():
        n = known.get(i, {})
        out.append({"id": i, "how": how, "at": at, "by": n.get("by"), "t": n.get("t"),
                    "text": n.get("text")})
    return out


def committed(sd, pkt):
    """The notes to record at commit: those the step saw that are still queued."""
    s = seen(sd)
    return [dict(n, how=s[n["id"]][0]) for n in queued(pkt) if n["id"] in s]


def consume(pkt, ids):
    for i in ids:
        try:
            os.unlink(os.path.join(inbox(pkt), i + ".json"))
        except OSError:
            pass
