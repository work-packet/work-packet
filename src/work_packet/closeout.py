"""Closing a packet: what is still outstanding in it (docs/close-remove-plan.md).

``check(entry)`` reads; it changes nothing. Its findings have a severity:

- ``busy``: something is live (a step, queued work, a person, an open
  question, an open child). Closing now would interrupt it.
- ``unsaved``: deleting the folder would lose it (uncommitted or untracked
  files, commits on no remote, stashes, a folder that is not in git at all).
- ``note``: worth saying, never in the way (still open, say).

Every git repo under the packet folder is looked at, not just the top one:
an IVPM clone is several. Symlinks are not followed; what a link points at is
not the packet's to lose.
"""

import hashlib
import json
import os
import subprocess
import time

from . import layout, registry

BUSY, UNSAVED, NOTE = "busy", "unsaved", "note"
SEVERITIES = (BUSY, UNSAVED, NOTE)
# Folders a repo walk never goes into: generated, or the packet's own records.
SKIP_DIRS = {".git", layout.DOT, "node_modules", "__pycache__", ".venv", "venv",
             ".mypy_cache", ".pytest_cache", ".tox"}
SHOW_FILES = 20             # porcelain lines kept per repo for the page


def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode:
        raise OSError((r.stderr or "git %s failed" % args[0]).strip())
    return r.stdout


def _is_repo(d):
    return os.path.exists(os.path.join(d, ".git"))


def repos(folder, extra=()):
    """The git repos under ``folder`` (``folder`` itself first when it is one),
    plus ``extra`` (the legacy ``work/`` trees). Real paths, no duplicates."""
    out, seen = [], set()

    def add(p):
        r = os.path.realpath(p)
        if r not in seen:
            seen.add(r)
            out.append(p)
    for dp, dns, _ in os.walk(folder):
        if _is_repo(dp):
            add(dp)
        dns[:] = sorted(n for n in dns if n not in SKIP_DIRS
                        and not os.path.islink(os.path.join(dp, n)))
    for p in extra:
        if os.path.isdir(p) and _is_repo(p):
            add(p)
    return out


def _ignore_paths(repo, folder, name):
    """Paths in ``repo`` that are the packet's own or generated, not work: the
    card and ``.work-packet/`` (both harvested on close), and IVPM's skills."""
    from . import workspace
    out = list(workspace.agent_links(repo))
    if os.path.realpath(repo) == os.path.realpath(folder):
        out += [layout.DOT, name + ".wp.md"]
    return out


def repo_state(repo, folder, name):
    """``{path, branch, changed, untracked, ahead: {branch: n}, unpushed, stashes,
    remotes, error}`` for one repo. ``unpushed``: commits on no remote, counted
    once however many branches hold them."""
    rel = os.path.relpath(repo, folder)
    st = {"path": "." if rel == "." else rel, "branch": None, "changed": [],
          "untracked": [], "ahead": {}, "unpushed": 0, "stashes": 0,
          "remotes": [], "kept_in": None, "error": None}
    try:
        skip = _ignore_paths(repo, folder, name)
        spec = ["--", "."] + [":(exclude)%s" % x for x in skip]
        for ln in _git(repo, "status", "--porcelain", *spec).splitlines():
            (st["untracked"] if ln.startswith("??") else st["changed"]).append(ln)
        head = _git(repo, "symbolic-ref", "-q", "--short", "HEAD") if subprocess.run(
            ["git", "-C", repo, "symbolic-ref", "-q", "HEAD"],
            capture_output=True).returncode == 0 else ""
        st["branch"] = head.strip() or None
        st["remotes"] = _git(repo, "remote").split()
        has_head = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", "HEAD"],
                                  capture_output=True).returncode == 0
        if has_head:
            for b in _git(repo, "for-each-ref", "--format=%(refname:short)",
                          "refs/heads").split():
                n = int(_git(repo, "rev-list", "--count", "refs/heads/" + b,
                             "--not", "--remotes").strip() or 0)
                if n:
                    st["ahead"][b] = n
            st["unpushed"] = int(_git(repo, "rev-list", "--count", "HEAD", "--branches",
                                      "--not", "--remotes").strip() or 0)
        st["stashes"] = len(_git(repo, "stash", "list").splitlines())
        # A worktree of a repo outside the folder: its commits live on there.
        common = os.path.realpath(os.path.join(repo, _git(
            repo, "rev-parse", "--git-common-dir").strip()))
        top = os.path.realpath(folder)
        if not (common + os.sep).startswith(top + os.sep):
            st["kept_in"] = os.path.dirname(common) if os.path.basename(common) == ".git" \
                else common
    except (OSError, ValueError) as ex:
        st["error"] = str(ex)
    return st


