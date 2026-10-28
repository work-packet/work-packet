"""``wpk step`` and ``wpk recover``: one step of one packet (stage1-plan §4)."""

import dataclasses
import difflib
import functools
import json
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass

from . import (clock, faults, frontmatter, fsutil, harness, journal, model, notes, procs,
               profiles, prompt, questions, registry, report, schema, spawn, workspace)
from .lease import Lease, LeaseHeld
from .packet import Packet
from .project import ProjectError, project_of, settings

log = logging.getLogger("wpk")
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
    """A packet directory, project directory or name, or a unique WPID prefix."""
    try:
        return Packet(registry.resolve(target))
    except registry.LookupFailed as e:
        raise UsageError(str(e)) from None


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

    notes.consume(pkt, [x["id"] for x in d.get("notes") or ()])
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
        if d.get("size"):           # for the next step only (docs/scheduler.md §5.2)
            meta["next_size"] = d["size"]
        else:
            meta.pop("next_size", None)
        body = d["summary"]
        if d.get("report"):         # the outcome leads, so ps and the board show it
            body = "%s\n\n%s" % (d["report"]["outcome"], body)
        pkt.save_status(meta, body)
    if d.get("report"):
        shutil.copyfile(os.path.join(pkt.step_dir(n), report.NAME), pkt.report_path)
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


PENDING_KEPT = ("summary.md", "memento.md")


def _keep_pending(pkt, dst):
    if not os.path.isdir(dst):
        return
    for name in PENDING_KEPT:
        src = os.path.join(pkt.pending_dir, name)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(dst, "pending-" + name))


def _last_attempt(pkt, n):
    """The prompt's "Last attempt" section for step ``n``, or "" if it has not failed.
    Runs are numbered by folder, so a failure before a resume counts too."""
    runs = pkt.failed_runs(n)
    if not runs:
        return ""
    whys = {k: "it did not finish" for k in runs}
    for r in journal.read(pkt.journal_path).records:
        k = r.get("run", r.get("attempt"))
        if r.get("type") == "step-failed" and r.get("step") == n and k in whys:
            whys[k] = r.get("why") or whys[k]
    last = runs[-1]
    d = pkt.step_dir(n, last)
    pending = []
    for name in PENDING_KEPT:
        text = fsutil.read_text(os.path.join(d, "pending-" + name)) if os.path.isfile(
            os.path.join(d, "pending-" + name)) else None
        if text and text.strip():
            pending.append((name, text))
    folders = [os.path.relpath(pkt.step_dir(n, k), pkt.path) for k in runs]
    return prompt.last_attempt_section(last, whys[last], os.path.join(d, "transcript.jsonl"),
                                       root=pkt.path, pending=pending,
                                       earlier=[(k, whys[k]) for k in runs[:-1]],
                                       folders=folders)


def _move_failed(pkt, n):
    """Move step ``n``'s folder to ``NNNN.failed-<run>``; returns the run."""
    r = pkt.next_run(n)
    sd = pkt.step_dir(n)
    if os.path.isdir(sd):
        fsutil.rename(sd, pkt.step_dir(n, r))
    return r


