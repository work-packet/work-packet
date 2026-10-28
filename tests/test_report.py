"""The completion report (docs/completion-report.md)."""

import os

import pytest

from conftest import NOW, make_project
from work_packet import executor, report, views
from work_packet.check import check
from work_packet.frontmatter import dump, load
from work_packet.packet import Packet


@pytest.fixture
def proj(tmp_path, fake):
    fake("reporter")
    return make_project(tmp_path)


def _done(root):
    return root.load_status()[0]["state"] == "COMPLETED"


def test_done_writes_report(proj):
    p, root = proj
    out = executor.step(p)
    assert out.code == 0, out.msg
    assert _done(root)
    meta, body = load(root.report_path)
    assert meta["outcome"] == "Chose a two-phase rollout."
    assert meta["deliverables"] == [{"path": "state/plan.md", "what": "the plan"}]
    assert os.path.isfile(os.path.join(root.step_dir(1), "report.md"))
    # The outcome leads status.md, so ps and the board's card show it.
    assert root.load_status()[1].startswith("Chose a two-phase rollout.\n\nPolished")
    dec = [r for r in root.journal().records if r["type"] == "commit-begin"][0]["decision"]
    assert dec["report"] == {"outcome": "Chose a two-phase rollout.",
                             "deliverables": ["state/plan.md"]}
    assert check(p).issues == []


def test_done_without_report_is_rejected(proj, fake):
    p, root = proj
    fake("reporter", "no-report")
    out = executor.step(p)
    assert out.code != 0 and ".pending/report.md was not written" in out.msg
    assert root.load_status()[0]["state"] == "RUNNABLE"
    assert not os.path.exists(root.report_path)


def test_missing_deliverable_is_rejected(proj, monkeypatch):
    p, root = proj
    monkeypatch.setenv("WPK_FAKE_REPORT_PATHS", "state/plan.md,state/nope.md")
    out = executor.step(p)
    assert out.code != 0 and "state/nope.md does not exist" in out.msg


@pytest.mark.parametrize("path,why", [
    ("/etc/passwd", "relative"), ("../x", "under state/ or work/"),
    ("steps/0001/summary.md", "under state/ or work/")])
def test_deliverable_must_be_in_the_packet(tmp_path, path, why):
    probs = report.validate({"outcome": "x", "deliverables": [{"path": path, "what": "w"}]},
                            "\n".join("## %s\nnone" % s for s in report.SECTIONS),
                            str(tmp_path), str(tmp_path / "state"))
    assert any(why in m for m in probs), probs


def test_sections_and_outcome_required(tmp_path):
    probs = report.validate({"deliverables": []}, "## Outcome\nok\n", str(tmp_path),
                            str(tmp_path))
    assert "outcome: missing" in probs
    assert any("Decisions, Deliverables, Open items" in m for m in probs)
    assert report.validate(None, "", str(tmp_path), str(tmp_path))


def test_stamp_records_work_repo_commits():
    meta = {"outcome": "x", "deliverables": [
        {"path": "work/app/docs/plan.md", "what": "a"}, {"path": "state/n.md", "what": "b"},
        {"path": "work/plain/x.md", "what": "c"}]}
    out = report.stamp(meta, {"app": "abc123"})
    assert [d.get("commit") for d in out["deliverables"]] == ["abc123", None, None]
    assert "commit" not in meta["deliverables"][0]      # the input is left alone


def test_next_batch_archives_the_report(proj):
    p, root = proj
    executor.step(p)
    out = executor.admin(root, "continue", instruction="Do phase two.", by="me")
    assert out.code == 0, out.msg
    assert not os.path.exists(root.report_path)
    assert os.path.isfile(os.path.join(root.state_dir, "history", "report-1.md"))
    h = [r for r in root.journal().records if r["type"] == "handoff"][-1]
    assert h["report"] == "state/history/report-1.md"


def _write_report(pkt, outcome, open_items="none"):
    os.makedirs(pkt.state_dir, exist_ok=True)
    with open(os.path.join(pkt.state_dir, "r.md"), "w") as fp:
        fp.write("x\n")
    body = "## Outcome\n%s\n\n## Decisions\n- d of %s\n\n## Deliverables\n\n" \
        "## Open items\n%s\n" % (outcome, outcome, open_items)
    with open(pkt.report_path, "w") as fp:
        fp.write(dump({"outcome": outcome,
                       "deliverables": [{"path": "state/r.md", "what": "result"}]}, body))


