"""Delivery on completion (docs/agent-dispatch.md §5.4).

A packet whose ``project.toml`` has ``[deliver]`` hands its branch back when it
completes, so the agent in it never pushes::

    [deliver]
    do = "push"            # "push" | "draft-pr" | "pr"
    gate = "make test"     # optional: run first in the packet folder; non-zero holds it
    base = "master"        # optional: the branch it started from (the clone's ref)

When: only while the root packet is COMPLETED, and only for a HEAD not tried
before. NEEDS_INPUT, FAILED, PAUSED and a packet someone works on never
deliver; reopened and completed again with new commits, it delivers again.
What was tried is kept in ``[delivered]`` (head, at, ok, msg) and in the root's
journal (a ``deliver`` record), so the board shows it. A failure is not tried
again by itself: ``wpk deliver <packet> --now`` (or Push now) tries again,
``--off`` cancels delivery.

The refusals are ``pr.py``'s: a branch of its own (never the base), nothing
uncommitted, commits to push, and never a force push.
"""

import os
import subprocess

from . import layout, registry, schema
from .tomlio import load_toml

MODES = ("push", "draft-pr", "pr")
GATE_TIMEOUT_S = 3600
TAIL_LINES = 20


class DeliverError(Exception):
    pass


def _git(folder, *args):
    r = subprocess.run(["git", "-C", folder] + list(args), capture_output=True, text=True,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    if r.returncode:
        raise DeliverError("git %s: %s" % (" ".join(args[:2]), (r.stderr or r.stdout).strip()))
    return r.stdout.strip()


def _ok(folder, *args):
    return subprocess.run(["git", "-C", folder] + list(args), capture_output=True).returncode == 0


def _entry(name, h):
    e = registry.get(name, h)
    if e is None:
        raise DeliverError("no project %s" % name)
    return e


def _toml(e):
    try:
        return load_toml(os.path.join(e["path"], "project.toml"))
    except (OSError, ValueError) as ex:
        raise DeliverError(str(ex)) from None


def policy(e):
    """``[deliver]`` of project entry ``e``, or None."""
    try:
        d = _toml(e).get("deliver")
    except DeliverError:
        return None
    return d if isinstance(d, dict) and d.get("do") in MODES else None


def last(e):
    """``[delivered]``: what was last tried, or {}."""
    try:
        d = _toml(e).get("delivered")
    except DeliverError:
        return {}
    return d if isinstance(d, dict) else {}


def head(folder):
    try:
        return _git(folder, "rev-parse", "HEAD")
    except DeliverError:
        return None


def _base(folder, d):
    if d.get("base"):
        return d["base"]
    try:                                # origin's default branch
        ref = _git(folder, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    except DeliverError:
        return None
    return ref.rsplit("/", 1)[-1] if ref.startswith("refs/remotes/origin/") else None


def push(folder, d):
    """Push the branch checked out in ``folder`` to ``origin`` under its own name.
    Returns {branch, base, ahead}; raises DeliverError on a refusal."""
    if not os.path.isdir(os.path.join(folder, ".git")):
        raise DeliverError("%s is not a git clone" % folder)
    branch = _git(folder, "rev-parse", "--abbrev-ref", "HEAD")
    base = _base(folder, d)
    if branch == "HEAD":
        raise DeliverError("%s is on a detached HEAD, not a branch of its own" % folder)
    if branch == base:
        raise DeliverError("%s is on %s, the base branch: it is never pushed" % (folder, base))
    dirty = [ln[3:] for ln in subprocess.run(
        ["git", "-C", folder, "status", "--porcelain", "-uno"], capture_output=True,
        text=True).stdout.splitlines()]
    if dirty:
        raise DeliverError("changes not committed in %s: %s%s" % (
            folder, ", ".join(dirty[:5]), " …" if len(dirty) > 5 else ""))
    if not _ok(folder, "remote", "get-url", "origin"):
        raise DeliverError("%s has no remote named origin" % folder)
    since = None
    for ref in ("refs/remotes/origin/" + branch, "refs/remotes/origin/" + (base or ""),
                base or ""):
        if ref and _ok(folder, "rev-parse", "--verify", "-q", ref):
            since = ref
            break
    ahead = int(_git(folder, "rev-list", "--count", "%s..HEAD" % since)) if since else None
    if ahead == 0:
        raise DeliverError("%s has no commits beyond %s: nothing to push" % (
            branch, since.replace("refs/remotes/", "")))
    _git(folder, "push", "-u", "origin", "%s:%s" % (branch, branch))
    return {"branch": branch, "base": base, "ahead": ahead}


def gate(folder, cmd, timeout=GATE_TIMEOUT_S):
    """Run the gate in ``folder``. Returns None if it passed, else why (with the
    end of its output)."""
    try:
        r = subprocess.run(cmd, shell=True, cwd=folder, capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "gate `%s` took more than %ds" % (cmd, timeout)
    except OSError as e:
        return "gate `%s`: %s" % (cmd, e)
    if r.returncode == 0:
        return None
    tail = "\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-TAIL_LINES:])
    return "gate `%s` failed (exit %d)%s" % (cmd, r.returncode, ":\n" + tail if tail else "")


def _record(e, rec, by):
    """``[delivered]`` and the root's journal."""
    from . import journal, project
    from .packet import Packet

    def put(d):
        d["delivered"] = {k: v for k, v in rec.items() if isinstance(v, (str, int))}
        return ["delivered: %s" % rec["msg"].splitlines()[0]]
    try:
        project.change_settings(e["path"], put, by)
    except project.ProjectError:
        pass                            # a step is running: the journal still has it
    pkt = Packet(layout.run_dir(e["path"], e["root"]))
    journal.append(pkt.journal_path, dict(
        {"type": "deliver", "t": schema.format_timestamp(_now()), "by": by}, **rec))


def _now():
    from . import clock
    return clock.now()


def run(name, h=None, by="wpk"):
    """Deliver ``name`` now, whatever its state (``wpk deliver --now``).
    Returns {ok, msg, ...}; the result is recorded either way."""
    from . import pr
    e = _entry(name, h)
    d = policy(e)
    if d is None:
        raise DeliverError("%s has no [deliver]: nothing to do" % name)
    folder = layout.packet_folder(e["path"])
    rec = {"do": d["do"], "head": head(folder) or "", "at": schema.format_timestamp(_now())}
    why = gate(folder, d["gate"]) if d.get("gate") else None
    if why:
        rec.update(ok=0, msg="Delivery held: " + why)
        _record(e, rec, by)
        return dict(rec, ok=False)
    try:
        if d["do"] == "push":
            r = push(folder, d)
            rec.update(ok=1, branch=r["branch"], msg="pushed %s%s to origin" % (
                r["branch"], " (%d commit%s)" % (r["ahead"], "" if r["ahead"] == 1 else "s")
                if r["ahead"] else ""))
        else:
            r = pr.open_pr(name, h, draft=d["do"] == "draft-pr", by=by)
            rec.update(ok=1, branch=r["branch"], url=r["url"], msg="%s %s" % (
                "opened" if r["new"] else "pushed; already open:", r["url"]))
    except (DeliverError, pr.PRError) as ex:
        rec.update(ok=0, msg="Push failed: %s" % ex)
    _record(e, rec, by)
    return dict(rec, ok=bool(rec["ok"]))


def off(name, h=None, by="wpk"):
    """Cancel delivery: ``[deliver]`` removed. Returns whether there was one."""
    from . import project
    e = _entry(name, h)

    def drop(d):
        return ["deliver: off"] if d.pop("deliver", None) is not None else []
    try:
        return bool(project.change_settings(e["path"], drop, by))
    except project.ProjectError as ex:
        raise DeliverError(str(ex)) from None


def due(e):
    """Whether ``e`` delivers now: it has ``[deliver]``, its root is COMPLETED,
    and its HEAD was not tried yet."""
    from . import pr
    if policy(e) is None or pr.state(e) != "COMPLETED":
        return False
    h = head(layout.packet_folder(e["path"]))
    return bool(h) and last(e).get("head") != h


def sync(h=None, report=lambda name, msg, ok: None):
    """Deliver each packet that is due. Returns how many were tried."""
    n = 0
    for e in registry.entries(h):
        try:
            if not due(e):
                continue
            r = run(e["name"], h, by="deliver")
        except DeliverError as ex:
            report(e["name"], str(ex), False)
            continue
        report(e["name"], r["msg"], r["ok"])
        n += 1
    return n


def badge(e):
    """For the board: None, or {text, ok, msg}."""
    d = policy(e)
    if d is None:
        return None
    rec = last(e)
    if rec.get("msg"):
        return {"text": rec["msg"].splitlines()[0], "ok": bool(rec.get("ok")),
                "pending": False}
    what = {"push": "push", "draft-pr": "open a draft PR", "pr": "open a PR"}[d["do"]]
    return {"text": "Will %s on completion%s" % (what, " if `%s` passes" % d["gate"]
                                                  if d.get("gate") else ""),
            "ok": True, "pending": True}
