"""Packets made and handed off from a session (docs/agent-dispatch.md)."""

import json
import os
import re
import shlex
import signal
import socket
import subprocess

import pytest

from work_packet import (briefing, cli, deliver, ide, layout, prompt, registry, schema,
                         skills, starters)
from work_packet.packet import Packet

from test_setup import git, home, source                       # noqa: F401


@pytest.fixture(autouse=True)
def _outside(monkeypatch):
    """Not in a packet, not in a step, not in VS Code (unless a test says so)."""
    for k in ("WPK_WPID", "WPK_STEP", "VSCODE_IPC_HOOK_CLI"):
        monkeypatch.delenv(k, raising=False)


def _config(text):
    h = registry.home()
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "a") as fp:
        fp.write(text)


def _toml(name):
    from work_packet.tomlio import load_toml
    return load_toml(os.path.join(registry.get(name)["path"], "project.toml"))


# --- P0 -------------------------------------------------------------------------------

def test_every_skill_command_parses():
    """The commands the skills tell an agent to run are ones wpk takes (P0.1:
    `wpk next . -m` never was)."""
    parser = cli.build_parser()
    wpk = skills.command()[:-len(" checkpoint")]
    seen = 0
    for name, text in skills.texts().items():
        for m in re.finditer(r"(?:^|`)\s*" + re.escape(wpk) + r" ([^`\n]*)", text, re.M):
            line = m.group(1).split("<<")[0].replace("\\", "")
            args = shlex.split(line)
            try:
                parser.parse_args(args)
            except SystemExit:
                pytest.fail("%s: `wpk %s` does not parse" % (name, line))
            seen += 1
    assert seen >= 10


def test_poke(tmp_path, monkeypatch):
    from work_packet.sched import home_lease
    got = []
    old = signal.signal(signal.SIGUSR1, lambda *a: got.append(1))
    try:
        monkeypatch.setattr(home_lease, "runs_wpk", lambda pid: True)
        st = {"pid": os.getpid(), "runner": True, "host": socket.gethostname()}
        (tmp_path / "server.json").write_text(json.dumps(st))
        assert not home_lease.poke(str(tmp_path))       # an older wpkd: never signalled
        (tmp_path / "server.json").write_text(json.dumps(dict(st, poke="SIGUSR1")))
        assert home_lease.poke(str(tmp_path)) and got
        (tmp_path / "server.json").write_text(json.dumps(dict(st, poke="SIGUSR1",
                                                              host="elsewhere")))
        assert not home_lease.poke(str(tmp_path))
        assert not home_lease.poke(str(tmp_path / "none"))
    finally:
        signal.signal(signal.SIGUSR1, old)


def test_making_a_packet_installs_the_skills(home, tmp_path):
    dirs = skills.dirs()
    assert cli.main(["start", "folder", "name=a", "dir=%s" % tmp_path]) == 0
    assert all(os.path.isfile(os.path.join(d, "wpk-dispatch", "SKILL.md")) for d in dirs)
    for d in dirs:
        os.unlink(os.path.join(d, "wpk-dispatch", "SKILL.md"))
    _config("\n[skills]\ninstall = false\n")
    assert cli.main(["start", "folder", "name=b", "dir=%s" % tmp_path]) == 0
    assert not any(os.path.isfile(os.path.join(d, "wpk-dispatch", "SKILL.md")) for d in dirs)


# --- D1: where packets go ---------------------------------------------------------------

def test_packet_directories(home, tmp_path):
    assert registry.packet_dir("main", "x") is None             # nothing set: as before
    registry.new_board("dv")
    _config('\n[packets]\nroot = "%s"\n' % (tmp_path / "pk"))
    assert registry.packet_dir("dv", "x") == str(tmp_path / "pk" / "dv" / "x")
    assert registry.packet_dir(None, "x") == str(tmp_path / "pk" / "main" / "x")
    assert starters.folder_of({"name": "x", "board": "dv"}) == str(tmp_path / "pk" / "dv" / "x")
    assert starters.folder_of({"name": "x", "board": "dv", "dir": "/d"}) == "/d/x"
    p = os.path.join(registry.boards_dir(), "dv.toml")
    with open(p, "a") as fp:
        fp.write("# mine\n\n[[watch]]\nname = \"w\"\nrepos = [\"home:o/r\"]\n")
    assert registry.set_board("dv", {"dir": str(tmp_path / "dvwork")}) == ["dir"]
    text = open(p).read()
    assert "# mine" in text and "[[watch]]" in text            # the rest stays as it was
    assert registry.board("dv")["dir"] == str(tmp_path / "dvwork")
    assert registry.packet_dir("dv", "x") == str(tmp_path / "dvwork" / "x")
    assert cli.main(["board", "set", "dv", "dir="]) == 0
    assert "dir" not in registry.board("dv")
    with pytest.raises(registry.BoardError):
        registry.set_board("dv", {"watch": "x"})
    assert cli.main(["start", "folder", "name=made", "board=dv"]) == 0
    assert os.path.isdir(tmp_path / "pk" / "dv" / "made")
    assert registry.get("made")["board"] == "dv"
    _config('layout = "flat"\n')
    assert registry.packet_dir("dv", "x") == str(tmp_path / "pk" / "x")


