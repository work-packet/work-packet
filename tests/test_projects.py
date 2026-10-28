import json
import os
import signal
import subprocess
import sys

import pytest

from conftest import NOW
from work_packet import executor, project, registry, schema, views
from work_packet.check import check
from work_packet.cli import main
from work_packet.packet import Packet


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return os.environ["WPK_HOME"]


def new(name="demo", **kw):
    kw.setdefault("prompt", "Read state/count.md (0 if missing), add one.")
    return project.new(name, **kw)


def root_of(plan):
    return Packet(os.path.join(plan.path, "packets", plan.root))


def test_new_creates_valid_registered_project(home, tmp_path):
    plan = new(tz="Europe/London")
    assert plan.path == str(tmp_path / "demo")
    e = registry.get("demo")
    assert (e["path"], e["root"], e["template"], e["created"]) == \
        (plan.path, plan.root, "blank@1", NOW)
    pkt = root_of(plan)
    meta, body = pkt.load_status()
    assert (meta["state"], meta["step"], meta["model"]) == \
        ("RUNNABLE", 0, schema.CONFIG_DEFAULTS["model"])
    assert open(pkt.memento_path).read() == "Read state/count.md (0 if missing), add one.\n"
    assert open(os.path.join(plan.path, "prompt.md")).read() == open(pkt.memento_path).read()
    assert check(plan.path).issues == []
    assert check(home).issues == []
    assert not [n for n in os.listdir(tmp_path) if n.startswith(".")]


def test_new_paused_and_model(home):
    plan = new(paused=True, model="claude-sonnet-5")
    meta, _ = root_of(plan).load_status()
    assert (meta["state"], meta["reason"], meta["model"]) == \
        ("PAUSED", "created with --paused", "claude-sonnet-5")
    from work_packet.tomlio import load_toml
    assert load_toml(os.path.join(plan.path, "project.toml"))["model"] == "claude-sonnet-5"
    assert check(plan.path).issues == []


def test_dry_run_writes_nothing(home, tmp_path):
    before = sorted(os.listdir(tmp_path))
    plan = new(dry_run=True)
    assert "project.toml" in plan.files
    assert sorted(os.listdir(tmp_path)) == before
    assert registry.entries() == []


@pytest.mark.parametrize("kw,msg", [
    ({"name": "Bad Name"}, "must match"),
    ({"tz": "Mars/Olympus"}, "unknown time zone"),
    ({"prompt": "  "}, "prompt is empty"),
])
def test_new_rejects(home, kw, msg):
    with pytest.raises(project.ProjectError, match=msg):
        new(**kw)
    assert registry.entries() == []


def test_name_clash_and_nonempty_dir(home, tmp_path):
    new()
    with pytest.raises(project.ProjectError, match="already registered"):
        new(path=str(tmp_path / "other"))
    os.makedirs(tmp_path / "full")
    (tmp_path / "full" / "x").write_text("x")
    with pytest.raises(project.ProjectError, match="not an empty directory"):
        new("two", path=str(tmp_path / "full"))
    os.makedirs(tmp_path / "empty")
    assert new("three", path=str(tmp_path / "empty")).path == str(tmp_path / "empty")


def _wpk(*args, **env):
    return subprocess.run([sys.executable, "-m", "work_packet"] + list(args),
                          env=dict(os.environ, **env), capture_output=True, text=True)


def test_e5_new_killed_before_rename(home, tmp_path):
    r = _wpk("new", "demo", "--prompt", "Count.", WPK_FAULT_AT="new-before-rename")
    assert r.returncode == -signal.SIGKILL
    assert registry.entries() == [] and not os.path.exists(tmp_path / "demo")
    r = _wpk("new", "demo", "--prompt", "Count.")
    assert r.returncode == 0, r.stderr
    assert registry.get("demo") is not None
    assert not [n for n in os.listdir(tmp_path) if n.startswith(".")]
    assert check(str(tmp_path / "demo")).issues == []


def test_e5_new_killed_before_register(home, tmp_path):
    r = _wpk("new", "demo", "--prompt", "Count.", WPK_FAULT_AT="new-before-register")
    assert r.returncode == -signal.SIGKILL
    assert registry.entries() == []
    r = _wpk("new", "demo", "--prompt", "Count.")
    assert r.returncode == 4 and "wpk adopt" in r.stderr
    assert _wpk("adopt", "demo").returncode == 0
    assert registry.get("demo")["path"] == str(tmp_path / "demo")


def test_adopt_and_rm(home, tmp_path):
    plan = new()
    assert main(["rm", "demo"]) == 0
    assert registry.entries() == [] and os.path.isdir(plan.path)
    assert main(["rm", "demo"]) == 4
    assert main(["adopt", plan.path]) == 0
    assert main(["adopt", plan.path]) == 4
    assert registry.get("demo")["root"] == plan.root


def test_lookup(home):
    a = new("aaa")
    b = new("bbb")
    pa = root_of(a).path
    assert registry.resolve("aaa") == pa
    assert registry.resolve(a.root) == pa
    assert registry.resolve(a.root[:8]) == pa
    assert registry.resolve(a.root[:8].upper()) == pa
    assert registry.resolve(a.path) == pa
    with pytest.raises(registry.LookupFailed, match="no packet"):
        registry.resolve("zzz")
    with pytest.raises(registry.LookupFailed, match="no packet"):
        registry.resolve(a.root[:3])                   # too short to be a prefix
    # Force an ambiguous prefix with a second packet sharing the first 4 characters.
    other = a.root[:4] + b.root[4:]
    os.rename(root_of(b).path, os.path.join(b.path, "packets", other))
    with pytest.raises(registry.LookupFailed, match="matches 2 packets"):
        registry.resolve(a.root[:4])


