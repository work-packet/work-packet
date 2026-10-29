"""ask:, wpk handoff and the Hand-off prompt section; wpk allow / deny / set (docs/l1a-plan.md)."""

import os

import pytest

from conftest import make_project
from work_packet import executor, schema
from work_packet.check import check
from work_packet.cli import main
from work_packet.tomlio import load_toml

QUESTION = "Which colour: red or blue? I recommend blue."


def status(pkt):
    return pkt.load_status()[0]


def records(pkt, *types):
    return [r for r in pkt.journal().records if r["type"] in types]


def assert_clean(proj):
    rep = check(proj)
    assert rep.issues == [], [str(i) for i in rep.issues]


@pytest.fixture
def asker(tmp_path, fake):
    fake("asker")
    return make_project(tmp_path)


def test_ask_waits_for_a_handoff(asker):
    proj, root = asker
    out = executor.step(proj)
    assert out.code == 0 and "NEEDS_INPUT" in out.msg and QUESTION in out.msg
    st = status(root)
    assert (st["state"], st["reason"], st["resume_expr"], st["wake_at"]) == \
        ("NEEDS_INPUT", QUESTION, "now", None)
    assert_clean(proj)
    again = executor.step(proj)
    assert again.code == executor.NOT_RUNNABLE and "wpk handoff" in again.msg
    assert status(root)["step"] == 1


def test_handoff_note_reaches_the_next_step_only(asker):
    proj, root = asker
    executor.step(proj)
    assert main(["handoff", root.path, "-m", "Take the recommendations: blue."]) == 0
    st = status(root)
    assert (st["state"], st["reason"]) == ("RUNNABLE", None)
    h = records(root, "handoff")[-1]
    assert (h["from"], h["to"], h["asked"], h["note"]) == \
        ("NEEDS_INPUT", "RUNNABLE", QUESTION, "Take the recommendations: blue.")
    assert executor.step(proj).code == 0
    text = open(os.path.join(root.step_dir(2), "prompt.md")).read()
    assert "## Hand-off" in text and "The last step asked: " + QUESTION in text
    assert "Take the recommendations: blue." in text
    answer = open(os.path.join(root.state_dir, "answer.md")).read()
    assert "blue" in answer and status(root)["state"] == "COMPLETED"
    assert_clean(proj)


def test_handoff_note_is_kept_for_a_retry_and_dropped_after_a_commit(asker, fake):
    proj, root = asker
    executor.step(proj)
    main(["handoff", root.path, "-m", "blue"])
    fake("asker", fault="crash")
    assert executor.step(proj).code == executor.FAILED
    fake("add_one")
    assert executor.step(proj).code == 0           # attempt 2 commits step 2
    assert "## Hand-off" in open(os.path.join(root.step_dir(2), "prompt.md")).read()
    executor.step(proj)
    assert "## Hand-off" not in open(os.path.join(root.step_dir(3), "prompt.md")).read()


def test_handoff_and_resume_states(asker):
    proj, root = asker
    assert executor.admin(root, "handoff", note="x").code == executor.NOT_RUNNABLE
    executor.step(proj)
    assert main(["resume", root.path]) == 0        # resume takes NEEDS_INPUT too, without a note
    assert status(root)["state"] == "RUNNABLE"
    assert records(root, "handoff") == []
    assert main(["pause", root.path]) == 0
    assert main(["handoff", root.path]) == 0       # a hand-off with no note
    h = records(root, "handoff")[-1]
    assert h["from"] == "PAUSED" and "note" not in h and "asked" not in h


def test_handoff_by_project_takes_failed(tmp_path, fake):
    fake("add_one", fault="crash")
    proj, root = make_project(tmp_path)
    for _ in range(3):
        executor.step(proj)
    assert status(root)["state"] == "FAILED"
    assert main(["resume", proj]) == 0             # resume by project leaves FAILED alone
    assert status(root)["state"] == "FAILED"
    assert main(["handoff", proj, "-m", "fixed"]) == 0
    assert status(root)["state"] == "RUNNABLE"
    assert records(root, "handoff")[-1]["note"] == "fixed"


