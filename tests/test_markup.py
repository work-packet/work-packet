"""Marking up a Markdown file from the board (docs/doc-markup.md)."""

import os

import pytest

from conftest import NOW

pytest.importorskip("markdown_it")
from work_packet.dash import data, markup as M      # noqa: E402

SRC = """# Plan

Run **two** workers {++ nightly ++} on the [farm](http://x/y) and {--drop--} it.
Then {~~2~>4~~} more {==hi==}{>> why? <<}.

- item one with `code_x`
- item two
"""


def line(src, n):
    return src.splitlines()[n]


def test_render_shows_items_and_source_lines():
    html = data.md(SRC, lines=True)
    assert '<h1 data-src="0-1">Plan</h1>' in html
    assert '<ins class="cm cm-ins" data-cm="{++ nightly ++}" data-n="0"> nightly </ins>' in html
    assert '<del class="cm cm-del"' in html and "<del>2</del><ins>4</ins>" in html
    assert '<mark class="cm cm-mark"' in html and 'class="cm cm-comment"' in html
    assert '<li data-src="5-6">' in html
    assert "data-src" not in data.md(SRC)            # the report keeps its plain HTML


@pytest.mark.parametrize("lines,sel,at,op,text,want", [
    ((2, 4), "two workers", 0, "comment", "how many?",
     "Run {==**two** workers==}{>> how many? <<} {++ nightly ++}"),
    ((2, 4), "two", 0, "delete", "", "Run {--**two**--} workers"),
    ((2, 4), "tw", 0, "delete", "", "Run **{--tw--}o** workers"),
    ((2, 4), "farm", 0, "insert", "cluster", "on the [farm](http://x/y){++ cluster ++} and"),
    ((5, 6), "code_x", 0, "replace", "y", "- item one with {~~`code_x`~>y~~}"),
    ((0, 1), "Plan", 0, "comment", "x\n  y", "# {==Plan==}{>> x y <<}"),
])
def test_mark(lines, sel, at, op, text, want):
    out = M.mark(SRC, lines, sel, at, op, text)
    assert want in out
    assert out.replace(want, "") != out


def test_mark_picks_the_occurrence_nearest_the_selection():
    src = "a cat and a cat\n"
    assert M.mark(src, (0, 1), "cat", 9, "delete") == "a cat and a {--cat--}\n"
    assert M.mark(src, (0, 1), "cat", 1, "delete") == "a {--cat--} and a cat\n"


@pytest.mark.parametrize("lines,sel,why", [
    ((2, 4), "nightly on", "overlaps existing markup"),
    ((2, 4), "zzz", "could not find"),
    ((2, 4), "  ", "select some text"),
    ((40, 41), "x", "no such block"),
])
def test_mark_refuses(lines, sel, why):
    with pytest.raises(M.MarkupError, match=why):
        M.mark(SRC, lines, sel, 0, "delete")


def test_mark_refuses_text_with_the_closing_delimiter():
    with pytest.raises(M.MarkupError, match="cannot contain"):
        M.mark(SRC, (0, 1), "Plan", 0, "comment", "a <<} b")


@pytest.mark.parametrize("raw,accept,want", [
    ("{++ nightly ++}", True, "workers nightly on"),
    ("{++ nightly ++}", False, "workers on"),
    ("{--drop--}", True, "and it."),
    ("{--drop--}", False, "and drop it."),
    ("{~~2~>4~~}", True, "Then 4 more"),
    ("{~~2~>4~~}", False, "Then 2 more"),
    ("{>> why? <<}", True, "more hi."),
    ("{==hi==}", True, "more hi{>> why? <<}."),
])
def test_resolve(raw, accept, want):
    assert want in M.resolve(SRC, raw, 0, accept)


def test_resolve_counts_repeats():
    src = "x {--a--} y {--a--} z\n"
    assert M.resolve(src, "{--a--}", 1, False) == "x {--a--} y a z\n"
    with pytest.raises(M.Stale):
        M.resolve(src, "{--a--}", 2, False)


