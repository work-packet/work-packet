"""The root packet filled from the project root when a step starts (docs/setup.md §10)."""

import os
import shutil
import subprocess

from work_packet import executor, project, workspace
from work_packet.check import check
from work_packet.packet import Packet

from test_setup import git, home, source                       # noqa: F401


def setup_root(tmp_path, source, name="dvs"):
    """A held project with everything at its root: prompt, state, identity, work."""
    plan = project.new(name)
    proj = plan.path
    open(os.path.join(proj, "prompt.md"), "w").write("Count in state/count.md.\n")
    os.makedirs(os.path.join(proj, "state", "notes"), exist_ok=True)
    open(os.path.join(proj, "state", "plan.md"), "w").write("# Plan\n")
    open(os.path.join(proj, "state", "notes", "a.md"), "w").write("a\n")
    os.makedirs(os.path.join(proj, "identity"), exist_ok=True)
    research = tmp_path / "research"
    research.mkdir()
    os.symlink(str(research), os.path.join(proj, "identity", "research"))
    os.makedirs(os.path.join(proj, "work", "data"), exist_ok=True)
    open(os.path.join(proj, "work", "data", "x.txt"), "w").write("x\n")
    subprocess.run(["git", "clone", "-q", str(source), os.path.join(proj, "work", "dv-solve")],
                   check=True)
    os.symlink(str(source / "packages"), os.path.join(proj, "work", "dv-solve", "packages"))
    pkt = Packet(plan.packet)
    assert executor.admin(pkt, "resume").code == 0
    return proj, pkt


def seeds(pkt):
    return [r for r in pkt.journal().records if r["type"] == "seed"]


def test_first_step_fills_the_root_packet(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    out = executor.step(proj)
    assert out.code == 0, out.msg
    # Seeded: state files and the instruction.
    assert open(os.path.join(pkt.state_dir, "plan.md")).read() == "# Plan\n"
    assert os.path.isfile(os.path.join(pkt.state_dir, "notes", "a.md"))
    prompt = open(os.path.join(pkt.step_dir(1), "prompt.md")).read()
    assert "Count in state/count.md." in prompt
    [rec] = seeds(pkt)
    assert rec["files"] == ["state/plan.md", "state/notes/a.md", "memento.md"]
    # identity/ is linked to the same target.
    assert os.path.realpath(os.path.join(pkt.identity_dir, "research")) == \
        str(tmp_path / "research")
    # A git repo becomes a worktree on wpk/<project>; the clone stays on main.
    tree = os.path.join(pkt.path, "work", "dv-solve")
    assert os.path.isfile(os.path.join(tree, ".git"))
    assert git(tree, "symbolic-ref", "--short", "HEAD") == "wpk/dvs"
    assert git(os.path.join(proj, "work", "dv-solve"), "symbolic-ref", "--short", "HEAD") == \
        "main"
    # ... with the clone's untracked link shared.
    assert os.path.realpath(os.path.join(tree, "packages")) == str(source / "packages")
    assert git(tree, "status", "--porcelain") == ""
    # Anything else is a relative link to the root.
    data = os.path.join(pkt.path, "work", "data")
    assert os.readlink(data) == os.path.join("..", "..", "..", "work", "data")
    assert open(os.path.join(data, "x.txt")).read() == "x\n"
    assert check(proj).issues == []


def test_later_steps_add_new_entries_and_never_seed_again(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0
    open(os.path.join(proj, "state", "late.md"), "w").write("late\n")
    os.makedirs(os.path.join(proj, "work", "more"), exist_ok=True)
    assert executor.step(proj).code == 0
    assert len(seeds(pkt)) == 1
    assert not os.path.exists(os.path.join(pkt.state_dir, "late.md"))
    assert os.path.islink(os.path.join(pkt.path, "work", "more"))


def test_branch_checked_out_in_the_clone_fails_the_attempt(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    git(os.path.join(proj, "work", "dv-solve"), "switch", "-q", "-c", "wpk/dvs")
    out = executor.step(proj)
    assert out.code == executor.FAILED
    assert "workspace: git worktree add" in out.msg
    meta, _ = pkt.load_status()
    assert (meta["state"], meta["attempts"], meta["step"]) == ("RUNNABLE", 1, 0)
    assert "already" in open(os.path.join(pkt.step_dir(1, 1), "stderr.log")).read()
    # Fixed by hand: the next attempt prepares and runs.
    git(os.path.join(proj, "work", "dv-solve"), "switch", "-q", "main")
    assert executor.step(proj).code == 0
    assert len(seeds(pkt)) == 1


def test_a_project_without_git_never_runs_git(home, tmp_path, monkeypatch):
    plan = project.new("plain")
    proj = plan.path
    open(os.path.join(proj, "prompt.md"), "w").write("Count.\n")
    os.makedirs(os.path.join(proj, "work", "data"), exist_ok=True)
    executor.admin(Packet(plan.packet), "resume")
    empty = tmp_path / "nobin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))              # no git to be found
    assert shutil.which("git") is None
    assert executor.step(proj).code == 0
    assert os.path.islink(os.path.join(plan.packet, "work", "data"))


def test_projects_made_with_a_prompt_are_unchanged(home):
    plan = project.new("old", prompt="Count.")
    assert executor.step(plan.path).code == 0
    pkt = Packet(plan.packet)
    assert seeds(pkt) == []
    assert not os.path.exists(os.path.join(pkt.path, "work"))


def test_a_packet_that_ran_before_is_never_seeded(home, tmp_path):
    plan = project.new("ran", prompt="Count.")
    assert executor.step(plan.path).code == 0
    os.makedirs(os.path.join(plan.path, "state"), exist_ok=True)
    open(os.path.join(plan.path, "state", "x.md"), "w").write("x\n")
    pkt = Packet(plan.packet)
    workspace.prepare(pkt, plan.path, "ran", first=False)
    assert seeds(pkt) == [] and not os.path.exists(os.path.join(pkt.state_dir, "x.md"))
