"""Take and release (docs/studio-plan.md P0.1): the studio takes a packet so the
runner leaves it alone; v1 is PAUSED with reason ``studio`` and ``taken_by``."""

import subprocess
import sys

import pytest

from test_dash_tasks import _client, _new
from work_packet import actions, executor, schema
from work_packet.lease import Lease
from work_packet.packet import Packet


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _state(pkt):
    return pkt.load_status()[0]


def _ops(pkt):
    return [r["op"] for r in pkt.journal().records if r.get("type") == "admin"]


def test_idle_take_and_release(tmp_path, fake):
    e, pkt = _new("a")
    out = executor.take(pkt, by="matt")
    assert out.code == 0 and "taken by matt" in out.msg
    meta = _state(pkt)
    assert meta["state"] == "PAUSED" and meta["reason"] == "studio"
    assert meta["taken_by"] == "matt" and meta["taken"]
    assert not schema.validate_status(meta)
    assert executor.take(pkt, by="matt").code == 0                  # again: a no-op
    assert executor.take(pkt, by="sam").code == executor.NOT_RUNNABLE
    assert executor.release(pkt, by="sam").code == executor.NOT_RUNNABLE
    out = executor.release(pkt, by="matt")
    assert out.code == 0 and "PAUSED -> RUNNABLE" in out.msg
    meta = _state(pkt)
    assert meta["state"] == "RUNNABLE" and meta["reason"] is None and "taken_by" not in meta
    assert _ops(pkt) == ["take", "release"]
    assert executor.release(pkt, by="matt").code == executor.NOT_RUNNABLE


def test_release_hold_and_force(tmp_path, fake):
    e, pkt = _new("a")
    executor.take(pkt, by="matt")
    assert executor.release(pkt, how="hold", by="sam", force=True).code == 0
    meta = _state(pkt)
    assert meta["state"] == "PAUSED" and meta["reason"] == "held" and "taken_by" not in meta
    assert actions.resumable(meta)          # a held packet resumes like one paused by hand


def test_a_finished_packet_keeps_its_state(tmp_path, fake):
    from work_packet import scheduler
    e, pkt = _new("a")
    scheduler.tick([e], until_idle=True)
    assert _state(pkt)["state"] == "COMPLETED"
    assert executor.take(pkt, by="matt").code == 0
    assert _state(pkt)["state"] == "COMPLETED" and _state(pkt)["taken_by"] == "matt"
    assert executor.release(pkt, by="matt").code == 0
    assert _state(pkt)["state"] == "COMPLETED" and "taken_by" not in _state(pkt)


def test_take_while_running_lands_at_the_commit(tmp_path, fake, monkeypatch):
    e, pkt = _new("a")
    got = {}

    def at_step(n):                     # inside step 1, under its lease
        if n == 1:
            got["take"] = executor.take(pkt, by="matt")
            got["other"] = executor.take(pkt, by="sam")
            got["taking"] = executor.taking(pkt)
            got["state"] = _state(pkt)["state"]
    monkeypatch.setattr(executor.faults, "at_step", at_step)
    assert executor.step(pkt.path).code == 0
    assert got["take"].code == 0 and "after the running step" in got["take"].msg
    assert got["other"].code == executor.NOT_RUNNABLE and got["taking"] == "matt"
    assert got["state"] == "RUNNABLE"
    meta = _state(pkt)
    assert meta["step"] == 1 and meta["state"] == "PAUSED" and meta["reason"] == "studio"
    assert meta["taken_by"] == "matt" and executor.pause_request(pkt) is None
    kinds = [r["type"] for r in pkt.journal().records]
    assert kinds[-3:] == ["commit-begin", "admin", "commit-end"]
    assert _ops(pkt) == ["take"]


