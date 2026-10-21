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