def test_render_rolls_up_children(tmp_path, fake):
    p, root = make_project(tmp_path, steps=2, spawn_at=1)
    kid = Packet(os.path.join(p, "packets", root.load_status()[0]["children"][0]))
    _write_report(root, "Parent done.")
    lines = report.render(root)
    text = "\n".join(lines)
    assert lines[0] == "# Report: %s" % root.wpid
    assert "**Outcome:** Parent done." in text
    assert os.path.join(root.path, "state/r.md") + ": result" in text
    assert "### %s (RUNNABLE)" % kid.wpid in text and "No report yet." in text
    _write_report(kid, "Child done.", open_items="- check the child's numbers")
    text = "\n".join(report.render(root))
    assert "### %s (RUNNABLE): Child done." % kid.wpid in text
    assert "#### Open items" in text and "check the child's numbers" in text
    assert os.path.join(kid.path, "state/r.md") in text


def test_report_lines_falls_back_to_summary(proj, fake):
    p, root = proj
    lines = views.report_lines(root)
    assert "No completion report: the packet has not finished" in "\n".join(lines)
    executor.step(p)
    assert views.report_lines(root)[0] == "# Report: %s" % root.wpid
    os.remove(root.report_path)
    assert "finished without one" in "\n".join(views.report_lines(root))
    assert any("Polished the plan" in x for x in views.report_lines(root))


def test_show_includes_the_report(proj):
    p, root = proj
    executor.step(p)
    text = "\n".join(views.show(root))
    assert "## report.md" in text and "### Decisions" in text


