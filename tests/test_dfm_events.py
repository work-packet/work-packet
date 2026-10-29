"""DFM runs on the board (docs/dfm-events.md): the collector, the fold, the pages."""

import asyncio
import json
import os
import socket

import pytest

from work_packet.dash import dfmrun, events

SID = "01JB8Z3K9V6Q2T4X7M5N0P1R2S"
T0 = 1761400000.0


def _ev(seq, ev, t=None, sid=SID, **kw):
    return dict(v=1, src="dfm", sid=sid, seq=seq, t=T0 + (seq if t is None else t), ev=ev, **kw)


def _plan(end=True, sid=SID):
    """build -> {t1, t2} -> report; t1 fails, so report is skipped; t2 is still running."""
    nodes = [
        {"id": "top", "name": "top", "kind": "compound", "parent": None, "needs": []},
        {"id": "top.build", "name": "top.build", "kind": "leaf", "parent": "top", "needs": []},
        {"id": "top.t1", "name": "top.t1", "kind": "leaf", "parent": "top",
         "needs": [{"id": "top.build", "block": False}]},
        {"id": "top.t2", "name": "top.t2", "kind": "leaf", "parent": "top",
         "needs": [{"id": "top.build", "block": False}]},
        {"id": "top.lint", "name": "top.lint", "kind": "leaf", "parent": "top", "needs": []},
        {"id": "top.report", "name": "top.report", "kind": "leaf", "parent": "top",
         "needs": [{"id": "top.t1", "block": False}, {"id": "top.t2", "block": False}]},
    ]
    lines = [
        _ev(0, "run.start", sid=sid, host="h", pid=42, cwd="/w", argv=["dfm", "run", "top"],
            rundir="/w/rundir", roots=["top"], jobs=4, dfm_run_id="0001",
            ctx={"WPK_WPID": "01JB0000000000000000000000", "WPK_STEP": "3", "WPK_ATTEMPT": "1"}),
        _ev(1, "graph.plan", sid=sid, nodes=nodes),
        _ev(2, "task.state", sid=sid, id="top.build", state="enter"),
        _ev(3, "task.state", sid=sid, id="top.build", state="run"),
        _ev(4, "task.exec", sid=sid, id="top.build", phase="start", cmd=["make", "-j4"]),
        _ev(5, "task.state", sid=sid, id="top.build", state="done", status=0, changed=True, dur=2.5),
        _ev(6, "task.state", sid=sid, id="top.lint", state="done", status=0, changed=False),
        _ev(7, "task.state", sid=sid, id="top.t1", state="enter"),
        _ev(8, "task.state", sid=sid, id="top.t2", state="enter"),
        _ev(9, "task.exec", sid=sid, id="top.t2", phase="start", cmd=["vcs", "-R"]),
        _ev(10, "task.marker", sid=sid, id="top.t1", severity="error", msg="assert failed",
            loc={"path": "t1.sv", "line": 7, "pos": 0}),
        _ev(11, "task.state", sid=sid, id="top.t1", state="done", status=1, changed=True, dur=1.0),
    ]
    if end:
        lines += [
            _ev(12, "task.state", sid=sid, id="top.t2", state="done", status=0, changed=True),
            _ev(13, "task.state", sid=sid, id="top.report", state="skipped"),
            _ev(14, "run.end", sid=sid, status=1, result="fail",
                counts={"ok": 2, "uptodate": 1, "failed": 1, "skipped": 1}, dropped=0),
        ]
    return lines


def test_fold_lists_running_pending_and_done():
    v = dfmrun.view(dfmrun.fold(_plan(end=False)), now=T0 + 12)
    assert v["status"] == "running" and v["live"]
    assert v["title"] == "run top" and v["wpid"].startswith("01JB0") and v["step"] == "3"
    assert v["total"] == 5                                   # leaves only, not the compound
    assert [n["id"] for n in v["running"]] == ["top.t2"]
    assert v["running"][0]["cmd"] == "vcs -R" and v["running"][0]["for_s"] == 4
    assert [n["id"] for n in v["failed"]] == ["top.t1"]
    assert v["failed"][0]["errors"] == 1 and v["failed"][0]["markers"][0]["loc"]["line"] == 7
    assert [n["id"] for n in v["done"]] == ["top.build"] and v["done"][0]["cmd"] is None
    assert [n["id"] for n in v["quiet"]] == ["top.lint"]
    (rep,) = v["pending"]
    assert rep["id"] == "top.report" and rep["waiting"] == "top.t2" and rep["n_waiting"] == 1
    assert v["finished"] == 3 and v["pct"] == 60


