"""The studio's data and kernel (docs/studio-plan.md S2.1, S2.2, S2.5): queries
over the folder's files, the viewers' sandbox, the kernel process (state across
calls, crashes, time limits) and ``wpk studio exec|query|datasets``."""

import datetime
import json
import os
import sqlite3
import subprocess
import sys

import pytest

duckdb = pytest.importorskip("duckdb")

from test_dash_tasks import _new  # noqa: E402
from work_packet import layout, registry  # noqa: E402
from work_packet.studio import data, kernel, model  # noqa: E402

CSV = "week,test,fails\n2026-10-05,uart,3\n2026-10-12,uart,5\n2026-10-12,spi,1\n2026-10-19,uart,0\n"


@pytest.fixture
def folder(tmp_path, monkeypatch):
    f = tmp_path / "studio"
    (f / "data").mkdir(parents=True)
    (f / "data" / "r.csv").write_text(CSV)
    (tmp_path / "secret.csv").write_text("a\nsecret\n")
    monkeypatch.chdir(f)
    yield f
    kernel.stop(str(f))


def test_sources_pages_and_stats(folder):
    con = data.connect(sandbox=True)
    p = data.page(con, {"path": "data/r.csv"}, sort="fails", desc=True, limit=2)
    assert [c["name"] for c in p["columns"]] == ["week", "test", "fails"]
    assert p["total"] == 4 and p["rows"] == [["2026-10-12", "uart", 5], ["2026-10-05", "uart", 3]]
    p = data.page(con, {"path": "data/r.csv"}, filters={"test": "SP"})
    assert p["total"] == 1 and p["rows"][0][1] == "spi"
    with pytest.raises(data.DataError):
        data.page(con, {"path": "data/r.csv"}, sort="nope")
    st = {c["name"]: c for c in data.stats(con, {"path": "data/r.csv"})}
    assert st["fails"]["max"] == "5" and st["test"]["distinct"] == 2 and st["week"]["nulls"] == 0
    # A saved query, and a parquet file written from it.
    (folder / "q.sql").write_text("SELECT test, sum(fails) AS n FROM 'data/r.csv' GROUP BY 1;\n")
    p = data.page(con, {"path": "q.sql"}, sort="n", desc=True)
    assert p["rows"] == [["uart", 8], ["spi", 1]]
    duckdb.sql("COPY (SELECT * FROM 'data/r.csv') TO 'data/r.parquet' (FORMAT parquet)")
    assert data.page(con, {"path": "data/r.parquet"})["total"] == 4
    (folder / "data" / "e.jsonl").write_text('{"a": 1}\n{"a": 2}\n')
    assert data.page(con, {"path": "data/e.jsonl"})["rows"] == [[1], [2]]
    rows, cut = data.records(con, {"path": "data/r.csv"}, cap=3)
    assert cut and rows[0] == {"week": "2026-10-05", "test": "uart", "fails": 3}


def test_the_sandbox(folder):
    """The viewers' connection reads inside the folder only, and runs one
    SELECT: no writes, no settings, no attaching."""
    con = data.connect(sandbox=True)
    os.symlink(folder.parent / "secret.csv", folder / "link.csv")
    for src in ({"path": "../secret.csv"}, {"path": "/etc/passwd"}, {"path": ".git/x"},
                {"sql": "SELECT * FROM read_csv_auto('../secret.csv')"},
                {"sql": "SELECT * FROM '%s'" % (folder.parent / "secret.csv")},
                {"sql": "SELECT * FROM 'link.csv'"},
                {"sql": "COPY (SELECT 1) TO 'out.csv'"},
                {"sql": "SET enable_external_access=true"},
                {"sql": "ATTACH 'x.db' AS x"},
                {"sql": "SELECT 1; SELECT 2"},
                {"sql": "CREATE TABLE t AS SELECT 1"}):
        with pytest.raises(data.DataError):
            data.page(con, src)
    assert not (folder / "out.csv").exists()
    (folder / "w.sql").write_text("COPY (SELECT 1) TO 'out.csv'")
    with pytest.raises(data.DataError, match="SELECT only"):
        data.page(con, {"path": "w.sql"})


