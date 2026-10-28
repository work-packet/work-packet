"""What ``wpk ps``, ``show`` and ``log`` print."""

import json
import os

from . import clock, frontmatter, layout, report, schema
from .packet import Packet
from .project import ProjectError, load_project

ACTIVE = ("RUNNABLE", "SLEEPING", "NEEDS_INPUT", "PAUSED")


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


def ps(entries, show_all=False, now=None):
    """Lines for ``wpk ps``. Finished projects are left out unless ``show_all``."""
    now = now or clock.now()
    rows = []
    for e in entries:
        try:
            tz = clock.zone(load_project(e["path"]).get("tz"))
        except (ProjectError, clock.ResumeError):
            tz = clock.zone(None)
        pk = packets(e["path"], e["root"])
        if not show_all and pk and all(m is not None and m["state"] not in ACTIVE
                                       for _, _, m, _ in pk):
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
            rows.append((e["name"], "  " * depth + pkt.wpid[:8], meta["state"],
                         str(meta["step"]), _next(meta, now, tz), summary))
    head = ("PROJECT", "WPID", "STATE", "STEP", "NEXT", "LAST SUMMARY")
    if not rows:
        return []
    widths = [max(len(r[i]) for r in rows + [head]) for i in range(5)]
    fmt = "  ".join("%%-%ds" % w for w in widths) + "  %s"
    return [(fmt % head).rstrip()] + [(fmt % r).rstrip() for r in rows]


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
