"""A person's planning fields for a project (docs/collaboration.md §9.2): what
matters to you, when it is due, and what it waits on.

They live in the project's card, ``<name>.wp.md``, as a ``plan:`` block of its
front matter: files are the source of truth, and a card's own front matter wins
when the board rebuilds it, so they survive. They are yours: the board and you
write them; an agent only proposes.

::

    plan:
      priority: now        # now | next | later | someday   (default next)
      rank: 3              # order within the priority (dragged on the backlog)
      due: 2026-11-14
      due_kind: hard       # hard: someone depends on it; soft: your target
      estimate: 2d
      blocked_by: [dma-bug, "PR #41"]
      area: dv
"""

import os
import re
from datetime import date, datetime, timedelta

from . import card as cardmod, layout

PRIORITIES = ("now", "next", "later", "someday")
DEFAULT = "next"
DUE_KINDS = ("hard", "soft")
FOCUS_WIP = 3               # at most this many in "now" ([plan] focus_wip)
# What the runner's scheduler class follows when the project sets none (§9.2).
CLASS_OF = {"now": "high", "next": "normal", "later": "low", "someday": "low"}
DUE_BOOST_DAYS = 2          # due this soon: one class up, never above high
# Untouched this long, it shows under Housekeeping (§9.6).
ROT_DAYS = {"now": 3, "next": 21, "later": 42, "someday": 91}
_EST = re.compile(r"^\d+(\.\d+)?[hdw]$")
KEYS = ("priority", "rank", "due", "due_kind", "estimate", "blocked_by", "area")


class PlanError(Exception):
    pass


def path_of(entry):
    return layout.card_path(entry["path"], entry["name"])


def get(entry):
    """The project's plan, with defaults: ``{"priority", "rank", "due", ...}``."""
    out = {"priority": DEFAULT, "rank": None, "due": None, "due_kind": None,
           "estimate": None, "blocked_by": [], "area": None}
    p = path_of(entry)
    if not os.path.isfile(p):
        return out
    try:
        got = cardmod.load(p).meta.get("plan")
    except Exception:                   # noqa: BLE001: a card that does not parse plans nothing
        return out
    if isinstance(got, dict):
        out.update({k: got[k] for k in KEYS if k in got})
    if out["priority"] not in PRIORITIES:
        out["priority"] = DEFAULT
    return out


def validate(changes):
    """``changes`` cleaned: values checked, "" meaning unset. PlanError if bad."""
    out = {}
    for k, v in changes.items():
        if k not in KEYS:
            raise PlanError("no plan field %r" % k)
        if v in ("", None, []):
            out[k] = None
            continue
        if k == "priority" and v not in PRIORITIES:
            raise PlanError("priority is one of %s" % ", ".join(PRIORITIES))
        if k == "due_kind" and v not in DUE_KINDS:
            raise PlanError("due_kind is hard or soft")
        if k == "due":
            try:
                v = date.fromisoformat(str(v)).isoformat()
            except ValueError:
                raise PlanError("due is a date, YYYY-MM-DD") from None
        if k == "rank":
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise PlanError("rank is a whole number") from None
        if k == "estimate" and not _EST.match(str(v)):
            raise PlanError("estimate is like 4h, 2d or 1w")
        if k == "blocked_by":
            v = [x.strip() for x in (v.split(",") if isinstance(v, str) else v) if x.strip()]
        out[k] = v
    return out


def in_focus(entries, but=None):
    """The open projects whose priority is ``now`` (``but``: leave this one out)."""
    from . import views
    out = []
    for e in entries:
        if e["name"] == but or get(e)["priority"] != "now":
            continue
        try:
            from .packet import Packet
            meta = Packet(layout.run_dir(e["path"], e["root"])).load_status()[0]
        except Exception:               # noqa: BLE001
            continue
        if views.lifecycle(meta) == "open":
            out.append(e["name"])
    return out


def set_(entry, changes, by=None, entries=(), wip=FOCUS_WIP, force=False):
    """Change the project's plan (``changes``: field -> value, "" to unset).
    Putting one more project in ``now`` than ``wip`` allows refuses, naming those
    there, unless ``force``. Writes the card under the project's lock, and an
    ``admin`` ``plan`` record in the root's journal. Returns the plan."""
    from . import executor, journal, livecard
    changes = validate(changes)
    if changes.get("priority") == "now" and not force and get(entry)["priority"] != "now":
        there = in_focus(entries, but=entry["name"])
        if len(there) >= wip:
            raise PlanError("%d projects are already in now (%s): move one to next first, "
                            "or put this one there anyway" % (len(there), ", ".join(there)))
    p = path_of(entry)
    fp = livecard._lock(entry["name"])
    try:
        c = cardmod.load(p) if os.path.isfile(p) else cardmod.Card(meta={})
        plan = dict(c.meta.get("plan") or {})
        for k, v in changes.items():
            if v is None:
                plan.pop(k, None)
            else:
                plan[k] = v
        if plan:
            c.meta["plan"] = {k: plan[k] for k in KEYS if k in plan}
        else:
            c.meta.pop("plan", None)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        cardmod.save(p, c)
    finally:
        fp.close()
    from .packet import Packet
    root = Packet(layout.run_dir(entry["path"], entry["root"]))
    if os.path.isfile(root.journal_path):
        journal.append(root.journal_path, {
            "type": "admin", "t": executor._ts(), "op": "plan", "by": by or executor._who(),
            "changes": {k: v for k, v in changes.items()}})
    return get(entry)


def sched_class(plan, today=None):
    """The scheduler class the plan asks for (§9.2): from the priority, one class
    up when ``due`` is within ``DUE_BOOST_DAYS``, never above high."""
    cls = CLASS_OF.get(plan.get("priority"), "normal")
    due = plan.get("due")
    if due:
        today = today or date.today()
        try:
            if date.fromisoformat(str(due)) - today <= timedelta(days=DUE_BOOST_DAYS):
                cls = {"low": "normal", "normal": "high", "background": "low"}.get(cls, cls)
        except ValueError:
            pass
    return cls


def due_text(plan, today=None):
    """"due Fri" / "due in 9 days" / "overdue 2 days", or ""."""
    due = plan.get("due")
    if not due:
        return ""
    today = today or date.today()
    try:
        d = date.fromisoformat(str(due))
    except ValueError:
        return ""
    n = (d - today).days
    if n < 0:
        return "overdue %d day%s" % (-n, "" if n == -1 else "s")
    if n == 0:
        return "due today"
    if n < 7:
        return "due %s" % d.strftime("%a")
    return "due in %d days" % n


def rotting(plan, last_t, now=None):
    """Untouched for longer than its priority allows (``last_t``: epoch of the
    last activity by anyone), or None: ``{"days", "limit"}``."""
    if not last_t:
        return None
    now = datetime.now().timestamp() if now is None else now
    days = int((now - last_t) // 86400)
    limit = ROT_DAYS.get(plan.get("priority"), ROT_DAYS[DEFAULT])
    return {"days": days, "limit": limit} if days > limit else None
