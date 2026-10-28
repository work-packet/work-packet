"""Hand-off as a pull request (docs/starters-v1.md, Hand-off).

A packet that came from a forge (``project.toml [origin]`` with ``forge`` and
``repo``) hands its work back by pushing its branch and opening a pull request
into the repo's default branch: for an issue, one that closes it, with the
packet's report as the description. What was opened is kept in
``project.toml [pr]``; a second ``open`` pushes again and finds the same one.

By hand: ``wpk pr <project>``, or "Open PR" on the dashboard. By itself: a
watcher with ``pr = "draft"`` or ``"ready"`` opens one when a packet it made
completes (``sync``, polled by the runner beside its watchers).
"""

import os
import subprocess

from . import layout, registry, schema
from .tomlio import load_toml

MODES = ("off", "draft", "ready")


class PRError(Exception):
    pass


def _git(folder, *args, raw=False):
    r = subprocess.run(["git", "-C", folder] + list(args), capture_output=True, text=True)
    if r.returncode:
        raise PRError("git %s: %s" % (" ".join(args[:2]), (r.stderr or r.stdout).strip()))
    return r.stdout if raw else r.stdout.strip()


def _toml(e):
    try:
        return load_toml(os.path.join(e["path"], "project.toml"))
    except (OSError, ValueError) as ex:
        raise PRError(str(ex)) from None


def recorded(e):
    """The pull request already opened for project entry ``e`` ([pr]), or None."""
    try:
        p = load_toml(os.path.join(e["path"], "project.toml")).get("pr")
    except (OSError, ValueError):
        return None
    return p if isinstance(p, dict) and p.get("url") else None


def state(e):
    from .packet import Packet
    try:
        meta, _ = Packet(layout.run_dir(e["path"], e["root"])).load_status()
    except (OSError, ValueError):
        return None
    return meta.get("state")


def target(e, h=None):
    """Where ``e``'s work goes: {forge, repo, branch, base, folder, origin}.
    Raises PRError naming what is missing."""
    o = _toml(e).get("origin") or {}
    if not o.get("forge") or not o.get("repo"):
        raise PRError("%s did not come from a forge (no [origin] forge and repo); push "
                      "it by hand" % e["name"])
    folder = layout.packet_folder(e["path"])
    if not os.path.isdir(os.path.join(folder, ".git")):
        raise PRError("%s is not a git clone" % folder)
    branch = o.get("branch") or _git(folder, "rev-parse", "--abbrev-ref", "HEAD")
    base = o.get("base")
    if not base:
        from . import forges
        try:
            base = forges.get(o["forge"], h).repo(o["repo"])["default_branch"]
        except forges.ForgeError as ex:
            raise PRError(str(ex)) from None
    if not base:
        raise PRError("%s:%s: no default branch" % (o["forge"], o["repo"]))
    if branch in ("HEAD", base):
        raise PRError("%s is on %s, not a branch of its own; make one first" % (
            folder, base if branch == base else "a detached HEAD"))
    return {"forge": o["forge"], "repo": o["repo"], "branch": branch, "base": base,
            "folder": folder, "origin": o}


def check(t):
    """Refusals before anything is pushed: changes not committed, nothing to
    hand off, or the branch not checked out. Returns the commits ahead."""
    f = t["folder"]
    cur = _git(f, "rev-parse", "--abbrev-ref", "HEAD")
    if cur != t["branch"]:
        raise PRError("%s is on %s, not %s" % (f, cur, t["branch"]))
    dirty = [ln[3:] for ln in _git(f, "status", "--porcelain", "-uno",
                                                       raw=True).splitlines()]
    if dirty:
        raise PRError("changes not committed in %s: %s%s" % (
            f, ", ".join(dirty[:5]), " …" if len(dirty) > 5 else ""))
    upstream = "origin/" + t["base"]
    try:
        _git(f, "rev-parse", "--verify", "-q", upstream)
    except PRError:
        upstream = t["base"]
    n = int(_git(f, "rev-list", "--count", "%s..HEAD" % upstream))
    if not n:
        raise PRError("%s has no commits beyond %s: nothing to hand off" % (
            t["branch"], t["base"]))
    return n


