"""A checkpoint: where a packet stands after work done by hand (docs/session-checkpoint.md).

A Claude or Codex session in VS Code, the studio, or the scribe that reads a
session's transcript when it ends, records what it did as the packet's next
step (``executor.record_step``), so the board's card says where things stand
whoever did the work. The summary is the status line, an optional body, and a
``Next:`` line when there is a next action.

The memento (what the next autonomous step starts from) changes only when a
person or their session names the next action (D1); the scribe's next action
goes in the summary only. ``tick`` marks items of ``state/outline.md`` done.
"""

import os
import re

from . import executor, frontmatter, fsutil, journal, schema
from .dash.plan import _BOX, _ID, _LIST, OUTLINE

WORKERS = ("session", "studio", "scribe")
BY_HAND = ("session", "studio")
NEXT = re.compile(r"^Next:[ \t]*(.+?)\s*$", re.M)


class CheckpointError(ValueError):
    pass


def summary_text(status, body=None, next_action=None):
    """The step's summary: the status line, the body, then ``Next: ...``."""
    status = " ".join((status or "").split())
    if not status:
        raise CheckpointError("a checkpoint needs a status line")
    parts = [status]
    body = (body or "").strip()
    if body:
        parts.append(NEXT.sub("", body).strip() if next_action else body)
    if next_action:
        parts.append("Next: " + " ".join(next_action.split()))
    return "\n\n".join(p for p in parts if p) + "\n"


def next_of(summary):
    """The ``Next:`` line of a summary, or None."""
    m = NEXT.search(summary or "")
    return m.group(1) if m else None


def tick(text, ids):
    """``text`` (an outline) with the items ``ids`` checked: (new text, ids ticked,
    ids not found). An item already done counts as ticked."""
    want = {i.strip().strip("*").rstrip(".:)") for i in ids if i.strip()}
    got = set()
    out = []
    for ln in (text or "").splitlines(keepends=True):
        li = _LIST.match(ln.rstrip("\n"))
        box = _BOX.match(li.group(2)) if li else None
        if box:
            m = _ID.match(box.group(2).strip())
            if m and m.group(2) in want:
                got.add(m.group(2))
                if box.group(1) not in "xX":
                    at = li.start(2) + 1          # the mark inside "[ ]"
                    ln = ln[:at] + "x" + ln[at + 1:]
        out.append(ln)
    return "".join(out), sorted(got), sorted(want - got)


def memento_with(text, next_action):
    """The memento with ``next_action`` as its instruction. Its ``resume`` and
    ``size`` stay; what was for the step that wrote it (``ask``, ``spawn``,
    ``item``, ``reason``) goes."""
    try:
        meta, _ = frontmatter.parse(text or "")
    except frontmatter.FrontMatterError:
        meta = None
    keep = {k: meta[k] for k in ("resume", "size") if meta and k in meta} if meta else None
    return frontmatter.dump(keep or None, next_action.strip() + "\n")


def last(pkt):
    """The packet's last step: ``{"step", "t", "worker"}`` (``t``, epoch seconds,
    when it committed), or None."""
    workers, out = {}, None
    for r in journal.read(pkt.journal_path).records:
        if r.get("type") == "step-start":
            workers[r.get("step")] = r.get("worker") or "model"
        elif r.get("type") == "commit-begin":
            out = {"step": r.get("step"), "t": _epoch(r.get("t")),
                   "worker": (r.get("decision") or {}).get("worker")
                   or workers.get(r.get("step")) or "model"}
    return out


def last_by_hand(pkt):
    """When the last checkpoint by a person or their session committed (epoch), or None."""
    t = None
    workers = {}
    for r in journal.read(pkt.journal_path).records:
        if r.get("type") == "step-start":
            workers[r.get("step")] = r.get("worker")
        elif r.get("type") == "commit-begin":
            w = (r.get("decision") or {}).get("worker") or workers.get(r.get("step"))
            if w in BY_HAND:
                t = _epoch(r.get("t"))
    return t


def _epoch(s):
    try:
        return schema.parse_timestamp(s).timestamp()
    except (TypeError, ValueError, AttributeError):
        return None


def record(pkt, status, body=None, next_action=None, ticks=(), worker="session",
           by=None, meta=None, files=None, after=None):
    """Record a checkpoint as the packet's next step. ``after`` (epoch, the scribe's):
    record nothing if a checkpoint by hand committed since. Returns
    ``(executor.Outcome, step)``; the step is None when nothing was recorded."""
    if worker not in WORKERS:
        raise CheckpointError("worker is one of %s" % ", ".join(WORKERS))
    text = summary_text(status, body, next_action)
    if after is not None:
        t = last_by_hand(pkt)
        if t is not None and t >= after:
            return executor.Outcome(executor.OK, "%s: checkpointed by hand since; the "
                                    "scribe's draft is dropped" % pkt.wpid[:8]), None
    ticks = [i for i in ticks or () if i.strip()]
    missing = []

    def prepare(p):
        change = {}
        if ticks:
            path = os.path.join(p.path, OUTLINE)
            old = fsutil.read_text(path) if os.path.isfile(path) else ""
            new, _, miss = tick(old, ticks)
            missing.extend(miss)
            if new != old:
                change["state"] = {os.path.relpath(path, p.state_dir): new}
        if next_action and worker in BY_HAND:
            old = fsutil.read_text(p.memento_path) if os.path.isfile(p.memento_path) else ""
            change["memento"] = memento_with(old, next_action)
        return change
    m = dict(meta or {})
    m.setdefault("checkpoint", {})
    m["checkpoint"].update({"by": by or executor._who(), "next": next_action or None,
                            "ticked": ticks})
    out, n = executor.record_step(pkt, worker, text, meta=m, files=files, prepare=prepare)
    if out.code == executor.LEASED and worker in BY_HAND:
        return during_step(pkt, text, by), None
    if out.code == 0 and missing:
        out = executor.Outcome(out.code, "%s; not in the outline: %s" % (
            out.msg, ", ".join(missing)))
    return out, n


def during_step(pkt, text, by=None):
    """A person's checkpoint while a runner step runs (docs/collaboration.md §5.5):
    it takes no lease and changes no status. It becomes a note, which the running
    step sees (through its hook) or the next one does, and a ``note`` journal
    record for the history. Its next action reaches the runner as part of the note."""
    from . import journal, notes
    by = by or executor._who()
    note = notes.add(pkt, "Where it stands, from %s's checkpoint:\n%s" % (
        by.split("@")[0], text.strip()), by)
    journal.append(pkt.journal_path, {"type": "note", "t": note["t"], "by": by,
                                      "msg": "checkpoint during a step: %s" % (
                                          text.strip().splitlines() or [""])[0]})
    return executor.Outcome(executor.OK, "%s: a step is running, so this was left as a "
                            "note it will see (%s)" % (pkt.wpid[:8], note["id"]))
