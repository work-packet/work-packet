"""Harness adapters (docs/harness.md H1): the executor follows the adapter's caps."""

import json
import os

import pytest

from conftest import make_project
from test_context import calls, meta
from test_executor import set_project
from work_packet import executor, harness, model, prompt
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


class _EP:
    def __init__(self, name, value, load):
        self.name, self.value, self._load = name, value, load

    def load(self):
        return self._load()


class Fake(harness.Harness):
    name = "fake"


def _boom():
    raise ImportError("no module named fake_site")


@pytest.fixture
def plugin_harnesses(monkeypatch):
    import importlib.metadata
    eps = [_EP("fake", "site:Fake", lambda: Fake),
           _EP("bad", "site:Bad", _boom),
           _EP("notone", "site:x", lambda: object),
           _EP("claude", "site:Claude", lambda: Fake)]
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda group=None: eps if group == harness.GROUP else [])
    harness._reset()
    yield
    harness._reset()


def test_plugin_harness_from_entry_point(plugin_harnesses):
    assert harness.names() == ["claude", "codex", "fake"]
    assert isinstance(harness.get("fake"), Fake)
    assert isinstance(harness.get("claude"), claude.Claude)    # a built-in keeps its name


def test_broken_plugin_harness_is_reported(plugin_harnesses):
    b = harness.broken()
    assert set(b) == {"bad", "notone", "claude"}
    assert "fake_site" in b["bad"] and "not a Harness" in b["notone"]
    with pytest.raises(KeyError, match="did not load.*fake_site"):
        harness.get("bad")
    from work_packet import setup
    titles = [c.title for c in setup._tools() if c.id.startswith("tools.harness.")]
    assert titles == ["harness plugin bad not loaded", "harness plugin claude not loaded",
                      "harness plugin notone not loaded"]


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


# --- [harnesses.<name>] env and env_file (docs/harness.md) ---------------------

def _home(tmp_path, monkeypatch, config):
    h = tmp_path / "home-env"
    h.mkdir()
    (h / "config.toml").write_text(config)
    monkeypatch.setenv("WPK_HOME", str(h))
    return h


def _secret(path, text, mode=0o600):
    path.write_text(text)
    os.chmod(path, mode)


def test_no_harness_table_keeps_todays_env(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, "")
    monkeypatch.delenv("CLAUDE_CODE_PROMPT_CACHE_TTL", raising=False)
    assert claude.Claude().env(None) == {"CLAUDE_CODE_PROMPT_CACHE_TTL": "1h"}


def test_env_then_env_file_over_it(tmp_path, monkeypatch):
    h = _home(tmp_path, monkeypatch,
              '[harnesses.claude]\nenv_file = "claude.env"\n'
              '[harnesses.claude.env]\nANTHROPIC_BASE_URL = "https://gw.example/v1"\n'
              'A = "from-env"\nCLAUDE_CODE_PROMPT_CACHE_TTL = "5m"\n')
    _secret(h / "claude.env", '# key\nexport A="from-file"\nANTHROPIC_API_KEY=sk-x\n\n')
    got = claude.Claude().env(None)
    assert got == {"CLAUDE_CODE_PROMPT_CACHE_TTL": "5m", "A": "from-file",
                   "ANTHROPIC_BASE_URL": "https://gw.example/v1", "ANTHROPIC_API_KEY": "sk-x"}


def test_env_is_per_harness(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, '[harnesses.codex.env]\nOPENAI_BASE_URL = "x"\n')
    assert "OPENAI_BASE_URL" not in claude.Claude().env(None)
    assert harness.home_env("codex") == {"OPENAI_BASE_URL": "x"}


def test_env_file_readable_by_others_is_refused(tmp_path, monkeypatch):
    h = _home(tmp_path, monkeypatch, '[harnesses.claude]\nenv_file = "claude.env"\n')
    _secret(h / "claude.env", "ANTHROPIC_API_KEY=sk-x\n", 0o644)
    said = []
    assert harness.home_env("claude", warn=said.append) == {}
    assert "must be 0600" in said[0] and "sk-x" not in said[0]


def test_env_file_missing_or_bad_is_warned(tmp_path, monkeypatch):
    h = _home(tmp_path, monkeypatch, '[harnesses.claude]\nenv_file = "~nobody-here/x.env"\n'
              '[harnesses.claude.env]\nB = "1"\n')
    said = []
    assert harness.home_env("claude", warn=said.append) == {"B": "1"}
    assert "not used" in said[0]
    _secret(h / "bad.env", "no equals sign\n")
    cfg = {"harnesses": {"claude": {"env_file": str(h / "bad.env")}}}
    said = []
    assert harness.home_env("claude", cfg=cfg, warn=said.append) == {}
    assert "line 1" in said[0]


