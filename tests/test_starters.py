"""Starters (docs/starters-v1.md): ways to make a new packet, against a fake forge."""

import io
import json
import os
import urllib.parse

import pytest

from work_packet import forges, layout, project, registry, schema, starters
from work_packet.packet import Packet

from test_setup import git, home, source                       # noqa: F401

API = "https://forge.test/api/v1"


class Seen(list):
    """The requests a fake forge got; ``issues`` is its issues, to add to."""


@pytest.fixture
def forge(home, source, monkeypatch):
    """A Forgejo named "home" holding owner/dv-solve (cloned from ``source``) and
    two issues; the requests it got are in the returned list."""
    h = registry.home()
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "a") as fp:
        fp.write('\n[[forge]]\nname = "home"\nkind = "forgejo"\n'
                 'url = "https://forge.test"\ntoken_env = "FAKE_PAT"\n')
    monkeypatch.setenv("FAKE_PAT", "sekrit")
    repo = {"full_name": "owner/dv-solve", "description": "a solver",
            "clone_url": str(source), "ssh_url": "ssh://x", "html_url":
            "https://forge.test/owner/dv-solve", "default_branch": "main"}
    issues = {7: {"number": 7, "title": "Fix the off-by-one in count()", "state": "open",
                  "body": "count() returns n-1.", "html_url":
                  "https://forge.test/owner/dv-solve/issues/7", "comments": 1,
                  "user": {"login": "ann"}, "labels": [{"name": "bug"}]},
              8: {"number": 8, "title": "Docs", "state": "open", "body": "", "comments": 0,
                  "html_url": "https://forge.test/owner/dv-solve/issues/8",
                  "user": {"login": "bob"}, "labels": []}}
    seen = Seen()
    seen.issues = issues

    def get(url, headers, timeout=20):
        assert headers.get("Authorization") == "token sekrit"
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        seen.append((u.path, q))
        p = u.path[len("/api/v1"):]
        if p == "/repos/search":
            return {"ok": True, "data": [repo] if q.get("q", "") in "dv-solve" else []}
        if p == "/repos/owner/dv-solve":
            return repo
        if p == "/orgs/owner/repos":
            return [repo, dict(repo, full_name="owner/old", archived=True)]
        if p == "/repos/owner/dv-solve/issues":
            want = set(filter(None, q.get("labels", "").split(",")))
            return [i for i in issues.values() if q.get("q", "").lower() in i["title"].lower()
                    and want <= {x["name"] for x in i["labels"]}]
        if p.startswith("/repos/owner/dv-solve/issues/") and p.endswith("/comments"):
            return [{"user": {"login": "cy"}, "body": "Also in count_all().",
                     "created_at": "2026-10-01T00:00:00Z"}]
        if p.startswith("/repos/owner/dv-solve/issues/"):
            return issues[int(p.rsplit("/", 1)[1])]
        raise forges.ForgeError("%s: HTTP 404" % url)
    monkeypatch.setattr(forges, "_get", get)
    return seen


def test_registry_and_config():
    assert starters.names()[:3] == ["folder", "clone", "issue"]
    bad = schema.validate_config({"forge": [{"name": "x", "kind": "gitlab"},
                                            {"name": "y", "kind": "forgejo"}]})
    assert [p.field for p in bad] == ["forge[0].kind", "forge[1].url"]
    assert schema.validate_config({"forge": [{"name": "g", "kind": "github"}]}) == []


def test_parse(forge):
    assert forges.parse("home:owner/dv-solve#7") == ("home", "owner/dv-solve", 7)
    assert forges.parse("https://forge.test/owner/dv-solve/issues/7") == \
        ("home", "owner/dv-solve", 7)
    assert forges.parse("https://forge.test/owner/dv-solve.git") == \
        ("home", "owner/dv-solve", None)
    assert forges.parse("/some/path") is None


def test_clone_a_path(home, source, tmp_path):
    r = starters.from_values("clone", {"clone": str(source), "dir": str(tmp_path / "t"),
                                       "branch": "try-it"})
    assert r["name"] == "dv-solve" and r["hold"]
    plan = starters.make(r)
    folder = tmp_path / "t" / "dv-solve"
    assert plan.path == str(folder / ".work-packet")
    assert git(folder, "symbolic-ref", "--short", "HEAD") == "try-it"
    assert git(folder, "status", "--porcelain") == ""
    assert "origin" not in project.load_project(plan.path)