def _finding(kind, sev, msg, **kw):
    return dict(kw, kind=kind, severity=sev, msg=msg)


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _repo_findings(st):
    out, where = [], st["path"]
    if st["error"]:
        out.append(_finding("git-error", UNSAVED, "git could not read it: %s" % st["error"],
                            repo=where))
        return out
    if st["changed"]:
        out.append(_finding("changed", UNSAVED, "%s not committed"
                            % _plural(len(st["changed"]), "changed file"), repo=where,
                            n=len(st["changed"]), files=st["changed"][:SHOW_FILES]))
    if st["untracked"]:
        out.append(_finding("untracked", UNSAVED, "%s not in git"
                            % _plural(len(st["untracked"]), "new file"), repo=where,
                            n=len(st["untracked"]), files=st["untracked"][:SHOW_FILES]))
    if st["unpushed"] and st["kept_in"]:
        out.append(_finding("kept", NOTE, "%s on no remote, kept in %s (this is a worktree of it)"
                            % (_plural(st["unpushed"], "commit"), st["kept_in"]), repo=where,
                            n=st["unpushed"]))
    elif st["unpushed"]:
        bits = ", ".join("%s +%d" % (b, n) for b, n in sorted(st["ahead"].items()))
        msg = "%s on no remote" % _plural(st["unpushed"], "commit")
        if not st["remotes"]:
            msg += " (it has no remote)"
        out.append(_finding("unpushed", UNSAVED, msg + (": " + bits if bits else ""),
                            repo=where, n=st["unpushed"], branches=st["ahead"]))
    if st["stashes"]:
        out.append(_finding("stash", UNSAVED, _plural(st["stashes"], "stash"), repo=where,
                            n=st["stashes"]))
    return out


def _wpids(entry):
    try:
        return sorted(n for n in os.listdir(layout.runs_dir(entry["path"]))
                      if not n.startswith("."))
    except OSError:
        return []


def _busy(entry, wpids, h):
    from . import jobs, lease, presence, questions
    from .packet import Packet
    out = []
    proj = entry["path"]
    for w in wpids:
        pkt = Packet(layout.run_dir(proj, w))
        try:
            lz = lease.read(pkt.lease_path)
        except (OSError, ValueError):
            lz = None
        if lz and not lease.is_stale(lz):
            out.append(_finding("running", BUSY, "a step is running", wpid=w))
        qs = questions.of_packet(pkt)
        if qs:
            out.append(_finding("question", BUSY, "%s waiting for an answer"
                                % _plural(len(qs), "question"), wpid=w, n=len(qs)))
        try:
            meta = pkt.load_status()[0]
        except (OSError, ValueError):
            meta = {}
        if meta.get("taken_by"):
            out.append(_finding("taken", BUSY, "taken for the studio by %s" % meta["taken_by"],
                                wpid=w))
    try:
        from .sched import jobs as sjobs
        q = [r for r in sjobs.all(h) if r.wpid in wpids and not r.cancel
             and r.state in ("PENDING", "RUNNING")]
    except Exception:                   # noqa: BLE001: no scheduler state is no queue
        q = []
    if q:
        out.append(_finding("queued", BUSY, "%s queued or running in the scheduler"
                            % _plural(len(q), "job"), jobs=[r.id for r in q]))
    try:
        js = jobs.live(proj)
    except OSError:
        js = []
    if js:
        out.append(_finding("job", BUSY, "%s running" % _plural(len(js), "job"),
                            jobs=[d["id"] for d in js]))
    recs = presence.live(proj)
    if recs:
        out.append(_finding("presence", BUSY, "someone is in it: %s"
                            % (presence.where(recs) or "a session"), n=len(recs)))
    try:
        from . import ide_stranded
        st = [s for w in wpids for s in ide_stranded.for_packet(h, w)]
    except Exception:                   # noqa: BLE001: no /proc, no desks
        st = []
    if st:
        out.append(_finding("stranded", BUSY, "%s left behind by its desk"
                            % _plural(len(st), "VS Code server"), n=len(st)))
    kids = children(entry, wpids, h)
    opened = [k for k in kids if k["lifecycle"] == "open"]
    if opened:
        out.append(_finding("children", BUSY, "%s still open: %s" % (
            _plural(len(opened), "packet made from it"), ", ".join(k["name"] for k in opened)),
            names=[k["name"] for k in opened]))
    return out