def test_edit_checks_the_sha(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("hello\n")
    p.chmod(0o640)
    sha = M.edit(str(p), M.sha("hello\n"), lambda t: t.upper())
    assert p.read_text() == "HELLO\n" and sha == M.sha("HELLO\n")
    assert oct(p.stat().st_mode & 0o777) == "0o640"
    with pytest.raises(M.Stale):
        M.edit(str(p), M.sha("hello\n"), lambda t: t)
    assert [n for n in os.listdir(tmp_path)] == ["a.md"]


# --- the board -------------------------------------------------------------------------

@pytest.fixture
def board(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet import registry
    from work_packet.dash.app import create_app
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "wpk-home"))     # not your registry
    proj = tmp_path / "demo"
    (proj / "work" / "repo" / "docs").mkdir(parents=True)
    (proj / "work" / "repo" / "docs" / "plan.md").write_text(SRC)
    (proj / "work" / "repo" / "notes.txt").write_text("n\n")
    (tmp_path / "secret.md").write_text("no\n")
    os.symlink(str(tmp_path / "secret.md"), str(proj / "work" / "out.md"))
    registry.register({"name": "demo", "path": str(proj), "root": "00000000-0000-4000-8000-000000000000", "created": NOW})
    return TestClient(create_app()), proj / "work" / "repo" / "docs" / "plan.md"


def test_doc_view_lists_and_renders(board):
    c, plan = board
    r = c.get("/p/demo/doc", params={"path": "work/repo"})
    assert r.status_code == 200 and "docs/" in r.text and "notes.txt" not in r.text
    r = c.get("/p/demo/doc", params={"path": "work/repo/docs/plan.md"})
    assert r.status_code == 200
    assert 'id="mk-doc"' in r.text and 'data-sha="%s"' % M.sha(SRC) in r.text
    assert "5</strong> markup items" in r.text and "compose?instruction=" in r.text
    assert c.get("/p/demo/doc", params={"path": "work/repo/docs/plan.md",
                                        "raw": "1"}).text == SRC
    for bad in ("work/out.md", "work/../x.md", "/etc/passwd", "state/x.md"):
        assert c.get("/p/demo/doc", params={"path": bad}).status_code == 404, bad


def test_markup_post_writes_the_file(board):
    c, plan = board
    body = {"path": "work/repo/docs/plan.md", "sha": M.sha(SRC), "op": "comment",
            "lines": "2-4", "sel": "two workers", "at": 0, "text": "how many?"}
    r = c.post("/p/demo/markup", json=body)
    assert r.status_code == 200, r.text
    text = plan.read_text()
    assert "{==**two** workers==}{>> how many? <<}" in text
    assert r.json()["sha"] == M.sha(text)
    r = c.post("/p/demo/markup", json=body)                     # the old sha
    assert r.status_code == 409 and r.json()["stale"]
    r = c.post("/p/demo/markup", json={"path": "work/repo/docs/plan.md", "sha": M.sha(text),
                                       "op": "accept", "raw": "{~~2~>4~~}", "n": 0})
    assert r.status_code == 200 and "Then 4 more" in plan.read_text()


def test_markup_post_refuses(board):
    c, plan = board
    for body, status in [
        ({"path": "work/out.md", "op": "delete"}, 404),
        ({"path": "work/repo/notes.txt", "op": "delete"}, 404),
        ({"path": "work/repo/docs/plan.md", "op": "delete", "lines": "2-4", "sel": "zzz"}, 400),
        ({"path": "work/repo/docs/plan.md", "op": "ask"}, 400),
    ]:
        assert c.post("/p/demo/markup", json=body).status_code == status, body
    assert c.post("/p/demo/markup", content=b"[1]",
                  headers={"content-type": "application/json"}).status_code == 400
    assert plan.read_text() == SRC


def test_compose_takes_an_instruction(board):
    c, _ = board
    r = c.get("/p/demo/compose", params={"instruction": "Resolve the markup"})
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert "Resolve the markup</textarea>" in r.text
