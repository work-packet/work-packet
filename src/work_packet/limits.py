"""Usage limits (docs/ask-and-limits-plan.md, Part L).

A run cut off by the account's usage limit is not a failed attempt: the
packet sleeps until the limit resets. When the harness gives no reset time,
it waits ``BACKOFF_FIRST``, doubling up to ``BACKOFF_MAX``.

The limit is the account's, so it is also held per profile in
``$WPK_HOME/limits.json``: ``{profile: {"until", "set", "wpid", "kind"}}``. A step on
a held profile sleeps until then without running.

A run whose login was refused or had expired (``kind: "auth"``) is held the
same way, but with a shorter backoff (``AUTH_BACKOFF_FIRST``) and no reset time:
it lifts when someone logs in again, which wpk cannot see. For either kind, a
hand-off or a wake of the packet after the hold was set releases it: the owner
says the login or the limit is back (docs/pssc-debug-failures-review.md). The
profile's other held packets then wake too. If the limit was not in fact lifted,
the next run hits it again and sets a new hold, at the cost of one uncounted run.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import fsutil, registry, schema

MARGIN = timedelta(minutes=2)           # wake this long after the reset
BACKOFF_FIRST = timedelta(minutes=15)
BACKOFF_MAX = timedelta(hours=1)
AUTH_BACKOFF_FIRST = timedelta(minutes=5)

# "You've hit your session limit · resets 6:40pm (UTC)"; "resets Nov 20, 3pm (Europe/London)"
_HIT = re.compile(r"hit your [\w -]*limit|usage limit|rate.?limit", re.I)
_RESETS = re.compile(
    r"resets\s+(?:(?P<mon>[A-Z][a-z]{2})[a-z]*\s+(?P<day>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?\s*(?:\((?P<tz>[^)]+)\))?", re.I)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


# "Failed to authenticate: OAuth session expired and could not be refreshed";
# "Invalid API key · Please run /login"; "Not logged in"
_AUTH = re.compile(r"failed to authenticate|oauth (session|token)[\w ]*expired|"
                   r"invalid api key|not logged in|please run /login|authentication_error", re.I)


def looks_auth(text):
    """Does a harness's error text say the account's login was refused or expired?"""
    return bool(text) and bool(_AUTH.search(text))


def looks_limited(text):
    """Does a harness's error text say the account hit a usage limit?"""
    return bool(text) and bool(_HIT.search(text))


def reset_from_text(text, now):
    """The reset time in a message like "resets 6:40pm (UTC)", as an aware UTC
    datetime, or None. A time of day already past means the next day."""
    m = _RESETS.search(text or "")
    if not m:
        return None
    h, mi = int(m["h"]), int(m["m"] or 0)
    if m["ap"]:
        h = h % 12 + (12 if m["ap"].lower() == "pm" else 0)
    if h > 23 or mi > 59:
        return None
    try:
        tz = ZoneInfo(m["tz"].strip()) if m["tz"] else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    local = now.astimezone(tz)
    day = local.date()
    if m["mon"] and m["mon"][:3].lower() in _MONTHS:
        try:
            day = day.replace(month=_MONTHS.index(m["mon"][:3].lower()) + 1, day=int(m["day"]))
        except ValueError:
            return None
        if day < local.date() - timedelta(days=180):      # "Jan 2" read in December
            day = day.replace(year=day.year + 1)
    at = datetime(day.year, day.month, day.day, h, mi, tzinfo=tz)
    if not m["mon"] and at <= local:
        at += timedelta(days=1)
    return at.astimezone(timezone.utc)


def wake_time(until, tries, now, first=BACKOFF_FIRST):
    """When a limited packet wakes: just after ``until``, or, with no reset
    time, after a backoff from ``first`` that doubles with each earlier limited
    run (``tries``)."""
    if until is not None and until > now:
        return until + MARGIN
    return now + min(first * (2 ** tries), BACKOFF_MAX)


def _path():
    return os.path.join(registry.home(), "limits.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def hold(profile, until, wpid=None, now=None, kind="limit"):
    """Hold ``profile`` until ``until``; an existing later hold stands."""
    d = _load()
    cur = held(profile, now or until, d)
    if cur is not None and cur >= until:
        return cur
    d[profile] = {"until": schema.format_timestamp(until),
                  "set": schema.format_timestamp(now or datetime.now(timezone.utc)), "wpid": wpid,
                  "kind": kind}
    _save(d)
    return until


def _save(d):
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    fsutil.atomic_write(_path(), json.dumps(d, indent=2) + "\n")


def hold_of(profile, now):
    """``profile``'s hold at ``now`` as ``{"until", "set", "kind", ...}`` (times
    parsed), or None if it is not held."""
    d = _load()
    until = held(profile, now, d)
    if until is None:
        return None
    rec = dict(d[profile], until=until, kind=d[profile].get("kind") or "limit")
    try:
        rec["set"] = schema.parse_timestamp(rec.get("set"))
    except (TypeError, ValueError):
        rec["set"] = None
    return rec


def release(profile):
    """Drop ``profile``'s hold (someone logged in again, or the limit lifted)."""
    d = _load()
    if d.pop(profile, None) is not None:
        _save(d)


def held(profile, now, d=None):
    """The time ``profile`` is held until, or None if it is not held at ``now``."""
    rec = (d if d is not None else _load()).get(profile)
    if not isinstance(rec, dict):
        return None
    try:
        until = schema.parse_timestamp(rec.get("until"))
    except (TypeError, ValueError):
        return None
    return until if until > now else None
