"""Watchers: a board polls issue trackers and starts a packet per new issue
(docs/starters-v1.md, Watchers), or polls CI and starts one per breakage
(``on = "ci"``, docs/ci-watch.md).

A watcher is a ``[[watch]]`` table in ``boards/<board>.toml``. Each poll
lists the open issues of its repos (with its labels), and makes a packet with
the ``issue`` starter for each one not seen before, on the watcher's board.
What it has seen is kept in ``$WPK_HOME/watch/<board>.<name>.json``; an issue
already the origin of a registered project is never made again.
"""

import fcntl
import json
import os
import time

from . import fsutil, registry, schema
from .tomlio import load_toml

EVERY_S = 15 * 60
MAX_NEW = 5
SINCE = "7d"         # a CI breakage older than this is not made (docs/ci-watch.md)


class WatchError(Exception):
    pass


def _board_file(board, h):
    return os.path.join(registry.boards_dir(h), board + ".toml")


def watchers(h=None):
    """Every watcher on every board: [{board, problems?, ...the [[watch]] table}].
    A board file whose watchers do not validate gives one row with ``problems``."""
    out = []
    names = [b["name"] for b in registry.boards(h)]
    for board in names:
        path = _board_file(board, h)
        try:
            d = load_toml(path)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            out.append({"board": board, "name": "?", "problems": [str(e)]})
            continue
        bad = ["%s: %s" % (p.field, p.msg) for p in schema.validate_watches(d.get("watch"))
               if p.level == "error"]
        if bad:
            out.append({"board": board, "name": "?", "problems": bad})
            continue
        out += [dict(w, board=board) for w in d.get("watch") or []]
    return out


# --- editing from the board (docs/collaboration-plan.md G4) -----------------------

def _load_board(board, h):
    path = _board_file(board, h)
    try:
        return path, load_toml(path)
    except FileNotFoundError:
        if board != registry.DEFAULT_BOARD:
            raise WatchError("no board %s" % board) from None
        return path, {}                 # main has no file until it needs one
    except (OSError, ValueError) as e:
        raise WatchError("boards/%s.toml: %s; edit it by hand" % (board, e)) from None


