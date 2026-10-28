"""The executor keeps the card and the history store current (design P2,
docs/dash-history-v1.md E1-E4): no `wpk migrate` by hand."""

import os

from conftest import ROOT, child_wpid, make_project
from work_packet import card, executor, history, livecard, migrate, project, stats
from work_packet.packet import Packet


def _card(proj):
    return card.load(os.path.join(proj, "demo.wp.md"))


def _thread(c):
    return [card.render(card.Card(meta={}, entries=[e])) for e in c.entries]


def test_steps_write_the_card_as_they_run(tmp_path, fake):
    proj, root = make_project(tmp_path / "p")
    project.adopt(proj)
    executor.step(proj)
    c = _card(proj)
    assert [e.kind for e in c.entries][:2] == ["sent", "accepted"]
    assert c.state() == "working"
    executor.step(proj)
    con = history.connect()
    assert len(history.steps(con, project="demo")) == 2
    assert con.execute("SELECT provisional FROM packet WHERE id = ?", (ROOT,)).fetchone()[0] == 1
    con.close()


def test_live_card_equals_a_migrated_one_and_completion_harvests(tmp_path, fake):
    proj, root = make_project(tmp_path / "p")
    project.adopt(proj)
    for _ in range(20):
        if root.load_status()[0]["state"] != "RUNNABLE":
            break
        assert executor.step(proj).code == 0
    kid = Packet(os.path.join(proj, "packets", child_wpid(ROOT, 8, 0)))
    assert executor.step(kid.path).code == 0

    live = _card(proj)
    assert live.state() == "done"
    con = history.connect()
    rows = dict(con.execute("SELECT id, provisional FROM packet WHERE project = 'demo'"))
    con.close()
    assert rows == {ROOT: 0, kid.wpid: 0}           # harvested when it all completed
    assert history.verify_project(history.connect(), "demo", proj) == []

    # What `wpk migrate` would make from scratch is the same thread.
    os.unlink(os.path.join(proj, "demo.wp.md"))
    (res,) = migrate.migrate()
    assert res["problems"] == []
    assert _thread(_card(proj)) == _thread(live)
    assert stats.report(stats.groups(*history.collect(["demo"]))) == \
        stats.report(stats.groups(*stats.collect([("demo", proj)])))


def test_resuming_a_finished_project_makes_it_provisional_again(tmp_path, fake):
    proj, root = make_project(tmp_path / "p")
    project.adopt(proj)
    for _ in range(20):
        if root.load_status()[0]["state"] != "RUNNABLE":
            break
        executor.step(proj)
    kid = Packet(os.path.join(proj, "packets", child_wpid(ROOT, 8, 0)))
    executor.step(kid.path)
    con = history.connect()
    assert con.execute("SELECT provisional FROM packet WHERE id = ?", (ROOT,)).fetchone()[0] == 0
    con.close()

    assert executor.admin(root, "continue", instruction="Count to 9.").code == 0
    con = history.connect()
    assert con.execute("SELECT provisional FROM packet WHERE id = ?", (ROOT,)).fetchone()[0] == 1
    con.close()
    c = _card(proj)
    assert c.entries[-1].kind == "request" and "Count to 9." in c.entries[-1].body
    assert c.state() == "open"


def test_a_card_failure_never_fails_a_step(tmp_path, fake, monkeypatch):
    proj, root = make_project(tmp_path / "p")
    project.adopt(proj)

    real, broken = migrate.keep_project, [True]

    def flaky(*a, **k):
        if broken[0]:
            raise RuntimeError("no")
        return real(*a, **k)
    monkeypatch.setattr(migrate, "keep_project", flaky)
    assert executor.step(proj).code == 0
    assert not os.path.exists(os.path.join(proj, "demo.wp.md"))
    broken[0] = False
    executor.step(proj)                                 # the next one catches up
    assert len([e for e in _card(proj).entries if e.kind == "accepted"]) == 1


def test_unregistered_and_disabled_projects_are_left_alone(tmp_path, fake, monkeypatch):
    proj, root = make_project(tmp_path / "p")
    executor.step(proj)
    assert not os.path.exists(os.path.join(proj, "demo.wp.md"))
    project.adopt(proj)
    monkeypatch.setenv("WPK_NO_LIVECARD", "1")
    executor.step(proj)
    assert not os.path.exists(os.path.join(proj, "demo.wp.md"))
    assert livecard.flush() == []
