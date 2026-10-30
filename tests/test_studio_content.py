"""Frames and the content origin (docs/studio-plan.md P0.6): studio frames may be
framed by the board; untrusted pages are served sandboxed under /sc/<token>/,
with no cookies and no way into the board. The ``live`` tests load pages in
headless Chrome against a real server."""

import json
import os
import socket
import threading
import time
import warnings

import pytest

from work_packet.studio import content, render

SECRET = b"k" * 32
BASE = "http://127.0.0.1:7878"


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "folder"
    (d / "pages").mkdir(parents=True)
    (d / "pages" / "a.html").write_text("<p>hi</p>")
    (d / "index.html").write_text("<p>index</p>")
    (d / ".work-packet").mkdir()
    (d / ".work-packet" / "project.toml").write_text("secret")
    (tmp_path / "outside.txt").write_text("outside")
    os.symlink(tmp_path / "outside.txt", d / "link.txt")
    return d


def _guarded(app=None):
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    g = Guard(app or create_app(), "loopback", SECRET, local_user="alice")
    return TestClient(g, base_url=BASE, client=("127.0.0.1", 50000))


def _csp(r):
    return r.headers.get("content-security-policy", "")


# --- tokens and files ------------------------------------------------------------

def test_tokens(tmp_path):
    now = [1000.0]
    t = content.Tokens(ttl_s=60, clock=lambda: now[0])
    a = t.issue(str(tmp_path))
    b = t.issue(str(tmp_path), ttl_s=600)
    c = t.issue(str(tmp_path / "other"), ttl_s=600)
    assert t.resolve(a) == os.path.realpath(tmp_path) and len(a) >= 32
    assert t.resolve("nope") is None and t.resolve(None) is None and t.resolve("") is None
    now[0] += 61
    assert t.resolve(a) is None and t.resolve(b)            # a expired
    t.revoke_root(str(tmp_path))
    assert t.resolve(b) is None and t.resolve(c)            # the studio closed
    t.revoke(c)
    assert t.resolve(c) is None


def test_file_for(folder):
    root = os.path.realpath(folder)
    assert content.file_for(root, "pages/a.html").endswith("pages/a.html")
    assert content.file_for(root, "").endswith("index.html")
    assert content.file_for(root, "pages/") is None                 # no index there
    for bad in ("../outside.txt", "pages/../../outside.txt", "link.txt",
                ".work-packet/project.toml", "pages/./a.html", "x\0y", "nope.html"):
        assert content.file_for(root, bad) is None, bad
    assert content.split("/sc/tok/a/b.html") == ("tok", "a/b.html")
    assert content.split("/sc/tok") == ("tok", "")
    assert content.split("/p/x") == (None, None)


# --- headers per route -----------------------------------------------------------

def test_board_pages_refuse_framing(tmp_path, fake):
    with _guarded() as c:
        r = c.get("/")
        assert "frame-ancestors 'none'" in _csp(r) and r.headers["x-frame-options"] == "DENY"
        r = c.get("/p/a/0123/studio/frame/doc")             # a studio frame (404 for now)
        csp = _csp(r)
        assert "frame-ancestors 'self'" in csp and r.headers["x-frame-options"] == "SAMEORIGIN"
        assert "img-src 'self' data: blob:" in csp and "worker-src 'self' blob:" in csp
        assert "script-src 'self' 'wasm-unsafe-eval'" in csp and "unsafe-eval'" not in \
            csp.replace("wasm-unsafe-eval", "")
        r = c.get("/p/a/0123/studio/framework")             # not a frame
        assert "frame-ancestors 'none'" in _csp(r)


