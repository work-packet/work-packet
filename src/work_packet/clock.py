"""Time for the executor: the clock, resume expressions and their resolution.

Stored times are aware UTC. A zone is applied only when an expression is
resolved: ``in`` days and weeks count calendar days in the project zone,
and an ``at`` without an offset is read in it (spec §5).
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
}

_IN_RX = re.compile(r"^in\s+(\d+)\s+([a-z]+)$")
_FRAC_RX = re.compile(r"(\d{2}:\d{2}:\d{2})\.(\d+)")


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
    # 3.10 takes only 3 or 6 fraction digits; seconds precision is all we keep.
    s = _FRAC_RX.sub(lambda m: m.group(1) + "." + (m.group(2) + "000000")[:6], s)
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
    if head == "ask":
        raise ResumeError("'%s' is not a resume value: ask a question with the memento key "
                          "'ask: <question>' next to resume" % e)
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


# Expression kind -> state after commit.
STATE_AFTER = {
    "now": "RUNNABLE",
    "done": "COMPLETED",
    "fail": "FAILED",
    "in": "SLEEPING",
    "at": "SLEEPING",
}


def local_zone():
    """The machine's zone, with its DST rules: ``$TZ``, then ``/etc/localtime``, then UTC."""
    name = os.environ.get("TZ", "").lstrip(":")
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    try:
        with open("/etc/localtime", "rb") as fp:
            return ZoneInfo.from_file(fp, key="localtime")
    except (OSError, ValueError):
        return timezone.utc


def zone(name=None):
    """The zone named by a project's ``tz``, or the local zone when it has none."""
    if name is None:
        return local_zone()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ResumeError("unknown time zone '%s'" % name) from None


def _wall(local, tz):
    """Attach ``tz`` to the naive wall time ``local`` and return aware UTC.

    A time skipped by a DST change moves forward by the size of the gap
    (02:30 on a spring-forward night is 03:30). A time that occurs twice
    is the first of the two. Both come from ``fold=0``.
    """
    return local.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)


def resolve(resume, committed, tz=None):
    """Resolve a resume expression at commit time.

    ``resume`` is a Resume or an expression string; ``committed`` is the
    aware commit time; ``tz`` is a zone name or tzinfo (None: local zone).
    Returns ``(state, wake_at)``, where ``wake_at`` is aware UTC with whole
    seconds, or None when the state is not SLEEPING.
    """
    if isinstance(resume, str):
        resume = parse_resume(resume)
    if committed.tzinfo is None:
        raise ValueError("resolve needs an aware commit time")
    if tz is None or isinstance(tz, str):
        tz = zone(tz)
    state = STATE_AFTER[resume.kind]
    if resume.kind == "in":
        if resume.unit in ("minutes", "hours"):
            wake = committed + timedelta(**{resume.unit: resume.count})
        else:
            days = resume.count * (7 if resume.unit == "weeks" else 1)
            local = committed.astimezone(tz).replace(tzinfo=None)
            wake = _wall(local + timedelta(days=days), tz)
    elif resume.kind == "at":
        at = resume.at
        wake = _wall(at, tz) if at.tzinfo is None else at
    else:
        return state, None
    return state, wake.astimezone(timezone.utc).replace(microsecond=0)
