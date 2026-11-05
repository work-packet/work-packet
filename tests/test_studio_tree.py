"""The studio's file tree and editor (docs/studio-v2.md V1): the Packet
section's mapping, what may be written, saving with a sha check (stale saves
get what the file holds now), the watcher on ``state/``, the path hook's
allow list, and the routes."""

import json
import os
import subprocess
import warnings

import pytest

from conftest import _new_packet, child_wpid
from test_packet_layout import new_here
from work_packet import layout, registry
from work_packet.dash.agent import Agents
from work_packet.studio import model, tree

SECRET = b"k" * 32
BASE = "http://127.0.0.1:7878"


@pytest.fixture
def pk(tmp_path, fake):
    """A packet-layout project with a plan, a step and a child."""
    folder = tmp_path / "clone"
    folder.mkdir()
    (folder / "src").mkdir()
    (folder / "src" / "cli.py").write_text("print('hi')\n")
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    (folder / "node_modules").mkdir()
    plan = new_here(str(folder), name="sr")
    e = registry.get("sr")
    run = layout.run_dir(e["path"], e["root"])
    os.makedirs(os.path.join(run, "state", "notes"), exist_ok=True)
    with open(os.path.join(run, "state", "outline.md"), "w") as fp:
        fp.write("- [ ] 1 parse {>>why?<<}\n")
    with open(os.path.join(run, "state", "questions.md"), "w") as fp:
        fp.write("- [ ] which lexer?\n- [x] done one\n")
    with open(os.path.join(run, "state", "spec.txt"), "w") as fp:
        fp.write("input\n")
    os.makedirs(os.path.join(run, "steps", "0001"), exist_ok=True)
    with open(os.path.join(run, "steps", "0001", "summary.md"), "w") as fp:
        fp.write("did one\n")
    kid = child_wpid(e["root"], 1, 0)
    _new_packet(layout.runs_dir(e["path"]), kid, "sr", "child work", parent=e["root"])
    os.makedirs(os.path.join(run, "children"), exist_ok=True)
    os.symlink(os.path.join("..", "..", kid), os.path.join(run, "children", kid))
    return e, str(folder), run, kid, plan


def test_tree_mapping(pk):
    e, folder, run, kid, _ = pk
    t = tree.tree(e, e["root"])
    names = [n["name"] for n in t["packet"]]
    assert names == ["Card", "Plan", "Inputs", "Steps", "Children"]
    card = t["packet"][0]
    assert card["path"] == "wp:card" and card["file"] == "sr.wp.md" and card["access"] == "edit"
    plan = {n["name"]: n for n in t["packet"][1]["children"]}
    assert list(plan) == ["outline.md", "questions.md", "notes"]
    assert plan["outline.md"]["path"] == "wp:state/outline.md"
    assert plan["outline.md"]["open"] == 1 and plan["questions.md"]["open"] == 1
    assert [n["path"] for n in t["packet"][2]["children"]] == ["wp:state/spec.txt"]
    steps = t["packet"][3]["children"]
    assert steps[0]["path"] == "wp:steps/0001" and steps[0]["access"] == "read"
    assert steps[0]["children"][0]["path"] == "wp:steps/0001/summary.md"
    kids = t["packet"][4]["children"]
    assert kids[0]["wpid"] == kid and kids[0]["children"][0]["name"] == "Plan"
    top = [n["name"] for n in t["files"]]
    assert "src" in top and "sr.wp.md" in top
    assert not {".work-packet", ".git", "node_modules", ".studio"} & set(top)
    shown = [n for n in tree.tree(e, e["root"], show_hidden=True)["files"]]
    assert {n["name"]: n.get("hidden") for n in shown if n["dir"]} == {
        ".git": True, "node_modules": True, "src": None}
    assert ".work-packet" not in [n["name"] for n in shown]
    assert [n["path"] for n in tree.listing(e, e["root"], "src")] == ["src/cli.py"]


def test_resolve_access(pk):
    e, folder, run, kid, _ = pk
    r = lambda p: tree.resolve(e, e["root"], p)    # noqa: E731
    assert r("wp:card") == (os.path.realpath(os.path.join(folder, "sr.wp.md")), "edit")
    assert r("wp:state/outline.md")[1] == "edit"
    assert r("wp:state/new/plan.md")[1] == "edit"           # need not exist
    assert r("wp:steps/0001/summary.md")[1] == "read"
    assert r("wp:child/%s/state/x.md" % kid)[1] == "read"
    assert r("src/cli.py")[1] == "edit"
    assert r(".git/config")[1] == "read"
    assert r(".github/workflows/ci.yml")[1] == "edit"
    for bad in ("wp:state/../status.md", "wp:status.md", "wp:journal", "../x",
                ".work-packet/project.toml", ".studio/studio.json", "src/../../x", "",
                "wp:child/%s/state/x" % ("0" * 8 + kid[8:]), "wp:state/a\0b"):
        with pytest.raises(tree.TreeError):
            r(bad)
    os.symlink("/etc", os.path.join(run, "state", "out"))
    with pytest.raises(tree.TreeError, match="out of"):
        r("wp:state/out/passwd")