def test_harness_table_validated():
    from work_packet import schema
    ok = {"harnesses": {"claude": {"env": {"A": "1"}, "env_file": "x"}}}
    assert schema.validate_config(ok) == []
    bad = [p.field for p in schema.validate_config(
        {"harnesses": {"claude": {"env": {"A": 1}, "env_file": "", "other": 1}}})]
    assert bad == ["harnesses.claude.other", "harnesses.claude.env", "harnesses.claude.env_file"]
    assert [p.field for p in schema.validate_config({"harnesses": {"claude": 1}})] == ["harnesses"]


def test_step_gets_home_env(fresh, monkeypatch, tmp_path):
    proj, root, argv = fresh
    with open(tmp_path / "wpk-home" / "config.toml", "a") as f:
        f.write('[harnesses.claude.env]\nWPK_TEST_ROUTE = "gateway"\n')
    seen = {}
    real = executor._model

    def spy(pkt, st, h, spec, env, *a, **kw):
        seen.update(env)
        return real(pkt, st, h, spec, env, *a, **kw)
    monkeypatch.setattr(executor, "_model", spy)
    executor.step(proj)
    assert seen.get("WPK_TEST_ROUTE") == "gateway"


def test_meta_records_route_not_key(fresh, tmp_path):
    proj, root, argv = fresh
    with open(tmp_path / "wpk-home" / "config.toml", "a") as f:
        f.write('[harnesses.claude.env]\nANTHROPIC_BASE_URL = "https://gw.example:8443/v1"\n'
                'ANTHROPIC_API_KEY = "sk-secret"\n')
    executor.step(proj)
    text = open(os.path.join(root.step_dir(1), "meta.json")).read()
    assert json.loads(text)["route"] == {"account": "subscription", "host": "gw.example"}
    assert "sk-secret" not in text


def test_route_account_from_init_event(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "system", "subtype": "init", "session_id": "s",
                             "apiKeySource": "ANTHROPIC_API_KEY"}) + "\n")
    res = claude.Claude().parse(str(t), model.StepResult())
    assert res.account == "key"
    h = claude.Claude()
    assert executor._route(h, {}, model.StepResult()) == {"account": "unknown", "host": "default"}


# --- Codex (UNVERIFIED event names; see harness/codex.py) --------------------------

CODEX_TRANSCRIPT = [
    {"type": "thread.started", "thread_id": "0199-thread"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "i0", "type": "reasoning", "text": "thinking"}},
    {"type": "item.completed", "item": {"id": "i1", "type": "command_execution",
                                        "command": "ls", "exit_code": 0}},
    {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "Done."}},
    {"type": "turn.completed", "usage": {"input_tokens": 12000, "cached_input_tokens": 9000,
                                         "output_tokens": 800, "reasoning_output_tokens": 300}},
]


def _codex_parse(tmp_path, events, account=None):
    from work_packet.harness import codex
    t = tmp_path / "t.jsonl"
    t.write_text("".join(json.dumps(e) + "\n" for e in events) + "not json\n")
    h = codex.Codex()
    h.account = account
    return h.parse(str(t), model.StepResult(exit_code=0))


def test_codex_registered():
    h = harness.get("codex")
    assert h.base_url_var == "OPENAI_BASE_URL"
    assert not h.caps.system_slot and not h.caps.resume and not h.caps.reports_cost


def test_codex_command(monkeypatch):
    monkeypatch.delenv("WPK_CODEX", raising=False)
    spec = harness.StepSpec(model="gpt-5-codex", session_id="s", permission_mode="acceptEdits",
                            allowed_tools=["Read"], budget_usd=1.0, add_dirs=["/w"])
    argv = harness.get("codex").command(spec)
    assert argv[:3] == ["codex", "exec", "--json"] and argv[-1] == "-"
    assert argv[argv.index("--model") + 1] == "gpt-5-codex"
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("--add-dir") + 1] == "/w"
    spec.permission_mode = "bypassPermissions"
    assert "--dangerously-bypass-approvals-and-sandbox" in harness.get("codex").command(spec)


def test_codex_parse(tmp_path):
    res = _codex_parse(tmp_path, CODEX_TRANSCRIPT, account="subscription")
    assert res.failure() is None
    assert res.session_id == "0199-thread" and res.text == "Done."
    assert res.tokens == {"input_tokens": 3000, "cache_read_input_tokens": 9000,
                          "output_tokens": 800, "thinking_tokens": 300}
    assert res.context == [12000] and res.cost_usd is None
    assert res.account == "subscription"


def test_codex_failed_turn(tmp_path):
    res = _codex_parse(tmp_path, CODEX_TRANSCRIPT[:2] + [
        {"type": "turn.failed", "error": {"message": "stream disconnected"}}])
    assert res.is_error and "stream disconnected" in res.failure()
    res = _codex_parse(tmp_path, CODEX_TRANSCRIPT[:2])
    assert res.failure() == "transcript has no result event"


def test_codex_account_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path))
    for v in ("CODEX_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    h = harness.get("codex")
    h.env(None)
    assert h.account == "subscription"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    h.env(None)
    assert h.account == "key"
    assert executor._route(h, {"OPENAI_BASE_URL": "https://gw.example/v1"},
                           model.StepResult(account=h.account)) == {"account": "key",
                                                                     "host": "gw.example"}
