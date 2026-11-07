"""Starters (docs/starters-v1.md): ways to make a new packet, against a fake forge."""

import io
import json
import os
import urllib.parse

import pytest

from work_packet import forges, layout, project, registry, schema, setup, starters
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
    seen.pulls = []

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
        if p == "/repos/owner/dv-solve/pulls":
            return list(reversed(seen.pulls))
        if p.startswith("/repos/owner/dv-solve/issues/") and p.endswith("/comments"):
            return [{"user": {"login": "cy"}, "body": "Also in count_all().",
                     "created_at": "2026-10-01T00:00:00Z"}]
        if p.startswith("/repos/owner/dv-solve/issues/"):
            return issues[int(p.rsplit("/", 1)[1])]
        raise forges.ForgeError("%s: HTTP 404" % url)
    def post(url, headers, body, timeout=30):
        assert headers.get("Authorization") == "token sekrit"
        p = urllib.parse.urlparse(url).path[len("/api/v1"):]
        seen.append(("POST " + p, body))
        assert p == "/repos/owner/dv-solve/pulls"
        n = 100 + len(seen.pulls)
        pr = {"number": n, "html_url": "https://forge.test/owner/dv-solve/pulls/%d" % n,
              "state": "open", "title": body["title"], "head": {"ref": body["head"]},
              "base": {"ref": body["base"]}, "body": body["body"]}
        seen.pulls.append(pr)
        return pr
    monkeypatch.setattr(forges, "_get", get)
    monkeypatch.setattr(forges, "_post", post)
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
    root = registry.get("fix7")["root"]                  # nothing started: its page
    assert r.headers["location"].startswith("/p/fix7/%s?" % root), r.headers["location"]
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
                                           "failed": {}, "errors": [], "proposed": [], "dates": []}
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


def _finish(e, outcome="Fixed count()", body="Changed count() to return n."):
    """As if the packet's last step completed with a report."""
    from work_packet import frontmatter
    pkt = Packet(layout.run_dir(e["path"], e["root"]))
    meta, b = pkt.load_status()
    meta["state"] = "COMPLETED"
    pkt.save_status(meta, b)
    with open(os.path.join(pkt.path, "report.md"), "w") as f:
        f.write(frontmatter.dump({"outcome": outcome, "deliverables": [
            {"path": "count.py", "what": "the fix"}]}, body + "\n"))


def test_pr(forge, tmp_path, source, capsys):
    from work_packet import cli, pr
    from test_setup import git
    plan = starters.make(starters.from_values("issue", {
        "issue": "home:owner/dv-solve#7", "dir": str(tmp_path / "w"), "hold": "yes"}))
    e = registry.get(plan.name)
    folder = layout.packet_folder(e["path"])
    with pytest.raises(pr.PRError, match="no commits beyond main"):
        pr.open_pr(e["name"])
    (tmp_path / "w" / plan.name / "count.py").write_text("def count(n): return n\n")
    git(folder, "add", "count.py")
    git(folder, "commit", "-q", "-m", "fix count")
    (tmp_path / "w" / plan.name / "README.md").write_text("changed\n")
    with pytest.raises(pr.PRError, match="not committed.*README.md"):
        pr.open_pr(e["name"])
    git(folder, "checkout", "README.md")
    _finish(e)
    r = pr.open_pr(e["name"], dry_run=True)
    assert r["branch"].startswith("wpk/7-") and r["base"] == "main" and r["ahead"] == 1
    assert r["title"] == "Fix the off-by-one in count()"
    assert r["body"].startswith("Closes #7.") and "Changed count()" in r["body"]
    assert "`count.py`: the fix" in r["body"] and not forge.pulls
    assert cli.main(["pr", e["name"]]) == 0
    assert "opened pull request: https://forge.test/owner/dv-solve/pulls/100" in \
        capsys.readouterr().out
    assert git(source, "rev-parse", r["branch"]) == git(folder, "rev-parse", "HEAD")
    rec = project.load_project(e["path"])["pr"]
    assert rec["number"] == 100 and rec["base"] == "main"
    [p] = forge.pulls
    assert p["head"]["ref"] == r["branch"] and p["base"]["ref"] == "main"
    # Again, after another commit: pushed, the same pull request found.
    (tmp_path / "w" / plan.name / "count.py").write_text("def count(n):\n    return n\n")
    git(folder, "commit", "-qam", "tidy")
    r2 = pr.open_pr(e["name"])
    assert not r2["new"] and r2["number"] == 100 and len(forge.pulls) == 1
    assert git(source, "rev-parse", r["branch"]) == git(folder, "rev-parse", "HEAD")
    # The dashboard's button: the same, said in the flash.
    from test_dash_tasks import _client
    got = _client().post("/p/%s/pr" % e["name"], follow_redirects=False)
    assert got.status_code == 303 and "already+open" in got.headers["location"]
    # A project not from a forge is refused with the reason.
    other = project.new("plain", None, path=str(tmp_path / "plain"), packet=True)
    with pytest.raises(pr.PRError, match="did not come from a forge"):
        pr.open_pr(other.name)