def _only_hooks(d):
    """A ``.claude/`` holding nothing but the ``settings.local.json`` wpk writes
    (its hooks and status line, sessionhooks.py)."""
    try:
        return set(os.listdir(d)) <= {"settings.local.json"}
    except OSError:
        return False


def lifecycle(entry):
    """The project's lifecycle (its root packet's): open, done or dropped."""
    from . import views
    from .hookcmd import _root
    from .packet import Packet
    root = _root(entry["path"])
    if not root:
        return "open"
    try:
        return views.lifecycle(Packet(layout.run_dir(entry["path"], root)).load_status()[0])
    except (OSError, ValueError):
        return "open"


def origin(entry):
    from .tomlio import load_toml
    try:
        return load_toml(os.path.join(entry["path"], "project.toml")).get("origin") or {}
    except (OSError, ValueError):
        return {}


def children(entry, wpids=None, h=None):
    """The registered projects made from a session in one of ``entry``'s
    packets (``[origin] by``): ``[{name, lifecycle}]``."""
    want = {"packet:%s" % w for w in (wpids if wpids is not None else _wpids(entry))}
    out = []
    for e in registry.entries(h):
        if e["name"] != entry["name"] and origin(e).get("by") in want:
            out.append({"name": e["name"], "lifecycle": lifecycle(e)})
    return out


def fingerprint(findings):
    """What a person saw: the findings minus their wording, for the close
    form to send back (a change since then refuses)."""
    keys = sorted(json.dumps({k: f.get(k) for k in ("kind", "severity", "repo", "wpid", "n")},
                             sort_keys=True) for f in findings)
    return hashlib.sha1("\n".join(keys).encode()).hexdigest()[:16]


def check(entry, h=None):
    """What is outstanding in ``entry``'s packet: ``{name, folder, git, repos,
    findings, counts: {severity: n}, fp, checked}``. Reads only."""
    from . import workspace
    from .packet import Packet
    h = h or registry.home()
    proj = entry["path"]
    folder = layout.packet_folder(proj)
    wpids = _wpids(entry)
    findings = _busy(entry, wpids, h)
    extra = []
    for w in wpids:
        extra += workspace.git_trees(Packet(layout.run_dir(proj, w))).values()
    sts = [repo_state(r, folder, entry["name"]) for r in repos(folder, extra)] \
        if os.path.isdir(folder) else []
    for st in sts:
        findings += _repo_findings(st)
    if not os.path.isdir(folder):
        findings.append(_finding("missing", NOTE, "the folder is gone: %s" % folder))
    elif not sts:
        own = {layout.DOT, entry["name"] + ".wp.md"}
        try:
            mine = [n for n in os.listdir(folder) if n not in own
                    and not (n == ".claude" and _only_hooks(os.path.join(folder, n)))]
        except OSError:
            mine = []
        if mine:                        # not just the packet's own files (harvested)
            findings.append(_finding("no-git", UNSAVED, "not in git: these files are "
                                     "nowhere else", n=len(mine), files=sorted(mine)[:SHOW_FILES]))
    life = lifecycle(entry)
    if life == "open":
        findings.append(_finding("open", NOTE, "it is still open: closing marks it done"))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
    res = {"name": entry["name"], "folder": folder, "git": bool(sts), "repos": sts,
           "lifecycle": life, "findings": findings, "counts": counts,
           "fp": fingerprint(findings), "checked": time.time()}
    try:
        remember(res, h)
    except OSError:
        pass
    return res


