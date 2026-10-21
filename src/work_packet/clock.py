"""Time for the executor.

M1 holds ``now()`` and the resume-expression parser, which the checker
needs. M2 adds ``resolve()`` and zone handling.
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

UNITS = {
    "minute": "minutes", "minutes": "minutes",
    "hour": "hours", "hours": "hours",
    "day": "days", "days": "days",
    "week": "weeks", "weeks": "weeks",
}

# Forms that a later stage adds, and the stage that adds them.
LATER = {
    "on": "Stage 2",
    "every": "Stage 2",
    "wait": "Stage 3",
    "ask": "Stage 3",
}

_IN_RX = re.compile(r"^in\s+(\d+)\s+([a-z]+)$")


class ResumeError(ValueError):
    pass


@dataclass(frozen=True)
class Resume:
    kind: str                       # now | done | fail | in | at
    count: Optional[int] = None     # for "in"
    unit: Optional[str] = None      # for "in": minutes | hours | days | weeks
    at: Optional[datetime] = None   # for "at"; naive means project zone


def parse_iso(s):
    """Parse an ISO 8601 date or date-time, accepting a ``Z`` suffix on 3.10."""
    s = s.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def now():
    """The executor's clock: aware UTC. ``WPK_NOW`` (ISO 8601) overrides it."""
    fake = os.environ.get("WPK_NOW")
    if fake:
        dt = parse_iso(fake)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_resume(expr):
    """Parse a ``resume:`` value. Raises ResumeError with a message for a person."""
    if not isinstance(expr, str):
        raise ResumeError("resume must be a string, not %s" % type(expr).__name__)
    e = " ".join(expr.strip().split())
    low = e.lower()
    if low in ("now", "done", "fail"):
        return Resume(low)
    head = low.split(" ", 1)[0].rstrip(":")
    if head in LATER:
        raise ResumeError("'%s' is not supported yet: %s adds it" % (e, LATER[head]))
    if head == "in":
        m = _IN_RX.match(low)
        if not m:
            raise ResumeError("expected 'in <N> <unit>', got '%s'" % e)
        n, unit = int(m.group(1)), m.group(2)
        if unit not in UNITS:
            raise ResumeError("unknown unit '%s' (use minutes, hours, days or weeks)" % unit)
        if n <= 0:
            raise ResumeError("'in' needs a positive count, got %d" % n)
        return Resume("in", count=n, unit=UNITS[unit])
    if head == "at":
        rest = e[2:].strip()
        if not rest:
            raise ResumeError("expected 'at <ISO 8601 time>'")
        try:
            return Resume("at", at=parse_iso(rest))
        except ValueError:
            raise ResumeError("'%s' is not an ISO 8601 date or time" % rest) from None
    raise ResumeError("unknown resume expression '%s' "
                      "(use now, done, fail, 'in <N> <unit>' or 'at <time>')" % e)
