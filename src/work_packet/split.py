"""Split: the runner works beside you, in a copy (docs/collaboration.md W4, W6,
§5.4; docs/packet-ux.md U3; plan C7d).

Handing off while you are in the middle of something means the runner edits
the folder you are editing. A split avoids that. It makes a git worktree of
your packet folder, on a new branch ``wpk/<name>-split`` from your ``HEAD``,
at ``$WPK_HOME/splits/<name>-split``, and a project there with the hand-off as
its instruction. Your uncommitted edits stay with you. The runner works there,
and the split shows up as a project of its own, so its result is reviewed like
any other.

**Bring it in**:
- commits what the split left uncommitted, in the split's worktree;
- merges its branch into your folder: a fast-forward when your ``HEAD`` is
  still where the split began, else a merge commit;
- git refuses when your own edits would be overwritten, and nothing changes;
- then marks the split done.

**Drop the split** marks it dropped. Neither removes the split's folder or
branch: **Remove its folder** (``remove``) does, once it is done or dropped.
It keeps a copy of the split's journal, removes the worktree, deletes the
branch only if it was brought in, and unregisters the split.

Untracked tool folders of yours (``SHARES``: ``packages``, a virtualenv,
``node_modules``) and untracked top-level links are linked into the split, so the
runner has the same tools.

Only for a packet-layout project whose folder is a git checkout. Plain folders
(a copy in and out) and legacy ``work/`` clones are not done yet. The split
project keeps ``split.json`` (``of, base, branch, folder, made, by``) in its
project directory.
"""

import json
import os
import subprocess
import time

from . import fsutil, layout, registry, workspace

INFO = "split.json"
SHARES = ("packages", ".venv", "venv", "node_modules")
DIFF_MAX = 200 * 1024


class SplitError(Exception):
    pass


def _git(repo, *args):
    try:
        return workspace._git(repo, *args)
    except workspace.WorkspaceError as e:
        raise SplitError(str(e)) from None


def info(entry):
    """``split.json`` of a split project, or None."""
    try:
        with open(os.path.join(entry["path"], INFO)) as fp:
            d = json.load(fp)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return d if isinstance(d, dict) and d.get("of") else None


def allowed(entry):
    """None if ``entry`` can be split, else why not."""
    proj = entry["path"]
    if not layout.is_packet_layout(proj):
        return "only a packet folder can be split (this project keeps its repositories in work/)"
    if not workspace.is_git(layout.packet_folder(proj)):
        return "only a git checkout can be split (a plain folder can't yet)"
    if info(entry):
        return "this is a split already"
    return None


def of(name, h=None):
    """The splits made from project ``name``: ``[(entry, info)]``."""
    out = []
    for e in registry.entries(h):
        d = info(e)
        if d and d["of"] == name:
            out.append((e, d))
    return out


def _free(name, folder, h):
    for i in range(1, 100):
        n = "%s-split%s" % (name, "" if i == 1 else i)
        if len(n) > 64 or registry.get(n, h) is not None:
            continue
        if subprocess.run(["git", "-C", folder, "rev-parse", "--verify", "--quiet",
                           "refs/heads/wpk/" + n], capture_output=True).returncode == 0:
            continue
        if os.path.lexists(os.path.join(h, "splits", n)):
            continue
        return n
    raise SplitError("no free name for a split of %s" % name)