def test_read_save_stale(pk):
    e, folder, run, kid, _ = pk
    w = e["root"]
    got = tree.read(e, w, "wp:state/outline.md")
    assert got["access"] == "edit" and got["text"].startswith("- [ ] 1 parse")
    p, sha = tree.save(e, w, "wp:state/outline.md", "- [ ] 1 parse\n", got["sha"])
    assert open(p).read() == "- [ ] 1 parse\n"
    with pytest.raises(tree.Stale) as ex:                   # the old sha
        tree.save(e, w, "wp:state/outline.md", "mine\n", got["sha"])
    assert ex.value.text == "- [ ] 1 parse\n" and ex.value.sha == sha
    with pytest.raises(tree.Stale):                         # no sha for a file there
        tree.save(e, w, "wp:state/outline.md", "mine\n", "")
    with pytest.raises(tree.TreeError, match="read-only"):
        tree.save(e, w, "wp:steps/0001/summary.md", "x", tree.sha("did one\n"))
    with pytest.raises(tree.TreeError, match="read-only"):
        tree.save(e, w, ".git/config", "x", tree.read(e, w, ".git/config")["sha"])
    with pytest.raises(tree.Stale, match="deleted"):        # gone, not created
        tree.save(e, w, "wp:state/notes/1.md", "n\n", "abc")
    p, _ = tree.save(e, w, "wp:state/notes/1.md", "n\n", "", create=True)
    assert open(p).read() == "n\n"
    with pytest.raises(tree.Stale):                         # create over a file
        tree.save(e, w, "wp:state/notes/1.md", "m\n", "", create=True)
    crlf = os.path.join(folder, "src", "w.txt")
    with open(crlf, "wb") as fp:
        fp.write(b"a\r\nb\r\n")
    os.chmod(crlf, 0o755)
    got = tree.read(e, w, "src/w.txt")
    assert got["text"] == "a\r\nb\r\n"                      # newlines kept
    tree.save(e, w, "src/w.txt", got["text"] + "c\r\n", got["sha"])
    assert open(crlf, "rb").read() == b"a\r\nb\r\nc\r\n" and os.stat(crlf).st_mode & 0o777 == 0o755
    with open(os.path.join(folder, "b.bin"), "wb") as fp:
        fp.write(b"\0\1\2")
    assert tree.read(e, w, "b.bin")["why"] == "binary"


def test_watcher_sees_state(pk):
    e, folder, run, kid, _ = pk
    now = [100.0]
    w = model.watcher(e, e["root"], clock=lambda: now[0])
    assert "wp:state/outline.md" in w.stats and "src/cli.py" in w.stats
    assert not any(p.startswith(".work-packet") for p in w.stats)
    p = os.path.join(run, "state", "outline.md")
    w.agent_wrote(p)                                        # the agent's absolute path
    with open(p, "a") as fp:
        fp.write("- [ ] 2 more\n")
    got = w.poll()
    assert [(c["path"], c["by"]) for c in got] == [("wp:state/outline.md", "agent")]
    w.saved("wp:state/questions.md")
    with open(os.path.join(run, "state", "questions.md"), "a") as fp:
        fp.write("- [ ] another\n")
    assert [(c["path"], c["by"]) for c in w.poll()] == [("wp:state/questions.md", "you")]


def test_changed_counts_state_only_with_a_new_baseline(pk):
    e, folder, run, kid, _ = pk
    model.open_studio(e, e["root"], "alice")
    with open(os.path.join(run, "state", "outline.md"), "a") as fp:
        fp.write("- [ ] 2\n")
    assert model.changed(e, e["root"])[1] == ["wp:state/outline.md"]
    bl = os.path.join(model.studio_dir(e, e["root"]), model.BASELINE)
    d = json.load(open(bl))
    d = {k: v for k, v in d.items() if not k.startswith("wp:")}     # a v1 baseline
    json.dump(d, open(bl, "w"))
    assert model.changed(e, e["root"]) == ([], [], [])


