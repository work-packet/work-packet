"""The packet layout (docs/run-binding-v1.md, stage A): the clone is the
packet; the card and ``.work-packet/`` sit at its top, runs in
``.work-packet/runs/``, and steps work in the clone through ``work/<name>``."""

import os

from conftest import child_wpid
from work_packet import (card, executor, history, layout, project, registry, stats, views,
                         workspace)
from work_packet.check import check
from work_packet.packet import Packet

from test_setup import git, home, source                       # noqa: F401


def new_here(folder, name="sr", prompt="Count in state/count.md."):
    cwd = os.getcwd()
    os.chdir(folder)
    try:
        plan = project.new(name, prompt, path=os.getcwd(), packet=True)
    finally:
        os.chdir(cwd)
    return plan


def run_out(proj, root):
    for _ in range(20):
        if root.load_status()[0]["state"] != "RUNNABLE":
            break
        assert executor.step(proj).code == 0


def test_new_here_in_a_clone(home, source):
    plan = new_here(source)
    proj = str(source / ".work-packet")
    assert plan.path == proj
    assert sorted(os.listdir(proj)) == ["identity", "project.toml", "prompt.md", "runs", "state"]
    assert os.path.isfile(os.path.join(proj, "runs", plan.root, "status.md"))
    assert registry.get("sr")["path"] == proj
    # Hidden from git: the clone stays clean.
    assert git(source, "status", "--porcelain") == ""
    excl = open(source / ".git" / "info" / "exclude").read().split()
    assert "/.work-packet" in excl and "/sr.wp.md" in excl
    # Found from the folder, the card, the name.
    root = layout.run_dir(proj, plan.root)
    assert registry.resolve(str(source)) == root
    assert registry.resolve("sr") == root
    assert project.project_of(root) == proj


def test_steps_work_in_the_clone(home, source):
    plan = new_here(source)
    proj = plan.path
    root = Packet(layout.run_dir(proj, plan.root))
    assert executor.step(str(source)).code == 0
    w = os.path.join(root.path, "work", "dv-solve")
    assert os.readlink(w) == os.path.join("..", "..", "..", "..")
    assert os.path.realpath(w) == str(source)
    assert workspace.git_trees(root) == {"dv-solve": w}
    assert workspace.heads(root)["dv-solve"] == git(source, "rev-parse", "HEAD")
    # The card is at the clone's top, and git does not see it or the run.
    c = card.load(str(source / "sr.wp.md"))
    assert [e.kind for e in c.entries][:2] == ["sent", "accepted"]
    assert git(source, "status", "--porcelain") == ""
    # A change the step makes in the clone is a change in the clone.
    (source / "new.txt").write_text("x\n")
    assert workspace.dirty(root) == {"dv-solve": ["?? new.txt"]}
    # Nothing else in the run dir was linked or made.
    assert sorted(os.listdir(os.path.join(root.path, "work"))) == ["dv-solve"]


def test_a_folder_without_a_repo(home, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "input.txt").write_text("some input\n")
    plan = new_here(folder, name="notes")
    root = Packet(layout.run_dir(plan.path, plan.root))
    assert executor.step(str(folder)).code == 0
    assert open(os.path.join(root.path, "work", "notes", "input.txt")).read() == "some input\n"
    assert workspace.git_trees(root) == {}
    assert os.path.isfile(folder / "notes.wp.md")
    assert not os.path.exists(folder / ".git")


def test_runs_children_stats_and_harvest(home, source):
    plan = new_here(source)
    proj = plan.path
    root = Packet(layout.run_dir(proj, plan.root))
    run_out(proj, root)
    kid = Packet(layout.run_dir(proj, child_wpid(plan.root, 8, 0)))
    assert os.path.isfile(kid.status_path)
    assert executor.step(kid.path).code == 0
    assert card.load(str(source / "sr.wp.md")).state() == "done"
    # Everything that lists runs sees both.
    assert {p.wpid for _, p, _, _ in views.packets(proj, plan.root)} == {plan.root, kid.wpid}
    assert len(registry.find_packets(kid.wpid[:8])) == 1
    con = history.connect()
    rows = dict(con.execute("SELECT id, provisional FROM packet WHERE project = 'sr'"))
    assert rows == {plan.root: 0, kid.wpid: 0}
    assert history.verify_project(con, "sr", proj) == []
    con.close()
    assert stats.report(stats.groups(*history.collect(["sr"]))) == \
        stats.report(stats.groups(*stats.collect([("sr", proj)])))
    assert check(proj).issues == []
    assert git(source, "status", "--porcelain") == ""