def test_handoff_note_file(asker, tmp_path):
    proj, root = asker
    executor.step(proj)
    note = tmp_path / "note.md"
    note.write_text("1. blue\n2. yes\n")
    assert main(["handoff", root.path, "--note-file", str(note)]) == 0
    assert records(root, "handoff")[-1]["note"] == "1. blue\n2. yes"


def test_handoff_note_from_stdin(asker, monkeypatch):
    import io
    proj, root = asker
    executor.step(proj)
    monkeypatch.setattr("sys.stdin", io.StringIO("blue, from stdin\n"))
    assert main(["handoff", root.path, "--note-file", "-"]) == 0
    assert records(root, "handoff")[-1]["note"] == "blue, from stdin"


@pytest.mark.parametrize("meta,body,match", [
    ({"resume": "done", "ask": "Why?"}, "x", "cannot go with resume: done"),
    ({"resume": "fail", "reason": "r", "ask": "Why?"}, "x", "cannot go with resume: fail"),
    ({"resume": "now", "ask": "Why?"}, "", "instruction for after the answer"),
    ({"resume": "now", "ask": "  "}, "x", "non-empty string"),
    ({"resume": "now", "ask": ["a"]}, "x", "must be a mapping"),
    ({"resume": "now", "ask": []}, "x", "or a list of questions"),
    ({"resume": "now", "ask": [{"id": "a", "q": "x"}, {"id": "a", "q": "y"}]}, "x", "duplicate id"),
    ({"resume": "now", "ask": [{"id": "A", "q": "x"}]}, "x", "must match"),
    ({"resume": "now", "ask": [{"id": "a"}]}, "x", "the question as a non-empty string"),
    ({"resume": "now", "ask": [{"id": "a", "q": "x", "grants": "Bash"}]}, "x", "list of strings"),
    ({"resume": "now", "ask": [{"id": "a", "q": "x", "why": 1}]}, "x", "unknown key"),
    ({"resume": "now", "ask": [{"id": "a", "q": "x", "sets": {"model": "m"}}]}, "x",
     "cannot be set by an answer"),
    ({"resume": "now", "ask": [{"id": "a", "q": "x", "sets": {"step_budget_usd": -1}}]}, "x",
     "must be a number > 0"),
    ({"resume": "now", "ask": [{"id": "a", "q": "x", "choices": ["up", "no"],
                                "sets": {"up": {"max_attempts": 9}}}]}, "x",
     "cannot be set by an answer"),
    ({"resume": "now", "ask": [{"id": "a", "q": "x", "sets": []}]}, "x", "must be a mapping"),
])
def test_ask_rules(meta, body, match):
    probs = schema.validate_memento(meta, body)
    assert any(match in p.msg for p in probs), probs


def test_ask_is_not_a_resume_value():
    probs = schema.validate_memento({"resume": "ask"}, "x")
    assert any("not a resume value" in p.msg for p in probs)


def test_needs_input_needs_a_reason():
    from work_packet.packet import new_status
    meta = new_status("2454b9ba-4aad-42bc-b620-075e0651f652", "demo", "m",
                      "2026-10-23T00:00:00Z")
    meta.update(state="NEEDS_INPUT")
    assert any(p.field == "reason" for p in schema.validate_status(meta))


# --- wpk allow / deny / set ------------------------------------------------

@pytest.fixture
def proj(tmp_path, fake):
    return make_project(tmp_path)


def toml(proj):
    return load_toml(os.path.join(proj, "project.toml"))


def test_allow_and_deny(proj):
    proj, root = proj
    assert main(["allow", proj, "Bash", "Read", "Bash(git commit *)"]) == 0
    assert toml(proj)["permissions"]["allowed_tools"] == \
        ["Read", "Write", "Bash", "Bash(git commit *)"]
    assert main(["deny", proj, "Write", "Glob"]) == 0
    assert toml(proj)["permissions"]["allowed_tools"] == ["Read", "Bash", "Bash(git commit *)"]
    cfg = records(root, "config")
    assert [r["changes"] for r in cfg] == [["allow Bash", "allow Bash(git commit *)"],
                                           ["deny Write"]]
    assert_clean(proj)