def test_pathhook_allows_state(pk, monkeypatch):
    from work_packet import pathhook
    e, folder, run, kid, _ = pk
    ev = lambda p: {"tool_name": "Edit", "tool_input": {"file_path": p}, "cwd": folder}  # noqa: E731
    monkeypatch.setenv("WPK_PROTECT", e["path"])
    monkeypatch.setenv("WPK_PROTECT_ALLOW", os.pathsep.join((os.path.join(run, "state"), folder)))
    assert pathhook.blocked(ev(os.path.join(run, "state", "outline.md"))) is None
    assert pathhook.blocked(ev(os.path.join(run, "status.md")))
    assert pathhook.blocked(ev(os.path.join(e["path"], "project.toml")))
    kid_state = os.path.join(layout.run_dir(e["path"], kid), "state", "x.md")
    assert pathhook.blocked(ev(kid_state))                  # another packet's plan
    assert pathhook.blocked(ev(os.path.join(folder, "src", "cli.py"))) is None


def test_studio_env_allows_the_plan(pk):
    e, folder, run, kid, _ = pk
    ag = Agents(os.environ["WPK_HOME"])
    meta = ag.new({"kind": "packet", "project": "sr", "wpid": e["root"]}, folder, "alice",
                  project_dir=e["path"], mode="studio")
    allow = ag._studio_env(meta)["WPK_PROTECT_ALLOW"].split(os.pathsep)
    assert os.path.join(run, "state") in allow and folder in allow


# --- the routes ------------------------------------------------------------------------

@pytest.fixture
def board(pk, fake):
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard, csrf_token
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    fake("studio")
    e = pk[0]
    ag = Agents(os.environ["WPK_HOME"])
    g = Guard(create_app(agents=ag), "loopback", SECRET, local_user="alice")
    with TestClient(g, base_url=BASE, client=("127.0.0.1", 50000)) as c:
        yield c, pk, csrf_token(SECRET), "/p/sr/%s/studio" % e["root"]


def _post(c, url, tok, body=None):
    return c.post(url, json=body or {}, headers={"origin": BASE, "x-csrf-token": tok})


def test_routes(board):
    c, (e, folder, run, kid, _), tok, base = board
    assert c.get(base + "/tree").status_code == 403                 # not open yet
    assert c.post(base + "/open", data={"csrf": tok}, headers={"origin": BASE},
                  follow_redirects=False).status_code == 303
    t = c.get(base + "/tree").json()
    assert t["packet"][1]["children"][0]["path"] == "wp:state/outline.md"
    assert c.get(base + "/tree?dir=src").json()["files"][0]["path"] == "src/cli.py"
    assert c.get(base + "/tree?dir=../x").status_code == 404
    f = c.get(base + "/fs?path=wp:state/outline.md").json()
    r = _post(c, base + "/fs", tok, {"path": "wp:state/outline.md", "text": "new\n",
                                     "sha": f["sha"]})
    assert r.status_code == 200 and open(os.path.join(run, "state", "outline.md")).read() == "new\n"
    r = _post(c, base + "/fs", tok, {"path": "wp:state/outline.md", "text": "x", "sha": f["sha"]})
    assert r.status_code == 409 and r.json()["text"] == "new\n" and r.json()["stale"]
    assert _post(c, base + "/fs", tok, {"path": "wp:steps/0001/summary.md", "text": "x",
                                        "sha": tree.sha("did one\n")}).status_code == 400
    assert _post(c, base + "/fs", tok, {"path": "wp:status.md", "text": "x"}).status_code == 404
    assert c.post(base + "/fs", json={"path": "src/a.txt", "text": "x", "create": True},
                  headers={"origin": BASE}).status_code == 403              # no CSRF token
    # a plan file opens in a tab, renders as a document, and takes markup
    r = _post(c, base + "/pin", tok, {"path": "wp:state/outline.md"})
    assert r.status_code == 200 and r.json()["canvas"][0]["path"] == "wp:state/outline.md"
    assert not r.json()["canvas"][0]["missing"]
    page = c.get(base + "/frame/doc?path=wp:state/outline.md")
    assert page.status_code == 200 and "new" in page.text
    assert c.get(base + "/frame/doc?path=wp:steps/0001/summary.md").status_code == 200
    assert c.get(base + "/file?path=wp:state/spec.txt").text == "input\n"
    assert c.get(base + "/file?path=wp:status.md").status_code == 404
    for url in ("/tree", "/fs?path=src/cli.py"):
        assert c.get(base + url).status_code == 200
    page = c.get(base)
    assert page.status_code == 200 and 'id="st-files"' in page.text
