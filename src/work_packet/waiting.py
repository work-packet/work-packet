"""A child that stops wakes its sleeping parent (docs/waiting-v1.md §4).

A parent's ``children_seen`` maps each child to the state its last step's
prompt showed. A child the parent has not seen stop since then is news,
and a ``SLEEPING`` parent with news is due now, whatever its ``wake_at``.
"""
import os

from . import frontmatter, schema
from .packet import Packet

# States a child stays in until someone (its parent, or a person) acts.
STOPPED = ("COMPLETED", "FAILED", "NEEDS_INPUT", "PAUSED")


def _sibling(pkt, wpid):
    return Packet(os.path.join(os.path.dirname(pkt.path), wpid))


def snapshot(children):
    """``children_seen`` from the (wpid, meta, body) triples a prompt showed."""
    return {w: m["state"] for w, m, _ in children if m and m.get("state") in schema.STATES}


def unseen_stops(pkt, meta):
    """(wpid, state) of each child that stopped since the parent's last prompt.

    Without ``children_seen`` (a parent from before it), a stop counts when the
    child's ``updated`` is later than the parent's.
    """
    seen = meta.get("children_seen")
    out = []
    for w in meta.get("children") or ():
        try:
            m, _ = _sibling(pkt, w).load_status()
        except (OSError, frontmatter.FrontMatterError):
            continue
        st = m.get("state")
        if st not in STOPPED:
            continue
        if seen is not None:
            if seen.get(w) != st:
                out.append((w, st))
        elif (m.get("updated") or "") > (meta.get("updated") or ""):
            out.append((w, st))
    return out


def wake_parent(child):
    """Wake the child's parent if it sleeps and the child's stop is news to it.
    Returns the admin Outcome, or None when there was nothing to do. A parent
    whose step is running is left alone: its prompt was built before this stop,
    so once it commits to SLEEPING, ``scheduler.due`` finds the news."""
    try:
        cm, _ = child.load_status()
        if cm.get("state") not in STOPPED or not cm.get("parent"):
            return None
        parent = _sibling(child, cm["parent"])
        pm, _ = parent.load_status()
    except (OSError, frontmatter.FrontMatterError):
        return None
    if pm.get("state") != "SLEEPING" or not unseen_stops(parent, pm):
        return None
    from . import executor
    return executor.admin(parent, "wake", by="child %s %s" % (child.wpid[:8], cm["state"]))
