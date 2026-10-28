"""Migration to cards and the history store (docs/migration-v1.md): every
statistic must come out the same from the history store as from the runs."""

import json
import os
import shutil

from conftest import ROOT, child_wpid, make_project

from work_packet import card, executor, history, index, journal, migrate, project, stats
from work_packet.cli import main
from work_packet.packet import Packet


def status(pkt):
    return pkt.load_status()[0]


def run_to_end(proj, root):
    for _ in range(20):
        if status(root)["state"] != "RUNNABLE":
            break
        assert executor.step(proj).code == 0
    kid = Packet(os.path.join(proj, "packets", child_wpid(ROOT, 8, 0)))
    assert executor.step(kid.path).code == 0
    return kid


def finished(tmp_path):
    proj, root = make_project(tmp_path / "p")
    kid = run_to_end(proj, root)
    project.adopt(proj)
    return proj, root, kid


def test_finished_project_migrates_and_keeps_every_statistic(tmp_path, fake, capsys):
    proj, root, kid = finished(tmp_path)
    before = stats.collect([("demo", proj)])
    (res,) = migrate.migrate()
    assert res["problems"] == [] and res["skipped"] is None
    assert sorted(res["harvested"]) == sorted([ROOT, kid.wpid])

    # The card.
    cpath = os.path.join(proj, "demo.wp.md")
    text = open(cpath).read()
    c = card.parse(text)
    assert c.problems == [] and card.render(c) == text
    assert c.id == ROOT and c.name == "demo" and c.title == "Count to 8."
    kinds = [e.kind for e in c.entries]
    assert kinds[:2] == ["sent", "accepted"] and kinds[-2:] == ["result", "pinned"]
    assert "note" in kinds                         # the spawn of hello
    assert c.state() == "done"
    assert all(e.get("Migrated-From") for e in c.entries if e.kind != "pinned")
    res_e = [e for e in c.entries if e.kind == "result"][0]
    assert res_e.get("Outcome") == "done" and res_e.get("Steps") == "s1-s8"

    # The child's card, under runs/<root>/sub/, reached through the link.
    sub = os.path.join(migrate.runs_dir(), ROOT, "sub", "hello.wp.md")
    kc = card.load(sub)
    assert kc.meta["parent"] == "pkt:demo" and kc.entries[0].who == "pkt:demo"
    assert kc.state() == "done"
    assert os.path.realpath(os.path.join(migrate.runs_dir(), ROOT)) == os.path.realpath(root.path)

    # The index.
    assert index.find("demo") == cpath and index.find("demo.hello") == sub

    # Every statistic, identical, from history.
    con = history.connect()
    after = history.collect(["demo"], con=con)
    assert [history._step_json(s) for s in before[0]] == [history._step_json(s) for s in after[0]]
    assert sorted(before[1]) == sorted(after[1])
    assert stats.report(stats.groups(*before)) == stats.report(stats.groups(*after))
    for by in stats.ROLLUPS:
        assert stats.rollup(before[0], by) == stats.rollup(after[0], by)
    assert history.figures(before[0]) == history.figures(after[0])

    # Every file of the record is in the blob store, and an archive exists.
    n = con.execute("SELECT COUNT(*) FROM file WHERE packet = ?", (ROOT,)).fetchone()[0]
    assert n > 10
    (arch,) = [r[0] for r in con.execute("SELECT archive FROM packet WHERE id = ?", (ROOT,))]
    assert os.path.isfile(arch)
    con.close()

    # Running it again changes nothing.
    (res2,) = migrate.migrate()
    assert res2["problems"] == [] and open(cpath).read() == text


def test_stats_survive_the_runs_being_removed(tmp_path, fake, capsys):
    proj, root, kid = finished(tmp_path)
    assert main(["stats", "demo", "--json"]) == 0
    want = capsys.readouterr().out
    assert main(["stats", "demo", "--by", "day", "--json"]) == 0
    want_day = capsys.readouterr().out
    migrate.migrate()
    shutil.rmtree(os.path.join(proj, "packets"))
    assert main(["stats", "demo", "--json"]) == 0
    assert capsys.readouterr().out == want
    assert main(["stats", "demo", "--by", "day", "--json"]) == 0
    assert capsys.readouterr().out == want_day


def test_rebuild_from_archives(tmp_path, fake):
    proj, root, kid = finished(tmp_path)
    migrate.migrate()
    con = history.connect()
    want = [history._step_json(s) for s in history.steps(con)]
    con.close()
    os.unlink(history.db_path())
    assert history.rebuild() == 2
    con = history.connect()
    assert [history._step_json(s) for s in history.steps(con)] == want
    con.close()


