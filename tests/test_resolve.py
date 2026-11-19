"""wpk resolve: a fresh session that talks a packet's questions through (docs/question-ux-plan.md §2)."""

import io

import pytest

from conftest import make_project
from work_packet import executor, resolve
from work_packet.cli import main
from work_packet.project import project_of


@pytest.fixture
def multi(tmp_path, fake):
    fake("multi_asker")
    proj, root = make_project(tmp_path)
    executor.step(proj)
    return proj, root


def test_brief_has_the_questions_in_full_and_where_to_look(multi):
    proj, root = multi
    text = resolve.brief(root, project_of(root.path), "wpk")
    assert "waiting for my answers to 2 questions" in text
    assert "cadence: One commit per item, or per sub-item?" in text
    assert "      Every commit is reviewed on its own." in text      # the premise
    assert "if per sub-item: twice as many commits" in text
    assert "## What the agent plans to do after the answers" in text
    assert "Act on the answers." in text
    assert root.step_dir(1) in text and root.state_dir in text
    assert "wpk answer %s id=answer ... --note-file -" % root.wpid in text
    assert "Ids: `bash`, `cadence`." in text


def test_argv_puts_the_mode_in_the_system_prompt(multi):
    proj, root = multi
    p = project_of(root.path)
    a = resolve.argv("/bin/claude", "claude", root, p)
    assert a[:2] == ["/bin/claude", "--append-system-prompt"]
    assert "# Question resolution" in a[2] and a[3] == resolve.brief(root, p)
    c = resolve.argv("/bin/codex", "codex", root, p)
    assert len(c) == 2 and c[1].startswith("# Question resolution") and "cadence" in c[1]


def test_resolve_print_and_nothing_to_resolve(multi, capsys):
    proj, root = multi
    assert main(["resolve", root.path, "--print"]) == 0
    assert "Help me understand and answer them." in capsys.readouterr().out
    assert main(["answer", root.path, "-r"]) == 0
    capsys.readouterr()
    assert main(["resolve", root.path, "--print"]) == 0
    assert "has no open questions" in capsys.readouterr().out
    assert resolve.brief(root, project_of(root.path)) is None


def test_answer_note_from_stdin(multi, monkeypatch):
    proj, root = multi
    monkeypatch.setattr("sys.stdin", io.StringIO("The premise is wrong: squash instead.\n"))
    assert main(["answer", root.path, "bash=yes", "cadence=see note", "--note-file", "-"]) == 0
    h = [r for r in root.journal().records if r["type"] == "handoff"][-1]
    assert h["answers"] == {"bash": "yes", "cadence": "see note"}
    assert h["note"].strip() == "The premise is wrong: squash instead."
