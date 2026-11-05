"""The studio page in a real browser (docs/studio-plan.md S1.5): it loads, draws
the canvas with a document frame and an image, and logs no errors (CSP
refusals among them). ``WPK_LIVE=1``, with a browser on PATH."""

import os
import socket
import threading
import time
import warnings

import pytest

from test_dash_tasks import _new
from work_packet import layout, registry
from work_packet.studio import model, render

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("WPK_LIVE") != "1" or not render.find_browser({}),
                       reason="set WPK_LIVE=1, with a browser on PATH"),
]

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
                    "0000000c4944415478da63f8cfc0000003010100c9fe92ef0000000049454e44ae426082")


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def served(tmp_path, fake):
    import uvicorn
    from work_packet.dash.agent import Agents
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    fake("studio")
    e, pkt = _new("a")
    e = registry.get("a")
    me = "alice"
    ag = Agents(os.environ["WPK_HOME"])
    app = Guard(create_app(agents=ag), "loopback", b"k" * 32, local_user=me)
    port = _port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                        lifespan="off"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.05)
    yield "http://127.0.0.1:%d" % port, e, pkt, ag, me
    srv.should_exit = True
    t.join(5)


def test_live_studio_page(served, tmp_path):
    base, e, pkt, ag, me = served
    from work_packet.studio import record  # noqa: F401  (imported as the page uses it)
    folder = layout.packet_folder(e["path"])
    os.makedirs(os.path.join(folder, "docs"))
    with open(os.path.join(folder, "docs", "f.md"), "w") as fp:
        fp.write("# Findings\n\nThe {==flaky==}{>> which? <<} tests cluster in uart.\n")
    with open(os.path.join(folder, "p.png"), "wb") as fp:
        fp.write(PNG)
    scope = {"kind": "packet", "project": "a", "wpid": pkt.wpid}
    conv = ag.new(scope, folder, me, model="haiku", project_dir=e["path"], mode="studio")
    model.open_studio(e, pkt.wpid, me, conv=conv["id"])
    model.pin(e, pkt.wpid, "p.png", me)
    model.pin(e, pkt.wpid, "docs/f.md", me)
    model.set_layout(e, pkt.wpid, mode="two-up", open_paths=["docs/f.md", "p.png"])
    b = render.Browser(home=str(tmp_path / "home"))
    try:
        r = b.render(base + "/p/a/%s/studio" % pkt.wpid, ready_timeout_s=10,
                     png=str(tmp_path / "studio.png"), width=1300, height=800,
                     script="new Promise(r => setTimeout(() => r({"
                            "tabs: document.querySelectorAll('.st-tab').length, "
                            "frames: document.querySelectorAll('.st-tile iframe').length, "
                            "imgs: document.querySelectorAll('.st-tile img').length, "
                            "doc: (document.querySelector('.st-tile iframe') || {}).contentDocument"
                            " ? document.querySelector('.st-tile iframe').contentDocument"
                            ".querySelectorAll('.cm-comment').length : -1}), 1500))")
    finally:
        b.stop()
    assert r["errors"] == [], r["errors"]
    v = r["value"]
    assert v["tabs"] == 2 and v["frames"] == 1 and v["imgs"] == 1, v
    assert v["doc"] == 1, v                       # the markup rendered inside the frame


