"""Requests: handing work to another project's agent (docs/delegation.md)."""

import json
import os

import pytest

from conftest import make_project
from work_packet import actions, executor, frontmatter, journal, notes, project, questions, \
    registry, requests
from work_packet.cli import main
from work_packet.lease import Lease
from work_packet.packet import Packet

BRIEF = """---
title: Lower reg_c register access in pssc sv-native
to: worker
repo:
  - name: pssc
    from: ~/projects/pssc
---
## Task
Make reg_c classes get read/write methods.

## Done when
`pssc compile` output has `task read`.
"""


@pytest.fixture
def req(tmp_path, fake):
    """A registered requester project with the brief ``reg`` in its root's state/."""
    project.new("asker", "Do the labs.\n", path=str(tmp_path / "asker"))
    root = Packet(registry.resolve("asker"))
    os.makedirs(os.path.join(root.state_dir, "requests"))
    with open(requests.brief_path(root.state_dir, "reg"), "w") as fp:
        fp.write(BRIEF)
    return root


def _types(pkt, op=None):
    return [r for r in journal.read(pkt.journal_path).records
            if r["type"] == "request" and (op is None or r["op"] == op)]


def _finish(pkt, state="COMPLETED", outcome="reg_c lowers; pssc main at abc123"):
    meta, body = pkt.load_status()
    meta["state"] = state
    pkt.save_status(meta, body)
    with open(pkt.report_path, "w") as fp:
        fp.write(frontmatter.dump({"outcome": outcome, "deliverables": [
            {"path": "state/fix.md", "what": "What changed"}]},
            "## Outcome\nx\n## Decisions\nnone\n## Deliverables\nnone\n## Open items\nnone\n"))


def test_brief_checks(tmp_path):
    assert requests.validate({}, "x")
    assert requests.validate({"title": "t", "to": "Bad Name"}, "x")
    assert requests.validate({"title": "t", "to": "ok"}, "  ")
    assert requests.validate({"title": "t", "to": "ok", "nope": 1}, "x")
    assert requests.validate({"title": "t", "to": "ok", "repo": [{"name": "a"}]}, "x")
    assert requests.validate({"title": "t", "to": "ok", "repo": [{"name": "a", "from": "b"}]},
                             "brief") == []
    with pytest.raises(requests.RequestError, match="no brief"):
        requests.load_brief(str(tmp_path), "missing")
    assert questions.validate([{"id": "a", "q": "send?", "request": "Bad"}])
    assert questions.validate([{"id": "a", "q": "send?", "request": "reg"}]) == []


def test_send_to_a_new_project_then_deliver(req, tmp_path):
    e = requests.send(req, "reg", by="me")
    assert e["state"] == "open" and e["to"]["created"] and e["to"]["batch"] == 1
    worker = Packet(registry.resolve("worker"))
    assert os.path.dirname(os.path.dirname(worker.path)) == str(tmp_path / "worker")
    meta, _ = worker.load_status()
    assert meta["state"] == "PAUSED" and "a request from asker" in meta["reason"]
    _, text = worker.load_memento()
    assert text.startswith("# Lower reg_c") and "request from packet" in text \
        and "Make reg_c classes" in text
    ptoml = project.load_project(str(tmp_path / "worker"))
    assert ptoml["setup"]["repo"] == [{"name": "pssc", "from": "~/projects/pssc"}]
    (rec,) = _types(worker, "received")
    assert rec["from"] == {"project": "asker", "wpid": req.wpid}
    (rec,) = _types(req, "sent")
    assert rec["to"]["project"] == "worker" and "path" not in rec["to"]
    with pytest.raises(requests.RequestError, match="already sent"):
        requests.send(req, "reg")

    assert requests.sync() == []                      # still PAUSED
    _finish(worker)
    ((got, msg),) = requests.sync()
    assert msg.startswith("delivered")
    (n,) = notes.queued(req)
    assert "came back from project worker" in n["text"] and "COMPLETED" in n["text"]
    assert "reg_c lowers; pssc main at abc123" in n["text"]
    assert os.path.join(worker.path, "state/fix.md") in n["text"]
    (rec,) = _types(req, "done")
    assert rec["outcome"] == "completed" and rec["note"] == n["id"]
    assert requests.get(req.wpid, "reg")["state"] == "delivered"
    assert requests.sync() == []
    assert len(notes.queued(req)) == 1


def test_a_sleeping_requester_wakes(req):
    requests.send(req, "reg")
    meta, body = req.load_status()
    meta.update(state="SLEEPING", wake_at="2026-10-30T00:00:00Z")
    req.save_status(meta, body)
    _finish(Packet(registry.resolve("worker")), state="FAILED")
    requests.sync()
    assert req.load_status()[0]["state"] == "RUNNABLE"
    assert "FAILED" in notes.queued(req)[0]["text"]


