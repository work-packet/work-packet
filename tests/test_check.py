import json
import os
import shutil
import socket

import pytest
import tomli_w

from conftest import NOW, ROOT, child_wpid, make_project
from work_packet import frontmatter
from work_packet.check import check
from work_packet.cli import main
from work_packet.packet import Packet


def where(rep, proj, level="error"):
    """{(path relative to the project, field)} for issues at ``level``."""
    return {(os.path.relpath(i.path, proj), i.field)
            for i in rep.issues if i.level == level}


def edit_status(pkt, **kw):
    meta, body = pkt.load_status()
    meta.update(kw)
    pkt.save_status(meta, body)


R = os.path.join("packets", ROOT)
CHILD = child_wpid(ROOT, 2, 0)
C = os.path.join("packets", CHILD)


def test_fresh_project_is_clean(tmp_path):
    proj, _ = make_project(tmp_path)
    rep = check(proj)
    assert rep.issues == []


def test_project_with_steps_and_child_is_clean(project):
    proj, root = project
    rep = check(proj)
    assert rep.issues == [], [str(i) for i in rep.issues]
    assert os.path.isdir(os.path.join(proj, C))


def test_check_single_packet(project):
    proj, root = project
    assert check(root.path).issues == []


# Each case breaks one thing and names the (file, field) the checker must report.

def _status_step(proj, root):
    edit_status(root, step=5)
    return (os.path.join(R, "status.md"), "step")


def _status_wpid(proj, root):
    edit_status(root, wpid=CHILD)
    return (os.path.join(R, "status.md"), "wpid")


def _status_project(proj, root):
    edit_status(root, project="other")
    return (os.path.join(R, "status.md"), "project")


def _status_garbage(proj, root):
    with open(root.status_path, "w") as fp:
        fp.write("---\nstate: [\n---\n")
    return (os.path.join(R, "status.md"), None)


def _memento_bad(proj, root):
    with open(root.memento_path, "w") as fp:
        fp.write(frontmatter.dump({"resume": "every monday"}, "x\n"))
    return (os.path.join(R, "memento.md"), "resume")


def _missing_state(proj, root):
    shutil.rmtree(root.state_dir)
    return (os.path.join(R, "state"), None)


def _missing_step_dir(proj, root):
    shutil.rmtree(root.step_dir(2))
    return (os.path.join(R, "steps", "0002"), None)


def _future_step_dir(proj, root):
    os.makedirs(root.step_dir(9))
    return (os.path.join(R, "steps", "0009"), None)


def _journal_bad_json(proj, root):
    with open(root.journal_path, "a") as fp:
        fp.write("{not json\n")
    return (os.path.join(R, "journal.jsonl"), "line 10")


def _journal_unknown_type(proj, root):
    with open(root.journal_path, "a") as fp:
        fp.write(json.dumps({"type": "oops", "t": NOW}) + "\n")
    return (os.path.join(R, "journal.jsonl") + ":10", "type")


def _journal_end_without_begin(proj, root):
    with open(root.journal_path, "a") as fp:
        fp.write(json.dumps({"type": "commit-end", "t": NOW, "step": 4}) + "\n")
    return (os.path.join(R, "journal.jsonl") + ":10", None)


def _child_link_missing(proj, root):
    os.unlink(os.path.join(root.children_dir, CHILD))
    return (os.path.join(R, "children", CHILD), None)


def _child_link_wrong(proj, root):
    p = os.path.join(root.children_dir, CHILD)
    os.unlink(p)
    os.symlink("../" + CHILD, p)
    return (os.path.join(R, "children", CHILD), None)


def _child_not_listed(proj, root):
    edit_status(root, children=[])
    return (os.path.join(R, "children", CHILD), None)


def _child_parent_wrong(proj, root):
    other = "1b2c3d4e-0000-4000-8000-000000000001"
    edit_status(Packet(os.path.join(proj, C)), parent=other, spawn_key=other + ":2:0")
    return (os.path.join(C, "status.md"), "parent")


def _orphan_root(proj, root):
    edit_status(Packet(os.path.join(proj, C)), parent=None, spawn_key=None)
    return (os.path.join(C, "status.md"), "parent")


def _project_root_missing(proj, root):
    with open(os.path.join(proj, "project.toml"), "wb") as fp:
        tomli_w.dump({"name": "demo", "root": "1b2c3d4e-0000-4000-8000-000000000001",
                      "created": NOW}, fp)
    return ("project.toml", "root")


def _project_bad_tz(proj, root):
    with open(os.path.join(proj, "project.toml"), "wb") as fp:
        tomli_w.dump({"name": "demo", "root": ROOT, "created": NOW, "tz": "Nowhere"}, fp)
    return ("project.toml", "tz")


def _stray_packet_name(proj, root):
    os.makedirs(os.path.join(proj, "packets", "notes"))
    return (os.path.join("packets", "notes"), None)


