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
    seen = []

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
        if p == "/repos/owner/dv-solve/issues":
            return [i for i in issues.values() if q.get("q", "").lower() in i["title"].lower()]
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
