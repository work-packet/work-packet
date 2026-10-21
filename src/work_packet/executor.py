"""``wpk step`` and ``wpk recover``: one step of one packet (stage1-plan §4)."""

import difflib
import json
import os
import shutil
import uuid
from dataclasses import dataclass

from . import clock, faults, frontmatter, fsutil, journal, model, prompt, schema, spawn
from .lease import Lease, LeaseHeld
from .packet import Packet
from .project import ProjectError, project_of, settings

OK, FAILED, NOT_RUNNABLE, LEASED, USAGE = 0, 1, 2, 3, 4
LEASE_MARGIN_S = 120


@dataclass
class Outcome:
    code: int
    msg: str


class UsageError(Exception):
    pass


# --- finding the packet ------------------------------------------------------

def resolve_packet(target):
    """A packet directory, or a project directory (meaning its root packet)."""
    p = os.path.abspath(target)
    if os.path.isfile(os.path.join(p, "status.md")):
        return Packet(p)
    if os.path.isfile(os.path.join(p, "project.toml")):
        from .project import load_project
        try:
            root = load_project(p)["root"]
        except ProjectError as e:
            raise UsageError(str(e)) from None
        return Packet(os.path.join(p, "packets", root))
    raise UsageError("%s is not a packet or project directory" % target)


def _context(target):
    pkt = resolve_packet(target)
    proj = project_of(pkt.path)
    if proj is None:
        raise UsageError("%s is not inside a project (no ../../project.toml)" % pkt.path)
    try:
        st = settings(proj)
    except ProjectError as e:
        raise UsageError(str(e)) from None
    return pkt, st


def _ts(dt=None):
    return schema.format_timestamp(dt or clock.now())


def _rmtree(p):
    if os.path.lexists(p):
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.unlink(p)


# --- snapshot of committed files (E3) ----------------------------------------

def _snapshot(pkt):
    """{relpath: (kind, data)} for every file the model must not touch."""
    snap = {}

    def add(rel):
        p = os.path.join(pkt.path, rel)
        if os.path.islink(p):
            snap[rel] = ("l", os.readlink(p))
        elif os.path.isdir(p):
            snap[rel] = ("d", None)
            for n in sorted(os.listdir(p)):
                add(os.path.join(rel, n))
        elif os.path.isfile(p):
            with open(p, "rb") as fp:
                snap[rel] = ("f", fp.read())

    for top in ("status.md", "memento.md", "journal.jsonl", "state", "children", "identity"):
        if os.path.lexists(os.path.join(pkt.path, top)):
            add(top)
    return snap


def _restore(pkt, snap):
    cur = _snapshot(pkt)
    for rel in sorted(set(cur) - set(snap), reverse=True):
        _rmtree(os.path.join(pkt.path, rel))
    for rel in sorted(snap):
        if cur.get(rel) == snap[rel]:
            continue
        p = os.path.join(pkt.path, rel)
        kind, data = snap[rel]
        if os.path.lexists(p) and (kind != "d" or not os.path.isdir(p)):
            _rmtree(p)
        if kind == "d":
            os.makedirs(p, exist_ok=True)
        elif kind == "l":
            os.symlink(data, p)
        else:
            with open(p, "wb") as fp:
                fp.write(data)


# --- the step folder -----------------------------------------------------------

def _tree_files(root):
    out = {}
    if not os.path.isdir(root):
        return out
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            if os.path.islink(p) or os.path.isfile(p):
                out[os.path.relpath(p, root)] = p
    return out


def state_diff(old, new):
    """``diff -ruN old new`` in pure Python, with ``state/`` paths."""
    a, b = _tree_files(old), _tree_files(new)
    out = []
    for rel in sorted(set(a) | set(b)):
        def lines(m):
            p = m.get(rel)
            if p is None:
                return []
            if os.path.islink(p):
                return ["-> %s\n" % os.readlink(p)]
            with open(p, "rb") as fp:
                data = fp.read()
            try:
                return data.decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError:
                return ["(binary, %d bytes)\n" % len(data)]
        la, lb = lines(a), lines(b)
        if la == lb:
            continue
        name = os.path.join("state", rel)
        for line in difflib.unified_diff(la, lb, "a/" + name, "b/" + name):
            out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


# --- commit ----------------------------------------------------------------------