def test_sqlite_and_history(folder):
    db = sqlite3.connect(str(folder / "runs.db"))
    db.execute("CREATE TABLE run (id INTEGER, test TEXT)")
    db.execute("CREATE TABLE seed (n INTEGER)")
    db.executemany("INSERT INTO run VALUES (?, ?)", [(1, "uart"), (2, "spi")])
    db.commit()
    db.close()
    try:
        duckdb.connect().execute("LOAD sqlite")
    except duckdb.Error:
        pytest.skip("DuckDB's sqlite extension is not installed here")
    con = data.connect(sandbox=True)
    assert data.tables(con, {"path": "runs.db"}) == ["run", "seed"]
    assert data.page(con, {"path": "runs.db", "table": "run"})["total"] == 2
    with pytest.raises(data.DataError, match="no table"):
        data.page(con, {"path": "runs.db", "table": "x"})
    # history.steps: from the file wpk writes (empty: a typed, empty view).
    assert data.page(con, {"sql": "SELECT * FROM history.steps"})["total"] == 0
    with open(folder / data.HISTORY_FILE, "w") as fp:
        fp.write(json.dumps({"packet": "p1", "step": 1, "worker": "studio", "cost": 0.25,
                             "end": "2026-10-30T10:00:00Z", "failed": False}) + "\n")
    p = data.page(con, {"sql": "SELECT packet, worker, cost, \"end\" FROM history.steps"})
    assert p["rows"] == [["p1", "studio", 0.25, "2026-10-30T10:00:00"]]
    ds = {d["path"] + d.get("table", ""): d for d in data.datasets(con, ["runs.db", "x.md"])}
    assert set(ds) == {"runs.dbrun", "runs.dbseed", "history.steps"}


def test_selection_rows(folder):
    con = data.connect(sandbox=True)
    ms = lambda s: int(datetime.datetime.fromisoformat(s).replace(  # noqa: E731
        tzinfo=datetime.timezone.utc).timestamp() * 1000)
    got = data.selected(con, {"path": "data/r.csv"},
                        {"week": [ms("2026-10-10"), ms("2026-10-20")], "fails": [1, 9]})
    assert got["total"] == 2 and {r[1] for r in got["rows"]} == {"uart", "spi"}
    got = data.selected(con, {"path": "data/r.csv"}, {"kind": "point", "test": ["spi"]})
    assert got["total"] == 1
    with pytest.raises(data.DataError):
        data.selected(con, {"path": "data/r.csv"}, {"nope": [1, 2]})


def test_kernel_process(folder):
    f = str(folder)
    r = kernel.call(f, "exec", code="x = 41\nx + 1")
    assert r["ok"] and r["value"] == "42"
    assert kernel.call(f, "exec", code="x")["value"] == "41"           # state lasts
    r = kernel.call(f, "exec", code="print('hi')\n1/0")
    assert not r["ok"] and r["stdout"] == "hi\n" and "ZeroDivisionError" in r["stderr"]
    assert "kernel_main" not in r["stderr"]                             # the agent's frames only
    r = kernel.call(f, "exec", code="raise SystemExit(3)")
    assert not r["ok"] and kernel.call(f, "ping")["ok"]                 # still up
    # The agent's connection keeps tables between calls; the viewers' does not see them.
    kernel.call(f, "query", sql="CREATE TABLE t AS SELECT * FROM 'data/r.csv'")
    r = kernel.call(f, "query", sql="SELECT count(*) AS n FROM t")
    assert r["columns"] == ["n"] and r["rows"] == [[4]]
    assert not kernel.call(f, "page", src={"sql": "SELECT * FROM t"})["ok"]
    r = kernel.call(f, "page", src={"path": "data/r.csv"}, limit=2, offset=2)
    assert r["ok"] and r["total"] == 4 and len(r["rows"]) == 2
    assert not kernel.call(f, "page", src={"path": "../secret.csv"})["ok"]
    assert "error" in kernel.call(f, "page")                            # a bad request: an answer
    # A crash: the next call starts a new kernel.
    pid = kernel.info(f)["pid"]
    with pytest.raises(kernel.KernelError, match="stopped"):
        kernel.call(f, "exec", code="import os; os._exit(1)")
    assert kernel.call(f, "exec", code="1")["value"] == "1" and kernel.info(f)["pid"] != pid
    # Over its time limit: stopped, and said so.
    with pytest.raises(kernel.KernelError, match="ran over"):
        kernel.call(f, "exec", code="import time; time.sleep(30)", timeout=1)
    assert kernel.call(f, "exec", code="'x' in dir()")["value"] == "False"
    kernel.stop(f)
    assert not kernel.alive(f) and kernel.info(f) is None


