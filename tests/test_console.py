"""The board's console, C1 (docs/console.md): slash commands scoped to the page."""

import pytest

from test_dash_tasks import _client, _new
from work_packet import executor
from work_packet.dash import console


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _state(pkt):
    return pkt.load_status()[0]["state"]


def _run(c, line, path="/"):
    r = c.post("/console/cmd", json={"line": line, "path": path})
    assert r.status_code == 200
    return r.json()


def test_scope_of():
    assert console.scope_of("/")["kind"] == "server"
    assert console.scope_of("/runs/abc") == dict(kind="server", project=None, wpid=None,
                                                  step=None, run="abc")
    for tab in ("", "/tasks", "/steps", "/cost", "/settings", "/compose"):
        sc = console.scope_of("/p/my%20proj" + tab)
        assert (sc["kind"], sc["project"], sc["wpid"]) == ("project", "my proj", None)
    sc = console.scope_of("/p/a/wp1/live")
    assert (sc["kind"], sc["wpid"], sc["step"]) == ("packet", "wp1", None)
    sc = console.scope_of("/p/a/wp1/0003")
    assert (sc["kind"], sc["wpid"], sc["step"]) == ("packet", "wp1", "0003")


def test_help_and_commands(tmp_path, fake):
    c = _client()
    r = _run(c, "/help", "/")
    assert r["ok"] and "not about a project" in r["text"]
    assert any(l["text"].startswith("/pause ") for l in r["lines"])
    assert _run(c, "/help note")["text"].startswith("/note ")
    assert not _run(c, "/nosuch")["ok"]
    assert not _run(c, "why is it stuck?")["ok"]            # no agent in this client
    names = {x["name"]: x["changes"] for x in c.get("/console/commands").json()}
    assert names["show"] is False and names["pause"] is True


def test_show_scoped_to_the_page(tmp_path, fake):
    e, pkt = _new("a")
    c = _client()
    r = _run(c, "/show", "/")
    assert not r["ok"] and "name a project" in r["text"]
    r = _run(c, "/show", "/p/a")
    assert r["ok"] and r["text"].startswith("a · ") and r["href"] == "/p/a"
    r = _run(c, "/show", "/p/a/" + pkt.wpid)
    assert r["ok"] and "RUNNABLE" in r["text"] and r["href"] == "/p/a/" + pkt.wpid
    # by name, by packet id prefix (from anywhere), and project/prefix
    assert _run(c, "/show a")["href"] == "/p/a"
    assert _run(c, "/show " + pkt.wpid[:6])["href"] == "/p/a/" + pkt.wpid
    assert _run(c, "/show a/" + pkt.wpid[:6])["href"] == "/p/a/" + pkt.wpid
    assert not _run(c, "/show nothere")["ok"]
    r = _run(c, "/open a")
    assert r["go"] and r["href"] == "/p/a"


def test_pause_resume_packet_and_project(tmp_path, fake):
    e, pkt = _new("a")
    c = _client()
    page = "/p/a/" + pkt.wpid
    assert _run(c, "/pause", page)["ok"] and _state(pkt) == "PAUSED"
    assert _run(c, "/resume", page)["ok"] and _state(pkt) == "RUNNABLE"
    r = _run(c, "/pause", "/p/a")
    assert r["ok"] and r["text"] == "a: paused 1 packet" and _state(pkt) == "PAUSED"
    assert _run(c, "/resume a", "/")["ok"] and _state(pkt) == "RUNNABLE"
    # a pause waiting on a running step, and taking it back
    executor.request_pause(pkt, by="me")
    assert "pause requested" in " ".join(l["text"] for l in _run(c, "/show", page)["lines"])
    assert _run(c, "/keep", page)["ok"] and executor.pause_request(pkt) is None
    assert not _run(c, "/keep", "/p/a")["ok"]               # needs a packet


def test_note_and_handoff(tmp_path, fake):
    e, pkt = _new("a")
    c = _client()
    assert not _run(c, "/note", "/p/a/" + pkt.wpid)["ok"]
    r = _run(c, '/note @%s "look at the log first"' % pkt.wpid[:6], "/")
    assert r["ok"], r
    from work_packet import notes
    assert any("look at the log first" in (n.get("text") or "") for n in notes.queued(pkt))
    assert not _run(c, "/note @a/x @b hi")["ok"]            # one @target


