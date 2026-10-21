"""What the board shows, read straight from the files (no database).

Every function here takes paths and returns plain dicts and lists, so the
board can be tested without a web server.
"""

import json
import os
import shlex
from datetime import timedelta

from .. import clock, frontmatter, lease as lease_mod, registry, schema
from ..packet import Packet
from ..project import ProjectError, load_project
from ..views import packets, relative

# Board columns that exist in Stage 1, in display order.
COLUMNS = ("Running", "Ready", "Sleeping", "Paused", "Failed", "Done")
COLUMN_OF = {"RUNNABLE": "Ready", "SLEEPING": "Sleeping", "PAUSED": "Paused",
             "FAILED": "Failed", "COMPLETED": "Done"}

TOOL_RESULT_MAX = 4000      # characters of one tool result shown in the step viewer


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            return fp.read()
    except OSError:
        return None


def _json(path):
    try:
        with open(path) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _ts(s):
    try:
        return schema.parse_timestamp(s)
    except (TypeError, ValueError):
        return None


def _first_line(text):
    lines = (text or "").strip().splitlines()
    return lines[0] if lines else ""


def _zone(proj):
    try:
        return clock.zone(load_project(proj).get("tz"))
    except (ProjectError, clock.ResumeError):
        return clock.zone(None)


def _local(dt, tz):
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M") if dt else ""


def running(pkt, now):
    """The live lease of ``pkt`` as {step, attempt, since}, or None."""
    lz = lease_mod.read(pkt.lease_path)
    if not lz or lease_mod.is_stale(lz, now):
        return None
    since = None
    for r in reversed(pkt.journal().records):
        if r.get("type") == "step-start" and r.get("step") == lz.get("step"):
            since = _ts(r.get("t"))
            break
    return {"step": lz.get("step"), "attempt": lz.get("attempt"), "since": since,
            "host": lz.get("host"), "pid": lz.get("pid")}


def steps(pkt):
    """Every step folder of ``pkt``, committed or failed, oldest first."""
    failed_why = {}
    for r in pkt.journal().records:
        if r.get("type") == "step-failed":
            failed_why[(r.get("step"), r.get("attempt"))] = r.get("why")
    out = []
    try:
        names = os.listdir(pkt.steps_dir)
    except OSError:
        names = []
    for name in names:
        parsed = schema.parse_step_dir(name)
        if parsed is None:
            continue
        n, failed = parsed
        sd = os.path.join(pkt.steps_dir, name)
        meta = _json(os.path.join(sd, "meta.json")) or {}
        if failed is not None:
            outcome = "failed"
        elif os.path.isfile(os.path.join(sd, "summary.md")):
            outcome = "committed"
        else:
            outcome = "running"         # or a crash that recovery has not seen yet
        attempt = failed if failed is not None else meta.get("attempt")
        out.append({
            "dir": name, "n": n, "attempt": attempt, "outcome": outcome,
            "start": _ts(meta.get("start")), "end": _ts(meta.get("end")),
            "cost_usd": meta.get("cost_usd"), "duration_s": meta.get("duration_s"),
            "summary": _first_line(_read(os.path.join(sd, "summary.md"))),
            "why": failed_why.get((n, failed)) if failed is not None else None,
        })
    out.sort(key=lambda s: (s["n"], s["outcome"] != "failed", s["attempt"] or 0))
    return out


def spawn_names(pkt):
    """{child wpid: name} from the spawn lists in ``pkt``'s journal."""
    names = {}
    for r in pkt.journal().records:
        if r.get("type") == "commit-begin":
            for e in (r.get("decision") or {}).get("spawn") or ():
                if e.get("wpid"):
                    names[e["wpid"]] = e.get("name")
    return names


def _next(meta, now, tz):
    st = meta.get("state")
    if st == "RUNNABLE":
        return "due now"
    if st == "SLEEPING":
        t = _ts(meta.get("wake_at"))
        if t:
            return "%s, %s" % (_local(t, tz), "due" if t <= now else relative(
                (t - now).total_seconds()))
    return ""