def test_content_needs_a_live_token(tmp_path, fake, folder):
    tok = content.TOKENS.issue(str(folder))
    try:
        with _guarded() as c:
            assert c.get("/sc/nope/pages/a.html").status_code == 403
            assert c.get("/sc//pages/a.html").status_code == 403
            r = c.get("/sc/%s/pages/a.html" % tok)
            assert r.status_code == 200 and r.text == "<p>hi</p>"
            assert r.headers["content-type"].startswith("text/html")
            assert _csp(r).startswith("sandbox allow-scripts")
            assert "allow-same-origin" not in _csp(r)
            assert r.headers["referrer-policy"] == "no-referrer"
            assert "x-frame-options" not in r.headers and "set-cookie" not in r.headers
            assert c.get("/sc/%s/" % tok).text == "<p>index</p>"
            assert c.get("/sc/%s/.work-packet/project.toml" % tok).status_code == 404
            assert c.get("/sc/%s/link.txt" % tok).status_code == 404
            hdr = {"origin": BASE, "x-csrf-token": "x"}
            assert c.post("/sc/%s/pages/a.html" % tok, headers=hdr).status_code == 405
            content.TOKENS.revoke(tok)
            assert c.get("/sc/%s/pages/a.html" % tok).status_code == 403   # stale
    finally:
        content.TOKENS.revoke(tok)


def test_content_never_sets_cookies(folder):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    def page(request):
        r = PlainTextResponse("x")
        r.set_cookie("sid", "1")
        r.headers["content-security-policy"] = "default-src *"     # replaced, not kept
        return r
    app = Starlette(routes=[Route("/sc/{token}/{path:path}", page)])
    tok = content.TOKENS.issue(str(folder))
    try:
        with _guarded(app) as c:
            r = c.get("/sc/%s/x" % tok)
            assert r.status_code == 200 and "set-cookie" not in r.headers
            assert _csp(r) == content.CSP
    finally:
        content.TOKENS.revoke(tok)


# --- live: a real server and a real browser ------------------------------------------

live = pytest.mark.skipif(os.environ.get("WPK_LIVE") != "1" or not render.find_browser({}),
                          reason="set WPK_LIVE=1, with a browser on PATH")

