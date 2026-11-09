"""CI watchers (docs/ci-watch.md): a packet per CI breakage, against a fake GitHub."""

import os
import urllib.parse
import urllib.request

import pytest

from work_packet import forges, project, registry, schema, starters, tomlio
from work_packet.packet import Packet

from test_setup import git, home, source                       # noqa: F401

API = "https://gh.test/api/v3"
LOG = ("2026-11-08T10:00:00.1234567Z ##[group]Run make test\n"
       "2026-11-08T10:00:01.0000000Z \x1b[31mFAIL\x1b[0m test_count: 3 != 4\n"
       "2026-11-08T10:00:02.0000000Z ##[error]Process completed with exit code 2.\n")


class Fake:
    """What the fake GitHub holds: ``runs`` newest first, as GitHub sends them."""

    def __init__(self, sha):
        self.sha, self.runs, self.requests = sha, [], []

    def add(self, rid, conclusion, file="ci.yml", name="CI", event="push", branch="main",
            sha=None, created="2026-11-08T10:00:00Z"):
        self.runs.insert(0, {"id": rid, "run_number": rid, "name": name,
                             "path": ".github/workflows/" + file, "workflow_id": hash(file),
                             "conclusion": conclusion, "event": event, "head_branch": branch,
                             "head_sha": sha or self.sha, "display_title": "Change %d" % rid,
                             "html_url": "https://gh.test/edapack/foo/actions/runs/%d" % rid,
                             "created_at": created})


@pytest.fixture
def gh(home, source, monkeypatch):
    """A GitHub named "gh" holding edapack/foo (cloned from ``source``)."""
    h = registry.home()
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "a") as fp:
        fp.write('\n[[forge]]\nname = "gh"\nkind = "github"\nurl = "https://gh.test"\n'
                 'token_env = "FAKE_GH"\n')
    monkeypatch.setenv("FAKE_GH", "sekrit")
    repo = {"full_name": "edapack/foo", "description": "", "clone_url": str(source),
            "ssh_url": "ssh://x", "html_url": "https://gh.test/edapack/foo",
            "default_branch": "main"}
    fake = Fake(git(source, "rev-parse", "HEAD"))

    def get(url, headers, timeout=20):
        assert headers.get("Authorization") == "token sekrit"
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        p = u.path[len("/api/v3"):]
        fake.requests.append((p, q))
        if p == "/repos/edapack/foo":
            return repo
        if p == "/users/edapack/repos":
            return [repo, dict(repo, full_name="edapack/old", archived=True)]
        if p == "/repos/edapack/foo/actions/runs":
            assert q["status"] == "completed"
            return {"workflow_runs": [r for r in fake.runs if r["head_branch"] == q["branch"]]}
        if p.startswith("/repos/edapack/foo/actions/runs/") and p.endswith("/jobs"):
            return {"jobs": [
                {"id": 900, "name": "test (3.12)", "conclusion": "failure",
                 "html_url": "https://gh.test/edapack/foo/actions/runs/1/job/900",
                 "steps": [{"name": "Checkout", "conclusion": "success"},
                           {"name": "Run tests", "conclusion": "failure"}]},
                {"id": 901, "name": "lint", "conclusion": "success", "steps": []}]}
        if p.startswith("/repos/edapack/foo/actions/runs/"):
            rid = int(p.rsplit("/", 1)[1])
            return next(r for r in fake.runs if r["id"] == rid)
        raise forges.ForgeError("%s: HTTP 404" % url)

    def get_text(url, headers, timeout=60):
        assert headers.get("Authorization") == "token sekrit"
        assert urllib.parse.urlparse(url).path == "/api/v3/repos/edapack/foo/actions/jobs/900/logs"
        return LOG
    monkeypatch.setattr(forges, "_get", get)
    monkeypatch.setattr(forges, "_get_text", get_text)
    return fake


def _board(tmp_path, **kw):
    if "eda" not in [b["name"] for b in registry.boards()]:
        registry.new_board("eda")
    path = os.path.join(registry.boards_dir(), "eda.toml")
    b = tomlio.load_toml(path)
    b["watch"] = [dict({"name": "ci", "on": "ci", "repos": ["gh:edapack/*"],
                        "dir": str(tmp_path / "w")}, **kw)]
    tomlio.save_toml(path, b)
    from work_packet import watch
    [w] = watch.watchers()
    return w


