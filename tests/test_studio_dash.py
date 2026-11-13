"""The studio on the board (docs/studio-plan.md S1.4-S1.6, S1.9): the page, the
routes (CSRF, the taker only, paths inside the folder), the socket with its
changes and output cards, documents in frames with markup, and closing."""

import json
import os
import time
import warnings

import pytest

from test_dash_tasks import _new
from work_packet import executor, layout, registry
from work_packet.dash.agent import Agents
from work_packet.studio import model

SECRET = b"k" * 32
BASE = "http://127.0.0.1:7878"


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


@pytest.fixture
def board(tmp_path, fake):
    """(client as alice, entry, packet, Agents, csrf token, studio base URL)."""
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard, csrf_token
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    fake("studio")
    e, pkt = _new("a")
    e = registry.get("a")
    ag = Agents(os.environ["WPK_HOME"])
    g = Guard(create_app(agents=ag), "loopback", SECRET, local_user="alice")
    with TestClient(g, base_url=BASE, client=("127.0.0.1", 50000)) as c:
        yield c, e, pkt, ag, csrf_token(SECRET), "/p/a/%s/studio" % pkt.wpid


def _post(c, url, tok, body=None):
    return c.post(url, json=body or {}, headers={"origin": BASE, "x-csrf-token": tok})


def _open(c, base, tok):
    return c.post(base + "/open", data={"csrf": tok}, headers={"origin": BASE},
                  follow_redirects=False)


