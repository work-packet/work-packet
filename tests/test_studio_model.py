"""The studio's logic (docs/studio-plan.md S1.1-S1.3, S1.8): kinds, the watcher,
open/close with the canvas, and the session recorded as one step."""

import json
import os
import subprocess

import pytest

from test_dash_tasks import _new
from work_packet import layout, registry
from work_packet.dash.agent import Agents
from work_packet.studio import kinds, model, record, watch


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


# --- kinds -----------------------------------------------------------------------

def test_kinds():
    assert kinds.kind_of("docs/findings.md").name == "document"
    assert kinds.kind_of("README.MD").name == "document"
    assert kinds.kind_of("a/b/plot.PNG").name == "image"
    assert kinds.kind_of("x.svg").name == "image"
    assert kinds.kind_of("data.csv").name == "table" and kinds.kind_of("Makefile") is None
    assert kinds.kind_of("c/flaky.vl.json").name == "chart" and kinds.kind_of("x.json") is None
    assert kinds.get("document").anchor == "text" and kinds.get("nope") is None
    with pytest.raises(ValueError):
        kinds.register(kinds.Kind("document", ("*.md",), viewer="doc"))


def test_kinds_order(monkeypatch):
    monkeypatch.setattr(kinds, "REGISTRY", [])
    kinds.register(kinds.Kind("json", ("*.json",), viewer="text"))
    kinds.register(kinds.Kind("chart", ("*.vl.json",), viewer="chart"), before="json")
    assert kinds.kind_of("c.vl.json").name == "chart" and kinds.kind_of("c.json").name == "json"


# --- the watcher -------------------------------------------------------------------

def test_watcher(tmp_path):
    root = tmp_path / "f"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("a")
    (root / "keep.md").write_text("k")
    (root / ".work-packet").mkdir()
    (root / ".work-packet" / "x").write_text("x")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "y.js").write_text("y")
    now = [100.0]
    w = watch.Watcher(str(root), clock=lambda: now[0])
    assert set(w.stats) == {"docs/a.md", "keep.md"}
    assert w.poll() == []
    w.agent_wrote(str(root / "docs" / "b.md"))
    (root / "docs" / "b.md").write_text("b")                      # created, by the agent
    w.saved("docs/a.md")
    (root / "docs" / "a.md").write_text("a2")                     # modified, by you
    os.utime(root / "keep.md", ns=(1, 1))                         # touched only
    (root / ".work-packet" / "x").write_text("x2")                # not watched
    got = {c["path"]: c for c in w.poll()}
    assert set(got) == {"docs/a.md", "docs/b.md"}
    assert got["docs/b.md"]["change"] == "created" and got["docs/b.md"]["by"] == "agent"
    assert got["docs/a.md"]["change"] == "modified" and got["docs/a.md"]["by"] == "you"
    os.rename(root / "docs" / "b.md", root / "docs" / "c.md")     # renamed, outside
    now[0] += 60                                                  # the marks are old now
    (root / "keep.md").unlink()
    got = w.poll()
    assert {"path": "docs/c.md", "change": "renamed", "from": "docs/b.md", "by": "outside",
            "sha": got[0]["sha"]} in got
    assert {"path": "keep.md", "change": "deleted", "by": "outside"} in got
    assert watch.diff({"a": 1, "b": 2}, {"b": 3, "c": 4}) == (["c"], ["b"], ["a"])


def test_watch_a_mark_explains_one_change(tmp_path):
    """The person edits a file seconds after the agent did: theirs is outside
    (seen in the S1 exit check with the real model)."""
    (tmp_path / "f.md").write_text("a")
    now = [100.0]
    w = watch.Watcher(str(tmp_path), clock=lambda: now[0])
    w.agent_wrote("f.md")
    (tmp_path / "f.md").write_text("agent's")
    assert w.poll()[0]["by"] == "agent"
    now[0] += 2                                                   # inside the window
    (tmp_path / "f.md").write_text("mine, from VS Code")
    assert w.poll()[0]["by"] == "outside"
    w.saved("f.md")
    w.forget("f.md")                                              # the save failed
    (tmp_path / "f.md").write_text("mine again")
    assert w.poll()[0]["by"] == "outside"