def test_kernel_idles_out(folder):
    f = str(folder)
    kernel.ensure(f, idle_s=0.5)
    pid = kernel.info(f)["pid"]
    import time
    end = time.time() + 15
    while time.time() < end and kernel.alive(f):
        time.sleep(0.2)
    assert not kernel.alive(f)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def test_cli_round_trip(tmp_path, fake, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd
    e, pkt = _new("a")
    e = registry.get("a")
    root = layout.packet_folder(e["path"])
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    with open(os.path.join(root, "data", "r.csv"), "w") as fp:
        fp.write(CSV)

    def wpk(*a, cwd=root, stdin=None):
        return subprocess.run([sys.executable, "-m", "work_packet", "studio", *a], cwd=cwd,
                              capture_output=True, text=True, input=stdin)
    r = wpk("query", "SELECT 1", cwd=str(tmp_path))
    assert r.returncode != 0 and "open studio's folder" in r.stderr
    model.open_studio(e, pkt.wpid, "matt")
    try:
        r = wpk("query", "SELECT test, sum(fails) AS n FROM 'data/r.csv' GROUP BY 1 ORDER BY 2 DESC")
        assert r.returncode == 0, r.stderr
        assert r.stdout.split("\n")[0].split() == ["test", "|", "n"] and "uart | 8" in r.stdout
        r = wpk("exec", "rows = sql(\"SELECT * FROM 'data/r.csv'\").fetchall()\nlen(rows)")
        assert r.returncode == 0 and r.stdout.strip() == "4", r.stderr
        assert wpk("exec", "-", stdin="print(len(rows))").stdout.strip() == "4"
        r = wpk("exec", "1/0")
        assert r.returncode == 1 and "ZeroDivisionError" in r.stderr
        r = wpk("query", "--out", "data/top.csv", "SELECT * FROM 'data/r.csv' WHERE fails > 2")
        assert r.returncode == 0 and "wrote 2 rows" in r.stdout, r.stderr
        assert open(os.path.join(root, "data", "top.csv")).read().startswith("week,test,fails")
        r = wpk("query", "SELECT * FROM nope")
        assert r.returncode != 0 and "nope" in r.stderr
        r = wpk("status")                               # the studio of this folder
        assert r.returncode == 0 and "open:    yes, by matt" in r.stdout, r.stderr
        r = wpk("datasets")
        assert r.returncode == 0 and "data/r.csv (4 rows)" in r.stdout and "history.steps" in r.stdout
        assert "fails BIGINT" in r.stdout
    finally:
        model.close_studio(e, pkt.wpid, "matt")
    assert not kernel.alive(root)                        # closing stops the kernel


def test_a_stale_kernel_is_replaced(folder, tmp_path):
    """A folder removed and made again at the same path (same socket name): the
    old kernel, whose cwd is gone, is replaced, not used (seen in the S2 exit
    check). And exec's chdir does not move the viewers' folder."""
    f = str(folder)
    assert kernel.call(f, "exec", code="import os; os.chdir('data'); 1")["ok"]
    assert kernel.call(f, "page", src={"path": "data/r.csv"})["ok"]     # back in the folder
    old = kernel.info(f)["pid"]
    os.rename(f, str(tmp_path / "gone"))
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "r.csv").write_text(CSV)
    assert not kernel.alive(f)
    r = kernel.call(f, "page", src={"path": "data/r.csv"})
    assert r["ok"] and r["total"] == 4 and kernel.info(f)["pid"] != old
