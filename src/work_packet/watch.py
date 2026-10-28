"""Watchers: a board polls issue trackers and starts a packet per new issue
(docs/starters-v1.md, Watchers).

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
    return s


def _save_state(w, s, h):
    p = state_path(w, h)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, json.dumps(s, indent=1, sort_keys=True))


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
    """Issues that are the origin of a registered project: {key: project}."""
    out = {}
    for e in registry.entries(h):
        try:
            o = load_toml(os.path.join(e["path"], "project.toml")).get("origin")
        except (OSError, ValueError):
            continue
        if isinstance(o, dict) and o.get("kind") == "issue" and isinstance(
                o.get("number"), int):
            out[_key(o.get("forge", ""), o.get("repo", ""), o["number"])] = e["name"]
    return out


# --- a poll -----------------------------------------------------------------------

def poll(w, h=None, dry_run=False, now=None):
    """Poll one watcher. Returns {made: [(key, project)], would: [key],
    failed: {key: error}, errors: [str]}. Only one poll of a watcher at a time
    (a lock beside its state file)."""
    from . import forges, starters
    out = {"made": [], "would": [], "failed": {}, "errors": []}
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
        labels = w.get("labels") or []
        fresh = []
        for fname, repo in _expand(w["repos"], h, out["errors"]):
            ref = "%s:%s" % (fname, repo)
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
                if k in s["seen"]:
                    continue
                if k in known:
                    s["seen"][k] = known[k]
                    continue
                fresh.append((k, ref, i))
        fresh.sort(key=lambda x: x[0] in s["failed"])     # new ones before retries
        for k, ref, i in fresh[:w.get("max_new", MAX_NEW)]:
            if dry_run:
                out["would"].append(k)
                continue
            try:
                plan = starters.make(recipe(w, k, h), h)
                registry.move(plan.name, w["board"], h)
            except (starters.StartError, registry.BoardError, OSError) as e:
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


def recipe(w, key, h=None):
    """The recipe for issue ``key`` (``forge:owner/repo#n``) from watcher ``w``."""
    from . import starters
    vals = {"issue": key, "dir": os.path.expanduser(w["dir"]),
            "hold": "yes" if w.get("hold", True) else "no"}
    for k in ("from", "model", "harness"):
        if w.get(k):
            vals[k] = w[k]
    r = starters.from_values("issue", vals, h)
    others = [x for x in w["repos"] if x != key.split("#")[0]
              and not (x.endswith("/*") and key.startswith(x[:-1]))]
    if others:
        r["objective"] += ("\nThe board %s also covers %s; if the fix needs them, say so "
                           "rather than working around it here.\n" % (w["board"],
                                                                      ", ".join(others)))
    r["origin"]["watch"] = "%s/%s" % (w["board"], w["name"])
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
