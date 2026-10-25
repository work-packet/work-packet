"""Profiles (docs/harness.md H2): choice, precedence, sizing text, validation."""

import json
import os

import pytest

from conftest import make_project
from test_context import calls, flag, meta
from test_executor import set_project
from work_packet import executor, profiles, schema


@pytest.fixture
def fresh(tmp_path, fake, monkeypatch):
    argv = tmp_path / "argv.jsonl"
    monkeypatch.setenv("WPK_FAKE_ARGV", str(argv))
    proj, root = make_project(tmp_path)
    return proj, root, argv, tmp_path / "wpk-home"


def write_config(home, text):
    home.mkdir(exist_ok=True)
    (home / "config.toml").write_text(text)


def hook_limit(argv):
    cmd = json.loads(flag(argv, "--settings"))["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    args = cmd.split()
    return int(args[[a.endswith("ctxhook.py") for a in args].index(True) + 1])


FAST = """
[profiles.fast]
version = 2
harness = "claude"
models = ["claude-haiku-*"]
sizing = "persistent"
step_context_tokens = 5000
"""


def test_builtin_choice():
    ps = profiles.load()
    assert profiles.select(ps, "claude", "claude-haiku-4-5-20251001").id == "claude-haiku@1"
    assert profiles.select(ps, "claude", "claude-sonnet-5").id == "claude@1"
    with pytest.raises(profiles.ProfileError):
        profiles.select(ps, "codex", "gpt-5")


def test_default_step_records_profile_and_bounded_sizing(fresh):
    proj, root, _, _ = fresh
    executor.step(proj)
    assert meta(root, 1)["profile"] == "claude-haiku@1"
    system = open(os.path.join(root.step_dir(1), "system.md")).read()
    assert "Do one step's worth of work" in system
    assert system.index("## How much to do") < system.index("## Claude Code")


def test_config_profile_comes_first_and_sets_values(fresh):
    proj, root, argv_file, home = fresh
    write_config(home, FAST)
    executor.step(proj)
    assert meta(root, 1)["profile"] == "fast@2"
    system = open(os.path.join(root.step_dir(1), "system.md")).read()
    assert "Carry out this step's instruction completely" in system
    assert "Do one step's worth" not in system
    assert hook_limit(calls(argv_file)[0]) == 5000


def test_toml_keys_win_over_profile(fresh):
    proj, root, argv_file, home = fresh
    write_config(home, "step_context_tokens = 6000\n" + FAST)
    executor.step(proj)
    assert hook_limit(calls(argv_file)[0]) == 6000
    set_project(proj, step_context_tokens=7000)
    executor.step(proj)
    assert hook_limit(calls(argv_file)[1]) == 7000


def test_project_names_profile(fresh):
    proj, root, _, home = fresh
    write_config(home, FAST)
    set_project(proj, profile="claude")
    executor.step(proj)
    assert meta(root, 1)["profile"] == "claude@1"


def test_unknown_profile_is_a_usage_error(fresh):
    proj, root, _, _ = fresh
    set_project(proj, profile="nope")
    out = executor.step(proj)
    assert out.code == executor.USAGE and "no profile named 'nope'" in out.msg
    assert root.load_status()[0]["attempts"] == 0


@pytest.mark.parametrize("table,msg", [
    ({"version": 1, "harness": "claude", "models": ["*"]}, "sizing"),
    ({"version": 0, "harness": "claude", "models": ["*"], "sizing": "bounded"}, "version"),
    ({"version": 1, "harness": "nope", "models": ["*"], "sizing": "bounded"}, "harness"),
    ({"version": 1, "harness": "claude", "models": [], "sizing": "bounded"}, "models"),
    ({"version": 1, "harness": "claude", "models": ["*"], "sizing": "bounded",
      "price": {"input": 1}}, "price"),
    ({"version": 1, "harness": "claude", "models": ["*"], "sizing": "bounded", "x": 1},
     "unknown key"),
])
def test_profile_validation(table, msg):
    probs = schema.validate_config({"profiles": {"p": table}})
    assert probs and probs[0].field == "profiles.p" and msg in probs[0].msg
