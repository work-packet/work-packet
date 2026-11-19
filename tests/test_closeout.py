"""Closing packets (docs/close-remove-plan.md): what is outstanding, off the
board with history kept, and deleting a folder wpk made."""

import json
import os
import socket
import subprocess

import pytest

from work_packet import closeout, cli, history, layout, project, registry
from work_packet.packet import Packet


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True,
                          text=True).stdout


def _clone(tmp_path, name="f"):
    """A clone of a bare origin with one pushed commit."""
    bare = tmp_path / ("%s-origin.git" % name)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    f = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(bare), str(f)], check=True, capture_output=True)
    (f / "a").write_text("a\n")
    _git(f, "add", "a")
    _git(f, "commit", "-qm", "a")
    _git(f, "push", "-q", "origin", "HEAD:main")
    return f


def _packet(name, folder, made=None):
    extra = {"origin": {"made": made}} if made else None
    project.new(name, "Do it.", path=str(folder), packet=True, paused=True, extra=extra)
    return registry.get(name)


def _kinds(res, sev=None):
    return sorted(f["kind"] for f in res["findings"] if sev is None or f["severity"] == sev)


def _root(e):
    return Packet(layout.run_dir(e["path"], e["root"]))


# --- outstanding ------------------------------------------------------------------

def test_a_clean_clone_has_only_the_open_note(fake, tmp_path):
    e = _packet("pk", _clone(tmp_path))
    res = closeout.check(e)
    assert _kinds(res) == ["open"]                  # the card and .work-packet are not work
    assert closeout.code(res) == 1 and res["git"]


def test_changed_untracked_and_unpushed(fake, tmp_path):
    f = _clone(tmp_path)
    e = _packet("pk", f)
    (f / "a").write_text("b\n")
    _git(f, "commit", "-qam", "b")
    (f / "a").write_text("c\n")
    (f / "new").write_text("x\n")
    _git(f, "stash")
    (f / "a").write_text("d\n")
    res = closeout.check(e)
    assert _kinds(res, closeout.UNSAVED) == ["changed", "stash", "unpushed", "untracked"]
    un = next(x for x in res["findings"] if x["kind"] == "unpushed")
    assert un["n"] == 1 and un["branches"] == {"main": 1}
    assert closeout.code(res) == 2
    fp = res["fp"]
    assert closeout.check(e)["fp"] == fp
    (f / "new2").write_text("y\n")
    assert closeout.check(e)["fp"] != fp            # one more new file


def test_nested_repos_and_plain_folders(fake, tmp_path):
    f = _clone(tmp_path)
    inner = f / "packages" / "dep"
    inner.mkdir(parents=True)
    _git(inner, "init", "-q", "-b", "main")
    (inner / "x").write_text("x\n")
    _git(inner, "add", "x")
    _git(inner, "commit", "-qm", "x")
    (f / ".gitignore").write_text("packages/\n")
    _git(f, "add", ".gitignore")
    _git(f, "commit", "-qm", "ignore")
    _git(f, "push", "-q", "origin", "HEAD:main")
    e = _packet("pk", f)
    res = closeout.check(e)
    assert [r["path"] for r in res["repos"]] == [".", "packages/dep"]
    f2 = next(x for x in res["findings"] if x["kind"] == "unpushed")
    assert f2["repo"] == "packages/dep" and "no remote" in f2["msg"]

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "notes.txt").write_text("n\n")
    e2 = _packet("pl", plain)
    res = closeout.check(e2)
    assert not res["git"] and _kinds(res, closeout.UNSAVED) == ["no-git"]


def test_a_worktree_keeps_its_commits_in_its_repo(fake, tmp_path):
    f = _clone(tmp_path)
    wt = tmp_path / "wt"
    _git(f, "worktree", "add", "-q", "-b", "side", str(wt))
    (wt / "s").write_text("s\n")
    _git(wt, "add", "s")
    _git(wt, "commit", "-qm", "s")
    e = _packet("pk", wt)
    res = closeout.check(e)
    assert "unpushed" not in _kinds(res) and "kept" in _kinds(res, closeout.NOTE)


def test_busy_a_running_step_and_open_children(fake, tmp_path):
    e = _packet("pk", _clone(tmp_path))
    pkt = _root(e)
    with open(pkt.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 1,
                   "attempt": 1, "expires": "2999-01-01T00:00:00Z"}, fp)
    assert "running" in _kinds(closeout.check(e), closeout.BUSY)
    with pytest.raises(closeout.CloseError, match="busy"):
        closeout.close(e)
    os.unlink(pkt.lease_path)
    kid = tmp_path / "kid"
    project.new("kid", "Do it.", path=str(kid), packet=True, paused=True,
                extra={"origin": {"by": "packet:%s" % e["root"]}})
    res = closeout.check(e)
    ch = next(x for x in res["findings"] if x["kind"] == "children")
    assert ch["severity"] == closeout.BUSY and ch["names"] == ["kid"]