def test_pr_by_a_watcher_and_the_page(forge, tmp_path):
    from work_packet import pr, watch
    from test_dash_tasks import _client
    from test_setup import git
    _watch_board(tmp_path, pr="draft")
    [w] = watch.watchers()
    [(_, name)] = watch.poll(w)["made"]
    e = registry.get(name)
    folder = layout.packet_folder(e["path"])
    assert pr.sync() == 0                              # not completed yet
    _finish(e)
    assert pr.sync() == 0                              # completed, nothing committed: kept
    assert "nothing to hand off" in watch.load_state(w)["pr_failed"][name]
    (tmp_path / "w" / name / "count.py").write_text("x\n")
    git(folder, "add", "count.py")
    git(folder, "commit", "-q", "-m", "fix")
    assert pr.sync() == 0                              # a failure is not retried by itself
    pr.forget_failure(name)
    assert pr.sync() == 1 and forge.pulls[0]["title"].startswith("WIP: ")
    assert pr.sync() == 0 and len(forge.pulls) == 1    # recorded: not opened twice
    assert schema.validate_watches([{"name": "x", "repos": ["a:b/c"], "dir": "d",
                                     "pr": "yes"}])[0].field == "watch[0].pr"
    page = _client().get("/p/%s" % name).text
    assert "pull request #100" in page and "Push to PR #100" in page


def test_new_packet_on_a_board(forge, tmp_path):
    from test_dash_tasks import _client
    registry.new_board("solver")
    with pytest.raises(starters.StartError, match="no board named nope"):
        starters.preview(starters.from_values("folder", {
            "name": "x", "dir": str(tmp_path), "board": "nope"}))
    r = starters.from_values("folder", {"name": "a1", "dir": str(tmp_path), "board": "solver"})
    assert "on board solver" in starters.preview(r)[0]
    starters.make(r)
    assert registry.get("a1")["board"] == "solver"
    c = _client()
    assert 'href="/new?board=solver"' in c.get("/b/solver").text      # the board's context
    page = c.get("/new?board=solver").text
    assert '<option value="solver" selected>' in page
    assert "board=solver" in page.split('class="tabs"')[1].split("</nav>")[0]
    got = c.post("/new", data={"starter": "folder", "name": "a2", "dir": str(tmp_path),
                               "board": "solver", "action": "create"}, follow_redirects=False)
    assert got.status_code == 303 and registry.get("a2")["board"] == "solver"


