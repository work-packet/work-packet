"""Every control of the pool, and the only code that writes its state
(docs/scheduler.md §6; plan §1). The CLI commands and the board's POSTs call
these and do nothing else. Each takes ``by``, the principal asking, checks it
with ``authz.check``, writes an event naming it, and returns an
``executor.Outcome``."""

import os

from .. import clock, layout, registry, schema
from ..executor import OK, NOT_RUNNABLE, USAGE, Outcome
from ..tomlio import load_toml, save_toml
from . import authz, classes, events, jobs
from . import config as sconfig


def control_path(h=None):
    return os.path.join(sconfig.sched_dir(h), "control.toml")


def read_mode(h=None, cfg=None):
    """``{"mode", "by", "at", "reason"}``. A missing ``control.toml`` is
    ``[sched] start_mode`` (default ``run``)."""
    p = control_path(h)
    try:
        d = load_toml(p)
        if d.get("mode") in schema.SCHED_MODES:
            return d
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return {"mode": "drain", "by": "wpkd", "reason": "%s is unreadable" % p}
    if cfg is None:
        try:
            cfg = sconfig.load(h)
        except registry.ConfigError:
            cfg = {}
    m = cfg.get("start_mode", "run")
    return {"mode": m, "by": "config", "reason": "start_mode" if m != "run" else None}


def _now():
    return schema.format_timestamp(clock.now())


def _refuse(by, action, target, h):
    try:
        authz.check(by, action, target, h)
    except authz.Denied as e:
        return Outcome(USAGE, "not allowed: %s" % e)
    return None


def set_mode(mode, by, reason=None, h=None, backend=None):
    """``run``, ``drain`` (Halt) or ``stop`` (Stop now). Stop also cancels every
    agent job; their next attempts are not counted (``lost`` markers)."""
    no = _refuse(by, "mode", None, h)
    if no:
        return no
    if mode not in schema.SCHED_MODES:
        return Outcome(USAGE, "mode must be one of %s" % ", ".join(schema.SCHED_MODES))
    if mode == "stop" and not (reason or "").strip():
        return Outcome(USAGE, "Stop now needs a reason (-m WHY)")
    old = read_mode(h).get("mode")
    d = {"mode": mode, "by": by, "at": _now()}
    if reason and reason.strip():
        d["reason"] = reason.strip()
    os.makedirs(sconfig.sched_dir(h), exist_ok=True)
    save_toml(control_path(h), d)
    cancelled = []
    if mode == "stop":
        cancelled = cancel_jobs(lambda r: r.kind == "step", by, "stopped: %s" % d["reason"],
                                h=h, backend=backend)
    events.append("mode", h=h, by=by, mode=mode, was=old, reason=d.get("reason"),
                  cancelled=len(cancelled) or None)
    msg = {"run": "pool running", "drain": "pool halted: running steps finish, "
           "nothing new starts", "stop": "pool stopped"}[mode]
    if cancelled:
        msg += "; cancelled %d job%s" % (len(cancelled), "" if len(cancelled) == 1 else "s")
    return Outcome(OK, msg)


def cancel_jobs(which, by, why, h=None, backend=None, lost=True):
    """Cancel the jobs ``which(record)`` picks. Running steps get SIGTERM (the
    dispatcher sends SIGKILL 30 s later); with ``lost`` their packets get a
    marker so the next attempt is not counted. Returns the records."""
    from .backends import get as get_backend
    out = []
    for r in jobs.all(h):
        if not which(r) or r.cancel:
            continue
        if backend is None:
            try:
                backend = get_backend(sconfig.load(h), h)
            except (registry.ConfigError, ValueError):
                return out
        if r.ref:
            try:
                backend.cancel(r.ref)
            except Exception:           # noqa: BLE001: the reaper tries again
                pass
        r.cancel, r.cancel_why = _now(), why
        jobs.save(r, h)
        if lost and r.kind == "step" and r.state == "RUNNING":
            jobs.mark_lost(r.wpid, why, by, r.cancel, r.step, h)
        events.append("cancelled", h=h, by=by, job=r.id, project=r.project, wpid=r.wpid,
                      why=why, state=r.state)
        out.append(r)
    return out


def cancel_pending(wpid, by, h=None, backend=None):
    """A packet was paused or taken: withdraw its job if it is still pending."""
    return cancel_jobs(lambda r: r.wpid == wpid and r.kind == "step" and r.state == "PENDING",
                       by, "packet no longer runnable", h=h, backend=backend, lost=False)


# --- projects and packets ----------------------------------------------------------

def _target(target, h):
    """(entry, wpid or None) for a project name or a packet (WPID prefix, path)."""
    e = registry.get(target, h)
    if e is not None:
        return e, None
    try:
        path = registry.resolve(target, h)
    except registry.LookupFailed as ex:
        raise LookupError(str(ex)) from None
    pdir = os.path.dirname(path)
    for e in registry.entries(h):
        if os.path.abspath(layout.runs_dir(e["path"])) == os.path.abspath(pdir):
            return e, os.path.basename(path)
    raise LookupError("%s is not in a registered project" % target)


def _update(name, fn, h):
    try:
        return registry.update(name, fn, h), None
    except (registry.ConfigError, registry.EntryBusy, registry.LookupFailed) as ex:
        return None, Outcome(USAGE, str(ex))