def test_live_tree_and_editor(served, tmp_path):
    """v2 V1: the tree with its Packet section, a plan file and a source file in
    tabs, CodeMirror in the source tab, and the merge view (docs/studio-v2.md)."""
    from work_packet.dash import vendored
    if not vendored.built("codemirror"):
        pytest.skip(vendored.NOT_BUILT)
    base, e, pkt, ag, me = served
    folder = layout.packet_folder(e["path"])
    os.makedirs(os.path.join(folder, "src"))
    with open(os.path.join(folder, "src", "cli.py"), "w") as fp:
        fp.write("def main():\n    return 1\n")
    with open(os.path.join(pkt.state_dir, "outline.md"), "w") as fp:
        fp.write("- [ ] 1 parse {>>why?<<}\n")
    scope = {"kind": "packet", "project": "a", "wpid": pkt.wpid}
    conv = ag.new(scope, folder, me, model="haiku", project_dir=e["path"], mode="studio")
    model.open_studio(e, pkt.wpid, me, conv=conv["id"])
    model.pin(e, pkt.wpid, "wp:state/outline.md", me)
    model.pin(e, pkt.wpid, "src/cli.py", me)
    model.set_layout(e, pkt.wpid, mode="two-up", open_paths=["wp:state/outline.md", "src/cli.py"])
    b = render.Browser(home=str(tmp_path / "home"))
    try:
        r = b.render(base + "/p/a/%s/studio" % pkt.wpid, ready_timeout_s=10,
                     png=str(tmp_path / "studio-v2.png"), width=1400, height=800,
                     script="new Promise(r => setTimeout(() => {"
                            "const d = document.createElement('div'); document.body.appendChild(d);"
                            "import('/static/studio_edit.js').then(m => {"
                            " m.makeMerge(d, {mine: 'a\\nb\\n', theirs: 'a\\nc\\n', name: 'x.md'});"
                            " r({rows: [...document.querySelectorAll('#st-tree .ft-row')].map(x => x.textContent),"
                            "   cm: document.querySelectorAll('.st-tile .cm-editor').length,"
                            "   text: (document.querySelector('.st-tile .cm-content') || {}).textContent,"
                            "   frames: document.querySelectorAll('.st-tile iframe').length,"
                            "   merge: document.querySelectorAll('.cm-mergeView').length,"
                            "   tabs: [...document.querySelectorAll('.st-tab')].map(x => x.textContent)});"
                            "});}, 2000))")
    finally:
        b.stop()
    assert r["errors"] == [], r["errors"]
    v = r["value"]
    assert any(x.startswith("▾ Packet") for x in v["rows"]), v["rows"]
    assert any("outline.md" in x and "1" in x for x in v["rows"]), v["rows"]
    assert any(x.startswith("▸ src") for x in v["rows"]), v["rows"]
    assert v["cm"] == 1 and "def main" in v["text"], v
    assert v["frames"] == 1 and v["merge"] == 1, v
    assert v["tabs"][0].startswith("plan: outline.md"), v["tabs"]


def test_live_chart_and_table(served, tmp_path):
    """S2.3/S2.4: a chart (Vega-Lite in its frame, with the studio's theme and a
    selection) and a table (from the kernel) side by side, with no errors."""
    pytest.importorskip("duckdb")
    import json
    from work_packet.studio import kernel
    base, e, pkt, ag, me = served
    folder = layout.packet_folder(e["path"])
    os.makedirs(os.path.join(folder, "data"))
    os.makedirs(os.path.join(folder, "charts"))
    with open(os.path.join(folder, "data", "r.csv"), "w") as fp:
        fp.write("week,test,fails\n2026-10-05,uart,3\n2026-10-12,uart,5\n"
                 "2026-10-12,spi,1\n2026-10-19,uart,0\n")
    with open(os.path.join(folder, "charts", "f.vl.json"), "w") as fp:
        json.dump({"data": {"url": "../data/r.csv"}, "mark": "bar", "title": "Fails by test",
                   "params": [{"name": "pick", "select": {"type": "point", "fields": ["test"]}}],
                   "encoding": {"x": {"field": "test", "type": "nominal"},
                                "y": {"field": "fails", "type": "quantitative",
                                      "aggregate": "sum"}}}, fp)
    scope = {"kind": "packet", "project": "a", "wpid": pkt.wpid}
    conv = ag.new(scope, folder, me, model="haiku", project_dir=e["path"], mode="studio")
    model.open_studio(e, pkt.wpid, me, conv=conv["id"])
    model.pin(e, pkt.wpid, "charts/f.vl.json", me)
    model.pin(e, pkt.wpid, "data/r.csv", me)
    model.set_layout(e, pkt.wpid, mode="two-up", open_paths=["charts/f.vl.json", "data/r.csv"])
    b = render.Browser(home=str(tmp_path / "home"))
    try:
        r = b.render(base + "/p/a/%s/studio" % pkt.wpid, ready_timeout_s=10,
                     png=str(tmp_path / "s2.png"), width=1400, height=800,
                     script="new Promise(r => setTimeout(() => { const f = document.querySelector("
                            "'.st-tile iframe'); const d = f && f.contentDocument; r({"
                            "bars: d ? d.querySelectorAll('#chart svg .mark-rect path').length : -1, "
                            "msg: d ? d.getElementById('ch-msg').textContent : '', "
                            "rows: document.querySelectorAll('.st-table tbody tr').length, "
                            "where: (document.querySelector('.st-table .tb-bar') || {}).textContent"
                            "}); }, 3000))")
    finally:
        b.stop()
        kernel.stop(folder)
    assert r["errors"] == [], r["errors"]
    v = r["value"]
    assert v["bars"] == 2 and v["msg"] == "", v                    # uart and spi
    assert v["rows"] == 4 and "1–4 of 4" in v["where"], v


