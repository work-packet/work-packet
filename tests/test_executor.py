import json
import os
import shutil
import socket

import pytest
import tomli_w

from conftest import NOW, ROOT, child_wpid, make_project
from work_packet import executor
from work_packet.check import check
from work_packet.cli import main
from work_packet.packet import Packet

STEP_FILES = {"prompt.md", "system.md", "transcript.jsonl", "stderr.log", "meta.json", "result.md",
              "summary.md", "state.diff"}


def records(pkt, *types):
    return [r for r in pkt.journal().records if not types or r["type"] in types]


def status(pkt):
    return pkt.load_status()[0]


def count(pkt):
    with open(os.path.join(pkt.state_dir, "count.md")) as fp:
        return int(fp.read())


def set_project(proj, **kw):
    path = os.path.join(proj, "project.toml")
    from work_packet.tomlio import load_toml
    d = load_toml(path)
    d.update(kw)
    with open(path, "wb") as fp:
        tomli_w.dump(d, fp)


def assert_clean(proj):
    rep = check(proj)
    assert rep.issues == [], [str(i) for i in rep.issues]


def tree(path):
    """{relpath: bytes or link} under ``path``."""
    out = {}
    for d, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, path)
            if os.path.islink(p):
                out[rel] = "-> " + os.readlink(p)
            elif os.path.isfile(p):
                with open(p, "rb") as fp:
                    out[rel] = fp.read()
    return out


@pytest.fixture
def fresh(tmp_path, fake):
    return make_project(tmp_path)


def test_one_step_commits(fresh):
    proj, root = fresh
    out = executor.step(proj)
    assert out.code == 0, out.msg
    st = status(root)
    assert (st["state"], st["step"], st["attempts"], st["resume_expr"]) == \
        ("RUNNABLE", 1, 0, "now")
    assert count(root) == 1
    assert set(os.listdir(root.step_dir(1))) == STEP_FILES
    assert [r["type"] for r in records(root)] == ["step-start", "commit-begin", "commit-end"]
    end = records(root, "commit-end")[0]
    assert end["cost_usd"] == 0.0012 and end["tokens"]["output_tokens"] == 120
    meta = json.load(open(os.path.join(root.step_dir(1), "meta.json")))
    assert meta["exit_code"] == 0 and meta["session_id"] == records(root, "step-start")[0][
        "session_id"]
    diff = open(os.path.join(root.step_dir(1), "state.diff")).read()
    assert "-0\n+1\n" in diff and "a/state/count.md" in diff
    assert "Count is 1" in root.load_status()[1]
    assert not os.path.exists(root.pending_dir) and not os.path.exists(root.lease_path)
    assert_clean(proj)


def test_prompt_contents(fresh):
    proj, root = fresh
    executor.step(proj)
    executor.step(proj)
    text = open(os.path.join(root.step_dir(2), "prompt.md")).read()
    assert "Step 2, attempt 1 of 3" in text
    assert "Count is 1" in text                    # last summary
    assert "Read state/count.md" in text           # the instruction
    assert "$" not in text and "Write **only**" not in text
    system = open(os.path.join(root.step_dir(2), "system.md")).read()
    assert "Write **only**" in system and "Keeping the context small" in system
    assert "$" not in system and "(no offset: UTC)" in system
    assert NOW in text
    assert "## State files\n\n- `state/count.md`:\n\n```\n1\n```" in text


