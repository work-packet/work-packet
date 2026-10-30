"""Steps recorded from outside the executor (docs/studio-plan.md P0.2): a studio
session is one step with ``worker: studio`` that every reader takes in its stride."""

import json
import os

import pytest

from test_dash_tasks import _client, _new
from work_packet import executor, history, notes, stats
from work_packet.check import check


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _state(pkt):
    return pkt.load_status()


def _record(pkt, tmp_path, **kw):
    tr = tmp_path / "transcript.jsonl"
    tr.write_text(json.dumps({"type": "result", "total_cost_usd": 0.25}) + "\n")
    meta = {"cost_usd": 0.25, "duration_s": 600.0, "start": "2026-10-30T10:00:00Z",
            "end": "2026-10-30T10:10:00Z", "tokens": {"output_tokens": 100}}
    return executor.record_step(pkt, "studio", "Drew a chart of flaky tests.", meta=meta,
                                files={"transcript.jsonl": str(tr)}, **kw)


def test_a_recorded_step(tmp_path, fake):
    e, pkt = _new("a")
    assert executor.step(pkt.path).code == 0
    executor.take(pkt, by="matt")
    before, _ = _state(pkt)
    memento = open(pkt.memento_path).read()
    out, n = _record(pkt, tmp_path)
    assert out.code == 0 and n == 2
    meta, body = _state(pkt)
    # The step moved on; nothing else did.
    assert meta["step"] == 2 and meta["attempts"] == 0
    for k in ("state", "reason", "resume_expr", "model", "taken_by"):
        assert meta.get(k) == before.get(k), k
    assert body.strip() == "Drew a chart of flaky tests."
    assert open(pkt.memento_path).read() == memento
    sd = pkt.step_dir(2)
    m = json.load(open(os.path.join(sd, "meta.json")))
    assert m["worker"] == "studio" and m["step"] == 2 and m["attempt"] == 1
    assert m["cost_usd"] == 0.25
    assert os.path.isfile(os.path.join(sd, "transcript.jsonl"))
    assert open(os.path.join(sd, "result.md")).read() == memento
    types = [r["type"] for r in pkt.journal().records][-3:]
    assert types == ["step-start", "commit-begin", "commit-end"]
    end = pkt.journal().records[-1]
    assert end["cost_usd"] == 0.25 and end["duration_s"] == 600.0
    assert check(pkt.path).errors == []


def test_readers_see_it(tmp_path, fake):
    e, pkt = _new("a")
    assert executor.step(pkt.path).code == 0
    executor.take(pkt, by="matt")
    _record(pkt, tmp_path)
    # Stats: a worker, and the cost counts.
    ss = stats.packet_steps("a", pkt)
    assert [s.worker for s in ss] == ["agent", "studio"] and ss[-1].cost == 0.25
    assert {k for k, _, _ in stats.rollup(ss, "worker")} == {"agent", "studio"}
    # The dash: the Steps tab, the step page and the cost total.
    c = _client()
    html = c.get("/p/a/" + pkt.wpid).text
    assert '<span class="badge" title="done by a person in the studio' in html
    assert c.get("/p/a/%s/0002" % pkt.wpid).status_code == 200
    from work_packet.dash import data
    from work_packet import registry
    row = data.tree(registry.get("a"))[0]
    assert row["steps"][-1]["worker"] == "studio" and row["cost_usd"] >= 0.25
    # history.db.
    history.sync("a", os.path.dirname(os.path.dirname(pkt.path)))
    con = history.connect()
    try:
        got = con.execute("SELECT step, cost, stats FROM step WHERE packet = ? ORDER BY step",
                          (pkt.wpid,)).fetchall()
    finally:
        con.close()
    assert [g[0] for g in got] == [1, 2] and got[1][1] == 0.25
    assert json.loads(got[1][2])["worker"] == "studio"


def test_notes_it_dealt_with_are_consumed(tmp_path, fake):
    e, pkt = _new("a")
    executor.take(pkt, by="matt")
    a = notes.add(pkt, "use a log scale", by="matt")
    b = notes.add(pkt, "later: a table too", by="matt")
    _record(pkt, tmp_path, notes_seen=[a["id"]])
    assert [x["id"] for x in notes.queued(pkt)] == [b["id"]]
    begin = [r for r in pkt.journal().records if r["type"] == "commit-begin"][-1]
    assert [x["id"] for x in begin["decision"]["notes"]] == [a["id"]]


def test_a_crash_mid_commit_rolls_forward(tmp_path, fake, monkeypatch):
    e, pkt = _new("a")
    executor.take(pkt, by="matt")

    class Crash(Exception):
        pass

    def point(name):
        if name == "after-commit-begin":
            raise Crash()
    monkeypatch.setattr(executor.faults, "point", point)
    with pytest.raises(Crash):
        _record(pkt, tmp_path)
    monkeypatch.undo()
    assert _state(pkt)[0]["step"] == 0
    out = executor.recover(pkt.path)
    assert out.code == 0 and "rolled forward the commit of step 1" in out.msg
    meta, body = _state(pkt)
    assert meta["step"] == 1 and meta["taken_by"] == "matt" and meta["state"] == "PAUSED"
    assert body.strip() == "Drew a chart of flaky tests."
    assert check(pkt.path).errors == []


def test_refused_while_a_step_runs(tmp_path, fake):
    from work_packet.lease import Lease
    e, pkt = _new("a")
    lease = Lease(pkt.lease_path, 1, 1, 60).acquire()
    try:
        out, n = _record(pkt, tmp_path)
        assert out.code == executor.LEASED and n is None
    finally:
        lease.release()
