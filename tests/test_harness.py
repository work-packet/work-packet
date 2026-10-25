"""Harness adapters (docs/harness.md H1): the executor follows the adapter's caps."""

import json
import os

import pytest

from conftest import make_project
from test_context import calls, meta
from test_executor import set_project
from work_packet import executor, harness, prompt
from work_packet.harness import claude


class Plain(claude.Claude):
    """Claude Code's command line, but claiming none of the optional features."""
    name = "plain"
    caps = harness.Caps()


@pytest.fixture
def fresh(tmp_path, fake, monkeypatch):
    argv = tmp_path / "argv.jsonl"
    monkeypatch.setenv("WPK_FAKE_ARGV", str(argv))
    monkeypatch.setitem(harness._REGISTRY, "plain", Plain)
    (tmp_path / "wpk-home").mkdir(exist_ok=True)
    (tmp_path / "wpk-home" / "config.toml").write_text(
        '[profiles.plain]\nversion = 1\nharness = "plain"\nmodels = ["*"]\nsizing = "bounded"\n')
    proj, root = make_project(tmp_path)
    return proj, root, argv


def test_registry():
    assert "claude" in harness.names()
    assert isinstance(harness.get("claude"), claude.Claude)
    with pytest.raises(KeyError):
        harness.get("nope")


def test_claude_notes_in_system_prompt(fresh):
    proj, root, _ = fresh
    executor.step(proj)
    system = open(os.path.join(root.step_dir(1), "system.md")).read()
    assert "## Claude Code" in system and "Read a\n`.pending/state/` file" in system
    assert meta(root, 1)["harness"] == "claude"


def test_no_harness_notes_for_other_harness():
    assert "## Claude Code" not in prompt.system("UTC", "plain")


def test_without_caps_the_executor_falls_back(fresh):
    proj, root, argv_file = fresh
    set_project(proj, harness="plain", carry_session=True)
    executor.step(proj)
    executor.step(proj)
    for argv in calls(argv_file):
        assert "--append-system-prompt-file" not in argv      # no system slot
        assert "PostToolUse" not in " ".join(argv)            # no injection
        assert "--resume" not in argv                         # no resume
    text = open(os.path.join(root.step_dir(2), "prompt.md")).read()
    assert text.startswith("You are running one step")   # prompt.md is what was sent
    m = meta(root, 2)
    assert m["harness"] == "plain" and m["carried_from"] is None


def test_without_system_slot_protocol_goes_in_the_prompt(fresh, monkeypatch):
    proj, root, _ = fresh
    set_project(proj, harness="plain")
    sent = {}
    real = executor.model.run

    def spy(argv, text, *a, **kw):
        sent["text"] = text
        return real(argv, text, *a, **kw)
    monkeypatch.setattr(executor.model, "run", spy)
    executor.step(proj)
    assert sent["text"].startswith("You are running one step of a work packet")
    assert "## Instruction for this step" in sent["text"]


def test_carry_not_across_harnesses(fresh):
    proj, root, argv_file = fresh
    set_project(proj, carry_session=True)
    executor.step(proj)
    path = os.path.join(root.step_dir(1), "meta.json")
    m = json.load(open(path))
    m["harness"] = "other"
    open(path, "w").write(json.dumps(m))
    executor.step(proj)
    assert "--resume" not in calls(argv_file)[1]


def _rate(five, week, reset=1793124000):
    return {"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed", "rateLimitType": "five_hour", "unifiedWindows": {
            "five_hour": {"utilization": five, "resetsAt": 1792867800},
            "seven_day": {"utilization": week, "resetsAt": reset}}}}


def test_quota_from_rate_limit_events(tmp_path):
    from work_packet import model
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in [
        _rate(0.41, 0.37), {"type": "rate_limit_event", "rate_limit_info": "junk"},
        _rate(0.56, 0.39), {"type": "result", "total_cost_usd": 0.1}]) + "\n")
    res = claude.Claude().parse(str(p), model.StepResult())
    assert res.quota == {"five_hour": {"first": 0.41, "last": 0.56, "resets_at": 1792867800},
                         "seven_day": {"first": 0.37, "last": 0.39, "resets_at": 1793124000}}


def test_no_quota_without_rate_limit_events(tmp_path):
    from work_packet import model
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"type": "result", "total_cost_usd": 0.1}) + "\n")
    assert claude.Claude().parse(str(p), model.StepResult()).quota == {}
