"""Tables and charts on the board (docs/studio-plan.md S2.3, S2.4, S2.6): the
table routes over the kernel, the SQL box and saved queries, chart specs (check,
data by path, the theme, the spec panel), selections that ask the agent about
rows, and the primer's data section."""

import json
import os
import re
import warnings

import pytest

duckdb = pytest.importorskip("duckdb")

from test_dash_tasks import _new  # noqa: E402
from work_packet import layout, registry  # noqa: E402
from work_packet.dash.agent import Agents  # noqa: E402
from work_packet.dash import vendored  # noqa: E402
from work_packet.studio import chart, kernel, model, primer  # noqa: E402

SECRET = b"k" * 32
BASE = "http://127.0.0.1:7878"
CSV = "week,test,fails\n2026-10-05,uart,3\n2026-10-12,uart,5\n2026-10-12,spi,1\n2026-10-19,uart,0\n"
SPEC = {"$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "data": {"url": "../data/r.csv"}, "mark": "bar",
        "params": [{"name": "pick", "select": {"type": "interval", "encodings": ["x"]}}],
        "encoding": {"x": {"field": "week", "type": "temporal"},
                     "y": {"field": "fails", "type": "quantitative", "aggregate": "sum"}}}


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def board(tmp_path, fake):
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard, csrf_token
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    fake("studio")
    e, pkt = _new("a")
    e = registry.get("a")
    folder = layout.packet_folder(e["path"])
    os.makedirs(os.path.join(folder, "data"))
    os.makedirs(os.path.join(folder, "charts"))
    with open(os.path.join(folder, "data", "r.csv"), "w") as fp:
        fp.write(CSV)
    with open(os.path.join(folder, "charts", "f.vl.json"), "w") as fp:
        json.dump(SPEC, fp)
    ag = Agents(os.environ["WPK_HOME"])
    g = Guard(create_app(agents=ag), "loopback", SECRET, local_user="alice")
    with TestClient(g, base_url=BASE, client=("127.0.0.1", 50000)) as c:
        base = "/p/a/%s/studio" % pkt.wpid
        tok = csrf_token(SECRET)
        c.post(base + "/open", data={"csrf": tok}, headers={"origin": BASE},
               follow_redirects=False)
        yield c, e, pkt, ag, tok, base, folder
    kernel.stop(folder)


def _post(c, url, tok, body=None):
    return c.post(url, json=body or {}, headers={"origin": BASE, "x-csrf-token": tok})


# --- charts, without the board -----------------------------------------------------

def test_chart_check_and_rewrite(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "r.csv").write_text(CSV)
    assert chart.check(SPEC, "charts/f.vl.json", str(tmp_path)) == []
    bad = dict(SPEC, data={"url": "https://example.com/x.csv"})
    assert "studio's folder" in chart.check(bad, "charts/f.vl.json", str(tmp_path))[0]
    bad = dict(SPEC, data={"url": "../../etc/x.csv"})
    assert "outside" in chart.check(bad, "charts/f.vl.json", str(tmp_path))[0]
    assert "no such file" in chart.check(dict(SPEC, data={"url": "../data/x.csv"}),
                                         "charts/f.vl.json", str(tmp_path))[0]
    assert "not a table" in chart.check(dict(SPEC, data={"url": "../notes.md"}),
                                        "charts/f.vl.json", str(tmp_path))[0]
    assert "no view" in chart.check({"data": {"url": "r.csv"}}, "x.vl.json", str(tmp_path))[0]
    assert "unknown mark" in chart.check(dict(SPEC, mark="pie3d"), "charts/f.vl.json",
                                         str(tmp_path))[0]
    layered = {"layer": [{"data": {"url": "../data/r.csv", "format": {"type": "csv",
                                                                      "parse": {"w": "date"}}},
                          "mark": "line"}]}
    out = chart.for_board(layered, "charts/f.vl.json", lambda p: "/B/data?path=" + p)
    assert out["layer"][0]["data"] == {"url": "/B/data?path=data/r.csv",
                                       "format": {"type": "json", "parse": {"w": "date"}}}
    assert layered["layer"][0]["data"]["url"] == "../data/r.csv"      # a copy
    assert chart.first_source(layered, "charts/f.vl.json") == "data/r.csv"


