"""M9: the read-only board. Every Stage 1 state lands in the right column."""

import json
import os
import socket
import subprocess
import time

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
    mp.setenv("WPK_FAKE_BEHAVIOR", "asker")
    p["asking"] = _new("asking")
    _tick(p["asking"][0])
    mp.setenv("WPK_FAKE_BEHAVIOR", "add_one")
    yield p
    mp.undo()


def test_every_state_in_its_column(tree):
    cols, broken = data.board(now=data._ts(NOW))
    got = {c["name"]: col for col, cards in cols.items() for c in cards}
    assert got == {"done": "Done", "ready": "Ready", "paused": "Paused",
                   "running": "Running", "sleeping": "Sleeping", "failed": "Failed",
                   "asking": "Needs you"}
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
    asking = data.card(tree["asking"][0], now)
    assert asking["root"]["reason"].startswith("Which colour")


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
    r = client.get("/b/main")
    assert r.status_code == 200
    for name in tree:
        assert ">%s<" % name in r.text
    assert "Needs you" in r.text and "Which colour" in r.text and "wpk answer asking" in r.text
    # The Overview: no cards, but what needs you, the boards' counts, what runs and wakes.
    r = client.get("/")
    assert r.status_code == 200 and 'data-project=' not in r.text
    assert "Needs attention" in r.text and "Which colour" in r.text \
        and "wpk answer asking" in r.text and "/p/asking#answer" in r.text
    assert "/p/failed\"><strong>failed<" in r.text            # failed root, in the attention list
    assert 'title="ready">1<' not in r.text and 'title="ready"><a href="/b/main">1<' in r.text
    assert "/p/running/%s/live" % tree["running"][1].wpid in r.text
    assert ">sleeping</strong>" in r.text and "Coming up" in r.text
    up = r.text[r.text.index("Coming up"):]                  # ready first, then the sleepers
    assert ">READY<" in up and up.index(">ready</strong>") < up.index(">sleeping</strong>")
    r = client.get("/p/done")
    assert r.status_code == 200 and "<svg" in r.text and "hello" in r.text
    r = client.get("/p/done/" + root)
    assert r.status_code == 200 and "state/count.md" in r.text
    r = client.get("/p/done/%s/0002" % root)
    assert r.status_code == 200 and "--fork-session" in r.text
    assert 'id="live"' not in r.text                   # a finished step does not refresh
    r = client.get("/p/failed/%s/0001.failed-1" % tree["failed"][1].wpid)
    assert r.status_code == 200 and "failed" in r.text


def test_token_panels(tree, client):
    from work_packet.dash import tokens
    e, root = tree["done"]
    tk = tokens.packet(e, root.wpid)
    assert tk["steps"] >= 2 and tk["figures"]["context_tokens"] > 0
    bar = tk["chart"]["bars"][0]
    assert bar["link"].endswith("/0001") and [g["cls"] for g in bar["segs"]] == ["tk-new"]  # the fake: uncached only
    assert tokens.chart([], tokens.CONTEXT) is None
    r = client.get("/stats")             # moved off the Overview (docs/overview-recent.md §3)
    assert "Tokens, last 7 days" in r.text and 'href="/p/done/cost"' in r.text
    assert "Context read per day" in r.text
    assert "Tokens, last" not in client.get("/").text
    for d, head in ((1, "Tokens, today"), (30, "Tokens, last 30 days"), (5, "Tokens, last 7 days")):
        assert head in client.get("/stats?days=%d" % d).text
    r = client.get("/p/done/cost")
    assert 'id="tokens"' in r.text and "Context read per day" in r.text and "By task" in r.text
    r = client.get("/p/done/" + root.wpid)
    assert "Context read per step" in r.text and "<th class=\"num\">Context</th>" in r.text
    r = client.get("/p/done/%s/0001" % root.wpid)
    assert "Context of each call" in r.text and "over 2 calls" in r.text
    assert tokens.step(root.step_dir(1), {}) is None


def test_where_the_context_went(tree, client):
    from test_toolcost import transcript
    e, root = tree["done"]
    transcript(os.path.join(root.step_dir(1), "transcript.jsonl"))
    for url in ("/p/done/cost", "/p/done/" + root.wpid, "/p/done/%s/0001" % root.wpid):
        r = client.get(url)
        assert "Where the context went" in r.text and "python -m pytest" in r.text, url
        assert "Lines read again in the same step" in r.text, url
    assert 'href="/p/done/%s/0001"' % root.wpid in client.get("/p/done/" + root.wpid).text


