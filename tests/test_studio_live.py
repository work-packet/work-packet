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
