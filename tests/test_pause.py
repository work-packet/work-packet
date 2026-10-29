"""Pausing to re-prioritise (docs/pause-v1.md): a pause that works on a packet
whose step is running, a whole project, and the board's controls."""

import pytest

from test_dash_tasks import _client, _flash, _new
from work_packet import actions, executor
from work_packet.lease import Lease


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _state(pkt):
    return pkt.load_status()[0]


def test_pause_while_a_step_runs_is_a_request(tmp_path, fake):
    e, pkt = _new("a")
    lease = Lease(pkt.lease_path, 1, 1, 60).acquire()        # as a running step holds it
    try:
        out = executor.admin(pkt, "pause", by="me")
        assert out.code == 0 and "pause requested" in out.msg
        assert executor.pause_request(pkt)["by"] == "me" and _state(pkt)["state"] == "RUNNABLE"
        assert executor.admin(pkt, "pause", by="you").code == 0       # asking twice keeps the first
        assert executor.pause_request(pkt)["by"] == "me"
        assert executor.admin(pkt, "resume").code == executor.LEASED  # only pause becomes a request
    finally:
        lease.release()
    # The next step pauses it instead of running.
    out = executor.step(pkt.path)
    assert out.code == executor.NOT_RUNNABLE and "paused" in out.msg
    meta = _state(pkt)
    assert meta["state"] == "PAUSED" and meta["step"] == 0 and meta["reason"].startswith("paused by me")
    assert executor.pause_request(pkt) is None
    rec = [r for r in pkt.journal().records if r.get("type") == "admin"][-1]
    assert rec["op"] == "pause" and rec["by"] == "me" and rec["requested"]


def test_the_commit_honours_a_request(tmp_path, fake, monkeypatch):
    e, pkt = _new("a")
    # Asked for while step 1 runs (faults.at_step runs inside the step, under its lease).
    monkeypatch.setattr(executor.faults, "at_step",
                        lambda n: executor.request_pause(pkt, by="me") if n == 1 else None)
    assert executor.step(pkt.path).code == 0
    meta = _state(pkt)
    assert meta["step"] == 1 and meta["state"] == "PAUSED"
    assert meta["reason"] == "paused by me after step 1"
    assert executor.pause_request(pkt) is None
    kinds = [r["type"] for r in pkt.journal().records]
    assert kinds[-3:] == ["commit-begin", "admin", "commit-end"]


def test_a_request_is_dropped_when_the_step_finishes_the_packet(tmp_path, fake, monkeypatch):
    from work_packet import scheduler
    e, pkt = _new("a")
    monkeypatch.setattr(executor.faults, "at_step",
                        lambda n: executor.request_pause(pkt, by="me") if n == 8 else None)
    scheduler.tick([e], until_idle=True)
    assert _state(pkt)["state"] == "COMPLETED" and executor.pause_request(pkt) is None


def test_withdraw(tmp_path, fake):
    e, pkt = _new("a")
    executor.request_pause(pkt, by="me")
    assert executor.withdraw_pause(pkt).code == 0 and executor.pause_request(pkt) is None
    assert executor.withdraw_pause(pkt).code == executor.NOT_RUNNABLE


def test_the_dispatcher_pauses_instead_of_starting(tmp_path, fake):
    from work_packet import scheduler
    e, pkt = _new("a")
    executor.request_pause(pkt, by="me")
    scheduler.tick([e])
    meta = _state(pkt)
    assert meta["state"] == "PAUSED" and meta["step"] == 0
    assert meta["reason"] == "paused by me" and executor.pause_request(pkt) is None


def test_project_pause_and_resume(tmp_path, fake):
    e, pkt = _new("a")
    out = actions.pause_project(e, by="me")
    assert out.code == 0 and out.msg == "a: paused 1 packet"
    assert _state(pkt)["state"] == "PAUSED"
    assert actions.pause_project(e).code == executor.NOT_RUNNABLE
    out = actions.resume_project(e, by="me")
    assert out.code == 0 and "resumed 1 packet" in out.msg and _state(pkt)["state"] == "RUNNABLE"

    # A running step: after it.
    lease = Lease(pkt.lease_path, 1, 1, 60).acquire()
    try:
        out = actions.pause_project(e, by="me")
        assert out.msg == "a: 1 after the running step"
        out = actions.resume_project(e, by="me")       # taken back before it happened
        assert "will not pause after all" in out.msg and executor.pause_request(pkt) is None
    finally:
        lease.release()

    # Resume leaves alone what was not paused by hand: setup, a limit.
    e2, held = _new("b")
    executor.admin(held, "pause", by="wpkd", reason="over the day's cap", stopped=True)
    assert actions.resume_project(e2).code == executor.NOT_RUNNABLE
    assert _state(held)["state"] == "PAUSED"


def test_stop_now_ends_the_projects_steps(tmp_path, fake, monkeypatch):
    from work_packet.sched import control
    e, pkt = _new("a")
    seen = {}

    class R:
        def __init__(self, project, kind):
            self.project, self.kind = project, kind

    def cancel(which, by, why, h=None, backend=None, lost=True):
        seen["picks"] = [which(R("a", "step")), which(R("b", "step")), which(R("a", "ide"))]
        seen["lost"] = lost
        return [R("a", "step")]
    monkeypatch.setattr(control, "cancel_jobs", cancel)
    lease = Lease(pkt.lease_path, 1, 1, 60).acquire()
    try:
        out = actions.stop_project(e, by="me")
    finally:
        lease.release()
    assert seen == {"picks": [True, False, False], "lost": True}
    assert "ended 1 running step" in out.msg and executor.pause_request(pkt) is not None


def test_board_controls(tmp_path, fake):
    e, pkt = _new("a")
    c = _client()
    html = c.get("/").text
    assert 'action="/p/a/run"' in html and 'value="pause"' in html     # Coming up
    html = c.get("/p/a").text
    assert 'action="/p/a/run"' in html and ">Pause<" in html and "Stop now" not in html
    r = c.post("/p/a/run", data={"op": "pause", "back": "/#running"}, follow_redirects=False)
    assert _flash(r) == ("a: paused 1 packet", True)
    assert r.headers["location"].startswith("/?") and r.headers["location"].endswith("#running")
    assert _state(pkt)["state"] == "PAUSED"
    html = c.get("/p/a").text
    assert ">Resume<" in html and ">Pause<" not in html
    r = c.post("/p/a/run", data={"op": "resume", "back": "//evil"}, follow_redirects=False)
    assert _flash(r)[1] and r.headers["location"].startswith("/p/a?")
    assert _state(pkt)["state"] == "RUNNABLE"

    # A pause waiting on a running step shows, and can be taken back.
    executor.request_pause(pkt, by="me")
    html = c.get("/p/a").text
    assert "PAUSING" in html and ("Don&#39;t pause" in html or "Don't pause" in html)
    assert "PAUSING" in c.get("/p/a/" + pkt.wpid).text
    r = c.post("/p/a/%s/act" % pkt.wpid, data={"action": "keep"}, follow_redirects=False)
    assert _flash(r)[1] and executor.pause_request(pkt) is None
    assert c.get("/b/main").status_code == 200 and 'action="/p/a/run"' in c.get("/b/main").text
