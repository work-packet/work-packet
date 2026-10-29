"""Sphinx docs on the board: found, built when stale, served (docs/sphinx-docs-v1.md)."""

import os
import time

import pytest

from conftest import make_project
from work_packet import docs, layout, project, registry, schema

CONF = 'project = "demo"\nextensions = []\nhtml_theme = "alabaster"\n'
INDEX = "Demo\n====\n\nHello from the docs.\n"


def _docs(tree, rel="docs", conf=CONF, index=INDEX):
    d = os.path.join(tree, rel)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "conf.py"), "w") as f:
        f.write(conf)
    with open(os.path.join(d, "index.rst"), "w") as f:
        f.write(index)
    return d


def _ds(tmp_path, src):
    tree = os.path.dirname(src)
    return docs.DocSet("demo", "lib", docs.slug(tree, src), src, tree, None,
                       str(tmp_path / "home"))


# --- detect ----------------------------------------------------------------------

def test_find_known_places_first(tmp_path):
    t = str(tmp_path)
    a = _docs(t, "docs")
    _docs(t, "deep/x/y")
    assert docs.find(t) == [a]


def test_find_searches_shallowly_and_skips(tmp_path):
    t = str(tmp_path)
    src = _docs(t, "pkg/manual")
    _docs(t, "node_modules/thing/docs")
    _docs(t, "_build/docs")
    _docs(t, "a/b/c/d/docs")                      # too deep
    os.makedirs(os.path.join(t, "tools"))
    with open(os.path.join(t, "tools", "conf.py"), "w") as f:
        f.write("TIMEOUT = 3\n")                   # not Sphinx
    assert docs.find(t) == [src]
    assert docs.slug(t, src) == "pkg-manual"


def test_find_source_override(tmp_path):
    t = str(tmp_path)
    _docs(t, "docs")
    other = _docs(t, "manual/src")
    assert docs.find(t, "manual/src") == [other]
    assert docs.find(t, ["nope"]) == []


def test_trees_prefer_newest_edits(tmp_path):
    proj, root = make_project(tmp_path)
    clone = os.path.join(proj, "work", "lib")
    _docs(clone)
    assert docs.trees(proj) == [("lib", clone, None)]
    # The root packet's worktree has its edits; a running child's beat that.
    wt = os.path.join(root.path, "work", "lib")
    _docs(wt)
    assert docs.trees(proj) == [("lib", wt, root.wpid)]
    kid = layout.run_dir(proj, "kid")
    _docs(os.path.join(kid, "work", "lib"))
    assert docs.trees(proj, "kid") == [("lib", os.path.join(kid, "work", "lib"), "kid")]
    # A run's link to a shared plain folder is not a tree of its own.
    os.makedirs(os.path.join(layout.run_dir(proj, "kid2"), "work"))
    os.symlink(clone, os.path.join(layout.run_dir(proj, "kid2"), "work", "lib2"))
    assert docs.trees(proj, "kid2")[0][2] == root.wpid


