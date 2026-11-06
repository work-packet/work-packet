"""Done, drop, reopen and autonomy (docs/collaboration.md §4.1, §4.4): a person's
facts about a packet, with the runner leaving what is closed."""

import json
import os
import socket

import pytest

from test_dash_tasks import _new
from work_packet import checkpoint, cli, executor, migrate, project, scheduler, views
from work_packet.packet import Packet


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _hold_lease(pkt):
    with open(pkt.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 1,
                   "attempt": 1, "expires": "2999-01-01T00:00:00Z"}, fp)


def test_new_packets_carry_the_persons_facts(fake):
    _, pkt = _new("a")
    meta, _ = pkt.load_status()
    assert meta["lifecycle"] == "open" and meta["autonomy"] == "handoff"
    assert meta["owner"]
    plan = project.new("b", None)                       # no instruction: yours to start
    meta, _ = Packet(os.path.join(plan.path, "packets", plan.root)).load_status()
    assert meta["autonomy"] == "manual" and meta["state"] == "PAUSED"


def test_done_parks_what_the_runner_has(fake):
    e, pkt = _new("a")                                  # RUNNABLE: queued for the runner
    out = executor.mark(pkt, "done", by="me", note="not needed after all")
    assert out.code == 0
    meta, _ = pkt.load_status()
    assert meta["lifecycle"] == "done" and meta["state"] == "PAUSED"
    assert meta["reason"] == "done"
    assert views.column(meta) == "Done"
    rec = pkt.journal().records[-1]
    assert rec == dict(rec, type="admin", op="done", by="me", to="PAUSED",
                       note="not needed after all")
    assert scheduler.due([e]) == []
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["step"] == 0            # the runner left it
    assert executor.mark(pkt, "done").msg.endswith("already done")


def test_done_keeps_a_finished_state(fake):
    e, pkt = _new("a")
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["state"] == "COMPLETED"
    assert executor.mark(pkt, "done").code == 0
    meta, _ = pkt.load_status()
    assert meta["state"] == "COMPLETED" and meta["lifecycle"] == "done"


def test_reopen_and_drop(fake):
    _, pkt = _new("a")
    assert executor.mark(pkt, "drop").code == 0
    assert views.lifecycle(pkt.load_status()[0]) == "dropped"
    assert executor.mark(pkt, "reopen").code == 0
    meta, _ = pkt.load_status()
    assert meta["lifecycle"] == "open" and meta["state"] == "PAUSED"   # parked, not handed
    assert views.column(meta) == "Parked"
    assert executor.mark(pkt, "reopen").msg.endswith("is open")


def test_a_hand_off_reopens(fake):
    _, pkt = _new("a")
    executor.mark(pkt, "done")
    assert executor.admin(pkt, "handoff", note="one more thing").code == 0
    meta, _ = pkt.load_status()
    assert meta["lifecycle"] == "open" and meta["state"] == "RUNNABLE"
    assert pkt.journal().records[-1]["reopened"] == "done"


def test_a_running_step_refuses(fake):
    _, pkt = _new("a")
    _hold_lease(pkt)
    out = executor.mark(pkt, "done")
    assert out.code == executor.LEASED and "step running" in out.msg
    assert pkt.load_status()[0]["lifecycle"] == "open"


def test_autonomy(fake):
    _, pkt = _new("a")
    assert executor.mark(pkt, "autonomy", autonomy="runner").code == 0
    meta, _ = pkt.load_status()
    assert meta["autonomy"] == "runner" and meta["review"] == "each"
    assert executor.mark(pkt, "autonomy", autonomy="runner", review="never").code == 0
    assert pkt.load_status()[0]["review"] == "never"
    assert executor.mark(pkt, "autonomy", autonomy="manual").code == 0
    meta, _ = pkt.load_status()
    assert meta["autonomy"] == "manual" and "review" not in meta
    assert executor.mark(pkt, "autonomy", autonomy="auto").code == executor.USAGE
    assert executor.mark(pkt, "autonomy", autonomy="runner", review="x").code == executor.USAGE
    rec = pkt.journal().records[-1]
    assert rec["op"] == "autonomy" and rec["autonomy"] == "manual"


def test_cli(fake, capsys):
    _, pkt = _new("a")
    assert cli.main(["done", "a", "-m", "shipped"]) == 0
    assert views.lifecycle(pkt.load_status()[0]) == "done"
    assert cli.main(["reopen", "a"]) == 0
    assert cli.main(["autonomy", "runner", "a", "--review", "failure"]) == 0
    meta, _ = pkt.load_status()
    assert meta["autonomy"] == "runner" and meta["review"] == "failure"
    assert cli.main(["drop", "nope-not-here"]) != 0


def test_thread_credits_who_did_it(fake):
    e, pkt = _new("a")
    scheduler.tick([e], until_idle=True)
    executor.admin(pkt, "continue", instruction="More.", force=True)
    executor.admin(pkt, "pause")
    checkpoint.record(pkt, "parser half done", next_action="write tests", by="alice@host")
    executor.mark(pkt, "done", by="bob@host", note="good enough")
    es, _, _ = migrate.rebuild_thread(pkt.path, "a")
    notes = [(x.kind, x.who, x.body.split("\n")[0]) for x in es if x.kind == "note"]
    assert ("note", "alice (VS Code)", "parser half done") in notes
    assert ("note", "bob", "Marked done.") in notes
    accepted = [x for x in es if x.kind == "accepted"]
    assert all(x.who == migrate.RUNNER for x in accepted)