# --- the board's view: the last check of each packet ----------------------------
#
# A check runs git in every repo, so the board never runs one while it draws a
# page: it shows the last one, kept here. A check is run when a packet is
# marked done, when its close page opens, and on Check all.

def cache_path(name, h=None):
    return os.path.join(h or registry.home(), "cache", "outstanding", name + ".json")


def remember(res, h=None):
    from . import fsutil
    p = cache_path(res["name"], h)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, json.dumps(res, default=str))


def cached(name, h=None):
    try:
        with open(cache_path(name, h), encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return None


def drop_cached(name, h=None):
    try:
        os.unlink(cache_path(name, h))
    except OSError:
        pass


CHIPS = (("busy", lambda f: f["severity"] == BUSY, "something is live in it"),
         ("uncommitted", lambda f: f["kind"] in ("changed", "untracked", "stash"),
          "files not committed"),
         ("unpushed", lambda f: f["kind"] == "unpushed", "commits on no remote"),
         ("not in git", lambda f: f["kind"] == "no-git", "the folder is not in git"))


def chips(res):
    """``[{text, title}]`` for a card: what kinds of outstanding work it has."""
    if not res:
        return []
    out = []
    for text, pick, title in CHIPS:
        fs = [f for f in res["findings"] if pick(f)]
        if fs:
            out.append({"text": text, "title": "%s: %s" % (title, "; ".join(
                ("%s: " % f["repo"] if f.get("repo") not in (None, ".") else "") + f["msg"]
                for f in fs))})
    return out


def board_view(names, h=None):
    """``{name: {chips, checked, clean, ready}}`` from the cache, for the names
    that have a check. ``clean``: nothing busy or unsaved."""
    out = {}
    for n in names:
        r = cached(n, h)
        if r is None:
            continue
        c = r.get("counts") or {}
        clean = not c.get(BUSY) and not c.get(UNSAVED)
        out[n] = {"chips": chips(r), "checked": r.get("checked"), "clean": clean,
                  "fp": r.get("fp")}
    return out


def code(res):
    """The exit code ``wpk check`` gives: 0 clean, 1 notes only, 2 busy or unsaved."""
    c = res["counts"]
    return 2 if c[BUSY] or c[UNSAVED] else 1 if c[NOTE] else 0


def summary(res):
    """One short line: "clean", or "busy: …; unsaved: …"."""
    parts = []
    for sev in (BUSY, UNSAVED):
        fs = [f for f in res["findings"] if f["severity"] == sev]
        if fs:
            parts.append("%s: %s" % (sev, "; ".join(
                ("%s: %s" % (f["repo"], f["msg"])) if f.get("repo") not in (None, ".")
                else f["msg"] for f in fs)))
    return " | ".join(parts) or "clean"


def render(res):
    """``wpk check``'s text."""
    lines = ["%s  %s" % (res["name"], res["folder"])]
    names = {BUSY: "Busy (closing now would interrupt these)",
             UNSAVED: "Unsaved (deleting the folder would lose these)", NOTE: "Notes"}
    for sev in SEVERITIES:
        fs = [f for f in res["findings"] if f["severity"] == sev]
        if not fs:
            continue
        lines.append(names[sev])
        for f in fs:
            where = "%s: " % f["repo"] if f.get("repo") not in (None, ".") else ""
            lines.append("  - %s%s" % (where, f["msg"]))
            for ln in f.get("files") or []:
                lines.append("      %s" % ln)
    if not any(res["counts"].values()):
        lines.append("clean: nothing outstanding")
    return "\n".join(lines)


# --- closing ------------------------------------------------------------------
#
# A closed packet's registry entry moves to ``<home>/closed/<name>@<stamp>.toml``
# (with what the check found at close), so it leaves every active view but its
# history stays reachable, and its name is free again. Closing harvests its runs
# into the history store first; deleting bundles its commits on no remote there.

# Busy findings close stops itself, with ``stop``: the rest wait for a person.
STOPPABLE = ("queued", "stranded")


class CloseError(Exception):
    pass


def closed_dir(h=None):
    return os.path.join(h or registry.home(), "closed")


def _stamp(t):
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(t))


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def closed(h=None):
    """Every closed record, newest first. Each has ``id`` (its file's name)."""
    from .tomlio import load_toml
    d = closed_dir(h)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = []
    for n in names:
        if n.endswith(".toml") and not n.startswith("."):
            try:
                out.append(dict(load_toml(os.path.join(d, n)), id=n[:-5]))
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda r: r.get("closed", ""), reverse=True)


