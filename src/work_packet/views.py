"""What ``wpk ps``, ``show`` and ``log`` print."""

import json
import os

from . import clock, frontmatter, layout, report, schema
from .packet import Packet
from .project import ProjectError, load_project


def relative(seconds):
    """``in 3d 2h``, ``5m ago``, ``now``."""
    s = int(seconds)
    if abs(s) < 60:
        return "now"
    a = abs(s)
    parts = []
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if a >= n:
            parts.append("%d%s" % (a // n, unit))
            a %= n
        if len(parts) == 2:
            break
    txt = " ".join(parts)
    return "in " + txt if s > 0 else txt + " ago"


def packets(proj, root):
    """[(depth, Packet, meta, body)] in tree order: root, then each child's subtree."""
    pdir = layout.runs_dir(proj)
    out, seen = [], set()

    def walk(w, depth):
        if w in seen:
            return
        seen.add(w)
        pkt = Packet(os.path.join(pdir, w))
        try:
            meta, body = pkt.load_status()
        except (OSError, frontmatter.FrontMatterError):
            out.append((depth, pkt, None, ""))
            return
        out.append((depth, pkt, meta, body))
        for c in meta.get("children") or ():
            walk(c, depth + 1)
    walk(root, 0)
    try:
        rest = sorted(n for n in os.listdir(pdir) if schema.is_wpid(n) and n not in seen)
    except OSError:
        rest = []
    for w in rest:                 # not reachable from the root: show them anyway
        walk(w, 0)
    return out


# --- who has it, and whose move it is (docs/collaboration.md §4.1) --------------
#
# The executor's state answers only "what will the runner do with this?". These
# derive what a person wants to know from it: is the work still open, who is
# on it now, and whose move it is. The board, ``wpk ps`` and the CLI all use
# them; nothing is stored but the person's own facts (lifecycle, autonomy).

COLUMNS = ("Inbox", "Needs you", "Working: you", "Working: agent", "Waiting", "Parked", "Done")
NEEDS_YOU = ("question", "failure", "review")      # ball kinds that are a person's move


def autonomy(meta):
    """manual, handoff or runner (docs/collaboration.md §4.4). Packets from before
    it work as they always did: on hand-off."""
    a = meta.get("autonomy")
    return a if a in schema.AUTONOMIES else "handoff"


def lifecycle(meta):
    """open, done or dropped. A person says done (``wpk done``); the runner
    finishing is done only for a packet left to it with no review. A finished
    packet from before the field counts as done, as the board showed it."""
    lc = meta.get("lifecycle")
    if lc in ("done", "dropped"):
        return lc
    if meta.get("state") == "COMPLETED" and (lc is None or (
            autonomy(meta) == "runner" and meta.get("review") == "never")):
        return "done"
    return "open"


def ball(meta, running=None, present=()):
    """Whose move it is: ``{"who", "kind", "text"}``. ``who``: you, agent,
    scheduled or nobody; ``kind`` says why; ``text`` is a short line for a card.
    ``running``: the live lease (``{"step"}``), if a step runs. ``present``: the
    project's live presence records (``presence.live``)."""
    st, why = meta.get("state"), meta.get("reason") or ""
    lc = lifecycle(meta)
    if lc != "open":
        return {"who": "nobody", "kind": lc, "text": lc}
    if running:
        return {"who": "agent", "kind": "working",
                "text": "step %s running" % running.get("step", "?")}
    if meta.get("taken_by"):
        return {"who": "you", "kind": "studio", "text": "in the studio"}
    if st == "PAUSED" and why == schema.REASON_CLAIMED:
        from .presence import where
        here = " · %s" % where(present) if present else ""
        return {"who": "you", "kind": "claimed",
                "text": "yours%s: hand it back when you're done" % here}
    if present and st not in ("NEEDS_INPUT", "FAILED"):
        from .presence import where
        return {"who": "you", "kind": "working", "text": "you · %s" % (where(present) or
                                                                       "working on it")}
    if st == "NEEDS_INPUT":
        return {"who": "you", "kind": "question", "text": why or "a question"}
    if st == "FAILED":
        return {"who": "you", "kind": "failure", "text": why or "failed"}
    if st == "COMPLETED":
        if _unread(meta):
            return {"who": "you", "kind": "review", "text": "the runner finished: review it"}
        return {"who": "you", "kind": "parked", "text": "finished; mark it done or hand it more"}
    if st == "RUNNABLE":
        if meta.get("waiting_on"):
            return {"who": "agent", "kind": "children", "text": "waits on its children"}
        return {"who": "agent", "kind": "queued", "text": "queued for the runner"}
    if st == "SLEEPING":
        if meta.get("waiting_on"):
            return {"who": "agent", "kind": "children", "text": "waits on its children"}
        return {"who": "scheduled", "kind": "scheduled", "text": "wakes later"}
    if st == "PAUSED":
        if why == schema.REASON_SETUP:
            return {"who": "you", "kind": "parked", "text": "not started"}
        if why in (schema.REASON_BY_HAND, schema.REASON_STUDIO, schema.REASON_DONE):
            return {"who": "you", "kind": "parked", "text": "parked"}
        return {"who": "you", "kind": "parked", "text": "paused: %s" % why}
    return {"who": "you", "kind": "failure", "text": "status.md unreadable"}


def _unread(meta):
    """Stopped, and nobody has looked since (docs/overview-recent.md §2): looking at
    a finished packet is reviewing it. ``stopped`` and ``seen`` as status.md has them,
    or both as datetimes."""
    at, seen = meta.get("stopped"), meta.get("seen")
    return bool(at) and not (seen and seen >= at)


def driver(meta, running=None, present=()):
    """Who is on it now: runner, you, "you + runner" (a hand-off made while you
    were there, §5.2) or nobody. ``present``: as for ``ball``."""
    you = bool(present) or bool(meta.get("taken_by")) or (
        meta.get("state") == "PAUSED" and meta.get("reason") == schema.REASON_CLAIMED)
    if running:
        return "you + runner" if you else "runner"
    return "you" if you else "nobody"


def column(meta, running=None, present=()):
    """The board column (docs/collaboration.md §8.2), from the ball and the driver."""
    if lifecycle(meta) != "open":
        return "Done"
    d = driver(meta, running, present)
    if d in ("runner", "you + runner"):
        return "Working: agent"
    if d == "you":
        return "Working: you"
    b = ball(meta, running, present)
    if b["kind"] in NEEDS_YOU:
        return "Needs you"
    if b["kind"] == "queued":
        return "Working: agent"
    if b["kind"] in ("scheduled", "children"):
        return "Waiting"
    return "Parked"


def _next(meta, now, tz):
    st = meta["state"]
    if st == "RUNNABLE":
        return "due now"
    if st == "SLEEPING" and meta.get("wake_at"):
        t = schema.parse_timestamp(meta["wake_at"])
        local = t.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        rel = relative((t - now).total_seconds())
        return "%s (%s)" % (local, "due" if t <= now else rel)
    return "-"


def ps(entries, show_all=False, now=None, raw=False):
    """Lines for ``wpk ps``: whose move each packet is (``raw``: the executor's
    state instead). Projects that are done are left out unless ``show_all``."""
    now = now or clock.now()
    rows = []
    for e in entries:
        try:
            tz = clock.zone(load_project(e["path"]).get("tz"))
        except (ProjectError, clock.ResumeError):
            tz = clock.zone(None)
        pk = packets(e["path"], e["root"])
        if not show_all and pk and pk[0][2] is not None and lifecycle(pk[0][2]) != "open":
            continue
        for depth, pkt, meta, body in pk:
            if meta is None:
                rows.append((e["name"], "  " * depth + pkt.wpid[:8], "?", "?", "-",
                             "(status.md unreadable)"))
                continue
            line = (body or "").strip().splitlines()
            summary = line[0] if line else ""
            if meta["state"] in ("NEEDS_INPUT", "PAUSED", "FAILED") and meta.get("reason"):
                summary = "[%s] %s" % (meta["reason"], summary)
            if raw:
                what = meta["state"]
            else:
                b = ball(meta, _live(pkt, now))
                what = "%s:%s" % (b["who"], b["kind"])
            rows.append((e["name"], "  " * depth + pkt.wpid[:8], what,
                         str(meta["step"]), _next(meta, now, tz), summary))
    head = ("PROJECT", "WPID", "STATE" if raw else "BALL", "STEP", "NEXT", "LAST SUMMARY")
    if not rows:
        return []
    widths = [max(len(r[i]) for r in rows + [head]) for i in range(5)]
    fmt = "  ".join("%%-%ds" % w for w in widths) + "  %s"
    return [(fmt % head).rstrip()] + [(fmt % r).rstrip() for r in rows]


def _live(pkt, now):
    """The packet's live lease, or None."""
    from . import lease
    lz = lease.read(pkt.lease_path)
    return lz if lz and not lease.is_stale(lz, now) else None


def show(pkt):
    meta, body = pkt.load_status()
    out = ["# %s" % pkt.wpid, "", "## status.md", ""]
    for k in schema.STATUS_FIELDS:
        if k in schema.STATUS_OPTIONAL and k not in meta:
            continue
        out.append("%-12s %s" % (k + ":", meta.get(k)))
    if body.strip():
        out += ["", body.rstrip()]
    from . import questions
    qs = questions.of_packet(pkt)
    if qs:
        out += ["", "## open questions (answer with `wpk answer`)", ""]
        for q in qs:
            out.append("%s: %s" % (q["id"], q["q"]))
            extra = []
            if q["recommend"]:
                extra.append("recommend: %s" % q["recommend"])
            if q["choices"]:
                extra.append("choices: %s" % " / ".join(q["choices"]))
            if q["grants"]:
                extra.append("yes grants: %s" % ", ".join(q["grants"]))
            if q.get("sets"):
                extra.append(questions.describe_sets(q))
            if q.get("request"):
                extra.append("yes sends request %s (state/requests/%s.md)" % (
                    q["request"], q["request"]))
            if extra:
                out.append("    " + "; ".join(extra))
    if meta["state"] in ("COMPLETED", "FAILED"):
        rep = report.render(pkt)
        if rep is not None:
            out += ["", "## report.md (wpk report prints it on its own)", ""]
            out += [report._demote(x, 1) for x in rep[2:]]
    from . import requests
    rs = requests.entries(wpid=pkt.wpid)
    if rs:
        out += ["", "## requests (docs/delegation.md)", ""]
        for e in rs:
            out.append(("from %s (%s): " % (e["from"]["project"], e["from"]["wpid"][:8])
                        if e["from"]["wpid"] != pkt.wpid else "") + requests.describe(e))
    out += ["", "## memento.md", "", open(pkt.memento_path, encoding="utf-8").read().rstrip()]
    kids = meta.get("children") or []
    out += ["", "## children", ""]
    if not kids:
        out.append("none")
    for c in kids:
        try:
            m, b = Packet(os.path.join(os.path.dirname(pkt.path), c)).load_status()
            line = b.strip().splitlines()
            out.append("%s  %-9s step %-3s %s" % (c, m["state"], m["step"],
                                                  line[0] if line else ""))
        except (OSError, frontmatter.FrontMatterError):
            out.append("%s  (unreadable)" % c)
    return out


def report_lines(pkt):
    """``wpk report``: the completion report with its children rolled up, or,
    for a packet that has none, the last step's summary and a note saying so."""
    rep = report.render(pkt)
    if rep is not None:
        return rep
    meta, body = pkt.load_status()
    why = "has not finished" if meta["state"] not in ("COMPLETED", "FAILED") else \
        "finished without one (before reports were required)"
    return ["# %s (%s)" % (pkt.wpid, meta["state"]), "",
            "No completion report: the packet %s. Last summary:" % why, "",
            body.strip() or "(none)"]


def _detail(r):
    t = r.get("type")
    if t == "step-start":
        return "attempt %s, %s" % (r.get("attempt"), r.get("model"))
    if t in ("step-failed", "step-nudge"):
        return "attempt %s: %s" % (r.get("attempt"), r.get("why"))
    if t == "commit-begin":
        d = r.get("decision") or {}
        s = "%s (%s)" % (d.get("state"), d.get("resume_expr"))
        if d.get("wake_at"):
            s += " until %s" % d["wake_at"]
        if d.get("spawn"):
            s += ", spawn %s" % ", ".join(e.get("name", "?") for e in d["spawn"])
        return s
    if t == "commit-end":
        bits = []
        if r.get("cost_usd") is not None:
            bits.append("$%.4f" % r["cost_usd"])
        if r.get("duration_s") is not None:
            bits.append("%.1fs" % r["duration_s"])
        return ", ".join(bits)
    if t == "admin":
        return "%s by %s" % (r.get("op"), r.get("by"))
    return str(r.get("msg", ""))


def log(pkt, step=None):
    if step is None:
        j = pkt.journal()
        out = ["%-20s  %-12s  %-4s  %s" % ("TIME", "TYPE", "STEP", "DETAIL")]
        for r in j.records:
            out.append(("%-20s  %-12s  %-4s  %s" % (
                r.get("t", "?"), r.get("type", "?"), r.get("step", ""), _detail(r))).rstrip())
        return out
    sd = pkt.step_dir(step)
    if not os.path.isdir(sd):
        raise FileNotFoundError("no committed step %d (%s)" % (step, sd))
    out = ["# %s step %d" % (pkt.wpid, step)]
    for name in ("summary.md", "state.diff", "meta.json"):
        p = os.path.join(sd, name)
        out += ["", "## " + name, ""]
        try:
            text = open(p, encoding="utf-8").read()
        except FileNotFoundError:
            text = "(missing)"
        if name == "meta.json":
            try:
                text = json.dumps(json.loads(text), indent=2)
            except ValueError:
                pass
        out.append(text.rstrip() or "(empty)")
    return out


# --- the timeline: every actor's work, in one list (docs/collaboration.md §8.4) ---

_HAND = {"session": "VS Code", "studio": "studio"}


def _epoch(ts):
    import calendar
    import time
    try:
        return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def _who(by):
    return (by or "someone").split("@")[0]


def _line(text, n=120):
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


def timeline(pkt, since=None, limit=None):
    """The packet's history, newest first: ``[{"t", "actor", "kind", "text", "step"}]``
    (``t`` epoch seconds; ``actor`` "runner", "alice (VS Code)", "Claude (VS Code
    (web))", ...). ``since``: only what came after (epoch)."""
    from .migrate import SCRIBE, _hand_actor
    out, worker = [], {}
    for r in pkt.journal().records:
        t = _epoch(r.get("t"))
        if t is None or (since is not None and t <= since):
            if r.get("type") == "step-start":
                worker[r.get("step")] = r.get("worker")
            continue
        typ = r.get("type")
        ev = None
        if typ == "step-start":
            worker[r.get("step")] = r.get("worker")
        elif typ == "commit-begin":
            d = r.get("decision") or {}
            w = d.get("worker") or worker.get(r.get("step"))
            summary = _line((d.get("summary") or "").strip().split("\n")[0])
            if w not in (None, "agent", "model"):
                actor = SCRIBE if w == "scribe" else _hand_actor(pkt, r.get("step"), w,
                                                                 "someone")
                ev = {"actor": actor, "kind": "checkpoint", "text": summary or "checkpoint"}
            else:
                st = d.get("state")
                what = {"NEEDS_INPUT": "asked: %s" % _line(d.get("reason")),
                        "COMPLETED": "finished: %s" % summary,
                        "FAILED": "failed: %s" % _line(d.get("reason"))}.get(st, summary)
                ev = {"actor": "runner", "kind": "step", "text": "step %s: %s" % (
                    r.get("step"), what or "done")}
        elif typ == "step-failed":
            ev = {"actor": "runner", "kind": "failure", "text": "step %s attempt %s failed: %s"
                  % (r.get("step"), r.get("attempt"), _line(r.get("why")))}
        elif typ == "handoff":
            what = r.get("instruction") or r.get("note") or (
                "answered %d question%s" % (len(r["answers"]), "" if len(r["answers"]) == 1
                                            else "s") if r.get("answers") else "")
            ev = {"actor": _who(r.get("by")), "kind": "handoff", "text": "handed off%s%s" % (
                ": " if what else "", _line(what))}
        elif typ == "admin" and r.get("op") in ("done", "drop", "reopen", "autonomy",
                                                "pause", "resume", "wake"):
            what = {"done": "marked it done", "drop": "dropped it", "reopen": "reopened it",
                    "pause": "paused it", "resume": "resumed it", "wake": "woke it",
                    "autonomy": "set autonomy to %s" % r.get("autonomy")}[r["op"]]
            ev = {"actor": _who(r.get("by")), "kind": r["op"], "text": what}
        elif typ in ("session-start", "session-end"):
            a = r.get("actor") or {}
            from .presence import WHERE
            ev = {"actor": "%s (%s)" % ((a.get("kind") or "claude").capitalize(),
                                        WHERE.get(a.get("via"), a.get("via") or "?")),
                  "kind": typ, "text": "session %s" % ("started" if typ == "session-start"
                                                       else "ended"),
                  "who": _who(r.get("by"))}
        elif typ == "note" and r.get("by"):        # a person's (a checkpoint during a step)
            ev = {"actor": _who(r.get("by")), "kind": "note", "text": _line(r.get("msg"))}
        elif typ == "config" and r.get("changes"):
            ev = {"actor": _who(r.get("by")), "kind": "config",
                  "text": "changed settings: %s" % _line("; ".join(map(str, r["changes"])))}
        if ev:
            ev.update(t=t, step=r.get("step"))
            out.append(ev)
    out.reverse()
    return out[:limit] if limit else out
