"""Context size and session length (docs/context.md): C1 measure, C3 hook, C4 carry-over."""

import json
import os
import subprocess
import sys

import pytest

from test_executor import records, set_project, status
from conftest import make_project
from work_packet import ctxhook, executor, model
from work_packet.harness import claude


@pytest.fixture
def fresh(tmp_path, fake, monkeypatch):
    argv = tmp_path / "argv.jsonl"
    monkeypatch.setenv("WPK_FAKE_ARGV", str(argv))
    proj, root = make_project(tmp_path)
    return proj, root, argv


def calls(argv_file):
    with open(argv_file) as fp:
        return [json.loads(line) for line in fp]


def flag(argv, name):
    return argv[argv.index(name) + 1] if name in argv else None


def meta(root, n):
    with open(os.path.join(root.step_dir(n), "meta.json")) as fp:
        return json.load(fp)


# --- C1 ----------------------------------------------------------------------------

def test_transcript_context_per_call(tmp_path):
    u = {"input_tokens": 5, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 900}
    evs = [
        {"type": "assistant", "message": {"id": "a", "usage": u}},
        {"type": "assistant", "message": {"id": "a", "usage": u}},       # same call, split
        {"type": "assistant", "parent_tool_use_id": "t1",                 # subagent
         "message": {"id": "s", "usage": dict(u, cache_read_input_tokens=50000)}},
        {"type": "assistant", "message": {"id": "b", "usage": dict(u, cache_read_input_tokens=1900)}},
        {"type": "result", "subtype": "success", "is_error": False},
    ]
    p = tmp_path / "t.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in evs))
    res = claude.Claude().parse(str(p), model.StepResult())
    assert res.context == [1005, 2005]
    assert model.context_summary(res.context) == {"first": 1005, "peak": 2005, "last": 2005,
                                                   "calls": 2}
    assert model.context_summary([]) is None


def test_tokens_summed_over_results_with_cache_breaks(tmp_path):
    def call(i, read, write):
        return {"type": "assistant", "message": {"id": i, "usage": {
            "input_tokens": 1, "cache_creation_input_tokens": write,
            "cache_read_input_tokens": read}}}

    def result(out, think, w1h, ms):
        return {"type": "result", "subtype": "success", "is_error": False,
                "duration_api_ms": ms, "usage": {
                    "input_tokens": 2, "cache_creation_input_tokens": w1h,
                    "cache_read_input_tokens": 100, "output_tokens": out,
                    "output_tokens_details": {"thinking_tokens": think},
                    "cache_creation": {"ephemeral_1h_input_tokens": w1h,
                                       "ephemeral_5m_input_tokens": 0},
                    "server_tool_use": {"web_search_requests": 0}}}
    evs = [call("a", 0, 1000), call("b", 1000, 200), result(50, 20, 1200, 1500),
           call("c", 300, 1000), result(30, 10, 1000, 500)]       # a nudge; c is a break
    p = tmp_path / "t.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in evs))
    res = claude.Claude().parse(str(p), model.StepResult())
    assert res.tokens == {"input_tokens": 4, "cache_creation_input_tokens": 2200,
                          "cache_read_input_tokens": 200, "output_tokens": 80,
                          "thinking_tokens": 30, "cache_write_1h": 2200, "cache_write_5m": 0}
    assert (res.cache_breaks, res.cache_rewrite, res.api_s) == (1, 1000, 2.0)


def test_tokens_of_a_killed_run_come_from_its_messages(tmp_path):
    def call(i, read, write, sub=None):
        return {"type": "assistant", "parent_tool_use_id": sub, "message": {"id": i, "usage": {
            "input_tokens": 1, "cache_creation_input_tokens": write,
            "cache_read_input_tokens": read, "output_tokens": 3,
            "cache_creation": {"ephemeral_1h_input_tokens": write}}}}
    done = {"type": "result", "subtype": "success", "is_error": False, "usage": {
        "input_tokens": 2, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 9,
        "output_tokens": 40}}
    evs = [call("a", 0, 50), done,                       # the first run reported its usage
           call("b", 100, 20), call("b", 100, 20),       # one message over two events
           call("s", 0, 7, sub="t1")]                    # a subagent call, killed
    p = tmp_path / "t.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in evs))
    res = claude.Claude().parse(str(p), model.StepResult())
    assert res.tokens == {"input_tokens": 4, "cache_creation_input_tokens": 77,
                          "cache_read_input_tokens": 109, "output_tokens": 40,
                          "cache_write_1h": 27, "unreported_calls": 2}


