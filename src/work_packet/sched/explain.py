"""The queue with reasons, for ``wpk sched`` and the board (docs/scheduler.md §6.3)."""

from datetime import timedelta

from .. import clock, registry
from . import control, gates, jobs, queue
from . import config as sconfig
from .backends.local import Local


def snapshot(h=None, now=None, cfg=None):
    """Everything ``wpk sched`` shows, as plain data (``--json``)."""
    from .dispatcher import Dispatcher
    h = h or registry.home()
    now = now or clock.now()
    cfg = cfg or sconfig.load(h)
    d = Dispatcher(home=h, backend=Local(h), cfg=cfg, now=lambda: now)
    items, ctx = d.context(now, cfg)
    held = gates.Usage.of(jobs.all(h))
    budget = ctx.budget.describe() if ctx.budget is not None else None
    start, reasons = gates.plan(items, ctx, queue.order)
    rest = [it for it in items if it.key in reasons]
    rows = [_row(it, None, i + 1) for i, it in enumerate(start)]
    rows += [_row(it, reasons[it.key], len(start) + i + 1)
             for i, it in enumerate(queue.order(rest, ctx.usage, ctx.projs))]
    lim = ctx.limits
    out = {
        "now": sconfig.schema.format_timestamp(now),
        "mode": control.read_mode(h, cfg),
        "backend": cfg.get("backend", "local"),
        "limits": {"cores": lim.cores, "mem_mb": lim.mem_mb, "jobs": lim.jobs,
                   "grant": lim.grant, "notes": lim.notes},
        "usage": {"cores": held.cores, "mem_mb": held.mem_mb, "jobs": held.jobs,
                  "by_size": held.by_size, "by_kind": held.by_kind,
                  "by_project": held.by_project},
        "holds": sorted(p.name for p in ctx.projs.values() if p.hold),
        "queue": rows,
        "jobs": [_job(r) for r in jobs.all(h)],
        "sizes": {n: s.describe() for n, s in sconfig.sizes(cfg).items()},
        "default_size": cfg["default_size"],
        "core_hours": core_hours(h, now - timedelta(days=7)),
        "backend_down": backend_down(h),
    }
    if budget is not None:
        out["budget"] = budget
    return out


def backend_down(h=None):
    """The last ``backend_down`` event if no ``backend_up`` came after it."""
    from . import events
    last = None
    for e in events.read(h, types=("backend_down", "backend_up", "wpkd_start")):
        last = e if e["type"] == "backend_down" else None
    return last


def _row(it, r, pos):
    return {"pos": pos, "project": it.project, "wpid": it.wpid, "state": it.state,
            "due": it.due, "class": it.cls, "class_from": it.cls_from, "aged": it.aged,
            "size": it.size.name, "size_from": it.size_from, "next": it.next,
            "waiting": None if r is None else r.code,
            "why": "starts next" if r is None else r.text,
            "clears_at": None if r is None else r.clears_at, "notes": it.notes}


def _job(r):
    return {"id": r.id, "kind": r.kind, "project": r.project, "wpid": r.wpid, "step": r.step,
            "size": r.size, "cpus": r.cpus, "mem_mb": r.mem_mb, "class": r.cls,
            "state": r.state, "ref": r.ref, "submitted": r.submitted, "started": r.started,
            "cancel": r.cancel, "lost": r.lost, "by": r.by}


def pool(h=None):
    """Usage by size and kind, from the job records."""
    u = gates.Usage.of(jobs.all(h))
    return {"cores": u.cores, "mem_mb": u.mem_mb, "jobs": u.jobs, "by_size": u.by_size,
            "by_kind": u.by_kind}