PARENT = """<!doctype html><html><body>
<iframe sandbox="allow-scripts" src="/sc/%s/evil.html"></iframe>
<script src="/test/parent.js"></script></body></html>"""
PARENT_JS = """window.__studioReady = false;
window.addEventListener("message", (e) => { window.__result = e.data; window.__studioReady = true; });
"""
EVIL = """<!doctype html><html><body><script>
const out = {};
try { out.cookie = "read: " + document.cookie; } catch (e) { out.cookie = "threw " + e.name; }
try { out.storage = "read: " + localStorage.length; } catch (e) { out.storage = "threw " + e.name; }
try { out.parent = "read: " + parent.document.title; } catch (e) { out.parent = "threw " + e.name; }
out.origin = String(self.origin);
fetch("/p/a/markup", {method: "POST", body: "csrf=x"})
  .then(r => { out.post = "status " + r.status; })
  .catch(e => { out.post = "failed " + e.name; })
  .finally(() => parent.postMessage(out, "*"));
</script></body></html>"""
LIBS = """<!doctype html><html><head>
<link rel="stylesheet" href="/static/vendor/draw/excalidraw.css">
<script src="/test/asset-path.js"></script>
<script type="module" src="/test/libs.js"></script></head>
<body><div id="chart"></div><div id="diagram"></div>
<div id="sketch" style="width:600px;height:400px"></div></body></html>"""
ASSET_PATH_JS = """window.EXCALIDRAW_ASSET_PATH = "/static/vendor/draw/";
window.__studioReady = false; window.__violations = [];
document.addEventListener("securitypolicyviolation",
  (e) => window.__violations.push(e.violatedDirective + " " + e.blockedURI));
"""
LIBS_JS = """import { embed, expressionInterpreter } from "/static/vendor/vega/vega.js";
import mermaid from "/static/vendor/draw/mermaid.js";
import { React, createRoot, Excalidraw, convertToExcalidrawElements }
  from "/static/vendor/draw/excalidraw.js";
const done = {};
try {
  await embed("#chart", {"$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    data: {values: [{a: "x", b: 2}, {a: "y", b: 5}]}, mark: "bar",
    encoding: {x: {field: "a", type: "nominal"}, y: {field: "b", type: "quantitative"}},
    transform: [{calculate: "datum.b * 2", as: "c"}]},
    {ast: true, expr: expressionInterpreter, renderer: "svg", actions: false});
  done.vega = document.querySelectorAll("#chart svg .mark-rect path").length;
} catch (e) { done.vega = "error " + e; }
try {
  mermaid.initialize({startOnLoad: false, securityLevel: "strict"});
  const {svg} = await mermaid.render("m1", "graph TD; A-->B; B-->C");
  document.getElementById("diagram").innerHTML = svg;
  done.mermaid = document.querySelectorAll("#diagram .node").length;
} catch (e) { done.mermaid = "error " + e; }
try {
  const els = convertToExcalidrawElements([{type: "rectangle", x: 10, y: 10, width: 100,
    height: 60, label: {text: "DMA"}}]);
  createRoot(document.getElementById("sketch")).render(
    React.createElement(Excalidraw, {initialData: {elements: els}}));
  await new Promise(r => setTimeout(r, 1500));
  done.excalidraw = document.querySelectorAll("#sketch canvas").length;
} catch (e) { done.excalidraw = "error " + e; }
window.__result = done;
window.__studioReady = true;
"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(tmp_path, fake, folder):
    """A real board on a loopback port behind the guard, plus /test/ pages."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, Response
    from starlette.routing import Mount, Route
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard
    (folder / "evil.html").write_text(EVIL)
    tok = content.TOKENS.issue(str(folder))
    seen = []
    js = lambda body: (lambda request: Response(body, media_type="text/javascript"))  # noqa: E731
    test = Starlette(routes=[
        Route("/test/parent", lambda request: HTMLResponse(PARENT % tok)),
        Route("/test/parent.js", js(PARENT_JS)),
        Route("/test/asset-path.js", js(ASSET_PATH_JS)),
        Route("/test/libs.js", js(LIBS_JS)),
        Route("/p/x/y/studio/frame/libs", lambda request: HTMLResponse(LIBS)),
        Mount("/", app=create_app()),
    ])
    guarded = Guard(test, "loopback", SECRET, local_user="alice")

    async def recorder(scope, receive, send):
        async def rec(msg):
            if msg["type"] == "http.response.start":
                seen.append((scope.get("method"), scope.get("path"), msg["status"]))
            await send(msg)
        await guarded(scope, receive, rec)
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(recorder, host="127.0.0.1", port=port,
                                        log_level="warning", lifespan="off"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield "http://127.0.0.1:%d" % port, seen
    srv.should_exit = True
    t.join(5)
    content.TOKENS.revoke(tok)


@pytest.mark.live
@live
def test_live_sandboxed_page_cannot_reach_the_board(server, tmp_path):
    base, seen = server
    b = render.Browser(home=str(tmp_path / "home"))
    try:
        r = b.render(base + "/test/parent", script="JSON.stringify(window.__result)")
    finally:
        b.stop()
    assert r["ready"], r
    got = json.loads(r["value"])
    assert got["cookie"].startswith("threw ") and got["storage"].startswith("threw ")
    assert got["parent"].startswith("threw ") and got["origin"] == "null"
    assert got["post"].startswith("failed ")
    assert ("POST", "/p/a/markup", 403) in seen          # refused: Origin null
    assert any(p.startswith("/sc/") and s == 200 for _, p, s in seen)


@pytest.mark.live
@live
def test_live_libraries_run_under_the_frame_csp(server, tmp_path):
    base, seen = server
    b = render.Browser(home=str(tmp_path / "home"))
    try:
        r = b.render(base + "/p/x/y/studio/frame/libs", ready_timeout_s=30,
                     script="JSON.stringify({done: window.__result, "
                            "violations: window.__violations})")
    finally:
        b.stop()
    assert r["ready"], r
    got = json.loads(r["value"])
    fonts = [x for x in seen if "/fonts/" in x[1]]
    assert got["violations"] == [], (got["violations"][:3], fonts[:5])
    done = got["done"]
    assert done["vega"] == 2, done
    assert done["mermaid"] == 3, done
    assert isinstance(done["excalidraw"], int) and done["excalidraw"] >= 1, done
    assert [e for e in r["errors"] if "Content Security Policy" in e] == [], r["errors"]