# --- the studio ----------------------------------------------------------------------

def _open(e, pkt, user="matt", conv=None):
    return model.open_studio(e, pkt.wpid, user, conv=conv)


def test_open_close_round_trip(tmp_path, fake):
    e, pkt = _new("a")
    e = registry.get("a")
    root = layout.packet_folder(e["path"])
    st = _open(e, pkt)
    assert st["open"] and st["taken_by"] == "matt" and st["folder"] == root
    assert pkt.load_status()[0]["reason"] == "studio"
    assert os.path.isfile(os.path.join(root, ".studio", "studio.json"))
    assert _open(e, pkt)["open"]                                    # return to it
    with pytest.raises(model.StudioError, match="matt's studio"):
        _open(e, pkt, user="sam")
    (tmp_path / "doc.md").write_text("# x\n")
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    with open(os.path.join(root, "docs", "f.md"), "w") as fp:
        fp.write("# Findings\n")
    model.pin(e, pkt.wpid, "docs/f.md", "matt")
    with pytest.raises(model.StudioError):
        model.pin(e, pkt.wpid, "../doc.md", "matt")
    with pytest.raises(model.StudioError):
        model.pin(e, pkt.wpid, "nope.md", "matt")
    assert model.changed(e, pkt.wpid) == (["docs/f.md"], [], [])
    with pytest.raises(model.StudioError, match="only they"):
        model.close_studio(e, pkt.wpid, "sam")
    out = model.close_studio(e, pkt.wpid, "matt", summary="Wrote the findings.")
    assert out["recorded"] == 1
    meta, body = pkt.load_status()
    assert meta["state"] == "RUNNABLE" and "taken_by" not in meta
    assert body.strip() == "Wrote the findings."
    m = json.load(open(os.path.join(pkt.step_dir(1), "meta.json")))
    assert m["worker"] == "studio" and m["studio"]["created"] == ["docs/f.md"]
    assert model.close_studio(e, pkt.wpid, "matt")["recorded"] is None   # twice: no-op
    # Reopening keeps the canvas.
    st = _open(e, pkt)
    assert [a["path"] for a in st["canvas"]] == ["docs/f.md"]
    assert st["canvas"][0]["kind"] == "document" and st["layout"]["open"] == ["docs/f.md"]
    assert len(st["sessions"]) == 1 and st["sessions"][0]["step"] == 1


def test_a_session_that_did_nothing_records_nothing(tmp_path, fake):
    e, pkt = _new("a")
    e = registry.get("a")
    _open(e, pkt)
    out = model.close_studio(e, pkt.wpid, "matt", how="hold")
    assert out["recorded"] is None and pkt.load_status()[0]["reason"] == "held"
    assert pkt.load_status()[0]["step"] == 0


def test_layout_and_unpin(tmp_path, fake):
    e, pkt = _new("a")
    e = registry.get("a")
    root = layout.packet_folder(e["path"])
    _open(e, pkt)
    for n in ("a.md", "b.md", "c.png"):
        open(os.path.join(root, n), "w").write("x")
        model.pin(e, pkt.wpid, n, "matt")
    assert model.state(e, pkt.wpid)["layout"]["open"] == ["c.png"]           # tabs: one
    d = model.set_layout(e, pkt.wpid, mode="two-up", open_paths=["a.md", "b.md"])
    assert d["layout"] == {"mode": "two-up", "open": ["a.md", "b.md"]}
    with pytest.raises(model.StudioError):
        model.set_layout(e, pkt.wpid, mode="grid")
    with pytest.raises(model.StudioError):
        model.set_layout(e, pkt.wpid, open_paths=["zzz.md"])
    d = model.unpin(e, pkt.wpid, "a.md")
    assert [a["path"] for a in d["canvas"]] == ["b.md", "c.png"] and d["layout"]["open"] == ["b.md"]


