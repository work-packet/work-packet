"""Your time on a project, from presence (docs/collaboration.md §9.1 Time, plan F3a).

No timers: each presence beat that shows you doing something adds the time
since your previous beat on the project, when that was at most ``GAP_S`` ago.
The ledger is kept per user, not per source, so two sessions open at once
count once. A beat that only says a tab is open and idle (``idle_since``, a
hidden tab) or that a session ended adds nothing, and the next beat starts
afresh.

``<project dir>/time/<YYYY-MM-DD>.json`` (local day)::

    {"by": {"alice": 5400.0}, "last": {"alice": 1762500000.0}}

Stdlib only, plus ``fsutil``: ``presence.beat`` calls it from the Claude Code
hook on every prompt.
"""

import json
import os
import time

from . import fsutil

DIR = "time"
GAP_S = 300


def _path(proj, day):
    return os.path.join(proj, DIR, day + ".json")


def _day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _load(p):
    try:
        with open(p) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    for k in ("by", "last"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def counts(fields):
    """Does a beat with these ``fields`` show someone at work?"""
    return not (fields.get("turn") == "ended" or fields.get("idle_since")
                or fields.get("visible") is False)


def add(proj, by, now=None, counts=True):
    """``by`` did something on ``proj`` at ``now``. Returns the seconds added.
    ``counts`` false (an idle or hidden tab, a session that ended): nothing is
    added, and the next beat starts afresh."""
    if not by:
        return 0.0
    now = time.time() if now is None else now
    p = _path(proj, _day(now))
    d = _load(p)
    if not counts:
        if d["last"].pop(by, None) is not None:
            fsutil.atomic_write(p, json.dumps(d, sort_keys=True) + "\n")
        return 0.0
    last = d["last"].get(by)
    if last is None:                    # first today: yesterday's file may hold the last beat
        prev = _load(_path(proj, _day(now - GAP_S)))["last"].get(by)
        last = prev if prev is not None and _day(prev) != _day(now) else None
    gap = now - last if isinstance(last, (int, float)) else None
    got = gap if gap is not None and 0 < gap <= GAP_S else 0.0
    d["by"][by] = round(float(d["by"].get(by, 0)) + got, 1)
    d["last"][by] = now
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, json.dumps(d, sort_keys=True) + "\n")
    return got


def days(proj):
    """The days with time on ``proj``, oldest first (``YYYY-MM-DD``)."""
    try:
        names = os.listdir(os.path.join(proj, DIR))
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".json") and len(n) == 15)


def spent(proj, since=None, until=None):
    """``{user: seconds}`` on ``proj`` over the days ``since``..``until``
    (``YYYY-MM-DD``, both included; None: no bound)."""
    out = {}
    for day in days(proj):
        if (since and day < since) or (until and day > until):
            continue
        for u, s in _load(_path(proj, day))["by"].items():
            if isinstance(s, (int, float)):
                out[u] = out.get(u, 0.0) + s
    return out


def by_day(proj, since=None):
    """``[(day, seconds of anyone)]``, oldest first."""
    return [(d, sum(v for v in _load(_path(proj, d))["by"].values()
                    if isinstance(v, (int, float))))
            for d in days(proj) if not since or d >= since]


def hours(s):
    """Seconds as "5h", "1.5h" or "20m"."""
    if s < 3600:
        return "%dm" % round(s / 60)
    h = s / 3600
    return ("%.1fh" % h).replace(".0h", "h")