def make(entry, text, note=None, by=None, h=None):
    """Split ``entry``: a worktree and a project there that runs ``text``.
    Returns the new project's name."""
    from . import project
    from .hookcmd import _journal, _root
    from .packet import user
    h = h or registry.home()
    why = allowed(entry)
    if why:
        raise SplitError(why)
    text = (text or "").strip()
    if not text:
        raise SplitError("say what the runner should do in the split")
    if note and note.strip():
        text += "\n\n" + note.strip()
    folder = layout.packet_folder(entry["path"])
    base = _git(folder, "rev-parse", "HEAD")
    name = _free(entry["name"], folder, h)
    tree = os.path.join(h, "splits", name)
    os.makedirs(os.path.dirname(tree), exist_ok=True)
    try:
        workspace.add_worktree(folder, tree, "wpk/" + name)
    except workspace.WorkspaceError as e:
        raise SplitError(str(e)) from None
    try:
        workspace.link_shares(folder, tree, workspace.shares(folder, [
            n for n in SHARES if os.path.isdir(os.path.join(folder, n)) and not _tracked(
                folder, n)]))
    except OSError:
        pass                            # the split works without them
    try:
        project.new(name, text, path=tree, packet=True, h=h)
    except project.ProjectError as e:
        subprocess.run(["git", "-C", folder, "worktree", "remove", "--force", tree],
                       capture_output=True)
        raise SplitError(str(e)) from None
    new = registry.get(name, h)
    d = {"of": entry["name"], "base": base, "branch": "wpk/" + name, "folder": folder,
         "made": time.time(), "by": by or user()}
    fsutil.atomic_write(os.path.join(new["path"], INFO), json.dumps(d, sort_keys=True) + "\n")
    try:
        _journal(entry["path"], _root(entry["path"]),
                 {"type": "split", "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "to": name, "by": d["by"]})
    except OSError:
        pass
    return name


def _tracked(folder, n):
    return subprocess.run(["git", "-C", folder, "ls-files", "--error-unmatch", "--", n],
                          capture_output=True).returncode == 0


def remove(entry, by=None, h=None):
    """**Remove its folder**: a split that is done or dropped. Its journal is kept
    at ``$WPK_HOME/splits/removed/<name>.journal.jsonl``; the worktree goes; the
    branch goes only if it was brought in (``git branch -d`` refuses otherwise);
    the project is unregistered. Returns a line saying what happened."""
    from . import views
    from .hookcmd import _journal, _root
    from .packet import Packet, user
    h = h or registry.home()
    d = info(entry)
    if d is None:
        raise SplitError("%s is not a split" % entry["name"])
    root = _root(entry["path"])
    pkt = Packet(layout.run_dir(entry["path"], root))
    life = views.lifecycle(pkt.load_status()[0])
    if life == "open":
        raise SplitError("bring it in or drop it first")
    tree = layout.packet_folder(entry["path"])
    keep = os.path.join(h, "splits", "removed")
    os.makedirs(keep, exist_ok=True)
    try:
        with open(pkt.journal_path, "rb") as fp:
            fsutil.atomic_write(os.path.join(keep, entry["name"] + ".journal.jsonl"),
                                fp.read().decode("utf-8", "replace"))
    except OSError:
        pass
    r = subprocess.run(["git", "-C", d["folder"], "worktree", "remove", "--force", tree],
                       capture_output=True, text=True)
    if r.returncode and os.path.exists(tree):
        raise SplitError("git would not remove the worktree: %s" % (r.stderr or "").strip())
    subprocess.run(["git", "-C", d["folder"], "worktree", "prune"], capture_output=True)
    branch = "kept"
    if life == "done" and subprocess.run(["git", "-C", d["folder"], "branch", "-d",
                                          d["branch"]], capture_output=True).returncode == 0:
        branch = "deleted"
    registry.unregister(entry["name"], h)
    try:
        orig = registry.get(d["of"], h)
        if orig:
            _journal(orig["path"], _root(orig["path"]), {
                "type": "split", "op": "removed", "to": entry["name"], "by": by or user(),
                "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    except OSError:
        pass
    return "removed %s's folder; branch %s %s" % (entry["name"], d["branch"], branch)


def diff(entry):
    """What the split changed since it began: ``{"commits": [line], "stat",
    "text", "untracked": [path], "cut": bool}``. Reads only."""
    d = info(entry)
    if d is None:
        raise SplitError("%s is not a split" % entry["name"])
    tree = layout.packet_folder(entry["path"])
    log = _git(tree, "log", "--format=%h %s", "%s..HEAD" % d["base"])
    stat = _git(tree, "diff", "--stat", d["base"])
    text = _git(tree, "diff", d["base"])
    new = _git(tree, "ls-files", "--others", "--exclude-standard")
    return {"commits": log.splitlines() if log else [], "stat": stat,
            "text": text[:DIFF_MAX], "cut": len(text) > DIFF_MAX,
            "untracked": new.splitlines() if new else []}


def _busy(entry):
    from . import lease
    from .hookcmd import _root
    from .packet import Packet
    pkt = Packet(layout.run_dir(entry["path"], _root(entry["path"])))
    meta, _ = pkt.load_status()
    from . import views
    if views.lifecycle(meta) != "open":
        return "it is %s already" % views.lifecycle(meta)
    lz = lease.read(pkt.lease_path)
    if lz and not lease.is_stale(lz):
        return "a step is running in it"
    if meta.get("state") in ("RUNNABLE", "SLEEPING"):
        return "the runner still has it (%s): pause it first" % meta["state"]
    return None


def land(entry, by=None):
    """**Bring it in**. Returns a line saying what happened."""
    from . import executor
    from .hookcmd import _root
    from .packet import Packet
    d = info(entry)
    if d is None:
        raise SplitError("%s is not a split" % entry["name"])
    why = _busy(entry)
    if why:
        raise SplitError(why)
    tree, folder = layout.packet_folder(entry["path"]), d["folder"]
    if not workspace.is_git(folder):
        raise SplitError("%s is gone or not a git checkout" % folder)
    if _git(tree, "status", "--porcelain"):
        _git(tree, "add", "-A")
        _git(tree, "commit", "-q", "-m", "wpk: %s, uncommitted when brought in" % entry["name"])
    head = _git(folder, "rev-parse", "HEAD")
    tip = _git(tree, "rev-parse", "HEAD")
    if tip == d["base"]:
        how = "nothing to bring in"
    elif head == d["base"]:
        _git(folder, "merge", "-q", "--ff-only", d["branch"])
        how = "fast-forwarded to %s" % tip[:8]
    else:
        r = subprocess.run(["git", "-C", folder, "merge", "-q", "--no-edit", d["branch"]],
                           capture_output=True, text=True)
        if r.returncode:
            if subprocess.run(["git", "-C", folder, "rev-parse", "-q", "--verify",
                               "MERGE_HEAD"], capture_output=True).returncode == 0:
                subprocess.run(["git", "-C", folder, "merge", "--abort"], capture_output=True)
            msg = (r.stderr or r.stdout).strip().splitlines()
            raise SplitError("git would not merge it, so nothing changed: %s" % (
                " ".join(msg[:3]) or "exit %d" % r.returncode))
        how = "merged %s" % d["branch"]
    pkt = Packet(layout.run_dir(entry["path"], _root(entry["path"])))
    executor.mark(pkt, "done", by=by, note="brought into %s: %s" % (d["of"], how))
    return "%s into %s: %s" % (entry["name"], d["of"], how)


def drop(entry, by=None):
    from . import executor
    from .hookcmd import _root
    from .packet import Packet
    if info(entry) is None:
        raise SplitError("%s is not a split" % entry["name"])
    pkt = Packet(layout.run_dir(entry["path"], _root(entry["path"])))
    out = executor.mark(pkt, "drop", by=by, note="split dropped")
    return getattr(out, "msg", "dropped")


def view(entry, h=None):
    """For the project page: ``{"me": info + diff, or None, "splits": [...]}``."""
    from .hookcmd import _root
    from .packet import Packet
    out = {"me": None, "splits": [], "allowed": allowed(entry) is None}
    d = info(entry)
    if d:
        try:
            out["me"] = dict(d, diff=diff(entry), busy=_busy(entry))
        except (SplitError, OSError) as e:
            out["me"] = dict(d, diff=None, error=str(e), busy=None)
    for e, s in of(entry["name"], h):
        try:
            meta, _ = Packet(layout.run_dir(e["path"], _root(e["path"]))).load_status()
        except Exception:               # noqa: BLE001: an unreadable split still lists
            meta = {}
        from . import views
        out["splits"].append(dict(s, name=e["name"], state=meta.get("state", "?"),
                                  lifecycle=views.lifecycle(meta)))
    return out