def test_detect_and_disable(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    proj, _ = make_project(tmp_path)
    _docs(os.path.join(proj, "work", "lib"))
    (ds,) = docs.detect(proj)
    assert (ds.project, ds.entry, ds.name) == ("demo", "lib", "docs")
    assert ds.out == os.path.join(str(tmp_path / "home"), "docs", "demo", "lib", "docs")
    assert docs.detect(proj, cfg={"enabled": False}) == []


def test_packet_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    folder = str(tmp_path / "thing")
    os.makedirs(folder)
    project.new("thing", "Do it.", path=folder, packet=True)
    _docs(folder, "doc/source")
    (ds,) = docs.detect(os.path.join(folder, layout.DOT))
    assert (ds.entry, ds.name, ds.wpid) == ("thing", "doc-source", None)


def test_schema():
    ok = {"source": ["docs"], "python": ".venv/bin/python", "enabled": True, "auto": False}
    assert schema._validate_docs(ok) == []
    bad = schema._validate_docs({"source": 3, "auto": "yes", "what": 1})
    assert {p.field for p in bad} == {"docs.source", "docs.auto", "docs.what"}


# --- stale, build ------------------------------------------------------------------

def test_interpreters_in_order(tmp_path):
    t = str(tmp_path)
    src = _docs(t)
    for rel in ("packages/python/bin/python", ".venv/bin/python"):
        os.makedirs(os.path.dirname(os.path.join(t, rel)), exist_ok=True)
        open(os.path.join(t, rel), "w").close()
    got = [label for _, label in docs.interpreters(_ds(tmp_path, src), {"python": "/x/py"})]
    assert got[:3] == ["[docs] python", "IVPM packages/python", ".venv"]
    assert got[-1] == "the board's Python"


def test_no_sphinx_anywhere(tmp_path, monkeypatch):
    ds = _ds(tmp_path, _docs(str(tmp_path / "w")))
    monkeypatch.setattr(docs, "interpreters", lambda ds, cfg: [(["/bin/false"], "nothing")])
    rec = docs.build(ds)
    assert rec["result"] == "failed" and "no Python with sphinx" in rec["why"]
    with open(os.path.join(ds.out, "build.log")) as f:
        assert "pip install sphinx" in f.read()
    assert docs.is_stale(ds)


def test_lock(tmp_path):
    ds = _ds(tmp_path, _docs(str(tmp_path / "w")))
    os.makedirs(ds.out)
    with open(os.path.join(ds.out, "lock"), "w") as f:
        f.write(str(os.getpid()))
    assert docs.building(ds) == os.getpid()
    assert docs.build(ds) is None
    with open(os.path.join(ds.out, "lock"), "w") as f:
        f.write("999999999")                            # a dead build's lock
    assert docs.building(ds) is None


def test_build_stale_fresh(tmp_path):
    pytest.importorskip("sphinx")
    src = _docs(str(tmp_path / "w"))
    ds = _ds(tmp_path, src)
    assert docs.is_stale(ds)
    rec = docs.build(ds, by="me")
    assert rec["result"] in ("ok", "warnings"), open(os.path.join(ds.out, "build.log")).read()
    assert rec["python"] == "the board's Python" and rec["by"] == "me"
    with open(os.path.join(ds.html, "index.html")) as f:
        assert "Hello from the docs." in f.read()
    assert not docs.is_stale(ds)
    later = time.time() + 5
    os.utime(os.path.join(src, "index.rst"), (later, later))
    assert docs.is_stale(ds)
    docs.build(ds)
    st = docs.state(ds)
    assert not st["stale"] and st["has_html"] and len(st["history"]) == 2


def test_failed_build_records_log(tmp_path):
    pytest.importorskip("sphinx")
    ds = _ds(tmp_path, _docs(str(tmp_path / "w"), conf=CONF + "raise SystemExit(3)\n"))
    rec = docs.build(ds)
    assert rec["result"] == "failed"
    assert docs.history(ds)[0]["result"] == "failed"
    ds = _ds(tmp_path, _docs(str(tmp_path / "w2"), conf=CONF + 'html_theme = "no_such"\n'))
    assert "no theme named 'no_such'" in docs.build(ds)["why"]


def test_after_step(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    proj, root = make_project(tmp_path)
    _docs(os.path.join(proj, "work", "lib"))
    kicked = []
    monkeypatch.setattr(docs.subprocess, "Popen", lambda argv, **kw: kicked.append(argv))
    assert len(docs.after_step(root.path)) == 1
    argv = kicked[0]
    assert argv[argv.index("--wpid") + 1] == root.wpid and "--if-stale" in argv
    # [docs] auto = false turns it off; a broken project never raises.
    monkeypatch.setattr(docs, "settings", lambda proj: {"auto": False})
    assert docs.after_step(root.path) == []
    assert docs.after_step(str(tmp_path / "nowhere" / "x")) == []


# --- the board ---------------------------------------------------------------------

@pytest.fixture
def board(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    pytest.importorskip("sphinx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    project.new("demo", "Do it.")
    proj = registry.get("demo")["path"]
    src = _docs(os.path.join(proj, "work", "lib"))
    return proj, src, TestClient(create_app())


def _until_built(proj, timeout=90):
    (ds,) = docs.detect(proj)
    end = time.time() + timeout
    while time.time() < end:
        if docs.last(ds) and docs.building(ds) is None:
            return docs.last(ds)
        time.sleep(0.2)
    raise AssertionError("no build")


def test_board_builds_and_serves(board):
    proj, src, c = board
    r = c.get("/p/demo")
    assert r.status_code == 200 and 'id="docs"' in r.text and "Build</button>" in r.text
    r = c.get("/p/demo/docs/lib/docs", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].endswith("/docs/lib/docs/")
    r = c.get("/p/demo/docs/lib/docs/")             # nothing built: starts a build
    assert r.status_code == 200 and "BUILDING" in r.text
    rec = _until_built(proj)
    assert rec["result"] in ("ok", "warnings"), c.get("/p/demo/docslog/lib/docs").text
    r = c.get("/p/demo/docs/lib/docs/")
    assert r.status_code == 200 and "Hello from the docs." in r.text
    csp = r.headers["content-security-policy"]
    assert "'unsafe-inline'" in csp and "sandbox" not in csp
    assert c.get("/p/demo/docs/lib/docs/_static/basic.css").headers[
        "content-type"].startswith("text/css")
    r = c.get("/p/demo")
    assert ">Docs" in r.text and "/p/demo/docs/lib/docs/" in r.text and "Rebuild" in r.text
    assert "sphinx" in c.get("/p/demo/docslog/lib/docs").text


def test_board_rebuild_and_paths(board):
    proj, src, c = board
    r = c.post("/p/demo/docs", data={"entry": "lib", "name": "docs"}, follow_redirects=False)
    assert r.status_code == 303 and "building" in r.headers["location"]
    _until_built(proj)
    assert c.post("/p/demo/docs", data={"entry": "lib", "name": "nope"},
                  follow_redirects=False).headers["location"].endswith("ok=0")
    for bad in ("/p/demo/docs/lib/docs/%2e%2e/build.json",
                "/p/demo/docs/lib/docs/%2e%2e/%2e%2e/docs/build.json",
                "/p/demo/docs/%2e%2e/docs/x", "/p/demo/docs/lib/docs/nothing.html"):
        assert c.get(bad).status_code == 404, bad
    os.symlink("/etc", os.path.join(docs.detect(proj)[0].html, "out"))
    assert c.get("/p/demo/docs/lib/docs/out/hostname").status_code == 404


def test_board_without_docs_has_no_menu(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    project.new("plain", "Do it.")
    r = TestClient(create_app()).get("/p/plain")
    assert r.status_code == 200 and 'id="docs"' not in r.text


def test_guard_keeps_the_docs_csp(board):
    """Behind the guard the docs carry their own CSP; the board keeps the strict one."""
    from test_server import _client
    from work_packet.dash.app import create_app
    proj, src, c = board
    (ds,) = docs.detect(proj)
    docs.build(ds)
    g = _client(create_app(), "loopback", None, peer="127.0.0.1", host="127.0.0.1:7878")
    page = g.get("/p/demo/docs/lib/docs/").headers["content-security-policy"]
    board_csp = g.get("/p/demo").headers["content-security-policy"]
    assert page == docs.CSP
    assert "'unsafe-inline'" not in board_csp.split("style-src")[0]


def test_cli(tmp_path, monkeypatch, capsys):
    pytest.importorskip("sphinx")
    from work_packet import cli
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    project.new("demo", "Do it.")
    proj = registry.get("demo")["path"]
    assert cli.main(["docs", "demo"]) == 0
    assert "no Sphinx docs found" in capsys.readouterr().out
    _docs(os.path.join(proj, "work", "lib"))
    assert cli.main(["docs", "demo"]) == 0
    assert "never built, stale" in capsys.readouterr().out
    assert cli.main(["docs", "demo", "--build"]) == 0
    out = capsys.readouterr().out
    assert "building" in out and "board: /p/demo/docs/lib/docs/" in out and "stale" not in out


def test_run_page_says_docs_were_built(board):
    proj, src, c = board
    root = project.load_project(proj)["root"]
    wt = os.path.join(layout.run_dir(proj, root), "work", "lib")
    _docs(wt)                                       # the root packet's worktree
    (ds,) = docs.detect(proj, root)
    docs.build(ds, by="step")
    r = c.get("/p/demo/%s" % root)
    assert "rebuilt after a step" in r.text and "/p/demo/docs/lib/docs/" in r.text