def _recover(pkt, st, lost=None):
    """Finish or clean up a crashed step. Returns a message, or None if there was nothing.

    ``lost``: the scheduler ended that attempt (Stop now, or the farm took the
    slot): it is recorded with ``counted: false`` and does not raise
    ``attempts`` (docs/scheduler-plan.md decision 3)."""
    begin, start = _scan(pkt.journal().records)
    if begin is not None:
        faults.at_step(begin["step"])
        _apply(pkt, st, begin)
        return "rolled forward the commit of step %d" % begin["step"]
    msg = None
    if start is not None:
        n, a = start["step"], start["attempt"]
        r = _move_failed(pkt, n)
        _keep_pending(pkt, pkt.step_dir(n, r))
        meta, body = pkt.load_status()
        if not lost and meta["step"] == n - 1 and meta["attempts"] < a:
            meta.update(attempts=a, updated=_ts())
            pkt.save_status(meta, body)
        rec = {"type": "step-failed", "t": _ts(), "step": n, "attempt": a, "run": r,
               "why": "attempt did not finish"}
        if lost:
            rec.update(why="attempt did not finish: %s" % lost, counted=False)
        journal.append(pkt.journal_path, rec)
        msg = "recorded step %d attempt %d as failed (it did not finish)" % (n, a)
        if lost:
            msg = "recorded step %d attempt %d as lost, not counted (%s)" % (n, a, lost)
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
    """An attempt that did not commit: steps/NNNN.failed-<run>, attempts + 1.
    The ``.pending/`` files it left are kept there for the retry's prompt."""
    r = _move_failed(pkt, n)
    _keep_pending(pkt, pkt.step_dir(n, r))
    meta, body = pkt.load_status()
    meta.update(attempts=a, updated=_ts())
    if a >= st.max_attempts:
        meta.update(state="FAILED", wake_at=None,
                    reason="%d failed attempts at step %d; last: %s" % (a, n, why))
    pkt.save_status(meta, body)
    journal.append(pkt.journal_path, {"type": "step-failed", "t": _ts(), "step": n,
                                      "attempt": a, "run": r, "why": why})
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


_OPEN_ITEM = re.compile(r"^\s*[-*]\s+\[([ >+])\]\s*(\S+)")


def _open_items(path):
    """The open items of an outline (``[ ]``, ``[>]``, ``[+]``): the first word of
    each, at most five, then ``...``. Empty when there is no outline."""
    try:
        text = fsutil.read_text(path)
    except OSError:
        return []
    left = [m.group(2).rstrip(".:") for m in map(_OPEN_ITEM.match, text.splitlines()) if m]
    return left[:5] + (["..."] if len(left) > 5 else [])


def _requests_section(pkt):
    """The step prompt's "Requests" (docs/delegation.md §5); "" if it can't be read."""
    from . import requests
    try:
        return requests.section(pkt.wpid)
    except (OSError, KeyError, TypeError):
        return ""


def _validate_pending(pkt, st=None):
    """(memento meta, problem message or None). ``st``: the project's settings,
    for the sizes its steps may ask for."""
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
    if mm.get("size") is not None and st is not None:
        sizes = allowed_sizes(st)
        if mm["size"] not in sizes:
            return None, ".pending/memento.md: size: %r is not one of this project's " \
                "sizes: %s" % (mm["size"], ", ".join(sizes) or "none")
    if not os.path.isfile(spath) or not fsutil.read_text(spath).strip():
        return None, ".pending/summary.md is missing or empty"
    if not os.path.isdir(os.path.join(pkt.pending_dir, "state")):
        return None, ".pending/state/ was removed"
    from . import requests              # it imports this module
    for q in questions.normalise(mm.get("ask")):
        if q.get("request"):
            try:
                requests.load_brief(os.path.join(pkt.pending_dir, "state"), q["request"])
            except requests.RequestError as e:
                return None, ".pending/memento.md: ask %s: %s" % (q["id"], e)
    kind = clock.parse_resume(mm["resume"]).kind
    if kind == "done":
        left = _open_items(os.path.join(pkt.pending_dir, "state", "outline.md"))
        if left:
            return None, "resume: done, but state/outline.md has open items: %s. " \
                "Use ask: if the next one needs the owner, resume: now if work can " \
                "go on, or mark them [-] with a reason" % ", ".join(left)
    if kind in ("done", "fail"):
        rpath = os.path.join(pkt.pending_dir, report.NAME)
        if not os.path.isfile(rpath):
            return None, ".pending/report.md was not written (it is required with " \
                "resume: %s)" % kind
        try:
            rm, rbody = frontmatter.load(rpath)
        except (OSError, frontmatter.FrontMatterError) as e:
            return None, ".pending/report.md: %s" % e
        probs = report.validate(rm, rbody, pkt.path, os.path.join(pkt.pending_dir, "state"))
        if probs:
            return None, ".pending/report.md: %s" % probs[0]
    return mm, None


