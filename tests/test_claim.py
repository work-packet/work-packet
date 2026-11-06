"""Opening a project in VS Code claims it (docs/collaboration.md §5.1): the runner
leaves every packet of it, however long the editor stays open or closed, until you
hand it back."""

import json
import os
import socket

import pytest

from test_dash_tasks import _new
from work_packet import actions, cli, executor, scheduler
from work_packet.dash import data
from work_packet.packet import Packet


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def test_a_claim_lasts_until_you_hand_it_back(fake):
    e, pkt = _new("a")
    out = actions.claim(e, "me")
    assert out.code == 0 and "yours until you hand it back" in out.msg
    meta = pkt.load_status()[0]
    assert meta["reason"] == "claimed"
    card = data.card(e)
    assert card["column"] == "Working: you" and card["driver"] == "you"
    assert card["ball"]["kind"] == "claimed"
    scheduler.tick([e], until_idle=True)              # no presence at all: still yours
    assert pkt.load_status()[0]["step"] == 0
    assert executor.admin(pkt, "handoff", note="over to you").code == 0
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["step"] > 0


def test_a_running_step_finishes_first(fake):
    e, pkt = _new("a")
    with open(pkt.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 1,
                   "attempt": 1, "expires": "2999-01-01T00:00:00Z"}, fp)
    out = actions.claim(e, "me")
    assert out.code == 0 and executor.pause_request(pkt)["reason"] == "claimed"
    assert pkt.load_status()[0]["state"] == "RUNNABLE"


def test_handing_back_the_root_hands_back_the_rest(fake):
    e, root = _new("a")
    for _ in range(8):                                # add_one: counts to 8, spawns hello
        executor.step(root.path)
    [kid] = [Packet(os.path.join(os.path.dirname(root.path), w))
             for w in root.load_status()[0]["children"]]
    assert kid.load_status()[0]["state"] == "RUNNABLE"
    actions.claim(e, "me")
    assert kid.load_status()[0]["reason"] == "claimed"
    assert root.load_status()[0]["state"] == "COMPLETED"   # the root had finished
    out = executor.admin(root, "continue", instruction="Say hello again.", force=True)
    assert out.code == 0 and "1 more packet you had claimed" in out.msg
    assert kid.load_status()[0]["state"] == "RUNNABLE"
    actions.claim(e, "me")                            # and Resume on the project
    assert actions.resume_project(e, "me").code == 0
    assert kid.load_status()[0]["state"] == "RUNNABLE"


def test_resume_on_the_project_is_a_hand_back_too(fake):
    e, pkt = _new("a")
    actions.claim(e, "me")
    assert actions.resume_project(e, "me").code == 0
    assert pkt.load_status()[0]["state"] == "RUNNABLE"


def test_wpk_ide_claims_unless_look(fake, capsys, monkeypatch):
    from work_packet import ide
    e, pkt = _new("a")
    monkeypatch.setattr(ide, "resolve", lambda *a, **k: (_ for _ in ()).throw(
        ide.IdeError("stop here")))
    cli.main(["ide", "a", "--look"])
    assert pkt.load_status()[0]["state"] == "RUNNABLE"
    cli.main(["ide", "a"])
    assert pkt.load_status()[0]["reason"] == "claimed"
    assert "yours until you hand it back" in capsys.readouterr().err