def test_cli_new_here(home, source):
    from work_packet import cli
    cwd = os.getcwd()
    os.chdir(source)
    try:
        assert cli.main(["new", "cl", "--here", "--prompt", "Count."]) == 0
        assert cli.main(["new", "cl2", "--here", "--prompt", "Count."]) != 0   # one per folder
    finally:
        os.chdir(cwd)
    assert registry.get("cl")["path"] == str(source / ".work-packet")


def _crawl_one(tmp_path, monkeypatch, packet):
    """The same finished project, in one layout, crawled in its own home."""
    import uuid
    from starlette.testclient import TestClient
    from work_packet.dash import crawl
    from work_packet.dash.app import create_app
    base = tmp_path / ("packet" if packet else "legacy")
    base.mkdir()
    monkeypatch.setenv("WPK_HOME", str(base / "home"))
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("00000000-0000-4000-8000-000000000001"))
    folder = base / "sr"
    folder.mkdir()
    plan = project.new("sr", "Count in state/count.md.", path=str(folder), packet=packet)
    root = Packet(layout.run_dir(plan.path, plan.root))
    run_out(plan.path, root)
    kid = Packet(layout.run_dir(plan.path, child_wpid(plan.root, 8, 0)))
    assert executor.step(kid.path).code == 0
    return plan.path, crawl.crawl(TestClient(create_app()), "sr")


