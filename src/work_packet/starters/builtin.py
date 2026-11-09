"""The built-in starters: folder, clone, issue, ci (docs/starters-v1.md, docs/ci-watch.md)."""

import os
import re

from .. import forges
from . import Field, StartError, Starter, register


def _repo_choices(query, h):
    """Repos on every forge matching ``query``, as ``forge:owner/name`` values."""
    out = []
    for f in forges.forges(h).values():
        try:
            rows = f.repos(query, limit=15)
        except forges.ForgeError as e:
            out.append({"value": "", "label": "%s: %s" % (f.name, e), "detail": ""})
            continue
        out += [{"value": "%s:%s" % (f.name, r["full_name"]), "label": r["full_name"],
                 "detail": "%s · %s" % (f.name, r["description"][:80])} for r in rows]
    return out


def _resolve_repo(text, h):
    """A repo as typed: (clone url, (forge, "owner/name") or None)."""
    ref = forges.parse(text, h)
    if ref is None or ref[2] is not None:
        if ref is None:
            p = os.path.expanduser(text)
            return (os.path.abspath(p) if os.path.exists(p) else text), None
        raise StartError("%s is an issue: use the issue starter" % text)
    fname, repo, _ = ref
    if ":" in text and not text.startswith(("http:", "https:")):
        try:
            return forges.get(fname, h).repo(repo)["clone_url"], (fname, repo)
        except forges.ForgeError as e:
            raise StartError(str(e)) from None
    return text, (fname, repo)         # a pasted URL: cloned as given


def _base_name(url):
    n = os.path.basename(url.rstrip("/"))
    n = n[:-4] if n.endswith(".git") else n
    return forges.slug(n, 48)


@register
class FolderStarter(Starter):
    name = "folder"
    title = "Folder"
    help = "A new empty folder, or a folder that exists (a clone you have): steps work in it."

    def recipe(self, values, h=None):
        return self.base(values)


@register
class CloneStarter(Starter):
    name = "clone"
    title = "Clone a repo"
    help = "Clone a repo as the packet folder: a path, a URL, or one picked on a forge."
    fields = (
        Field("clone", "Repo", "repo", required=True,
              placeholder="path, URL, or search the forges",
              help="Type to search the configured forges, or paste a URL or path."),
        Field("ref", "Check out", placeholder="the default branch",
              help="A branch, tag or commit to start from."),
        Field("branch", "New branch", placeholder="none",
              help="Made at the start, and checked out: steps commit on it."),
    )

    def search(self, key, query, values, h=None):
        return _repo_choices(query, h) if key == "clone" else []

    def recipe(self, values, h=None):
        url, ref = _resolve_repo(values["clone"], h)
        r = self.base(values)
        r.setdefault("name", _base_name(url))
        r["clone"] = {"url": url}
        for k in ("ref", "branch"):
            if values.get(k):
                r["clone"][k] = values[k]
        if ref:
            r["origin"] = {"kind": "repo", "forge": ref[0], "repo": ref[1]}
        return r


OBJECTIVE = """\
Resolve issue #{number} in {repo}: {title}
{url}

The issue and its comments are in state/{input}. This folder is a clone of
{repo}; work on branch `{branch}` and commit as you go. When it is done, say
what changed and how you tested it.
"""


def issue_markdown(repo, i):
    out = ["# #%d %s" % (i["number"], i["title"]), "",
           "%s · %s · opened by %s%s" % (i["url"], i["state"], i["user"],
                                          " · labels: %s" % ", ".join(i["labels"])
                                          if i["labels"] else ""), "",
           i["body"].strip() or "(no description)", ""]
    for c in i["comments"]:
        out += ["## %s, %s" % (c["user"], c["created"][:10]), "", c["body"].strip(), ""]
    return "\n".join(out)


@register
class IssueStarter(Starter):
    name = "issue"
    title = "From an issue"
    help = ("Pick an issue: its repo is cloned, a branch made for it, and the issue becomes "
            "the objective and an input.")
    fields = (
        Field("repo", "Repo", "repo", placeholder="search the forges",
              help="Type to search; or paste an issue URL below."),
        Field("issue", "Issue", "issue", required=True,
              placeholder="number, search text, or an issue URL"),
    )

    def search(self, key, query, values, h=None):
        if key == "repo":
            return _repo_choices(query, h)
        if key != "issue":
            return []
        ref = forges.parse(values.get("repo") or "", h)
        if ref is None:
            return [{"value": "", "label": "pick a repo first", "detail": ""}]
        f = forges.get(ref[0], h)
        try:
            rows = f.issues(ref[1], query)
        except forges.ForgeError as e:
            return [{"value": "", "label": str(e), "detail": ""}]
        return [{"value": "%s:%s#%d" % (f.name, ref[1], i["number"]),
                 "label": "#%d %s" % (i["number"], i["title"]), "detail": i["url"]}
                for i in rows]

    def _which(self, values, h):
        text = values.get("issue") or ""
        ref = forges.parse(text, h)
        if ref and ref[2] is not None:
            return ref
        r = forges.parse(values.get("repo") or "", h)
        if r is None:
            raise StartError("Issue: give a URL or forge:owner/repo#n, or pick the repo first")
        n = text.lstrip("#")
        if not n.isdigit():
            raise StartError("Issue: a number, a URL, or one picked from the list")
        return r[0], r[1], int(n)

    def recipe(self, values, h=None):
        fname, repo, n = self._which(values, h)
        f = forges.get(fname, h)
        try:
            i = f.issue(repo, n)
            info = f.repo(repo)
        except forges.ForgeError as e:
            raise StartError(str(e)) from None
        branch = "wpk/%d-%s" % (n, forges.slug(i["title"], 32))
        inp = "issue-%d.md" % n
        r = self.base(values)
        r.setdefault("name", "%s-%d" % (forges.slug(repo.split("/")[-1], 40), n))
        r["clone"] = {"url": info["clone_url"], "branch": branch}
        r.setdefault("objective", OBJECTIVE.format(number=n, repo=repo, title=i["title"],
                                                   url=i["url"], input=inp, branch=branch))
        r["inputs"] = [{"name": inp, "text": issue_markdown(repo, i)}]
        r["origin"] = {"kind": "issue", "forge": fname, "repo": repo, "number": n,
                       "title": i["title"], "url": i["url"], "branch": branch,
                       "base": info.get("default_branch") or ""}
        return r