def test_state_files_section(tmp_path):
    from work_packet.prompt import FILE_MAX, state_files
    d = tmp_path / "state"
    assert state_files(str(d)) == "`state/` is empty."
    (d / "sub").mkdir(parents=True)
    (d / "a.md").write_text("has ``` inside\n")
    (d / "big.txt").write_text("x" * (FILE_MAX + 1))
    (d / "bin.dat").write_bytes(b"\xff\xfe\x00")
    (d / "sub" / "n.md").write_text("no newline")
    (d / "empty.md").write_text("")
    got = state_files(str(d))
    assert "- `state/a.md`:\n\n````\nhas ``` inside\n````" in got
    assert "- `state/big.txt` (%d bytes, not shown)" % (FILE_MAX + 1) in got
    assert "- `state/bin.dat` (3 bytes, not shown)" in got
    assert "- `state/sub/n.md` (10 bytes, not shown)" in got
    assert "- `state/empty.md`:\n\n```\n```" in got
    assert got.index("a.md") < got.index("empty.md") < got.index("sub/n.md")


def test_state_files_env_and_outline_first_archive_hidden(tmp_path):
    from work_packet.prompt import state_files
    d = tmp_path / "state"
    (d / "archive" / "old").mkdir(parents=True)
    (d / "a.md").write_text("a\n")
    (d / "outline.md").write_text("- [ ] 1\n")
    (d / "env.md").write_text("PATH=x\n")
    (d / "archive" / "questions.md").write_text("answered\n")
    (d / "archive" / "old" / "q.md").write_text("answered\n")
    got = state_files(str(d))
    assert got.index("env.md") < got.index("outline.md") < got.index("a.md")
    assert "answered" not in got
    assert "- `state/archive/`: 2 files, not shown" in got
    (d / "a.md").unlink(); (d / "outline.md").unlink(); (d / "env.md").unlink()
    assert state_files(str(d)) == "- `state/archive/`: 2 files, not shown"


def test_step_passes_settings_to_model(fresh, monkeypatch, tmp_path):
    proj, root = fresh
    set_project(proj, step_budget_usd=0.25,
                permissions={"allowed_tools": ["Read", "Bash(git log *)", "Bash(ls)"],
                             "permission_mode": "plan"})
    seen = {}
    real = executor.model.run

    def spy(argv, *a, **kw):
        seen["argv"] = argv
        seen["env"] = a[2]
        return real(argv, *a, **kw)
    monkeypatch.setattr(executor.model, "run", spy)
    assert executor.step(proj).code == 0
    argv = seen["argv"]
    assert argv[argv.index("--max-budget-usd") + 1] == "0.25"
    assert argv[argv.index("--allowedTools") + 1] == "Read,Bash(git log *),Bash(ls)"
    assert argv[argv.index("--tools") + 1] == "Read,Bash"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv and "--disable-slash-commands" in argv
    assert argv[argv.index("--permission-mode") + 1] == "plan"
    assert argv[argv.index("--model") + 1] == status(root)["model"]
    assert seen["env"]["WPK_WPID"] == ROOT and seen["env"]["WPK_STEP"] == "1"


def test_runs_to_completion_and_spawns(fresh):
    """E1 with the fake model."""
    proj, root = fresh
    for _ in range(20):
        if status(root)["state"] != "RUNNABLE":
            break
        assert executor.step(proj).code == 0
    st = status(root)
    assert (st["state"], st["step"], count(root)) == ("COMPLETED", 8, 8)
    kid = child_wpid(ROOT, 8, 0)
    assert st["children"] == [kid]
    child = Packet(os.path.join(proj, "packets", kid))
    assert os.readlink(os.path.join(root.children_dir, kid)) == os.path.join("..", "..", kid)
    cs = status(child)
    assert (cs["parent"], cs["spawn_key"], cs["step"]) == (ROOT, "%s:8:0" % ROOT, 0)
    assert executor.step(root.path).code == 2          # COMPLETED
    assert executor.step(child.path).code == 0
    assert open(os.path.join(child.state_dir, "p.md")).read() == "Hello World\n"
    assert status(child)["state"] == "COMPLETED"
    assert len(os.listdir(os.path.join(proj, "packets"))) == 2
    assert_clean(proj)