def test_step_by_name(home):
    plan = new()
    assert executor.step("demo").code == 0
    assert root_of(plan).load_status()[0]["step"] == 1


def _set(pkt, **kw):
    meta, body = pkt.load_status()
    meta.update(kw)
    pkt.save_status(meta, body)


def test_ps_each_state(home, capsys):
    plans = {}
    for name, change in [
        ("run", {}),
        ("sleep", {"state": "SLEEPING", "wake_at": "2026-10-31T18:00:00Z",
                   "resume_expr": "in 10 days"}),
        ("late", {"state": "SLEEPING", "wake_at": "2026-10-21T17:00:00Z",
                  "resume_expr": "in 1 hour"}),
        ("pause", {"state": "PAUSED", "reason": "by hand"}),
        ("fail", {"state": "FAILED", "reason": "no input"}),
        ("done", {"state": "COMPLETED"}),
    ]:
        plans[name] = new(name, tz="UTC")
        _set(root_of(plans[name]), **change)
    assert main(["ps"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["PROJECT", "WPID", "STATE", "STEP", "NEXT", "LAST", "SUMMARY"]
    rows = {line.split()[0]: line for line in out[1:]}
    assert set(rows) == {"run", "sleep", "late", "pause"}       # finished ones hidden
    assert "RUNNABLE" in rows["run"] and "due now" in rows["run"]
    assert "2026-10-31 18:00 (in 10d)" in rows["sleep"]
    assert "2026-10-21 17:00 (due)" in rows["late"]
    assert "PAUSED" in rows["pause"] and "[by hand]" in rows["pause"]
    assert plans["run"].root[:8] in rows["run"]
    main(["ps", "--all"])
    rows = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()[1:]}
    assert "[no input]" in rows["fail"] and "COMPLETED" in rows["done"]
    main(["ps", "--project", "sleep"])
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert main(["ps", "--project", "nope"]) == 4


def test_ps_shows_children_indented(home, capsys):
    plan = new()
    for _ in range(8):
        executor.step("demo")
    _set(root_of(plan), state="RUNNABLE")        # keep the project active
    lines = views.ps(registry.entries())
    assert len(lines) == 3 and "  " + lines[2].split()[1] in lines[2]
    assert lines[2].split()[2] == "RUNNABLE" and "step" not in lines[2]


def test_relative():
    assert views.relative(30) == "now"
    assert views.relative(90) == "in 1m"
    assert views.relative(3 * 86400 + 7200 + 60) == "in 3d 2h"
    assert views.relative(-3700) == "1h 1m ago"


def test_show_and_log(home, capsys):
    plan = new()
    executor.step("demo")
    executor.step("demo")
    assert main(["show", plan.root[:8]]) == 0
    out = capsys.readouterr().out
    assert "state:       RUNNABLE" in out and "## memento.md" in out and "Count is 2" in out
    assert main(["log", "demo"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["TIME", "TYPE", "STEP", "DETAIL"]
    assert [line.split()[1] for line in out[1:]] == ["step-start", "commit-begin",
                                                     "commit-end"] * 2
    assert "RUNNABLE (now)" in out[2] and "$0.0012" in out[3]
    assert main(["log", "demo", "--step", "2"]) == 0
    out = capsys.readouterr().out
    assert "## state.diff" in out and "+2" in out and '"exit_code": 0' in out
    assert main(["log", "demo", "--step", "9"]) == 4
    assert main(["show", "nope"]) == 4


def test_pause_and_resume(home, capsys):
    plan = new()
    pkt = root_of(plan)
    assert main(["pause", "demo"]) == 0
    meta, _ = pkt.load_status()
    assert (meta["state"], meta["reason"]) == ("PAUSED", "by hand")
    assert executor.step("demo").code == 2
    assert main(["pause", plan.root[:8]]) == 2               # already paused
    adm = [r for r in pkt.journal().records if r["type"] == "admin"]
    assert adm[0]["op"] == "pause" and "@" in adm[0]["by"]
    assert check(plan.path).issues == []
    assert main(["resume", "demo"]) == 0
    assert pkt.load_status()[0]["state"] == "RUNNABLE"
    assert executor.step("demo").code == 0
    assert check(plan.path).issues == []


def test_resume_failed_resets_attempts(home, fake):
    plan = new()
    fake(fault="crash")
    for _ in range(3):
        executor.step("demo")
    pkt = root_of(plan)
    assert pkt.load_status()[0]["state"] == "FAILED"
    assert main(["resume", plan.root]) == 0
    meta, _ = pkt.load_status()
    assert (meta["state"], meta["attempts"], meta["reason"]) == ("RUNNABLE", 0, None)
    fake(fault=None)
    assert executor.step("demo").code == 0


def test_pause_waits_for_lease(home):
    import socket
    plan = new()
    pkt = root_of(plan)
    with open(pkt.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 1,
                   "attempt": 1, "expires": "2999-01-01T00:00:00Z"}, fp)
    assert executor.admin(pkt, "pause").code == 3
    assert pkt.load_status()[0]["state"] == "RUNNABLE"


def test_cli_new_prints_permissions(home, capsys, tmp_path):
    (tmp_path / "p.md").write_text("Do it.\n")
    assert main(["new", "demo", "--prompt-file", str(tmp_path / "p.md"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Would create project demo" in out
    assert "--permission-mode acceptEdits --allowedTools Read,Write,Edit,Glob,Grep,Bash" in out
    assert main(["new", "demo", "--prompt", "Go."]) == 0
    assert "wpk tick" in capsys.readouterr().out
    assert main(["new", "held"]) == 0               # no prompt: held for setup
    assert "wpk setup held" in capsys.readouterr().out