# --- a CI breakage (docs/ci-watch.md) ----------------------------------------------

CI_OBJECTIVE = """\
CI is failing in {repo}: workflow "{workflow}" on {base}, from run #{number}
at commit {sha7} ("{title}").
{url}

The failed jobs, their failed steps and the end of their logs are in
state/{input}. This folder is a clone of {repo} at that commit, on branch
`{branch}`.

Find out why it fails; reproduce it here if you can. Say which it is: a
regression (and which change caused it), a flaky test, or a problem with the
CI setup or its machines. If the fix is small and clear, make it and commit it
on `{branch}`; if not, say what the fix needs. Report what you found and how
sure you are.
"""

LOG_LINES = 200
LOG_JOBS = 4
_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def log_tail(text, n=LOG_LINES):
    """The last ``n`` lines of a CI log, without timestamps or colour codes."""
    lines = [_ANSI.sub("", _STAMP.sub("", ln)) for ln in text.splitlines()]
    return "\n".join(lines[-n:])


def run_markdown(repo, run, jobs, logs):
    """The input a CI packet starts from: the run, then each failed job."""
    out = ["# %s #%s on %s: %s" % (run["name"], run["number"], run["branch"],
                                    run["conclusion"]), "",
           "- repo: %s" % repo, "- run: %s" % run["url"],
           "- commit: %s (%s)" % (run["sha"], run["title"]),
           "- event: %s · %s" % (run["event"], run["created"]), ""]
    bad = [j for j in jobs if j["conclusion"] in forges.RED]
    if not bad:
        out += ["(No failed job was listed.)", ""]
    for j in bad:
        out += ["## Job: %s (%s)" % (j["name"], j["conclusion"]), "", j["url"], ""]
        if j["failed_steps"]:
            out += ["Failed steps: " + ", ".join(j["failed_steps"]), ""]
        if j["id"] in logs:
            out += ["Last %d lines of its log:" % LOG_LINES, "", "```", logs[j["id"]], "```", ""]
        elif len(logs) >= LOG_JOBS:
            out += ["(Log not fetched: only the first %d failed jobs' logs are.)" % LOG_JOBS, ""]
    return "\n".join(out)


_RUN_URL = re.compile(r"^(.*/[\w.-]+/[\w.-]+)/actions/runs/(\d+)")


@register
class CIStarter(Starter):
    name = "ci"
    title = "From a CI run"
    help = ("Pick a failed CI run: its repo is cloned at the failing commit, a branch made, "
            "and the failed jobs' logs become an input to investigate.")
    fields = (
        Field("repo", "Repo", "repo", placeholder="search the forges",
              help="Type to search; or paste a run URL below."),
        Field("run", "Run", required=True, placeholder="run id, or a run URL"),
    )

    def search(self, key, query, values, h=None):
        return _repo_choices(query, h) if key == "repo" else []

    def _which(self, values, h):
        text = (values.get("run") or "").strip()
        m = _RUN_URL.match(text)
        if m:
            ref = forges.parse(m.group(1), h)
            if ref is None:
                raise StartError("Run: %s is not on a configured forge" % m.group(1))
            return ref[0], ref[1], int(m.group(2))
        r = forges.parse(values.get("repo") or "", h)
        if r is None:
            raise StartError("Run: give a run URL, or pick the repo first")
        if not text.isdigit():
            raise StartError("Run: a run id or a run URL")
        return r[0], r[1], int(text)

    def recipe(self, values, h=None):
        fname, repo, rid = self._which(values, h)
        f = forges.get(fname, h)
        try:
            run = f.run(repo, rid)
            info = f.repo(repo)
            jobs = f.run_jobs(repo, rid)
        except forges.ForgeError as e:
            raise StartError(str(e)) from None
        logs = {}
        for j in [j for j in jobs if j["conclusion"] in forges.RED][:LOG_JOBS]:
            try:
                logs[j["id"]] = log_tail(f.job_log(repo, j["id"]))
            except forges.ForgeError as e:
                logs[j["id"]] = "(could not fetch the log: %s)" % e
        wf = forges.slug(os.path.splitext(run["file"])[0] or run["name"], 24)
        sha7 = run["sha"][:7]
        branch = "wpk/ci-%s-%s" % (wf, sha7)
        inp = "ci-run-%d.md" % rid
        r = self.base(values)
        r.setdefault("name", "%s-ci-%s-%s" % (forges.slug(repo.split("/")[-1], 32), wf, sha7))
        r["clone"] = {"url": info["clone_url"], "ref": run["sha"], "branch": branch}
        r.setdefault("objective", CI_OBJECTIVE.format(
            repo=repo, workflow=run["name"], base=run["branch"], number=run["number"],
            sha7=sha7, title=run["title"], url=run["url"], input=inp, branch=branch))
        r["inputs"] = [{"name": inp, "text": run_markdown(repo, run, jobs, logs)}]
        r["origin"] = {"kind": "ci", "forge": fname, "repo": repo,
                       "workflow": run["file"] or run["name"], "run": rid,
                       "url": run["url"], "sha": run["sha"], "branch": branch,
                       "base": run["branch"]}
        return r