def tree(entry, now=None):
    """Every packet of a project, in tree order, with what a board row needs."""
    now = now or clock.now()
    tz = _zone(entry["path"])
    names = {}
    out = []
    for depth, pkt, meta, body in packets(entry["path"], entry["root"]):
        if meta is None:
            out.append({"wpid": pkt.wpid, "short": pkt.wpid[:8], "depth": depth,
                        "name": names.get(pkt.wpid), "state": "?", "step": "?",
                        "next": "", "summary": "(status.md unreadable)", "reason": None,
                        "running": None, "steps": [], "cost_usd": 0.0, "path": pkt.path})
            continue
        names.update(spawn_names(pkt))
        st = steps(pkt)
        out.append({
            "wpid": pkt.wpid, "short": pkt.wpid[:8], "depth": depth,
            "name": names.get(pkt.wpid) or ("root" if depth == 0 else None),
            "state": meta.get("state"), "step": meta.get("step"),
            "attempts": meta.get("attempts"), "reason": meta.get("reason"),
            "next": _next(meta, now, tz), "summary": _first_line(body),
            "updated": _ts(meta.get("updated")), "wake_at": _ts(meta.get("wake_at")),
            "running": running(pkt, now),
            "steps": st, "cost_usd": sum(s["cost_usd"] or 0 for s in st), "path": pkt.path,
        })
    return out


def card(entry, now=None):
    """One project's card on the board."""
    now = now or clock.now()
    tz = _zone(entry["path"])
    nodes = tree(entry, now)
    root = nodes[0] if nodes else None
    live = [n for n in nodes if n["running"]]
    if live:
        column = "Running"
    else:
        column = COLUMN_OF.get(root["state"] if root else None, "Failed")
    counts = {}
    for n in nodes:
        counts[n["state"]] = counts.get(n["state"], 0) + 1
    today = now.astimezone(tz).date()
    spend_today = sum(s["cost_usd"] or 0 for n in nodes for s in n["steps"]
                      if s["start"] and s["start"].astimezone(tz).date() == today)
    trouble = [n for n in nodes[1:] if n["state"] in ("FAILED", "?")]
    last = max((s["end"] for n in nodes for s in n["steps"] if s["end"]), default=None)
    run = None
    if live:
        n = live[0]
        since = n["running"]["since"]
        run = {"wpid": n["wpid"], "short": n["short"], "name": n["name"],
               "step": n["running"]["step"],
               "for": relative(-(now - since).total_seconds()).replace(" ago", "")
               if since else ""}
    return {
        "name": entry["name"], "column": column, "root": root, "running": run,
        "counts": sorted(counts.items(), key=lambda kv: str(kv[0])),
        "packets": len(nodes), "trouble": len(trouble),
        "spend_total": sum(n["cost_usd"] for n in nodes), "spend_today": spend_today,
        "last_step": relative(-(now - last).total_seconds()) if last else "never",
        "finished": _local(root["updated"], tz) if root and root.get("updated") else "",
    }


def board(h=None, now=None):
    """{column: [card]} for every registered project, plus projects that failed to load."""
    now = now or clock.now()
    cols = {c: [] for c in COLUMNS}
    broken = []
    for e in registry.entries(h):
        if not os.path.isdir(e["path"]):
            broken.append({"name": e["name"], "why": "%s is missing" % e["path"]})
            continue
        try:
            c = card(e, now)
        except (OSError, ValueError, KeyError) as ex:
            broken.append({"name": e["name"], "why": str(ex)})
            continue
        cols[c["column"]].append(c)
    # Sleepers soonest first; the rest by name.
    far = now + timedelta(days=36500)
    for c in cols.values():
        c.sort(key=lambda k: ((k["root"] or {}).get("wake_at") or far, k["name"]))
    return cols, broken