def _apply(pkt, st, rec):
    """Steps 14-18 of the commit. Safe to redo after a crash at any point."""
    n, d = rec["step"], rec["decision"]
    meta, _ = pkt.load_status()
    pend_state = os.path.join(pkt.pending_dir, "state")
    source = pend_state if os.path.isdir(pend_state) else pkt.state_dir
    spawn.create_children(pkt, d["spawn"], source, meta["project"], d["model"], clock.now())

    if os.path.isdir(pend_state):
        if os.path.exists(pkt.state_dir) and os.path.exists(pkt.state_old_dir):
            shutil.rmtree(pkt.state_old_dir)
        if os.path.exists(pkt.state_dir):
            fsutil.rename(pkt.state_dir, pkt.state_old_dir)
        faults.point("after-state-swap-1")
        fsutil.rename(pend_state, pkt.state_dir)
    faults.point("after-state-swap-2")

    pend_memento = os.path.join(pkt.pending_dir, "memento.md")
    if os.path.exists(pend_memento):
        fsutil.rename(pend_memento, pkt.memento_path)
    faults.point("after-memento")

    meta, _ = pkt.load_status()
    if meta["step"] != n:
        kids = list(meta["children"])
        kids += [e["wpid"] for e in d["spawn"] if e["wpid"] not in kids]
        meta.update(state=d["state"], step=n, attempts=0, children=kids,
                    resume_expr=d["resume_expr"], wake_at=d["wake_at"], model=d["model"],
                    reason=d["reason"], updated=_ts())
        pkt.save_status(meta, d["summary"])
    faults.point("after-status")

    end = {"type": "commit-end", "t": _ts(), "step": n}
    try:
        with open(os.path.join(pkt.step_dir(n), "meta.json")) as fp:
            m = json.load(fp)
        for k in ("cost_usd", "tokens", "duration_s"):
            if m.get(k) is not None:
                end[k] = m[k]
    except (OSError, ValueError):
        pass
    journal.append(pkt.journal_path, end)
    faults.point("before-cleanup")
    _cleanup(pkt)


def _cleanup(pkt):
    _rmtree(pkt.state_old_dir)
    _rmtree(pkt.pending_dir)
    for n in os.listdir(pkt.path):
        if n.startswith(".tmp-"):        # an atomic_write cut short
            _rmtree(os.path.join(pkt.path, n))


# --- recovery --------------------------------------------------------------------

def _scan(records):
    """(unfinished commit-begin or None, unfinished step-start or None)."""
    begin, ended, start = None, set(), None
    for r in records:
        t = r.get("type")
        if t == "commit-begin":
            begin = r
        elif t == "commit-end":
            ended.add(r.get("step"))
            if start and start.get("step") == r.get("step"):
                start = None
        elif t == "step-start":
            start = r
        elif t == "step-failed":
            if start and (start.get("step"), start.get("attempt")) == \
                    (r.get("step"), r.get("attempt")):
                start = None
    if begin is not None and begin.get("step") in ended:
        begin = None
    return begin, start


def _move_failed(pkt, n, a):
    sd = pkt.step_dir(n)
    if os.path.isdir(sd):
        dst = pkt.step_dir(n, a)
        _rmtree(dst)
        fsutil.rename(sd, dst)


def _recover(pkt, st):
    """Finish or clean up a crashed step. Returns a message, or None if there was nothing."""
    begin, start = _scan(pkt.journal().records)
    if begin is not None:
        faults.at_step(begin["step"])
        _apply(pkt, st, begin)
        return "rolled forward the commit of step %d" % begin["step"]
    msg = None
    if start is not None:
        n, a = start["step"], start["attempt"]
        _move_failed(pkt, n, a)
        meta, body = pkt.load_status()
        if meta["step"] == n - 1 and meta["attempts"] < a:
            meta.update(attempts=a, updated=_ts())
            pkt.save_status(meta, body)
        journal.append(pkt.journal_path, {"type": "step-failed", "t": _ts(), "step": n,
                                          "attempt": a, "why": "attempt did not finish"})
        msg = "recorded step %d attempt %d as failed (it did not finish)" % (n, a)
    if os.path.lexists(pkt.pending_dir) or os.path.lexists(pkt.state_old_dir) or \
            any(n.startswith(".tmp-") for n in os.listdir(pkt.path)):
        _cleanup(pkt)
        msg = msg or "removed leftovers of an unfinished step"
    return msg


def _lease(pkt, st, n, a):
    lease = Lease(pkt.lease_path, n, a, st.step_timeout_s + LEASE_MARGIN_S)
    lease.acquire()
    if lease.broken is not None:
        b = lease.broken
        journal.append(pkt.journal_path, {
            "type": "note", "t": _ts(),
            "msg": "removed stale lease (host %s, pid %s, step %s, expires %s)" % (
                b.get("host"), b.get("pid"), b.get("step"), b.get("expires"))})
    return lease