@pytest.mark.parametrize("fault,why", [
    ("crash", "exited with status 1"),
    ("error", "reported an error"),
    ("bad-memento", ".pending/memento.md"),
    ("no-summary", "summary.md"),
    ("bad-resume", "Stage 2"),
])
def test_failed_attempt(fresh, fake, fault, why):
    proj, root = fresh
    before = tree(root.state_dir)
    fake(fault=fault)
    out = executor.step(proj)
    assert out.code == 1 and why in out.msg, out.msg
    st = status(root)
    assert (st["state"], st["step"], st["attempts"]) == ("RUNNABLE", 0, 1)
    assert records(root, "step-failed")[0]["why"].find(why.split()[0]) >= 0
    assert os.path.isdir(root.step_dir(1, 1)) and not os.path.exists(root.step_dir(1))
    assert tree(root.state_dir) == before
    assert not os.path.exists(root.pending_dir)
    assert_clean(proj)
    fake(fault=None)
    assert executor.step(proj).code == 0
    st = status(root)
    assert (st["step"], st["attempts"]) == (1, 0)
    assert os.path.isdir(root.step_dir(1)) and os.path.isdir(root.step_dir(1, 1))
    assert_clean(proj)


def test_timeout_kills_model(fresh, fake):
    proj, root = fresh
    set_project(proj, step_timeout="1s")
    fake(fault="hang")
    out = executor.step(proj)
    assert out.code == 1 and "timeout" in out.msg
    meta = json.load(open(os.path.join(root.step_dir(1, 1), "meta.json")))
    assert meta["timed_out"] is True


def test_three_failures_give_failed(fresh, fake):
    proj, root = fresh
    fake(fault="crash")
    for a in (1, 2, 3):
        assert executor.step(proj).code == 1
    st = status(root)
    assert st["state"] == "FAILED" and "3 failed attempts at step 1" in st["reason"]
    assert sorted(os.listdir(root.steps_dir)) == ["0001.failed-1", "0001.failed-2",
                                                  "0001.failed-3"]
    assert executor.step(proj).code == 2
    assert_clean(proj)


def test_resume_after_failed_never_reuses_a_folder_or_session(fresh, fake):
    """A resume restarts the attempt count; the run number goes on."""
    proj, root = fresh
    fake(fault="crash")
    for _ in range(3):
        executor.step(proj)
    assert executor.admin(root, "resume").code == 0
    assert executor.step(proj).code == 1
    assert status(root)["attempts"] == 1
    assert sorted(os.listdir(root.steps_dir)) == ["0001.failed-%d" % k for k in (1, 2, 3, 4)]
    sids = [r["session_id"] for r in records(root, "step-start")]
    assert len(set(sids)) == 4
    assert [r["run"] for r in records(root, "step-failed")] == [1, 2, 3, 4]
    fake(fault=None)
    assert executor.step(proj).code == 0
    text = open(os.path.join(root.step_dir(1), "prompt.md")).read()
    assert "Attempt 4 of this step failed" in text and "- Attempt 1 failed" in text
    assert "`steps/0001.failed-4/`" in text


def test_write_outside_pending_is_rejected(fresh, fake):
    """E3: committed files are restored byte for byte."""
    proj, root = fresh
    executor.step(proj)
    before = tree(root.path)
    fake(fault="write-outside")
    out = executor.step(proj)
    assert out.code == 1 and "wrote committed files" in out.msg
    assert "state/count.md" in out.msg and "memento.md" in out.msg
    after = tree(root.path)
    for rel in set(before) | set(after):
        if rel.startswith("steps" + os.sep) or rel in ("status.md", "journal.jsonl"):
            continue
        assert before.get(rel) == after.get(rel), rel
    assert after["journal.jsonl"].startswith(before["journal.jsonl"])
    st0 = Packet(root.path)
    st = status(st0)
    assert (st["step"], st["attempts"]) == (1, 1)
    assert_clean(proj)


def _lease(root, pid, expires):
    with open(root.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": pid, "step": 1, "attempt": 1,
                   "expires": expires}, fp)


