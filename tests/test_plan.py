"""The plan as a tree, and its versions over the steps (docs/plan-tree.md)."""

import os
import shlex
import sys

import pytest

from conftest import FAKE, NOW
from work_packet import executor, project, registry, scheduler
from work_packet.dash import data, plan
from work_packet.packet import Packet
from work_packet.prompt import state_files

OUTLINE = """# fw-thing outline
Legend: [ ] pending [>] active [x] done.

- [x] 0 Setup: ivpm.yaml. Check: `ivpm update` rc 0.
- [x] 3 Cores: manager and subordinate
  with skid. [x] 3a cores `mgr`; [>] 3b harness
  + BMC; [ ] 3c covers.
- [>] **4 Class layer**
  - [x] 4a pkg
    wrapped line
  - [ ] 4b xact
    - refs: chi src/class
    - checks: `pytest`
  - [-] 4c dropped (no time)
- [ ] Docs without an id

## Regression

- `dfm run lint` rc 0
"""


def _items(tree):
    return [(d, n["id"] or n["text"][:12], n["state"]) for d, n in plan.walk(tree)]


def test_parse_nests_by_indent_and_inline():
    t = plan.parse(OUTLINE)
    assert t["title"] == "fw-thing outline" and t["notes"][0].startswith("Legend:")
    assert _items(t) == [
        (0, "0", "done"), (0, "3", "done"), (1, "3a", "done"), (1, "3b", "active"),
        (1, "3c", "pending"), (0, "4", "active"), (1, "4a", "done"), (1, "4b", "pending"),
        (1, "4c", "deferred"), (0, "Docs without", "pending"), (0, "Regression", None)]
    by = {n["id"]: n for _, n in plan.walk(t) if n["id"]}
    assert by["3"]["text"] == "Cores: manager and subordinate with skid."
    assert by["3b"]["text"] == "harness + BMC"
    assert by["4"]["text"] == "**Class layer**"
    assert by["4a"]["text"] == "pkg wrapped line"
    assert by["4b"]["details"] == ["refs: chi src/class", "checks: `pytest`"]
    reg = t["children"][-1]
    assert reg["kind"] == "group" and reg["notes"] == ["- `dfm run lint` rc 0"]
    assert plan.count(t) == (4, 9)                    # 4c is deferred: not counted
    assert plan.current(t)["id"] == "3b"


def test_compare_marks_changes():
    old = plan.parse("- [ ] 1 a\n- [ ] 2 b\n- [ ] 3 c\n")
    new = plan.parse("- [x] 1 a\n- [ ] 2 b, longer\n  - [ ] 2a sub\n")
    gone = plan.compare(new, old)
    ch = {n["id"]: (n.get("change"), n.get("was")) for _, n in plan.walk(new)}
    assert ch == {"1": ("state", "pending"), "2": ("edited", None), "2a": ("new", None)}
    assert [g["id"] for g in gone] == ["3"]
    assert new["children"][1]["changed"] and not new["children"][0]["changed"]


def _diff(tmp_path, a, b):
    for name, text in (("a", a), ("b", b)):
        os.makedirs(tmp_path / name, exist_ok=True)
        p = tmp_path / name / "outline.md"
        if text is None:
            if p.exists():
                p.unlink()
        else:
            p.write_text(text)
    return executor.state_diff(str(tmp_path / "a"), str(tmp_path / "b"))


@pytest.mark.parametrize("before,after", [
    ("- [ ] 1\n- [ ] 2\n", "- [x] 1\n- [ ] 2\n  - [ ] 2a\n"),
    (None, "- [ ] 1\n"),
    ("- [ ] 1\n", None),
    ("".join("- [ ] %d\n" % i for i in range(40)),
     "".join("- [%s] %d\n" % ("x" if i in (3, 30) else " ", i) for i in range(40) if i != 17)),
])
def test_undo_reverses_a_step_diff(tmp_path, before, after):
    d = _diff(tmp_path, before, after)
    assert plan.undo(after or "", d) == (before or "")
    assert plan.undo(after or "", "--- a/state/x.md\n+++ b/state/x.md\n@@ -1 +1 @@\n-a\n+b\n") \
        == (after or "")
    assert plan.undo("something else\n", d) is None or before is None


