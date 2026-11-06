"""Who has a packet and whose move it is (docs/collaboration.md §4.1): pure
derivations from status.md, tested without a run."""

import pytest

from work_packet import schema, views

RUN = {"step": 3}           # a live lease


def _m(state, **kw):
    m = {"state": state, "lifecycle": "open"}
    m.update(kw)
    return m


# (meta, running) -> (lifecycle, driver, ball who, ball kind, column)
CASES = [
    ("queued", _m("RUNNABLE"), None, ("open", "nobody", "agent", "queued", "Working: agent")),
    ("running", _m("RUNNABLE"), RUN, ("open", "runner", "agent", "working", "Working: agent")),
    ("children", _m("SLEEPING", waiting_on=["x"], wait_mode="all"), None,
     ("open", "nobody", "agent", "children", "Waiting")),
    ("sleeping", _m("SLEEPING", wake_at="2026-11-07T00:00:00Z"), None,
     ("open", "nobody", "scheduled", "scheduled", "Waiting")),
    ("question", _m("NEEDS_INPUT", reason="which?"), None,
     ("open", "nobody", "you", "question", "Needs you")),
    ("failed", _m("FAILED", reason="boom"), None, ("open", "nobody", "you", "failure", "Needs you")),
    ("finished, unread", _m("COMPLETED", stopped="2026-11-06T10:00:00Z"), None,
     ("open", "nobody", "you", "review", "Needs you")),
    ("finished, looked at", _m("COMPLETED", stopped="2026-11-06T10:00:00Z",
                               seen="2026-11-06T11:00:00Z"), None,
     ("open", "nobody", "you", "parked", "Parked")),
    ("not started", _m("PAUSED", reason=schema.REASON_SETUP), None,
     ("open", "nobody", "you", "parked", "Parked")),
    ("by hand", _m("PAUSED", reason=schema.REASON_BY_HAND), None,
     ("open", "nobody", "you", "parked", "Parked")),
    ("capped", _m("PAUSED", reason="over the day's cap"), None,
     ("open", "nobody", "you", "parked", "Parked")),
    ("studio", _m("PAUSED", reason=schema.REASON_STUDIO, taken_by="me"), None,
     ("open", "you", "you", "studio", "Working: you")),
    ("marked done", _m("PAUSED", reason=schema.REASON_DONE, lifecycle="done"), None,
     ("done", "nobody", "nobody", "done", "Done")),
    ("dropped", _m("FAILED", reason="x", lifecycle="dropped"), None,
     ("dropped", "nobody", "nobody", "dropped", "Done")),
    # From before the fields: the runner finishing was done, as the board showed it.
    ("legacy finished", {"state": "COMPLETED"}, None, ("done", "nobody", "nobody", "done", "Done")),
    ("legacy paused", {"state": "PAUSED", "reason": "setup"}, None,
     ("open", "nobody", "you", "parked", "Parked")),
    # Left to the runner with no review: finishing is done.
    ("runner, never", _m("COMPLETED", autonomy="runner", review="never"), None,
     ("done", "nobody", "nobody", "done", "Done")),
    ("runner, each", _m("COMPLETED", autonomy="runner", review="each",
                        stopped="2026-11-06T10:00:00Z"), None,
     ("open", "nobody", "you", "review", "Needs you")),
    ("unreadable", {"state": "?"}, None, ("open", "nobody", "you", "failure", "Needs you")),
]


@pytest.mark.parametrize("name,meta,run,want", CASES, ids=[c[0] for c in CASES])
def test_derivation(name, meta, run, want):
    b = views.ball(meta, run)
    got = (views.lifecycle(meta), views.driver(meta, run), b["who"], b["kind"],
           views.column(meta, run))
    assert got == want
    assert b["text"]
    assert views.column(meta, run) in views.COLUMNS


def test_texts_say_why():
    assert views.ball(_m("PAUSED", reason="over the day's cap"))["text"] == \
        "paused: over the day's cap"
    assert views.ball(_m("PAUSED", reason=schema.REASON_SETUP))["text"] == "not started"
    assert views.ball(_m("NEEDS_INPUT", reason="Which colour?"))["text"] == "Which colour?"
    assert views.ball(_m("RUNNABLE"), RUN)["text"] == "step 3 running"


def test_autonomy_defaults_to_handoff():
    assert views.autonomy({}) == "handoff"
    assert views.autonomy({"autonomy": "manual"}) == "manual"
    assert views.autonomy({"autonomy": "bogus"}) == "handoff"


def test_seen_as_datetimes_too():
    """The board's rows carry ``stopped`` and ``seen`` as datetimes."""
    at, later = schema.parse_timestamp("2026-11-06T10:00:00Z"), \
        schema.parse_timestamp("2026-11-06T11:00:00Z")
    assert views.ball(_m("COMPLETED", stopped=at))["kind"] == "review"
    assert views.ball(_m("COMPLETED", stopped=at, seen=later))["kind"] == "parked"


@pytest.mark.parametrize("field,good,bad", [
    ("lifecycle", "done", "finished"), ("autonomy", "runner", "auto"),
    ("review", "never", "sometimes"), ("owner", "alice", "")])
def test_schema_validates_the_fields(field, good, bad):
    base = {"wpk": schema.FORMAT_VERSION, "wpid": "0" * 8 + "-0000-4000-8000-" + "0" * 12,
            "project": "p", "state": "RUNNABLE", "step": 0, "attempts": 0, "parent": None,
            "spawn_key": None, "children": [], "resume_expr": None, "wake_at": None,
            "model": "m", "reason": None, "updated": "2026-11-06T10:00:00Z"}
    ok = [p for p in schema.validate_status(dict(base, **{field: good})) if p.level == "error"]
    assert ok == []
    errs = [p for p in schema.validate_status(dict(base, **{field: bad})) if p.level == "error"]
    assert [p.field for p in errs] == [field]