def test_from_an_issue(forge, source, tmp_path):
    st = starters.get("issue")
    assert [c["value"] for c in st.search("repo", "dv", {})] == ["home:owner/dv-solve"]
    got = st.search("issue", "off", {"repo": "home:owner/dv-solve"})
    assert [(c["value"], c["label"]) for c in got] == [
        ("home:owner/dv-solve#7", "#7 Fix the off-by-one in count()")]
    r = starters.from_values("issue", {"repo": "home:owner/dv-solve", "issue": "7",
                                       "dir": str(tmp_path)})
    assert r["name"] == "dv-solve-7"
    assert r["clone"] == {"url": str(source),
                          "branch": "wpk/7-fix-the-off-by-one-in-count"}
    lines = starters.preview(r)
    assert any("on branch wpk/7-" in ln for ln in lines) and lines[-1].startswith("held")
    plan = starters.make(r)
    folder = tmp_path / "dv-solve-7"
    assert git(folder, "symbolic-ref", "--short", "HEAD") == "wpk/7-fix-the-off-by-one-in-count"
    assert git(folder, "status", "--porcelain") == ""
    assert open(os.path.join(plan.path, "prompt.md")).read().startswith(
        "Resolve issue #7 in owner/dv-solve: Fix the off-by-one in count()\n")
    root = Packet(layout.run_dir(plan.path, plan.root))
    text = open(os.path.join(root.state_dir, "issue-7.md")).read()
    assert "count() returns n-1." in text and "Also in count_all()." in text
    assert root.load_status()[0]["reason"] == project.SETUP_REASON
    o = project.load_project(plan.path)["origin"]
    assert o["url"] == "https://forge.test/owner/dv-solve/issues/7" and o["number"] == 7
    # A pasted URL works without the repo field.
    r2 = starters.from_values("issue", {"issue": "https://forge.test/owner/dv-solve/issues/8",
                                        "dir": str(tmp_path)})
    assert r2["name"] == "dv-solve-8"


def test_failures_leave_nothing(forge, tmp_path):
    r = starters.from_values("clone", {"clone": "home:owner/dv-solve", "dir": str(tmp_path),
                                       "ref": "no-such-ref"})
    with pytest.raises(starters.StartError):
        starters.make(r)
    assert not os.path.exists(tmp_path / "dv-solve") and registry.get("dv-solve") is None
    with pytest.raises(starters.StartError, match="unknown recipe keys"):
        starters.check({"name": "x", "bogus": 1})
    with pytest.raises(starters.StartError, match="plain file name"):
        starters.check({"name": "x", "inputs": [{"name": "../x", "text": ""}]})
    with pytest.raises(starters.StartError, match="an issue"):
        starters.from_values("clone", {"clone": "home:owner/dv-solve#7"})