def test_cli_outstanding(fake, tmp_path, capsys):
    f = _clone(tmp_path)
    _packet("pk", f)
    (f / "new").write_text("x\n")
    assert cli.main(["outstanding", "pk"]) == 2
    assert "1 new file not in git" in capsys.readouterr().out
    assert cli.main(["outstanding", "--all"]) == 2
    assert cli.main(["outstanding", "pk", "--json"]) == 2
    assert json.loads(capsys.readouterr().out.split("\n", 1)[1])["name"] == "pk"


# --- whose folder -----------------------------------------------------------------

def test_made_says_whose_folder_it_is(fake, tmp_path):
    assert closeout.origin(_packet("a", tmp_path / "fresh")).get("made") == "new"
    assert closeout.owned(registry.get("a"))
    assert closeout.origin(_packet("b", _clone(tmp_path))).get("made") == "adopted"
    assert not closeout.owned(registry.get("b"))


# --- close ------------------------------------------------------------------------

def test_close_keeps_the_folder_and_the_history(fake, tmp_path):
    f = _clone(tmp_path)
    e = _packet("pk", f)
    (f / "new").write_text("x\n")                   # unsaved does not block a close
    rec = closeout.close(e, by="me", note="finished")
    assert registry.get("pk") is None and os.path.isdir(f)
    assert rec["lifecycle"] == "done" and rec["by"] == "me" and not rec.get("deleted")
    assert rec["id"].startswith("pk@") and "new file" in rec["summary"]
    assert [r["id"] for r in closeout.closed()] == [rec["id"]]
    con = history.connect()
    try:
        assert history.harvested(con, "pk") == [e["root"]]
    finally:
        con.close()
    last = _root(e).journal().records[-1]
    assert last["op"] == "closed" and last["note"] == "finished"
    with pytest.raises(closeout.CloseError, match="no closed packet"):
        closeout.reopen("nope@0")
    back = closeout.reopen(rec["id"])
    assert registry.get("pk")["path"] == back["path"] and closeout.closed() == []


def test_close_drop_and_stop(fake, tmp_path):
    e = _packet("pk", _clone(tmp_path))
    rec = closeout.close(e, drop=True, stop=True)
    assert rec["lifecycle"] == "dropped" and rec["stopped"] == []


def test_a_changed_check_refuses(fake, tmp_path):
    f = _clone(tmp_path)
    e = _packet("pk", f)
    fp = closeout.check(e)["fp"]
    (f / "new").write_text("x\n")
    with pytest.raises(closeout.CloseError, match="changed since"):
        closeout.close(e, fp=fp)
    assert registry.get("pk") is not None


def test_rm_keeps_history_and_forget_does_not(fake, tmp_path, capsys):
    _packet("pk", _clone(tmp_path))
    assert cli.main(["rm", "pk"]) == 0
    rec = closeout.closed()[0]
    assert rec["lifecycle"] == "open"               # rm leaves the lifecycle alone
    assert cli.main(["closed", "reopen", "pk"]) == 0
    assert cli.main(["rm", "pk", "--forget"]) == 0
    assert registry.get("pk") is None and closeout.closed() == []


# --- delete -----------------------------------------------------------------------

def test_delete_refuses_a_folder_wpk_did_not_make(fake, tmp_path):
    f = _clone(tmp_path)
    e = _packet("pk", f)
    with pytest.raises(closeout.CloseError, match="did not make"):
        closeout.close(e, delete=True, force=True)
    assert registry.get("pk") is not None and os.path.isdir(f)


def test_delete_bundles_commits_and_refuses_files(fake, tmp_path):
    f = _clone(tmp_path)
    e = _packet("pk", f, made="new")
    (f / "a").write_text("b\n")
    _git(f, "commit", "-qam", "unpushed")
    (f / "new").write_text("x\n")
    with pytest.raises(closeout.CloseError, match="1 new file"):
        closeout.close(e, delete=True)
    os.unlink(f / "new")
    rec = closeout.close(e, delete=True)            # the commit alone does not block
    assert rec["deleted"] and not os.path.exists(f)
    (b,) = rec["bundles"]
    assert b["repo"] == "." and b["commits"] == 1
    back = tmp_path / "back"                        # restore: clone, fetch the bundle
    subprocess.run(["git", "clone", "-q", b["remote"], str(back)], check=True,
                   capture_output=True)
    _git(back, "fetch", "-q", b["file"], "main:kept")
    assert _git(back, "show", "kept:a") == "b\n"
    with pytest.raises(closeout.CloseError, match="gone"):
        closeout.reopen(rec["id"])