def test_no_nesting_from_inside_a_packet(home, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WPK_WPID", "0" * 8)
    assert cli.main(["start", "folder", "name=n"]) == 4
    assert "nest" in capsys.readouterr().err
    assert cli.main(["start", "folder", "name=n", "dir=%s" % tmp_path]) == 0
    monkeypatch.setenv("WPK_STEP", "3")
    assert cli.main(["start", "folder", "name=m", "dir=%s" % tmp_path]) == 4
    assert "runner step" in capsys.readouterr().err


# --- D2/D3: notes and repos ----------------------------------------------------------------

def test_repos_and_context(home, source, tmp_path, capsys):
    registry.new_board("vl")
    _config('\n[[repo]]\nname = "dvs"\nurl = "%s"\naliases = ["my dv fork"]\n'
            'branch_prefix = "mb/"\nnotes = "Run make test."\n' % source)
    with open(os.path.join(registry.boards_dir(), "vl.toml"), "a") as fp:
        fp.write('\n[[repo]]\nname = "dvs"\nurl = "%s"\nref = "main"\n' % source)
    assert [r["scope"] for r in registry.repos("vl")] == ["board"]
    assert registry.repo("My DV fork")["name"] == "dvs"           # an alias, any case
    with open(registry.notes_path(None), "w") as fp:
        fp.write("I review everything.\n")
    with open(registry.notes_path("vl"), "w") as fp:
        fp.write("Verilator: build with ./ci/build.sh\n")
    assert cli.main(["context", "--board", "vl"]) == 0
    out = capsys.readouterr().out
    assert "I review everything." in out and "./ci/build.sh" in out and "@dvs" in out
    assert cli.main(["repos", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["aliases"] == ["my dv fork"]
    assert cli.main(["start", "clone", "clone=@dvs", "name=t1", "dir=%s" % tmp_path,
                     "--dry-run", "--json"]) == 0
    r = json.loads(capsys.readouterr().out)["recipe"]
    assert r["clone"]["branch"] == "mb/t1" and r["origin"]["registry"] == "dvs"
    assert cli.main(["start", "clone", "clone=@dvs", "name=t1", "board=vl", "branch=b1",
                     "dir=%s" % tmp_path, "--dry-run", "--json"]) == 0
    r = json.loads(capsys.readouterr().out)["recipe"]
    assert r["clone"] == {"url": str(source), "ref": "main", "branch": "b1"}
    assert cli.main(["start", "clone", "clone=@nope", "name=t2"]) == 4
    assert "no [[repo]] named nope; there are: dvs" in capsys.readouterr().err


def test_notes_reach_steps_and_sessions(home, tmp_path):
    registry.new_board("vl")
    assert cli.main(["start", "folder", "name=a", "dir=%s" % tmp_path, "board=vl"]) == 0
    e = registry.get("a")
    with open(registry.notes_path("vl"), "w") as fp:
        fp.write("Board rule.\n")
    with open(registry.notes_path(None), "w") as fp:
        fp.write("x" * 5000)
    from work_packet import executor
    got = dict(executor._wider_notes(e["path"]))
    assert got["Board notes (vl)"] == "Board rule.\n" and len(got["Your notes"]) == 5000
    text = prompt.capped(got["Your notes"])
    assert len(text) < 4200 and "wpk context" in text
    ctx = briefing.dispatch_context(e["path"])
    assert "Board rule." in ctx and "Your notes for agents: 1 lines" in ctx


# --- B1: batches -------------------------------------------------------------------------

def test_batch_is_all_or_nothing(home, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "list.md").write_text("t1\nt2\n")
    assert cli.main(["start", "folder", "name=taken", "dir=%s" % tmp_path]) == 0
    capsys.readouterr()
    items = [{"starter": "folder", "name": "a", "dir": str(tmp_path), "objective": "Do A.",
              "inputs": [{"name": "slice.md", "text": "t1\n"}, "list.md"]},
             {"starter": "folder", "name": "taken", "dir": str(tmp_path / "x"),
              "objective": "Do B."}]
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(items)))
    assert cli.main(["start", "--recipes", "-", "--go"]) == 4
    err = capsys.readouterr().err
    assert "refused: taken" in err and "nothing was made" in err
    assert registry.get("a") is None
    items[1]["name"] = "b"
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(items)))
    assert cli.main(["start", "--recipes", "-", "--go", "--json"]) == 0
    made = json.loads(capsys.readouterr().out)
    assert [m["name"] for m in made] == ["a", "b"]
    assert all(m["state"] == "runnable" for m in made)
    oa, ob = _toml("a")["origin"], _toml("b")["origin"]
    assert oa["by"] == "user" and oa["batch"] == ob["batch"] and oa["batch"].startswith("b-")
    e = registry.get("a")
    st = Packet(layout.run_dir(e["path"], e["root"])).state_dir
    assert open(os.path.join(st, "list.md")).read() == "t1\nt2\n"
    assert open(os.path.join(st, "slice.md")).read() == "t1\n"
    _config("\n[dispatch]\nmax_batch = 1\n")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(items)))
    assert cli.main(["start", "--recipes", "-"]) == 4
    assert "max_batch is 1" in capsys.readouterr().err