def get_closed(cid, h=None):
    from .tomlio import load_toml
    if "/" in cid or cid.startswith("."):
        return None
    try:
        return dict(load_toml(os.path.join(closed_dir(h), cid + ".toml")), id=cid)
    except (OSError, ValueError):
        return None


def _save_closed(rec, h):
    from .tomlio import save_toml
    os.makedirs(closed_dir(h), exist_ok=True)
    save_toml(os.path.join(closed_dir(h), rec["id"] + ".toml"),
              {k: v for k, v in rec.items() if k != "id" and v is not None})


def owned(entry):
    """Whether wpk made the packet's folder (so ``delete`` may remove it): its
    ``[origin] made`` says ``new``, or it is a split. Packets made before wpk wrote
    ``made`` say nothing, and count as the user's."""
    from . import split
    return origin(entry).get("made") == "new" or split.info(entry) is not None


def _stop(entry, res, by, h):
    """Stop the busy findings close may stop itself. Returns lines saying what."""
    out = []
    wpids = set(_wpids(entry))
    kinds = {f["kind"] for f in res["findings"] if f["severity"] == BUSY}
    if "queued" in kinds:
        from .sched import control
        got = control.cancel_jobs(lambda r: r.wpid in wpids and r.state == "PENDING",
                                  by, "packet closed", h=h, lost=False)
        out.append("cancelled %s" % _plural(len(got), "queued job"))
    if "stranded" in kinds:
        from . import ide_stranded
        n = 0
        for w in wpids:
            for s in ide_stranded.for_packet(h, w):
                n += bool(ide_stranded.end_server(s["key"], s["pid"]))
        out.append("ended %s" % _plural(n, "stranded VS Code server"))
    return out


def _harvest(entry, h):
    from . import history
    proj = entry["path"]
    try:
        with open(layout.card_path(proj, entry["name"]), encoding="utf-8") as fp:
            card = fp.read()
    except OSError:
        card = None
    from .hookcmd import _root
    root = _root(proj)
    con = history.connect(h)
    try:
        for w in _wpids(entry):
            history.harvest(entry["name"], layout.run_dir(proj, w),
                            card if w == root else None, h=h, con=con)
    finally:
        con.close()


def bundle_dir(cid, h=None):
    return os.path.join(h or registry.home(), "history", "bundles", cid)


def _bundle(res, cid, h):
    """A ``git bundle`` of each repo's commits on no remote. Returns ``[{repo,
    file, commits, remote?}]``; raises CloseError if one cannot be made. With a
    remote the bundle is thin: clone ``remote``, then ``git fetch <file>``."""
    out = []
    for st in res["repos"]:
        if not st["unpushed"] or st["kept_in"] or st["error"]:
            continue
        repo = os.path.join(res["folder"], st["path"])
        safe = "top" if st["path"] == "." else st["path"].replace(os.sep, "__")
        path = os.path.join(bundle_dir(cid, h), safe + ".bundle")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        args = ["bundle", "create", path, "HEAD", "--branches"]
        if st["remotes"]:
            args += ["--not", "--remotes"]
        try:
            _git(repo, *args)
            _git(repo, "bundle", "verify", path)
        except OSError as ex:
            raise CloseError("could not keep %s's commits: %s" % (st["path"], ex)) from None
        b = {"repo": st["path"], "file": path, "commits": st["unpushed"]}
        if st["remotes"]:               # a thin bundle: restore on a clone of this
            try:
                b["remote"] = _git(repo, "remote", "get-url", st["remotes"][0]).strip()
            except OSError:
                pass
        out.append(b)
    return out