def core_hours(h=None, since=None):
    """From ``finished`` events since ``since``: core-hours (cpus x wall) and CPU
    hours by size and by project, and the multi-core jobs that hardly used
    their cores (``low_cpu``, docs/scheduler.md §5.2)."""
    from datetime import timedelta
    from . import events
    since = since or clock.now() - timedelta(days=7)
    by_size, by_project, low = {}, {}, []
    for e in events.read(h, since=since, types=("finished",)):
        if e.get("wall_s") is None:
            continue
        ch = (e.get("cpus") or 1) * e["wall_s"] / 3600.0
        cpu = (e.get("cpu_s") or 0) / 3600.0
        for d, k in ((by_size, e.get("size", "?")), (by_project, e.get("project", "?"))):
            t = d.setdefault(k, {"core_h": 0.0, "cpu_h": 0.0, "jobs": 0})
            t["core_h"] += ch
            t["cpu_h"] += cpu
            t["jobs"] += 1
        if e.get("low_cpu"):
            low.append(e)
    return {"since": sconfig.schema.format_timestamp(since), "by_size": by_size,
            "by_project": by_project, "low_cpu": low[-20:]}


def queue_rows(h=None, now=None):
    return snapshot(h, now)["queue"]


def waiting_on(snap):
    """{wpid: one line}: why each due packet waits, for cards and packet pages."""
    return {r["wpid"]: r["why"] for r in snap["queue"]}


def lines(snap):
    """``wpk sched`` as text."""
    m = snap["mode"]
    out = []
    head = "pool: %s" % {"run": "running", "drain": "HALTED (draining)",
                         "stop": "STOPPED"}[m.get("mode", "run")]
    if m.get("mode") != "run":
        head += " by %s" % m.get("by", "?")
        if m.get("at"):
            head += " at %s" % m["at"]
        if m.get("reason"):
            head += ": %s" % m["reason"]
    out.append(head + "   (backend %s)" % snap["backend"])
    if snap.get("backend_down"):
        b = snap["backend_down"]
        out.append("backend DOWN since %s: %s" % (b["t"], b.get("why", "")))
    lim, u = snap["limits"], snap["usage"]

    def of(used, limit, fmt=str):
        return "%s/%s" % (fmt(used), fmt(limit) if limit else "-")
    out.append("in use: cores %s  mem %s  jobs %s%s" % (
        of(u["cores"], lim["cores"]), of(u["mem_mb"], lim["mem_mb"], sconfig.fmt_mem),
        of(u["jobs"], lim["jobs"]),
        "  (" + ", ".join("%s %d" % kv for kv in sorted(u["by_size"].items())) + ")"
        if u["by_size"] else ""))
    if lim.get("grant"):
        g = lim["grant"]
        out.append("grant: by %s until %s" % (g.get("by", "?"), g.get("expires", "-")))
    for n in lim.get("notes") or ():
        out.append("note: %s" % n)
    if snap.get("budget"):
        b = snap["budget"]
        out.append("budget: %s" % b.get("line", ""))
        for c in b.get("classes") or ():
            out.append("  %-10s %s" % (c["class"], c["line"]))
    if snap["holds"]:
        out.append("on hold: %s" % ", ".join(snap["holds"]))
    if snap["jobs"]:
        out.append("")
        out.append("jobs:")
        for j in snap["jobs"]:
            out.append("  %-12s %-8s %-10s %s  step %s  %s%s" % (
                j["id"], j["state"], j["project"], j["wpid"][:8], j["step"], j["size"],
                "  (cancelling)" if j["cancel"] else ""))
    out.append("")
    if not snap["queue"]:
        out.append("queue: nothing due")
        return out
    out.append("queue:")
    for r in snap["queue"]:
        cls = r["class"] + ("->%s" % r["aged"] if r["aged"] != r["class"] else "")
        out.append("  %2d %-10s %s  %-17s %-5s %s%s" % (
            r["pos"], r["project"], r["wpid"][:8], cls + (" next" if r["next"] else ""),
            r["size"], r["why"], " (until %s)" % r["clears_at"] if r["clears_at"] else ""))
    return out