def test_meta_records_context(fresh):
    proj, root, _ = fresh
    assert executor.step(proj).code == 0
    assert meta(root, 1)["context"] == {"first": 10010, "peak": 10510, "last": 10510, "calls": 2,
                                       "base": 10010, "cache_breaks": 0, "cache_rewrite": 0}


# --- C2 and C3: the command line ------------------------------------------------------

def test_system_prompt_and_hook_flags(fresh):
    proj, root, argv_file = fresh
    executor.step(proj)
    argv = calls(argv_file)[0]
    assert flag(argv, "--append-system-prompt-file") == os.path.join(root.step_dir(1),
                                                                      "system.md")
    hooks = json.loads(flag(argv, "--settings"))["hooks"]["PostToolUse"]
    cmd = hooks[0]["hooks"][0]["command"]
    assert hooks[0]["matcher"] == "*" and "ctxhook.py 80000 " in cmd
    assert cmd.endswith(" %s %s %s" % (os.path.join(root.step_dir(1), "ctxhook.fired"),
                                       os.path.join(root.path, "mailbox"),
                                       os.path.join(root.step_dir(1), "notes.seen")))
    assert "--resume" not in argv


def test_context_limit_zero_turns_off_the_warning(fresh):
    proj, root, argv_file = fresh
    set_project(proj, step_context_tokens=0)
    executor.step(proj)
    hooks = json.loads(flag(calls(argv_file)[0], "--settings"))["hooks"]
    assert "PreToolUse" in hooks                                  # the background guard stays
    # The hook stays for notes (interaction.md §6a), with the warning off.
    assert "ctxhook.py 0 " in hooks["PostToolUse"][0]["hooks"][0]["command"]


# --- C3: the hook itself ---------------------------------------------------------------

def _session(tmp_path, *sizes, sidechain=None):
    lines = [{"type": "user", "message": {"content": "x"}}]
    for i, n in enumerate(sizes):
        lines.append({"type": "assistant", "isSidechain": False, "message": {
            "id": "m%d" % i, "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0,
                                       "cache_read_input_tokens": n}}})
    if sidechain:
        lines.append({"type": "assistant", "isSidechain": True, "message": {
            "id": "s", "usage": {"cache_read_input_tokens": sidechain}}})
    p = tmp_path / "session.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in lines))
    return str(p)


def run_hook(tmp_path, transcript, limit=1000):
    marker = str(tmp_path / "fired")
    p = subprocess.run([sys.executable, claude.HOOK, str(limit), marker],
                       input=json.dumps({"transcript_path": transcript}),
                       capture_output=True, text=True)
    assert p.returncode == 0
    if not p.stdout:
        return None
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    return out["additionalContext"]


def test_hook_last_main_thread_call(tmp_path):
    assert ctxhook.last_context(_session(tmp_path, 100, 700, sidechain=99999)) == 700


def test_hook_fires_once_per_level(tmp_path):
    assert run_hook(tmp_path, _session(tmp_path, 500, 900)) is None
    msg = run_hook(tmp_path, _session(tmp_path, 1050))
    assert "about 1050 tokens (limit 1000)" in msg and "resume: now" in msg
    assert run_hook(tmp_path, _session(tmp_path, 1150)) is None
    assert "Stop now" in run_hook(tmp_path, _session(tmp_path, 1200))
    assert run_hook(tmp_path, _session(tmp_path, 3000)) is None


def test_hook_jumps_straight_to_hard(tmp_path):
    assert "Stop now" in run_hook(tmp_path, _session(tmp_path, 5000))
    assert run_hook(tmp_path, _session(tmp_path, 5100)) is None


def test_hook_never_fails(tmp_path):
    marker = str(tmp_path / "fired")
    for stdin in ("not json", json.dumps({"transcript_path": str(tmp_path / "missing")})):
        p = subprocess.run([sys.executable, claude.HOOK, "1000", marker], input=stdin,
                           capture_output=True, text=True)
        assert p.returncode == 0 and p.stdout == ""


