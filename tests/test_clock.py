from datetime import datetime, timedelta, timezone

import pytest

from work_packet import clock
from work_packet.clock import Resume, ResumeError


@pytest.mark.parametrize("expr,want", [
    ("now", Resume("now")),
    ("Done", Resume("done")),
    (" fail ", Resume("fail")),
    ("in 10 days", Resume("in", count=10, unit="days")),
    ("in 1 day", Resume("in", count=1, unit="days")),
    ("in  3   hours", Resume("in", count=3, unit="hours")),
    ("in 1 minute", Resume("in", count=1, unit="minutes")),
    ("in 2 weeks", Resume("in", count=2, unit="weeks")),
    ("at 2027-01-10", Resume("at", at=datetime(2027, 1, 10))),
    ("at 2027-01-10 09:00", Resume("at", at=datetime(2027, 1, 10, 9, 0))),
    ("at 2027-01-10T09:00:00Z",
     Resume("at", at=datetime(2027, 1, 10, 9, 0, tzinfo=timezone.utc))),
    ("at 2027-01-10T09:00:00+01:00",
     Resume("at", at=datetime(2027, 1, 10, 9, 0, tzinfo=timezone(timedelta(hours=1))))),
])
def test_parse_resume(expr, want):
    assert clock.parse_resume(expr) == want


@pytest.mark.parametrize("expr,match", [
    ("later", "unknown resume"),
    ("in ten days", "expected 'in <N> <unit>'"),
    ("in 0 days", "positive"),
    ("in 3 fortnights", "unknown unit"),
    ("at", "expected 'at"),
    ("at tomorrow", "not an ISO 8601"),
    ("on 10 Jan", "Stage 2"),
    ("every monday 08:00", "Stage 2"),
    ("wait: child", "Stage 3"),
    ("ask", "Stage 3"),
    (5, "must be a string"),
    (None, "must be a string"),
])
def test_parse_resume_rejects(expr, match):
    with pytest.raises(ResumeError, match=match):
        clock.parse_resume(expr)


def test_now_fake(monkeypatch):
    monkeypatch.setenv("WPK_NOW", "2027-01-10T09:00:00Z")
    assert clock.now() == datetime(2027, 1, 10, 9, tzinfo=timezone.utc)
    monkeypatch.setenv("WPK_NOW", "2027-01-10T10:00:00+01:00")
    assert clock.now() == datetime(2027, 1, 10, 9, tzinfo=timezone.utc)


def test_now_real(monkeypatch):
    monkeypatch.delenv("WPK_NOW", raising=False)
    n = clock.now()
    assert n.tzinfo is not None and n.microsecond == 0


# --- resolve --------------------------------------------------------------

UTC = timezone.utc


def at(s):
    return clock.parse_iso(s).astimezone(UTC)


@pytest.mark.parametrize("expr,state", [
    ("now", "RUNNABLE"), ("done", "COMPLETED"), ("fail", "FAILED"),
])
def test_resolve_no_wake(expr, state):
    assert clock.resolve(expr, at("2026-10-21T18:00:00Z"), "UTC") == (state, None)