def test_live_lease_exits_3(fresh):
    proj, root = fresh
    _lease(root, os.getpid(), "2999-01-01T00:00:00Z")
    out = executor.step(proj)
    assert out.code == 3 and "lease held" in out.msg
    assert status(root)["step"] == 0 and os.path.exists(root.lease_path)


def test_stale_lease_is_cleared(fresh):
    proj, root = fresh
    _lease(root, 2 ** 22 + 12345, "2999-01-01T00:00:00Z")      # no such pid
    assert executor.step(proj).code == 0
    notes = records(root, "note")
    assert len(notes) == 1 and "removed stale lease" in notes[0]["msg"]
    assert not os.path.exists(root.lease_path)


def test_expired_lease_is_cleared(fresh):
    proj, root = fresh
    _lease(root, os.getpid(), "2000-01-01T00:00:00Z")
    assert executor.step(proj).code == 0


@pytest.mark.parametrize("change,msg", [
    ({"state": "PAUSED", "reason": "by hand"}, "PAUSED"),
    ({"state": "SLEEPING", "wake_at": "2026-10-22T00:00:00Z", "resume_expr": "in 6 hours"},
     "SLEEPING until 2026-10-22T00:00:00Z"),
])
def test_not_runnable(fresh, change, msg):
    proj, root = fresh
    meta, body = root.load_status()
    meta.update(change)
    root.save_status(meta, body)
    out = executor.step(proj)
    assert out.code == 2 and msg in out.msg
    assert records(root) == []
    assert executor.step(proj, force=True).code == 0


def test_due_sleeper_runs_and_prompt_says_late(fresh):
    proj, root = fresh
    meta, body = root.load_status()
    meta.update(state="SLEEPING", wake_at="2026-10-21T15:00:00Z", resume_expr="in 1 hour")
    root.save_status(meta, body)
    assert executor.step(proj).code == 0
    text = open(os.path.join(root.step_dir(1), "prompt.md")).read()
    assert "due 2026-10-21T15:00:00Z, 3 hours late" in text


def test_timer_e4(fresh, fake, monkeypatch):
    """E4: in 10 days is not due on day 9, due on day 10, and runs once."""
    proj, root = fresh
    fake(behavior="sleeper")
    with open(os.path.join(root.state_dir, "period.md"), "w") as fp:
        fp.write("in 10 days\n")
    assert executor.step(proj).code == 0
    st = status(root)
    assert (st["state"], st["wake_at"]) == ("SLEEPING", "2026-10-31T18:00:00Z")
    monkeypatch.setenv("WPK_NOW", "2026-10-30T18:00:00Z")
    assert executor.step(proj).code == 2
    monkeypatch.setenv("WPK_NOW", "2026-10-31T18:00:00Z")
    assert executor.step(proj).code == 0
    assert executor.step(proj).code == 2
    assert status(root)["wake_at"] == "2026-11-10T18:00:00Z"
    assert open(os.path.join(root.state_dir, "wakes.md")).read() == "2\n"
    assert_clean(proj)


def test_recover_crashed_attempt(fresh):
    proj, root = fresh
    executor.step(proj)
    # What a SIGKILL during the model leaves behind.
    from work_packet import journal
    journal.append(root.journal_path, {"type": "step-start", "t": NOW, "step": 2,
                                       "attempt": 1, "model": "m", "session_id": "s"})
    os.makedirs(os.path.join(root.pending_dir, "state"))
    os.makedirs(root.step_dir(2))
    assert check(proj).errors == []
    out = executor.recover(proj)
    assert out.code == 0 and "step 2 attempt 1" in out.msg
    assert status(root)["attempts"] == 1
    assert os.path.isdir(root.step_dir(2, 1)) and not os.path.exists(root.pending_dir)
    assert executor.recover(proj).msg == "nothing to recover"
    assert_clean(proj)
    assert executor.step(proj).code == 0
    assert status(root)["step"] == 2