def test_dash_pages_match_the_legacy_layout(home, tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from work_packet.dash import crawl
    old, before = _crawl_one(tmp_path, monkeypatch, False)
    new, after = _crawl_one(tmp_path, monkeypatch, True)
    assert len(before) > 20
    assert [u for u, (st, _) in after.items() if st >= 500] == []
    subst = [(layout.runs_dir(new), layout.runs_dir(old)), (new, old),
             (layout.packet_folder(new), old)]
    probs = crawl.compare(before, after, subst)
    # Intended: compose's work check names the packet folder, not an empty work/.
    compose = [u for u in after if u.startswith("/p/sr/compose")]
    assert compose and all("steps work in " in after[u][1] for u in compose)
    probs = [p for p in probs if not p.startswith("/p/sr/compose")]
    if probs:                      # say what differs (seen once, not reproduced)
        import difflib
        u = probs[0].split(":")[0]
        a, b = before.get(u, (0, ""))[1], after.get(u, (0, ""))[1]
        if isinstance(a, str) and isinstance(b, str):
            for x, y in subst:
                b = b.replace(x, y)
            probs.append("".join(list(difflib.unified_diff(
                a.splitlines(1), b.splitlines(1), n=0))[:20]))
    if probs and os.environ.get("WPK_DUMP"):
        import difflib
        with open(os.environ["WPK_DUMP"], "w") as fp:
            fp.write("\n".join(probs) + "\n")
            for u in [p.split(":")[0] for p in probs][:40]:
                a = before.get(u, (0, ""))[1]
                b = after.get(u, (0, ""))[1]
                if isinstance(a, str) and isinstance(b, str):
                    for x, y in subst:
                        b = b.replace(x, y)
                    fp.write("".join(difflib.unified_diff(a.splitlines(1), b.splitlines(1), u, u, n=0)))
    assert probs == []


def test_dash_file_browser_shows_the_packet_folder(home, source):
    import pytest
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    new_here(source)
    c = TestClient(create_app())
    r = c.get("/p/sr/doc")
    assert r.status_code == 200 and "README.md" in r.text
    assert c.get("/p/sr/doc?path=work/dv-solve/README.md").status_code == 200
    assert c.get("/p/sr/doc?path=work/dv-solve/.work-packet/project.toml").status_code == 404
    assert c.get("/p/sr/doc?path=work/other").status_code == 404


def _finished_legacy(base, nested=True):
    folder = base / "sr"
    folder.mkdir()
    plan = project.new("sr", "Count in state/count.md.",
                       path=str(folder / "sr") if nested else str(folder))
    root = Packet(layout.run_dir(plan.path, plan.root))
    run_out(plan.path, root)
    kid = Packet(layout.run_dir(plan.path, child_wpid(plan.root, 8, 0)))
    assert executor.step(kid.path).code == 0
    return folder, plan


def _tokens(pages, subst):
    out = {}
    for u, (st, body) in pages.items():
        for x, y in subst:
            body = body.replace(x, y) if isinstance(body, str) else \
                body.replace(x.encode(), y.encode())
        out[u] = (st, body)
    return out


def test_convert_a_nested_project(home, tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet import convert
    from work_packet.dash import crawl
    from work_packet.dash.app import create_app
    folder, plan = _finished_legacy(tmp_path)
    old = plan.path
    before = crawl.crawl(TestClient(create_app()), "sr")
    stats_before = stats.report(stats.groups(*stats.collect([("sr", old)])))
    assert convert.convert("sr", dry_run=True)["folder"] == str(folder)
    assert os.path.isdir(old)                                   # dry run: nothing moved
    p = convert.convert("sr")
    assert p["checks"] == []
    assert os.path.isfile(p["backup"])
    assert sorted(os.listdir(folder)) == [".work-packet", "sr.wp.md"]
    dot = str(folder / ".work-packet")
    assert registry.get("sr")["path"] == dot
    assert sorted(os.listdir(os.path.join(dot, "runs"))) == sorted(
        [plan.root, child_wpid(plan.root, 8, 0)])
    assert stats.report(stats.groups(*stats.collect([("sr", dot)]))) == stats_before
    after = crawl.crawl(TestClient(create_app()), "sr")
    # Paths overlap (the folder is a prefix of the old project), so both
    # sides get placeholders.
    before = _tokens(before, [(layout.runs_dir(old), "@RUNS@"), (old, "@PROJ@")])
    after = _tokens(after, [(layout.runs_dir(dot), "@RUNS@"), (dot, "@PROJ@"),
                            (layout.runs_dir(old), "@RUNS@"), (old, "@PROJ@"),
                            (str(folder), "@PROJ@")])     # transcripts keep old paths
    subst = []
    probs = [x for x in crawl.compare(before, after, subst)
             if not x.startswith("/p/sr/compose")]
    if probs and os.environ.get("WPK_DUMP"):
        import difflib
        with open(os.environ["WPK_DUMP"], "w") as fp:
            fp.write("\n".join(probs) + "\n")
            for u in [x.split(":")[0] for x in probs][:10]:
                a, b = before.get(u, (0, ""))[1], after.get(u, (0, ""))[1]
                if isinstance(a, str) and isinstance(b, str):
                    for x, y in subst:
                        b = b.replace(x, y)
                    fp.write("".join(difflib.unified_diff(a.splitlines(1), b.splitlines(1),
                                                          u, u, n=0)))
    assert probs == []
    # It goes on running in the new layout: a continue adds a step.
    assert executor.admin(Packet(layout.run_dir(dot, plan.root)), "continue",
                          instruction="Count to 9.").code == 0
    assert executor.step(str(folder)).code == 0
    assert os.path.realpath(os.path.join(layout.run_dir(dot, plan.root), "work", "sr")) == \
        str(folder)
    assert check(dot).issues == []


def test_convert_in_place_and_refusals(home, tmp_path):
    from work_packet import convert
    folder, plan = _finished_legacy(tmp_path, nested=False)
    (folder / "notes.txt").write_text("mine\n")
    p = convert.convert("sr")
    assert p["in_place"] and p["checks"] == []
    assert sorted(os.listdir(folder)) == [".work-packet", "notes.txt", "sr.wp.md"]
    import pytest
    with pytest.raises(convert.ConvertError, match="already"):
        convert.convert("sr")