def test_packet_page_leads_with_the_report(proj, tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet import registry
    from work_packet.dash.app import create_app
    p, root = proj
    executor.step(p)
    name = os.path.basename(p)
    registry.register({"name": name, "path": p, "root": root.wpid, "created": NOW})
    c = TestClient(create_app())
    r = c.get("/p/%s/%s" % (name, root.wpid))
    assert r.status_code == 200
    html = r.text
    i = html.index('id="report"')
    assert i < html.index("Next batch") and i < html.index("<h2>Status</h2>")
    assert "Chose a two-phase rollout." in html
    assert "Two phases, because the cutover is risky." in html
    assert "Last summary" not in html
    r = c.get("/p/%s/%s/file" % (name, root.wpid), params={"path": "state/plan.md", "raw": "1"})
    assert r.status_code == 200 and r.text.startswith("# Plan")
    r = c.get("/p/%s/%s/file" % (name, root.wpid), params={"path": "state/plan.md"})
    assert r.status_code == 200
    if data_has_md():
        assert ">Plan</h1>" in r.text and "text/html" in r.headers["content-type"]
    r = c.get("/p/%s" % name)
    assert r.status_code == 200 and "Chose a two-phase rollout." in r.text
    for bad in ("memento.md", "state/../memento.md", "state/other.md"):
        r = c.get("/p/%s/%s/file" % (name, root.wpid), params={"path": bad})
        assert r.status_code == 404, bad


def test_report_markdown_renders_tables_and_inline_outcome():
    pytest.importorskip("markdown_it")
    from work_packet.dash import data
    html = data.md("| # | Lab |\n|---|---|\n| 1 | Hello `PSS` |\n")
    assert "<table>" in html and "<code>PSS</code>" in html and "|---" not in html
    assert data.md_inline("see `x.md`") == "see <code>x.md</code>"


def data_has_md():
    from work_packet.dash import data
    return data.md("x") is not None


def test_report_links_go_to_the_file_view():
    pytest.importorskip("markdown_it")
    from work_packet.dash import data
    link = data.file_link({"name": "demo"}, "w1", "state")
    html = data.md("[a](plan.md) [b](../work/x.md#s) [c](https://x.org/y) [d](#top)", link)
    assert 'href="/p/demo/w1/file?path=state/plan.md"' in html
    assert 'href="/p/demo/w1/file?path=work/x.md#s"' in html
    assert 'href="https://x.org/y"' in html and 'href="#top"' in html


def test_done_with_open_outline_items_is_rejected(proj, monkeypatch):
    # dv-solve-simbench step 1: a design, an outline whose next item is the
    # owner's review, and resume: done. It should have asked.
    p, root = proj
    monkeypatch.setenv("WPK_FAKE_OUTLINE", "- [x] 1. Design\\n- [ ] 2. Owner review"
                       "\\n- [>] 3. Spike\\n- [-] 4. Dropped: out of scope")
    out = executor.step(p)
    assert out.code != 0 and "open items: 2, 3." in out.msg and "ask:" in out.msg
    assert root.load_status()[0]["state"] == "RUNNABLE"
    assert not os.path.exists(root.report_path)


def test_done_with_finished_outline_is_accepted(proj, monkeypatch):
    p, root = proj
    monkeypatch.setenv("WPK_FAKE_OUTLINE", "- [x] 1. Design\\n- [-] 2. Dropped: not needed")
    out = executor.step(p)
    assert out.code == 0, out.msg
    assert _done(root)


def test_report_keeps_a_copy_of_its_deliverables(proj):
    p, root = proj
    assert executor.step(p).code == 0
    sd = root.step_dir(1)
    assert report.snapshot_index(sd) == {"state/plan.md": "copied"}
    with open(os.path.join(sd, report.SNAP, "state", "plan.md")) as fp:
        assert fp.read() == "# Plan\n\nTwo phases.\n"
    assert check(p).issues == []


def test_snapshot_leaves_out_git_and_what_does_not_fit(tmp_path):
    pkt, sd = tmp_path / "pkt", tmp_path / "step"
    for rel, data in (("work/r/.git/HEAD", "x" * 50), ("work/r/a.txt", "a" * 10),
                      ("state/big.bin", "b" * 100), ("state/s.md", "s")):
        f = pkt / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(data)
    sd.mkdir()
    meta = {"deliverables": [{"path": "work/r"}, {"path": "state/big.bin"},
                             {"path": "state/s.md"}, {"path": "state/gone.md"}]}
    idx = report.snapshot(meta, str(pkt), str(pkt / "state"), str(sd), limit=20)
    assert idx == {"work/r": "copied", "state/big.bin": "too large", "state/s.md": "copied",
                   "state/gone.md": "missing"}
    snap = sd / report.SNAP
    assert (snap / "work/r/a.txt").read_text() == "a" * 10
    assert not (snap / "work/r/.git").exists() and not (snap / "state/big.bin").exists()
    report.snapshot({"deliverables": []}, str(pkt), str(pkt / "state"), str(sd))
    assert not (snap / "state/s.md").exists()                  # a retried commit starts again


def test_task_page_opens_deliverables_as_they_were(fake, tmp_path, monkeypatch):
    """Each task's report links to the copy its step kept, not to today's file."""
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet import project, registry, scheduler
    from work_packet.dash.app import create_app
    fake("reporter")
    monkeypatch.chdir(tmp_path)
    made = project.new("rp", "Write the plan.")
    e = registry.get("rp")
    root = Packet(os.path.join(made.path, "packets", made.root))
    scheduler.tick([e], until_idle=True)
    assert executor.admin(root, "continue", instruction="Again.").code == 0
    scheduler.tick([e], until_idle=True)
    with open(os.path.join(root.state_dir, "plan.md"), "w") as fp:
        fp.write("# Plan\n\nChanged since.\n")
    c = TestClient(create_app())
    page = c.get("/p/rp/tasks/1")
    assert page.status_code == 200 and "as they were when this task finished" in page.text
    href = "/p/rp/%s/file?path=state/plan.md&amp;step=0001" % root.wpid
    assert href in page.text
    then = c.get(href.replace("&amp;", "&"))
    assert then.status_code == 200 and "Two phases." in then.text
    assert 'data-writable="1"' not in then.text                 # a record, not to edit
    assert "Changed since." in c.get("/p/rp/%s/file?path=state/plan.md" % root.wpid).text
    for bad in ("../0001", "0009", "nope"):
        r = c.get("/p/rp/%s/file" % root.wpid, params={"path": "state/plan.md", "step": bad})
        assert r.status_code == 404, bad
    assert c.get("/p/rp/%s/file" % root.wpid, params={
        "path": "state/../status.md", "step": "0001"}).status_code == 404