def test_cli(forge, tmp_path, monkeypatch, capsys):
    from work_packet import cli
    assert cli.main(["start"]) == 0
    assert "issue" in capsys.readouterr().out
    assert cli.main(["start", "issue", "--search", "issue", "repo=home:owner/dv-solve",
                     "issue=docs"]) == 0
    assert "home:owner/dv-solve#8" in capsys.readouterr().out
    assert cli.main(["start", "issue", "issue=home:owner/dv-solve#7", "dir=%s" % tmp_path,
                     "--dry-run", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"branch": "wpk/7-' in out and not os.path.exists(tmp_path / "dv-solve-7")
    recipe = {"name": "scripted", "dir": str(tmp_path), "objective": "Count to 3.",
              "inputs": [{"name": "notes.md", "text": "hi\n"}],
              "origin": {"kind": "cron", "title": "nightly"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(recipe)))
    assert cli.main(["start", "--recipe", "-", "--go"]) == 0
    e = registry.get("scripted")
    root = Packet(layout.run_dir(e["path"], e["root"]))
    assert root.load_status()[0]["state"] == "RUNNABLE"
    assert open(os.path.join(root.state_dir, "notes.md")).read() == "hi\n"


def test_dash(forge, tmp_path):
    from test_dash_tasks import _client
    c = _client()
    page = c.get("/new?starter=issue").text
    assert 'data-search="issue"' in page and "From an issue" in page
    got = c.get("/new/search", params={"starter": "issue", "field": "issue", "q": "",
                                       "repo": "home:owner/dv-solve"}).json()
    assert len(got["choices"]) == 2
    r = c.post("/new", data={"starter": "issue", "action": "preview", "dir": str(tmp_path),
                             "issue": "home:owner/dv-solve#7"})
    assert r.status_code == 200 and "on branch wpk/7-" in r.text and 'name="recipe"' in r.text
    import html
    import re
    rec = html.unescape(re.search(r'name="recipe" value="([^"]*)"', r.text).group(1))
    r = c.post("/new", data={"starter": "issue", "action": "create", "recipe": rec,
                             "name": "fix7", "objective": "Edited objective.\n"},
               follow_redirects=False)
    assert r.headers["location"].startswith("/p/fix7/compose"), r.headers["location"]
    e = registry.get("fix7")
    assert open(os.path.join(e["path"], "prompt.md")).read() == "Edited objective.\n"
    page = c.get("/p/fix7").text
    assert 'href="https://forge.test/owner/dv-solve/issues/7"' in page
    # A refusal on preview shows the form again with the error.
    r = c.post("/new", data={"starter": "issue", "action": "preview", "issue": "abc"})
    assert r.status_code == 200 and "Issue: " in r.text


def _watch_board(tmp_path, **kw):
    from work_packet import tomlio
    registry.new_board("solver")
    path = os.path.join(registry.boards_dir(), "solver.toml")
    b = tomlio.load_toml(path)
    b["watch"] = [dict({"name": "bugs", "repos": ["home:owner/dv-solve", "home:owner/other"],
                        "labels": ["bug"], "dir": str(tmp_path / "w")}, **kw)]
    tomlio.save_toml(path, b)


def test_watch(forge, tmp_path):
    from work_packet import watch
    _watch_board(tmp_path)
    [w] = watch.watchers()
    assert w["board"] == "solver" and watch.due(w)
    r = watch.poll(w, dry_run=True)
    # owner/other answers 404: an error, the rest goes on; issue 8 has no "bug" label.
    assert r["would"] == ["home:owner/dv-solve#7"] and len(r["errors"]) == 1
    assert registry.get("dv-solve-7") is None and watch.due(w)
    r = watch.poll(w)
    assert r["made"] == [("home:owner/dv-solve#7", "dv-solve-7")]
    e = registry.get("dv-solve-7")
    assert e["board"] == "solver"
    o = project.load_project(e["path"])["origin"]
    assert o["watch"] == "solver/bugs" and o["number"] == 7
    text = open(os.path.join(e["path"], "prompt.md")).read()
    assert "home:owner/other" in text                  # the board's other repos named
    assert not watch.due(w) and watch.due(w, now=10 ** 11)
    assert watch.poll(w)["made"] == []                 # seen: not made again
    # Lose the state file: the project's origin still says the issue is done.
    os.unlink(watch.state_path(w))
    assert watch.poll(w)["made"] == []
    # A new labelled issue is made on the next poll; a failure is kept and retried.
    forge.issues[9] = dict(forge.issues[7], number=9, title="Another",
                           html_url="https://forge.test/owner/dv-solve/issues/9")
    forge.issues[10] = dict(forge.issues[7], number=10, title="Clash",
                            html_url="https://forge.test/owner/dv-solve/issues/10")
    os.makedirs(tmp_path / "w" / "dv-solve-10" / "junk")
    r = watch.poll(w)
    assert [k for k, _ in r["made"]] == ["home:owner/dv-solve#9"]
    assert list(r["failed"]) == ["home:owner/dv-solve#10"]
    assert watch.load_state(w)["failed"]
    os.rmdir(tmp_path / "w" / "dv-solve-10" / "junk")
    os.rmdir(tmp_path / "w" / "dv-solve-10")
    r = watch.poll(w)
    assert [k for k, _ in r["made"]] == ["home:owner/dv-solve#10"]
    assert not watch.load_state(w)["failed"]


def test_watch_config_and_cli(forge, tmp_path, capsys):
    from work_packet import cli, watch
    assert [p.field for p in schema.validate_watches([{"name": "x", "repos": ["nope"]}])] \
        == ["watch[0].repos", "watch[0].dir"]
    assert schema.validate_watches([{"name": "x", "repos": ["a:b/c"], "dir": "d",
                                     "every": "10s"}])[0].field == "watch[0].every"
    _watch_board(tmp_path, every="1h", max_new=1, hold=False)
    assert cli.main(["watch"]) == 0
    assert "solver/bugs  every 1h  polled never" in capsys.readouterr().out
    assert cli.main(["watch", "poll", "solver/bugs", "--dry-run"]) == 1   # owner/other 404s
    assert "would make a packet for home:owner/dv-solve#7" in capsys.readouterr().out
    assert cli.main(["watch", "poll", "nope"]) != 0
    # A bad [[watch]] does not hide the board; it is listed with its problem.
    from work_packet import tomlio
    path = os.path.join(registry.boards_dir(), "solver.toml")
    b = tomlio.load_toml(path)
    b["watch"][0]["every"] = "soon"
    tomlio.save_toml(path, b)
    assert "solver" in [x["name"] for x in registry.boards()]
    assert watch.watchers()[0]["problems"]
    cli.main(["watch"])
    assert "bad [[watch]]" in capsys.readouterr().out


def test_watch_an_org_and_the_board_page(forge, tmp_path):
    from test_dash_tasks import _client
    from work_packet import watch
    _watch_board(tmp_path, repos=["home:owner/*"])
    [w] = watch.watchers()
    assert watch.poll(w, dry_run=True) == {"made": [], "would": ["home:owner/dv-solve#7"],
                                           "failed": {}, "errors": []}
    c = _client()
    page = c.get("/b/solver").text
    assert 'id="watchers"' in page and "home:owner/*" in page and "polled never" in page
    r = c.post("/b/solver/watch/bugs/poll", follow_redirects=False)
    assert r.status_code == 303 and "made+dv-solve-7" in r.headers["location"]
    assert registry.get("dv-solve-7")["board"] == "solver"
    page = c.get("/b/solver").text
    assert 'href="/p/dv-solve-7"' in page and "1 made" in page
    r = c.post("/b/solver/watch/nope/poll", follow_redirects=False)
    assert "ok=0" in r.headers["location"]
