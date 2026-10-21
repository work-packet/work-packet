import os

from conftest import NOW, ROOT, child_wpid, make_project
from work_packet import clock, spawn
from work_packet.packet import Packet


def test_child_wpid_is_deterministic():
    assert spawn.child_wpid(ROOT, 2, 0) == child_wpid(ROOT, 2, 0)
    assert spawn.child_wpid(ROOT, 2, 0) != spawn.child_wpid(ROOT, 2, 1)
    assert spawn.child_wpid(ROOT, 2, 0) != spawn.child_wpid(ROOT, 3, 0)


def test_decision_entries():
    got = spawn.decision_entries(ROOT, 4, [{"name": "a", "instruction": "x"},
                                           {"name": "b", "instruction": "y",
                                            "copy": ["*.md"], "model": "m"}])
    assert got[1] == {"name": "b", "wpid": child_wpid(ROOT, 4, 1), "spawn_key": ROOT + ":4:1",
                      "instruction": "y", "copy": ["*.md"], "model": "m"}
    assert got[0]["copy"] == [] and got[0]["model"] is None


def test_create_child_copies_globs_and_is_idempotent(tmp_path):
    proj, root = make_project(tmp_path)
    src = str(tmp_path / "src")
    for rel in ("count.md", "notes/a.md", "notes/b.txt", "deep/x/y.md", "skip.txt"):
        os.makedirs(os.path.dirname(os.path.join(src, rel)), exist_ok=True)
        with open(os.path.join(src, rel), "w") as fp:
            fp.write(rel)
    os.makedirs(root.identity_dir)
    os.symlink("/nonexistent/repo", os.path.join(root.identity_dir, "repo"))
    e = spawn.decision_entries(ROOT, 1, [{"name": "a", "instruction": "Go.\n",
                                          "copy": ["count.md", "notes/*.md", "deep/**/*.md"]}])[0]
    now = clock.parse_iso(NOW)
    spawn.create_child(root, e, src, "demo", "m", now)
    child = Packet(os.path.join(proj, "packets", e["wpid"]))
    got = sorted(os.path.relpath(os.path.join(d, f), child.state_dir)
                 for d, _, fs in os.walk(child.state_dir) for f in fs)
    assert got == ["count.md", "deep/x/y.md", "notes/a.md"]
    assert os.readlink(os.path.join(child.identity_dir, "repo")) == "/nonexistent/repo"
    meta, body = child.load_status()
    assert (meta["parent"], meta["model"], meta["step"], body) == (ROOT, "m", 0, "")
    assert open(child.memento_path).read() == "Go.\n"
    # A second call (a retried commit) changes nothing and adds no second child.
    with open(os.path.join(child.state_dir, "count.md"), "w") as fp:
        fp.write("edited")
    spawn.create_child(root, e, src, "demo", "m", now)
    assert open(os.path.join(child.state_dir, "count.md")).read() == "edited"
    assert sorted(os.listdir(root.children_dir)) == [e["wpid"]]
    assert sorted(os.listdir(os.path.join(proj, "packets"))) == sorted([ROOT, e["wpid"]])