def title_and_body(e, t):
    """The pull request's title and description, from the origin and the report."""
    from . import report
    from .packet import Packet
    o = t["origin"]
    rep = report.of_packet(Packet(layout.run_dir(e["path"], e["root"])))
    meta, body = rep if rep else ({}, "")
    outcome = " ".join(str(meta.get("outcome") or "").split())
    if o.get("kind") == "issue" and o.get("number"):
        title = o.get("title") or outcome or e["name"]
        head = ["Closes #%s." % o["number"], ""]
    else:
        title = outcome or e["name"]
        head = []
    if len(title) > 120:
        title = title[:117].rstrip() + "…"
    lines = head
    if outcome:
        lines += ["**Outcome:** " + outcome, ""]
    if body.strip():
        lines += [body.strip(), ""]
    ds = [d for d in meta.get("deliverables") or () if isinstance(d, dict)]
    if ds:
        lines += ["**Deliverables:**"] + ["- `%s`: %s" % (d.get("path", ""), d.get("what", ""))
                                          for d in ds] + [""]
    if not outcome and not body.strip():
        lines += ["(The packet wrote no report.)", ""]
    lines.append("---\nHanded off by work-packet from packet `%s`." % e["name"])
    return title, "\n".join(lines)


def open_pr(name, h=None, draft=False, dry_run=False, by="wpk"):
    """Push ``name``'s branch and open (or find) its pull request.
    Returns {url, number, state, draft, new, pushed, title, ...target}; with
    ``dry_run``, what it would do, and nothing pushed or opened."""
    from . import forges, project
    e = registry.get(name, h)
    if e is None:
        raise PRError("no project %s" % name)
    t = target(e, h)
    ahead = check(t)
    title, body = title_and_body(e, t)
    out = dict(t, ahead=ahead, title=title, body=body, new=False, pushed=False)
    out.pop("origin")
    if dry_run:
        return out
    _git(t["folder"], "push", "-u", "origin", "%s:%s" % (t["branch"], t["branch"]))
    out["pushed"] = True
    f = forges.get(t["forge"], h)
    try:
        p = f.pull_for(t["repo"], t["branch"])
        if p is None:
            p = f.open_pull(t["repo"], t["branch"], t["base"], title, body, draft=draft)
            out["new"] = True
    except forges.ForgeError as ex:
        raise PRError("pushed %s; the pull request: %s" % (t["branch"], ex)) from None
    out.update(p)

    def put(d):
        rec = {"url": p["url"], "number": p["number"], "forge": t["forge"],
               "repo": t["repo"], "branch": t["branch"], "base": t["base"],
               "opened": d.get("pr", {}).get("opened") or schema.format_timestamp(
                   _now())}
        if d.get("pr") == rec:
            return []
        d["pr"] = rec
        return ["pr: %s" % p["url"]]
    try:
        project.change_settings(e["path"], put, by)
    except project.ProjectError as ex:
        raise PRError("opened %s, but could not record it: %s" % (p["url"], ex)) from None
    return out


def _now():
    from . import clock
    return clock.now()


# --- by itself: a watcher's packets ------------------------------------------------

def sync(h=None, report=lambda name, msg, ok: None):
    """Open the pull request of each completed packet made by a watcher with
    ``pr`` on. A failure is kept in the watcher's state and not tried again
    by itself (``wpk pr`` or "Open PR" tries again). Returns the number opened."""
    from . import watch
    modes = {"%s/%s" % (w["board"], w["name"]): w for w in watch.find(None, h)
             if w.get("pr", "off") != "off"}
    if not modes:
        return 0
    n = 0
    for e in registry.entries(h):
        try:
            o = load_toml(os.path.join(e["path"], "project.toml"))
        except (OSError, ValueError):
            continue
        w = modes.get((o.get("origin") or {}).get("watch"))
        if w is None or o.get("pr") or state(e) != "COMPLETED":
            continue
        s = watch.load_state(w, h)
        if e["name"] in s.get("pr_failed", {}):
            continue
        try:
            r = open_pr(e["name"], h, draft=w["pr"] == "draft", by="watch")
        except PRError as ex:
            watch.update_state(w, h, lambda s: s.setdefault("pr_failed", {}).__setitem__(
                e["name"], str(ex)))
            report(e["name"], str(ex), False)
            continue
        watch.update_state(w, h, lambda s: s.setdefault("pr_failed", {}).pop(e["name"], None))
        report(e["name"], r["url"], True)
        n += 1
    return n


def forget_failure(name, h=None):
    """After a hand-made open: the watcher may try this packet again."""
    from . import watch
    for w in watch.find(None, h):
        if name in watch.load_state(w, h).get("pr_failed", {}):
            watch.update_state(w, h, lambda s: s["pr_failed"].pop(name, None))
