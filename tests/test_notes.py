"""Notes from the owner (docs/interaction.md §6a): inbox, hook, prompt, commit."""

import json
import os
import subprocess
import sys

import pytest

from conftest import make_project
from test_executor import records, status
from work_packet import actions, executor, notes
from work_packet.cli import main
from work_packet.harness import claude


@pytest.fixture
def fresh(tmp_path, fake):
    return make_project(tmp_path)


def prompt_of(root, n, a=None):
    return open(os.path.join(root.step_dir(n, a) if a else root.step_dir(n), "prompt.md")).read()


def test_inbox_basics(tmp_path):
    proj, root = make_project(tmp_path)
    with pytest.raises(ValueError):
        notes.add(root, "  ", "me")
    a = notes.add(root, "first", "me")
    b = notes.add(root, "second\n\nwith a gap", "you")
    assert [n["text"] for n in notes.queued(root)] == ["first", "second\n\nwith a gap"]
    text = notes.section(notes.queued(root))
    assert text.startswith("## Notes from the owner") and "  with a gap" in text
    assert "- you, %s:" % b["t"] in text
    notes.consume(root, [a["id"], "nope"])
    assert [n["id"] for n in notes.queued(root)] == [b["id"]]
    assert notes.section([]) == ""


def test_note_before_a_step_is_in_its_prompt_and_cleared_at_commit(fresh):
    proj, root = fresh
    out = actions.note(root, "Add a pytest.ini that limits collection to tests/.", by="me")
    assert out.code == 0 and "the next step shows it" in out.msg
    assert executor.step(proj).code == 0
    text = prompt_of(root, 1)
    assert "## Notes from the owner" in text and "Add a pytest.ini" in text
    assert notes.queued(root) == []
    (begin,) = records(root, "commit-begin")
    (n,) = begin["decision"]["notes"]
    assert n["text"].startswith("Add a pytest.ini") and n["how"] == "prompt" and n["by"] == "me"
    assert executor.step(proj).code == 0
    assert "Notes from the owner" not in prompt_of(root, 2)
    assert notes.of_step(root.step_dir(1), root, root.journal().records)[0]["text"] \
        .startswith("Add a pytest.ini")


def test_note_mid_step_reaches_the_hook(fresh, monkeypatch):
    proj, root = fresh
    monkeypatch.setenv("WPK_FAKE_NOTE", "Stop running the fuzz test.")
    assert executor.step(proj).code == 0
    with open(os.path.join(root.step_dir(1), "transcript.jsonl")) as fp:
        evs = [json.loads(ln) for ln in fp]
    (hooked,) = [e["fake_hook_context"] for e in evs if "fake_hook_context" in e]
    assert "a note from the task's owner (tester" in hooked
    assert "Stop running the fuzz test." in hooked
    seen = notes.seen(root.step_dir(1))
    assert seen["20990101T000000-mid"][0] == "hook"
    (begin,) = records(root, "commit-begin")
    assert [n["how"] for n in begin["decision"]["notes"]] == ["hook"]
    assert notes.queued(root) == []


def test_a_failed_attempt_keeps_its_notes_for_the_retry(fresh, fake):
    proj, root = fresh
    actions.note(root, "Mind the build directory.", by="me")
    fake(fault="bad-memento")
    assert executor.step(proj).code == 1
    assert len(notes.queued(root)) == 1
    fake(fault=None)
    assert executor.step(proj).code == 0
    assert "Mind the build directory." in prompt_of(root, 1)
    assert notes.queued(root) == []


def test_hook_with_no_limit_sends_notes_once(tmp_path):
    inbox, seen = tmp_path / "mailbox", tmp_path / "notes.seen"
    inbox.mkdir()
    (inbox / "a.json").write_text(json.dumps({"id": "a", "t": "T", "by": "me", "text": "hi"}))

    def run():
        p = subprocess.run([sys.executable, claude.HOOK, "0", os.devnull, str(inbox), str(seen)],
                           input=json.dumps({"transcript_path": os.devnull}),
                           capture_output=True, text=True)
        assert p.returncode == 0
        return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout else None
    assert "hi" in run()
    assert run() is None
    assert seen.read_text().startswith("a hook ")


def test_hook_settings_with_notes_only():
    h = json.loads(claude.hook_settings(0, None, ("/in", "/seen")))["hooks"]
    cmd = h["PostToolUse"][0]["hooks"][0]["command"]
    assert "ctxhook.py 0 /dev/null /in /seen" in cmd
    assert "PostToolUse" not in json.loads(claude.hook_settings(0, None))["hooks"]


def test_wake_and_the_cli(fresh, capsys):
    proj, root = fresh
    meta, body = root.load_status()
    meta.update(state="SLEEPING", wake_at="2099-01-01T00:00:00Z")
    root.save_status(meta, body)
    assert main(["note", root.path, "-m", "Wake up."]) == 0
    assert "SLEEPING until 2099" in capsys.readouterr().err
    assert status(root)["state"] == "SLEEPING"
    assert main(["note", root.path, "-m", "Now.", "--wake"]) == 0
    assert status(root)["state"] == "RUNNABLE"
    assert records(root, "admin")[-1]["op"] == "wake"
    assert main(["note", root.path, "-m", " "]) != 0
    assert len(notes.queued(root)) == 2


def test_paused_packet_keeps_the_note(fresh):
    proj, root = fresh
    executor.admin(root, "pause")
    out = actions.note(root, "Later.", by="me")
    assert out.code == 0 and "until it is handed off" in out.msg
