"""Usage limits: a wait until the reset, not a failed attempt
(docs/ask-and-limits-plan.md, Part L)."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from conftest import NOW, make_project
from work_packet import executor, limits, model
from work_packet.harness import claude
from work_packet.schema import parse_timestamp

T0 = parse_timestamp(NOW)                       # 2026-10-21T18:00:00Z


def at(minutes):
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def status(pkt):
    return pkt.load_status()[0]


def records(pkt, *types):
    return [r for r in pkt.journal().records if r["type"] in types]


@pytest.fixture
def fresh(tmp_path, fake):
    return make_project(tmp_path)


# --- reading the limit --------------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    ("You've hit your session limit · resets 6:40pm (UTC)", "2026-10-21T18:40:00Z"),
    ("You've hit your session limit · resets 5pm (UTC)", "2026-10-22T17:00:00Z"),
    ("resets 9:15am (America/New_York)", "2026-10-22T13:15:00Z"),
    ("You've hit your weekly limit · resets Oct 24, 3pm (UTC)", "2026-10-24T15:00:00Z"),
    ("resets 6:40pm (Nowhere/Land)", "2026-10-21T18:40:00Z"),
])
def test_reset_from_text(text, want):
    assert limits.reset_from_text(text, T0) == parse_timestamp(want)


def test_reset_from_text_without_a_time():
    assert limits.reset_from_text("Rate limit exceeded", T0) is None
    assert limits.reset_from_text(None, T0) is None


def test_wake_time_backs_off_without_a_reset():
    assert limits.wake_time(T0 + timedelta(minutes=40), 0, T0) == T0 + timedelta(minutes=42)
    assert [limits.wake_time(None, k, T0) - T0 for k in range(4)] == [
        timedelta(minutes=15), timedelta(minutes=30), timedelta(hours=1), timedelta(hours=1)]
    assert limits.wake_time(T0 - timedelta(minutes=1), 0, T0) == T0 + timedelta(minutes=15)


def test_claude_parse_of_a_real_limit(tmp_path):
    """The events of pssc-debug step 110."""
    path = tmp_path / "t.jsonl"
    evs = [{"type": "rate_limit_event", "rate_limit_info": {
               "status": "allowed_warning", "resetsAt": 1795027200, "rateLimitType": "five_hour",
               "utilization": 0.99}},
           {"type": "rate_limit_event", "rate_limit_info": {
               "status": "rejected", "resetsAt": 1795027200, "rateLimitType": "five_hour",
               "overageStatus": "rejected", "unifiedWindows": {
                   "five_hour": {"utilization": 1, "resetsAt": 1795027200}}}},
           {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429,
            "terminal_reason": "api_error", "session_id": "s",
            "result": "You've hit your session limit · resets 6:40pm (UTC)"}]
    path.write_text("".join(json.dumps(e) + "\n" for e in evs))
    res = model.StepResult(exit_code=1)
    claude.Claude().parse(str(path), res)
    assert res.limit_hit()
    assert res.limited_until == datetime(2026, 11, 18, 18, 40, tzinfo=timezone.utc)
    assert res.failure() == "usage limit (resets 18:40 UTC)"


# --- the executor -------------------------------------------------------------------

def test_a_limited_run_sleeps_until_the_reset_and_is_not_counted(fresh, fake, monkeypatch):
    proj, root = fresh
    fake(fault="limit")
    monkeypatch.setenv("WPK_FAKE_RESETS", str(int((T0 + timedelta(minutes=40)).timestamp())))
    out = executor.step(proj)
    assert out.code == executor.NOT_RUNNABLE and "usage limit" in out.msg
    st = status(root)
    assert (st["state"], st["wake_at"], st["attempts"], st["step"]) == \
        ("SLEEPING", at(42), 0, 0)
    assert "resumes 18:42 UTC" in st["reason"]
    rec, = records(root, "step-failed")
    assert rec["counted"] is False and rec["limited"] == at(42) and rec["run"] == 1
    assert os.path.isdir(root.step_dir(1, 1))
    # not due before the reset
    assert executor.step(proj).code == executor.NOT_RUNNABLE
    assert len(records(root, "step-start")) == 1
    # after it, the step runs, and its prompt says why the last run stopped
    monkeypatch.setenv("WPK_NOW", at(43))
    fake(fault=None)
    assert executor.step(proj).code == executor.OK
    st = status(root)
    assert (st["state"], st["step"], st["attempts"]) == ("RUNNABLE", 1, 0)
    assert "usage limit" in open(os.path.join(root.step_dir(1), "prompt.md")).read()


def test_limits_never_make_a_packet_failed(fresh, fake, monkeypatch):
    proj, root = fresh
    fake(fault="limit-bare")
    wakes = []
    for k in range(5):
        assert executor.step(proj, force=True).code == executor.NOT_RUNNABLE
        wakes.append(status(root)["wake_at"])
        monkeypatch.setenv("WPK_NOW", wakes[-1])
    st = status(root)
    assert st["state"] == "SLEEPING" and st["attempts"] == 0
    assert wakes == [at(15), at(45), at(105), at(165), at(225)]


def test_the_reset_can_come_from_the_text_alone(fresh, fake):
    proj, root = fresh
    fake(fault="limit-text")
    executor.step(proj)
    assert status(root)["wake_at"] == at(42)


def test_a_rejected_event_in_a_finished_run_is_no_limit(fresh, fake):
    proj, root = fresh
    fake(fault="limit-passed")
    assert executor.step(proj).code == executor.OK
    assert status(root)["state"] == "RUNNABLE"


def test_other_packets_on_the_profile_wait_without_running(tmp_path, fake, monkeypatch):
    proj_a, a = make_project(tmp_path / "a")
    proj_b, b = make_project(tmp_path / "b")
    fake(fault="limit-text")
    executor.step(proj_a)
    fake(fault=None)
    out = executor.step(proj_b)
    assert out.code == executor.NOT_RUNNABLE and "usage limit on" in out.msg
    st = status(b)
    assert (st["state"], st["wake_at"], st["attempts"]) == ("SLEEPING", at(42), 0)
    assert records(b, "step-start") == [] and len(records(b, "limit-wait")) == 1
    # Run now (force) ignores the hold; after the reset both run
    assert executor.step(proj_b, force=True).code == executor.OK
    monkeypatch.setenv("WPK_NOW", at(43))
    assert executor.step(proj_a).code == executor.OK