def test_delete_a_kept_folder_later(fake, tmp_path, capsys):
    folder = tmp_path / "fresh"
    e = _packet("pk", folder)
    (folder / "x").write_text("x\n")
    rec = closeout.close(e)
    assert cli.main(["closed", "delete", rec["id"]]) == 4    # not in git: needs force
    assert "not in git" in capsys.readouterr().err
    assert cli.main(["closed", "delete", rec["id"], "--force"]) == 0
    assert not os.path.exists(folder) and closeout.get_closed(rec["id"])["deleted"]


def test_cli_close(fake, tmp_path, capsys):
    folder = tmp_path / "fresh"
    _packet("pk", folder)
    (folder / "notes.txt").write_text("n\n")       # yours, and in no git
    assert cli.main(["close", "pk", "--delete"]) == 4
    assert cli.main(["close", "pk", "--delete", "--force", "-m", "bye"]) == 0
    assert "deleted" in capsys.readouterr().err and not os.path.exists(folder)


# --- the board ----------------------------------------------------------------------

def _web():
    from test_dash_tasks import _client
    return _client()


def _msg(r):
    from test_dash_tasks import _flash
    return _flash(r)


def test_the_close_page_shows_findings_and_closes(fake, tmp_path):
    f = _clone(tmp_path)
    e = _packet("pk", f)
    (f / "new").write_text("x\n")
    c = _web()
    assert "/p/pk/close" in c.get("/p/pk/%s" % e["root"]).text      # Close… on the page
    page = c.get("/p/pk/close").text
    assert "1 new file not in git" in page and "yours (wpk did not make it)" in page
    assert 'value="delete"' not in page                             # not wpk's folder
    fp = closeout.cached("pk")["fp"]
    (f / "new2").write_text("y\n")
    r = c.post("/p/pk/close", data={"mode": "close", "fp": fp}, follow_redirects=False)
    msg, ok = _msg(r)
    assert not ok and "changed since" in msg
    fp = closeout.check(e)["fp"]
    r = c.post("/p/pk/close", data={"mode": "close", "fp": fp, "lifecycle": "drop",
                                    "note": "not needed"}, follow_redirects=False)
    msg, ok = _msg(r)
    assert ok and msg == "closed pk", msg
    rec = closeout.closed()[0]
    import urllib.parse
    assert urllib.parse.unquote(r.headers["location"]).startswith("/closed/%s" % rec["id"])
    assert rec["lifecycle"] == "dropped" and rec["note"] == "not needed"
    assert "pk" in c.get("/closed").text
    one = c.get("/closed/%s" % rec["id"]).text
    assert "Reopen" in one and "wpk did not make this folder" in one
    r = c.post("/closed/%s" % rec["id"], data={"op": "reopen"}, follow_redirects=False)
    assert _msg(r)[1] and registry.get("pk") is not None


def test_close_and_delete_from_the_board(fake, tmp_path):
    folder = tmp_path / "fresh"
    e = _packet("pk", folder)
    (folder / "x").write_text("x\n")
    c = _web()
    page = c.get("/p/pk/close?delete=1").text
    assert "Close and delete folder" in page and 'name="need_ack"' in page
    fp = closeout.cached("pk")["fp"]
    r = c.post("/p/pk/close", data={"mode": "delete", "fp": fp, "need_ack": "1"},
               follow_redirects=False)
    assert "tick the box" in _msg(r)[0] and os.path.isdir(folder)
    r = c.post("/p/pk/close", data={"mode": "delete", "fp": fp, "need_ack": "1", "ack": "1"},
               follow_redirects=False)
    msg, ok = _msg(r)
    assert ok and "deleting its folder" in msg, msg
    from test_dash_tasks import _wait
    assert _wait(lambda: closeout.closed()[0].get("deleted"))   # in the background
    assert not os.path.exists(folder)
    rec = closeout.closed()[0]
    assert "deleting" not in rec
    assert "deleted" in c.get("/closed/%s" % rec["id"]).text
    r = c.post("/closed/%s" % rec["id"], data={"op": "forget"}, follow_redirects=False)
    assert _msg(r)[1] and closeout.closed() == []