# --- C4: carry-over ----------------------------------------------------------------------

def test_no_carry_by_default(fresh):
    proj, root, argv_file = fresh
    executor.step(proj)
    executor.step(proj)
    assert all("--resume" not in a for a in calls(argv_file))
    assert meta(root, 2)["carried_from"] is None


def test_carry_resumes_previous_session(fresh):
    proj, root, argv_file = fresh
    set_project(proj, carry_session=True)
    executor.step(proj)
    executor.step(proj)
    first, second = calls(argv_file)
    assert "--resume" not in first
    prev = meta(root, 1)["session_id"]
    assert flag(second, "--resume") == prev and "--fork-session" in second
    assert flag(second, "--session-id") != prev
    assert meta(root, 2)["carried_from"] == prev
    assert records(root, "step-start")[1]["carried_from"] == prev
    assert meta(root, 2)["context"]["base"] == meta(root, 1)["context"]["first"]
    assert "carried_from" not in records(root, "step-start")[0]


def test_carry_stops_after_ttl(fresh, monkeypatch):
    proj, root, argv_file = fresh
    set_project(proj, carry_session=True, carry_ttl="10m")
    executor.step(proj)
    monkeypatch.setenv("WPK_NOW", "2026-10-21T19:00:00Z")    # an hour after the step ended
    executor.step(proj)
    assert "--resume" not in calls(argv_file)[1]


def test_carry_stops_when_previous_step_was_full(fresh):
    proj, root, argv_file = fresh
    set_project(proj, carry_session=True, step_context_tokens=10500)   # fake peaks at 10510
    executor.step(proj)
    executor.step(proj)
    assert "--resume" not in calls(argv_file)[1]


def test_carry_stops_at_factor_of_base(fresh):
    proj, root, argv_file = fresh
    set_project(proj, carry_session=True, carry_factor=1.04)    # fake: 10510 / 10010 = 1.05
    executor.step(proj)
    executor.step(proj)
    assert "--resume" not in calls(argv_file)[1]


def test_carried_step_cost_is_a_delta():
    res = model.StepResult(cost_usd=0.0348)
    assert executor._step_cost(res, None) == 0.0348
    assert executor._step_cost(res, {"cost_usd": 0.0234}) == 0.0114
    assert executor._step_cost(res, {"cost_usd": 0.0114, "session_cost_usd": 0.0234}) == 0.0114
    assert executor._step_cost(model.StepResult(), {"cost_usd": 0.02}) is None


def test_carry_never_on_retry(fresh, fake):
    proj, root, argv_file = fresh
    set_project(proj, carry_session=True)
    executor.step(proj)
    fake(fault="crash")
    executor.step(proj)                     # step 2 attempt 1 fails
    fake()
    executor.step(proj)                     # step 2 attempt 2
    a1, a2 = calls(argv_file)[1:]
    assert "--resume" in a1 and "--resume" not in a2
    assert status(root)["step"] == 2


@pytest.mark.parametrize("key,value,msg", [
    ("step_context_tokens", -1, "integer >= 0"),
    ("carry_session", "yes", "true or false"),
    ("carry_ttl", "1d", "duration"),
    ("carry_factor", 1, "number > 1"),
    ("harness", "nope", "one of: claude"),
])
def test_config_keys_validated(key, value, msg):
    from work_packet import schema
    probs = schema.validate_config({key: value})
    assert probs and probs[0].field == key and msg in probs[0].msg


def test_time_warning_fires_once_after_warn_at(tmp_path):
    marker = str(tmp_path / "fired")
    env = {"WPK_STARTED_AT": "1000", "WPK_WARN_AT": "2260", "WPK_DEADLINE": "2800"}
    assert ctxhook.time_message(marker, env, 2000) is None
    m = ctxhook.time_message(marker, env, 2300)
    assert "about 8 of this step's 30 minutes are left" in m
    assert ctxhook.time_message(marker, env, 2400) is None
    assert ctxhook.time_message(marker, {}, 2400) is None


def test_time_warning_does_not_mute_the_context_warning(tmp_path):
    assert ctxhook.message(100, 100, {"time"})[0] == "soft"