def test_live_renders_and_checks(tmp_path, fake):
    """S3.1/S3.5: each kind rendered by the real browser through the render
    listener; the cheap checks flag a too-wide table and a chart title that
    runs off the page, and nothing on clean pages."""
    pytest.importorskip("duckdb")
    import json
    import uvicorn
    from work_packet.dash.app import create_app
    from work_packet.dash.render_gate import RenderGate
    from work_packet.studio import kernel, renders
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    e, pkt = _new("a")
    e = registry.get("a")
    folder = layout.packet_folder(e["path"])

    def w(rel, text):
        p = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fp:
            fp.write(text)
    w("docs/clean.md", "# Findings\n\nThe flaky tests cluster in uart.\n")
    w("docs/wide.md", "# Wide\n\n| a | b |\n|---|---|\n| %s | x |\n" % ("y" * 400))
    w("data/r.csv", "test,fails\nuart,5\nspi,1\n")
    w("charts/ok.vl.json", json.dumps({"data": {"url": "../data/r.csv"}, "mark": "bar",
                                       "encoding": {"x": {"field": "test", "type": "nominal"},
                                                    "y": {"field": "fails",
                                                          "type": "quantitative"}}}))
    w("charts/hbar.vl.json", json.dumps({"data": {"url": "../data/r.csv"}, "mark": "bar",
                                         "encoding": {"y": {"field": "test", "type": "nominal"},
                                                      "x": {"field": "fails",
                                                            "type": "quantitative"}}}))
    w("charts/long.vl.json", json.dumps({"data": {"url": "../data/r.csv"}, "mark": "bar",
                                         "width": 200, "title": "A title " * 30,
                                         "encoding": {"x": {"field": "test", "type": "nominal"},
                                                      "y": {"field": "fails",
                                                            "type": "quantitative"}}}))
    model.open_studio(e, pkt.wpid, "alice")
    b = render.Browser(home=str(tmp_path / "rhome"))
    svc = renders.Service(os.environ["WPK_HOME"], browser=b)
    port = _port()
    srv = uvicorn.Server(uvicorn.Config(RenderGate(create_app(), svc), host="127.0.0.1",
                                        port=port, log_level="warning", lifespan="off"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.05)
    svc.base_url = "http://127.0.0.1:%d" % port
    try:
        got = {rel: svc.render(e, pkt.wpid, rel, "alice") for rel in (
            "docs/clean.md", "docs/wide.md", "charts/ok.vl.json", "charts/hbar.vl.json",
            "charts/long.vl.json", "data/r.csv")}
    finally:
        b.stop()
        kernel.stop(folder)
        srv.should_exit = True
        t.join(5)
    for rel, inf in got.items():
        d = os.path.join(renders.render_dir(e, pkt.wpid), inf["key"])
        assert os.path.getsize(os.path.join(d, "full.png")) > 1000, rel
        assert os.path.getsize(os.path.join(d, "thumb.png")) < os.path.getsize(
            os.path.join(d, "full.png")), rel
    assert got["docs/clean.md"]["checks"] == [], got["docs/clean.md"]["checks"]
    assert got["charts/ok.vl.json"]["checks"] == [], got["charts/ok.vl.json"]["checks"]
    assert got["charts/hbar.vl.json"]["checks"] == [], got["charts/hbar.vl.json"]["checks"]
    assert got["data/r.csv"]["checks"] == [], got["data/r.csv"]["checks"]
    assert any(c["check"] == "overflow" and "table" in c["what"]
               for c in got["docs/wide.md"]["checks"]), got["docs/wide.md"]["checks"]
    assert any(c["check"] in ("overflow", "clipped-text")
               for c in got["charts/long.vl.json"]["checks"]), got["charts/long.vl.json"]