def test_theme_follows_the_dash_tokens():
    """The chart palette is the dash's --sp0..--sp7, light and dark."""
    from work_packet.dash import app
    base = open(os.path.join(os.path.dirname(app.__file__), "templates", "base.html")).read()
    light, dark = base.split("prefers-color-scheme: dark")[:2]
    for mode, css in (("light", light), ("dark", dark)):
        sp = [re.search(r"--sp%d: (#[0-9a-f]{6})" % i, css).group(1) for i in range(8)]
        assert chart.PALETTE[mode] == sp, mode
        t = chart.theme(mode)
        assert t["range"]["category"] == sp and t["background"] == chart.INK[mode][3]
        assert re.search(r"--panel: %s" % t["background"], css)


def test_spec_panel_round_trip():
    p = chart.summary(SPEC)
    assert p["mark"] == "bar" and p["y"] == {"field": "fails", "type": "quantitative",
                                             "aggregate": "sum"}
    s = chart.apply(SPEC, {"mark": "line", "title": "Fails by week",
                           "color": {"field": "test", "type": "nominal"},
                           "y": {"field": "fails", "type": "quantitative", "aggregate": ""}})
    assert s["mark"] == "line" and s["title"] == "Fails by week"
    assert s["encoding"]["color"] == {"field": "test", "type": "nominal"}
    assert "aggregate" not in s["encoding"]["y"] and s["params"] == SPEC["params"]
    assert chart.summary({"layer": []}) is None
    with pytest.raises(chart.ChartError):
        chart.apply(SPEC, {"mark": "pie3d"})


def test_primer_lists_datasets():
    st = {"folder": "/f", "canvas": [], "layout": {"open": []}}
    text = primer.build({"name": "a"}, "w", st, datasets=[
        {"path": "data/r.csv", "rows": 4, "columns": [{"name": "week", "type": "DATE"},
                                                      {"name": "fails", "type": "BIGINT"}]},
        {"path": "bad.csv", "error": "cannot parse"}])
    assert "## Data" in text and "- data/r.csv: 4 rows; week date, fails bigint" in text
    assert "- bad.csv: cannot parse" in text and "wpk studio query" in text


# --- the board -----------------------------------------------------------------------