def _write_board(path, d, ws):
    from .tomlio import save_toml
    bad = ["%s: %s" % (p.field.split(".", 1)[-1], p.msg)
           for p in schema.validate_watches(ws) if p.level == "error"]
    if bad:
        raise WatchError("; ".join(bad))
    d = dict(d)
    if ws:
        d["watch"] = ws
    else:
        d.pop("watch", None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_toml(path, d)


def save(board, w, was=None, h=None):
    """Add a watcher to ``board``, or replace the one named ``was`` (keys the form
    doesn't show, such as ``query`` or ``model``, are kept). It is checked as
    ``[[watch]]`` is; nothing is written if it doesn't pass."""
    path, d = _load_board(board, h)
    ws = [dict(x) for x in d.get("watch") or []]
    w = {k: v for k, v in w.items() if v not in (None, "", [])}
    if was:
        i = next((i for i, x in enumerate(ws) if x.get("name") == was), None)
        if i is None:
            raise WatchError("%s has no watcher %s" % (board, was))
        keep = {k: v for k, v in ws[i].items() if k not in FORM_KEYS}
        ws[i] = dict(keep, **w)
    else:
        if any(x.get("name") == w.get("name") for x in ws):
            raise WatchError("%s has a watcher %s already" % (board, w.get("name")))
        ws.append(w)
    _write_board(path, d, ws)
    return w


def remove(board, name, h=None):
    """Remove a watcher. What it made stays; so does what it has seen."""
    path, d = _load_board(board, h)
    ws = [x for x in d.get("watch") or [] if x.get("name") != name]
    if len(ws) == len(d.get("watch") or []):
        raise WatchError("%s has no watcher %s" % (board, name))
    _write_board(path, d, ws)


FORM_KEYS = ("name", "repos", "dir", "labels", "every", "propose", "hold", "enabled", "pr",
             "on", "branches")


def find(spec, h=None):
    """Watchers named by ``board`` or ``board/name``; all for None."""
    ws = [w for w in watchers(h) if not w.get("problems")]
    if not spec:
        return ws
    board, _, name = spec.partition("/")
    got = [w for w in ws if w["board"] == board and (not name or w["name"] == name)]
    if not got:
        raise WatchError("no watcher %s" % spec)
    return got


# --- state ------------------------------------------------------------------------

def state_path(w, h=None):
    return os.path.join(h or registry.home(), "watch", "%s.%s.json" % (w["board"], w["name"]))


def load_state(w, h=None):
    try:
        with open(state_path(w, h), encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault("seen", {})        # "forge:owner/repo#n" -> project made
    s.setdefault("failed", {})      # "forge:owner/repo#n" -> the error, tried again
    s.setdefault("dates", {})       # project -> the milestone date proposed for it
    return s


def _save_state(w, s, h):
    p = state_path(w, h)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, json.dumps(s, indent=1, sort_keys=True))


def update_state(w, h, change):
    """Apply ``change(state)`` under the watcher's lock (waiting for a poll)."""
    lock = state_path(w, h) + ".lock"
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        s = load_state(w, h)
        change(s)
        _save_state(w, s, h)


def every(w):
    return schema.parse_duration(w["every"]) if w.get("every") else EVERY_S


def due(w, h=None, now=None):
    """The watcher is enabled and its last poll is ``every`` ago."""
    if w.get("problems") or w.get("enabled") is False:
        return False
    last = load_state(w, h).get("polled")
    return last is None or (now or time.time()) - last >= every(w)


def _key(fname, repo, n):
    return "%s:%s#%d" % (fname, repo, n)


def known_issues(h=None):
    """Issues and CI breakages that are the origin of a registered project:
    {key: project}."""
    out = {}
    for e in registry.entries(h):
        try:
            o = load_toml(os.path.join(e["path"], "project.toml")).get("origin")
        except (OSError, ValueError):
            continue
        if not isinstance(o, dict):
            continue
        if o.get("kind") == "issue" and isinstance(o.get("number"), int):
            out[_key(o.get("forge", ""), o.get("repo", ""), o["number"])] = e["name"]
        elif o.get("kind") == "ci" and isinstance(o.get("key"), str):
            out[o["key"]] = e["name"]
    return out


# --- a poll -----------------------------------------------------------------------

def poll(w, h=None, dry_run=False, now=None):
    """Poll one watcher. Returns {made: [(key, project)], would: [key],
    failed: {key: error}, errors: [str], proposed: [key], dates: [id],
    cleared: [key], old: [key]}. A watcher with ``propose = true`` puts each new issue
    (or CI breakage) in the Inbox instead of making it. Only one poll of a
    watcher at a time (a lock beside its state file)."""
    from . import starters
    out = {"made": [], "would": [], "failed": {}, "errors": [], "proposed": [], "dates": [],
           "cleared": [], "old": []}
    lock = state_path(w, h) + ".lock"
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    with open(lock, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            out["errors"].append("another poll of %s/%s is running" % (w["board"], w["name"]))
            return out
        s = load_state(w, h)
        known = known_issues(h)
        source = _ci_fresh if w.get("on") == "ci" else _issue_fresh
        fresh = source(w, h, s, known, out, dry_run, now)
        fresh.sort(key=lambda x: x[0] in s["failed"])     # new ones before retries
        for k, i in fresh[:w.get("max_new", MAX_NEW)]:
            if dry_run:
                out["would"].append(k)
                continue
            if w.get("propose"):          # to the Inbox, for you to accept (collaboration.md W8)
                from . import inbox
                try:
                    d = inbox.add(h or registry.home(), "%s (%s)" % (i.get("title") or k, k),
                                  source="watch", board=w["board"],
                                  ref={"watch": w["name"], "key": k, "url": i.get("url")})
                except (ValueError, OSError) as e:
                    s["failed"][k] = str(e)
                    out["failed"][k] = str(e)
                    continue
                s["seen"][k] = "inbox:" + d["id"]
                s["failed"].pop(k, None)
                out["proposed"].append(k)
                continue
            try:
                plan = starters.make(recipe(w, k, h, i), h)
            except (starters.StartError, OSError) as e:
                s["failed"][k] = str(e)
                out["failed"][k] = str(e)
                continue
            s["seen"][k] = plan.name
            s["failed"].pop(k, None)
            out["made"].append((k, plan.name))
        if not dry_run:
            s["polled"] = now or time.time()
            s["errors"] = out["errors"]
            _save_state(w, s, h)
    return out


def _issue_fresh(w, h, s, known, out, dry_run, now):
    """The open issues not made yet: [(key, issue)]. Proposes milestone dates
    for those made already."""
    from . import forges
    labels = w.get("labels") or []
    fresh = []
    for fname, repo in _expand(w["repos"], h, out["errors"]):
        try:
            rows = forges.get(fname, h).issues(repo, w.get("query") or "", limit=50,
                                               labels=labels)
        except forges.ForgeError as e:
            out["errors"].append(str(e))
            continue
        for i in rows:
            if not set(labels) <= set(i.get("labels") or []):
                continue          # a forge that ignored the filter
            k = _key(fname, repo, i["number"])
            made = known.get(k) or s["seen"].get(k)
            if made and not dry_run and not made.startswith("inbox:"):
                d = propose_date(made, i, k, s, h)
                if d:
                    out["dates"].append(d)
            if k in s["seen"]:
                continue
            if k in known:
                s["seen"][k] = known[k]
                continue
            fresh.append((k, i))
    return fresh


# --- CI breakages (docs/ci-watch.md) ----------------------------------------------

PR_EVENTS = ("pull_request", "pull_request_target")


def ci_key(fname, repo, branch, workflow, run_id):
    return "%s:%s@%s/%s#%d" % (fname, repo, branch, workflow, run_id)


def parse_ci_key(key):
    """``forge:owner/repo@branch/workflow#run`` to (forge, repo, branch, workflow, run)."""
    head, _, rid = key.rpartition("#")
    ref, _, bw = head.partition("@")
    fname, _, repo = ref.partition(":")
    branch, _, wf = bw.rpartition("/")
    return fname, repo, branch, wf, int(rid)


def _wanted(w, run):
    want = w.get("workflows")
    if not want:
        return True
    stem = os.path.splitext(run["file"])[0]
    return any(x in (run["name"], run["file"], stem) for x in want)


def _ci_fresh(w, h, s, known, out, dry_run, now):
    """The CI breakages not made yet: [(key, item)]. A breakage is a streak of red
    runs of one workflow on one branch, named by its first red run; the last
    green run of each is kept in ``s["green"]``. One whose newest red run is older
    than ``since`` is left (``out["old"]``): it has stopped running, not been fixed.
    A breakage made already whose workflow has gone green since gets a note, once
    (``s["cleared"]``)."""
    from . import clock, forges
    t = now if now is not None else clock.now().timestamp()
    oldest = t - schema.parse_age(w.get("since") or SINCE)
    green, cleared = s.setdefault("green", {}), s.setdefault("cleared", {})
    made = {**known, **s["seen"]}
    fresh = []
    for fname, repo in _expand(w["repos"], h, out["errors"]):
        try:
            f = forges.get(fname, h)
            branches = w.get("branches") or [f.repo(repo)["default_branch"]]
        except forges.ForgeError as e:
            out["errors"].append(str(e))
            continue
        for branch in branches:
            try:
                runs = f.runs(repo, branch)
            except forges.ForgeError as e:
                out["errors"].append(str(e))
                continue
            flows = {}
            for r in runs:           # newest first; one list per workflow
                if r["branch"] == branch and r["event"] not in PR_EVENTS and _wanted(w, r) \
                        and (r["conclusion"] in forges.RED or r["conclusion"] == "success"):
                    flows.setdefault(r["file"] or r["name"], []).append(r)
            for wf, rs in sorted(flows.items()):
                prefix = ci_key(fname, repo, branch, wf, 0)[:-1]
                streak = []
                for r in rs:
                    if r["conclusion"] == "success":
                        break
                    streak.append(r)
                last_ok = rs[len(streak)] if len(streak) < len(rs) else None
                if last_ok and last_ok["id"] > green.get(prefix, {}).get("id", 0):
                    green[prefix] = {"id": last_ok["id"], "number": last_ok["number"],
                                     "sha": last_ok["sha"], "url": last_ok["url"]}
                ok_id = green.get(prefix, {}).get("id", 0)
                mine = {k: v for k, v in made.items() if k.startswith(prefix)}
                if not dry_run:
                    for k, p in sorted(mine.items()):
                        if parse_ci_key(k)[4] < ok_id and k not in cleared:
                            _note_green(p, green[prefix], h)
                            cleared[k] = ok_id
                            out["cleared"].append(k)
                if not streak:
                    continue
                if any(parse_ci_key(k)[4] > ok_id for k in mine):
                    for k in mine:
                        if k in known and k not in s["seen"]:
                            s["seen"][k] = known[k]
                    continue                # this breakage is made already
                first = streak[-1]
                k = ci_key(fname, repo, branch, wf, first["id"])
                try:
                    last = clock.parse_iso(streak[0]["created"]).timestamp()
                except ValueError:
                    last = t
                if last < oldest:       # the newest red run: a weekly job red for weeks counts
                    out["old"].append(k)
                    continue
                fresh.append((k, {
                    "title": "%s: %s failing on %s" % (repo, first["name"] or wf, branch),
                    "url": first["url"], "latest": streak[0],
                    "count": "%d%s" % (len(streak), "+" if last_ok is None else "")}))
    return fresh


def _note_green(project, run, h):
    """Tell a CI packet its workflow passes again (a note, as ``wpk note``)."""
    from . import actions, layout
    from .packet import Packet
    if project.startswith("inbox:"):
        return
    e = registry.get(project, h)
    if e is None:
        return
    try:
        actions.note(Packet(layout.run_dir(e["path"], e["root"])),
                     "CI is green again: run #%s at commit %s passed (%s). If you have not "
                     "found the cause yet, say whether this looks flaky." % (
                         run["number"], run["sha"][:7], run["url"]), by="watch")
    except (OSError, ValueError):
        pass


def propose_date(project, issue, key, s, h=None):
    """A due date from the issue's milestone, as an Inbox item for ``project``
    (docs/collaboration.md §9.3, plan F3c): once per project and date, and only
    when the project's due is not that date already. Returns the item's id."""
    from . import inbox, planning
    m = issue.get("milestone") or {}
    due = m.get("due")
    if not due or s["dates"].get(project) == due:
        return None
    e = registry.get(project, h)
    if e is None or planning.get(e)["due"] == due:
        s["dates"][project] = due
        return None
    try:
        d = inbox.add(h or registry.home(), "%s: issue %s's milestone %s is due %s" % (
            project, key, m["title"], due), source="date", project=project,
            ref={"date": due, "project": project, "from": "%s milestone %s" % (key, m["title"]),
                 "url": issue.get("url")})
    except (ValueError, OSError):
        return None
    s["dates"][project] = due
    return d["id"]


def _expand(refs, h, errors):
    """``forge:owner/repo`` and ``forge:owner/*`` to [(forge, "owner/repo")], once each."""
    from . import forges
    out = []
    for ref in refs:
        fname, repo = ref.split(":", 1)
        owner, _, name = repo.partition("/")
        if name != "*":
            got = [repo]
        else:
            try:
                got = forges.get(fname, h).owner_repos(owner)
            except forges.ForgeError as e:
                errors.append(str(e))
                continue
        out += [(fname, r) for r in got if (fname, r) not in out]
    return out


def recipe(w, key, h=None, item=None):
    """The recipe for ``key`` from watcher ``w``: an issue (``forge:owner/repo#n``)
    or, for ``on = "ci"``, a CI breakage (``ci_key``). ``item`` is what the poll
    found (for a breakage, its latest run and how many failed)."""
    from . import starters
    vals = {"hold": "yes" if w.get("hold", True) else "no", "board": w["board"]}
    if w.get("dir"):
        vals["dir"] = os.path.expanduser(w["dir"])
    else:                       # the board's packet directory (agent-dispatch.md §3)
        if registry.packet_dir(w["board"], None, h) is None:
            raise starters.StartError("watcher %s has no dir, and neither board %s nor "
                                      "[packets] root says where packets go"
                                      % (w["name"], w["board"]))
    for k in ("from", "model", "harness"):
        if w.get(k):
            vals[k] = w[k]
    if w.get("on") == "ci":
        fname, repo, _, _, rid = parse_ci_key(key)
        r = starters.from_values("ci", dict(vals, repo="%s:%s" % (fname, repo), run=str(rid)),
                                 h)
        latest = (item or {}).get("latest")
        if latest and latest["id"] != rid:
            r["objective"] += ("\nIt has failed %s times in a row since; the latest is run "
                               "#%s at %s: %s\n" % (item["count"], latest["number"],
                                                   latest["sha"][:7], latest["url"]))
        r["origin"]["key"] = key
        repo_ref = "%s:%s" % (fname, repo)
    else:
        r = starters.from_values("issue", dict(vals, issue=key), h)
        repo_ref = key.split("#")[0]
    others = [x for x in w["repos"] if x != repo_ref
              and not (x.endswith("/*") and repo_ref.startswith(x[:-1]))]
    if others:
        r["objective"] += ("\nThe board %s also covers %s; if the fix needs them, say so "
                           "rather than working around it here.\n" % (w["board"],
                                                                      ", ".join(others)))
    if w.get("prompt"):
        p = os.path.join(registry.boards_dir(h), os.path.expanduser(w["prompt"]))
        try:
            with open(p, encoding="utf-8") as f:
                r["objective"] += "\n" + f.read()
        except OSError as e:
            raise starters.StartError("prompt %s: %s" % (w["prompt"], e)) from None
    r["origin"]["watch"] = "%s/%s" % (w["board"], w["name"])
    r["board"] = w["board"]
    return r


def poll_due(h=None, now=None, report=lambda w, r: None):
    """Poll every watcher that is due. Returns the number of packets made."""
    n = 0
    for w in watchers(h):
        if due(w, h, now):
            r = poll(w, h, now=now)
            n += len(r["made"])
            report(w, r)
    return n