def recover(target):
    try:
        pkt, st = _context(target)
        meta, _ = pkt.load_status()
    except (UsageError, OSError, frontmatter.FrontMatterError) as e:
        return Outcome(USAGE, str(e))
    try:
        lease = _lease(pkt, st, meta["step"] + 1, meta["attempts"] + 1)
    except LeaseHeld as e:
        return Outcome(LEASED, str(e))
    try:
        return Outcome(OK, _recover(pkt, st) or "nothing to recover")
    finally:
        lease.release()


# --- one step --------------------------------------------------------------------

def _set_failed(pkt, meta, body, reason):
    meta.update(state="FAILED", reason=reason, wake_at=None, updated=_ts())
    pkt.save_status(meta, body)


def _fail(pkt, st, n, a, why):
    """An attempt that did not commit: steps/NNNN.failed-<a>, attempts + 1."""
    _move_failed(pkt, n, a)
    meta, body = pkt.load_status()
    meta.update(attempts=a, updated=_ts())
    if a >= st.max_attempts:
        meta.update(state="FAILED", wake_at=None,
                    reason="%d failed attempts at step %d; last: %s" % (a, n, why))
    pkt.save_status(meta, body)
    journal.append(pkt.journal_path, {"type": "step-failed", "t": _ts(), "step": n,
                                      "attempt": a, "why": why})
    _rmtree(pkt.pending_dir)
    tail = "; packet is now FAILED" if a >= st.max_attempts else ""
    return Outcome(FAILED, "step %d attempt %d failed: %s%s" % (n, a, why, tail))


def _due(meta, now):
    if meta["state"] == "RUNNABLE":
        return True
    if meta["state"] == "SLEEPING" and meta.get("wake_at"):
        return schema.parse_timestamp(meta["wake_at"]) <= now
    return False


def _children(pkt, meta):
    out = []
    for w in meta.get("children") or ():
        try:
            m, b = Packet(os.path.join(os.path.dirname(pkt.path), w)).load_status()
        except (OSError, frontmatter.FrontMatterError):
            m, b = None, ""
        out.append((w, m, b))
    return out


def _validate_pending(pkt):
    """(memento meta, problem message or None)."""
    mpath = os.path.join(pkt.pending_dir, "memento.md")
    spath = os.path.join(pkt.pending_dir, "summary.md")
    if not os.path.isfile(mpath):
        return None, ".pending/memento.md was not written"
    try:
        mm, mbody = frontmatter.load(mpath)
    except (OSError, frontmatter.FrontMatterError) as e:
        return None, ".pending/memento.md: %s" % e
    probs = [p for p in schema.validate_memento(mm, mbody) if p.level == "error"]
    if probs:
        p = probs[0]
        return None, ".pending/memento.md: %s%s" % (p.field + ": " if p.field else "", p.msg)
    if not os.path.isfile(spath) or not fsutil.read_text(spath).strip():
        return None, ".pending/summary.md is missing or empty"
    if not os.path.isdir(os.path.join(pkt.pending_dir, "state")):
        return None, ".pending/state/ was removed"
    return mm, None


def step(target, force=False):
    try:
        pkt, st = _context(target)
        meta, body = pkt.load_status()
    except (UsageError, OSError, frontmatter.FrontMatterError) as e:
        return Outcome(USAGE, str(e))
    try:
        lease = _lease(pkt, st, meta["step"] + 1, meta["attempts"] + 1)
    except LeaseHeld as e:
        return Outcome(LEASED, str(e))
    try:
        rec = _recover(pkt, st)
        if rec and rec.startswith("rolled forward"):
            return Outcome(OK, rec)
        meta, body = pkt.load_status()
        n, a = meta["step"] + 1, meta["attempts"] + 1
        lease.refresh(n, a)
        faults.at_step(n)
        if meta["state"] in ("RUNNABLE", "SLEEPING") and meta["attempts"] >= st.max_attempts:
            _set_failed(pkt, meta, body, "%d failed attempts at step %d" % (meta["attempts"], n))
            return Outcome(NOT_RUNNABLE, "packet is FAILED after %d attempts" % meta["attempts"])
        now = clock.now()
        if not force and not _due(meta, now):
            when = " until %s" % meta["wake_at"] if meta["state"] == "SLEEPING" else ""
            return Outcome(NOT_RUNNABLE, "packet is %s%s" % (meta["state"], when))
        return _run(pkt, st, meta, body, n, a, lease, now)
    finally:
        lease.release()


