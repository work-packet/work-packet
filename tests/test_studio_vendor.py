"""The vendored JavaScript (docs/studio-v2.md §7): what the manifest lists
is there, unchanged, and served with the right type; nothing else is. The
bundles are build output: without a build, the tests that need them skip."""


import pytest

from test_dash_tasks import _client
from work_packet.dash import vendored

needs_build = pytest.mark.skipif(not vendored.libs(), reason=vendored.NOT_BUILT)


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@needs_build
def test_the_manifest_matches_the_files():
    m = vendored.manifest()
    assert set(vendored.libs(m)) == {"vega", "draw", "codemirror", "term"}
    assert {"vega", "vega-lite", "vega-embed", "vega-interpreter", "mermaid", "react",
            "@excalidraw/excalidraw"} <= set(m["versions"])
    assert [p for p in vendored.check(m) if p[0] == "error"] == []
    assert {"codemirror", "@codemirror/view", "@xterm/xterm"} <= set(m["versions"])
    for want in ("codemirror/codemirror.js", "term/xterm.js", "term/xterm.css", "term/addon-fit.js",
                 "vega/vega.js", "draw/mermaid.js", "draw/excalidraw.js",
                 "draw/excalidraw.css", "draw/mermaid-to-excalidraw.js"):
        assert want in m["files"], want
    assert any(p.startswith("draw/fonts/") and p.endswith(".woff2") for p in m["files"])


def test_check_finds_a_half_done_rebuild(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.js").write_text("a")
    (tmp_path / "lib" / "extra.js").write_text("x")
    (tmp_path / "lib" / "b.js").write_text("changed")
    m = {"budget": {"lib": 3}, "files": {
        "lib/a.js": {"sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                     "size": 1},
        "lib/b.js": {"sha256": "0" * 64, "size": 1},
        "lib/gone.js": {"sha256": "0" * 64, "size": 5},
        "lib/x.exe": {"sha256": "0" * 64, "size": 1}}}
    got = vendored.check(m, root=str(tmp_path))
    text = "\n".join("%s %s" % p for p in got)
    assert "error lib/b.js: changed" in text and "error lib/gone.js: listed but missing" in text
    assert "error lib/extra.js: not in the manifest" in text
    assert "error lib/x.exe: no media type" in text
    assert "warning lib: 8 bytes, above its budget of 3" in text
    assert "lib/a.js" not in text


@needs_build
def test_every_file_is_served_with_its_type(tmp_path, fake):
    c = _client()
    m = vendored.manifest()
    for rel, ent in m["files"].items():
        r = c.get("/static/vendor/" + rel)
        assert r.status_code == 200, rel
        assert r.headers["content-type"].startswith(vendored.media_type(rel)), rel
        assert len(r.content) == ent["size"], rel
        assert "max-age=604800" in r.headers["cache-control"]
    r = c.get("/static/vendor/vega/vega.js")
    again = c.get("/static/vendor/vega/vega.js", headers={"if-none-match": r.headers["etag"]})
    assert again.status_code == 304 and again.content == b""


def test_nothing_else_is_served(tmp_path, fake):
    c = _client()
    for bad in ("vendor/xterm.js", "vendor/vega/nope.js", "vendor/manifest.json", "vendor/../app.py",
                "vendor/vega/../../app.py", "vendor/draw", "vendor/"):
        assert c.get("/static/" + bad).status_code == 404, bad


def test_unbuilt_is_empty_not_an_error(tmp_path):
    m = vendored.manifest.__wrapped__(str(tmp_path / "manifest.json"))
    assert m["files"] == {} and vendored.libs(m) == [] and not vendored.built("vega", m)
    assert vendored.check(m, root=str(tmp_path)) == []


@needs_build
def test_budget():
    m = vendored.manifest()
    over = [p for p in vendored.check(m) if p[0] == "warning"]
    if over:
        import warnings
        warnings.warn("vendored JavaScript above its budget: %s" % over)
    assert all(vendored.sizes(m)[lib] < 2 * m["budget"][lib] for lib in m["budget"])