FAKE_IVPM = r"""#!%(python)s
# Stand-in for ivpm. `update` records the branch it ran on, then fills packages/;
# `clone` records its arguments, clones and checks out as ivpm does, prints the
# transcript ivpm does, and updates when there is an ivpm.yaml. IVPM_FAIL fails
# the dependencies.
import os, subprocess, sys
a, log = sys.argv[1:], %(log)r
def git(*args, cwd=None):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True).returncode
def deps(where):
    with open(log, "w") as f:
        f.write(subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=where,
                               capture_output=True, text=True).stdout)
    print(">> dep (git)", flush=True)
    if os.environ.get("IVPM_FAIL"):
        print("fetch failed: no route to host", file=sys.stderr, flush=True)
        print("<< dep (ivpm.yaml:3:5) ERROR: no route to host", flush=True)
        sys.exit(1)
    os.makedirs(os.path.join(where, "packages", "python"))
    open(os.path.join(where, "packages", "python", "marker"), "w").close()
    print("<< dep (0.1s)", flush=True)
    print(">> [Installing Python packages]", flush=True)
    print("   Installing package set 1/1 (1/1)", flush=True)
    print("<< [Installing Python packages] (0.1s)", flush=True)
if a == ["--version"]:
    print("2.40.2")
elif a[:1] == ["update"]:
    deps(".")
elif a[:1] == ["clone"]:
    with open(log + ".clone", "a") as f:
        f.write(" ".join(a[1:-2]) + "\n")
    src, dst = a[-2:]
    print(">> [clone] (git)", flush=True)
    sys.stdout.write("Receiving objects:  50%% (1/2)\rReceiving objects: 100%% (2/2), done.\n")
    if git("clone", "-q", src, dst):
        print("<< [clone] ERROR: Git clone failed (git exit 128)", flush=True)
        sys.exit(1)
    if "-b" in a:
        b = a[a.index("-b") + 1]
        if git("switch", "-q", b, cwd=dst):
            git("switch", "-q", "-c", b, cwd=dst)
    rev = a[a.index("-r") + 1] if "-r" in a else None
    if rev and git("checkout", "-q", "--detach", rev, cwd=dst) and \
            git("checkout", "-q", "--detach", "origin/" + rev, cwd=dst):
        print("<< [clone] ERROR: no such revision", flush=True)
        sys.exit(1)
    print("<< [clone] (0.1s)", flush=True)
    if os.path.exists(os.path.join(dst, "ivpm.yaml")):
        deps(dst)
else:
    sys.exit(2)
"""


@pytest.fixture
def fake_ivpm(tmp_path, monkeypatch):
    """A fake ``ivpm`` first on PATH; returns the file it logs the branch to (and
    ``<that>.clone``, the arguments of each clone)."""
    import sys
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "ivpm.log"
    (bin_ / "ivpm").write_text(FAKE_IVPM % {"log": str(log), "python": sys.executable})
    (bin_ / "ivpm").chmod(0o755)
    monkeypatch.setenv("PATH", "%s:%s" % (bin_, os.environ["PATH"]))
    monkeypatch.delitem(setup._IVPM_VERSION, "v", raising=False)   # asked again
    return log


def _ivpm_source(source):
    (source / "ivpm.yaml").write_text("package:\n  name: dv-solve\n")
    git(source, "add", "ivpm.yaml")
    git(source, "commit", "-q", "-m", "ivpm")


def test_a_clone_with_an_ivpm_yaml_gets_its_dependencies(home, source, tmp_path, fake_ivpm):
    _ivpm_source(source)
    r = starters.from_values("clone", {"clone": str(source), "dir": str(tmp_path / "t"),
                                       "branch": "try-it"})
    starters.make(r)
    folder = tmp_path / "t" / "dv-solve"
    assert (folder / "packages" / "python" / "marker").exists()
    assert fake_ivpm.read_text().strip() == "try-it"          # after the branch checkout
    assert git(folder, "status", "--porcelain") == ""


def test_a_clone_without_an_ivpm_yaml_is_not_updated(home, source, tmp_path, fake_ivpm):
    r = starters.from_values("clone", {"clone": str(source), "dir": str(tmp_path / "t")})
    starters.make(r)
    assert not fake_ivpm.exists()
    assert not (tmp_path / "t" / "dv-solve" / "packages").exists()


def test_a_failed_ivpm_update_leaves_nothing(home, source, tmp_path, fake_ivpm, monkeypatch):
    _ivpm_source(source)
    monkeypatch.setenv("IVPM_FAIL", "1")
    r = starters.from_values("clone", {"clone": str(source), "dir": str(tmp_path / "t")})
    with pytest.raises(starters.StartError, match="(?s)ivpm update .* failed:\n.*no route to host"):
        starters.make(r)
    assert not (tmp_path / "t" / "dv-solve").exists()