def test_schema():
    ok = {"name": "ci", "repos": ["gh:o/*"], "dir": "d"}
    assert schema.validate_watches([dict(ok, on="ci", branches=["main"], workflows=["CI"],
                                         prompt="p.md")]) == []
    bad = schema.validate_watches([dict(ok, on="ci", labels=["x"]),
                                   dict(ok, name="b", on="push"),
                                   dict(ok, name="c", branches=["main"]),
                                   dict(ok, name="d", on="ci", branches="main")])
    assert [p.field for p in bad] == ["watch[0].labels", "watch[1].on", "watch[2].branches",
                                      "watch[3].branches"]


def test_redirect_drops_the_token():
    h = forges._NoAuthOnHop()
    req = urllib.request.Request("https://api.github.com/x", headers={"Authorization": "t"})
    away = h.redirect_request(req, None, 302, "Found", {}, "https://blob.example/log?sig=1")
    assert not away.has_header("Authorization")
    home_ = h.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/y")
    assert home_.has_header("Authorization")


def test_ci_starter_by_hand(gh, source, tmp_path):
    gh.add(11, "failure")
    r = starters.from_values("ci", {"run": "https://gh.test/edapack/foo/actions/runs/11",
                                    "dir": str(tmp_path)})
    sha7 = gh.sha[:7]
    assert r["name"] == "foo-ci-ci-" + sha7
    assert r["clone"] == {"url": str(source), "ref": gh.sha, "branch": "wpk/ci-ci-" + sha7}
    assert r["origin"] == {"kind": "ci", "forge": "gh", "repo": "edapack/foo",
                           "workflow": "ci.yml", "run": 11, "sha": gh.sha,
                           "url": "https://gh.test/edapack/foo/actions/runs/11",
                           "branch": "wpk/ci-ci-" + sha7, "base": "main"}
    [inp] = r["inputs"]
    assert inp["name"] == "ci-run-11.md"
    text = inp["text"]
    assert "## Job: test (3.12) (failure)" in text and "Failed steps: Run tests" in text
    assert "FAIL test_count: 3 != 4" in text and "2026-11-08T" not in text.split("```")[1]
    assert "\x1b" not in text and "lint" not in text
    assert 'workflow "CI" on main' in r["objective"]
    # The same by repo and id; a bad run is refused.
    r2 = starters.from_values("ci", {"repo": "gh:edapack/foo", "run": "11",
                                     "dir": str(tmp_path)})
    assert r2["origin"] == r["origin"]
    with pytest.raises(starters.StartError):
        starters.from_values("ci", {"repo": "gh:edapack/foo", "run": "x", "dir": "d"})
    lines = starters.preview(r)
    assert "input state/ci-run-11.md (%d lines)" % (text.count("\n") + 1) in lines
    assert "from https://gh.test/edapack/foo/actions/runs/11" in lines
    plan = starters.make(r)
    folder = tmp_path / r["name"]
    assert git(folder, "symbolic-ref", "--short", "HEAD") == "wpk/ci-ci-" + sha7
    assert git(folder, "rev-parse", "HEAD") == gh.sha
    assert "state/ci-run-11.md" in open(os.path.join(plan.path, "prompt.md")).read()


def _notes(name):
    from work_packet import layout, notes
    e = registry.get(name)
    return [n["text"] for n in notes.queued(Packet(layout.run_dir(e["path"], e["root"])))]