def test_from_prompt(tmp_path):
    (tmp_path / "outline.md").write_text("- [ ] 1 uses ``` fences\n")
    (tmp_path / "env.md").write_text("env\n")
    text = "# Step\n\n" + state_files(str(tmp_path)) + "\n\nmore\n"
    assert plan.from_prompt(text) == "- [ ] 1 uses ``` fences\n"
    assert plan.from_prompt("- `state/outline.md` (9000 bytes, not shown)\n") is None


# --- a packet that plans --------------------------------------------------------------

@pytest.fixture(params=[0, 9000], ids=["prompt", "undo"])
def planned(request, tmp_path, monkeypatch):
    """A packet run by the planner behaviour: four steps, then a second batch.
    With padding the prompt does not show the outline, so versions undo diffs."""
    monkeypatch.setenv("WPK_CLAUDE", "%s %s" % (shlex.quote(sys.executable), shlex.quote(FAKE)))
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WPK_NOW", NOW)
    monkeypatch.setenv("WPK_FAKE_BEHAVIOR", "planner")
    monkeypatch.setenv("WPK_FAKE_PAD", str(request.param))
    monkeypatch.delenv("WPK_FAULT_AT", raising=False)
    monkeypatch.delenv("WPK_FAKE_FAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    p = project.new("pl", "Plan, then work through it.")
    e = registry.get("pl")
    pkt = Packet(os.path.join(p.path, "packets", p.root))
    scheduler.tick([e], until_idle=True)
    assert pkt.load_status()[0]["state"] == "COMPLETED"
    out = executor.admin(pkt, "continue", instruction="Now batch two.")
    assert out.code == 0, out.msg
    scheduler.tick([e], until_idle=True)
    return e, pkt, request.param


def test_versions_of_a_packet(planned):
    e, pkt, pad = planned
    if pad:
        assert plan.from_prompt(open(os.path.join(pkt.steps_dir, "0002", "prompt.md")).read()) is None
    vs = plan.versions(pkt, data.steps(pkt))
    assert [(v["key"], v["batch"], v["item"]) for v in vs] == [
        ("s1", 1, "1"), ("s2", 1, "2"), ("s3", 1, "2a"), ("s4", 1, "2b"), ("s5", 2, "1")]
    assert vs[1]["text"].startswith("- [x] 1 Survey the code\n- [>] 2 Build it; [ ] 2a")
    assert vs[3]["text"].startswith("- [x] 1 Survey the code\n- [x] 2 Build it; [x] 2a")
    assert vs[4]["instruction"] == "Now batch two." and vs[4]["text"].startswith("- [x] 1 Second")
    assert vs[0]["summary"] == "Step 1."
    assert os.path.isfile(os.path.join(pkt.state_dir, "history", "outline-1.md"))


def test_page_of_a_version(planned):
    e, pkt, _ = planned
    pl = plan.page(e, pkt.wpid, data.steps(pkt), v="s3")
    assert pl["v"]["key"] == "s3" and not pl["latest"]
    by = {n["id"]: n for _, n in plan.walk(pl["tree"]) if n["id"]}
    assert by["2a"]["change"] == "state" and by["2a"]["was"] == "pending"
    assert [s["n"] for s in by["2a"]["steps"]] == [3]
    assert pl["current"]["id"] == "2b" and pl["done"] == (2, 4)
    assert plan.page(e, pkt.wpid, data.steps(pkt))["latest"]
    assert plan.page(e, "nope", []) is None


def test_plan_page_and_state_files(planned):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    e, pkt, _ = planned
    c = TestClient(create_app())
    base = "/p/pl/%s" % pkt.wpid
    r = c.get(base + "/plan", params={"v": "s3"})
    assert r.status_code == 200
    assert "after step 3" in r.text and "was pending" in r.text and "Batch 2" in r.text
    assert "Now batch two." in r.text
    r = c.get(base + "/plan", params={"v": "s3", "changes": "1", "open": "all"})
    assert r.status_code == 200 and "Survey the code" not in r.text and "parser" in r.text
    assert c.get(base + "/plan").status_code == 200
    assert "/plan" in c.get(base).text
    r = c.get(base + "/file", params={"path": "state/history/outline-1.md"})
    assert r.status_code == 200 and 'id="mk-doc"' in r.text
    assert 'data-writable="1"' in r.text                       # COMPLETED: yours to edit
    for bad in ("state/../status.md", "state/nope.md", "memento.md"):
        assert c.get(base + "/file", params={"path": bad}).status_code == 404, bad
    assert c.get("/p/pl/00000000-0000-4000-8000-00000000dead/plan").status_code == 404


def test_packet_page_tabs_and_tasks(planned):
    """docs/packet-page.md: the root's steps split into tasks at each hand-off."""
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    e, pkt, _ = planned
    ts = data.tasks(e, data.tree(e))
    assert [(t["kind"], t["n"], t["first"], t["last"]) for t in ts] == [
        ("task", 1, 1, 4), ("task", 2, 5, 5)]
    assert ts[0]["state"] == "COMPLETED" and ts[1]["instruction"] == "Now batch two."
    assert ts[0]["step"] == 4 and ts[1]["step"] == 1
    c = TestClient(create_app())
    r = c.get("/p/pl")
    assert r.status_code == 200 and 'id="snapshot"' in r.text and "New task" in r.text
    assert 'class="on" aria-current="page">Overview' in r.text
    assert "task 1" in r.text and "task 2" in r.text and "Tasks</dt><dd>2" in r.text
    r = c.get("/p/pl/tasks")
    assert r.status_code == 200 and "Now batch two." in r.text and 'id="task-2"' in r.text
    assert 'id="task-1"' not in c.get("/p/pl/tasks?state=RUNNING").text
    r = c.get("/p/pl/steps")
    assert r.status_code == 200 and "5 steps" in r.text
    r = c.get("/p/pl/steps?task=2")
    assert "1 step<" in r.text and 'href="/p/pl/%s/0005"' % pkt.wpid in r.text
    assert 'href="/p/pl/%s/0001"' % pkt.wpid not in r.text
    assert "5 steps" in c.get("/p/pl/steps?task=nope&page=x").text
    assert c.get("/p/pl/cost").status_code == 200
    # Each task has a page with its own report, the one the step that finished it wrote.
    assert (ts[0]["report"], ts[1]["report"]) == ("steps/0004/report.md", "steps/0005/report.md")
    assert (ts[0]["report_step"], ts[1]["report_step"]) == ("0004", "0005")
    assert 'href="/p/pl/tasks/1"' in c.get("/p/pl/tasks").text
    one, two = c.get("/p/pl/tasks/1"), c.get("/p/pl/tasks/2")
    assert one.status_code == two.status_code == 200
    assert 'id="report"' in one.text and "written by" in one.text and "task 2 →" in one.text
    assert 'href="/p/pl/%s/0001"' % pkt.wpid in one.text
    assert 'href="/p/pl/%s/0005"' % pkt.wpid not in one.text
    assert 'id="report"' in two.text and "Now batch two." in two.text and "← task 1" in two.text
    assert data.task(e, ts, 1)["report"]["outcome"]
    for bad in ("3", "0", "x"):
        assert c.get("/p/pl/tasks/" + bad).status_code == 404, bad
    r = c.get("/p/pl/settings")
    assert r.status_code == 200 and "Scheduling" in r.text and "Permissions" in r.text
    r = c.post("/p/pl/settings", data={"action": "set", "key": "step_timeout", "value": "45m"},
               follow_redirects=False)
    assert r.headers["location"].startswith("/p/pl/settings?")
    assert c.get("/p/nope/steps").status_code == 404