# --- the clone tool and progress (dash-create-progress-design.md) -----------------------

def _make(r):
    seen = []
    plan = starters.make(r, progress=seen.append)
    return plan, seen


def _steps(seen):
    return [(e["id"], e["state"]) for e in seen if e["k"] == "step"]


def _head(folder):
    import subprocess
    return subprocess.run(["git", "-C", str(folder), "symbolic-ref", "-q", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip() or None


def _with_ivpm(r):
    r["clone"]["tool"] = "ivpm"
    return r


def test_ivpm_clone_fetches_the_dependencies_in_one(home, source, tmp_path, fake_ivpm):
    _ivpm_source(source)
    r = _with_ivpm(starters.from_values("clone", {"clone": str(source),
                                                  "dir": str(tmp_path / "t")}))
    assert "with ivpm" in " ".join(starters.preview(r))
    plan, seen = _make(r)
    folder = tmp_path / "t" / "dv-solve"
    assert (folder / "packages" / "python" / "marker").exists()
    assert (tmp_path / "ivpm.log.clone").read_text() == "\n"           # no ref options
    assert _steps(seen) == [("clone", "run"), ("clone", "ok"), ("deps", "run"),
                            ("deps", "ok"), ("files", "run"), ("files", "ok")]
    assert {"k": "tool", "name": "ivpm", "version": "2.40.2"} in seen
    pk = [(e["name"], e["state"], e["step"]) for e in seen if e["k"] == "pkg"]
    assert pk == [("[clone]", "run", "clone"), ("[clone]", "ok", "clone"),
                  ("dep", "run", "deps"), ("dep", "ok", "deps")]
    g = [e for e in seen if e["k"] == "git"]
    assert [(e["pct"], e["pkg"]) for e in g] == [(50, "[clone]"), (100, "[clone]")]
    assert {"k": "line", "step": "clone", "text": ">> [clone] (git)"} in seen
    tk = [(e["step"], e["at"], e["total"], e["state"]) for e in seen if e["k"] == "task"]
    assert tk == [("deps", None, None, "run"), ("deps", 1, 1, "run"), ("deps", 1, 1, "ok")]
    assert git(folder, "status", "--porcelain") == ""


def test_ivpm_clone_of_a_repo_without_an_ivpm_yaml(home, source, tmp_path, fake_ivpm):
    r = _with_ivpm(starters.from_values("clone", {"clone": str(source),
                                                  "dir": str(tmp_path / "t")}))
    plan, seen = _make(r)
    assert _steps(seen)[:4] == [("clone", "run"), ("clone", "ok"), ("deps", "run"),
                                ("deps", "skip")]
    assert not fake_ivpm.exists()


@pytest.mark.parametrize("ref,branch,args,head", [
    (None, "try-it", "-b try-it", "try-it"),                     # a new branch
    (None, "feat", "-b feat", "feat"),                           # carried on
    ("feat", None, "-r feat", "feat"),                           # a branch as the ref
    ("v1", None, "-r v1", None),                                 # a tag: detached
    ("v1", "try-it", "-r v1", "try-it"),                         # a new branch at a ref
    ("v1", "feat", "-b feat", "feat"),                           # the existing one wins
])
def test_ivpm_clone_ref_and_branch(home, source, tmp_path, fake_ivpm, ref, branch, args, head):
    git(source, "branch", "feat")
    git(source, "tag", "v1")
    vals = {"clone": str(source), "dir": str(tmp_path / "t")}
    vals.update({k: v for k, v in (("ref", ref), ("branch", branch)) if v})
    r = _with_ivpm(starters.from_values("clone", vals))
    plan, seen = _make(r)
    folder = tmp_path / "t" / "dv-solve"
    assert (tmp_path / "ivpm.log.clone").read_text().strip() == args
    assert _head(folder) == head
    # the same as the git tool does
    r2 = starters.from_values("clone", dict(vals, name="git-" + "x"))
    starters.make(r2)
    assert _head(tmp_path / "t" / "git-x") == head


def test_a_failed_ivpm_clone_leaves_nothing(home, source, tmp_path, fake_ivpm, monkeypatch):
    _ivpm_source(source)
    monkeypatch.setenv("IVPM_FAIL", "1")
    r = _with_ivpm(starters.from_values("clone", {"clone": str(source),
                                                  "dir": str(tmp_path / "t")}))
    seen = []
    with pytest.raises(starters.StartError, match="(?s)ivpm clone .* failed:\n.*no route"):
        starters.make(r, progress=seen.append)
    assert not (tmp_path / "t" / "dv-solve").exists()
    assert _steps(seen) == [("clone", "run"), ("clone", "ok"), ("deps", "run"),
                            ("deps", "fail")]
    assert seen[-1] == {"k": "undo", "folder": str(tmp_path / "t" / "dv-solve")}
    assert [e["error"] for e in seen if e["k"] == "pkg" and e["state"] == "fail"] == \
        ["no route to host"]


def test_the_clone_tool(home, source, tmp_path, fake_ivpm, monkeypatch):
    c = {"url": str(source)}
    assert starters.clone_tool(c) == ("git", None)          # the tests' default
    monkeypatch.setitem(schema.CONFIG_DEFAULTS, "clone_tool", "ivpm")
    assert starters.clone_tool(c) == ("ivpm", None)
    os.makedirs(registry.home(), exist_ok=True)
    with open(os.path.join(registry.home(), "config.toml"), "a") as fp:
        fp.write('clone_tool = "git"\n')
    assert starters.clone_tool(c) == ("git", None)
    assert starters.clone_tool(dict(c, tool="ivpm")) == ("ivpm", None)
    tool, why = starters.clone_tool(dict(c, tool="ivpm", share=["packages"]))
    assert tool == "git" and "shares" in why
    monkeypatch.setattr(setup, "ivpm_exe", lambda: None)
    assert starters.clone_tool(dict(c, tool="ivpm")) == ("git", "ivpm is not installed")
    with pytest.raises(starters.StartError, match="tool is one of"):
        starters.check({"name": "x", "clone": {"url": "u", "tool": "svn"}})
    assert [p.field for p in schema.validate_config({"clone_tool": "svn"})] == ["clone_tool"]


def test_git_tool_progress(home, source, tmp_path, fake_ivpm):
    _ivpm_source(source)
    r = starters.from_values("clone", {"clone": str(source), "dir": str(tmp_path / "t"),
                                       "branch": "try-it"})
    plan, seen = _make(r)
    assert _steps(seen) == [("clone", "run"), ("clone", "ok"), ("branch", "run"),
                            ("branch", "ok"), ("deps", "run"), ("deps", "ok"),
                            ("files", "run"), ("files", "ok")]
    assert [e["name"] for e in seen if e["k"] == "pkg"] == ["dep", "dep"]
    assert any(e["k"] == "line" and e["step"] == "clone" and "Cloning into" in e["text"]
               for e in seen)


@pytest.mark.skipif(setup.ivpm_exe() is None, reason="ivpm is not installed")
def test_real_ivpm_clone(home, source, tmp_path, monkeypatch):
    """The installed ivpm, on a repo without dependencies: its transcript reads."""
    r = _with_ivpm(starters.from_values("clone", {"clone": str(source),
                                                  "dir": str(tmp_path / "t"),
                                                  "branch": "try-it"}))
    plan, seen = _make(r)
    folder = tmp_path / "t" / "dv-solve"
    assert git(folder, "symbolic-ref", "--short", "HEAD") == "try-it"
    assert ("[clone]", "ok") in [(e["name"], e["state"]) for e in seen if e["k"] == "pkg"]
    assert _steps(seen)[:4] == [("clone", "run"), ("clone", "ok"), ("deps", "run"),
                                ("deps", "skip")]


def _guarded():
    """A client through the guard, so sockets have a CSRF token; and the token."""
    import warnings
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard, csrf_token
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    secret = b"k" * 32
    base = "http://127.0.0.1:7878"
    c = TestClient(Guard(create_app(), "loopback", secret, local_user="alice"),
                   base_url=base, client=("127.0.0.1", 50000))
    return c, csrf_token(secret), base


def _job_events(c, token, base, ws):
    with c.websocket_connect("ws://127.0.0.1:7878" + ws, headers={"origin": base}) as s:
        s.send_text(json.dumps({"token": token}))
        got = []
        while not got or got[-1]["k"] != "done":
            got.append(json.loads(s.receive_text()))
    return got


def test_dash_create_runs_as_a_job(home, source, tmp_path, fake_ivpm):
    _ivpm_source(source)
    c, token, base = _guarded()
    hdr = {"origin": base, "x-csrf-token": token, "accept": "application/json"}
    with c:
        page = c.post("/new", data={"starter": "clone", "clone": str(source),
                                    "dir": str(tmp_path / "t"), "action": "preview",
                                    "csrf": token}, headers={"origin": base}).text
        assert 'id="create-form"' in page and 'name="clone_tool"' in page
        recipe = page.split('name="recipe" value="')[1].split('"')[0]
        import html
        form = {"starter": "clone", "recipe": html.unescape(recipe), "name": "dv-solve",
                "objective": "", "action": "create", "clone_tool": "ivpm", "csrf": token}
        r = c.post("/new", data=form, headers=hdr)
        assert r.status_code == 200, r.text
        job = r.json()
        got = _job_events(c, token, base, job["ws"])
        assert got[-1]["ok"] and got[-1]["url"].startswith(
            "/p/dv-solve/%s?" % registry.get("dv-solve")["root"])
        assert [e["n"] for e in got] == list(range(1, len(got) + 1))
        assert ("deps", "ok") in _steps(got)
        assert (tmp_path / "t" / "dv-solve" / "packages" / "python" / "marker").exists()
        # replay from a point, then the page and the log
        again = _job_events(c, token, base, job["ws"] + "?since=%d" % (len(got) - 2))
        assert [e["n"] for e in again] == [len(got) - 1, len(got)]
        assert 'data-job="%s"' % job["job"] in c.get("/new?job=" + job["job"]).text
        log = c.get(job["log"]).text
        assert "== Clone %s (ivpm clone) ok" % source in log and ">> [clone] (git)" in log
        assert os.path.isfile(os.path.join(registry.home(), "runs", "create",
                                           job["job"] + ".jsonl"))
        # the same again: refused before any job starts
        r = c.post("/new", data=form, headers=hdr)
        assert r.status_code == 400 and "already registered" in r.json()["error"]


def test_dash_create_job_failure(home, source, tmp_path, fake_ivpm, monkeypatch):
    _ivpm_source(source)
    monkeypatch.setenv("IVPM_FAIL", "1")
    c, token, base = _guarded()
    hdr = {"origin": base, "x-csrf-token": token, "accept": "application/json"}
    with c:
        r = c.post("/new", data={"starter": "clone", "clone": str(source), "clone_tool": "ivpm",
                                 "dir": str(tmp_path / "t"), "action": "create",
                                 "csrf": token}, headers=hdr)
        got = _job_events(c, token, base, r.json()["ws"])
        assert not got[-1]["ok"] and "no route to host" in got[-1]["error"]
        assert any(e["k"] == "undo" for e in got)
        assert not (tmp_path / "t" / "dv-solve").exists()
        with c.websocket_connect("ws://127.0.0.1:7878" + r.json()["ws"],
                                 headers={"origin": base}) as s:
            from starlette.websockets import WebSocketDisconnect
            s.send_text(json.dumps({"token": "nope"}))
            with pytest.raises(WebSocketDisconnect) as ex:
                s.receive_text()
            assert ex.value.code == 1008
    assert c.get("/new/job/nosuch/log").status_code == 404


def test_cli_shows_the_steps(home, source, tmp_path, fake_ivpm, capsys):
    from work_packet import cli
    _ivpm_source(source)
    assert cli.main(["start", "clone", "clone=%s" % source, "dir=%s" % (tmp_path / "t")]) == 0
    err = capsys.readouterr().err
    assert "Clone %s ..." % source in err and "Clone %s: ok (" % source in err
    assert "Dependencies (ivpm update): ok" in err and "  dep ok" in err
    assert "Receiving" not in err                     # git's progress only on a terminal