def _wait(cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_open_from_the_task_page(board):
    c, e, pkt, ag, tok, base = board
    html = c.get("/p/a/" + pkt.wpid).text
    assert 'action="%s/open"' % base in html and "Open studio" in html
    assert "Open studio" in c.get(base).text                      # not open yet
    r = c.post(base + "/open", data={"csrf": "wrong"}, headers={"origin": BASE},
               follow_redirects=False)
    assert r.status_code == 403                                     # CSRF
    r = _open(c, base, tok)
    assert r.status_code == 303 and r.headers["location"] == base
    meta = pkt.load_status()[0]
    assert meta["taken_by"] == "alice" and meta["reason"] == "studio"
    st = model.state(e, pkt.wpid)
    conv = ag.get(st["session"]["conv"])
    assert conv["mode"] == "studio" and conv["cwd"] == layout.packet_folder(e["path"])
    html = c.get(base).text
    assert 'id="studio"' in html and "/static/studio.js" in html and conv["id"] in html
    html = c.get("/p/a/" + pkt.wpid).text
    assert "Return to the studio" in html and "IN STUDIO" in html
    assert c.get("/static/studio.js").status_code == 200


def test_only_the_taker(board):
    c, e, pkt, ag, tok, base = board
    for url in ("/canvas", "/draft", "/file?path=x.md", "/frame/doc?path=x.md"):
        assert c.get(base + url).status_code == 403, url             # not open
    executor.take(pkt, by="sam")
    model.open_studio(e, pkt.wpid, "sam")
    assert "sam's studio is open" in c.get(base).text
    for url in ("/pin", "/unpin", "/layout", "/ask", "/markup", "/cancel"):
        assert _post(c, base + url, tok, {"path": "a.md", "text": "x"}).status_code == 403, url
    r = _open(c, base, tok)
    assert r.status_code == 303 and "sam" in r.headers["location"]   # refused, with why


def test_paths_stay_in_the_folder(board, tmp_path):
    c, e, pkt, ag, tok, base = board
    _open(c, base, tok)
    folder = layout.packet_folder(e["path"])
    (tmp_path / "secret.md").write_text("secret")
    os.symlink(tmp_path / "secret.md", os.path.join(folder, "link.md"))
    for bad in ("../secret.md", "link.md", ".work-packet/project.toml", "/etc/passwd",
                ".studio/studio.json"):
        assert c.get(base + "/file", params={"path": bad}).status_code == 404, bad
        assert _post(c, base + "/pin", tok, {"path": bad}).status_code == 400, bad
    with open(os.path.join(folder, "page.html"), "w") as fp:
        fp.write("<script>alert(1)</script>")
    r = c.get(base + "/file", params={"path": "page.html"})
    assert r.headers["content-type"].startswith("text/plain")          # never a page here
    assert r.headers["content-security-policy"].startswith("sandbox")


def test_canvas_routes(board):
    c, e, pkt, ag, tok, base = board
    _open(c, base, tok)
    folder = layout.packet_folder(e["path"])
    os.makedirs(os.path.join(folder, "docs"))
    open(os.path.join(folder, "docs", "f.md"), "w").write("# F\n\nSome text here.\n")
    open(os.path.join(folder, "p.png"), "wb").write(b"\x89PNG\r\n\x1a\nfake")
    r = _post(c, base + "/pin", tok, {"path": "docs/f.md"})
    assert r.status_code == 200 and [a["path"] for a in r.json()["canvas"]] == ["docs/f.md"]
    _post(c, base + "/pin", tok, {"path": "p.png"})
    r = _post(c, base + "/layout", tok, {"mode": "two-up", "open": ["docs/f.md", "p.png"]})
    assert r.json()["layout"] == {"mode": "two-up", "open": ["docs/f.md", "p.png"]}
    assert _post(c, base + "/layout", tok, {"mode": "grid"}).status_code == 400
    r = c.get(base + "/canvas").json()
    assert [a["kind"] for a in r["canvas"]] == ["document", "image"] and r["open"]
    assert c.get(base + "/file", params={"path": "p.png"}).headers["content-type"] == "image/png"
    # The document's frame: framable by the board, with markup that goes to the studio.
    r = c.get(base + "/frame/doc", params={"path": "docs/f.md"})
    assert r.status_code == 200 and "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert 'data-post="%s/markup"' % base in r.text and 'id="console"' not in r.text
    assert "<h1" in r.text and "Some text here." in r.text
    sha = r.text.split('data-sha="')[1].split('"')[0]
    m = _post(c, base + "/markup", tok, {"path": "docs/f.md", "sha": sha, "op": "comment",
                                          "lines": "2-3", "sel": "Some text", "at": 0,
                                          "text": "say more"})
    assert m.status_code == 200, m.text
    assert "{>> say more <<}" in open(os.path.join(folder, "docs", "f.md")).read()
    stale = _post(c, base + "/markup", tok, {"path": "docs/f.md", "sha": sha, "op": "comment",
                                              "lines": "2-3", "sel": "Some", "at": 0,
                                              "text": "x"})
    assert stale.status_code == 409 and stale.json()["stale"]
    r = _post(c, base + "/unpin", tok, {"path": "p.png"})
    assert [a["path"] for a in r.json()["canvas"]] == ["docs/f.md"]


def test_socket_conversation_changes_and_cards(board):
    c, e, pkt, ag, tok, base = board
    _open(c, base, tok)
    folder = layout.packet_folder(e["path"])
    url = "ws://127.0.0.1:7878" + base + "/ws"
    with c.websocket_connect(url, headers={"origin": BASE}) as ws:
        ws.send_text(json.dumps({"token": "nope"}))
        with pytest.raises(Exception):
            ws.receive_text()
    with c.websocket_connect(url, headers={"origin": BASE}) as ws:
        ws.send_text(json.dumps({"token": tok}))
        assert json.loads(ws.receive_text()) == {"k": "busy", "on": False}
        r = _post(c, base + "/ask", tok, {"text": "write docs/findings.md"})
        assert r.status_code == 200 and r.json()["asked"]
        got = []
        while not any(x.get("k") == "output" for x in got):
            got.append(json.loads(ws.receive_text()))
        kinds = [x["k"] for x in got]
        assert "ask" in kinds and "say" in kinds and "tool" in kinds and "end" in kinds
        out = [x for x in got if x["k"] == "output"][0]
        assert out["files"] == [{"path": "docs/findings.md", "change": "created",
                                 "kind": "document"}]
        # The person edits a file outside the studio: a "changed" event, by outside.
        with open(os.path.join(folder, "notes.md"), "w") as fp:
            fp.write("mine\n")
        ev = json.loads(ws.receive_text())
        while ev.get("k") != "changed":
            ev = json.loads(ws.receive_text())
        assert ev["path"] == "notes.md" and ev["by"] == "outside" and ev["change"] == "created"
    # The card is in the transcript, so it comes back on a reload.
    cid = model.state(e, pkt.wpid)["session"]["conv"]
    assert [x for x in ag.transcript(cid) if x["k"] == "output"]
    # The next turn's primer names what the person changed.
    _post(c, base + "/ask", tok, {"text": "and now?"})
    ag.wait(cid)
    primer = open(os.path.join(ag.root(), cid, "primer.md")).read()
    assert "notes.md created" in primer and "docs/findings.md" in primer
    assert "You are the studio's agent" in primer


def test_close_records_and_releases(board):
    c, e, pkt, ag, tok, base = board
    _open(c, base, tok)
    cid = model.state(e, pkt.wpid)["session"]["conv"]
    _post(c, base + "/ask", tok, {"text": "write docs/a.md"})
    ag.wait(cid)
    d = c.get(base + "/draft").json()
    assert d["text"] and d["how"] in ("model", "facts")
    r = c.post(base + "/close", data={"csrf": tok, "summary": "Made a.", "how": "hold"},
               headers={"origin": BASE}, follow_redirects=False)
    assert r.status_code == 303 and "step+1+recorded" in r.headers["location"].replace("%20", "+")
    meta, body = pkt.load_status()
    assert meta["state"] == "PAUSED" and meta["reason"] == "held" and "taken_by" not in meta
    assert body.strip() == "Made a."
    html = c.get("/p/a/" + pkt.wpid).text
    assert "studio</span>" in html                     # the Steps tab badge
    assert c.get(base + "/canvas").status_code == 403   # closed


def test_studio_on_a_child_needs_work(board):
    c, e, pkt, ag, tok, base = board
    from work_packet.dash import data
    assert data._studio_ok(e, pkt.wpid)
    assert not data._studio_ok(dict(e, root="x"), pkt.wpid)


def test_project_page_and_console(board):
    c, e, pkt, ag, tok, base = board
    html = c.get("/p/a").text
    assert 'href="%s"' % base in html and "work on this project live" in html
    from work_packet.dash import console
    ctx = console.Ctx(home=os.environ["WPK_HOME"], by="alice")
    r = console.run("/studio", console.scope_of("/p/a"), ctx)
    assert r["ok"] and r["href"] == base and r["go"]
    r = console.run("/studio " + pkt.wpid[:8], console.scope_of("/"), ctx)
    assert r["href"] == base
    _open(c, base, tok)
    assert "Return to the studio" in c.get("/p/a").text


def test_socket_skips_scans_while_hidden(board, monkeypatch):
    """cpu-plan P1.7: a tab that reports itself hidden gets no scans; shown
    again, it gets one at once."""
    from work_packet.studio import watch
    c, e, pkt, ag, tok, base = board
    _open(c, base, tok)
    folder = layout.packet_folder(e["path"])
    polls = []
    real = watch.Watcher.poll
    monkeypatch.setattr(watch.Watcher, "poll", lambda self: polls.append(1) or real(self))
    monkeypatch.setattr(watch, "INTERVAL_S", 0.05)
    url = "ws://127.0.0.1:7878" + base + "/ws"
    with c.websocket_connect(url, headers={"origin": BASE}) as ws:
        ws.send_text(json.dumps({"token": tok}))
        assert json.loads(ws.receive_text())["k"] == "busy"
        ws.send_text(json.dumps({"type": "visible", "on": False}))
        time.sleep(0.3)
        n = len(polls)
        time.sleep(0.3)
        assert len(polls) == n
        with open(os.path.join(folder, "seen.md"), "w") as fp:
            fp.write("x\n")
        monkeypatch.setattr(watch, "INTERVAL_S", 60)
        ws.send_text(json.dumps({"type": "visible", "on": True}))
        ev = json.loads(ws.receive_text())
        while ev.get("k") != "changed":
            ev = json.loads(ws.receive_text())
        assert ev["path"] == "seen.md"


def test_watcher_skips_build_trees(tmp_path):
    from work_packet.studio import watch
    for d in ("build", "sim_build", "obj_dir", "rundir", "src"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "f.v").write_text("x")
    assert set(watch.Watcher(str(tmp_path)).stats) == {"src/f.v"}
    assert len(watch.scan(str(tmp_path))) == 5          # versions still take them


def test_cards_of_deleted_files(board):
    """Reloading the page replays the output cards; a file deleted since is
    marked gone, so the page does not load a preview of it (a 404)."""
    c, e, pkt, ag, tok, base = board
    _open(c, base, tok)
    cid = model.state(e, pkt.wpid)["session"]["conv"]
    _post(c, base + "/ask", tok, {"text": "write docs/findings.md"})
    ag.wait(cid)
    url = "ws://127.0.0.1:7878" + base + "/ws"

    def card():
        with c.websocket_connect(url, headers={"origin": BASE}) as ws:
            ws.send_text(json.dumps({"token": tok}))
            while True:
                ev = json.loads(ws.receive_text())
                if ev.get("k") == "output":
                    return ev["files"][0]
    from work_packet.dash import studio as dstudio
    folder = layout.packet_folder(e["path"])
    # The card is in the transcript once a socket saw the turn end.
    if not [x for x in ag.transcript(cid) if x["k"] == "output"]:
        ag.append(cid, {"k": "output", "files": [{"path": "docs/findings.md",
                                                  "change": "created", "kind": "document"}]})
    assert "gone" not in card()
    os.unlink(os.path.join(folder, "docs", "findings.md"))
    assert card()["gone"] is True
    assert dstudio.gone_marked({"k": "say", "text": "x"}, folder) == {"k": "say", "text": "x"}
