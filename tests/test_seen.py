"""Finished work in the Overview's Needs attention, and token use on /stats
(docs/overview-recent.md)."""

import pytest

from test_dash_tasks import _client, _flash, _new
from work_packet import actions, executor, schema


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _at(monkeypatch, t):
    monkeypatch.setenv("WPK_NOW", t)


def _done(name):
    from work_packet import scheduler
    e, pkt = _new(name)
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["state"] == "COMPLETED"
    return e, pkt


def test_status_records_stopped_and_seen(tmp_path, fake, monkeypatch):
    _at(monkeypatch, "2026-10-28T10:00:00Z")
    e, pkt = _done("a")
    meta, body = pkt.load_status()
    assert meta["stopped"] == "2026-10-28T10:00:00Z" and "seen" not in meta
    assert schema.validate_status(meta, body) == [] and executor.unread(meta)

    _at(monkeypatch, "2026-10-28T11:00:00Z")
    out = executor.mark_seen(pkt, by="me")
    assert out.code == 0 and out.msg.endswith("seen")
    meta, _ = pkt.load_status()
    assert meta["seen"] == "2026-10-28T11:00:00Z" and not executor.unread(meta)
    rec = [r for r in pkt.journal().records if r.get("type") == "seen"][-1]
    assert rec == {"type": "seen", "t": "2026-10-28T11:00:00Z", "by": "me"}
    assert schema.validate_journal_record(rec) == []

    # A next task: running again, so no longer stopped.
    assert actions.continue_(pkt, "Again.").code == 0
    meta, _ = pkt.load_status()
    assert meta["state"] == "RUNNABLE" and "stopped" not in meta
    assert executor.mark_seen(pkt).msg.endswith("not stopped")

    bad = dict(meta, stopped="2026-10-28T11:00:00Z")
    assert any(p.field == "stopped" for p in schema.validate_status(bad))


def test_pause_by_a_limit_is_stopped_by_hand_is_not(tmp_path, fake, monkeypatch):
    e, pkt = _new("b")
    assert executor.admin(pkt, "pause").code == 0
    assert "stopped" not in pkt.load_status()[0]
    assert executor.admin(pkt, "resume").code == 0
    assert executor.admin(pkt, "pause", by="wpkd", reason="over the day's cap",
                          stopped=True).code == 0
    meta, _ = pkt.load_status()
    assert meta["stopped"] and executor.unread(meta)
    assert executor.admin(pkt, "resume").code == 0
    assert "stopped" not in pkt.load_status()[0]


def test_overview_lists_finished_work_until_seen(tmp_path, fake, monkeypatch):
    _at(monkeypatch, "2026-10-28T10:00:00Z")
    _done("a")
    _done("b")
    e, held = _new("c")
    executor.admin(held, "pause", by="wpkd", reason="over the day's cap", stopped=True)
    c = _client()
    html = c.get("/").text
    assert html.count('class="state COMPLETED">DONE<') == 2 and ">STOPPED<" in html
    assert "over the day&#39;s cap" in html or "over the day's cap" in html
    assert 'data-pick-all="form"' in html and "Clear all finished (3)" in html

    # Opening a project takes it off.
    _at(monkeypatch, "2026-10-28T11:00:00Z")
    assert c.get("/p/a").status_code == 200
    html = c.get("/").text
    assert 'value="a" aria-label="tick a"' not in html
    assert 'value="b" aria-label="tick b"' in html

    # Dismissing one, without opening it.
    r = c.post("/seen", data={"project": ["b"]}, follow_redirects=False)
    assert _flash(r) == ("marked 1 seen", True)
    html = c.get("/").text
    assert 'value="b" aria-label="tick b"' not in html and 'value="c"' in html

    # Clear all.
    r = c.post("/seen", data={"all": "1"}, follow_redirects=False)
    assert _flash(r) == ("marked 1 seen", True)
    html = c.get("/").text
    assert ">DONE<" not in html and ">STOPPED<" not in html and "Clear all finished" not in html
    r = c.post("/seen", data={}, follow_redirects=False)
    assert _flash(r)[1] is False


def test_a_next_task_that_finishes_comes_back(tmp_path, fake, monkeypatch):
    from work_packet import scheduler
    _at(monkeypatch, "2026-10-28T10:00:00Z")
    e, pkt = _done("a")
    c = _client()
    c.get("/p/a/" + pkt.wpid)                  # the packet page marks it seen too
    assert ">DONE<" not in c.get("/").text
    _at(monkeypatch, "2026-10-28T12:00:00Z")
    assert actions.continue_(pkt, "Read state/count.md (0 if missing), add one.").code == 0
    assert ">DONE<" not in c.get("/").text     # running, not stopped
    scheduler.tick([e], until_idle=True)
    html = c.get("/").text
    assert html.count(">DONE<") == 1 and "task 2" in html


def test_waits_for_the_whole_project(tmp_path, fake, monkeypatch):
    _at(monkeypatch, "2026-10-28T10:00:00Z")
    e, pkt = _done("a")
    # A child still to run keeps the project off the list.
    from work_packet.dash import data
    nodes = data.tree(e)
    nodes.append(dict(nodes[0], wpid="k", depth=1, state="RUNNABLE", running=None))
    assert data.card(e, nodes=nodes)["unread"] is None
    assert data.card(e, nodes=nodes[:1])["unread"]["kind"] == "done"


def test_older_packets_are_not_listed(tmp_path, fake, monkeypatch):
    e, pkt = _done("a")
    meta, body = pkt.load_status()
    meta.pop("stopped")                      # as written before this change
    pkt.save_status(meta, body)
    c = _client()
    assert ">DONE<" not in c.get("/").text
    assert c.get("/p/a").status_code == 200
    assert not [r for r in pkt.journal().records if r.get("type") == "seen"]


def test_wpk_seen(tmp_path, fake, monkeypatch, capsys):
    from work_packet import cli
    _at(monkeypatch, "2026-10-28T10:00:00Z")
    _done("a")
    _done("b")
    assert cli.main(["seen"]) == 0
    out = capsys.readouterr().out
    assert "DONE" in out and " a " in out and " b " in out
    _at(monkeypatch, "2026-10-28T11:00:00Z")
    assert cli.main(["seen", "a"]) == 0
    assert "a:" in capsys.readouterr().out
    cli.main(["seen"])
    out = capsys.readouterr().out
    assert " a " not in out and " b " in out
    assert cli.main(["seen", "--all"]) == 0
    capsys.readouterr()
    cli.main(["seen"])
    assert "nothing finished" in capsys.readouterr().out


def test_stats_page_and_overview_boards(tmp_path, fake, monkeypatch):
    _done("a")
    c = _client()
    html = c.get("/").text
    assert 'href="/stats"' in html and "Tokens, last" not in html
    assert 'href="/?days=30#boards"' in html          # the Boards table keeps its window
    r = c.get("/stats?days=30")
    assert r.status_code == 200 and "Tokens, last 30 days" in r.text