@pytest.mark.parametrize("breaker", [
    _status_step, _status_wpid, _status_project, _status_garbage, _memento_bad,
    _missing_state, _missing_step_dir, _future_step_dir, _journal_bad_json,
    _journal_unknown_type, _journal_end_without_begin, _child_link_missing,
    _child_link_wrong, _child_not_listed, _child_parent_wrong, _orphan_root,
    _project_root_missing, _project_bad_tz, _stray_packet_name,
], ids=lambda f: f.__name__.lstrip("_"))
def test_reports_file_and_field(project, breaker):
    proj, root = project
    want = breaker(proj, root)
    got = where(check(proj), proj)
    assert want in got, got


# Crash leftovers are warnings: the packet is recoverable, not broken.

def test_pending_without_lease_warns(project):
    proj, root = project
    os.makedirs(os.path.join(root.pending_dir, "state"))
    os.makedirs(root.step_dir(4))
    rep = check(proj)
    assert rep.errors == []
    assert where(rep, proj, "warning") == {(os.path.join(R, ".pending"), None),
                                           (os.path.join(R, "steps", "0004"), None)}


def test_live_lease_hides_in_progress(project):
    proj, root = project
    os.makedirs(os.path.join(root.pending_dir, "state"))
    os.makedirs(root.step_dir(4))
    with open(root.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 4,
                   "attempt": 1, "expires": "2999-01-01T00:00:00Z"}, fp)
    assert check(proj).issues == []


def test_stale_lease_warns(project):
    proj, root = project
    with open(root.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 4,
                   "attempt": 1, "expires": "2000-01-01T00:00:00Z"}, fp)
    rep = check(proj)
    assert rep.errors == []
    assert (os.path.join(R, ".lease"), None) in where(rep, proj, "warning")


def test_torn_journal_tail_warns(project):
    proj, root = project
    with open(root.journal_path, "a") as fp:
        fp.write('{"type":"note","t":"%s","msg":"half' % NOW)
    rep = check(proj)
    assert rep.errors == []
    assert (os.path.join(R, "journal.jsonl"), None) in where(rep, proj, "warning")


def test_unfinished_commit_warns(project):
    proj, root = project
    with open(root.journal_path, "a") as fp:
        fp.write(json.dumps({"type": "commit-begin", "t": NOW, "step": 4, "decision": {
            "state": "RUNNABLE", "resume_expr": "now", "wake_at": None, "reason": None,
            "model": "m", "summary": "s", "spawn": []}}) + "\n")
    rep = check(proj)
    assert rep.errors == []
    assert (os.path.join(R, "journal.jsonl"), None) in where(rep, proj, "warning")


def test_half_built_child_warns(project):
    proj, root = project
    os.makedirs(os.path.join(proj, "packets", ".tmp-" + CHILD))
    rep = check(proj)
    assert rep.errors == []
    assert (os.path.join("packets", ".tmp-" + CHILD), None) in where(rep, proj, "warning")


# Runner home and registry.

def _register(home, proj, **kw):
    os.makedirs(os.path.join(home, "projects"), exist_ok=True)
    d = {"name": "demo", "path": proj, "root": ROOT, "created": NOW}
    d.update(kw)
    with open(os.path.join(home, "projects", "demo.toml"), "wb") as fp:
        tomli_w.dump(d, fp)


def test_home(project, tmp_path, monkeypatch):
    proj, _ = project
    home = str(tmp_path / "home")
    _register(home, proj)
    with open(os.path.join(home, "config.toml"), "w") as fp:
        fp.write('model = "claude-haiku-4-5-20251001"\nmax_concurrent = 2\n')
    assert check(home).issues == []
    monkeypatch.setenv("WPK_HOME", home)
    assert check().issues == []


def test_home_reports_registry_and_projects(project, tmp_path):
    proj, root = project
    home = str(tmp_path / "home")
    _register(home, proj, root="1b2c3d4e-0000-4000-8000-000000000001")
    edit_status(root, step=7)
    got = {(os.path.basename(i.path), i.field) for i in check(home).errors}
    assert ("demo.toml", "root") in got
    assert ("status.md", "step") in got


def test_home_missing_project(tmp_path):
    home = str(tmp_path / "home")
    _register(home, str(tmp_path / "gone"))
    assert ("demo.toml", "path") in {(os.path.basename(i.path), i.field)
                                     for i in check(home).errors}


# The command line.

def test_cli_clean(project, capsys):
    proj, _ = project
    assert main(["check", proj]) == 0
    assert "0 errors, 0 warnings" in capsys.readouterr().err


def test_cli_reports_relative_path_and_field(project, capsys):
    proj, root = project
    edit_status(root, state="WAITING")
    assert main(["check", proj]) == 1
    out = capsys.readouterr()
    assert "error: %s: state: WAITING is reserved for Stage 3" % os.path.join(R, "status.md") \
        in out.out
    assert "1 error," in out.err


def test_cli_strict_and_quiet(project, capsys):
    proj, root = project
    os.makedirs(os.path.join(root.pending_dir))
    assert main(["check", proj]) == 0
    assert main(["check", "--strict", proj]) == 1
    capsys.readouterr()
    assert main(["check", "-q", proj]) == 0
    assert capsys.readouterr().out == ""


def test_cli_not_a_packet(tmp_path):
    assert main(["check", str(tmp_path)]) == 1