def test_batch_records_the_dispatcher(home, tmp_path, monkeypatch, capsys):
    assert cli.main(["start", "folder", "name=boss", "dir=%s" % tmp_path]) == 0
    e = registry.get("boss")
    monkeypatch.setenv("WPK_WPID", e["root"])
    items = [{"starter": "folder", "name": n, "dir": str(tmp_path)} for n in ("c", "d")]
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(items)))
    assert cli.main(["start", "--recipes", "-"]) == 0
    assert _toml("c")["origin"]["by"] == "packet:" + e["root"]
    recs = [json.loads(ln) for ln in open(Packet(layout.run_dir(e["path"], e["root"]))
                                          .journal_path)]
    d = [r for r in recs if r["type"] == "dispatched"]
    assert d and d[0]["made"] == ["c", "d"] and not schema.validate_journal_record(d[0])
    from work_packet.dash import data
    assert data.origin(registry.get("c"))["by"]["project"] == "boss"


# --- B3: delivery ------------------------------------------------------------------------

@pytest.fixture
def remote(source, tmp_path):
    r = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(r)], check=True)
    return r


def _complete(monkeypatch):
    from work_packet import pr
    monkeypatch.setattr(pr, "state", lambda e: "COMPLETED")


def test_delivery(home, remote, tmp_path, monkeypatch, capsys):
    _config('\nclone_tool = "git"\n')
    assert cli.main(["start", "clone", "clone=%s" % remote, "name=p", "ref=main",
                     "dir=%s" % tmp_path, "deliver=push"]) == 4
    assert "needs a branch of its own" in capsys.readouterr().err
    assert cli.main(["start", "clone", "clone=%s" % remote, "name=p", "branch=mb/p",
                     "ref=main", "dir=%s" % tmp_path, "deliver=push", "--dry-run"]) == 0
    assert "on completion: push mb/p to origin" in capsys.readouterr().out
    assert cli.main(["start", "clone", "clone=%s" % remote, "name=p", "branch=mb/p",
                     "ref=main", "dir=%s" % tmp_path, "deliver=push"]) == 0
    e = registry.get("p")
    assert _toml("p")["deliver"] == {"do": "push", "base": "main"}
    assert deliver.badge(e)["text"] == "Will push on completion"
    assert not deliver.due(e)                       # not completed
    _complete(monkeypatch)
    folder = layout.packet_folder(e["path"])
    assert deliver.sync() == 1                      # nothing beyond main: refused, recorded
    assert "nothing to push" in deliver.last(e)["msg"]
    assert deliver.sync() == 0                      # the same HEAD is not tried again
    (tmp_path / "p" / "t.txt").write_text("x\n")
    git(folder, "add", "t.txt")
    git(folder, "commit", "-q", "-m", "t")
    assert deliver.sync() == 1
    assert git(remote, "rev-parse", "mb/p") == git(folder, "rev-parse", "HEAD")
    rec = deliver.last(e)
    assert rec["ok"] == 1 and rec["msg"] == "pushed mb/p (1 commit) to origin"
    recs = [json.loads(ln) for ln in open(Packet(layout.run_dir(e["path"], e["root"]))
                                          .journal_path)]
    dl = [r for r in recs if r["type"] == "deliver"]
    assert len(dl) == 2 and not schema.validate_journal_record(dl[-1])
    assert deliver.sync() == 0
    # A gate that fails holds it; it is not tried again until HEAD moves or --now.
    assert cli.main(["deliver", "p", "--set", "push", "--gate", "exit 3"]) == 0
    (tmp_path / "p" / "u.txt").write_text("y\n")
    git(folder, "add", "u.txt")
    git(folder, "commit", "-q", "-m", "u")
    assert deliver.sync() == 1
    assert deliver.last(e)["msg"].startswith("Delivery held: gate `exit 3` failed (exit 3)")
    assert git(remote, "rev-parse", "mb/p") != git(folder, "rev-parse", "HEAD")
    assert cli.main(["deliver", "p", "--off"]) == 0
    assert deliver.policy(e) is None and not deliver.due(e)