def test_table_routes(board):
    c, e, pkt, ag, tok, base, folder = board
    r = c.get(base + "/table", params={"path": "data/r.csv", "sort": "fails", "desc": "1",
                                       "limit": "2"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 4 and j["rows"][0] == ["2026-10-12", "uart", 5]
    j = c.get(base + "/table", params={"path": "data/r.csv", "f.test": "spi"}).json()
    assert j["total"] == 1
    st = c.get(base + "/table/stats", params={"path": "data/r.csv"}).json()
    assert [x["name"] for x in st["columns"]] == ["week", "test", "fails"]
    for bad in ("../x.csv", "charts/f.vl.json", "nope.csv", ".studio/kernel.json"):
        assert c.get(base + "/table", params={"path": bad}).status_code == 404, bad
    r = c.get(base + "/table", params={"path": "data/r.csv", "sort": "nope"})
    assert r.status_code == 400 and "nope" in r.json()["error"]


def test_sql_box_and_saved_queries(board):
    c, e, pkt, ag, tok, base, folder = board
    sql = "SELECT test, sum(fails) AS n FROM 'data/r.csv' GROUP BY 1"
    r = _post(c, base + "/sql", tok, {"sql": sql, "sort": "n", "desc": True})
    assert r.status_code == 200 and r.json()["rows"] == [["uart", 8], ["spi", 1]]
    for bad in ("COPY (SELECT 1) TO 'x.csv'", "SELECT * FROM '/etc/passwd'",
                "SELECT * FROM '../../x.csv'", "DROP TABLE x", "SELECT 1; SELECT 2"):
        r = _post(c, base + "/sql", tok, {"sql": bad})
        assert r.status_code == 400, bad
    assert not os.path.exists(os.path.join(folder, "x.csv"))
    r = _post(c, base + "/sql/save", tok, {"sql": sql, "path": "queries/by-test.sql"})
    assert r.status_code == 200 and r.json()["path"] == "queries/by-test.sql"
    assert open(os.path.join(folder, "queries", "by-test.sql")).read() == sql + ";\n"
    assert _post(c, base + "/sql/save", tok, {"sql": "DROP TABLE x",
                                              "path": "q.sql"}).status_code == 400
    assert _post(c, base + "/sql/save", tok, {"sql": sql, "path": "q.txt"}).status_code == 400
    assert _post(c, base + "/sql/save", tok, {"sql": sql,
                                              "path": "../q.sql"}).status_code == 400
    # A saved query is a table, and follows its input file.
    j = c.get(base + "/table", params={"path": "queries/by-test.sql", "sort": "n"}).json()
    assert j["rows"][0] == ["spi", 1]
    with open(os.path.join(folder, "data", "r.csv"), "a") as fp:
        fp.write("2026-10-26,spi,7\n")
    j = c.get(base + "/table", params={"path": "queries/by-test.sql", "sort": "n"}).json()
    assert j["rows"] == [["spi", 8], ["uart", 8]] or j["rows"] == [["uart", 8], ["spi", 8]]
    # history.steps is there for the SQL box.
    r = _post(c, base + "/sql", tok, {"sql": "SELECT count(*) AS n FROM history.steps"})
    assert r.status_code == 200 and r.json()["columns"] == [{"name": "n", "type": "BIGINT"}]


@pytest.mark.skipif(not vendored.built("vega"), reason=vendored.NOT_BUILT)
def test_chart_frame_data_and_panel(board):
    c, e, pkt, ag, tok, base, folder = board
    r = c.get(base + "/frame/chart", params={"path": "charts/f.vl.json"})
    assert r.status_code == 200 and "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert "/static/studio_chart.js" in r.text and 'id="console"' not in r.text
    spec = json.loads(r.text.split('id="ch-spec">')[1].split("</script>")[0])
    assert spec["data"] == {"url": base + "/data?path=data/r.csv", "format": {"type": "json"}}
    rows = c.get(spec["data"]["url"]).json()
    assert rows[0] == {"week": "2026-10-05", "test": "uart", "fails": 3}
    assert c.get("/static/studio_chart.js").status_code == 200
    # A spec that can't be drawn says why.
    with open(os.path.join(folder, "charts", "bad.vl.json"), "w") as fp:
        json.dump(dict(SPEC, data={"url": "../../../etc/passwd.csv"}), fp)
    r = c.get(base + "/frame/chart", params={"path": "charts/bad.vl.json"})
    assert r.status_code == 200 and "can't be drawn" in r.text and "outside" in r.text
    assert c.get(base + "/frame/chart", params={"path": "data/r.csv"}).status_code == 404
    # The spec panel writes into the spec.
    r = _post(c, base + "/chart", tok, {"path": "charts/f.vl.json",
                                        "panel": {"mark": "line", "title": "Fails"}})
    assert r.status_code == 200, r.text
    s = json.load(open(os.path.join(folder, "charts", "f.vl.json")))
    assert s["mark"] == "line" and s["title"] == "Fails" and s["params"] == SPEC["params"]
    r = _post(c, base + "/chart", tok, {"path": "charts/f.vl.json", "panel": {"mark": "x"}})
    assert r.status_code == 400


def test_selection_asks_with_rows(board):
    c, e, pkt, ag, tok, base, folder = board
    import datetime
    ms = lambda d: int(datetime.datetime(2026, 10, d, tzinfo=datetime.timezone.utc  # noqa: E731
                                         ).timestamp() * 1000)
    r = _post(c, base + "/select", tok, {"path": "charts/f.vl.json",
                                         "selection": {"kind": "interval",
                                                       "week": [ms(10), ms(20)]},
                                         "text": "Why so many?"})
    assert r.status_code == 200, r.text
    cid = model.state(e, pkt.wpid)["session"]["conv"]
    ag.wait(cid)
    asked = [x["text"] for x in ag.transcript(cid) if x["k"] == "ask"][-1]
    assert "charts/f.vl.json" in asked and "data/r.csv" in asked and "3 rows" in asked
    assert "uart" in asked and "spi" in asked and asked.rstrip().endswith("Why so many?")
    assert _post(c, base + "/select", tok, {"path": "charts/f.vl.json",
                                            "selection": {}}).status_code == 400
    r = _post(c, base + "/select", tok, {"path": "charts/f.vl.json",
                                         "selection": {"nope": [1, 2]}})
    assert r.status_code == 400


def test_only_the_taker_and_the_primer(board):
    c, e, pkt, ag, tok, base, folder = board
    cid = model.state(e, pkt.wpid)["session"]["conv"]
    _post(c, base + "/ask", tok, {"text": "what data is there?"})
    ag.wait(cid)
    p = open(os.path.join(ag.root(), cid, "primer.md")).read()
    assert "## Data" in p and "data/r.csv: 4 rows; week date" in p and "history.steps" in p
    model.close_studio(e, pkt.wpid, "alice")
    assert not kernel.alive(folder)
    for url in ("/table?path=data/r.csv", "/data?path=data/r.csv",
                "/frame/chart?path=charts/f.vl.json"):
        assert c.get(base + url).status_code == 403, url
    for url in ("/sql", "/sql/save", "/chart", "/select"):
        assert _post(c, base + url, tok, {"sql": "SELECT 1", "path": "charts/f.vl.json"}
                     ).status_code == 403, url