def test_ci_watch(gh, source, tmp_path):
    from work_packet import watch
    gh.add(9, "failure")
    gh.add(10, "success")
    gh.add(11, "failure")
    gh.add(12, "timed_out")
    gh.add(13, "failure", event="pull_request")        # a PR's run: not main's
    gh.add(14, "cancelled")                            # neither red nor green
    gh.add(15, "success", file="lint.yml", name="Lint")
    gh.add(16, "failure", branch="dev")                # not a watched branch
    w = _board(tmp_path, prompt="ci-notes.md")
    with open(os.path.join(registry.boards_dir(), "ci-notes.md"), "w") as f:
        f.write("Run `ivpm update` before building.\n")
    key = "gh:edapack/foo@main/ci.yml#11"
    r = watch.poll(w, dry_run=True)
    assert r["would"] == [key] and r["errors"] == []
    r = watch.poll(w)
    [(k, name)] = r["made"]
    assert k == key
    e = registry.get(name)
    assert e["board"] == "eda"
    o = project.load_project(e["path"])["origin"]
    assert o["key"] == key and o["watch"] == "eda/ci" and o["run"] == 11
    text = open(os.path.join(e["path"], "prompt.md")).read()
    assert "failed 2 times in a row since; the latest is run #12" in text
    assert "ivpm update" in text
    assert watch.load_state(w)["green"]["gh:edapack/foo@main/ci.yml#"]["id"] == 10

    # Still red: the same breakage. Losing the state file changes nothing.
    gh.add(17, "failure")
    assert watch.poll(w)["made"] == []
    os.unlink(watch.state_path(w))
    assert watch.poll(w)["made"] == [] and key in watch.load_state(w)["seen"]
    # Only red runs on the page (its start is older): still the same breakage.
    gh.runs[:] = [x for x in gh.runs if x["id"] >= 11]
    assert watch.poll(w)["made"] == []

    # Green again: the packet gets a note, once.
    gh.add(18, "success")
    r = watch.poll(w)
    assert r["made"] == [] and r["cleared"] == [key]
    [note] = _notes(name)
    assert "CI is green again: run #18" in note
    assert watch.poll(w)["cleared"] == []

    # Red after green: a new breakage, a new packet (at its own commit).
    (source / "x.txt").write_text("x\n")
    git(source, "add", "x.txt")
    git(source, "commit", "-q", "-m", "x")
    gh.add(19, "failure", sha=git(source, "rev-parse", "HEAD"))
    r = watch.poll(w)
    assert [k for k, _ in r["made"]] == ["gh:edapack/foo@main/ci.yml#19"]
    text = open(os.path.join(registry.get(r["made"][0][1])["path"], "prompt.md")).read()
    assert "in a row since" not in text


def test_ci_watch_filters_and_the_inbox(gh, tmp_path):
    from work_packet import inbox, watch
    gh.add(1, "failure", file="nightly.yml", name="Nightly")
    gh.add(2, "failure")
    w = _board(tmp_path, workflows=["nightly"], propose=True, branches=["main"])
    r = watch.poll(w)
    assert r["proposed"] == ["gh:edapack/foo@main/nightly.yml#1"] and r["made"] == []
    [item] = [x for x in inbox.items(registry.home()) if x.get("source") == "watch"]
    assert "edapack/foo: Nightly failing on main" in item["text"]
    # Accepting it makes the packet from the key alone.
    plan = starters.make(watch.recipe(w, "gh:edapack/foo@main/nightly.yml#1"))
    assert plan.name.startswith("foo-ci-nightly-")


def test_since(gh, tmp_path, capsys):
    from work_packet import cli, watch
    gh.add(1, "failure", file="old.yml", created="2026-09-01T00:00:00Z")     # NOW is 10-21
    gh.add(2, "failure", file="new.yml", created="2026-10-20T00:00:00Z")
    # A weekly job red since September and still failing: judged by its newest run.
    gh.add(3, "failure", file="weekly.yml", created="2026-09-02T00:00:00Z")
    gh.add(4, "failure", file="weekly.yml", created="2026-10-19T00:00:00Z")
    w = _board(tmp_path)
    r = watch.poll(w, dry_run=True)
    assert r["would"] == ["gh:edapack/foo@main/new.yml#2", "gh:edapack/foo@main/weekly.yml#3"]
    assert r["old"] == ["gh:edapack/foo@main/old.yml#1"]
    assert cli.main(["watch", "poll", "eda/ci", "--dry-run"]) == 0
    assert "old.yml#1 last failed before `since` (7d); left" in capsys.readouterr().out
    w = _board(tmp_path, since="60d")
    assert len(watch.poll(w, dry_run=True)["would"]) == 3
    bad = schema.validate_watches([{"name": "x", "on": "ci", "repos": ["gh:o/r"], "dir": "d",
                                    "since": "soon"}])
    assert [p.field for p in bad] == ["watch[0].since"]


def test_ci_on_forgejo_is_an_error(gh, tmp_path):
    from work_packet import watch
    with open(os.path.join(registry.home(), "config.toml"), "a") as fp:
        fp.write('\n[[forge]]\nname = "fj"\nkind = "forgejo"\nurl = "https://fj.test"\n')
    w = _board(tmp_path, repos=["fj:o/r"], branches=["main"])
    assert watch.poll(w)["errors"] == ["CI runs: not supported on forgejo yet"]


def test_the_board_page(gh, tmp_path):
    from test_dash_tasks import _client
    _board(tmp_path, branches=["main", "dev"])
    page = _client().get("/b/eda").text
    assert "CI failures on main, dev" in page and "CI failures</option>" in page
