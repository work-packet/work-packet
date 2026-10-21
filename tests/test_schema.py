import pytest

from work_packet import schema
from work_packet.packet import new_status

ROOT = "3f0c9a2e-6d1b-4c61-9a57-0d5e7f1b2c3d"
OTHER = "1b2c3d4e-0000-4000-8000-000000000001"
NOW = "2026-10-21T18:00:00Z"


def fields(problems, level="error"):
    return sorted({p.field for p in problems if p.level == level}, key=str)


def good_status(**kw):
    s = new_status(ROOT, "demo", "claude-haiku-4-5-20251001", NOW)
    s.update(kw)
    return s


# --- status ---------------------------------------------------------------

def test_status_good():
    assert schema.validate_status(good_status()) == []
    assert schema.validate_status(good_status(state="SLEEPING", wake_at=NOW,
                                              resume_expr="in 10 days")) == []
    assert schema.validate_status(good_status(state="FAILED", reason="gave up")) == []
    assert schema.validate_status(good_status(
        parent=OTHER, spawn_key=OTHER + ":4:0", children=[OTHER])) == []


@pytest.mark.parametrize("change,field", [
    ({"wpk": 0.2}, "wpk"),
    ({"wpk": "0.1"}, "wpk"),
    ({"wpid": "not-a-uuid"}, "wpid"),
    ({"wpid": ROOT.upper()}, "wpid"),
    ({"project": "Has Spaces"}, "project"),
    ({"state": "RUNNING"}, "state"),
    ({"state": "WAITING"}, "state"),
    ({"step": -1}, "step"),
    ({"step": "3"}, "step"),
    ({"attempts": True}, "attempts"),
    ({"parent": OTHER}, "spawn_key"),
    ({"spawn_key": OTHER + ":1:0"}, "spawn_key"),
    ({"parent": OTHER, "spawn_key": ROOT + ":1:0"}, "spawn_key"),
    ({"parent": OTHER, "spawn_key": "garbage"}, "spawn_key"),
    ({"parent": "x", "spawn_key": "x:1:0"}, "parent"),
    ({"children": [OTHER, OTHER]}, "children"),
    ({"children": "none"}, "children"),
    ({"state": "SLEEPING"}, "wake_at"),
    ({"wake_at": NOW}, "wake_at"),
    ({"state": "SLEEPING", "wake_at": "2026-10-21 18:00"}, "wake_at"),
    ({"state": "PAUSED"}, "reason"),
    ({"state": "FAILED", "reason": ""}, "reason"),
    ({"model": ""}, "model"),
    ({"updated": "yesterday"}, "updated"),
    ({"colour": "blue"}, "colour"),
])
def test_status_bad(change, field):
    assert field in fields(schema.validate_status(good_status(**change)))


def test_status_missing_key():
    s = good_status()
    del s["attempts"]
    assert fields(schema.validate_status(s)) == ["attempts"]


def test_status_no_front_matter():
    assert schema.validate_status(None)[0].field is None


def test_status_order_warning():
    s = good_status()
    s = dict(reversed(list(s.items())))
    probs = schema.validate_status(s)
    assert fields(probs) == [] and fields(probs, "warning") == [None]


# --- memento --------------------------------------------------------------

def test_memento_good():
    v = schema.validate_memento
    assert v({"resume": "now"}, "Next.\n") == []
    assert v({"resume": "done"}, "") == []
    assert v({"resume": "fail", "reason": "no input"}, "") == []
    assert v({"resume": "in 10 days"}, "Check again.\n") == []
    assert v({"resume": "now", "spawn": [
        {"name": "hello", "instruction": "Say hi.\n", "copy": ["count.md", "sub/*.txt"]},
        {"name": "bye", "instruction": "Say bye.\n", "model": None},
    ]}, "Next.\n") == []


@pytest.mark.parametrize("meta,body,field", [
    ({}, "x", None),
    ({"reason": "x"}, "x", "resume"),
    ({"resume": "later"}, "x", "resume"),
    ({"resume": "on 10 Jan"}, "x", "resume"),
    ({"resume": "now", "every": "monday"}, "x", "every"),
    ({"resume": "now", "wait": "child"}, "x", "wait"),
    ({"resume": "fail"}, "", "reason"),
    ({"resume": "now"}, "  \n", None),
    ({"resume": "now", "extra": 1}, "x", "extra"),
    ({"resume": "now", "spawn": "hello"}, "x", "spawn"),
    ({"resume": "now", "spawn": ["hello"]}, "x", "spawn[0]"),
    ({"resume": "now", "spawn": [{"instruction": "x"}]}, "x", "spawn[0].name"),
    ({"resume": "now", "spawn": [{"name": "a", "instruction": "x"},
                                 {"name": "a", "instruction": "y"}]}, "x", "spawn[1].name"),
    ({"resume": "now", "spawn": [{"name": "a"}]}, "x", "spawn[0].instruction"),
    ({"resume": "now", "spawn": [{"name": "a", "instruction": "x", "copy": "*.md"}]},
     "x", "spawn[0].copy"),
    ({"resume": "now", "spawn": [{"name": "a", "instruction": "x", "copy": ["../x"]}]},
     "x", "spawn[0].copy[0]"),
    ({"resume": "now", "spawn": [{"name": "a", "instruction": "x", "copy": ["/etc/*"]}]},
     "x", "spawn[0].copy[0]"),
    ({"resume": "now", "spawn": [{"name": "a", "instruction": "x", "pid": 1}]},
     "x", "spawn[0].pid"),
])
def test_memento_bad(meta, body, field):
    assert field in fields(schema.validate_memento(meta, body))