def test_answer_needs_answers(tmp_path, fake):
    e, pkt = _new("a")
    c = _client()
    r = _run(c, "/answer", "/p/a/" + pkt.wpid)
    assert not r["ok"] and "id=text" in r["text"]
    r = _run(c, "/questions", "/p/a/" + pkt.wpid)
    assert r["ok"] and "no open questions" in r["text"]


def test_stop_needs_a_project(tmp_path, fake):
    e, pkt = _new("a")
    c = _client()
    assert not _run(c, "/stop %s" % pkt.wpid[:6])["ok"]


def test_drawer_on_every_page(tmp_path, fake):
    e, pkt = _new("a")
    c = _client()
    for url in ("/", "/p/a", "/p/a/" + pkt.wpid, "/runs"):
        html = c.get(url).text
        assert 'id="console"' in html and "/static/console.js" in html, url
    assert c.get("/static/console.js").status_code == 200


# --- C2: the agent ------------------------------------------------------------

def _agent_client(tmp_path, fake):
    import os
    from work_packet.dash.agent import Agents
    fake("console")
    ag = Agents(os.environ["WPK_HOME"])
    return _client(agents=ag), ag


def _events(ag, cid, k=None):
    return [e for e in ag.transcript(cid) if k is None or e["k"] == k]


def test_ask_the_agent_in_the_project_dir(tmp_path, fake):
    import json
    import os
    from work_packet import layout
    e, pkt = _new("a")
    argv = tmp_path / "argv.jsonl"
    os.environ["WPK_FAKE_ARGV"] = str(argv)
    try:
        c, ag = _agent_client(tmp_path, fake)
        r = _run(c, "why is it stuck?", "/p/a/" + pkt.wpid)
        assert r["ok"] and r["asked"], r
        cid = r["conv"]
        ag.wait(cid)
        say = _events(ag, cid, "say")
        assert say and "You asked: why is it stuck?" in say[0]["text"]
        assert "model haiku" in say[0]["text"]
        assert "cwd %s" % layout.packet_folder(e["path"]) in say[0]["text"]
        end = _events(ag, cid, "end")[-1]
        assert end["ok"] and end["cost"] > 0
        m = ag.get(cid)
        assert m["scope"] == "p/a/" + pkt.wpid and m["started"] and m["turns"] == 1
        assert m["title"] == "why is it stuck?"
        primer = open(os.path.join(ag.root(), cid, "primer.md")).read()
        assert pkt.wpid in primer and "/pause" in primer and "RUNNABLE" in primer
        # the second question resumes the same session, read-only tools only
        _run(c, "and now?", "/p/a/" + pkt.wpid)
        ag.wait(cid)
        first, second = [json.loads(ln) for ln in argv.read_text().splitlines()]
        assert first[first.index("--session-id") + 1] == m["session"]
        assert second[second.index("--resume") + 1] == m["session"]
        assert first[first.index("--permission-mode") + 1] == "dontAsk"
        assert first[first.index("--tools") + 1] == "Read,Grep,Glob,Bash"
        allowed = first[first.index("--allowedTools") + 1]
        assert "Bash(wpk show *)" in allowed and "Edit" not in allowed
        assert ag.get(cid)["turns"] == 2
    finally:
        os.environ.pop("WPK_FAKE_ARGV", None)


def test_conversations_per_scope(tmp_path, fake):
    e, pkt = _new("a")
    c, ag = _agent_client(tmp_path, fake)
    r1 = _run(c, "/show", "/p/a")                       # commands go in the conversation too
    r2 = _run(c, "/show", "/p/a/" + pkt.wpid)
    r3 = _run(c, "/help", "/")
    assert len({r1["conv"], r2["conv"], r3["conv"]}) == 3
    assert _run(c, "/show", "/p/a/tasks")["conv"] == r1["conv"]
    cmd = _events(ag, r1["conv"], "cmd")
    assert [x["line"] for x in cmd] == ["/show", "/show"] and cmd[0]["out"]["ok"]
    got = c.get("/console/conv", params={"path": "/p/a"}).json()
    assert got["conv"]["id"] == r1["conv"] and len(got["events"]) == 2
    assert c.get("/console/conv", params={"path": "/p/b"}).json()["conv"] is None
    # /new, /sessions, and back
    n = _run(c, "/new", "/p/a")
    assert n["ok"] and n["conv"] != r1["conv"]
    assert c.get("/console/conv", params={"path": "/p/a"}).json()["conv"]["id"] == n["conv"]
    s = _run(c, "/sessions", "/p/a")
    assert len(s["lines"]) == 2 and s["lines"][0]["text"].startswith("* " + n["conv"])
    back = _run(c, "/sessions " + r1["conv"].split("-")[-1], "/p/a")
    assert back["ok"] and back["conv"] == r1["conv"]
    assert c.get("/console/conv", params={"path": "/p/a"}).json()["conv"]["id"] == r1["conv"]