def test_missing_pages_are_404(tree, client):
    root = tree["done"][1].wpid
    for url in ("/p/nope", "/p/done/" + "0" * 8, "/p/done/%s/9999" % root,
                "/p/done/%s/..%%2f..%%2fproject.toml" % root):
        assert client.get(url).status_code == 404, url


def test_file_contents_are_escaped(tree, client):
    r = client.get("/p/paused/" + tree["paused"][1].wpid)
    assert "<script>alert(1)" not in r.text
    assert "&lt;script&gt;alert(1)" in r.text


# --- actions (docs/interaction.md §5) --------------------------------------

@pytest.fixture
def acting(tmp_path, monkeypatch):
    """A fresh home with one project that asked two questions."""
    import shlex
    import sys
    from conftest import FAKE
    monkeypatch.setenv("WPK_CLAUDE", "%s %s" % (shlex.quote(sys.executable), shlex.quote(FAKE)))
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WPK_NOW", NOW)
    monkeypatch.delenv("WPK_FAKE_FAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "multi_asker")
    e, root = _new("q", extra={"permissions": {           # no Bash, so it can be granted
        "allowed_tools": ["Read", "Write", "Edit", "Glob", "Grep"]}})
    _tick(e)
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    return e, root, TestClient(create_app())


def _journal(root, t):
    return [r for r in root.journal().records if r["type"] == t]


def test_answer_form_and_recommendations(acting):
    e, root, client = acting
    r = client.get("/p/q/" + root.wpid)
    assert r.status_code == 200 and 'id="answer"' in r.text
    assert 'name="a.bash"' in r.text and 'value="per sub-item"' in r.text and "allows" in r.text
    r = client.post("/p/q/%s/act" % root.wpid, data={"action": "recommend", "note": "go"},
                    follow_redirects=False)
    assert r.status_code == 303 and "ok=1" in r.headers["location"]
    h = _journal(root, "handoff")[-1]
    assert h["answers"] == {"bash": "yes", "cadence": "per item"} and h["note"] == "go"
    from work_packet.tomlio import load_toml
    assert "Bash" in load_toml(os.path.join(e["path"], "project.toml"))["permissions"][
        "allowed_tools"]
    page = client.get(r.headers["location"])
    assert "answered 2 of 2" in page.text and "granted Bash" in page.text
    assert 'id="answer"' not in page.text and "Pause" in page.text


def test_answer_form_with_typed_answers(acting):
    e, root, client = acting
    r = client.post("/p/q/%s/act" % root.wpid,
                    data={"action": "answer", "a.bash": "no", "a.cadence": "per sub-item"})
    assert r.status_code == 200 and "answered 2 of 2" in r.text
    assert _journal(root, "handoff")[-1]["answers"] == {"bash": "no", "cadence": "per sub-item"}
    assert _journal(root, "config") == []


def test_answer_nothing_is_refused(acting):
    e, root, client = acting
    r = client.post("/p/q/%s/act" % root.wpid, data={"action": "answer"})
    assert "nothing to send" in r.text and 'class="flash bad"' in r.text
    assert root.load_status()[0]["state"] == "NEEDS_INPUT"


def test_pause_and_handoff_buttons(acting):
    e, root, client = acting
    client.post("/p/q/%s/act" % root.wpid, data={"action": "recommend"})
    client.post("/p/q/%s/act" % root.wpid, data={"action": "pause"})
    assert root.load_status()[0]["state"] == "PAUSED"
    r = client.get("/p/q/" + root.wpid)
    assert "Hand off to the runner" in r.text
    client.post("/p/q/%s/act" % root.wpid, data={"action": "handoff", "note": "carry on"})
    assert root.load_status()[0]["state"] == "RUNNABLE"
    assert _journal(root, "handoff")[-1]["note"] == "carry on"


def test_note_box(acting):
    from work_packet import notes
    e, root, client = acting
    r = client.post("/p/q/%s/act" % root.wpid,
                    data={"action": "note", "note": "add a pytest.ini", "back": "live"},
                    follow_redirects=False)
    assert r.status_code == 303 and "/live?" in r.headers["location"] and "ok=1" in r.headers["location"]
    assert [n["text"] for n in notes.queued(root)] == ["add a pytest.ini"]
    page = client.get("/p/q/" + root.wpid)
    assert "Send note" in page.text and "Queued, until a step" in page.text
    assert "until the packet is handed off" in page.text          # it is NEEDS_INPUT
    live = client.get("/p/q/%s/live" % root.wpid)
    assert "Send note" in live.text and "add a pytest.ini" in live.text
    r = client.post("/p/q/%s/act" % root.wpid, data={"action": "note", "note": ""})
    assert 'class="flash bad"' in r.text and "empty" in r.text


def test_settings_panel(acting):
    e, root, client = acting
    r = client.get("/p/q/settings")
    assert 'id="settings"' in r.text and 'name="tool" value="Read"' in r.text
    client.post("/p/q/settings", data={"action": "allow", "tool": "Bash(git commit *)"})
    client.post("/p/q/settings", data={"action": "deny", "tool": "Glob"})
    r = client.post("/p/q/settings", data={"action": "set", "key": "step_timeout", "value": "45m"})
    assert "set step_timeout" in r.text
    r = client.post("/p/q/settings", data={"action": "set", "key": "carry_session", "value": "true"})
    assert 'value="true"' in r.text
    r = client.post("/p/q/settings", data={"action": "set", "key": "max_attempts", "value": "0"})
    assert 'class="flash bad"' in r.text
    from work_packet.tomlio import load_toml
    d = load_toml(os.path.join(e["path"], "project.toml"))
    assert d["step_timeout"] == "45m" and d["carry_session"] is True and "max_attempts" not in d
    assert "Bash(git commit *)" in d["permissions"]["allowed_tools"]
    assert "Glob" not in d["permissions"]["allowed_tools"]


def test_needs_you_card_links_to_the_answer(acting):
    e, root, client = acting
    r = client.get("/")
    assert "/p/q#answer" in r.text


def test_project_page_carries_the_answer_form(acting):
    e, root, client = acting
    r = client.get("/p/q")
    assert r.status_code == 200 and 'id="answer"' in r.text and 'name="a.bash"' in r.text
    assert ">Answer</a>" in r.text and 'class="btn hi" href="/p/q#answer"' in r.text  # action bar
    assert 'class="state NEEDS_INPUT" href="/p/q#answer"' in r.text
    r = client.post("/p/q/%s/act" % root.wpid,
                    data={"action": "recommend", "back": "project"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/p/q?")
    assert 'id="answer"' not in client.get("/p/q").text


# --- the live view -----------------------------------------------------------

def _line(**e):
    return json.dumps(e) + "\n"


@pytest.fixture
def live_pkt(acting):
    """The asking project, handed off, with a running step 2 whose transcript we write."""
    e, root, client = acting
    client.post("/p/q/%s/act" % root.wpid, data={"action": "recommend"})
    sd = root.step_dir(2)
    os.makedirs(os.path.join(root.pending_dir, "state"))
    with open(os.path.join(root.pending_dir, "state", "outline.md"), "w") as fp:
        fp.write("# Outline\n- [x] 0a. benches\n- [ ] 0b. unit test\n  - [ ] 0b.1 xfail\n"
                 "- [-] 6. later\n")
    os.makedirs(sd)
    use = {"type": "tool_use", "id": "t1", "name": "Bash",
           "input": {"command": "pytest -q > t.log", "description": "Run the unit tests"}}
    todo = {"type": "tool_use", "id": "t2", "name": "TodoWrite", "input": {"todos": [
        {"content": "Write the test", "status": "completed", "activeForm": "Writing"},
        {"content": "Run it", "status": "in_progress", "activeForm": "Running the test"}]}}
    with open(os.path.join(sd, "transcript.jsonl"), "w") as fp:
        fp.write(_line(type="system", subtype="init", model="m", tools=["Bash"]))
        fp.write(_line(type="assistant", message={"content": [{"type": "text", "text": "Starting 0b."}, use],
                       "usage": {"input_tokens": 5, "cache_read_input_tokens": 20000,
                                 "output_tokens": 30}}))
        fp.write(_line(type="user", message={"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "...\n3 passed in 1.2s\n"}]}))
        fp.write(_line(type="assistant", message={"content": [todo], "usage": {
            "input_tokens": 5, "cache_read_input_tokens": 21000, "output_tokens": 10}}))
        fp.write(_line(type="assistant", message={"content": [
            {"type": "tool_use", "id": "t3", "name": "Read", "input": {"file_path": "src/x.c"}}]}))
    with open(root.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 2, "attempt": 1,
                   "expires": "2999-01-01T00:00:00Z"}, fp)
    from work_packet import journal
    journal.append(root.journal_path, {"type": "step-start", "t": NOW, "step": 2, "attempt": 1,
                                       "model": "m", "session_id": "s"})
    return e, root, client


def test_activity_feed(live_pkt):
    e, root, client = live_pkt
    a = data.activity(os.path.join(root.step_dir(2), "transcript.jsonl"))
    assert [ev["kind"] for ev in a["events"]] == ["text", "tool", "tool", "tool"]
    bash = a["events"][1]
    assert bash["label"] == "Run the unit tests" and bash["detail"] == "pytest -q > t.log"
    assert bash["result"] == "3 passed in 1.2s"
    assert a["pending"]["name"] == "Read" and a["context"] == 21005 and a["calls"] == 2
    assert [t["status"] for t in a["todos"]] == ["completed", "in_progress"]


def test_outline_reads_pending_first(live_pkt):
    e, root, client = live_pkt
    o = data.outline(root)
    assert o["file"] == ".pending/state/outline.md" and (o["done"], o["total"]) == (1, 4)
    assert [i["text"] for i in o["entries"] if i.get("current")] == ["0b. unit test"]
    assert o["entries"][2]["depth"] == 1 and o["entries"][3]["state"] == "deferred"


def test_live_page_and_raw(live_pkt):
    e, root, client = live_pkt
    r = client.get("/p/q/%s/live" % root.wpid)
    assert r.status_code == 200 and "RUNNING" in r.text and "Run the unit tests" in r.text
    assert "3 passed in 1.2s" in r.text and "… running" in r.text
    assert "Running the test" in r.text and "1 of 4 done" in r.text
    assert 'data-refresh-ms="3000"' in r.text
    assert "Steps done" in r.text and "Asked two questions." in r.text
    raw = client.get("/p/q/%s/0002/raw" % root.wpid)
    assert raw.status_code == 200 and raw.text.count("\n") == 5
    assert client.get("/p/q/%s/0009/raw" % root.wpid).status_code == 404
    board = client.get("/")
    assert "/p/q/%s/live" % root.wpid in board.text and "Read: src/x.c" in board.text
    proj = client.get("/p/q")
    assert "Live view" in proj.text and "/p/q/%s/live#procs" % root.wpid in proj.text
    os.remove(root.lease_path)


def test_live_page_processes(live_pkt):
    e, root, client = live_pkt
    sh = subprocess.Popen(["sh", "-c", "sleep 30 & wait"], start_new_session=True)
    try:
        with open(os.path.join(root.step_dir(2), "model.pid"), "w") as fp:
            fp.write("%d\n" % sh.pid)
        for _ in range(100):
            r = client.get("/p/q/%s/live" % root.wpid)
            if "sleep 30</code>" in r.text:
                break
            time.sleep(0.05)
        assert 'id="procs"' in r.text and "sleep 30</code>" in r.text
        assert "%d" % sh.pid in r.text
    finally:
        os.killpg(sh.pid, 9)
        sh.wait()
    # Another host's step: say so, don't scan.
    with open(root.lease_path) as fp:
        lz = json.load(fp)
    assert data.processes(root, dict(lz, host="elsewhere"), {"dir": "0002"}) == {
        "remote": "elsewhere"}
    os.remove(root.lease_path)


def test_log_view(live_pkt):
    e, root, client = live_pkt
    lg = data.log(os.path.join(root.step_dir(2), "transcript.jsonl"))
    tools = [g for g in lg["groups"] if g["kind"] == "tool"]
    bash = tools[0]
    assert bash["title"].startswith("Bash  Run the unit tests") and bash["done"]
    assert bash["lines"][0][1:] == ("$ pytest -q > t.log", "cmd")
    assert ("3 passed in 1.2s", "") in [ln[1:] for ln in bash["lines"]]
    assert not tools[-1]["done"]                       # the Read is still running
    ns = [n for g in lg["groups"] for n in ([g["n"]] if g.get("n") else []) + [x[0] for x in g["lines"]]]
    assert ns == sorted(ns) == list(range(1, lg["lines"] + 1))
    r = client.get("/p/q/%s/live?view=log" % root.wpid)
    assert r.status_code == 200 and 'class="console pane"' in r.text
    assert "$ pytest -q &gt; t.log" in r.text and "… running" in r.text
    assert 'href="#L1"' in r.text and 'data-expand="all"' in r.text
    assert 'class="feed pane box"' in client.get("/p/q/%s/live" % root.wpid).text
    st = client.get("/p/q/%s/0002?view=log" % root.wpid)
    assert st.status_code == 200 and "$ pytest -q &gt; t.log" in st.text
    assert 'id="transcript"' in client.get("/p/q/%s/0002" % root.wpid).text
    txt = client.get("/p/q/%s/0002/log.txt" % root.wpid)
    assert txt.status_code == 200 and txt.headers["content-type"].startswith("text/plain")
    assert "▶ Bash  Run the unit tests\n$ pytest -q > t.log\n" in txt.text
    assert client.get("/p/q/%s/0009/log.txt" % root.wpid).status_code == 404
    assert client.get("/static/pane.js").status_code == 200
    os.remove(root.lease_path)


def test_tasks_nest_children_under_the_task_that_spawned_them(tmp_path):
    """docs/concepts.md: a hand-off starts a task; a child is a sub-task of its spawner's."""
    from conftest import _commit, make_project
    from work_packet import journal
    proj, root = make_project(tmp_path, steps=2)
    journal.append(root.journal_path, {"type": "handoff", "t": NOW, "from": "FAILED",
                                       "to": "RUNNABLE", "batch": 2,
                                       "instruction": "Try again.\nslowly",
                                       "report": "state/history/report-1.md"})
    _commit(root, 3, spawn=["hello"])
    e = {"name": "demo", "path": proj, "root": root.wpid}
    ts = data.tasks(e, data.tree(e, data._ts(NOW)))
    assert [(t["kind"], t["name"], t["depth"]) for t in ts] == [
        ("task", "task 1", 0), ("task", "task 2", 0), ("child", "hello", 1)]
    assert ts[0]["state"] == "FAILED" and ts[0]["report"] == "state/history/report-1.md"
    assert (ts[1]["first"], ts[1]["last"], ts[1]["instruction"]) == (3, 3, "Try again.")
    assert data.tasks(e, []) == []


def test_live_view_shows_the_steps_dfm_runs(live_pkt):
    """The DFM runs a running step started sit beside its processes (docs/dfm-events.md)."""
    e, root, client = live_pkt
    now = time.time()
    sid = "01JBLIVELIVELIVELIVELIVELI"

    def ev(seq, kind, **kw):
        return json.dumps(dict(v=1, src="dfm", sid=sid, seq=seq, t=now - 5 + seq, ev=kind, **kw)) + "\n"
    nodes = [{"id": n, "name": n, "kind": "leaf", "parent": None, "needs": nd}
             for n, nd in (("d.build", []), ("d.sim", [{"id": "d.build", "block": False}]),
                           ("d.cov", [{"id": "d.sim", "block": False}]))]
    d = os.path.join(os.environ["WPK_HOME"], "runs", "dfm")
    os.makedirs(d, exist_ok=True)
    # stands in for the step's dfm process: found, like it, by its WPK_* tags
    dfm = subprocess.Popen(["sleep", "30"], env=dict(os.environ, WPK_WPID=root.wpid, WPK_STEP="2"))
    with open(os.path.join(d, sid + ".jsonl"), "w") as fp:
        fp.write(ev(0, "run.start", host="h", pid=dfm.pid, cwd="/w", argv=["dfm", "run", "d.cov"],
                    ctx={"WPK_WPID": root.wpid, "WPK_STEP": "2", "WPK_ATTEMPT": "1"}))
        fp.write(ev(1, "graph.plan", nodes=nodes))
        fp.write(ev(2, "task.state", id="d.build", state="done", status=0, changed=True))
        fp.write(ev(3, "task.state", id="d.sim", state="enter"))
        fp.write(ev(4, "task.exec", id="d.sim", phase="start", cmd=["vcs", "-R"]))
    try:
        t = client.get("/p/q/%s/live" % root.wpid).text
        assert 'id="dfm"' in t and "/runs/" + sid in t and "run d.cov" in t
        assert t.index('id="dfm"') < t.index('id="procs"')       # beside, above the processes
        assert "d.sim" in t and "vcs -R" in t and "1/3 done" in t
        assert "Next: <code>d.cov</code> (after <code>d.sim</code>)" in t
        assert 'class="cls">DFM</a>' in t                         # its dfm process, tagged
    finally:
        dfm.kill()
        dfm.wait()
        os.unlink(os.path.join(d, sid + ".jsonl"))