def test_memento_committed_without_front_matter():
    assert schema.validate_memento(None, "First instruction.\n", proposal=False) == []
    assert schema.validate_memento({}, "First instruction.\n", proposal=False) == []
    assert fields(schema.validate_memento(None, "", proposal=False)) == [None]
    assert fields(schema.validate_memento(None, "First.\n", proposal=True)) == [None]


# --- TOML files -----------------------------------------------------------

GOOD_PROJECT = {"name": "demo", "root": ROOT, "created": NOW, "template": "blank@1",
                "tz": "Europe/London", "model": "m", "step_timeout": "20m",
                "max_attempts": 3, "step_budget_usd": 0.5,
                "permissions": {"allowed_tools": ["Read"], "permission_mode": "acceptEdits"}}


def test_project_good():
    assert schema.validate_project(GOOD_PROJECT) == []
    assert schema.validate_project({"name": "demo", "root": ROOT, "created": NOW}) == []


@pytest.mark.parametrize("change,field", [
    ({"name": None}, "name"),
    ({"root": "x"}, "root"),
    ({"created": "today"}, "created"),
    ({"template": "blank"}, "template"),
    ({"tz": "Mars/Olympus"}, "tz"),
    ({"step_timeout": "20 minutes"}, "step_timeout"),
    ({"max_attempts": 0}, "max_attempts"),
    ({"step_budget_usd": 0}, "step_budget_usd"),
    ({"permissions": {"allowed_tools": "Read"}}, "permissions.allowed_tools"),
    ({"permissions": {"permission_mode": "yolo"}}, "permissions.permission_mode"),
    ({"permissions": {"sandbox": True}}, "permissions.sandbox"),
    ({"budget": "5/day"}, "budget"),
])
def test_project_bad(change, field):
    d = dict(GOOD_PROJECT, **change)
    if change.get("name", 1) is None:
        del d["name"]
    assert field in fields(schema.validate_project(d))


def test_config():
    assert schema.validate_config({}) == []
    assert schema.validate_config(dict(schema.CONFIG_DEFAULTS)) == []
    assert fields(schema.validate_config({"max_concurrent": 0})) == ["max_concurrent"]
    assert fields(schema.validate_config({"tz": "UTC"})) == ["tz"]


def test_registry_entry():
    good = {"name": "demo", "path": "/abs/demo", "root": ROOT, "created": NOW}
    assert schema.validate_registry_entry(good, "demo") == []
    assert fields(schema.validate_registry_entry(good, "other")) == ["name"]
    assert fields(schema.validate_registry_entry(dict(good, path="rel"), "demo")) == ["path"]


def test_duration():
    assert schema.parse_duration("90s") == 90
    assert schema.parse_duration("20m") == 1200
    assert schema.parse_duration("2h") == 7200
    with pytest.raises(ValueError):
        schema.parse_duration("2d")


# --- journal --------------------------------------------------------------

def test_journal_records():
    v = schema.validate_journal_record
    assert v({"type": "note", "t": NOW, "msg": "hi"}) == []
    assert v({"type": "step-start", "t": NOW, "step": 1, "attempt": 1,
              "model": "m", "session_id": "s"}) == []
    assert fields(v({"type": "bogus", "t": NOW})) == ["type"]
    assert fields(v({"type": "note", "msg": "hi"})) == ["t"]
    assert fields(v({"type": "step-failed", "t": NOW, "step": 1, "attempt": 1})) == ["why"]
    assert fields(v([1, 2])) == [None]
    dec = {"state": "RUNNABLE", "resume_expr": "now", "wake_at": None, "reason": None,
           "model": "m", "summary": "s", "spawn": []}
    assert v({"type": "commit-begin", "t": NOW, "step": 1, "decision": dec}) == []
    bad = dict(dec, spawn=[{"name": "a", "wpid": "x"}])
    del bad["summary"]
    got = fields(v({"type": "commit-begin", "t": NOW, "step": 1, "decision": bad}))
    assert "decision.summary" in got and "decision.spawn[0].wpid" in got
    assert "decision.spawn[0].instruction" in got


def test_step_dirs():
    assert schema.parse_step_dir("0007") == (7, None)
    assert schema.parse_step_dir("12345") == (12345, None)
    assert schema.parse_step_dir("0007.failed-2") == (7, 2)
    assert schema.parse_step_dir("7") is None
    assert schema.step_dir_name(7) == "0007"
