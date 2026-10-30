"""The studio's agent (docs/studio-plan.md P0.3): a console conversation in
``studio`` mode, which writes, with a step's command line, for whoever has
taken the packet."""

import json
import os

import pytest

from test_dash_tasks import _new
from work_packet import executor, layout, registry
from work_packet.dash import agent as agentmod
from work_packet.dash.agent import Agents, NotTaken


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


@pytest.fixture
def studio(tmp_path, fake, monkeypatch):
    """(entry, packet, Agents, studio conversation, argv log) for project ``a``."""
    fake("studio")
    argv = tmp_path / "argv.jsonl"
    monkeypatch.setenv("WPK_FAKE_ARGV", str(argv))
    e, pkt = _new("a")
    e = registry.get("a")
    ag = Agents(os.environ["WPK_HOME"])
    scope = {"kind": "packet", "project": "a", "wpid": pkt.wpid}
    cwd = agentmod.studio_place(e, pkt.wpid)
    meta = ag.new(scope, cwd, "matt", model=pkt.load_status()[0]["model"],
                  project_dir=e["path"], mode="studio")
    return e, pkt, ag, meta, argv


def _argvs(argv):
    return [json.loads(ln) for ln in argv.read_text().splitlines()]


def _flag(a, name):
    return a[a.index(name) + 1]


def test_refused_unless_taken_by_the_asker(studio):
    e, pkt, ag, meta, argv = studio
    with pytest.raises(NotTaken, match="not taken"):
        ag.ask(meta["id"], "hello", "matt", "primer")
    executor.take(pkt, by="sam")
    with pytest.raises(NotTaken, match="taken by sam"):
        ag.ask(meta["id"], "hello", "matt", "primer")
    assert not ag.busy(meta["id"]) and not argv.exists()


def test_a_turn_writes_in_the_packet_folder(studio):
    e, pkt, ag, meta, argv = studio
    executor.take(pkt, by="matt")
    cid = meta["id"]
    ag.ask(cid, "write docs/findings.md\nwrite charts/a.vl.json", "matt", "the primer")
    ag.wait(cid)
    folder = layout.packet_folder(e["path"])
    assert meta["cwd"] == folder
    assert open(os.path.join(folder, "docs", "findings.md")).read().startswith("# docs/")
    assert os.path.isfile(os.path.join(folder, "charts", "a.vl.json"))
    tools = [x for x in ag.transcript(cid) if x["k"] == "tool"]
    assert [(t["name"], t["what"]) for t in tools] == [
        ("Write", "docs/findings.md"), ("Write", "charts/a.vl.json")]
    end = [x for x in ag.transcript(cid) if x["k"] == "end"][-1]
    assert end["ok"] and end["cost"] > 0
    m = ag.get(cid)
    assert m["turns"] == 1 and m["cost"] == end["cost"] and m["mode"] == "studio"


def test_the_command_line_is_a_steps(studio):
    e, pkt, ag, meta, argv = studio
    executor.take(pkt, by="matt")
    cid = meta["id"]
    ag.ask(cid, "first", "matt", "primer")
    ag.wait(cid)
    ag.ask(cid, "second", "matt", "primer")
    ag.wait(cid)
    first, second = _argvs(argv)
    assert _flag(first, "--session-id") == meta["session"]
    assert _flag(second, "--resume") == meta["session"] and "--fork-session" not in second
    assert "--session-id" not in second
    assert _flag(first, "--permission-mode") == "acceptEdits"
    tools = _flag(first, "--tools").split(",")
    assert {"Read", "Write", "Edit", "Glob", "Grep"} <= set(tools)
    assert _flag(first, "--model") == pkt.load_status()[0]["model"]
    hooks = json.loads(_flag(first, "--settings"))["hooks"]
    cmds = json.dumps(hooks)
    assert "pathhook.py" in cmds and "bghook.py" in cmds and "ctxhook.py" in cmds
    assert _flag(first, "--append-system-prompt-file").endswith("primer.md")


def test_console_mode_is_unchanged(tmp_path, fake, monkeypatch):
    fake("console")
    argv = tmp_path / "argv.jsonl"
    monkeypatch.setenv("WPK_FAKE_ARGV", str(argv))
    e, pkt = _new("a")
    ag = Agents(os.environ["WPK_HOME"])
    scope = {"kind": "packet", "project": "a", "wpid": pkt.wpid}
    meta = ag.new(scope, str(tmp_path), "matt", project_dir=registry.get("a")["path"])
    assert meta["mode"] == "console"
    ag.ask(meta["id"], "hi", "matt", "primer")       # not taken: the console does not care
    ag.wait(meta["id"])
    (a,) = _argvs(argv)
    assert _flag(a, "--permission-mode") == "dontAsk" and "Write" not in _flag(a, "--tools")


def test_the_runs_files_are_refused(studio):
    e, pkt, ag, meta, argv = studio
    executor.take(pkt, by="matt")
    status = os.path.join(pkt.path, "status.md")
    before = open(status).read()
    rel = os.path.relpath(status, meta["cwd"])
    ag.ask(meta["id"], "write %s\nwrite ok.md" % rel, "matt", "primer")
    ag.wait(meta["id"])
    assert open(status).read() == before
    assert os.path.isfile(os.path.join(meta["cwd"], "ok.md"))
    toml = os.path.join(e["path"], "project.toml")
    before = open(toml).read()
    ag.ask(meta["id"], "write %s" % os.path.relpath(toml, meta["cwd"]), "matt", "primer")
    ag.wait(meta["id"])
    assert open(toml).read() == before


def test_protected():
    assert agentmod.protected("/f/.work-packet") == "/f/.work-packet"
    assert agentmod.protected("/f/proj").split(os.pathsep) == ["/f/proj/packets",
                                                              "/f/proj/project.toml"]


def test_pathhook_protect_rules(tmp_path, monkeypatch):
    from work_packet import pathhook
    runs = tmp_path / "f" / ".work-packet"
    (runs / "packets" / "x" / "work").mkdir(parents=True)
    ev = lambda p: {"tool_name": "Write", "tool_input": {"file_path": str(p)},   # noqa: E731
                    "cwd": str(tmp_path / "f")}
    monkeypatch.setenv("WPK_PROTECT", str(runs))
    monkeypatch.setenv("WPK_PROTECT_ALLOW", str(tmp_path / "f"))   # the root's folder holds runs
    assert pathhook.blocked(ev(runs / "project.toml"))
    assert pathhook.blocked(ev(tmp_path / "f" / "docs" / "a.md")) is None
    monkeypatch.setenv("WPK_PROTECT_ALLOW", str(runs / "packets" / "x" / "work"))  # a child's
    assert pathhook.blocked(ev(runs / "packets" / "x" / "work" / "a.md")) is None
    assert pathhook.blocked(ev(runs / "packets" / "x" / "status.md"))
    monkeypatch.delenv("WPK_PROTECT_ALLOW")
    assert pathhook.blocked(ev(runs / "packets" / "x" / "work" / "a.md"))