def _rmtree(folder):
    import shutil
    if os.path.isfile(os.path.join(folder, ".git")):        # a worktree: tell its repo
        try:
            common = os.path.realpath(os.path.join(folder, _git(
                folder, "rev-parse", "--git-common-dir").strip()))
            _git(common, "worktree", "remove", "--force", folder)
        except OSError:
            pass
    if os.path.lexists(folder):
        shutil.rmtree(folder)
    if os.path.lexists(folder):
        raise OSError("%s is still there" % folder)


def close(entry, by=None, stop=False, drop=False, delete=False, force=False, fp=None,
          note=None, keep_lifecycle=False, rm_later=False, with_children=False, h=None):
    """Take ``entry`` off the board (docs/close-remove-plan.md §2), and with
    ``delete`` remove its folder too (§3). Refuses (CloseError) while something
    is busy (``stop`` ends what it can first), and for ``delete``: a folder wpk
    did not make, or unsaved work other than commits (which are bundled) unless
    ``force``. ``fp``: the fingerprint the person saw; a change refuses.
    ``keep_lifecycle``: leave an open packet open (``wpk rm``). ``rm_later``:
    do not delete the folder here; the record says ``deleting``, and the
    caller runs ``delete_folder(rec, _checked=True)`` (the board, in a thread:
    a big clone takes a while). ``with_children``: close the open packets made
    from it first, each by the same rules (and their folders too with
    ``delete``); one that refuses stops it, and those closed stay closed.
    Returns the closed record."""
    from . import executor, split
    from .hookcmd import _journal, _root
    from .packet import Packet, user
    h = h or registry.home()
    by = by or user()
    res = check(entry, h)
    if fp and fp != res["fp"]:
        raise CloseError("something changed since you looked: check it again")
    done = []
    kids = [k for k in children(entry, h=h) if k["lifecycle"] == "open"] \
        if with_children else []
    for k in kids:
        ke = registry.get(k["name"], h)
        if ke is None:
            continue
        try:
            close(ke, by=by, stop=stop, drop=drop, delete=delete, force=force, note=note,
                  rm_later=rm_later, with_children=True, h=h)
        except CloseError as ex:
            raise CloseError("%s, made from it, would not close: %s" % (k["name"], ex)) \
                from None
        done.append("closed %s" % k["name"])
    if kids or stop:
        if stop:
            done += _stop(entry, res, by, h)
        res = check(entry, h)
    busy = [f for f in res["findings"] if f["severity"] == BUSY]
    if busy:
        raise CloseError("it is busy: " + "; ".join(f["msg"] for f in busy))
    folder = res["folder"]
    if delete:
        if not owned(entry):
            raise CloseError("wpk did not make %s, so it will not delete it: close it, "
                             "then delete the folder yourself" % folder)
        lost = [f for f in res["findings"] if f["severity"] == UNSAVED
                and f["kind"] != "unpushed"]
        if lost and not force:
            raise CloseError("deleting would lose: %s (force to delete anyway)"
                             % "; ".join(f["msg"] for f in lost))
    proj = entry["path"]
    root = _root(proj)
    now = time.time()
    cid = "%s@%s" % (entry["name"], _stamp(now))
    # An archived project's runs are gone (already in history): nothing to mark.
    pkt = Packet(layout.run_dir(proj, root)) \
        if root and os.path.isdir(layout.run_dir(proj, root)) else None
    if pkt is not None and res["lifecycle"] == "open" and not keep_lifecycle:
        out = executor.mark(pkt, "drop" if drop else "done", by=by, note=note)
        if out.code:
            raise CloseError(out.msg)
    _journal(proj, root, {"type": "admin", "op": "closed", "by": by, "t": _iso(now),
                          "delete": bool(delete), "summary": summary(res),
                          **({"note": note} if note else {})})
    try:
        _harvest(entry, h)
    except Exception as ex:             # noqa: BLE001: nothing is moved or deleted then
        raise CloseError("could not keep its history: %s" % ex) from None
    bundles = _bundle(res, cid, h) if delete else []
    rec = {"id": cid, "name": entry["name"], "closed": _iso(now), "by": by,
           "lifecycle": lifecycle(entry), "folder": folder, "board": registry.board_of(entry),
           "summary": summary(res), "counts": res["counts"], "owned": owned(entry),
           "split": split.info(entry) is not None, "entry": dict(entry),
           "bundles": bundles, "note": note, "stopped": done}
    _save_closed(rec, h)
    registry.unregister(entry["name"], h)
    drop_cached(entry["name"], h)
    if delete and rm_later:
        rec["deleting"] = _iso(time.time())
        _save_closed(rec, h)
    elif delete:
        delete_folder(rec, h=h, _checked=True)
        rec = get_closed(cid, h)
    return rec


