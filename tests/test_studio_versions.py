"""Renders, versions and looking (docs/studio-plan.md S3.1-S3.5): versions per
turn with restore and keep, renders through the render listener (fake browser),
their cache and checks, the strip's routes, ``wpk studio look``, and the
primer's checks."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import warnings

import pytest

from test_dash_tasks import _new
from work_packet import blobs, layout, registry
from work_packet.dash import vendored
from work_packet.dash.agent import Agents
from work_packet.studio import model, render, renders, versions

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakechrome.py")
SECRET = b"k" * 32
BASE = "http://127.0.0.1:7878"


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def studio(tmp_path, fake):
    e, pkt = _new("a")
    e = registry.get("a")
    folder = layout.packet_folder(e["path"])
    return e, pkt, folder


def _w(folder, rel, text):
    p = os.path.join(folder, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb" if isinstance(text, bytes) else "w") as fp:
        fp.write(text)


# --- versions --------------------------------------------------------------------------

def test_versions_snapshot_restore_keep(studio, monkeypatch):
    e, pkt, folder = studio
    home = os.environ["WPK_HOME"]
    v0 = versions.snapshot(e, pkt.wpid, folder, "matt", home=home)   # the project's own .md
    assert v0["n"] == 1 and "prompt.md" in v0["files"]
    assert versions.snapshot(e, pkt.wpid, folder, "matt", home=home) is None    # no change
    _w(folder, "docs/a.md", "# A\n")
    _w(folder, "p.png", b"\x89PNG\r\n\x1a\nxx")
    _w(folder, "notes.txt", "not a kind: not tracked")
    v1 = versions.snapshot(e, pkt.wpid, folder, "agent", turn={"conv": "c", "t": 1}, home=home)
    assert v1["n"] == 2 and v1["parent"] == 1 and v1["changed"] == ["docs/a.md", "p.png"]
    assert "notes.txt" not in v1["files"] and v1["turn"] == {"conv": "c", "t": 1}
    assert blobs.get_bytes(v1["files"]["docs/a.md"], home) == b"# A\n"
    _w(folder, "docs/a.md", "# A, again\n")
    os.unlink(os.path.join(folder, "p.png"))
    _w(folder, "docs/b.md", "# B\n")
    v2 = versions.snapshot(e, pkt.wpid, folder, "agent", home=home)
    assert v2["n"] == 3 and v2["changed"] == ["docs/a.md", "docs/b.md"]
    assert v2["deleted"] == ["p.png"]
    # Restore v1 (n 2): byte-exact, b.md removed, p.png back; as a new version.
    marked = []
    v3 = versions.restore(e, pkt.wpid, 2, folder, "matt", home=home, mark=marked.append)
    assert open(os.path.join(folder, "docs", "a.md"), "rb").read() == b"# A\n"
    assert open(os.path.join(folder, "p.png"), "rb").read() == b"\x89PNG\r\n\x1a\nxx"
    assert not os.path.exists(os.path.join(folder, "docs", "b.md"))
    assert v3["n"] == 4 and v3["note"] == "restored v2" and v3["files"] == v1["files"]
    assert set(marked) == {"docs/a.md", "p.png", "docs/b.md"}
    assert versions.restore(e, pkt.wpid, 2, folder, "matt", home=home) is None   # already v2
    assert versions.keep(e, pkt.wpid, 3)["keep"] and versions.get(e, pkt.wpid, 3)["keep"]
    with pytest.raises(versions.VersionError):
        versions.get(e, pkt.wpid, 9)
    # Too big: skipped, with a note.
    monkeypatch.setattr(versions, "SIZE_MAX", 30)
    _w(folder, "data/big.csv", "a,b\n" + "1,2\n" * 10)
    _w(folder, "docs/a.md", "# A3\n")
    v4 = versions.snapshot(e, pkt.wpid, folder, "agent", home=home)
    assert "data/big.csv" not in v4["files"]
    assert {"path": "data/big.csv", "why": "over 0 MB"} in v4["skipped"]
    assert versions.since(e, pkt.wpid, v2["at"]) == [3, 4, 5]


# --- renders ---------------------------------------------------------------------------

@pytest.fixture
def svc(studio, tmp_path, monkeypatch):
    exe = tmp_path / "fake-chrome"
    exe.write_text('#!/bin/sh\nexec %s %s "$@"\n' % (sys.executable, FAKE))
    exe.chmod(0o755)
    logf = tmp_path / "chrome.log"
    monkeypatch.setenv("FAKECHROME_LOG", str(logf))
    b = render.Browser(exe=str(exe), home=str(tmp_path / "rhome"), idle_s=60, timeout_s=10)
    s = renders.install(renders.Service(os.environ["WPK_HOME"], browser=b,
                                        base_url="http://127.0.0.1:1"))
    yield s, logf
    renders.install(None)
    b.stop()


def test_render_cache_checks_and_parts(studio, svc, monkeypatch):
    e, pkt, folder = studio
    s, logf = svc
    _w(folder, "docs/a.md", "# A\n")
    monkeypatch.setenv("FAKECHROME_CHECKS", json.dumps(
        [{"check": "overflow", "what": "table is wider than its box"}]))
    got = s.render(e, pkt.wpid, "docs/a.md", "matt")
    d = os.path.join(renders.render_dir(e, pkt.wpid), got["key"])
    assert os.path.isfile(os.path.join(d, "full.png")) and os.path.isfile(os.path.join(d, "thumb.png"))
    # The fake page is 1600 px tall: two parts of 1400.
    assert got["parts"] == ["full.1.png", "full.2.png"] and got["size"] == [1200, 1600]
    assert got["checks"][0] == {"check": "overflow", "what": "table is wider than its box"}
    assert {"check": "console", "what": "fake error"} in got["checks"]
    log = logf.read_text()
    assert "/p/a/%s/studio/frame/doc?path=docs/a.md&render=1" % pkt.wpid in log
    assert s.secret in log and '"x-wpk-render-user": "matt"' in log
    n = log.count("Page.navigate")
    assert s.render(e, pkt.wpid, "docs/a.md", "matt")["key"] == got["key"]      # cached
    assert logf.read_text().count("Page.navigate") == n
    _w(folder, "docs/a.md", "# A2\n")
    assert s.render(e, pkt.wpid, "docs/a.md", "matt")["key"] != got["key"]     # new content
    # A chart's key follows its data, through a saved query to its files.
    _w(folder, "data/r.csv", "a\n1\n")
    _w(folder, "q.sql", "SELECT * FROM 'data/r.csv'")
    _w(folder, "charts/c.vl.json", json.dumps({"data": {"url": "../q.sql"}, "mark": "bar"}))
    assert renders.deps(folder, "charts/c.vl.json", "chart") == ["data/r.csv", "q.sql"]
    k1 = renders.key(folder, "charts/c.vl.json", "chart")
    _w(folder, "data/r.csv", "a\n2\n")
    assert renders.key(folder, "charts/c.vl.json", "chart") != k1
    # An image is its own render; a kind with no picture has none.
    _w(folder, "p.png", b"\x89PNG")
    assert s.render(e, pkt.wpid, "p.png", "matt")["kind"] == "image"
    assert s.render(e, pkt.wpid, "notes.txt", "matt") is None
    assert renders.Service(os.environ["WPK_HOME"]).available() == "the board has no render listener"


def test_look_copies_into_the_folder(studio, svc):
    e, pkt, folder = studio
    s, logf = svc
    model.open_studio(e, pkt.wpid, "matt")
    _w(folder, "docs/a.md", "# A\n")
    out = s.look("a", pkt.wpid, "docs/a.md")
    assert out["files"] == [".studio/look/docs_a.md.1.png", ".studio/look/docs_a.md.2.png"]
    assert all(os.path.isfile(os.path.join(folder, f)) for f in out["files"])
    assert s.look("a", pkt.wpid, "docs/a.md", part=2)["files"] == [".studio/look/docs_a.md.2.png"]
    with pytest.raises(renders.RenderUnavailable, match="2 parts"):
        s.look("a", pkt.wpid, "docs/a.md", part=3)
    _w(folder, "p.png", b"\x89PNG")
    assert s.look("a", pkt.wpid, "p.png")["files"] == ["p.png"]
    with pytest.raises(model.StudioError):
        s.look("a", pkt.wpid, "../x.md")


# --- the render listener ------------------------------------------------------------------

def test_render_gate(studio, svc):
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.render_gate import RenderGate
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    e, pkt, folder = studio
    s, logf = svc
    model.open_studio(e, pkt.wpid, "matt")
    _w(folder, "docs/a.md", "# A\n\nText.\n")
    c = TestClient(RenderGate(create_app(), s), base_url="http://127.0.0.1:1")
    url = "/p/a/%s/studio/frame/doc?path=docs/a.md&render=1" % pkt.wpid
    assert c.get(url).status_code == 403                                   # no secret
    assert c.get(url, headers={"x-wpk-render": "nope"}).status_code == 403
    h = {"x-wpk-render": s.secret, "x-wpk-render-user": "matt"}
    r = c.get(url, headers=h)
    assert r.status_code == 200 and "Text." in r.text and 'class="docbar' not in r.text
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert c.get(url, headers=dict(h, **{"x-wpk-render-user": "sam"})).status_code == 403
    for bad in ("/", "/p/a/%s" % pkt.wpid, "/p/a/%s/studio" % pkt.wpid,
                "/p/a/%s/studio/canvas" % pkt.wpid):
        assert c.get(bad, headers=h).status_code == 403, bad
    assert c.post("/p/a/%s/studio/pin" % pkt.wpid, headers=h, json={}).status_code == 403
    assert c.get("/static/studio_wait.js", headers=h).status_code == 200
    r = c.post("/_render/look", headers=h, json={"project": "a", "wpid": pkt.wpid,
                                                   "path": "docs/a.md"})
    assert r.status_code == 200 and r.json()["files"][0].startswith(".studio/look/")
    r = c.post("/_render/look", headers=h, json={"project": "a"})
    assert r.status_code == 400


def _port():
    so = socket.socket()
    so.bind(("127.0.0.1", 0))
    p = so.getsockname()[1]
    so.close()
    return p


def test_cli_look(studio, svc):
    import uvicorn
    from work_packet.dash.app import create_app
    from work_packet.dash.render_gate import RenderGate
    e, pkt, folder = studio
    s, logf = svc
    model.open_studio(e, pkt.wpid, "matt")
    _w(folder, "docs/a.md", "# A\n")

    def wpk(*a):
        return subprocess.run([sys.executable, "-m", "work_packet", "studio", "look", *a],
                              cwd=folder, capture_output=True, text=True)
    r = wpk("docs/a.md")
    assert r.returncode != 0 and "not running" in r.stderr
    port = _port()
    srv = uvicorn.Server(uvicorn.Config(RenderGate(create_app(), s), host="127.0.0.1",
                                        port=port, log_level="warning", lifespan="off"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.05)
    try:
        renders.write_listener(os.environ["WPK_HOME"], "http://127.0.0.1:%d" % port, s.secret)
        assert oct(os.stat(renders.listener_file(os.environ["WPK_HOME"])).st_mode & 0o777) == "0o600"
        r = wpk("docs/a.md")
        assert r.returncode == 0, r.stderr
        assert "part 1 of 2: .studio/look/docs_a.md.1.png" in r.stdout
        assert "checks:" in r.stdout and "console: fake error" in r.stdout
        r = wpk("docs/a.md", "--part", "2")
        assert "part 2 of 2: .studio/look/docs_a.md.2.png" in r.stdout, r.stdout
        r = wpk("nope.md")
        assert r.returncode != 0
    finally:
        srv.should_exit = True
        t.join(5)


# --- on the board --------------------------------------------------------------------------

@pytest.fixture
def board(studio, svc):
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard, csrf_token
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    e, pkt, folder = studio
    ag = Agents(os.environ["WPK_HOME"])
    g = Guard(create_app(agents=ag), "loopback", SECRET, local_user="alice")
    with TestClient(g, base_url=BASE, client=("127.0.0.1", 50000)) as c:
        base = "/p/a/%s/studio" % pkt.wpid
        tok = csrf_token(SECRET)
        c.post(base + "/open", data={"csrf": tok}, headers={"origin": BASE},
               follow_redirects=False)
        yield c, e, pkt, ag, tok, base, folder


def _post(c, url, tok, body=None):
    return c.post(url, json=body or {}, headers={"origin": BASE, "x-csrf-token": tok})


def _wait(cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_versions_on_the_board(board, fake, monkeypatch):
    c, e, pkt, ag, tok, base, folder = board
    fake("studio")
    monkeypatch.setenv("FAKECHROME_CHECKS", json.dumps(
        [{"check": "clipped-text", "what": "\"Title\" runs outside the chart"}]))
    cid = model.state(e, pkt.wpid)["session"]["conv"]
    url = "ws://127.0.0.1:7878" + base + "/ws"
    with c.websocket_connect(url, headers={"origin": BASE}) as ws:
        ws.send_text(json.dumps({"token": tok}))
        _post(c, base + "/ask", tok, {"text": "write docs/findings.md"})
        while json.loads(ws.receive_text()).get("k") != "output":
            pass
    assert _wait(lambda: c.get(base + "/versions").json()["versions"])
    assert _wait(lambda: len(c.get(base + "/versions").json()["versions"]) == 2)
    j = c.get(base + "/versions").json()
    v0, v = j["versions"]
    assert v0["note"] == "at open" and v0["by"] == "alice" and "prompt.md" in v0["files"]
    assert j["renders"] == "on" and v["n"] == 2 and v["by"] == "agent"
    assert v["changed"][0]["path"] == "docs/findings.md" and v["changed"][0]["kind"] == "document"
    assert _wait(lambda: c.get(base + "/versions").json()["versions"][1]["changed"][0]["ready"])
    ch = c.get(base + "/versions").json()["versions"][1]["changed"][0]
    assert ch["checks"][0]["check"] == "clipped-text"
    r = c.get(base + "/render/%s/thumb.png" % ch["key"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    for bad in ("../x/thumb.png", "%s/info.json" % ch["key"], "0" * 32 + "/full.png"):
        assert c.get(base + "/render/" + bad).status_code == 404, bad
    r = c.get(base + "/version/2/file", params={"path": "docs/findings.md"})
    assert r.status_code == 200 and r.content == open(
        os.path.join(folder, "docs", "findings.md"), "rb").read()
    assert c.get(base + "/version/2/file", params={"path": "x.md"}).status_code == 404
    # The next turn's primer has the checks; the person's edit is a version first.
    with open(os.path.join(folder, "docs", "findings.md"), "a") as fp:
        fp.write("\nMine.\n")
    _post(c, base + "/ask", tok, {"text": "and now?"})
    ag.wait(cid)
    primer = open(os.path.join(ag.root(), cid, "primer.md")).read()
    assert "## Checks on what you changed last turn" in primer
    assert "docs/findings.md: clipped-text" in primer and "wpk studio look" in primer
    vs = c.get(base + "/versions").json()["versions"]
    assert vs[2]["by"] == "alice" and vs[2]["changed"][0]["path"] == "docs/findings.md"
    # Keep and restore.
    r = _post(c, base + "/keep", tok, {"n": 2, "keep": True})
    assert r.status_code == 200 and r.json()["version"]["keep"]
    r = _post(c, base + "/restore", tok, {"n": 2})
    assert r.status_code == 200 and r.json()["version"]["note"] == "restored v2"
    assert "Mine." not in open(os.path.join(folder, "docs", "findings.md")).read()
    assert _post(c, base + "/restore", tok, {"n": 99}).status_code == 400
    # Closing: a last version, and the step lists the session's versions.
    model.close_studio(e, pkt.wpid, "alice")
    steps = sorted(os.listdir(os.path.join(pkt.path, "steps")))
    meta = json.load(open(os.path.join(pkt.path, "steps", steps[-1], "meta.json")))
    assert meta["studio"]["versions"] == [v["n"] for v in versions.all_(e, pkt.wpid)]
    assert c.get(base + "/versions").status_code == 403


def test_frames_in_render_mode(board):
    pytest.importorskip("duckdb")
    c, e, pkt, ag, tok, base, folder = board
    _w(folder, "docs/a.md", "# A\n")
    _w(folder, "data/r.csv", "a,b\n1,x\n2,y\n")
    _w(folder, "charts/c.vl.json", json.dumps({"data": {"url": "../data/r.csv"}, "mark": "bar"}))
    r = c.get(base + "/frame/doc", params={"path": "docs/a.md", "render": "1"})
    assert 'class="docbar' not in r.text
    assert 'class="docbar' in c.get(base + "/frame/doc", params={"path": "docs/a.md"}).text
    r = c.get(base + "/frame/chart", params={"path": "charts/c.vl.json", "render": "1"})
    if vendored.built("vega"):
        assert "studio_wait.js" in r.text and 'id="ch-panel"' not in r.text and 'data-render="1"' in r.text
    else:
        assert "not built" in r.text
    r = c.get(base + "/frame/table", params={"path": "data/r.csv", "render": "1"})
    assert r.status_code == 200 and "2 rows" in r.text and "<td>x</td>" in r.text
    from work_packet.studio import kernel
    kernel.stop(folder)
