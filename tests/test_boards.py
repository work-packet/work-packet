"""Boards of the dash: make, delete, move projects between them (docs/boards.md)."""

import pytest

from conftest import NOW
from work_packet import cli, project, registry, schema


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WPK_NOW", NOW)
    monkeypatch.chdir(tmp_path)
    for n in ("alpha", "beta"):
        project.new(n, "Do a thing.")
    return tmp_path / "home"


def _on(name):
    return registry.board_of(registry.get(name), [b["name"] for b in registry.boards()])


def test_main_always_exists_and_projects_start_there(home):
    assert [b["name"] for b in registry.boards()] == ["main"]
    assert _on("alpha") == "main" and "board" not in registry.get("alpha")


def test_make_move_and_delete(home):
    registry.new_board("rtl", title="RTL work")
    assert [b["name"] for b in registry.boards()] == ["main", "rtl"]
    assert registry.move("alpha", "rtl") == "main"
    assert _on("alpha") == "rtl" and registry.get("alpha")["board"] == "rtl"
    assert not [p for p in schema.validate_registry_entry(registry.get("alpha"), "alpha")
                if p.level == "error"]
    assert registry.move("alpha", "rtl") == "rtl"            # already there
    assert registry.move("alpha", "main") == "rtl" and "board" not in registry.get("alpha")
    registry.move("beta", "rtl")
    assert registry.delete_board("rtl") == ["beta"]
    assert _on("beta") == "main" and "board" not in registry.get("beta")
    assert [b["name"] for b in registry.boards()] == ["main"]


@pytest.mark.parametrize("call, why", [
    (lambda: registry.new_board("main"), "already"),
    (lambda: registry.new_board("Bad Name"), "not a board name"),
    (lambda: registry.delete_board("main"), "cannot be deleted"),
    (lambda: registry.delete_board("nope"), "no board"),
    (lambda: registry.move("alpha", "nope"), "no board"),
    (lambda: registry.move("nope", "main"), "no registered project"),
])
def test_refusals(home, call, why):
    with pytest.raises(registry.BoardError, match=why):
        call()


def test_a_board_whose_file_is_gone_reads_as_main(home):
    registry.new_board("tmp")
    registry.move("alpha", "tmp")
    (home / "boards" / "tmp.toml").unlink()
    assert _on("alpha") == "main"


def test_cli(home, capsys):
    assert cli.main(["board", "new", "dv"]) == 0
    assert cli.main(["board", "move", "beta", "dv"]) == 0
    assert cli.main(["board"]) == 0
    out = capsys.readouterr().out
    assert "Moved beta from main to dv" in out and "dv" in out.splitlines()[-1]
    assert cli.main(["board", "rm", "main"]) == 4
    assert cli.main(["board", "rm", "dv"]) == 0
    assert "moved beta to main" in capsys.readouterr().out


@pytest.fixture
def client(home):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    return TestClient(create_app())


def test_dash_side_tab_and_board_pages(home, client):
    r = client.get("/")
    assert r.status_code == 200 and 'class="side"' in r.text and ">Inbox<" in r.text
    assert 'data-project="alpha"' not in r.text and "Delete board" not in r.text
    assert 'href="/b/main"><strong>main<' in r.text      # the Overview has a row per board
    r = client.post("/boards", data={"name": "rtl", "back": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/b/rtl?") \
        and "ok=1" in r.headers["location"]
    r = client.post("/boards", data={"name": "rtl", "back": "/b/rtl?msg=x"},
                    follow_redirects=False)
    assert r.headers["location"].startswith("/b/rtl?") and "ok=0" in r.headers["location"]
    r = client.post("/p/alpha/board", data={"board": "rtl", "back": "//evil.example/"},
                    follow_redirects=False)
    assert r.headers["location"].startswith("/p/alpha?") and "moved+alpha+from+main+to+rtl" in \
        r.headers["location"]
    page = client.get("/b/rtl").text
    assert 'data-project="alpha"' in page and 'data-project="beta"' not in page
    assert "Delete board" in page and "Tokens, last 7 days" not in page
    over = client.get("/").text
    assert 'href="/b/rtl"><strong>rtl<' in over
    assert 'value="rtl" selected' in client.get("/p/alpha/settings").text
    assert client.get("/b/nope").status_code == 404
    r = client.post("/b/rtl/delete", follow_redirects=False)
    assert r.headers["location"].startswith("/?") and "alpha+moved+to+main" in \
        r.headers["location"]
    assert _on("alpha") == "main" and client.get("/b/rtl").status_code == 404


def test_all_packets_table(home, client):
    registry.new_board("rtl")
    registry.move("beta", "rtl")
    r = client.get("/packets")
    assert r.status_code == 200 and 'id="pk"' in r.text and "packets.js" in r.text
    for p in ("alpha", "beta"):
        assert 'href="/p/%s"' % p in r.text
    assert 'data-board="rtl"' in r.text and 'data-board="main"' in r.text
    assert '<option value="rtl">' in r.text                   # the board filter
    assert 'class="item on" href="/packets"' in r.text
    assert 'data-filter' in r.text                            # typing does not stop live refresh


def test_all_packets_moves_ticked_packets_to_a_board(home, client):
    from urllib.parse import unquote_plus
    assert 'value="board"' not in client.get("/packets").text   # one board: nothing to move to
    registry.new_board("rtl")
    page = client.get("/packets").text
    assert 'name="board"' in page and 'value="board"' in page
    a, b = registry.get("alpha")["root"], registry.get("beta")["root"]
    picks = ["alpha/%s" % a, "alpha/%s" % a, "beta/%s" % b]
    r = client.post("/packets/bulk", data={"op": "board", "board": "rtl", "pick": picks},
                    follow_redirects=False)
    msg = unquote_plus(r.headers["location"])
    assert "ok=1" in msg and msg.count("moved project") == 2     # each project once
    assert _on("alpha") == "rtl" and _on("beta") == "rtl"
    r = client.post("/packets/bulk", data={"op": "board", "pick": picks}, follow_redirects=False)
    assert "pick a board" in unquote_plus(r.headers["location"])
    r = client.post("/packets/bulk", data={"op": "board", "board": "nope", "pick": picks[:1]},
                    follow_redirects=False)
    assert "ok=0" in r.headers["location"] and _on("alpha") == "rtl"