def delete_folder(rec, force=False, h=None, _checked=False, rm_later=False):
    """Delete a closed packet's folder (closed, files kept, then **Delete
    folder**): the same rules as ``close(delete=True)``. ``rm_later``: check and
    bundle only, mark it ``deleting``, and leave the removal to the caller
    (``delete_folder(rec, _checked=True)``). Returns the record."""
    h = h or registry.home()
    folder = rec["folder"]
    if not _checked:
        if rec.get("deleted"):
            raise CloseError("its folder was deleted already")
        if rec.get("deleting"):
            raise CloseError("its folder is being deleted")
        if not (rec.get("owned") or origin(rec["entry"]).get("made") == "new"):
            raise CloseError("wpk did not make %s, so it will not delete it" % folder)
        if os.path.isdir(folder):
            res = check(dict(rec["entry"]), h)
            lost = [f for f in res["findings"] if f["severity"] == UNSAVED
                    and f["kind"] != "unpushed"]
            if lost and not force:
                raise CloseError("deleting would lose: %s (force to delete anyway)"
                                 % "; ".join(f["msg"] for f in lost))
            rec = dict(rec, bundles=(rec.get("bundles") or []) + _bundle(res, rec["id"], h))
        if rm_later:
            rec = dict(rec, deleting=_iso(time.time()))
            _save_closed(rec, h)
            return rec
    try:
        if os.path.lexists(folder):
            _rmtree(folder)
    except OSError as ex:
        rec = dict(rec, delete_error=str(ex))
        rec.pop("deleting", None)
        _save_closed(rec, h)
        raise CloseError("closed, but its folder is still there: %s" % ex) from None
    rec = dict(rec, deleted=_iso(time.time()))
    rec.pop("delete_error", None)
    rec.pop("deleting", None)
    _save_closed(rec, h)
    return rec


def reopen(cid, h=None):
    """Put a closed packet back on its board (main if that board is gone). Its
    lifecycle stays done: Reopen on its page opens it. Returns the entry."""
    h = h or registry.home()
    rec = get_closed(cid, h)
    if rec is None:
        raise CloseError("no closed packet %r" % cid)
    e = dict(rec["entry"])
    if rec.get("deleting"):
        raise CloseError("its folder is being deleted")
    if rec.get("deleted") or not os.path.isdir(layout.runs_dir(e["path"])):
        raise CloseError("its folder is gone: %s" % rec["folder"])
    if registry.get(e["name"], h) is not None:
        raise CloseError("a packet named %s is registered again" % e["name"])
    if e.get("board") and e["board"] not in {b["name"] for b in registry.boards(h)}:
        e.pop("board")
    registry.register(e, h)
    forget(cid, h)
    return e


def forget(cid, h=None):
    """Remove a closed record. The history store keeps its runs."""
    try:
        os.unlink(os.path.join(closed_dir(h), cid + ".toml"))
    except FileNotFoundError:
        raise CloseError("no closed packet %r" % cid) from None