@pytest.mark.parametrize("expr,committed,tz,wake", [
    # Minutes and hours are elapsed time.
    ("in 90 minutes", "2026-10-21T18:00:00Z", "UTC", "2026-10-21T19:30:00Z"),
    ("in 3 hours", "2026-10-21T23:00:00Z", "UTC", "2026-10-22T02:00:00Z"),
    # Days across a month end and a year end.
    ("in 10 days", "2026-10-25T12:00:00Z", "UTC", "2026-11-04T12:00:00Z"),
    ("in 10 days", "2027-02-25T12:00:00Z", "UTC", "2027-03-07T12:00:00Z"),
    ("in 2 weeks", "2026-12-25T08:00:00Z", "UTC", "2027-01-08T08:00:00Z"),
    # London leaves BST on 2026-10-25: 1 day is 25 hours, 09:00 stays 09:00.
    ("in 1 day", "2026-10-24T08:00:00Z", "Europe/London", "2026-10-25T09:00:00Z"),
    ("in 1 week", "2026-10-21T08:00:00Z", "Europe/London", "2026-10-28T09:00:00Z"),
    # ...but 24 hours is 24 hours.
    ("in 24 hours", "2026-10-24T08:00:00Z", "Europe/London", "2026-10-25T08:00:00Z"),
    # London enters BST on 2027-03-28: 1 day is 23 hours.
    ("in 1 day", "2027-03-27T09:00:00Z", "Europe/London", "2027-03-28T08:00:00Z"),
    # New York leaves DST on 2026-11-01.
    ("in 1 day", "2026-10-31T13:00:00Z", "America/New_York", "2026-11-01T14:00:00Z"),
])
def test_resolve_in(expr, committed, tz, wake):
    assert clock.resolve(expr, at(committed), tz) == ("SLEEPING", at(wake))


@pytest.mark.parametrize("expr,tz,wake", [
    ("at 2027-01-10", "UTC", "2027-01-10T00:00:00Z"),
    ("at 2027-01-10 09:00", "Europe/London", "2027-01-10T09:00:00Z"),
    ("at 2027-07-10 09:00", "Europe/London", "2027-07-10T08:00:00Z"),
    ("at 2027-01-10 09:00", "America/New_York", "2027-01-10T14:00:00Z"),
    # An explicit offset ignores the zone.
    ("at 2027-01-10T09:00:00Z", "America/New_York", "2027-01-10T09:00:00Z"),
    ("at 2027-01-10T09:00:00+01:00", "UTC", "2027-01-10T08:00:00Z"),
    # Seconds precision.
    ("at 2027-01-10T09:00:00.75Z", "UTC", "2027-01-10T09:00:00Z"),
    # A wall time skipped by spring-forward moves on by the gap...
    ("at 2027-03-28 01:30", "Europe/London", "2027-03-28T01:30:00Z"),
    # ...and one that happens twice is the first.
    ("at 2026-10-25 01:30", "Europe/London", "2026-10-25T00:30:00Z"),
    # The past is accepted and means due now.
    ("at 2000-01-01", "UTC", "2000-01-01T00:00:00Z"),
])
def test_resolve_at(expr, tz, wake):
    assert clock.resolve(expr, at("2026-10-21T18:00:00Z"), tz) == ("SLEEPING", at(wake))


def test_resolve_in_from_ambiguous_hour():
    # Committed in the second 01:30 of the fall-back night: a day later is 01:30 GMT.
    committed = at("2026-10-25T01:30:00Z")
    assert clock.resolve("in 1 day", committed, "Europe/London") == \
        ("SLEEPING", at("2026-10-26T01:30:00Z"))


def test_resolve_accepts_parsed_and_tzinfo():
    r = clock.parse_resume("in 1 day")
    from zoneinfo import ZoneInfo
    got = clock.resolve(r, at("2026-10-24T08:00:00Z"), ZoneInfo("Europe/London"))
    assert got == ("SLEEPING", at("2026-10-25T09:00:00Z"))


def test_resolve_local_zone(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    assert clock.local_zone().key == "Europe/London"
    assert clock.resolve("in 1 day", at("2026-10-24T08:00:00Z")) == \
        ("SLEEPING", at("2026-10-25T09:00:00Z"))


def test_resolve_rejects():
    with pytest.raises(ResumeError, match="Stage 2"):
        clock.resolve("every monday", at("2026-10-21T18:00:00Z"), "UTC")
    with pytest.raises(ResumeError, match="Stage 3"):
        clock.resolve("wait: child", at("2026-10-21T18:00:00Z"), "UTC")
    with pytest.raises(ResumeError, match="unknown time zone"):
        clock.resolve("in 1 day", at("2026-10-21T18:00:00Z"), "Mars/Olympus")
    with pytest.raises(ValueError, match="aware"):
        clock.resolve("in 1 day", datetime(2026, 10, 21), "UTC")