def test_allow_reaches_the_step(proj):
    proj, root = proj
    main(["allow", proj, "Bash"])
    from work_packet.project import settings
    assert "Bash" in settings(proj).allowed_tools


def test_set_values(proj):
    proj, root = proj
    assert main(["set", proj, "step_timeout=60m", "step_budget_usd=4", "carry_session=true",
                 "permission_mode=auto"]) == 0
    d = toml(proj)
    assert (d["step_timeout"], d["step_budget_usd"], d["carry_session"]) == ("60m", 4, True)
    assert d["permissions"]["permission_mode"] == "auto"
    assert main(["set", proj, "step_timeout="]) == 0
    assert "step_timeout" not in toml(proj)
    assert_clean(proj)


def test_set_model_reaches_packets(proj):
    """Packets keep their own model; ``wpk set model=`` passes it on to the root and
    to packets on the old one, not to one whose model was chosen for it."""
    from work_packet import clock, spawn
    from work_packet.packet import Packet
    proj, root = proj
    old = status(root)["model"]
    assert main(["set", proj, "model=%s" % old]) == 0     # the fixture's, not the default
    kids = []
    for i, m in enumerate((None, "chosen-model")):
        e = {"wpid": spawn.child_wpid(root.wpid, 1, i), "spawn_key": "1:%d" % i,
             "instruction": "x\n", "model": m}
        spawn.create_child(root, e, root.state_dir, "p", old, clock.now())
        kids.append(Packet(os.path.join(os.path.dirname(root.path), e["wpid"])))
    assert main(["set", proj, "model=new-model"]) == 0
    assert [status(p)["model"] for p in [root] + kids] == ["new-model", "new-model",
                                                          "chosen-model"]
    assert records(root, "config")[-1]["changes"] == ["model %s -> new-model" % old]
    # project.toml changed by hand: setting it again still reaches the root.
    meta, body = root.load_status()
    meta["model"] = "typo-model"
    root.save_status(meta, body)
    assert main(["set", proj, "model=new-model"]) == 0
    assert status(root)["model"] == "new-model"


@pytest.mark.parametrize("pair", ["step_timeout=soon", "max_attempts=0", "name=other",
                                  "permission_mode=yolo", "step_timeout"])
def test_set_rejects(proj, pair, capsys):
    proj, root = proj
    before = open(os.path.join(proj, "project.toml"), "rb").read()
    assert main(["set", proj, pair]) != 0
    assert open(os.path.join(proj, "project.toml"), "rb").read() == before
    assert records(root, "config") == []


def test_settings_wait_for_a_running_step(proj):
    proj, root = proj
    from work_packet.lease import Lease
    lease = Lease(root.lease_path, 1, 1, 60).acquire()
    try:
        assert main(["allow", proj, "Bash"]) != 0
    finally:
        lease.release()
    assert "Bash" not in toml(proj)["permissions"]["allowed_tools"]


# --- structured questions and wpk answer (docs/interaction.md) -------------

@pytest.fixture
def multi(tmp_path, fake):
    fake("multi_asker")
    proj, root = make_project(tmp_path)
    executor.step(proj)
    return proj, root


def test_structured_ask_summary_and_show(multi, capsys):
    proj, root = multi
    st = status(root)
    assert (st["state"], st["reason"]) == \
        ("NEEDS_INPUT", "2 questions: Allow Bash for builds and tests?")
    assert_clean(proj)
    from work_packet import questions
    qs = questions.of_packet(root)
    assert [q["id"] for q in qs] == ["bash", "cadence"] and qs[0]["grants"] == ["Bash"]
    assert main(["show", root.path]) == 0
    out = capsys.readouterr().out
    assert "open questions" in out and "yes grants: Bash" in out
    assert "choices: per item / per sub-item" in out