def timeline(nodes, now=None, width=900, row=22, label=150):
    """An SVG-ready layout: one row per packet, one bar per step."""
    now = now or clock.now()
    starts = [s["start"] for n in nodes for s in n["steps"] if s["start"]]
    if not starts:
        return None
    t0 = min(starts)
    t1 = max([now] + [s["end"] for n in nodes for s in n["steps"] if s["end"]])
    span = max((t1 - t0).total_seconds(), 60.0)
    plot = width - label - 10

    def x(t):
        return label + plot * (t - t0).total_seconds() / span

    rows = []
    for i, n in enumerate(nodes):
        bars = []
        for s in n["steps"]:
            if not s["start"]:
                continue
            end = s["end"] or now
            bars.append({"x": round(x(s["start"]), 1),
                         "w": round(max(x(end) - x(s["start"]), 3.0), 1),
                         "outcome": s["outcome"], "dir": s["dir"],
                         "title": "step %s%s: %s" % (
                             s["n"], " attempt %s" % s["attempt"] if s["outcome"] == "failed"
                             else "", s["why"] or s["summary"] or s["outcome"])})
        rows.append({"y": i * row, "label": ("  " * n["depth"]) + (n["name"] or n["short"]),
                     "wpid": n["wpid"], "bars": bars})
    ticks = []
    step = _tick_step(span)
    t = t0.replace(second=0, microsecond=0)
    while t <= t1:
        if t >= t0:
            ticks.append({"x": round(x(t), 1), "label": t.strftime("%m-%d %H:%M")})
        t += step
    return {"width": width, "height": len(rows) * row + 24, "label": label, "rows": rows,
            "ticks": ticks[:12], "row": row, "start": t0, "end": t1}


def _tick_step(span):
    for s in (60, 300, 900, 3600, 6 * 3600, 86400, 7 * 86400):
        if span / s <= 10:
            return timedelta(seconds=s)
    return timedelta(days=30)


def packet(entry, wpid, now=None):
    """Everything the packet page shows. None if ``wpid`` is not in the project."""
    now = now or clock.now()
    if not schema.is_wpid(wpid):
        return None
    pkt = Packet(os.path.join(entry["path"], "packets", wpid))
    if not os.path.isdir(pkt.path):
        return None
    tz = _zone(entry["path"])
    try:
        meta, body = pkt.load_status()
    except (OSError, frontmatter.FrontMatterError):
        meta, body = {}, ""
    memento = _read(pkt.memento_path) or ""
    files = []
    for dirpath, dirnames, filenames in os.walk(pkt.state_dir):
        dirnames.sort()
        for n in sorted(filenames):
            p = os.path.join(dirpath, n)
            rel = os.path.relpath(p, pkt.state_dir)
            size = os.path.getsize(p) if os.path.isfile(p) else 0
            text = None
            if size <= 64 * 1024:
                try:
                    with open(p, encoding="utf-8") as fp:
                        text = fp.read()
                except (OSError, UnicodeDecodeError):
                    pass
            files.append({"rel": rel, "size": size, "text": text})
    kids = []
    names = spawn_names(pkt)
    for c in meta.get("children") or ():
        try:
            m, b = Packet(os.path.join(entry["path"], "packets", c)).load_status()
            kids.append({"wpid": c, "short": c[:8], "name": names.get(c),
                         "state": m.get("state"), "step": m.get("step"),
                         "summary": _first_line(b)})
        except (OSError, frontmatter.FrontMatterError):
            kids.append({"wpid": c, "short": c[:8], "name": names.get(c), "state": "?",
                         "step": "?", "summary": "(unreadable)"})
    parent = meta.get("parent")
    return {
        "wpid": wpid, "short": wpid[:8], "path": pkt.path, "meta": meta,
        "fields": [(k, meta.get(k)) for k in schema.STATUS_FIELDS if k in meta],
        "summary": body.strip(), "memento": memento, "files": files, "children": kids,
        "parent": parent, "steps": list(reversed(steps(pkt))), "running": running(pkt, now),
        "next": _next(meta, now, tz), "journal": pkt.journal().records[-200:],
    }


