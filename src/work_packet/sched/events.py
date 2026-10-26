"""``events.jsonl``: what the scheduler did and why (docs/scheduler.md §7).

One JSON object per line, ``{"t", "type", "by", ...}``. Files are monthly,
``sched/events-YYYY-MM.jsonl``; ``$WPK_HOME/events.jsonl`` is a symlink to
the current month's.
"""

import json
import os

from .. import clock, fsutil, registry, schema
from .config import sched_dir

TYPES = ("mode", "prio", "hold", "size", "next", "submitted", "started", "finished",
         "lost", "cancelled", "pending_long", "gate", "backend_down", "backend_up",
         "wpkd_start", "wpkd_stop", "grant_expired", "adopted", "cap")
SYSTEM = "wpkd"            # ``by`` of what the dispatcher does by itself


def month_path(h=None, when=None):
    when = when or clock.now()
    return os.path.join(sched_dir(h), "events-%s.jsonl" % when.strftime("%Y-%m"))


def _link(h, target):
    link = os.path.join(h or registry.home(), "events.jsonl")
    rel = os.path.relpath(target, os.path.dirname(link))
    try:
        if os.readlink(link) == rel:
            return
    except OSError:
        pass
    tmp = link + ".tmp-%d" % os.getpid()
    try:
        os.symlink(rel, tmp)
        os.replace(tmp, link)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def append(type, h=None, now=None, by=SYSTEM, **fields):
    """Write one event. ``by``: who caused it, a principal (``unix:matt``) or
    ``wpkd``. Returns the record."""
    if type not in TYPES:
        raise ValueError("unknown event type %r" % type)
    now = now or clock.now()
    rec = {"t": schema.format_timestamp(now), "type": type, "by": by}
    rec.update({k: v for k, v in fields.items() if v is not None})
    p = month_path(h, now)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.append_line(p, json.dumps(rec, sort_keys=False, separators=(",", ":")))
    _link(h, p)
    return rec


def read(h=None, since=None, types=None, limit=None):
    """Events at or after ``since`` (aware datetime), oldest first, of ``types``."""
    d = sched_dir(h)
    try:
        names = sorted(n for n in os.listdir(d) if n.startswith("events-")
                       and n.endswith(".jsonl"))
    except OSError:
        return []
    if since is not None:
        first = "events-%s.jsonl" % since.strftime("%Y-%m")
        names = [n for n in names if n >= first]
    cut = schema.format_timestamp(since) if since is not None else None
    out = []
    for n in names:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as fp:
                for line in fp:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(r, dict):
                        continue
                    if cut is not None and r.get("t", "") < cut:
                        continue
                    if types is not None and r.get("type") not in types:
                        continue
                    out.append(r)
        except OSError:
            continue
    return out[-limit:] if limit else out