def test_answer_take_recommendations_grants_and_hands_off(multi):
    proj, root = multi
    assert main(["answer", root.path, "-r", "-m", "Go."]) == 0
    assert "Bash" in toml(proj)["permissions"]["allowed_tools"]
    assert records(root, "config")[-1]["changes"] == ["allow Bash"]
    h = records(root, "handoff")[-1]
    assert h["answers"] == {"bash": "yes", "cadence": "per item"} and h["note"] == "Go."
    assert [q["id"] for q in h["questions"]] == ["bash", "cadence"]
    assert status(root)["state"] == "RUNNABLE"
    assert executor.step(proj).code == 0
    text = open(os.path.join(root.step_dir(2), "prompt.md")).read()
    assert "1. `bash`: Allow Bash for builds and tests?" in text
    assert "   - Answer: per item" in text and "Go." in text
    assert_clean(proj)


def test_answer_some_no_grant(multi):
    proj, root = multi
    assert main(["answer", root.path, "bash=no", "cadence=per sub-item"]) == 0
    assert "Bash" not in toml(proj)["permissions"]["allowed_tools"]
    assert records(root, "config") == []
    executor.step(proj)
    text = open(os.path.join(root.step_dir(2), "prompt.md")).read()
    assert "   - Answer: no" in text and "   - Answer: per sub-item" in text


def test_answer_partial_shows_unanswered(multi):
    proj, root = multi
    assert main(["answer", root.path, "cadence=per item"]) == 0
    executor.step(proj)
    assert "   - Answer: (no answer)" in open(os.path.join(root.step_dir(2), "prompt.md")).read()


def test_answer_rejects(multi, tmp_path):
    proj, root = multi
    assert main(["answer", root.path, "nope=1"]) != 0
    assert main(["answer", root.path]) != 0           # nothing to send
    assert status(root)["state"] == "NEEDS_INPUT"
    p2, r2 = make_project(tmp_path, name="other")      # RUNNABLE: no open questions
    assert main(["answer", r2.path, "-r"]) != 0


def test_string_ask_answers_as_q1(asker):
    proj, root = asker
    executor.step(proj)
    assert main(["answer", root.path, "q1=blue"]) == 0
    assert records(root, "handoff")[-1]["answers"] == {"q1": "blue"}


@pytest.fixture
def budget(tmp_path, fake):
    fake("budget_asker")
    proj, root = make_project(tmp_path)
    executor.step(proj)
    return proj, root


def test_sets_shown(budget, capsys):
    proj, root = budget
    assert_clean(proj)
    assert main(["show", root.path]) == 0
    out = capsys.readouterr().out
    assert '"raise budget" sets step_budget_usd 5.0' in out
    assert "yes sets step_timeout 60m" in out


def test_answer_choice_applies_sets(budget):
    proj, root = budget
    assert main(["answer", root.path, "-r"]) == 0
    d = toml(proj)
    assert (d["step_budget_usd"], d["step_timeout"]) == (5.0, "60m")
    assert sorted(records(root, "config")[-1]["changes"]) == \
        ["set step_budget_usd = 5.0", "set step_timeout = '60m'"]
    assert status(root)["state"] == "RUNNABLE"
    from work_packet import project
    assert project.settings(proj).step_budget_usd == 5.0
    assert_clean(proj)


def test_answer_other_choice_sets_nothing(budget):
    proj, root = budget
    assert main(["answer", root.path, "budget=split smaller", "time=no"]) == 0
    assert "step_budget_usd" not in toml(proj) and "step_timeout" not in toml(proj)
    assert records(root, "config") == []


def test_answer_sets_over_the_ceiling_refused(budget):
    proj, root = budget
    os.makedirs(os.environ["WPK_HOME"], exist_ok=True)
    with open(os.path.join(os.environ["WPK_HOME"], "config.toml"), "a") as f:
        f.write("max_step_budget_usd = 3.0\n")
    assert main(["answer", root.path, "budget=Raise Budget"]) != 0
    assert "step_budget_usd" not in toml(proj)
    assert status(root)["state"] == "NEEDS_INPUT"