def _run(pkt, st, meta, body, n, a, lease, now):
    tz = clock.zone(st.tz)
    # 4. Prepare.
    _rmtree(pkt.pending_dir)
    os.makedirs(pkt.pending_dir)
    shutil.copytree(pkt.state_dir, os.path.join(pkt.pending_dir, "state"), symlinks=True)
    sd = pkt.step_dir(n)
    _rmtree(sd)
    os.makedirs(sd)
    # 6. Prompt.
    _, instruction = pkt.load_memento()
    agent = fsutil.read_text(st.agent_md) if st.agent_md else None
    text = prompt.build(status=meta, last_summary=body, instruction=instruction, step=n,
                        attempt=a, max_attempts=st.max_attempts, now=now, tz=tz,
                        children=_children(pkt, meta), agent_md=agent)
    fsutil.atomic_write(os.path.join(sd, "prompt.md"), text)
    # 7. step-start, then 5. snapshot (so the journal line is part of it).
    session = str(uuid.uuid5(uuid.UUID(meta["wpid"]), "%d:%d" % (n, a)))
    journal.append(pkt.journal_path, {"type": "step-start", "t": _ts(now), "step": n,
                                      "attempt": a, "model": meta["model"],
                                      "session_id": session})
    snap = _snapshot(pkt)
    # 8. The model.
    add_dirs = []
    if os.path.isdir(pkt.identity_dir):
        for name in sorted(os.listdir(pkt.identity_dir)):
            t = os.path.realpath(os.path.join(pkt.identity_dir, name))
            if os.path.isdir(t):
                add_dirs.append(t)
    argv = model.command(meta["model"], session, st.permission_mode, st.allowed_tools,
                         st.step_budget_usd, add_dirs)
    env = dict(os.environ, WPK_WPID=meta["wpid"], WPK_STEP=str(n), WPK_ATTEMPT=str(a))
    lease.start_refresher()
    try:
        res = model.run(argv, text, pkt.path, env, st.step_timeout_s,
                        os.path.join(sd, "transcript.jsonl"), os.path.join(sd, "stderr.log"))
    finally:
        lease.stop_refresher()
    end = clock.now()
    faults.point("after-model")
    # 10. meta.json.
    fsutil.atomic_write(os.path.join(sd, "meta.json"), json.dumps({
        "step": n, "attempt": a, "start": _ts(now), "end": _ts(end), "model": meta["model"],
        "session_id": res.session_id or session, "exit_code": res.exit_code,
        "timed_out": res.timed_out, "is_error": res.is_error, "cost_usd": res.cost_usd,
        "tokens": res.tokens, "duration_s": res.duration_s}, indent=2) + "\n")
    # 9. Verify the snapshot.
    after = _snapshot(pkt)
    if after != snap:
        changed = sorted(k for k in set(snap) | set(after) if snap.get(k) != after.get(k))
        _restore(pkt, snap)
        return _fail(pkt, st, n, a,
                     "model wrote committed files: %s" % ", ".join(changed[:5]))
    why = res.failure()
    if why:
        return _fail(pkt, st, n, a, why)
    # 11. Validate.
    mm, why = _validate_pending(pkt)
    if why:
        return _fail(pkt, st, n, a, why)
    # 12. Resolve.
    try:
        state, wake = clock.resolve(mm["resume"], end, tz)
    except clock.ResumeError as e:
        return _fail(pkt, st, n, a, "resume: %s" % e)
    summary = fsutil.read_text(os.path.join(pkt.pending_dir, "summary.md"))
    pend_state = os.path.join(pkt.pending_dir, "state")
    fsutil.atomic_write(os.path.join(sd, "state.diff"), state_diff(pkt.state_dir, pend_state))
    shutil.copyfile(os.path.join(pkt.pending_dir, "memento.md"), os.path.join(sd, "result.md"))
    fsutil.atomic_write(os.path.join(sd, "summary.md"), summary)
    decision = {
        "state": state, "resume_expr": " ".join(mm["resume"].split()),
        "wake_at": _ts(wake) if wake else None,
        "reason": mm.get("reason") if state == "FAILED" else None,
        "model": meta["model"], "summary": summary,
        "spawn": spawn.decision_entries(meta["wpid"], n, mm.get("spawn")),
    }
    # 13-18. Commit.
    rec = {"type": "commit-begin", "t": _ts(end), "step": n, "decision": decision}
    journal.append(pkt.journal_path, rec)
    faults.point("after-commit-begin")
    _apply(pkt, st, rec)
    return Outcome(OK, "step %d committed: %s%s" % (
        n, state, " until %s" % decision["wake_at"] if wake else ""))
