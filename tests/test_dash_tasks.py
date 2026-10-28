"""docs/dash-tasks.md: the runner in the server, the next batch, Compose, the web shell."""

import os
import time

import pytest

from work_packet import actions, executor, layout, project, registry
from work_packet.packet import Packet


def _new(name, prompt="Read state/count.md (0 if missing), add one.", **kw):
    plan = project.new(name, prompt, **kw)
    return registry.get(name), Packet(os.path.join(plan.path, "packets", plan.root))


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _wait(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


# --- T1: the runner in the server -------------------------------------------------

def test_runner_runs_a_handed_off_packet(tmp_path, fake):
    from work_packet.dash.runner import Runner
    _, pkt = _new("r1", paused=True)
    r = Runner(max_wait=30)
    r.start()
    try:
        time.sleep(0.2)
        assert pkt.load_status()[0]["step"] == 0          # paused: nothing ran
        out = executor.admin(pkt, "handoff", "go")
        assert out.code == 0
        r.poke()
        assert _wait(lambda: pkt.load_status()[0]["state"] == "COMPLETED")
        assert pkt.load_status()[0]["step"] == 8
    finally:
        r.stop(timeout=30)
    assert not r.alive


def test_second_runner_is_refused(tmp_path, fake):
    from work_packet.dash.runner import Runner, RunnerBusy
    a = Runner()
    a.acquire()
    try:
        with pytest.raises(RunnerBusy):
            Runner().acquire()
    finally:
        a.stop()
    b = Runner()
    b.acquire()                    # free again once the first let go
    b.stop()


def test_board_action_pokes_the_runner(tmp_path, fake):
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    e, pkt = _new("r2", paused=True)

    class Spy:
        n = 0

        def poke(self):
            Spy.n += 1
    c = TestClient(create_app(runner=Spy()))
    r = c.post("/p/r2/%s/act" % pkt.wpid, data={"action": "handoff", "note": "x"},
               follow_redirects=False)
    assert r.status_code == 303 and Spy.n == 1
    r = c.post("/p/r2/%s/act" % pkt.wpid, data={"action": "handoff"}, follow_redirects=False)
    assert Spy.n == 1                                     # refused: RUNNABLE already
    assert "runner on" in c.get("/").text


# --- T2: the next batch of work -----------------------------------------------------

def _git(cwd, *a):
    import subprocess
    subprocess.run(["git", "-C", str(cwd)] + list(a), check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x"))


def _records(pkt, t):
    return [r for r in pkt.journal().records if r.get("type") == t]


def test_next_batch_from_completed(tmp_path, fake):
    from work_packet import scheduler
    e, pkt = _new("nb")
    scheduler.tick([e], until_idle=True)
    meta, _ = pkt.load_status()
    assert meta["state"] == "COMPLETED" and meta["step"] == 8
    # refused while it is nothing to continue from: an empty instruction
    assert actions.continue_(pkt, "  ").code == executor.USAGE
    assert actions.continue_(pkt, "---\nresume: now\n---\nx").code == executor.USAGE
    with open(os.path.join(pkt.state_dir, "outline.md"), "w") as fp:
        fp.write("- [x] 1 count to 8\n")
    actions.save_draft(pkt, "draft text", note="n")
    assert actions.load_draft(pkt)["instruction"] == "draft text"
    out = actions.continue_(pkt, "Read state/count.md (0 if missing), add one.",
                            note="carry on")
    assert out.code == 0, out.msg
    assert "batch 2" in out.msg
    assert actions.load_draft(pkt) is None
    meta, _ = pkt.load_status()
    assert meta["state"] == "RUNNABLE" and meta["attempts"] == 0
    assert pkt.load_memento()[1].strip().startswith("Read state/count.md")
    assert not os.path.exists(os.path.join(pkt.state_dir, "outline.md"))
    assert os.path.isfile(os.path.join(pkt.state_dir, "history", "outline-1.md"))
    h = _records(pkt, "handoff")[-1]
    assert h["batch"] == 2 and h["from"] == "COMPLETED" and h["outline"] == \
        "state/history/outline-1.md" and h["note"] == "carry on"
    assert executor.batch_of(pkt.journal().records) == 2
    scheduler.tick([e])
    text = open(os.path.join(pkt.step_dir(9), "prompt.md")).read()
    assert "New work (batch 2)" in text and "state/history/outline-1.md" in text
    assert pkt.load_status()[0]["step"] == 9
    # running packets cannot be given a batch; a second one from COMPLETED again works
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["state"] == "COMPLETED"
    out = actions.continue_(pkt, "Again.", archive_outline=False)
    assert out.code == 0 and "batch 3" in out.msg


def test_next_batch_refused_while_runnable(tmp_path, fake):
    _, pkt = _new("nr")
    out = actions.continue_(pkt, "x")
    assert out.code == executor.NOT_RUNNABLE


def test_next_batch_work_repos(tmp_path, fake):
    from work_packet import scheduler
    e, pkt = _new("wr")
    w = os.path.join(pkt.path, "work", "r")
    os.makedirs(w)
    _git(w, "init", "-q", "-b", "main")
    open(os.path.join(w, "a"), "w").write("1\n")
    _git(w, "add", "a")
    _git(w, "commit", "-qm", "first")
    scheduler.tick([e])                                   # one step: heads recorded
    begin = _records(pkt, "commit-begin")[-1]
    assert set(begin["decision"]["heads"]) == {"r"}
    assert executor.admin(pkt, "pause").code == 0
    open(os.path.join(w, "a"), "w").write("2\n")
    out = actions.continue_(pkt, "Next.")
    assert out.code == executor.USAGE and "work/r" in out.msg
    _git(w, "commit", "-qam", "my change")
    out = actions.continue_(pkt, "Next.")
    assert out.code == 0, out.msg
    h = _records(pkt, "handoff")[-1]
    assert [ln.split(" ", 1)[1] for ln in h["commits"]["r"]] == ["my change"]
    assert "outline" not in h                             # from PAUSED: not archived
    scheduler.tick([e])
    text = open(os.path.join(pkt.step_dir(2), "prompt.md")).read()
    assert "committed 1 change in `work/r`" in text and "my change" in text


def test_next_batch_carries_the_session(tmp_path, fake):
    from work_packet import scheduler
    e, pkt = _new("cs")
    scheduler.tick([e], until_idle=True)
    out = actions.continue_(pkt, "Read state/count.md (0 if missing), add one.",
                            carry_session=True)
    assert out.code == 0
    scheduler.tick([e])
    start = [r for r in _records(pkt, "step-start") if r["step"] == 9][0]
    prev = [r for r in _records(pkt, "step-start") if r["step"] == 8][-1]
    assert start.get("carried_from") == prev["session_id"]


def test_wpk_next_cli(tmp_path, fake, capsys):
    from work_packet import cli, scheduler
    e, pkt = _new("cl")
    scheduler.tick([e], until_idle=True)
    assert cli.main(["next", "cl"]) != 0                  # no instruction
    f = tmp_path / "i.md"
    f.write_text("Add one.\n")
    assert cli.main(["next", "cl", "-f", str(f), "-m", "hi"]) == 0
    assert "batch 2" in capsys.readouterr().err
    assert _records(pkt, "handoff")[-1]["note"] == "hi"


# --- T3: New task and Compose -------------------------------------------------------

def _client(**kw):
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    return TestClient(create_app(**kw))


def _flash(r):
    import urllib.parse
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    return q.get("msg", [""])[0], q.get("ok", [""])[0] == "1"


def test_new_task_form_creates_a_held_project(tmp_path, fake):
    c = _client()
    r = c.get("/new")
    assert r.status_code == 200 and 'name="name"' in r.text
    r = c.post("/new", data={"name": "nt", "dir": str(tmp_path / "pp"), "model": ""},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/p/nt/compose")
    e = registry.get("nt")
    assert e["path"] == str(tmp_path / "pp" / "nt" / ".work-packet")       # a packet
    assert os.path.isfile(tmp_path / "pp" / "nt" / "nt.wp.md")
    meta, _ = Packet(os.path.join(e["path"], "runs", e["root"])).load_status()
    assert meta["state"] == "PAUSED" and meta["reason"] == "setup"
    r = c.post("/new", data={"name": "nt", "dir": str(tmp_path / "pp")}, follow_redirects=False)
    msg, ok = _flash(r)
    assert not ok and "already" in msg and r.headers["location"].startswith("/new?")
    r = c.post("/new", data={"name": "Bad Name"}, follow_redirects=False)
    assert not _flash(r)[1]


def test_compose_setup_flow(tmp_path, fake):
    c = _client()
    c.post("/new", data={"name": "cf", "dir": str(tmp_path)})
    e = registry.get("cf")
    r = c.get("/p/cf/compose")
    assert r.status_code == 200 and "Checks" in r.text and "no instruction yet" in r.text
    assert "Hand off to the runner" in r.text and "disabled" in r.text
    r = c.get("/p/cf/compose?template=outline")
    assert "outline" in r.text
    # save writes prompt.md
    r = c.post("/p/cf/compose", data={"action": "save", "instruction": "Add one.\n"},
               follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    assert open(os.path.join(e["path"], "prompt.md")).read() == "Add one.\n"
    # upload an input
    r = c.post("/p/cf/compose/upload", files=[("files", ("plan.md", b"# plan\n"))],
               follow_redirects=False)
    assert _flash(r)[1], (r.status_code, r.text[:300], _flash(r))
    assert open(os.path.join(e["path"], "state", "plan.md")).read() == "# plan\n"
    assert "state/plan.md" in c.get("/p/cf/compose").text
    r = c.post("/p/cf/compose", data={"action": "rm-input", "path": "../project.toml"},
               follow_redirects=False)
    assert not _flash(r)[1] and os.path.exists(os.path.join(e["path"], "project.toml"))
    r = c.post("/p/cf/compose", data={"action": "rm-input", "path": "plan.md"},
               follow_redirects=False)
    assert _flash(r)[1] and not os.path.exists(os.path.join(e["path"], "state", "plan.md"))
    # settings from Compose come back to Compose
    r = c.post("/p/cf/settings", data={"action": "set", "key": "max_attempts", "value": "2",
                                       "back": "compose"}, follow_redirects=False)
    assert r.headers["location"].startswith("/p/cf/compose")
    # hand off
    from work_packet import setup
    miss = setup.missing(setup.readiness(setup.target("cf"), tools=False))
    r = c.post("/p/cf/compose", data={"action": "handoff", "instruction": "Add one.\n"},
               follow_redirects=False)
    if miss:
        assert not _flash(r)[1]
        r = c.post("/p/cf/compose", data={"action": "handoff", "instruction": "Add one.\n",
                                          "force": "1"}, follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    assert r.headers["location"].startswith("/p/cf/%s/live" % e["root"])
    pkt = Packet(layout.run_dir(e["path"], e["root"]))
    assert pkt.load_status()[0]["state"] == "RUNNABLE"
    # the runner has it now: Compose is read-only and refuses changes
    r = c.get("/p/cf/compose")
    assert "The runner has this task" in r.text
    r = c.post("/p/cf/compose", data={"action": "save", "instruction": "x"},
               follow_redirects=False)
    assert not _flash(r)[1]


def test_compose_next_batch(tmp_path, fake):
    from work_packet import scheduler
    e, pkt = _new("cn")
    scheduler.tick([e], until_idle=True)
    c = _client()
    r = c.get("/p/cn/%s" % pkt.wpid)
    assert "Next batch" in r.text
    r = c.get("/p/cn/compose")
    assert "batch 2" in r.text and "Where batch 1 stopped" in r.text
    assert "Count reached 8" in r.text
    r = c.post("/p/cn/compose", data={"action": "save", "instruction": "Batch two.",
                                      "note": "nn", "archive": "1"}, follow_redirects=False)
    assert _flash(r)[1]
    assert actions.load_draft(pkt)["instruction"] == "Batch two."
    assert pkt.load_memento()[1].strip() == ""                 # untouched until hand-off
    r = c.get("/p/cn/compose")
    assert "Batch two." in r.text and "nn" in r.text
    r = c.post("/p/cn/compose", data={"action": "handoff", "instruction": "Batch two.",
                                      "note": "nn", "archive": "1"}, follow_redirects=False)
    msg, ok = _flash(r)
    assert ok and "batch 2" in msg, msg
    assert pkt.load_status()[0]["state"] == "RUNNABLE"
    assert pkt.load_memento()[1].strip() == "Batch two."
    assert actions.load_draft(pkt) is None
    assert _records(pkt, "handoff")[-1]["note"] == "nn"


def test_static_files(tmp_path, fake):
    c = _client()
    assert c.get("/static/compose.js").status_code == 200
    assert c.get("/static/../app.py").status_code == 404
    assert c.get("/static/nope.js").status_code == 404


# --- T4: the shell in the browser ---------------------------------------------------

def test_recheck_sequence_is_stripped_even_when_split():
    from work_packet.dash.shells import RECHECK, Session, Shells
    s = Session("x", "p", "/", "me", 0, None)
    out, hit = Shells._strip(s, b"ls\r\n" + RECHECK[:4])
    assert out == b"ls\r\n" and not hit and s.tail == RECHECK[:4]
    out, hit = Shells._strip(s, RECHECK[4:] + b"$ ")
    assert out == b"$ " and hit and s.tail == b""
    out, hit = Shells._strip(s, b"\x1b]0;title\x07")
    assert out == b"\x1b]0;title\x07" and not hit


def test_pty_session_round_trip(tmp_path):
    import asyncio
    from work_packet.dash.shells import Shells

    async def run():
        sh = Shells()
        s = sh.open("p", ["/bin/sh", "-c", "echo hi; printf '\\033]7777;wpk-recheck\\007';"
                          " read x; echo got $x; exit 3"], str(tmp_path), dict(os.environ),
                    "me", str(tmp_path / "log"))
        q, _ = sh.attach(s)
        got, ctl = b"", []
        sh.write(s, b"abc\n")
        while True:
            item = await asyncio.wait_for(q.get(), 10)
            if item is None:
                break
            kind, v = item
            if kind == "data":
                got += v
            else:
                ctl.append(v)
        return got, ctl, sh
    got, ctl, sh = asyncio.run(run())
    assert b"hi" in got and b"got abc" in got and b"7777" not in got
    assert {"recheck": True} in ctl and {"exit": 3} in ctl
    assert sh.sessions == {}
    assert "open" in (tmp_path / "log").read_text()


def _guarded(tmp_path, shells):
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard, csrf_token
    secret = b"k" * 32
    g = Guard(create_app(shells=shells), "loopback", secret, local_user="alice")
    c = TestClient(g, base_url="http://127.0.0.1:7878", client=("127.0.0.1", 50000))
    c.__enter__()       # one event loop for every request, as under uvicorn: shells live on it
    return c, csrf_token(secret)


ORIGIN = {"origin": "http://127.0.0.1:7878"}


def _ws_until(ws, pred, limit=200):
    import json
    got = b""
    for _ in range(limit):
        m = ws.receive()
        if m.get("bytes"):
            got += m["bytes"]
        elif m.get("text"):
            j = json.loads(m["text"])
            if pred(j, got):
                return j, got
        if pred(None, got):
            return None, got
    raise AssertionError("not seen; got %r" % got[-400:])


@pytest.fixture
def guarded(tmp_path):
    from work_packet.dash.shells import Shells
    made = []

    def make():
        shells = Shells()
        c, token = _guarded(tmp_path, shells)
        made.append((c, shells))
        return c, token, shells
    yield make
    for c, shells in made:
        shells.shutdown()
        c.__exit__(None, None, None)


def test_websocket_shell(tmp_path, fake, monkeypatch, guarded):
    import json
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HOME", str(tmp_path))            # no ~/.bashrc of the user's
    project.new("ws", None)
    c, token, shells = guarded()
    # no Origin, or a foreign one: refused before the app
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("ws://127.0.0.1:7878/p/ws/shell/new") as ws:
            ws.receive_text()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("ws://127.0.0.1:7878/p/ws/shell/new", headers={"origin": "http://evil"}) as ws:
            ws.receive_text()
    # a wrong token: closed with 1008
    with c.websocket_connect("ws://127.0.0.1:7878/p/ws/shell/new", headers=ORIGIN) as ws:
        ws.send_text(json.dumps({"token": "nope"}))
        with pytest.raises(WebSocketDisconnect) as ex:
            ws.receive_text()
        assert ex.value.code == 1008
    # the real thing
    with c.websocket_connect("ws://127.0.0.1:7878/p/ws/shell/new", headers=ORIGIN) as ws:
        ws.send_text(json.dumps({"token": token}))
        hello = json.loads(ws.receive_text())
        sid = hello["sid"]
        assert hello["cwd"] == registry.get("ws")["path"]
        ws.send_text(json.dumps({"resize": [100, 30]}))
        ws.send_bytes(b"echo $WPK_PROJECT-$((6*7)); stty size\n")
        seen = []
        _, got = _ws_until(ws, lambda j, g: seen.append(j) or (
            {"recheck": True} in seen and b"ws-42" in g and b"30 100" in g))
        assert b"7777" not in got
    # detached, the session lives on; a reattach replays the output
    assert [s["sid"] for s in shells.of_project("ws")] == [sid]
    with c.websocket_connect("ws://127.0.0.1:7878/p/ws/shell/" + sid, headers=ORIGIN) as ws:
        ws.send_text(json.dumps({"token": token}))
        assert json.loads(ws.receive_text())["sid"] == sid
        assert b"ws-42" in ws.receive_bytes()
        ws.send_text(json.dumps({"input": "exit 0\n"}))
        j, _ = _ws_until(ws, lambda j, g: j is not None and "exit" in j)
        assert j == {"exit": 0}
    assert shells.of_project("ws") == []
    with c.websocket_connect("ws://127.0.0.1:7878/p/ws/shell/" + sid, headers=ORIGIN) as ws:
        ws.send_text(json.dumps({"token": token}))
        assert json.loads(ws.receive_text()) == {"gone": True}


def test_handoff_closes_the_projects_shells(tmp_path, fake, monkeypatch, guarded):
    import json
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HOME", str(tmp_path))
    project.new("hc", None)
    e = registry.get("hc")
    open(os.path.join(e["path"], "prompt.md"), "w").write("Add one.\n")
    c, token, shells = guarded()
    with c.websocket_connect("ws://127.0.0.1:7878/p/hc/shell/new", headers=ORIGIN) as ws:
        ws.send_text(json.dumps({"token": token}))
        sid = json.loads(ws.receive_text())["sid"]
    assert "Closes 1 open shell" in c.get("/p/hc/compose").text
    r = c.post("/p/hc/compose", headers=ORIGIN, data={
        "csrf": token, "action": "handoff", "instruction": "Add one.\n", "force": "1"},
        follow_redirects=False)
    msg, ok = _flash(r)
    assert ok and "closed 1 shell" in msg, msg
    assert _wait(lambda: shells.get(sid) is None, 10)
    # the runner's now: no new shell
    with c.websocket_connect("ws://127.0.0.1:7878/p/hc/shell/new", headers=ORIGIN) as ws:
        ws.send_text(json.dumps({"token": token}))
        assert "error" in json.loads(ws.receive_text())


def test_new_task_offers_harnesses_and_models(tmp_path, fake):
    from work_packet.dash import data
    from work_packet.harness.claude import MODELS
    _new("used", model="claude-custom-x")
    ch = data.model_choices()
    ids = [m["id"] for m in ch["claude"]]
    assert ids[:len(MODELS)] == [m for m, _ in MODELS]
    assert "claude-custom-x" in ids
    assert any("(the default)" in m["label"] for m in ch["claude"])
    c = _client()
    page = c.get("/new").text
    assert '<select id="harness"' in page and 'value="claude"' in page
    assert 'list="models-claude"' in page and '<option value="opus">' in page
    r = c.post("/new", data={"name": "hm", "dir": str(tmp_path), "harness": "claude",
                             "model": "opus"}, follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    assert project.load_project(registry.get("hm")["path"])["model"] == "opus"
    r = c.post("/new", data={"name": "hx", "dir": str(tmp_path), "harness": "nope"},
               follow_redirects=False)
    msg, ok = _flash(r)
    assert not ok and "no harness" in msg