def transcript(path, limit=TOOL_RESULT_MAX):
    """A stream-json transcript as display blocks: text, tool calls, results, the end."""
    blocks = []
    try:
        fp = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return blocks
    with fp:
        for line in fp:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            if t == "system" and e.get("subtype") == "init":
                blocks.append({"kind": "init", "text": "model %s, tools %s" % (
                    e.get("model"), ", ".join(e.get("tools") or []) or "none")})
            elif t in ("assistant", "user"):
                content = (e.get("message") or {}).get("content")
                if isinstance(content, str):
                    content = [{"type": "text", "text": content}]
                for c in content or ():
                    if not isinstance(c, dict):
                        continue
                    ct = c.get("type")
                    if ct == "text" and t == "assistant" and c.get("text", "").strip():
                        blocks.append({"kind": "text", "text": c["text"].strip()})
                    elif ct == "thinking" and c.get("thinking", "").strip():
                        blocks.append({"kind": "thinking", "text": c["thinking"].strip()})
                    elif ct == "tool_use":
                        blocks.append({"kind": "tool_use", "name": c.get("name"),
                                       "text": json.dumps(c.get("input"), indent=2)})
                    elif ct == "tool_result":
                        r = c.get("content")
                        if isinstance(r, list):
                            r = "\n".join(x.get("text", "") for x in r if isinstance(x, dict))
                        r = str(r if r is not None else "")
                        cut = len(r) > limit
                        blocks.append({"kind": "tool_result", "error": bool(c.get("is_error")),
                                       "text": r[:limit] + ("\n... (%d more characters)"
                                                            % (len(r) - limit) if cut else "")})
            elif t == "result":
                blocks.append({"kind": "result", "error": bool(e.get("is_error")),
                               "text": "%s: %s turns, $%.4f, %.1fs" % (
                                   e.get("subtype"), e.get("num_turns"),
                                   e.get("total_cost_usd") or 0,
                                   (e.get("duration_ms") or 0) / 1000.0)})
    return blocks


def step(entry, wpid, dirname):
    """Everything the step viewer shows. None if there is no such step folder."""
    if not schema.is_wpid(wpid) or schema.parse_step_dir(dirname) is None:
        return None
    pkt = Packet(os.path.join(entry["path"], "packets", wpid))
    sd = os.path.join(pkt.steps_dir, dirname)
    if not os.path.isdir(sd):
        return None
    all_steps = steps(pkt)
    dirs = [s["dir"] for s in all_steps]
    i = dirs.index(dirname)
    info = all_steps[i]
    meta = _json(os.path.join(sd, "meta.json"))
    session = (meta or {}).get("session_id")
    diff = _read(os.path.join(sd, "state.diff"))
    return {
        "wpid": wpid, "short": wpid[:8], "dir": dirname, "info": info, "meta": meta,
        "label": "%d%s" % (info["n"], " attempt %s" % info["attempt"]
                           if info["outcome"] == "failed" else ""),
        "prompt": _read(os.path.join(sd, "prompt.md")),
        "summary": _read(os.path.join(sd, "summary.md")),
        "result": _read(os.path.join(sd, "result.md")),
        "diff": [(("add" if ln.startswith("+") and not ln.startswith("+++") else
                   "del" if ln.startswith("-") and not ln.startswith("---") else
                   "hunk" if ln.startswith("@@") else ""), ln)
                 for ln in (diff or "").splitlines()] if diff is not None else None,
        "stderr": _read(os.path.join(sd, "stderr.log")),
        "blocks": transcript(os.path.join(sd, "transcript.jsonl")),
        "prev": dirs[i - 1] if i > 0 else None,
        "next": dirs[i + 1] if i + 1 < len(dirs) else None,
        "fork": "cd %s && claude --resume %s --fork-session" % (
            shlex.quote(pkt.path), session)
        if session else None,
    }