def test_delivery_never_pushes_the_base(home, remote, tmp_path, monkeypatch):
    _config('\nclone_tool = "git"\n')
    assert cli.main(["start", "clone", "clone=%s" % remote, "name=q", "dir=%s" % tmp_path]) == 0
    e = registry.get("q")
    assert cli.main(["deliver", "q", "--set", "push"]) == 0
    _complete(monkeypatch)
    folder = layout.packet_folder(e["path"])
    (tmp_path / "q" / "t.txt").write_text("x\n")
    git(folder, "add", "t.txt")
    git(folder, "commit", "-q", "-m", "t")
    deliver.sync()
    assert "the base branch: it is never pushed" in deliver.last(e)["msg"]


def test_pr_delivery_needs_a_forge(home, tmp_path, capsys):
    git_dir = tmp_path / "g"
    git_dir.mkdir()
    git(git_dir, "init", "-q")
    assert cli.main(["start", "folder", "name=g", "folder=%s" % git_dir, "deliver=pr",
                     "--dry-run"]) == 4
    assert "needs a repo on a configured forge" in capsys.readouterr().err


# --- I2/I3: a packet opened for you ------------------------------------------------------

def test_open_leaves_a_kickoff(home, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ide, "ssh_host", lambda *a, **k: None)
    (tmp_path / "t_issue.v").write_text("module t; endmodule\n")
    assert cli.main(["start", "folder", "name=vl", "dir=%s" % tmp_path,
                     "objective=Investigate the testcase.", "inputs=%s" % (tmp_path / "t_issue.v"),
                     "--open", "ide-desktop", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    e = registry.get("vl")
    ws = os.path.join(e["path"], ide.KICKOFF_WS)
    assert out["open_url"] == "vscode://file" + ws and out["kickoff"] and out["state"] == "held"
    task = ide.parse_jsonc(open(ws).read())["tasks"]["tasks"][0]
    assert task["runOptions"] == {"runOn": "folderOpen"} and "kickoff " + e["root"] in \
        task["command"]
    text = open(ide.kickoff_path(e["path"])).read()
    assert "Investigate the testcase." in text and "- t_issue.v" in text
    ctx = briefing.dispatch_context(e["path"], e["root"])      # the first session takes it
    assert "Investigate the testcase." in ctx
    assert "Investigate" not in briefing.dispatch_context(e["path"], e["root"])
    assert cli.main(["kickoff", e["root"], "--print"]) == 0
    assert "No kickoff waiting" in capsys.readouterr().out


def test_kickoff_runs_once(home, tmp_path, capsys):
    assert cli.main(["start", "folder", "name=k", "dir=%s" % tmp_path, "objective=Look.",
                     "--open", "ide-desktop"]) == 0
    e = registry.get("k")
    capsys.readouterr()
    assert cli.main(["kickoff", "k", "--print"]) == 0
    assert capsys.readouterr().out.startswith("Look.")
    assert os.path.isfile(os.path.join(e["path"], ide.KICKOFF_DONE))
    assert cli.main(["kickoff", "k", "--print"]) == 0
    assert "No kickoff waiting" in capsys.readouterr().out


def test_allow_automatic_tasks(tmp_path):
    assert ide.allow_automatic_tasks(str(tmp_path))
    p = tmp_path / "ide" / "data" / "data" / "Machine" / "settings.json"
    assert json.loads(p.read_text()) == {"task.allowAutomaticTasks": "on"}
    p.write_text('{"task.allowAutomaticTasks": "off"}')
    assert not ide.allow_automatic_tasks(str(tmp_path))       # yours stays
