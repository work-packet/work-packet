"""What can hold a due packet back (docs/scheduler.md §6.2). Each gate returns a
``Reason`` or None; the first that fails is what the queue view shows."""

from dataclasses import dataclass, field
from typing import Optional

from .. import schema
from .config import fmt_mem


@dataclass
class Reason:
    code: str
    text: str
    clears_at: Optional[str] = None


@dataclass
class Usage:
    """What the pool's jobs hold, pending ones included."""
    cores: int = 0
    mem_mb: int = 0
    jobs: int = 0
    by_project: dict = field(default_factory=dict)      # project -> cores
    by_size: dict = field(default_factory=dict)         # size -> jobs
    by_kind: dict = field(default_factory=dict)         # step | ide -> jobs
    wpids: dict = field(default_factory=dict)           # wpid -> JobRecord

    def add(self, project, cpus, mem_mb, size="?", kind="step", wpid=None, rec=None):
        self.cores += cpus
        self.mem_mb += mem_mb
        self.jobs += 1
        self.by_project[project] = self.by_project.get(project, 0) + cpus
        self.by_size[size] = self.by_size.get(size, 0) + 1
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1
        if wpid:
            self.wpids[wpid] = rec

    def add_item(self, it):
        self.add(it.project, it.size.cpus, it.size.mem_mb, it.size.name, "step", it.wpid, it)

    def project_cores(self, name):
        return self.by_project.get(name, 0)

    @classmethod
    def of(cls, records):
        u = cls()
        for r in records:
            u.add(r.project, r.cpus, r.mem_mb, r.size, r.kind, r.wpid if r.kind == "step"
                  else None, r)
        return u


@dataclass
class Ctx:
    cfg: dict
    now: object
    mode: dict                       # control.read_mode()
    limits: object                   # config.Limits
    usage: Usage
    projs: dict                      # queue.Project by name
    backfill_for_s: float = 600
    spare: object = None             # config.Size kept free by background work
    blocker: object = None           # the first item that waits for room
    budget: object = None            # budget.Budget, when [sched.budget] is set
    ledger: object = None            # budget.ledger(): every step's spend
    reserve: object = None           # config.Size: IDE room agents never use ([sched.ide] reserve)
    ide_waiting: list = field(default_factory=list)   # IDE requests with no room yet


def _free_after(ctx, cpus, mem_mb):
    """Would one more job of ``cpus``/``mem_mb`` fit under every pool limit?"""
    lim, u = ctx.limits, ctx.usage
    if lim.cores and u.cores + cpus > lim.cores:
        return "cores"
    if lim.mem_mb and mem_mb and u.mem_mb + mem_mb > lim.mem_mb:
        return "mem"
    if lim.jobs and u.jobs + 1 > lim.jobs:
        return "jobs"
    return None


def mode(it, ctx):
    m = ctx.mode
    if m.get("mode", "run") == "run":
        return None
    what = "halted" if m["mode"] == "drain" else "stopped"
    by = " by %s" % m["by"] if m.get("by") else ""
    at = " at %s" % m["at"] if m.get("at") else ""
    why = ": %s" % m["reason"] if m.get("reason") else ""
    return Reason("mode", "pool %s%s%s%s" % (what, by, at, why))


def project_hold(it, ctx):
    p = ctx.projs.get(it.project)
    if p is None or not p.hold:
        return None
    by = " by %s" % p.entry["sched_by"] if p.entry.get("sched_by") else ""
    at = " at %s" % p.entry["sched_at"] if p.entry.get("sched_at") else ""
    return Reason("hold", "project on hold%s%s" % (by, at))


def project_broken(it, ctx):
    p = ctx.projs.get(it.project)
    if p is not None and p.problem:
        return Reason("project", p.problem)
    return None


def job_pending(it, ctx):
    rec = ctx.usage.wpids.get(it.wpid)
    if rec is None:
        return None
    if getattr(rec, "state", None) == "RUNNING":
        return Reason("job", "a job is running for it (%s)" % rec.id)
    return Reason("job", "its job %s is waiting in the batch queue" % getattr(rec, "id", "?"))


