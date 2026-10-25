"""Setup: ``wpk new`` without a prompt, ``wpk doctor``, the helpers, ``[setup]``
(docs/setup.md)."""

import json
import os
import subprocess

import pytest

from work_packet import project, schema, setup
from work_packet.check import check
from work_packet.cli import main
from work_packet.packet import Packet


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k, v in (("GIT_AUTHOR_NAME", "T"), ("GIT_AUTHOR_EMAIL", "t@example.com"),
                 ("GIT_COMMITTER_NAME", "T"), ("GIT_COMMITTER_EMAIL", "t@example.com")):
        monkeypatch.setenv(k, v)
    return os.environ["WPK_HOME"]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def source(tmp_path):
    """A repository like dv-solve: committed code, an untracked packages/ of its own."""
    src = tmp_path / "src" / "dv-solve"
    src.mkdir(parents=True)
    git(src, "init", "-q", "-b", "main")
    (src / "README.md").write_text("dv-solve\n")
    (src / ".gitignore").write_text("packages/\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "init")
    (src / "packages" / "python" / "bin").mkdir(parents=True)
    return src


def clone(tg, source, share=False):
    """What you do by hand: git clone into the project's work/, and link packages/."""
    r = os.path.join(tg.work, "dv-solve")
    os.makedirs(tg.work, exist_ok=True)
    subprocess.run(["git", "clone", "-q", str(source), r], check=True)
    if share:
        os.symlink(str(source / "packages"), os.path.join(r, "packages"))
    return r


def held(name="dvs"):
    project.new(name)
    return setup.target(name)


def by_id(checks):
    return {c.id: c for c in checks}


def test_new_without_prompt_is_held_for_setup(home, tmp_path):
    tg = held()
    meta, _ = tg.packet.load_status()
    assert (meta["state"], meta["reason"]) == ("PAUSED", "setup")
    assert open(tg.packet.memento_path).read() == ""
    assert open(tg.prompt_path).read() == ""                        # for you to write
    for d in ("state", "identity", "work"):
        assert os.listdir(os.path.join(tg.proj, d)) == []
    assert check(tg.proj).issues == []
    cs = by_id(setup.readiness(tg, tools=False))
    assert cs["project.held"].level == "ok"
    assert cs["instruction.body"].level == "missing"
    assert cs["instruction.body"].fix == ["wpk instruct dvs --template outline"]
    assert cs["work.none"].level == "warn"


def test_doctor_cli_text_json_and_exit(home, capsys):
    held()
    assert main(["doctor", "dvs"]) == 1
    out = capsys.readouterr().out
    assert "✗ no instruction yet" in out
    assert "$ wpk instruct dvs --template outline" in out
    assert "1 missing" in out and "Next: wpk instruct dvs --template outline" in out
    assert main(["doctor", "dvs", "--json"]) == 1
    d = json.loads(capsys.readouterr().out)
    assert d["project"] == "dvs" and d["packet"].endswith(d["packet"].split("/")[-1])
    assert any(c["id"] == "instruction.body" and c["level"] == "missing" for c in d["checks"])
    assert main(["doctor"]) == 0          # the fake claude answers --version
    assert "dvs" in capsys.readouterr().out


def test_path(home, source, capsys):
    tg = held()
    assert main(["path", "dvs"]) == 0
    assert capsys.readouterr().out.strip() == tg.proj
    assert main(["path", "dvs", "--packet"]) == 0
    assert capsys.readouterr().out.strip() == tg.packet.path
    assert main(["path", "dvs", "--state"]) == 0              # before the first step: the root's
    assert capsys.readouterr().out.strip() == os.path.join(tg.proj, "state")
    assert main(["path", "dvs", "--work", "dv-solve"]) == 4
    clone(tg, source)
    assert main(["path", "dvs", "--work", "dv-solve"]) == 0
    assert capsys.readouterr().out.strip() == os.path.join(tg.proj, "work", "dv-solve")


def test_resume_and_handoff_refuse_until_set_up(home, capsys):
    tg = held()
    assert main(["resume", "dvs"]) == 1
    err = capsys.readouterr().err
    assert "dvs is not set up yet" in err and "wpk instruct dvs" in err
    assert tg.status()["state"] == "PAUSED"
    setup.instruct(tg, "Count to 3 in state/count.md.")
    assert main(["handoff", "dvs", "-m", "go"]) == 0
    assert tg.status()["state"] == "RUNNABLE"


def test_resume_force(home):
    tg = held()
    assert main(["resume", "dvs", "--force"]) == 0
    assert tg.status()["state"] == "RUNNABLE"


def test_dvs_enh_with_helpers_only(home, source, tmp_path):
    """The dvs-enh setup (trial-dv-solve.md §2-§5), done with helpers."""
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n" + "x" * 5000 + "\n")
    research = tmp_path / "research"
    research.mkdir()
    tg = held()
    r = clone(tg, source, share=True)                              # at the root, yours
    assert git(r, "symbolic-ref", "--short", "HEAD") == "main"
    setup.add_input(tg, [str(plan)])
    os.makedirs(tg.identity, exist_ok=True)
    os.symlink(str(research), os.path.join(tg.identity, "research"))
    setup.add_smoke(tg, "test -d packages/python")
    setup.instruct(tg, setup.template_text(tg, "outline"))
    assert tg.packet.load_memento()[1] == ""                       # not in the packet yet
    body, where = setup.instruction(tg)
    assert where == "prompt.md"
    assert "work/dv-solve/ (branch wpk/dvs)" in body and "state/plan.md" in body
    assert "work/dv-solve." in body           # end of a sentence: not a repo named "dv-solve."
    assert by_id(setup.readiness(tg, tools=False))["instruction.body"].level == "ok"
    assert not [c for c in setup.readiness(tg, tools=False) if c.group == "instruction"
                and c.level != "ok"]
    cs = by_id(setup.readiness(tg, tools=False))
    assert cs["limits.smoke"].level == "warn"
    assert cs["inputs.state"].level == "info"             # over 4 KB: listed, not shown
    assert "state/plan.md (4.9 KB)" in cs["inputs.state"].detail
    assert cs["inputs.identity.research"].level == "ok"
    res = setup.run_smoke(tg)
    assert res["ok"] and res["runs"][0]["code"] == 0
    assert res["runs"][0]["cwd"] == os.path.join(tg.proj, ".setup", "smoke", "dv-solve")
    assert os.path.isfile(os.path.join(res["runs"][0]["cwd"], ".git"))      # a worktree
    cs = setup.readiness(tg, tools=False)
    assert setup.missing(cs) == []
    assert by_id(cs)["limits.smoke"].level == "ok"
    assert setup.next_step(tg, [c for c in cs if c.level != "warn"]).startswith("wpk handoff dvs")
    spec = tg.reload().spec
    assert "repo" not in spec                                      # read from work/ instead:
    assert setup.repo_entries(tg.proj) == [
        {"name": "dv-solve", "from": str(source), "share": ["packages"]}]
    assert spec["input"] == [{"from": str(plan)}] and "link" not in spec
    assert setup.link_entries(tg.proj) == [{"from": str(research)}]
    assert check(tg.proj).issues == []
    assert os.listdir(tg.packet.state_dir) == []                   # nothing in the packet yet
    assert main(["handoff", "dvs"]) == 0
    # The first step fills the root packet; afterwards inputs go to the packet.
    from work_packet import executor
    assert executor.step(tg.proj).code == 0
    assert os.path.isfile(os.path.join(tg.packet.state_dir, "plan.md"))
    tree = os.path.join(tg.packet.path, "work", "dv-solve")
    assert git(tree, "symbolic-ref", "--short", "HEAD") == "wpk/dvs"
    assert git(tree, "status", "--porcelain") == ""                # packages/ shared, excluded
    assert git(r, "status", "--porcelain") == ""
    assert tg.started() and tg.state == tg.packet.state_dir
    late = tmp_path / "late.md"
    late.write_text("late\n")
    setup.add_input(tg, [str(late)])
    assert os.path.isfile(os.path.join(tg.packet.state_dir, "late.md"))
    assert by_id(setup.readiness(tg, tools=False))["work.dv-solve.tree"].level == "ok"


def test_untracked_link_found_and_fixed(home, source, capsys):
    tg = held()                       # a clone made inside the packet, the old way
    r = os.path.join(tg.packet_work, "dv-solve")
    os.makedirs(tg.packet_work, exist_ok=True)
    subprocess.run(["git", "clone", "-q", str(source), r], check=True)
    git(r, "switch", "-q", "-c", "wpk/dvs")
    os.symlink(str(source / "packages"), os.path.join(r, "packages"))
    c = by_id(setup.readiness(tg, tools=False))["work.dv-solve.share.packages"]
    assert (c.level, c.safe) == ("missing", True)
    assert c.fix[0].startswith("echo packages >> ")
    assert main(["doctor", "dvs", "--fix"]) == 1          # the instruction is still missing
    assert "work.dv-solve.share.packages" not in by_id(setup.readiness(tg, tools=False))
    assert git(r, "status", "--porcelain") == ""


def test_clone_at_the_root(home, source):
    tg = held()
    r = clone(tg, source)
    open(os.path.join(r, "new.c"), "w").close()
    cs = by_id(setup.readiness(tg, tools=False))
    assert cs["work.dv-solve.branch"].level == "ok"
    c = cs["work.dv-solve.clean"]                  # the worktree starts from HEAD without it
    assert c.level == "warn" and "new.c" in c.title
    os.unlink(os.path.join(r, "new.c"))
    git(r, "switch", "-q", "-c", "wpk/dvs")        # the steps' branch: their worktree needs it
    c = by_id(setup.readiness(tg, tools=False))["work.dv-solve.branch"]
    assert c.level == "missing" and c.fix[0].endswith("switch main")
    git(r, "switch", "-q", "--detach")
    assert by_id(setup.readiness(tg, tools=False))["work.dv-solve.branch"].level == "ok"
    os.symlink(str(source / "packages"), os.path.join(r, "packages"))
    assert by_id(setup.readiness(tg, tools=False))["work.dv-solve.share"].level == "info"


def test_plain_directory_in_work(home):
    tg = held()
    os.makedirs(os.path.join(tg.work, "data"), exist_ok=True)
    c = by_id(setup.readiness(tg, tools=False))["work.data.plain"]
    assert c.level == "warn" and "not rolled back" in c.detail


def test_smoke_failure_and_short_timeout(home, source, monkeypatch):
    tg = held()
    clone(tg, source)
    setup.add_smoke(tg, "exit 3")
    res = setup.run_smoke(tg)
    assert not res["ok"] and res["runs"][0]["code"] == 3
    c = by_id(setup.readiness(tg, tools=False))["limits.smoke"]
    assert c.level == "missing" and "exit 3" in c.title
    assert c.fix[0].startswith("tail -30 ")
    # A passing run that takes most of step_timeout.
    tg.toml["setup"]["smoke"] = [{"run": "true", "repo": "dv-solve"}]
    from work_packet.tomlio import save_toml
    save_toml(os.path.join(tg.proj, "project.toml"), tg.toml)
    setup.run_smoke(tg.reload())
    p = os.path.join(tg.setup_dir, "smoke.json")
    d = json.load(open(p))
    d["runs"][0]["seconds"] = 6000.0
    open(p, "w").write(json.dumps(d))
    c = by_id(setup.readiness(tg, tools=False))["limits.timeout"]
    assert c.level == "warn" and c.fix == ["wpk set dvs step_timeout=150m"] and c.safe
    # A new commit makes the result stale.
    r = os.path.join(tg.work, "dv-solve")
    git(r, "commit", "-q", "--allow-empty", "-m", "more")
    assert "changed since" in by_id(setup.readiness(tg, tools=False))["limits.smoke"].title


def test_from_setup_and_apply(home, source, tmp_path, capsys):
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n")
    tg = held()
    clone(tg, source, share=True)
    setup.add_input(tg, [str(plan)])
    project.allow(tg.proj, ["Bash"], "t")
    project.set_values(tg.proj, [("step_timeout", '"60m"')], "t")
    assert main(["new", "dvs2", "--from-setup", "dvs"]) == 0
    t2 = setup.target("dvs2")
    assert t2.toml["step_timeout"] == "60m"
    assert "Bash" in t2.toml["permissions"]["allowed_tools"]
    assert t2.spec["repo"] == [{"name": "dv-solve", "from": str(source),
                                "share": ["packages"]}]           # read from dvs's work/
    assert setup.held_for_setup(t2.status())
    capsys.readouterr()
    assert main(["setup", "dvs2", "--apply"]) == 1          # applied; the instruction is missing
    r = os.path.join(t2.work, "dv-solve")
    assert git(r, "symbolic-ref", "--short", "HEAD") == "main"
    assert os.path.realpath(os.path.join(r, "packages")) == str(source / "packages")
    assert os.path.exists(os.path.join(t2.proj, "state", "plan.md"))
    miss = setup.missing(setup.readiness(t2, tools=False))
    assert [c.id for c in miss] == ["instruction.body"]


def test_instruct_cli_file_and_bad_text(home, tmp_path):
    tg = held()
    f = tmp_path / "i.md"
    f.write_text("Do the thing.\n")
    assert main(["instruct", "dvs", "--file", str(f)]) == 0
    assert open(tg.prompt_path).read() == "Do the thing.\n"
    f.write_text("  \n")
    assert main(["instruct", "dvs", "--file", str(f)]) == 4


def test_instruct_keeps_front_matter(home):
    tg = held()
    from work_packet import frontmatter
    open(tg.packet.memento_path, "w").write(frontmatter.dump({"resume": "now"}, "old\n"))
    setup.instruct(tg, "new")
    assert tg.packet.load_memento() == ({"resume": "now"}, "new\n")


def test_packet_helpers_refuse_while_a_step_runs(home, tmp_path):
    from work_packet import executor
    project.new("ran", prompt="Count.")
    tg = setup.target("ran")
    assert executor.step(tg.proj).code == 0
    f = tmp_path / "x.md"
    f.write_text("x\n")
    from work_packet.lease import Lease
    lease = Lease(tg.packet.lease_path, 2, 1, 60).acquire()
    try:
        with pytest.raises(setup.SetupError, match="a step is running"):
            setup.add_input(tg, [str(f)])
        with pytest.raises(setup.SetupError, match="a step is running"):
            setup.instruct(tg, "x")
    finally:
        lease.release()


def test_setup_table_validation():
    base = {"name": "p", "root": "3f0c9a2e-6d1b-4c61-9a57-0d5e7f1b2c3d",
            "created": "2026-10-21T18:00:00Z"}
    ok = dict(base, setup={"smoke_timeout": "20m",
                           "repo": [{"name": "a", "from": "~/a", "share": ["packages"]}],
                           "input": [{"from": "~/p.md"}], "link": [{"from": "~/r"}],
                           "smoke": [{"run": "make", "repo": "a"}]})
    assert schema.validate_project(ok) == []
    bad = dict(base, setup={"repo": [{"name": "a"}], "smoke": [{"run": "x", "cwd": "y"}],
                            "other": 1})
    fields = sorted(p.field for p in schema.validate_project(bad))
    assert fields == ["setup.other", "setup.repo[0].from", "setup.smoke[0].cwd"]


def test_tilde_quotes_for_pasting():
    h = os.path.expanduser("~")
    assert setup.tilde(h + "/a b/c") == "~/'a b/c'"
    assert setup.tilde("/tmp/x") == "/tmp/x"


def test_board_card_shows_setup(home):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet import registry
    from work_packet.dash import data
    from work_packet.dash.app import create_app
    tg = held()
    c = data.card(registry.get("dvs"))
    assert c["column"] == "Paused"
    assert c["setup"] == {"missing": 1, "warnings": 1,
                          "next": "wpk instruct dvs --template outline"}
    r = TestClient(create_app()).get("/")
    assert "Setting up:" in r.text and "1 missing" in r.text
    assert "next: <code>wpk instruct dvs --template outline</code>" in r.text
    setup.instruct(tg, "Count to 3.")
    assert data.card(registry.get("dvs"))["setup"]["missing"] == 0
    assert "ready to hand off" in TestClient(create_app()).get("/").text


def test_setup_repo_not_cloned_gives_the_commands(home, source):
    tg = held()
    tg.toml["setup"] = {"repo": [{"name": "dv-solve", "from": str(source),
                                  "share": ["packages"]}]}
    from work_packet.tomlio import save_toml
    save_toml(os.path.join(tg.proj, "project.toml"), tg.toml)
    c = by_id(setup.readiness(tg, tools=False))["work.dv-solve.cloned"]
    assert c.level == "missing" and c.safe
    assert c.fix[0].startswith("git clone ") and c.fix[1].startswith("ln -s ")
    for f in c.fix:
        assert setup.run_fix(f).returncode == 0
    assert "work.dv-solve.cloned" not in by_id(setup.readiness(tg, tools=False))


def test_from_setup_reads_identity_links(home, tmp_path):
    research = tmp_path / "research"
    research.mkdir()
    tg = held()
    os.makedirs(tg.identity, exist_ok=True)
    os.symlink(str(research), os.path.join(tg.identity, "r"))
    assert main(["new", "dvs2", "--from-setup", "dvs"]) == 0
    t2 = setup.target("dvs2")
    assert t2.spec["link"] == [{"from": str(research), "name": "r"}]
    c = by_id(setup.readiness(t2, tools=False))["inputs.identity.r"]
    assert c.level == "missing" and c.safe and c.fix[0].startswith("mkdir -p ")
    assert main(["setup", "dvs2", "--apply"]) == 1                 # the instruction is missing
    assert os.path.realpath(os.path.join(t2.identity, "r")) == str(research)