def test_fold_finished_run():
    v = dfmrun.view(dfmrun.fold(_plan()), now=T0 + 1000)
    assert v["status"] == "fail" and not v["live"]
    assert not v["running"] and not v["pending"]
    assert [n["id"] for n in v["skipped"]] == ["top.report"]
    assert v["finished"] == v["total"] == 5 and v["elapsed"] == 14
    assert v["counts"]["failed"] == 1


def test_lost_runs_partial_streams_and_gaps():
    lines = _plan(end=False)
    # silence for three heartbeats, then a connection that closed without run.end
    assert dfmrun.view(dfmrun.fold(lines), now=T0 + 11 + 29, hb=10)["status"] == "running"
    assert dfmrun.view(dfmrun.fold(lines), now=T0 + 11 + 31, hb=10)["status"] == "lost"
    assert dfmrun.view(dfmrun.fold(lines), now=T0 + 10 ** 6, hb=0)["status"] == "running"
    closed = lines + [dict(v=1, src="wpk", sid=SID, t=T0 + 12, ev="conn.close", why="eof")]
    v = dfmrun.view(dfmrun.fold(closed), now=T0 + 12)
    assert v["status"] == "lost" and v["closed"] == "eof"
    assert v["running"][0]["for_s"] == 4                     # cut off at the last line
    v = dfmrun.view(dfmrun.fold([lines[0]] + lines[3:]), now=T0 + 12)
    assert v["gaps"] == 2 and not v["partial"]
    v = dfmrun.view(dfmrun.fold(lines[2:]), now=T0 + 12)
    assert v["partial"] and v["title"] == "dfm run"


def test_export_env_appends_once_and_unexport_restores():
    env = {"DFM_EVENT_SINK": "unix:/other.sock"}
    events.export_env("/h/events.sock", env)
    events.export_env("/h/events.sock", env)
    assert env == {"DFM_EVENT_SINK": "unix:/other.sock,unix:/h/events.sock",
                   "DFM_EVENT_CTX": "WPK_*"}
    events.unexport_env("/h/events.sock", env)
    assert env == {"DFM_EVENT_SINK": "unix:/other.sock"}


def test_sock_path_falls_back_when_too_long(tmp_path):
    assert events.sock_path(str(tmp_path)) == str(tmp_path / "events" / "events.sock")
    long = str(tmp_path / ("x" * 120))
    p = events.sock_path(long, env={})
    assert len(p) <= events.SUN_PATH_MAX and p.startswith("/tmp/wpk-ev-")


def test_prune_keeps_the_newest(tmp_path):
    d = tmp_path / "runs" / "dfm"
    d.mkdir(parents=True)
    for i in range(5):
        p = d / ("run%05d.jsonl" % i)
        p.write_text("{}\n")
        os.utime(p, (T0 + i, T0 + i))
    assert events.prune(str(tmp_path), keep=3, days=10 ** 6, now=T0 + 10) == 2
    assert sorted(os.listdir(d)) == ["run00002.jsonl", "run00003.jsonl", "run00004.jsonl"]
    assert events.prune(str(tmp_path), keep=10, days=1, now=T0 + 3 * 86400) == 3


def _send(path, lines, raw=b""):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    s.sendall(raw + b"".join(json.dumps(x).encode() + b"\n" for x in lines))
    s.close()