def _carry_from(pkt, st, meta, n, a, now, limit, factor, asked=False):
    """The previous step's ``meta.json`` if this step should resume its session,
    or None to start fresh (context.md C4). ``asked``: a next-batch hand-off asked
    for it (dash-tasks.md §6.5), which skips the setting, the state and the
    cache checks; the model, harness and context limit still apply."""
    if a != 1 or n < 2 or not harness.get(st.harness).caps.resume:
        return None
    if not asked and (not st.carry_session or meta["state"] != "RUNNABLE"
                      or meta.get("resume_expr") != "now"):
        return None
    try:
        with open(os.path.join(pkt.step_dir(n - 1), "meta.json"), encoding="utf-8") as fp:
            prev = json.load(fp)
        end = schema.parse_timestamp(prev["end"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if prev.get("model") != meta["model"] or not prev.get("session_id") or \
            prev.get("harness", "claude") != st.harness:
        return None
    ctx = prev.get("context") or {}
    peak, base = ctx.get("peak"), ctx.get("base")
    if not asked:
        if (now - end).total_seconds() > st.carry_ttl_s:
            return None
        if peak is None or base is None or peak >= factor * base:
            return None
    if limit > 0 and peak is not None and peak >= limit:
        return None
    return prev


def _context_meta(res, prev):
    """``meta.json``'s ``context``. ``base`` is the first call of the chain's fresh
    session, about its orientation cost O; carry-over stops at a multiple of it."""
    c = model.context_summary(res.context)
    if c is not None:
        c["base"] = (prev.get("context") or {}).get("base") if prev else c["first"]
        c["cache_breaks"], c["cache_rewrite"] = res.cache_breaks, res.cache_rewrite
    return c


def _step_cost(res, prev, chain_total=True):
    """This step's cost. Some harnesses (``Caps.cost_is_chain_total``) report the
    cost of the whole chain for a resumed session."""
    if res.cost_usd is None or prev is None or not chain_total:
        return res.cost_usd
    before = prev.get("session_cost_usd", prev.get("cost_usd")) or 0.0
    return round(max(0.0, res.cost_usd - before), 6)


def step(target, force=False, lost=None):
    """One step. ``lost``: why the scheduler ended this packet's last attempt;
    if that attempt is unfinished it is not counted (``wpk step --lost``)."""
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
        rec = _recover(pkt, st, lost)
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
            if meta["state"] == "NEEDS_INPUT":
                when = " (%s); answer with `wpk handoff -m`" % meta.get("reason")
            return Outcome(NOT_RUNNABLE, "packet is %s%s" % (meta["state"], when))
        try:
            prof = profiles.select(st.profiles, st.harness, meta["model"], st.profile)
        except profiles.ProfileError as e:
            return Outcome(USAGE, str(e))
        return _run(pkt, st, meta, body, n, a, lease, now, prof)
    finally:
        lease.release()
        _ide_owner(pkt)


NUDGE = ("wpk: your turn ended, but the step is not finished: %s. Nothing you "
         "started in the background is still running for you, and its result "
         "will not arrive. Check what it left (its output file, `git status`), "
         "then write `.pending/summary.md` and `.pending/memento.md` now (and, with "
         "resume: done or fail, `.pending/report.md`, as the protocol says). If the "
         "work is not done, say so in the summary and give the exact next action "
         "in the memento, with `resume: now`.")
NUDGE_WAIT_S = 600          # wait this long for processes the first run left
NUDGE_TIMEOUT_MIN = 300     # the nudge always gets at least this long
NUDGE_BUDGET_MIN = 0.25     # ... and this much budget
TIME_WARN = 0.7             # ctxhook warns when this much of step_timeout has gone


def _model(pkt, st, h, spec, env, sd, lease, text, timeout_s, append=False):
    lease.start_refresher()
    try:
        return model.run(h.command(spec), text, pkt.path, env, timeout_s,
                         os.path.join(sd, "transcript.jsonl"), os.path.join(sd, "stderr.log"),
                         h.parse, pid_path=os.path.join(sd, "model.pid"), append=append)
    finally:
        lease.stop_refresher()


def _meta(n, a, now, end, h, prof, meta, session, carried, res, prev):
    return {
        "step": n, "attempt": a, "start": _ts(now), "end": _ts(end), "harness": h.name,
        "profile": prof.id, "model": meta["model"],
        "session_id": res.session_id or session, "carried_from": carried,
        "exit_code": res.exit_code,
        "timed_out": res.timed_out, "is_error": res.is_error,
        "cost_usd": _step_cost(res, prev, h.caps.cost_is_chain_total),
        "session_cost_usd": res.cost_usd,
        "tokens": res.tokens, "context": _context_meta(res, prev),
        "duration_s": res.duration_s, "api_s": res.api_s, "quota": res.quota or None}


def allowed_sizes(st):
    """The job sizes a step of this project may ask for (docs/scheduler.md §5.2)."""
    from .sched import config as sconfig
    try:
        cfg = sconfig.load()
    except registry.ConfigError:
        return []
    return sconfig.allowed_sizes(cfg, st.sizes)


def _size_list(st):
    from .sched import config as sconfig
    try:
        cfg = sconfig.load()
    except registry.ConfigError:
        return []
    return [sconfig.size(cfg, n) for n in sconfig.allowed_sizes(cfg, st.sizes)]


def _check(pkt, st, snap, res):
    """(why the attempt cannot commit or None, the memento's meta)."""
    after = _snapshot(pkt)
    if after != snap:
        changed = sorted(k for k in set(snap) | set(after) if snap.get(k) != after.get(k))
        _restore(pkt, snap)
        return "model wrote committed files: %s" % ", ".join(changed[:5]), None
    why = res.failure()
    if why:
        return why, None
    mm, why = _validate_pending(pkt, st)
    return why, mm


def _nudgeable(h, res, why):
    """The model ended its turn cleanly but left ``.pending/`` incomplete."""
    return (h.caps.resume and res.session_id is not None and res.failure() is None
            and why.startswith(".pending/"))


def _wait_for_leftovers(wpid, n, limit_s):
    """Let processes the step started (and left running) finish, up to ``limit_s``."""
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        found = procs.of_step(None, wpid, n)
        if not found or not found["count"]:
            return
        time.sleep(5)


def _run(pkt, st, meta, body, n, a, lease, now, prof):
    tz = clock.zone(st.tz)
    limit = profiles.value(st, prof, "step_context_tokens")
    factor = profiles.value(st, prof, "carry_factor")
    # 4. Prepare. The root is filled from the project root first (docs/setup.md §10).
    if pkt.wpid == st.root:
        try:
            workspace.prepare(pkt, st.project_dir, st.name, st.setup, first=meta["step"] == 0)
        except workspace.WorkspaceError as e:
            sd = pkt.step_dir(n)
            _rmtree(sd)
            os.makedirs(sd)
            fsutil.atomic_write(os.path.join(sd, "stderr.log"), "workspace: %s\n" % e)
            return _fail(pkt, st, n, a, "workspace: %s" % e)
    _rmtree(pkt.pending_dir)
    os.makedirs(pkt.pending_dir)
    shutil.copytree(pkt.state_dir, os.path.join(pkt.pending_dir, "state"), symlinks=True)
    sd = pkt.step_dir(n)
    _rmtree(sd)
    os.makedirs(sd)
    # 6. Prompt.
    _, instruction = pkt.load_memento()
    queued = notes.queued(pkt)
    if queued:
        notes.mark(sd, queued, "prompt", _ts(now))
    agent = fsutil.read_text(st.agent_md) if st.agent_md else None
    handoffs = journal.handoffs_since_commit(journal.read(pkt.journal_path).records)
    text = prompt.build(status=meta, last_summary=body, instruction=instruction, step=n,
                        attempt=a, max_attempts=st.max_attempts, now=now, tz=tz,
                        children=_children(pkt, meta), agent_md=agent,
                        state_dir=pkt.state_dir,
                        handoffs=handoffs,
                        last_attempt=_last_attempt(pkt, n), notes=queued,
                        sizes=_size_list(st), requests=_requests_section(pkt))
    fsutil.atomic_write(os.path.join(sd, "prompt.md"), text)
    # 7. step-start, then 5. snapshot (so the journal line is part of it).
    run_no = pkt.next_run(n)     # not the attempt: that restarts at 1 on a resume
    session = str(uuid.uuid5(uuid.UUID(meta["wpid"]), "%d:%d" % (n, run_no)))
    prev = _carry_from(pkt, st, meta, n, a, now, limit, factor,
                       asked=any(r.get("carry_session") for r in handoffs))
    carried = prev["session_id"] if prev else None
    start = {"type": "step-start", "t": _ts(now), "step": n, "attempt": a,
             "model": meta["model"], "session_id": session}
    if carried:
        start["carried_from"] = carried
    journal.append(pkt.journal_path, start)
    snap = _snapshot(pkt)
    # 8. The model.
    add_dirs = []
    if os.path.isdir(pkt.identity_dir):
        for name in sorted(os.listdir(pkt.identity_dir)):
            t = os.path.realpath(os.path.join(pkt.identity_dir, name))
            if os.path.isdir(t):
                add_dirs.append(t)
    add_dirs += [d for d in workspace.linked_dirs(pkt) if d not in add_dirs]
    h = harness.get(st.harness)
    system = os.path.join(sd, "system.md")
    system_text = prompt.system(tz, h.name, prof.sizing)
    fsutil.atomic_write(system, system_text)
    if not h.caps.system_slot:      # no system prompt slot: the protocol leads the prompt
        text = system_text + "\n\n" + text
        fsutil.atomic_write(os.path.join(sd, "prompt.md"), text)
    spec = harness.StepSpec(
        model=meta["model"], session_id=session, permission_mode=st.permission_mode,
        allowed_tools=st.allowed_tools, budget_usd=st.step_budget_usd, add_dirs=add_dirs,
        system_file=system if h.caps.system_slot else None,
        context_limit=limit if h.caps.inject else 0,
        marker=os.path.join(sd, "ctxhook.fired"), resume_from=carried,
        notes=(notes.inbox(pkt), os.path.join(sd, notes.SEEN)) if h.caps.inject else None)
    env = dict(os.environ, WPK_WPID=meta["wpid"], WPK_STEP=str(n), WPK_ATTEMPT=str(a))
    t0 = time.time()        # for ctxhook's time warning; the timeout is wall-clock too
    env.update(WPK_STARTED_AT="%.0f" % t0, WPK_DEADLINE="%.0f" % (t0 + st.step_timeout_s),
               WPK_WARN_AT="%.0f" % (t0 + TIME_WARN * st.step_timeout_s))
    env.update(h.env(spec))
    run = functools.partial(_model, pkt, st, h, spec, env, sd, lease)
    res = run(text, st.step_timeout_s)
    end = clock.now()
    faults.point("after-model")
    meta_out = _meta(n, a, now, end, h, prof, meta, session, carried, res, prev)
    fsutil.atomic_write(os.path.join(sd, "meta.json"), json.dumps(meta_out, indent=2) + "\n")
    why, mm = _check(pkt, st, snap, res)
    if why is not None and _nudgeable(h, res, why):
        # One more turn in the same session: the work is all in its context,
        # only the two files are missing (docs/experiments/dvs-enh-steps.md).
        journal.append(pkt.journal_path, {"type": "step-nudge", "t": _ts(), "step": n,
                                          "attempt": a, "why": why})
        snap = _snapshot(pkt)       # the journal line is part of it, as at step-start
        lease.start_refresher()
        try:
            _wait_for_leftovers(meta["wpid"], n, NUDGE_WAIT_S)
        finally:
            lease.stop_refresher()
        first = res
        nspec = dataclasses.replace(spec, resume_from=res.session_id, session_id=str(
            uuid.uuid5(uuid.UUID(meta["wpid"]), "%d:%d:nudge" % (n, run_no))),
            budget_usd=max(spec.budget_usd - (res.cost_usd or 0.0), NUDGE_BUDGET_MIN))
        run = functools.partial(_model, pkt, st, h, nspec, env, sd, lease)
        res = run(NUDGE % why, max(st.step_timeout_s - res.duration_s, NUDGE_TIMEOUT_MIN),
                  append=True)
        if not h.caps.cost_is_chain_total and None not in (res.cost_usd, first.cost_usd):
            res.cost_usd += first.cost_usd
        res.duration_s = round(first.duration_s + res.duration_s, 3)
        end = clock.now()
        meta_out = _meta(n, a, now, end, h, prof, meta, session, carried, res, prev)
        meta_out["nudged"] = why
        fsutil.atomic_write(os.path.join(sd, "meta.json"), json.dumps(meta_out, indent=2) + "\n")
        why, mm = _check(pkt, st, snap, res)
    if why is not None:
        return _fail(pkt, st, n, a, why)
    # 12. Resolve.
    try:
        state, wake = clock.resolve(mm["resume"], end, tz)
    except clock.ResumeError as e:
        return _fail(pkt, st, n, a, "resume: %s" % e)
    asked = questions.normalise(mm.get("ask"))
    ask = questions.summary(asked) if asked else None
    if ask:                         # the questions wait for a hand-off; resume is the record
        state, wake = "NEEDS_INPUT", None
    summary = fsutil.read_text(os.path.join(pkt.pending_dir, "summary.md"))
    pend_state = os.path.join(pkt.pending_dir, "state")
    fsutil.atomic_write(os.path.join(sd, "state.diff"), state_diff(pkt.state_dir, pend_state))
    shutil.copyfile(os.path.join(pkt.pending_dir, "memento.md"), os.path.join(sd, "result.md"))
    fsutil.atomic_write(os.path.join(sd, "summary.md"), summary)
    hd = workspace.heads(pkt)
    rep = None
    if state in ("COMPLETED", "FAILED") and not ask:
        rm, rbody = frontmatter.load(os.path.join(pkt.pending_dir, report.NAME))
        rep = report.stamp(rm, hd)
        fsutil.atomic_write(os.path.join(sd, report.NAME), frontmatter.dump(rep, rbody))
        report.snapshot(rep, pkt.path, pend_state, sd)
    decision = {
        "state": state, "resume_expr": " ".join(mm["resume"].split()),
        "wake_at": _ts(wake) if wake else None,
        "reason": ask if ask else mm.get("reason") if state == "FAILED" else None,
        "model": meta["model"], "summary": summary,
        "spawn": spawn.decision_entries(meta["wpid"], n, mm.get("spawn")),
    }
    if mm.get("size"):
        decision["size"] = mm["size"]
    seen = notes.committed(sd, pkt)
    if seen:
        decision["notes"] = seen
    if rep is not None:
        decision["report"] = {"outcome": rep["outcome"].strip(),
                              "deliverables": [d["path"] for d in rep["deliverables"]]}
    if hd:
        decision["heads"] = hd
    # 13-18. Commit.
    rec = {"type": "commit-begin", "t": _ts(end), "step": n, "decision": decision}
    journal.append(pkt.journal_path, rec)
    faults.point("after-commit-begin")
    _apply(pkt, st, rec)
    return Outcome(OK, "step %d committed: %s%s%s" % (
        n, state, " until %s" % decision["wake_at"] if wake else "",
        ": %s" % ask if ask else ""))


# --- pause and resume ------------------------------------------------------------

def _who():
    import getpass
    import socket
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "unknown"
    return "%s@%s" % (user, socket.gethostname())


CONTINUE_FROM = ("COMPLETED", "NEEDS_INPUT", "PAUSED", "FAILED")


def last_heads(records):
    """The work repo heads the last committed step recorded (``decision.heads``)."""
    for r in reversed(records):
        if r.get("type") == "commit-begin":
            return (r.get("decision") or {}).get("heads") or {}
    return {}


def batch_of(records):
    """The batch the packet is on: 1, plus one for each next-batch hand-off."""
    return 1 + sum(1 for r in records if r.get("type") == "handoff" and "instruction" in r)


def _archive_outline(pkt, batch):
    """``state/outline.md`` to ``state/history/outline-<batch>.md``; the new path or None."""
    src = os.path.join(pkt.state_dir, "outline.md")
    if not os.path.isfile(src):
        return None
    rel = os.path.join("history", "outline-%d.md" % batch)
    dst = os.path.join(pkt.state_dir, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    n = 1
    while os.path.exists(dst):           # a retried hand-off, or a hand-made file
        n += 1
        rel = os.path.join("history", "outline-%d.%d.md" % (batch, n))
        dst = os.path.join(pkt.state_dir, rel)
    os.rename(src, dst)
    return "state/" + rel


def _archive_report(pkt, batch):
    """``report.md`` to ``state/history/report-<batch>.md``; the new path or None."""
    if not os.path.isfile(pkt.report_path):
        return None
    rel = os.path.join("history", "report-%d.md" % batch)
    dst = os.path.join(pkt.state_dir, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    n = 1
    while os.path.exists(dst):
        n += 1
        rel = os.path.join("history", "report-%d.%d.md" % (batch, n))
        dst = os.path.join(pkt.state_dir, rel)
    os.rename(pkt.report_path, dst)
    return "state/" + rel


def admin(pkt, op, note=None, answers=None, by=None, instruction=None,
          archive_outline=None, carry_session=False, force=False, reason=None):
    """``pause``: RUNNABLE or SLEEPING to PAUSED. ``wake``: SLEEPING to RUNNABLE
    (a note that should not wait, docs/interaction.md §6a). ``resume``: NEEDS_INPUT, PAUSED or
    FAILED to RUNNABLE. ``handoff``: the same as ``resume``, with an optional note
    for the next step (long-running.md §1); it records a ``handoff`` line, which
    the step prompt shows, instead of an ``admin`` line. ``answers`` maps question
    ids to text (docs/interaction.md §3).

    ``continue``: the next batch of work (docs/dash-tasks.md §6). From
    ``COMPLETED`` too; ``instruction`` replaces the memento, the outline is
    archived (``archive_outline``, default: only from ``COMPLETED``), and the
    ``handoff`` record gets ``instruction`` and ``batch``. Work repos with
    uncommitted changes refuse it unless ``force``. ``carry_session``: the
    next step resumes the last step's session (§6.5). ``reason``: the pause's
    reason in ``status.md`` (default "by hand"; the scheduler's caps name theirs).

    Takes the lease, so it never races a running step.
    """
    try:
        meta, body = pkt.load_status()
    except (OSError, frontmatter.FrontMatterError) as e:
        return Outcome(USAGE, str(e))
    try:
        lease = Lease(pkt.lease_path, meta["step"] + 1, 0, 60).acquire()
    except LeaseHeld as e:
        return Outcome(LEASED, str(e))
    try:
        meta, body = pkt.load_status()
        old = meta["state"]
        if op == "pause":
            if old not in ("RUNNABLE", "SLEEPING"):
                return Outcome(NOT_RUNNABLE, "%s is %s; nothing to pause" % (pkt.wpid[:8], old))
            meta.update(state="PAUSED", reason=reason or "by hand", wake_at=None)
        elif op == "wake":
            if old != "SLEEPING":
                return Outcome(NOT_RUNNABLE, "%s is %s; nothing to wake" % (pkt.wpid[:8], old))
            meta.update(state="RUNNABLE", wake_at=None)
        elif op in ("resume", "handoff", "continue"):
            allowed = CONTINUE_FROM if op == "continue" else ("NEEDS_INPUT", "PAUSED", "FAILED")
            if old not in allowed:
                return Outcome(NOT_RUNNABLE, "%s is %s; nothing to %s" % (pkt.wpid[:8], old, op))
            asked = meta.get("reason") if old == "NEEDS_INPUT" else None
            qs = questions.of_packet(pkt) if old == "NEEDS_INPUT" else []
            records = journal.read(pkt.journal_path).records
            extra = {}
            if op == "continue":
                text = (instruction or "").strip()
                if not text:
                    return Outcome(USAGE, "the next batch needs an instruction")
                if text.startswith("---"):
                    return Outcome(USAGE, "write the instruction without front matter")
                dirt = workspace.dirty(pkt)
                if dirt and not force:
                    return Outcome(USAGE, "uncommitted changes in %s: commit or stash them "
                                   "first, so the next step starts from a clean tree" % ", ".join(
                                       "work/%s (%d)" % (n, len(v)) for n, v in dirt.items()))
                batch = batch_of(records) + 1
                if archive_outline is None:
                    archive_outline = old == "COMPLETED"
                moved = _archive_outline(pkt, batch - 1) if archive_outline else None
                fsutil.atomic_write(pkt.memento_path, text + "\n")
                extra = {"batch": batch, "instruction": text}
                if moved:
                    extra["outline"] = moved
                if carry_session:
                    extra["carry_session"] = True
            rmoved = _archive_report(pkt, batch_of(records)) if old in (
                "COMPLETED", "FAILED") else None   # it no longer says where things stand
            if rmoved:
                extra["report"] = rmoved
            meta.update(state="RUNNABLE", reason=None, wake_at=None, attempts=0)
        else:
            raise ValueError(op)
        meta["updated"] = _ts()
        pkt.save_status(meta, body)
        if op in ("handoff", "continue"):
            rec = {"type": "handoff", "t": _ts(), "by": by or _who(), "from": old,
                   "to": meta["state"]}
            rec.update(extra)
            hd = workspace.heads(pkt)
            if hd:
                rec["heads"] = hd
                since = workspace.commits_since(pkt, last_heads(records))
                if since:
                    rec["commits"] = since
            if asked:
                rec["asked"] = asked
            if qs:
                rec["questions"] = qs
            if answers:
                rec["answers"] = dict(answers)
            if note and note.strip():
                rec["note"] = note.strip()
        else:
            rec = {"type": "admin", "t": _ts(), "op": op, "by": by or _who(),
                   "from": old, "to": meta["state"]}
        journal.append(pkt.journal_path, rec)
        return Outcome(OK, "%s: %s -> %s" % (pkt.wpid[:8], old, meta["state"]))
    finally:
        lease.release()
        _ide_owner(pkt)


def _ide_owner(pkt):
    """Read-only in VS Code while the runner owns the packet (docs/vscode-plan.md
    §5). Only a packet someone opened has a workspace file; never fails a step."""
    from . import ide
    try:
        ide.set_owner(pkt)
    except Exception as e:          # noqa: BLE001: the editor's file is not the packet
        log.warning("%s: VS Code workspace not updated: %s", pkt.wpid[:8], e)