def test_model_and_server_scope(tmp_path, fake):
    from work_packet.dash import agent
    c, ag = _agent_client(tmp_path, fake)
    assert _run(c, "/model")["text"] == "model: haiku"
    r = _run(c, "/model sonnet")
    assert r["ok"] and r["model"] == "sonnet"
    assert not _run(c, "/model 'x; rm'")["ok"]
    r = _run(c, "what is the server doing?", "/runs")
    ag.wait(r["conv"])
    say = _events(ag, r["conv"], "say")[0]["text"]
    assert "model sonnet" in say
    assert "cwd %s" % (agent.source_repo() or ag.home) in say


def test_cancel_and_busy(tmp_path, fake):
    import time
    c, ag = _agent_client(tmp_path, fake)
    assert not _run(c, "/cancel")["ok"]                 # nothing to stop
    r = _run(c, "please sleep")
    cid = r["conv"]
    assert ag.busy(cid)
    b = _run(c, "another")
    assert not b["ok"] and "still answering" in b["text"]
    assert _run(c, "/cancel")["ok"]
    t0 = time.time()
    ag.wait(cid, 15)
    assert not ag.busy(cid) and time.time() - t0 < 10
    end = _events(ag, cid, "end")[-1]
    assert not end["ok"] and end["error"] == "cancelled"


def test_ws_streams_the_reply(tmp_path, fake):
    import json
    import os
    import warnings
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from work_packet.dash.agent import Agents
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard, csrf_token
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    fake("console")
    ag = Agents(os.environ["WPK_HOME"])
    secret = b"k" * 32
    token = csrf_token(secret)
    g = Guard(create_app(agents=ag), "loopback", secret, local_user="alice")
    base = "http://127.0.0.1:7878"
    hdr = {"origin": base, "x-csrf-token": token}
    with TestClient(g, base_url=base, client=("127.0.0.1", 50000)) as c:
        r = c.post("/console/cmd", json={"line": "/help", "path": "/"}, headers=hdr).json()
        cid = r["conv"]
        url = "ws://127.0.0.1:7878/console/ws/" + cid
        with c.websocket_connect(url, headers={"origin": base}) as ws:
            ws.send_text(json.dumps({"token": "nope"}))
            with pytest.raises(WebSocketDisconnect) as ex:
                ws.receive_text()
            assert ex.value.code == 1008
        with c.websocket_connect(url + "?since=0", headers={"origin": base}) as ws:
            ws.send_text(json.dumps({"token": token}))
            assert json.loads(ws.receive_text()) == {"k": "busy", "on": False}
            assert json.loads(ws.receive_text())["k"] == "cmd"          # replayed
            c.post("/console/cmd", json={"line": "hello there", "path": "/"}, headers=hdr)
            got = []
            while not got or got[-1] != {"k": "busy", "on": False}:
                got.append(json.loads(ws.receive_text()))
            kinds = [x["k"] for x in got]
            assert kinds[0] == "ask" and "say" in kinds and "end" in kinds
            assert any("hello there" in x.get("text", "") for x in got if x["k"] == "say")


def test_without_the_agent_slash_only(tmp_path, fake):
    c = _client()
    r = _run(c, "hello?")
    assert not r["ok"] and "slash commands only" in r["text"]
    assert c.get("/console/conv").json() == {"conv": None, "events": [], "agent": False}


# --- C3: proposals, history, /packet --------------------------------------------

def test_proposed_commands():
    got = console.proposed("Look:\n\n    /show a1\n`/pause`\n/model opus\n/nosuch x\n"
                           "a path /tmp/x\n$ /note @a1 'hi there'\n//comment")
    assert [(p["at"], p["line"], p["auto"]) for p in got] == [
        (2, "/show a1", True), (3, "/pause", False), (7, "/note @a1 'hi there'", False)]
    assert [p["i"] for p in got] == [0, 1, 2]