def _pkt_table(e, wpid):
    pk = e.setdefault("packets", {})
    return pk.setdefault(wpid, {})


def _prune(e, wpid):
    pk = e.get("packets") or {}
    if wpid in pk and not pk[wpid]:
        del pk[wpid]
    if "packets" in e and not e["packets"]:
        del e["packets"]


def hold(project, by, reason=None, h=None, on=True):
    """Hold a project: the scheduler starts nothing in it. Packets are untouched."""
    no = _refuse(by, "hold", project, h)
    if no:
        return no
    if registry.get(project, h) is None:
        return Outcome(USAGE, "no registered project named %r" % (project,))

    def change(e):
        was = e.get("sched", "run")
        if on:
            e.update(sched="hold", sched_by=by, sched_at=_now())
            if reason and reason.strip():
                e["sched_reason"] = reason.strip()
        else:
            for k in ("sched", "sched_by", "sched_at", "sched_reason"):
                e.pop(k, None)
        return was
    was, bad = _update(project, change, h)
    if bad:
        return bad
    now = "hold" if on else "run"
    if was == now:
        return Outcome(OK, "%s is already %s" % (project, "on hold" if on else "running"))
    events.append("hold", h=h, by=by, project=project, sched=now, reason=reason or None)
    return Outcome(OK, "%s %s" % (project, "on hold: nothing new starts there" if on
                                  else "released"))


def release(project, by, h=None):
    return hold(project, by, h=h, on=False)


def set_prio(target, cls, by, h=None):
    """Set (``cls``) or clear (None) the class of a project or one packet."""
    no = _refuse(by, "prio", target, h)
    if no:
        return no
    if cls is not None and cls not in classes.CLASSES:
        return Outcome(USAGE, "class must be one of %s" % ", ".join(classes.CLASSES))
    try:
        e, wpid = _target(target, h)
    except LookupError as ex:
        return Outcome(USAGE, str(ex))

    def change(e):
        t = e if wpid is None else _pkt_table(e, wpid)
        was = t.get("priority")
        if cls is None:
            t.pop("priority", None)
        else:
            t["priority"] = cls
        if wpid is not None:
            _prune(e, wpid)
        return was
    was, bad = _update(e["name"], change, h)
    if bad:
        return bad
    what = e["name"] if wpid is None else "%s %s" % (e["name"], wpid[:8])
    events.append("prio", h=h, by=by, project=e["name"], wpid=wpid, cls=cls, was=was)
    if cls is None:
        return Outcome(OK, "%s: priority cleared (%s)" % (
            what, "normal" if wpid is None else "the project's"))
    return Outcome(OK, "%s: priority %s" % (what, cls))


def set_size(target, size, by, h=None):
    """Set (``size``) or clear (None) the job size of a project or one packet."""
    no = _refuse(by, "size", target, h)
    if no:
        return no
    if size is not None:
        try:
            cfg = sconfig.load(h)
        except registry.ConfigError as ex:
            return Outcome(USAGE, str(ex))
        if sconfig.size(cfg, size) is None:
            return Outcome(USAGE, "no size %r in [sched.sizes]; there is %s" % (
                size, ", ".join(cfg.get("sizes") or {}) or "none"))
    try:
        e, wpid = _target(target, h)
    except LookupError as ex:
        return Outcome(USAGE, str(ex))

    def change(e):
        t = e if wpid is None else _pkt_table(e, wpid)
        was = t.get("size")
        if size is None:
            t.pop("size", None)
        else:
            t["size"] = size
        if wpid is not None:
            _prune(e, wpid)
        return was
    was, bad = _update(e["name"], change, h)
    if bad:
        return bad
    what = e["name"] if wpid is None else "%s %s" % (e["name"], wpid[:8])
    events.append("size", h=h, by=by, project=e["name"], wpid=wpid, size=size, was=was)
    return Outcome(OK, "%s: size %s" % (what, size or "cleared"))


def run_next(target, by, h=None, on=True):
    """Put a packet at the head of the line for its next step, once."""
    no = _refuse(by, "next", target, h)
    if no:
        return no
    try:
        e, wpid = _target(target, h)
    except LookupError as ex:
        return Outcome(USAGE, str(ex))
    if wpid is None:
        return Outcome(USAGE, "run next takes a packet, not a project")

    def change(e):
        t = _pkt_table(e, wpid)
        if on:
            t["next"] = True
        else:
            t.pop("next", None)
        _prune(e, wpid)
    _, bad = _update(e["name"], change, h)
    if bad:
        return bad
    events.append("next", h=h, by=by, project=e["name"], wpid=wpid, on=on)
    if not on:
        return Outcome(OK, "%s %s: run next cleared" % (e["name"], wpid[:8]))
    return Outcome(OK, "%s %s: runs next" % (e["name"], wpid[:8]))


def clear_next(project, wpid, h=None):
    """The dispatcher started it: the bump is used up. Not a control (no ``by``)."""
    def change(e):
        t = (e.get("packets") or {}).get(wpid)
        if t and t.pop("next", None) is not None:
            _prune(e, wpid)
    try:
        registry.update(project, change, h)
    except (registry.ConfigError, registry.EntryBusy, registry.LookupFailed):
        pass


__all__ = ["set_mode", "hold", "release", "set_prio", "set_size", "run_next",
           "cancel_pending", "read_mode", "NOT_RUNNABLE"]