def test_a_running_step_holds_the_record_not_the_note(req):
    requests.send(req, "reg")
    _finish(Packet(registry.resolve("worker")))
    lz = Lease(req.lease_path, 1, 1, 60).acquire()
    try:
        ((_, msg),) = requests.sync()
        assert "waits" in msg
        assert requests.get(req.wpid, "reg")["state"] == "delivering"
        assert len(notes.queued(req)) == 1 and _types(req, "done") == []
    finally:
        lz.release()
    ((_, msg),) = requests.sync()
    assert msg.startswith("delivered")
    assert len(notes.queued(req)) == 1 and len(_types(req, "done")) == 1


def test_send_to_an_existing_project_is_its_next_batch(req, tmp_path):
    project.new("worker", "Old work.\n", path=str(tmp_path / "w"))
    worker = Packet(registry.resolve("worker"))
    with pytest.raises(requests.RequestError, match="RUNNABLE"):
        requests.send(req, "reg")
    assert requests.get(req.wpid, "reg")["state"] == "sending"
    _finish(worker)                                   # batch 1 done: not this request's
    e = requests.send(req, "reg")
    assert e["to"]["batch"] == 2 and not e["to"]["created"]
    assert worker.load_status()[0]["state"] == "RUNNABLE"
    assert requests.sync() == []
    _finish(worker)
    assert requests.sync()[0][1].startswith("delivered")


def test_external_and_done_by_hand(req):
    assert main(["request", "send", "asker", "reg", "--external", "an interactive session"]) == 0
    assert registry.get("worker") is None
    with pytest.raises(requests.RequestError, match="give the result"):
        requests.done(req, "reg", " ")
    assert main(["request", "done", "asker", "reg", "-m", "Fixed in pssc 1f2e3d."]) == 0
    (n,) = notes.queued(req)
    assert "outside wpk: an interactive session" in n["text"] and "1f2e3d" in n["text"]
    assert _types(req, "done")[0]["outcome"] == "by hand"
    with pytest.raises(requests.RequestError, match="already delivered"):
        requests.done(req, "reg", "again")


def test_answering_yes_sends_it(req):
    meta, body = req.load_status()
    meta.update(state="NEEDS_INPUT", reason="Send request reg?")
    req.save_status(meta, body)
    with open(req.memento_path, "w") as fp:
        fp.write(frontmatter.dump({"resume": "now", "ask": [
            {"id": "pssc", "q": "Send request reg?", "recommend": "yes", "request": "reg"}]},
            "Use the workaround meanwhile.\n"))
    out = actions.answer(req, take_recommendations=True, by="me")
    assert out.code == 0 and "sent request reg to project worker" in out.msg
    assert req.load_status()[0]["state"] == "RUNNABLE"
    assert registry.get("worker") is not None


def test_a_question_naming_a_missing_brief_is_rejected(tmp_path):
    proj, root = make_project(tmp_path)
    os.makedirs(os.path.join(root.pending_dir, "state"))
    with open(os.path.join(root.pending_dir, "summary.md"), "w") as fp:
        fp.write("Asked.\n")
    with open(os.path.join(root.pending_dir, "memento.md"), "w") as fp:
        fp.write(frontmatter.dump({"resume": "now", "ask": [
            {"id": "a", "q": "Send?", "request": "reg"}]}, "Then go on.\n"))
    _, why = executor._validate_pending(root)
    assert "ask a: no brief state/requests/reg.md" in why
    os.makedirs(os.path.join(root.pending_dir, "state", "requests"))
    with open(requests.brief_path(os.path.join(root.pending_dir, "state"), "reg"), "w") as fp:
        fp.write(BRIEF)
    assert executor._validate_pending(root) == (
        {"resume": "now", "ask": [{"id": "a", "q": "Send?", "request": "reg"}]}, None)


def test_the_step_prompt_lists_requests(req, capsys):
    requests.send(req, "reg")
    proj = os.path.dirname(os.path.dirname(req.path))
    executor.step(proj)
    text = open(os.path.join(req.step_dir(1), "prompt.md")).read()
    assert "## Requests" in text and "`reg` (Lower reg_c" in text and "; out" in text
    assert main(["request", "list"]) == 0
    assert "open" in capsys.readouterr().out
    assert main(["show", "worker"]) == 0
    assert "from asker" in capsys.readouterr().out


def test_tick_delivers(req):
    from work_packet import scheduler
    requests.send(req, "reg")
    _finish(Packet(registry.resolve("worker")))
    scheduler._sync_requests(None)
    assert requests.get(req.wpid, "reg")["state"] == "delivered"
    assert json.loads(open(requests._ipath(req.wpid, "reg")).read())["delivered"]