def test_cli_step(fresh, capsys):
    proj, root = fresh
    assert main(["step", proj]) == 0
    assert "step 1 committed: RUNNABLE" in capsys.readouterr().err
    assert main(["step", root.path]) == 0
    assert main(["recover", proj]) == 0
    assert main(["step", os.path.dirname(proj)]) == 4


def test_step_outside_project(tmp_path, fake):
    proj, root = make_project(tmp_path)
    loose = str(tmp_path / ROOT)
    shutil.move(root.path, loose)
    assert executor.step(loose).code == 4


def test_state_files_env_and_outline_shown_up_to_first_max(tmp_path):
    from work_packet.prompt import FILE_MAX, FIRST_MAX, state_files
    d = tmp_path / "state"
    d.mkdir()
    (d / "env.md").write_text("e" * (FILE_MAX + 500))
    (d / "outline.md").write_text("o" * (FIRST_MAX + 1))
    (d / "notes.md").write_text("n" * (FILE_MAX + 500))
    got = state_files(str(d))
    assert "- `state/env.md`:\n\n```\n" in got
    assert "- `state/outline.md` (%d bytes, not shown)" % (FIRST_MAX + 1) in got
    assert "- `state/notes.md` (%d bytes, not shown)" % (FILE_MAX + 500) in got


def test_nudge_saves_an_attempt_that_forgot_the_memento(fresh, fake, tmp_path, monkeypatch):
    proj, root = fresh
    argv = tmp_path / "argv.jsonl"
    monkeypatch.setenv("WPK_FAKE_ARGV", str(argv))
    fake(fault="forgetful")
    out = executor.step(proj)
    assert out.code == 0, out.msg
    nudge = records(root, "step-nudge")
    assert len(nudge) == 1 and nudge[0]["why"] == ".pending/memento.md was not written"
    first, second = [json.loads(x) for x in argv.read_text().splitlines()]
    sid = first[first.index("--session-id") + 1]
    assert second[second.index("--resume") + 1] == sid and "--fork-session" in second
    meta = json.loads(open(os.path.join(root.step_dir(1), "meta.json")).read())
    assert meta["nudged"] == nudge[0]["why"] and meta["session_id"] != sid
    tr = open(os.path.join(root.step_dir(1), "transcript.jsonl")).read()
    assert tr.count('"type": "result"') == 2          # both runs, one transcript
    assert status(root)["step"] == 1
    assert_clean(proj)


def test_retry_prompt_tells_what_the_last_attempt_did(fresh, fake):
    proj, root = fresh
    fake(fault="silent")
    assert executor.step(proj).code == 1
    assert len(records(root, "step-nudge")) == 1      # nudged once, then failed
    fake(fault="bad-memento")
    assert executor.step(proj).code == 1
    assert os.path.isfile(os.path.join(root.step_dir(1, 2), "pending-memento.md"))
    fake(fault=None)
    assert executor.step(proj).code == 0
    text = open(os.path.join(root.step_dir(1), "prompt.md")).read()
    assert "## Last attempt" in text
    assert "Attempt 2 of this step failed: .pending/memento.md" in text
    assert "The `.pending/memento.md` it left:" in text
    assert "Earlier attempts at this step:\n\n- Attempt 1 failed: .pending/memento.md was not written" in text
    assert "each failed attempt is in `steps/0001.failed-1/`, `steps/0001.failed-2/`" in text
    text1 = open(os.path.join(root.step_dir(1, 2), "prompt.md")).read()
    assert "Attempt 1 of this step failed: .pending/memento.md was not written" in text1
    assert "$ make check (in the background)" in text1
    assert "Waiting for the background job." in text1
    assert "Earlier attempts" not in text1
    assert "that attempt is in `steps/0001.failed-1/`" in text1
    assert "## Last attempt" not in open(os.path.join(root.step_dir(1, 1), "prompt.md")).read()
