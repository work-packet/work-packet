"""wpk's Claude Code hooks in a packet folder (docs/collaboration.md §4.3, §10):
merged into ``.claude/settings.local.json``, never replacing anyone's."""

import json
import os
import subprocess

import pytest

from work_packet import sessionhooks as sh

MINE = {"permissions": {"allow": ["Bash(make *)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}],
                  "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
                                                                "command": "guard.sh"}]}]}}


def _read(folder):
    return json.load(open(os.path.join(folder, sh.REL)))


def test_install_into_an_empty_folder(tmp_path):
    f = str(tmp_path)
    assert sh.status(f) == "missing"
    assert sh.install(f, python="/py") == "installed"
    d = _read(f)
    assert set(d["hooks"]) == set(sh.EVENTS)
    assert d["hooks"]["Stop"][0]["hooks"][0]["command"] == "/py -m work_packet.hookcmd Stop"
    assert d["hooks"]["PermissionRequest"][0]["matcher"] == "*"
    assert "matcher" not in d["hooks"]["SessionStart"][0]
    assert sh.status(f, python="/py") == "installed"
    assert sh.install(f, python="/py") == "unchanged"


def test_your_settings_and_hooks_are_kept(tmp_path):
    f = str(tmp_path)
    os.makedirs(os.path.join(f, ".claude"))
    with open(os.path.join(f, sh.REL), "w") as fp:
        json.dump(MINE, fp)
    sh.install(f, python="/py")
    d = _read(f)
    assert d["permissions"] == MINE["permissions"]
    assert d["hooks"]["PreToolUse"] == MINE["hooks"]["PreToolUse"]
    assert d["hooks"]["Stop"][0] == MINE["hooks"]["Stop"][0] and len(d["hooks"]["Stop"]) == 2
    # a new interpreter replaces ours, not yours
    assert sh.status(f, python="/other") == "modified"
    sh.install(f, python="/other")
    d = _read(f)
    assert len(d["hooks"]["Stop"]) == 2 and "/other" in d["hooks"]["Stop"][1]["hooks"][0]["command"]
    assert sh.uninstall(f) == "removed"
    assert _read(f) == MINE


def test_uninstall_removes_a_file_that_held_only_ours(tmp_path):
    f = str(tmp_path)
    sh.install(f)
    assert sh.uninstall(f) == "removed"
    assert not os.path.exists(os.path.join(f, sh.REL))
    assert sh.uninstall(f) == "unchanged"


def test_a_broken_settings_file_is_left_alone(tmp_path):
    f = str(tmp_path)
    os.makedirs(os.path.join(f, ".claude"))
    with open(os.path.join(f, sh.REL), "w") as fp:
        fp.write("{ not json")
    with pytest.raises(sh.HooksError):
        sh.install(f)
    assert open(os.path.join(f, sh.REL)).read() == "{ not json"
    assert sh.status(f) == "unreadable"
    assert "not valid JSON" in sh.ensure([f], {})[f]


def test_in_a_clone_it_is_excluded_from_git(tmp_path):
    f = str(tmp_path / "clone")
    subprocess.run(["git", "init", "-q", f], check=True)
    sh.install(f)
    out = subprocess.run(["git", "-C", f, "status", "--porcelain"], capture_output=True,
                         text=True, check=True).stdout
    assert out == ""
    assert "/.claude/settings.local.json" in open(os.path.join(f, ".git", "info", "exclude")).read()


def test_the_switch(tmp_path):
    home, f = str(tmp_path / "home"), str(tmp_path / "f")
    os.makedirs(f)
    assert sh.enabled({}) and not sh.enabled({"hooks": False})
    sh.set_enabled(home, False, "me")
    assert not sh.enabled({"hooks": True}, home)
    sh.install(f)
    assert sh.ensure([f], {}, home=home)[f] == "removed"
    sh.set_enabled(home, True)
    assert sh.ensure([f], {"hooks": False}, home=home)[f] == "installed"