def test_collector_journals_and_marks_a_dropped_connection_lost(tmp_path, monkeypatch):
    home = str(tmp_path / "home")
    monkeypatch.delenv("DFM_EVENT_SINK", raising=False)
    monkeypatch.delenv("DFM_EVENT_CTX", raising=False)

    async def go():
        c = await events.Collector(home).start()
        assert os.environ["DFM_EVENT_SINK"] == "unix:" + c.path
        assert os.environ["DFM_EVENT_CTX"] == "WPK_*"
        assert oct(os.stat(os.path.dirname(c.path)).st_mode & 0o777) == "0o700"
        loop = asyncio.get_running_loop()
        # a finished run, junk lines ignored; then a run whose producer goes away
        await loop.run_in_executor(None, _send, c.path, _plan(),
                                   b"not json\n" + b'{"v":2,"src":"x","sid":"%s"}\n' % SID.encode())
        other = SID[:-1] + "Z"
        await loop.run_in_executor(None, _send, c.path, _plan(end=False, sid=other))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if not c.conns:
                break
        await c.stop()
        assert "DFM_EVENT_SINK" not in os.environ and not os.path.exists(c.path)
        return other

    other = asyncio.run(go())
    done = dfmrun.read(events.journal(home, SID))
    assert done[0]["ev"] == "conn.open" and done[0]["src"] == "wpk"
    assert [x["ev"] for x in done[1:]] == [x["ev"] for x in _plan()]  # no conn.close after run.end
    v = dfmrun.view(dfmrun.load(home, SID))
    assert v["status"] == "fail" and v["peer"] == os.getpid()
    v = dfmrun.view(dfmrun.load(home, other))
    assert v["status"] == "lost" and v["closed"] == "eof"
    assert [r["sid"] for r in dfmrun.runs(home)] == [other, SID] or \
        {r["sid"] for r in dfmrun.runs(home)} == {other, SID}


def test_collector_rejects_a_sid_owned_by_another_peer(tmp_path):
    c = events.Collector(str(tmp_path))
    os.makedirs(events.journal_dir(str(tmp_path)))
    c.owner[SID] = 999999
    conn = events._Conn(c, os.getpid())
    assert conn.take(json.dumps(_plan()[0]).encode())
    assert not os.path.exists(events.journal(str(tmp_path), SID))
    assert events.journal(str(tmp_path), "../etc") is None


@pytest.fixture
def board(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    home = tmp_path / "home"
    monkeypatch.setenv("WPK_HOME", str(home))
    d = home / "runs" / "dfm"
    d.mkdir(parents=True)
    (d / (SID + ".jsonl")).write_text("".join(json.dumps(x) + "\n" for x in _plan()))
    kid = SID[:-1] + "K"
    start = dict(_plan(sid=kid)[0], parent=SID, argv=["dfm", "run", "inner"])
    (d / (kid + ".jsonl")).write_text(json.dumps(start) + "\n")
    rd = tmp_path / "w" / "rundir"
    rd.mkdir(parents=True)
    (rd / "t1.log").write_text("line one\nboom\n")
    (tmp_path / "secret.txt").write_text("no")
    lines = _plan()
    lines[11] = dict(lines[11], rundir=str(rd), log=str(rd / "t1.log"))
    lines[5] = dict(lines[5], rundir=str(rd), log=str(tmp_path / "secret.txt"))
    lines[0] = dict(lines[0], rundir=str(rd))
    (d / (SID + ".jsonl")).write_text("".join(json.dumps(x) + "\n" for x in lines))
    return TestClient(create_app(str(home)))


def test_runs_pages(board):
    r = board.get("/runs")
    assert r.status_code == 200 and "/runs/" + SID in r.text and "run top" in r.text
    assert 'href="/runs"' in r.text                       # the side tab
    r = board.get("/runs/" + SID)
    assert r.status_code == 200
    t = r.text
    assert "Failed (1)" in t and "assert failed" in t and "t1.sv:7" in t
    assert "Skipped (1)" in t and "Done (3)" in t and "1 up to date or cached" in t
    assert "Nested runs (1)" in t and "run inner" in t
    assert 'id="live"' not in t                           # a finished run does not refresh
    r = board.get("/runs/%s/log.txt?id=top.t1" % SID)
    assert r.status_code == 200 and "boom" in r.text
    assert board.get("/runs/%s/log.txt?id=top.build" % SID).status_code == 404   # outside rundir
    assert board.get("/runs/NOSUCHRUN0000").status_code == 404
    assert board.get("/runs/..%2Fetc").status_code == 404
