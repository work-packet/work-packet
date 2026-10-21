"""M9: the read-only board. Every Stage 1 state lands in the right column."""

import json
import os
import socket

import pytest

from conftest import NOW
from work_packet import project, registry, scheduler
from work_packet.dash import data
from work_packet.packet import Packet


def _new(name, **kw):
    plan = project.new(name, "Read state/count.md (0 if missing), add one.", **kw)
    return registry.get(name), Packet(os.path.join(plan.path, "packets", plan.root))


def _tick(entry):
    scheduler.tick([entry], until_idle=True)


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    """One project in each Stage 1 board column, built with the fake model."""
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("dash")
    import shlex
    import sys
    from conftest import FAKE
    mp.setenv("WPK_CLAUDE", "%s %s" % (shlex.quote(sys.executable), shlex.quote(FAKE)))
    mp.setenv("WPK_HOME", str(base / "home"))
    mp.setenv("WPK_NOW", NOW)
    mp.delenv("WPK_FAULT_AT", raising=False)
    mp.delenv("WPK_FAKE_FAULT", raising=False)
    mp.chdir(base)
    p = {}
    mp.setenv("WPK_FAKE_BEHAVIOR", "add_one")
    p["done"] = _new("done")
    _tick(p["done"][0])
    p["ready"] = _new("ready")
    p["paused"] = _new("paused", paused=True)
    with open(os.path.join(p["paused"][1].state_dir, "notes.md"), "w") as fp:
        fp.write("<script>alert(1)</script>\n")
    p["running"] = _new("running")
    with open(p["running"][1].lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 1,
                   "attempt": 1, "expires": "2999-01-01T00:00:00Z"}, fp)
    mp.setenv("WPK_FAKE_BEHAVIOR", "sleeper")
    p["sleeping"] = _new("sleeping")
    with open(os.path.join(p["sleeping"][1].state_dir, "period.md"), "w") as fp:
        fp.write("in 10 days\n")
    _tick(p["sleeping"][0])
    mp.setenv("WPK_FAKE_BEHAVIOR", "add_one")
    mp.setenv("WPK_FAKE_FAULT", "crash")
    p["failed"] = _new("failed")
    _tick(p["failed"][0])
    mp.delenv("WPK_FAKE_FAULT")
    yield p
    mp.undo()


def test_every_state_in_its_column(tree):
    cols, broken = data.board(now=data._ts(NOW))
    got = {c["name"]: col for col, cards in cols.items() for c in cards}
    assert got == {"done": "Done", "ready": "Ready", "paused": "Paused",
                   "running": "Running", "sleeping": "Sleeping", "failed": "Failed"}
    assert broken == []


def test_cards(tree):
    now = data._ts(NOW)
    done = data.card(tree["done"][0], now)
    assert done["packets"] == 2 and dict(done["counts"]) == {"COMPLETED": 2}
    assert done["trouble"] == 0 and done["spend_total"] > 0
    run = data.card(tree["running"][0], now)
    assert run["running"]["step"] == 1 and run["running"]["wpid"] == tree["running"][1].wpid
    sleep = data.card(tree["sleeping"][0], now)
    assert sleep["root"]["next"].startswith("2026-10-31")
    failed = data.card(tree["failed"][0], now)
    assert failed["root"]["reason"]


def test_registry_entry_with_missing_directory_is_listed_as_broken(tree, tmp_path):
    registry.register({"name": "gone", "path": str(tmp_path / "gone"),
                       "root": tree["done"][1].wpid, "created": NOW})
    try:
        _, broken = data.board(now=data._ts(NOW))
        assert [b["name"] for b in broken] == ["gone"]
    finally:
        registry.unregister("gone")


def test_tree_names_children_and_timeline(tree):
    nodes = data.tree(tree["done"][0], data._ts(NOW))
    assert [(n["depth"], n["name"]) for n in nodes] == [(0, "root"), (1, "hello")]
    assert all(s["outcome"] == "committed" for n in nodes for s in n["steps"])
    tl = data.timeline(nodes, data._ts(NOW))
    assert len(tl["rows"]) == 2 and tl["rows"][0]["bars"]
    assert data.timeline(data.tree(tree["ready"][0])) is None


def test_failed_attempts_are_steps_with_reasons(tree):
    st = data.steps(tree["failed"][1])
    assert [(s["dir"], s["outcome"]) for s in st] == [
        ("0001.failed-1", "failed"), ("0001.failed-2", "failed"), ("0001.failed-3", "failed")]
    assert all(s["why"] for s in st)


def test_step_view(tree):
    e, root = tree["done"]
    s = data.step(e, root.wpid, "0002")
    assert s["prev"] == "0001" and s["next"] == "0003"
    assert s["meta"]["step"] == 2 and s["fork"].endswith("--fork-session")
    assert any(k == "add" for k, _ in s["diff"])
    kinds = [b["kind"] for b in s["blocks"]]
    assert kinds[0] == "init" and kinds[-1] == "result" and "text" in kinds
    for bad in ("../x", "0002/..", "x", "0002.failed-9"):
        assert data.step(e, root.wpid, bad) is None
    assert data.step(e, "../../etc", "0001") is None
    assert data.packet(e, "not-a-wpid") is None


def test_transcript_blocks(tmp_path):
    p = tmp_path / "t.jsonl"
    lines = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "nope"},
            {"type": "tool_result", "content": [{"type": "text", "text": "y" * 50}]}]}},
    ]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n{torn")
    b = data.transcript(str(p), limit=10)
    assert [x["kind"] for x in b] == ["tool_use", "tool_result", "tool_result"]
    assert b[1]["error"] and b[2]["text"].startswith("y" * 10 + "\n... (40 more")


# The HTTP layer, when the dash extra is installed.

@pytest.fixture
def client(tree):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    return TestClient(create_app())


def test_pages(tree, client):
    root = tree["done"][1].wpid
    r = client.get("/")
    assert r.status_code == 200
    for name in tree:
        assert ">%s<" % name in r.text
    r = client.get("/p/done")
    assert r.status_code == 200 and "<svg" in r.text and "hello" in r.text
    r = client.get("/p/done/" + root)
    assert r.status_code == 200 and "state/count.md" in r.text
    r = client.get("/p/done/%s/0002" % root)
    assert r.status_code == 200 and "--fork-session" in r.text
    assert 'id="live"' not in r.text                   # a finished step does not refresh
    r = client.get("/p/failed/%s/0001.failed-1" % tree["failed"][1].wpid)
    assert r.status_code == 200 and "failed" in r.text


def test_missing_pages_are_404(tree, client):
    root = tree["done"][1].wpid
    for url in ("/p/nope", "/p/done/" + "0" * 8, "/p/done/%s/9999" % root,
                "/p/done/%s/..%%2f..%%2fproject.toml" % root):
        assert client.get(url).status_code == 404, url


def test_file_contents_are_escaped(tree, client):
    r = client.get("/p/paused/" + tree["paused"][1].wpid)
    assert "<script>alert(1)" not in r.text
    assert "&lt;script&gt;alert(1)" in r.text