def test_done_cards_get_chips_and_close_clean(fake, tmp_path):
    from work_packet import executor
    clean = _packet("clean", _clone(tmp_path, "c1"))
    dirty_f = _clone(tmp_path, "d1")
    dirty = _packet("dirty", dirty_f)
    (dirty_f / "new").write_text("x\n")
    for e in (clean, dirty):
        executor.mark(_root(e), "done")
        closeout.check(e)
    c = _web()
    page = c.get("/b/main").text
    assert "Close clean (1)" in page and 'cl-chip uncommitted' in page
    ov = c.get("/").text
    assert "READY TO CLOSE" in ov and "NOT SAVED" in ov and "done, but: uncommitted" in ov
    r = c.post("/b/main/close-clean", data={"pick": ["clean"]}, follow_redirects=False)
    assert _msg(r) == ("closed clean", True)
    assert registry.get("clean") is None and registry.get("dirty") is not None
    r = c.post("/packets/bulk", data={"op": "close", "pick": "dirty/%s" % dirty["root"]},
               follow_redirects=False)
    msg, ok = _msg(r)
    assert not ok and "dirty skipped" in msg and "new file" in msg


def test_check_json(fake, tmp_path):
    _packet("pk", _clone(tmp_path))
    j = _web().get("/p/pk/check").json()
    assert j["name"] == "pk" and j["counts"]["note"] == 1


def test_a_closed_packets_pages_stay_readable(fake, tmp_path):
    kept = _packet("kept", _clone(tmp_path, "k"))
    gone_f = tmp_path / "gone"
    gone = _packet("gone", gone_f)
    closeout.close(kept)
    rec = closeout.close(gone, delete=True)
    assert not os.path.exists(gone_f)
    c = _web()
    for name, e in (("kept", kept), ("gone", gone)):
        page = c.get("/p/%s" % name)
        assert page.status_code == 200 and "Closed: off every board" in page.text, name
        assert c.get("/p/%s/%s" % (name, e["root"])).status_code == 200
        r = c.post("/p/%s/%s/act" % (name, e["root"]), data={"action": "reopen"},
                   follow_redirects=False)
        assert r.status_code == 409 and "closed" in r.text
    assert "its pages" in c.get("/closed/%s" % rec["id"]).text
    assert "kept" not in c.get("/b/main").text            # off the board


def test_stats_keep_a_closed_packets_cost(fake, tmp_path):
    from test_dash_tasks import _new
    from work_packet import scheduler
    e, pkt = _new("spent")
    scheduler.tick([e], until_idle=True)
    c = _web()
    assert "spent" in c.get("/stats?days=30").text
    rec = closeout.close(e)
    page = c.get("/stats?days=30").text
    assert "spent" in page and "/closed/%s" % rec["id"].replace("@", "%40") in page


def test_delete_a_kept_folder_from_the_board(fake, tmp_path):
    from test_dash_tasks import _wait
    folder = tmp_path / "fresh"
    e = _packet("pk", folder)
    rec = closeout.close(e)
    c = _web()
    page = c.get("/closed/%s?delete=1" % rec["id"]).text
    assert 'value="delete"' in page and "Reopen" in page
    held = closeout.delete_folder(rec, rm_later=True)            # what the board does first
    assert held["deleting"] and os.path.isdir(folder)
    assert "deleting…" in c.get("/closed/%s" % rec["id"]).text
    with pytest.raises(closeout.CloseError, match="being deleted"):
        closeout.reopen(rec["id"])
    closeout.delete_folder(held, _checked=True)
    assert not os.path.exists(folder) and "deleting" not in closeout.get_closed(rec["id"])

    e = _packet("pk2", tmp_path / "fresh2")
    rec = closeout.close(e)
    r = c.post("/closed/%s" % rec["id"], data={"op": "delete"}, follow_redirects=False)
    assert _msg(r)[1]
    assert _wait(lambda: closeout.get_closed(rec["id"]).get("deleted"))
    assert not os.path.exists(tmp_path / "fresh2")


def test_with_children_closes_them_first(fake, tmp_path):
    e = _packet("pa", _clone(tmp_path, "pa"))
    project.new("kid", "Do it.", path=str(tmp_path / "kid"), packet=True, paused=True,
                extra={"origin": {"by": "packet:%s" % e["root"]}})
    with pytest.raises(closeout.CloseError, match="kid"):
        closeout.close(e)
    c = _web()
    page = c.get("/p/pa/close").text
    assert 'name="with_children"' in page
    fp = closeout.cached("pa")["fp"]
    r = c.post("/p/pa/close", data={"mode": "close", "fp": fp, "with_children": "1"},
               follow_redirects=False)
    msg, ok = _msg(r)
    assert ok and "closed kid" in msg, msg
    assert registry.get("kid") is None and registry.get("pa") is None
    assert sorted(r["name"] for r in closeout.closed()) == ["kid", "pa"]