def test_agent_proposals_run_or_wait(tmp_path, fake):
    e, pkt = _new("a")
    c, ag = _agent_client(tmp_path, fake)
    page = "/p/a/" + pkt.wpid
    r = _run(c, "please propose something", page)
    cid = r["conv"]
    ag.wait(cid)
    say = _events(ag, cid, "say")[0]
    assert [p["line"] for p in say["props"]] == ["/show", "/pause"]
    auto = [x for x in _events(ag, cid, "cmd") if x.get("auto")]
    assert auto and auto[0]["line"] == "/show" and auto[0]["out"]["ok"]
    assert auto[0]["ref"] == say["id"] + ":0"
    assert "RUNNABLE" in auto[0]["out"]["text"]
    assert _state(pkt) == "RUNNABLE"                      # /pause waits for a click
    # a click runs it, recorded against the proposal; a dismissal is recorded too
    ref = say["id"] + ":1"
    out = c.post("/console/cmd", json={"line": "/pause", "path": page, "ref": ref}).json()
    assert out["ok"] and out["t"] and _state(pkt) == "PAUSED"
    assert [x for x in _events(ag, cid, "cmd") if x.get("ref") == ref][0]["line"] == "/pause"
    other = _events(ag, cid, "say")[1]
    d = c.post("/console/cmd", json={"line": "", "path": page,
                                     "decline": other["id"] + ":1"}).json()
    assert d["declined"] and _events(ag, cid, "decline")[0]["ref"] == other["id"] + ":1"
    # the transcript page shows what became of each proposal
    html = c.get("/console/c/" + cid).text
    assert "please propose something" in html and "ran at once" in html
    assert "declined" in html and "/pause" in html


def test_history_pages(tmp_path, fake):
    e, pkt = _new("a")
    c, ag = _agent_client(tmp_path, fake)
    r1 = _run(c, "about the project", "/p/a")
    r2 = _run(c, "about the packet", "/p/a/" + pkt.wpid)
    r3 = _run(c, "about the server", "/")
    for r in (r1, r2, r3):
        ag.wait(r["conv"])
    html = c.get("/console").text
    assert all(t in html for t in ("about the project", "about the packet", "about the server"))
    proj = c.get("/p/a/console").text
    assert "about the project" in proj and "about the packet" in proj
    assert "about the server" not in proj and 'class="on" aria-current="page">Console' in proj
    pk = c.get("/p/a/" + pkt.wpid).text
    assert "/console/c/" + r2["conv"] in pk and "/console/c/" + r1["conv"] not in pk
    assert c.get("/console/c/nope").status_code == 404
    assert console.scope_of("/p/a/console")["kind"] == "project"


def test_packet_from_the_conversation(tmp_path, fake):
    import urllib.parse
    e, pkt = _new("a")
    c, ag = _agent_client(tmp_path, fake)
    assert not _run(c, "/packet", "/p/a")["ok"]            # nothing to draft from
    r = _run(c, "why is the build slow?", "/p/a")
    ag.wait(r["conv"])
    out = _run(c, "/packet Make the build faster", "/p/a")
    assert out["ok"] and out["go"] and out["href"].startswith("/p/a/compose?")
    text = urllib.parse.parse_qs(urllib.parse.urlparse(out["href"]).query)["instruction"][0]
    assert text.startswith("Make the build faster\n")
    assert "> Q: why is the build slow?" in text and "You asked" in text
    assert r["conv"] in text
    assert "Make the build faster" in c.get(out["href"]).text
    r = _run(c, "server question", "/")
    ag.wait(r["conv"])
    out = _run(c, "/packet", "/")
    assert out["href"].startswith("/new?objective=")
    assert "server question" in c.get(out["href"]).text


def test_one_console_id_per_page(tmp_path, fake):
    e, pkt = _new("a")
    c, ag = _agent_client(tmp_path, fake)
    ag.wait(_run(c, "hi", "/p/a/" + pkt.wpid)["conv"])     # the packet page lists it
    for url in ("/", "/p/a", "/p/a/" + pkt.wpid, "/p/a/console", "/console"):
        assert c.get(url).text.count('id="console"') == 1, url