def test_active_project_is_provisional_and_resyncs(tmp_path, fake):
    proj, root = make_project(tmp_path / "p")
    for _ in range(3):
        executor.step(proj)
    project.adopt(proj)
    (res,) = migrate.migrate()
    assert res["provisional"] == [ROOT] and res["harvested"] == [] and res["problems"] == []
    c = card.load(os.path.join(proj, "demo.wp.md"))
    assert c.state() == "working" and not [e for e in c.entries if e.kind == "pinned"]
    executor.step(proj)
    (res,) = migrate.migrate()
    assert res["problems"] == []
    con = history.connect()
    assert len(history.steps(con, project="demo")) == 4
    con.close()


def test_thread_from_questions_requests_and_notes(tmp_path):
    proj, root = make_project(tmp_path, steps=0)
    j = root.journal_path
    for r in [
        {"type": "handoff", "t": "2026-10-26T15:58:44Z", "by": "matt", "from": "PAUSED",
         "to": "RUNNABLE"},
        {"type": "step-start", "t": "2026-10-26T15:58:45Z", "step": 1, "attempt": 1},
        {"type": "commit-begin", "t": "2026-10-26T16:00:03Z", "step": 1,
         "decision": {"state": "NEEDS_INPUT", "reason": "2 questions", "summary": "s",
                      "spawn": []}},
        {"type": "config", "t": "2026-10-26T16:00:49Z", "by": "matt",
         "changes": ["allow WebSearch"]},
        {"type": "handoff", "t": "2026-10-26T16:00:50Z", "by": "matt", "from": "NEEDS_INPUT",
         "to": "RUNNABLE", "note": "Use the 2024 LRM.",
         "questions": [{"id": "web", "q": "Allow WebSearch?", "recommend": "yes",
                        "choices": [], "grants": ["WebSearch"]},
                       {"id": "n labs", "q": "Keep 9 labs?", "choices": ["9", "8"]}],
         "answers": {"web": "yes"}},
        {"type": "commit-begin", "t": "2026-10-26T17:00:00Z", "step": 2,
         "decision": {"state": "COMPLETED", "summary": "## Done\nAll of it.", "spawn": []}},
        {"type": "handoff", "t": "2026-10-26T18:00:51Z", "by": "matt", "from": "COMPLETED",
         "to": "RUNNABLE", "batch": 2, "instruction": "Now the labs.\r\n## Plan\r\nGo."},
    ]:
        journal.append(j, r)
    es, st, ws = migrate.rebuild_thread(root.path, "demo")
    got = [(e.kind, e.arg, e.who) for e in es]
    assert got == [
        ("sent", None, "matt"), ("accepted", None, "runner"),
        ("question", "web", "runner"), ("question", "n-labs", "runner"),
        ("note", None, "matt"),
        ("answer", "web", "matt"), ("answer", "n-labs", "matt"), ("note", None, "matt"),
        ("result", None, "runner"), ("request", None, "matt")]
    q = es[2]
    assert q.get("Recommend") == "yes" and q.get("Grants") == "WebSearch"
    assert es[3].get("Choices") == "9 | 8"
    assert es[6].body == migrate.NO_ANSWER
    assert es[-1].body == "Now the labs.\n### Plan\nGo." and es[-1].get("Batch") == "2"
    assert es[-2].body == "### Done\nAll of it."
    assert card.derive_state(es) == "open"
    text = card.render(card.Card(meta={"title": "t"}, entries=es))
    assert card.render(card.parse(text)) == text


def test_dry_run_writes_nothing(tmp_path, fake):
    proj, root, kid = finished(tmp_path)
    (res,) = migrate.migrate(dry_run=True)
    assert len(res["cards"]) == 2
    assert not os.path.exists(os.path.join(proj, "demo.wp.md"))
    assert not os.path.exists(history.db_path())
    assert not os.path.exists(migrate.runs_dir())


def test_missing_project_dir_is_skipped(tmp_path, fake):
    proj, root, kid = finished(tmp_path)
    shutil.rmtree(proj)
    (res,) = migrate.migrate()
    assert res["skipped"]


def test_cli(tmp_path, fake, capsys):
    proj, root, kid = finished(tmp_path)
    assert main(["migrate", "--dry-run"]) == 0
    assert "would write" in capsys.readouterr().out
    assert main(["migrate"]) == 0
    assert "statistics identical" in capsys.readouterr().out
    assert main(["card", "list"]) == 0
    assert "demo.hello" in capsys.readouterr().out
    assert main(["card", "show", "demo", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "done"
    assert main(["card", "check", os.path.join(proj, "demo.wp.md")]) == 0
    assert main(["history", "verify"]) == 0
    assert "identical" in capsys.readouterr().out
    assert main(["history", "list"]) == 0
    assert "hello" in capsys.readouterr().out
    assert main(["stats", "--history", "--by", "project", "--json"]) == 0
    a = capsys.readouterr().out
    assert main(["stats", "--by", "project", "--json"]) == 0
    assert capsys.readouterr().out == a
    for argv in (["--tools", "--json"], ["--tools", "kind", "--json"], ["--json"]):
        assert main(["stats", "--history"] + argv) == 0
        a = capsys.readouterr().out
        assert main(["stats"] + argv) == 0
        assert capsys.readouterr().out == a