def test_git_exclude(tmp_path, fake):
    e, pkt = _new("a")
    e = registry.get("a")
    root = layout.packet_folder(e["path"])
    subprocess.run(["git", "init", "-q", root], check=True)
    _open(e, pkt)
    ex = open(os.path.join(root, ".git", "info", "exclude")).read()
    assert "\n/.studio/\n" in ex
    open(os.path.join(root, ".studio", "probe"), "w").write("x")
    st = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=all"],
                        capture_output=True, text=True).stdout
    assert ".studio" not in st
    model.close_studio(e, pkt.wpid, "matt")
    _open(e, pkt)
    assert open(os.path.join(root, ".git", "info", "exclude")).read().count("/.studio/") == 1


def test_a_child_without_work_has_no_studio(tmp_path, fake):
    e, pkt = _new("a")
    e = dict(registry.get("a"), root="not-this-one")
    with pytest.raises(model.StudioError, match="no work/"):
        model.folder(e, pkt.wpid)


def test_a_session_with_turns_is_recorded_with_its_cost(tmp_path, fake):
    fake("studio")
    e, pkt = _new("a")
    e = registry.get("a")
    ag = Agents(os.environ["WPK_HOME"])
    from work_packet.dash import agent as agentmod
    scope = {"kind": "packet", "project": "a", "wpid": pkt.wpid}
    conv = ag.new(scope, agentmod.studio_place(e, pkt.wpid), "matt",
                  model="haiku", project_dir=e["path"], mode="studio")
    _open(e, pkt, conv=conv["id"])
    ag.ask(conv["id"], "write docs/one.md", "matt", "primer")
    ag.wait(conv["id"])
    ag.ask(conv["id"], "write docs/two.md", "matt", "primer")
    ag.wait(conv["id"])
    s = model.state(e, pkt.wpid)["session"]
    text, how = record.draft_summary(e, pkt.wpid, s)
    assert how == "model" and text        # the fake answers any prompt
    out = model.close_studio(e, pkt.wpid, "matt")
    n = out["recorded"]
    sd = pkt.step_dir(n)
    m = json.load(open(os.path.join(sd, "meta.json")))
    assert m["cost_usd"] == ag.get(conv["id"])["cost"] > 0
    assert m["studio"]["turns"] == 2 and m["studio"]["created"] == ["docs/one.md", "docs/two.md"]
    assert m["tokens"]["output_tokens"] > 0 and m["session_id"] == conv["session"]
    assert os.path.isfile(os.path.join(sd, "transcript.jsonl"))
    assert os.path.isfile(os.path.join(sd, "studio-transcript.jsonl"))
    body = pkt.load_status()[1]
    assert "Studio session by matt" in body and "write docs/one.md" in body
    assert "Created docs/one.md, docs/two.md." in body
    from work_packet import stats
    assert stats.packet_steps("a", pkt)[-1].worker == "studio"


def test_plain_summary_without_a_model(tmp_path, fake, monkeypatch):
    e, pkt = _new("a")
    e = registry.get("a")
    _open(e, pkt)
    s = model.state(e, pkt.wpid)["session"]
    text, how = record.draft_summary(e, pkt.wpid, s)        # no conversation: facts
    assert how == "facts" and "No files changed." in text
    f = {"minutes": 1, "turns": 1, "asks": ["x" * 300], "created": ["a"] * 10,
         "modified": [], "deleted": ["d"]}
    t = record.plain_summary(f, "matt")
    assert "1 minute, 1 turn." in t and "…" in t and "and 2 more" in t and "Deleted d." in t


def test_cli(tmp_path, fake):
    import sys
    e, pkt = _new("a")
    root = layout.packet_folder(registry.get("a")["path"])

    def wpk(*a):
        return subprocess.run([sys.executable, "-m", "work_packet", *a],
                              capture_output=True, text=True)
    r = wpk("studio", "open", pkt.wpid)
    assert r.returncode == 0 and "studio open on" in r.stdout and "/studio" in r.stdout, r.stderr
    assert pkt.load_status()[0]["reason"] == "studio"
    open(os.path.join(root, "x.md"), "w").write("x")
    r = wpk("studio", "status", pkt.wpid)
    assert "open:    yes" in r.stdout and "taken:   " in r.stdout
    r = wpk("studio", "close", "--hold", "--summary", "By hand.", pkt.wpid)
    assert r.returncode == 0 and "step 1 recorded" in r.stderr, r.stderr
    meta, body = pkt.load_status()
    assert meta["reason"] == "held" and body.strip() == "By hand."
