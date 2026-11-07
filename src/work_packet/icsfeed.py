"""Calendar fit (docs/collaboration.md §9.5, plan F3f).

With ``[calendar] ics = "<https URL or a file>"``, the brief lists today's
meetings and what fits before the next one ("45 min before 11:00: 2 reviews
fit"), and pushes wait while you are in a meeting (``notify``).

The board's loop fetches a URL at most once an hour into
``$WPK_HOME/calendar/feed.ics``; readers use that copy, so a page never waits on
the network. A file path is read as it is.

The parser is small: VEVENTs with DTSTART, DTEND (or DURATION) and SUMMARY.
Times in UTC (``Z``), with a ``TZID`` (zoneinfo), or floating (local). All-day
events, cancelled ones and ones marked free (``TRANSP:TRANSPARENT``) are left
out. **Recurring events (RRULE) are not expanded**: only their first instance
counts.
"""

import os
import re
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

from . import fsutil, registry

EVERY_S = 3600
ITEM_MIN = 15               # a review or an answer, in the brief's "what fits"
_DUR = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


class FeedError(Exception):
    pass


def source(h=None):
    try:
        cfg = registry.load_config_file(h).get("calendar") or {}
    except registry.ConfigError:
        return None
    s = cfg.get("ics")
    return s.strip() if isinstance(s, str) and s.strip() else None


def _copy(h):
    return os.path.join(h or registry.home(), "calendar", "feed.ics")


def _is_url(s):
    return s.startswith(("http://", "https://"))


def fetch(h=None, now=None, force=False, opener=None):
    """The board's loop: refresh the copy of a URL feed, at most every
    ``EVERY_S``. Returns True when it fetched."""
    h = h or registry.home()
    s = source(h)
    if not s or not _is_url(s):
        return False
    now = time.time() if now is None else now
    p = _copy(h)
    try:
        if not force and now - os.path.getmtime(p) < EVERY_S:
            return False
    except OSError:
        pass
    try:
        with (opener or urllib.request.urlopen)(s, timeout=20) as r:
            text = r.read(2 * 1024 * 1024).decode("utf-8", "replace")
    except Exception as e:              # noqa: BLE001: any failure keeps the old copy
        raise FeedError("calendar feed: %s" % e) from None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, text)
    return True


def text(h=None):
    s = source(h)
    if not s:
        return None
    p = _copy(h) if _is_url(s) else os.path.expanduser(s)
    try:
        with open(p, encoding="utf-8", errors="replace") as fp:
            return fp.read()
    except OSError:
        return None


# --- parsing -----------------------------------------------------------------------

def _lines(raw):
    out = []
    for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ln[:1] in (" ", "\t") and out:
            out[-1] += ln[1:]
        elif ln:
            out.append(ln)
    return out


def _unescape(v):
    return re.sub(r"\\([,;\\nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _when(params, value):
    """An aware datetime, or None for a date (all day)."""
    if "VALUE=DATE" in params.upper() or len(value) == 8:
        return None
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    m = re.search(r"TZID=([^;:]+)", params)
    if m:
        try:
            from zoneinfo import ZoneInfo
            return dt.replace(tzinfo=ZoneInfo(m.group(1).strip('"')))
        except Exception:               # noqa: BLE001: an unknown zone is read as local
            pass
    return dt.astimezone()              # floating: local time


def _duration(v):
    m = _DUR.match(v or "")
    if not m:
        return None
    d, hh, mm, ss = (int(x or 0) for x in m.groups())
    return timedelta(days=d, hours=hh, minutes=mm, seconds=ss)


def parse(raw):
    """``[{"start", "end" (aware datetimes), "title"}]``, by start."""
    out, cur = [], None
    for ln in _lines(raw or ""):
        name, _, value = ln.partition(":")
        key, _, params = name.partition(";")
        key = key.upper()
        if key == "BEGIN" and value.upper() == "VEVENT":
            cur = {}
        elif key == "END" and value.upper() == "VEVENT" and cur is not None:
            start = cur.get("start")
            end = cur.get("end") or (start + cur["dur"] if start and cur.get("dur") else None)
            if start and end and end > start and not cur.get("skip"):
                out.append({"start": start, "end": end, "title": cur.get("title") or "busy"})
            cur = None
        elif cur is None:
            continue
        elif key == "DTSTART":
            cur["start"] = _when(params, value.strip())
        elif key == "DTEND":
            cur["end"] = _when(params, value.strip())
        elif key == "DURATION":
            cur["dur"] = _duration(value.strip())
        elif key == "SUMMARY":
            cur["title"] = _unescape(value.strip())
        elif key == "STATUS" and value.strip().upper() == "CANCELLED":
            cur["skip"] = True
        elif key == "TRANSP" and value.strip().upper() == "TRANSPARENT":
            cur["skip"] = True
    return sorted(out, key=lambda e: e["start"])


def events(h=None):
    return parse(text(h) or "")


def on_day(evs, day):
    """The events that overlap local ``day`` (a date)."""
    t0 = datetime(day.year, day.month, day.day).astimezone()
    t1 = t0 + timedelta(days=1)
    return [e for e in evs if e["start"] < t1 and e["end"] > t0]


def busy(evs, now):
    """The event going on at epoch ``now``, or None."""
    t = datetime.fromtimestamp(now, timezone.utc)
    return next((e for e in evs if e["start"] <= t < e["end"]), None)


def fit(evs, now, items):
    """Before the next meeting today: ``{"minutes", "at", "fits"}`` (``fits``:
    how many of ``items`` 15-minute things fit), or None (no meeting left, or one
    now)."""
    t = datetime.fromtimestamp(now, timezone.utc)
    if busy(evs, now):
        return None
    today = t.astimezone().date()
    nxt = next((e for e in on_day(evs, today) if e["start"] > t), None)
    if nxt is None:
        return None
    mins = int((nxt["start"] - t).total_seconds() // 60)
    return {"minutes": mins, "at": nxt["start"].astimezone().strftime("%H:%M"),
            "title": nxt["title"], "fits": min(items, mins // ITEM_MIN)}


def brief_part(h, now, items):
    """For the brief: ``{"meetings": [{start, end, title}], "fit"}``, or None
    without a feed."""
    if not source(h):
        return None
    evs = events(h)
    day = date.fromtimestamp(now)
    return {"meetings": [{"start": e["start"].astimezone().strftime("%H:%M"),
                          "end": e["end"].astimezone().strftime("%H:%M"),
                          "title": e["title"]} for e in on_day(evs, day)],
            "fit": fit(evs, now, items)}
