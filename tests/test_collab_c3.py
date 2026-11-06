"""Starting work your way (docs/collaboration.md W1, W4, §8.3): the start modes on
New, Open ▾ on the cards, and the hand-off (Compose) with what it needs."""

import os
import subprocess

import pytest

from test_dash_tasks import _client, _flash, _new
from test_setup import git, home, source                       # noqa: F401
from work_packet import checkpoint, executor, registry, scheduler
from work_packet.packet import Packet


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _create(c, tmp_path, name, start, objective="", **extra):
    data = dict({"name": name, "dir": str(tmp_path / "pp"), "objective": objective,
                 "start": start}, **extra)
    return c.post("/new", data=data, follow_redirects=False)


def _root(name):
    e = registry.get(name)
    return e, Packet(os.path.join(e["path"], "runs", e["root"]))


def test_new_offers_ways_to_start(fake):
    c = _client()
    page = c.get("/new").text
    assert "For the runner: harness and model" in page          # tucked away
    r = c.post("/new", data={"name": "pv", "action": "preview"})
    for want in ('value="ide"', 'value="studio"', 'value="handoff"', 'value="none"'):
        assert want in r.text, want
    assert "Hand it to the runner at once" not in r.text


@pytest.mark.parametrize("start,how,action", [
    ("ide", "web", "/ide"), ("ide", "desktop", "/ide"), ("studio", None, "/studio/open")])
def test_start_by_opening_it(fake, tmp_path, start, how, action):
    c = _client()
    r = _create(c, tmp_path, "s1", start, **({"ide": how} if how else {}))
    e, pkt = _root("s1")
    loc = r.headers["location"]
    want = {"ide": "ide-" + how if how else None, "studio": "studio"}[start]
    assert loc.startswith("/p/s1/%s?" % pkt.wpid) and "open=" + want in loc
    meta = pkt.load_status()[0]
    assert meta["autonomy"] == "manual" and meta["state"] == "PAUSED"
    page = c.get(loc).text
    assert 'id="autoopen"' in page and action in page.split('id="autoopen"')[1][:400]
    assert "<script>" not in page and "/static/page.js" in page     # CSP: no inline script
    if how:
        assert 'name="go" value="%s"' % how in page
    assert 'id="autoopen"' not in c.get("/p/s1/%s" % pkt.wpid).text      # only when asked


def test_hand_to_runner_needs_an_objective(fake, tmp_path):
    c = _client()
    r = _create(c, tmp_path, "h1", "handoff")
    msg, ok = _flash(r)
    assert not ok and "objective" in msg and registry.get("h1") is None
    r = _create(c, tmp_path, "h1", "handoff", objective="Count to 3.")
    assert r.headers["location"].startswith("/p/h1?")
    e, pkt = _root("h1")
    meta = pkt.load_status()[0]
    assert meta["state"] == "RUNNABLE" and meta["autonomy"] == "handoff"


def test_old_form_still_works(fake, tmp_path):
    c = _client()
    r = c.post("/new", data={"name": "o1", "dir": str(tmp_path / "pp"),
                             "objective": "Count.", "go": "1"}, follow_redirects=False)
    assert r.headers["location"].startswith("/p/o1?")
    assert _root("o1")[1].load_status()[0]["state"] == "RUNNABLE"


def test_cards_have_open(fake):
    _new("a")
    page = _client().get("/b/main").text
    card = page.split('id="card-a"')[1].split("</details>\n    {%")[0]
    assert "Open ▾" in card and "/studio/open" in card and "/compose" in card


def test_hand_off_after_a_checkpoint(fake):
    e, pkt = _new("a")
    scheduler.tick([e], until_idle=True)
    checkpoint.record(pkt, "parser half done", body="Tokens work.", next_action="write tests")
    c = _client()
    page = c.get("/p/a/compose").text
    assert "Context so far:\nparser half done" in page and "drafted from where you left it" in page
    assert 'name="after" value="1"' in page
    r = c.post("/p/a/compose", data={"action": "handoff", "instruction": "Write the tests.",
                                     "note": "Context so far: parser half done",
                                     "after": "1"}, follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    rec = [x for x in pkt.journal().records if x["type"] == "handoff"][-1]
    assert rec["defer"] is True and rec["note"].startswith("Context so far")


def test_packet_page_hand_off_after_i_leave(fake):
    e, pkt = _new("a")
    executor.admin(pkt, "pause")
    c = _client()
    assert "after I leave" in c.get("/p/a/%s" % pkt.wpid).text
    r = c.post("/p/a/%s/act" % pkt.wpid, data={"action": "handoff", "after": "1"},
               follow_redirects=False)
    assert _flash(r)[1]
    assert pkt.journal().records[-1]["defer"] is True


def test_uncommitted_changes_commit_as_wip(home, source):
    """A git packet with uncommitted work: one click commits it as WIP."""
    from test_packet_layout import new_here, run_out
    from test_ide import _board_client
    plan = new_here(source)
    root = Packet(os.path.join(plan.path, "runs", plan.root))
    run_out(plan.path, root)
    (source / "scratch.txt").write_text("by hand\n")
    c, origin, tok = _board_client("loopback")
    page = c.get("/p/sr/compose").text
    assert "Commit as WIP" in page
    r = c.post("/p/sr/compose", headers=origin, data={
        "csrf": tok, "action": "fix", "check": "next.dirty.%s" % os.path.basename(source)},
        follow_redirects=False)
    assert _flash(r)[1], _flash(r)
    log = subprocess.run(["git", "-C", str(source), "log", "-1", "--format=%s"],
                         capture_output=True, text=True).stdout.strip()
    assert log == "WIP before hand-off"
    assert "Commit as WIP" not in c.get("/p/sr/compose").text
