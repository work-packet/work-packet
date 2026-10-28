"""The scheduler on the board: ``/sched``, the mode banner, and what the
project, packet and All packets pages show and change (docs/scheduler.md §9;
plan Q3). Every change goes through ``sched/control.py``."""

import logging
from datetime import datetime, timezone

from .. import archived, registry, schema
from ..sched import control, events, explain
from ..sched.budget import fmt
from ..sched.classes import CLASSES

log = logging.getLogger("wpk.dash")

EVENT_TYPES = ("mode", "hold", "prio", "size", "next", "lost", "cancelled", "pending_long",
               "gate", "backend_down", "backend_up", "cap", "grant_expired", "wpkd_start",
               "wpkd_stop")
MODES = {"run": "running", "drain": "halted", "stop": "stopped"}


def snapshot(home=None):
    """``explain.snapshot``, or None when the config cannot be read (the page says why)."""
    try:
        return explain.snapshot(home)
    except registry.ConfigError as e:
        log.warning("scheduler: %s", e)
        return None


def mode(home=None):
    """The pool's mode for the banner on every page: None while it runs."""
    m = control.read_mode(home)
    return None if m.get("mode", "run") == "run" else m


def recent(home=None, n=25):
    """The latest notable events, newest first."""
    return list(reversed(events.read(home, types=EVENT_TYPES)[-n:]))


def waiting(snap):
    """{wpid: queue row} for every due packet."""
    return {r["wpid"]: r for r in (snap or {}).get("queue", ())}


def packet_info(snap, entry, wpid):
    """What a packet page shows: its class and size and where they come from,
    its place in the queue and why it waits, and its job if it has one."""
    pk = (entry.get("packets") or {}).get(wpid) or {}
    row = waiting(snap).get(wpid)
    job = next((j for j in (snap or {}).get("jobs", ()) if j["wpid"] == wpid), None)
    cls = pk.get("priority") or entry.get("priority") or "normal"
    return {"cls": cls, "cls_from": "packet" if pk.get("priority") else
            "project" if entry.get("priority") else "default",
            "own_cls": pk.get("priority"), "own_size": pk.get("size"), "next": pk.get("next"),
            "size": row["size"] if row else pk.get("size") or entry.get("size") or
            (snap or {}).get("default_size", "look"),
            "row": row, "job": job, "sizes": list((snap or {}).get("sizes", {}))}


def project_info(snap, entry):
    u = (snap or {}).get("usage") or {}
    return {"cls": entry.get("priority") or "normal", "own_cls": entry.get("priority"),
            "size": entry.get("size"), "hold": entry.get("sched") == "hold",
            "hold_by": entry.get("sched_by"), "hold_at": entry.get("sched_at"),
            "hold_reason": entry.get("sched_reason"),
            "cores": (u.get("by_project") or {}).get(entry["name"], 0),
            "jobs": [j for j in (snap or {}).get("jobs", ()) if j["project"] == entry["name"]],
            "queue": [r for r in (snap or {}).get("queue", ()) if r["project"] == entry["name"]],
            "sizes": list((snap or {}).get("sizes", {}))}


def tiles(snap):
    """The Overview's scheduler tiles: mode, cores, spend against pace."""
    if snap is None:
        return None
    lim, u = snap["limits"], snap["usage"]
    out = {"mode": snap["mode"].get("mode", "run"), "cores": u["cores"], "cores_max": lim["cores"],
           "jobs": u["jobs"], "jobs_max": lim["jobs"],
           "queued": sum(1 for r in snap["queue"] if r["waiting"]),
           "next": sum(1 for r in snap["queue"] if not r["waiting"])}
    b = snap.get("budget")
    if b:
        w = b["windows"][0]
        out["spend"] = "%s of %s" % (fmt(b["measure"], w["spent"]), fmt(b["measure"], b["amount"]))
        out["pace"] = fmt(b["measure"], w["pace"])
        out["ahead"] = w["spent"] > w["pace"]
    return out


# --- the budget chart: an SVG drawn here, like the token charts ---------------------

W, H, PAD = 640, 180, 28


def chart(snap, home=None):
    """Coordinates for the budget chart over the current window: spend so far
    (a step line), pace, each class's ceiling, and the reservations on top."""
    b = (snap or {}).get("budget")
    if not b:
        return None
    from ..sched import budget as bmod
    w = b["windows"][0]
    t0, t1 = schema.parse_timestamp(w["start"]), schema.parse_timestamp(w["end"])
    span = (t1 - t0).total_seconds() or 1
    top = max(b["hard_cap"], w["spent"] + w["reserved"], b["amount"]) * 1.05 or 1
    now = schema.parse_timestamp(snap["now"])

    def x(t):
        return PAD + (W - 2 * PAD) * max(0.0, min(1.0, (t - t0).total_seconds() / span))

    def y(v):
        return H - PAD - (H - 2 * PAD) * max(0.0, min(1.0, v / top))
    pts, total = [(x(t0), y(0))], 0.0
    if b["measure"] != "quota":
        cut = w["start"]
        for r in bmod.ledger(archived.entries(home)):
            if (r.end or "") < cut or (r.end or "") > snap["now"]:
                continue
            v = r.amount(b["measure"])
            if v:
                tx = x(schema.parse_timestamp(r.end))
                pts += [(tx, y(total)), (tx, y(total + v))]
                total += v
    else:
        total = w["spent"]
        pts.append((x(now), y(total)))
    pts.append((x(now), y(total)))
    ceil = {}
    for c in CLASSES:
        if c in ("urgent", "high"):
            ceil[c] = "M%.1f %.1fH%.1f" % (x(t0), y(w["ceilings"][c]), x(t1))
    slack = b["slack"]
    pace = []
    steps = 48
    shape = b.get("shape") if w["name"] != "five_hour" else None
    tz = bmod._zone(b.get("tz"))
    for i in range(steps + 1):
        t = datetime.fromtimestamp(t0.timestamp() + span * i / steps, timezone.utc)
        pace.append((x(t), b["amount"] * bmod.fraction(t0, t1, t, shape, tz)))
    for c, off in (("normal", slack), ("low", 0.0), ("background", -slack)):
        ceil[c] = "M" + " L".join("%.1f %.1f" % (px, y(max(0.0, v + off))) for px, v in pace)
    return {"w": W, "h": H, "pad": PAD,
            "spend": "M" + " L".join("%.1f %.1f" % p for p in pts),
            "reserved": None if not w["reserved"] else {
                "x": x(now) - 3, "y": y(total + w["reserved"]), "w": 6,
                "h": max(1.0, y(total) - y(total + w["reserved"]))},
            "pace": "M" + " L".join("%.1f %.1f" % (px, y(v)) for px, v in pace),
            "ceil": ceil, "now": x(now), "top": fmt(b["measure"], top),
            "start": w["start"], "end": w["end"], "measure": b["measure"]}