def test_take_lands_even_when_the_step_finishes_the_packet(tmp_path, fake, monkeypatch):
    e, pkt = _new("a")
    for _ in range(7):                  # the fake finishes at step 8
        assert executor.step(pkt.path).code == 0
    monkeypatch.setattr(executor.faults, "at_step",
                        lambda n: executor.take(pkt, by="matt") if n == 8 else None)
    assert executor.step(pkt.path).code == 0
    meta = _state(pkt)
    assert meta["state"] == "COMPLETED" and meta["taken_by"] == "matt"


def test_a_take_left_by_a_failed_attempt_lands_at_the_next_start(tmp_path, fake):
    e, pkt = _new("a")
    lease = Lease(pkt.lease_path, 1, 1, 60).acquire()
    try:
        assert "after the running step" in executor.take(pkt, by="matt").msg
    finally:
        lease.release()
    assert executor.release(pkt, by="sam").code == executor.NOT_RUNNABLE   # not sam's
    out = executor.step(pkt.path)
    assert out.code == executor.NOT_RUNNABLE
    meta = _state(pkt)
    assert meta["state"] == "PAUSED" and meta["taken_by"] == "matt" and meta["step"] == 0


def test_release_withdraws_a_take_not_yet_landed(tmp_path, fake):
    e, pkt = _new("a")
    lease = Lease(pkt.lease_path, 1, 1, 60).acquire()
    try:
        executor.take(pkt, by="matt")
        out = executor.release(pkt, by="matt")
        assert out.code == 0 and "after all" in out.msg and executor.taking(pkt) is None
    finally:
        lease.release()


def test_the_runner_leaves_a_taken_packet_alone(tmp_path, fake):
    from work_packet import scheduler
    e, pkt = _new("a")
    executor.take(pkt, by="matt")
    scheduler.tick([e], until_idle=True)
    assert _state(pkt)["step"] == 0
    # Nor do the other ways of handing it back.
    for op in ("resume", "handoff", "continue"):
        out = executor.admin(pkt, op, instruction="x")
        assert out.code == executor.NOT_RUNNABLE and "taken by matt" in out.msg
    assert "nothing paused by hand" in actions.resume_project(e).msg
    assert executor.step(pkt.path).code == executor.NOT_RUNNABLE


def test_the_dispatcher_lands_a_pending_take(tmp_path, fake):
    from work_packet import scheduler
    e, pkt = _new("a")
    lease = Lease(pkt.lease_path, 1, 1, 60).acquire()
    try:
        executor.take(pkt, by="matt")
    finally:
        lease.release()
    scheduler.tick([e])
    meta = _state(pkt)
    assert meta["state"] == "PAUSED" and meta["reason"] == "studio"
    assert meta["taken_by"] == "matt" and meta["step"] == 0


def test_release_after_a_restart(tmp_path, fake):
    e, pkt = _new("a")
    executor.take(pkt, by="matt")
    again = Packet(pkt.path)             # nothing kept in memory: it is all in files
    assert executor.release(again, by="matt").code == 0
    assert _state(again)["state"] == "RUNNABLE"


def test_cli(tmp_path, fake):
    e, pkt = _new("a")

    def wpk(*a):
        return subprocess.run([sys.executable, "-m", "work_packet", *a],
                              capture_output=True, text=True)
    r = wpk("take", pkt.wpid)
    assert r.returncode == 0 and "taken by" in r.stderr
    assert _state(pkt)["reason"] == "studio"
    r = wpk("release", "--hold", pkt.wpid)
    assert r.returncode == 0 and _state(pkt)["reason"] == "held"


def test_the_dash_shows_it(tmp_path, fake):
    e, pkt = _new("a")
    executor.take(pkt, by="matt")
    c = _client()
    html = c.get("/p/a/" + pkt.wpid).text
    assert "IN STUDIO" in html and "In studio (matt)" in html
    assert "Hand off to the runner" not in html
    assert "IN STUDIO" in c.get("/b/main").text and "(matt)" in c.get("/b/main").text
    executor.release(pkt, by="matt")
    assert "IN STUDIO" not in c.get("/p/a/" + pkt.wpid).text