def project_cores(it, ctx):
    p = ctx.projs.get(it.project)
    if p is None or not p.max_cores:
        return None
    used = ctx.usage.project_cores(it.project)
    if used + it.size.cpus > p.max_cores:
        return Reason("project_cores", "project uses %d of its %d cores; %s needs %d"
                      % (used, p.max_cores, it.size.name, it.size.cpus))
    return None


def budget(it, ctx):
    if ctx.budget is None:
        return None
    return ctx.budget.gate(it, ctx)


def too_big(it, ctx):
    lim, s = ctx.limits, it.size
    if lim.cores and s.cpus > lim.cores:
        return Reason("too_big", "size %s needs %d cores; the pool has %d"
                      % (s.name, s.cpus, lim.cores))
    if lim.mem_mb and s.mem_mb > lim.mem_mb:
        return Reason("too_big", "size %s needs %s; the pool has %s"
                      % (s.name, fmt_mem(s.mem_mb), fmt_mem(lim.mem_mb)))
    return None


def ide_first(it, ctx):
    if not ctx.ide_waiting:
        return None
    return Reason("ide", "an IDE is waiting for room, and goes first")


def fits(it, ctx):
    s = it.size
    res = ctx.reserve
    cpus = s.cpus + (res.cpus if res is not None else 0)
    mem = s.mem_mb + (res.mem_mb if res is not None else 0)
    short = _free_after(ctx, cpus, mem)
    if short is None:
        return None
    u, lim = ctx.usage, ctx.limits
    have = {"cores": "%d of %d cores in use" % (u.cores, lim.cores),
            "mem": "%s of %s in use" % (fmt_mem(u.mem_mb), fmt_mem(lim.mem_mb)),
            "jobs": "%d of %d jobs running" % (u.jobs, lim.jobs)}[short]
    return Reason("room", "no room for a %s job (%s)" % (s.name, have))


def spare_room(it, ctx):
    if it.cls != "background" or ctx.spare is None:
        return None
    s, sp = it.size, ctx.spare
    res = ctx.reserve
    cpus = s.cpus + sp.cpus + (res.cpus if res is not None else 0)
    mem = s.mem_mb + sp.mem_mb + (res.mem_mb if res is not None else 0)
    lim, u = ctx.limits, ctx.usage
    short = (lim.cores and u.cores + cpus > lim.cores) or \
        (lim.mem_mb and mem and u.mem_mb + mem > lim.mem_mb) or \
        (lim.jobs and u.jobs + 2 > lim.jobs)
    if short:
        return Reason("spare", "background work leaves room for one %s job" % sp.name)
    return None


def backfill(it, ctx):
    b = ctx.blocker
    if b is None or b is it or b.waited_s < ctx.backfill_for_s:
        return None
    return Reason("backfill", "waiting behind %s %s (%s), which needs room first"
                  % (b.project, b.wpid[:8], b.size.name))


GATES = (mode, project_hold, project_broken, job_pending, project_cores, budget, too_big,
         ide_first, fits, spare_room, backfill)


def first(it, ctx):
    for g in GATES:
        r = g(it, ctx)
        if r is not None:
            return r
    return None


def plan(items, ctx, order, limit=None):
    """(the items to start now, in order; {key: Reason} for the rest).

    Re-orders after each pick, since fair share changes as cores are taken.
    The first item that waits only for room is the head of the line: smaller
    items may start past it (backfill) until it has waited ``backfill_for``.
    ``limit``: start at most this many."""
    remaining = list(items)
    start, reasons = [], {}
    while remaining and (limit is None or len(start) < limit):
        reasons = {}
        ctx.blocker = None
        pick = None
        for it in order(remaining, ctx.usage, ctx.projs):
            r = first(it, ctx)
            if r is None:
                pick = it
                break
            reasons[it.key] = r
            if r.code == "room" and ctx.blocker is None:
                ctx.blocker = it
        if pick is None:
            break
        start.append(pick)
        ctx.usage.add_item(pick)
        if ctx.budget is not None:
            ctx.budget.reserve(pick)
        remaining.remove(pick)
        reasons.pop(pick.key, None)
    if limit is not None and len(start) >= limit:
        for it in remaining:
            reasons.setdefault(it.key, Reason("limit", "this pass is full"))
    return start, reasons


def fmt_ts(dt):
    return schema.format_timestamp(dt)
