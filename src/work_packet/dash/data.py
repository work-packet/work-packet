"""What the board shows, read straight from the files (no database).

Every function here takes paths and returns plain dicts and lists, so the
board can be tested without a web server.
"""

import json
import os
import shlex
import socket
from datetime import timedelta
from urllib.parse import quote as urlquote

from .. import (clock, frontmatter, lease as lease_mod, notes as notes_mod, procs as procs_mod,
               questions, registry, report as report_mod, schema)
from .. import archived, layout
from ..packet import Packet
from ..project import ProjectError, load_project
from ..views import packets, relative

# Board columns, in display order.
COLUMNS = ("Needs you", "Running", "Ready", "Sleeping", "Paused", "Failed", "Done")
COLUMN_OF = {"NEEDS_INPUT": "Needs you", "RUNNABLE": "Ready", "SLEEPING": "Sleeping",
             "PAUSED": "Paused",
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
            failed_why[(r.get("step"), r.get("run", r.get("attempt")))] = r.get("why")
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
            "context_tokens": _context_tokens(meta.get("tokens")),
            "output_tokens": (meta.get("tokens") or {}).get("output_tokens"),
            "summary": _first_line(_read(os.path.join(sd, "summary.md"))),
            "why": failed_why.get((n, failed)) if failed is not None else None,
            "item": _item(sd, failed is not None),
        })
    out.sort(key=lambda s: (s["n"], s["outcome"] != "failed", s["attempt"] or 0))
    done = {s["n"]: s["item"] for s in out if s["outcome"] == "committed"}
    for s in out:
        if s["item"] is None and s["outcome"] == "failed":
            s["item"] = done.get(s["n"])
    return out


def _context_tokens(t):
    if not isinstance(t, dict):
        return None
    n = [t.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                            "cache_read_input_tokens")]
    return sum(v for v in n if isinstance(v, int)) if any(isinstance(v, int) for v in n) else None


def _item(sd, failed):
    """The memento's ``item`` (``stats.packet_steps`` does the same)."""
    try:
        mm, _ = frontmatter.load(os.path.join(sd, "pending-memento.md" if failed
                                              else "result.md"))
    except (OSError, frontmatter.FrontMatterError):
        return None
    return schema.memento_item(mm)


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


def tasks(entry, nodes):
    """The packet's tasks (docs/concepts.md): the root's steps split at each hand-off of a
    new instruction, oldest first, each followed by the child packets it spawned (as
    ``tree()`` rows, ``kind`` "child"). A task row has ``tree()``'s keys plus ``kind``
    "task", ``n``, ``instruction`` (its first line; ``text``, all of it), ``first``/``last``
    step, ``report`` (the report's path in the packet folder, if it has one; that of the
    step that wrote it, ``report_step``, where it can) and ``kids``
    (the wpids of the children it spawned)."""
    if not nodes:
        return []
    root = nodes[0]
    recs = Packet(root["path"]).journal().records
    batch, of, why, ended, reports, spawned = 1, {}, {}, {}, {}, {}
    for r in recs:
        t = r.get("type")
        if t == "step-start" and isinstance(r.get("step"), int):
            of[r["step"]] = batch
        elif t == "commit-begin":
            for sp in (r.get("decision") or {}).get("spawn") or ():
                if sp.get("wpid"):
                    spawned[sp["wpid"]] = of.get(r.get("step"), batch)
        elif t == "handoff":
            if r.get("report"):
                reports[batch] = r["report"]
            if "instruction" in r:
                ended[batch] = r.get("from")
                batch += 1
                why[batch] = r.get("instruction")
    subtrees, cur = {}, None
    for n in nodes[1:]:
        if n["depth"] == 1:
            cur = subtrees.setdefault(spawned.get(n["wpid"], batch), [])
        if cur is not None:
            cur.append(dict(n, kind="child"))
    out = []
    for i in range(1, batch + 1):
        st = [s for s in root["steps"] if of.get(s["n"], 1) == i]
        done = [s for s in st if s["outcome"] == "committed"]
        last = i == batch
        report = reports.get(i)
        if last and os.path.isfile(os.path.join(root["path"], "report.md")):
            report = "report.md"
        # The step that wrote it keeps it and a copy of its files (report.snapshot).
        wrote = [s["dir"] for s in done
                 if os.path.isfile(os.path.join(root["path"], "steps", s["dir"], "report.md"))]
        if report and wrote:
            report = "steps/%s/report.md" % wrote[-1]
        out.append({
            "kind": "task", "n": i, "wpid": root["wpid"], "short": root["short"], "depth": 0,
            "name": "task %d" % i, "instruction": _first_line(why.get(i)),
            "state": root["state"] if last else ended.get(i) or "COMPLETED",
            "reason": root.get("reason") if last else None,
            "running": root["running"] if last else None,
            "step": len({s["n"] for s in done}), "next": root["next"] if last else "",
            "steps": st, "first": st[0]["n"] if st else None, "last": st[-1]["n"] if st else None,
            "cost_usd": sum(s["cost_usd"] or 0 for s in st),
            "summary": (done[-1]["summary"] if done else None) or (root["summary"] if last else None),
            "report": report, "report_step": wrote[-1] if report and wrote else None,
            "text": (why.get(i) or "").strip(),
            "kids": [n["wpid"] for n in subtrees.get(i, []) if n["depth"] == 1],
        })
        out += subtrees.get(i, [])
    return out


def card(entry, now=None, nodes=None):
    """One project's card on the board. ``nodes``: its ``tree()``, if already read."""
    now = now or clock.now()
    tz = _zone(entry["path"])
    nodes = tree(entry, now) if nodes is None else nodes
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
        try:
            step_dir = os.path.join(layout.run_dir(entry["path"], n["wpid"]), "steps",
                                    schema.step_dir_name(int(run["step"])))
            evs = activity(os.path.join(step_dir, "transcript.jsonl"))["events"]
            ev = evs[-1] if evs else None
            if ev:
                run["now"] = ev["label"] if ev["kind"] == "text" else \
                    "%s: %s" % (ev["name"], ev["label"])
        except (TypeError, ValueError):
            pass
    held = None
    if root and root["state"] == "PAUSED" and root.get("reason") == "setup" and not live:
        held = setup_summary(entry)
    return {
        "name": entry["name"], "column": column, "root": root, "running": run,
        "setup": held,
        "counts": sorted(counts.items(), key=lambda kv: str(kv[0])),
        "packets": len(nodes), "trouble": len(trouble),
        "spend_total": sum(n["cost_usd"] for n in nodes), "spend_today": spend_today,
        "last_step": relative(-(now - last).total_seconds()) if last else "never",
        "last_end": last,
        "finished": _local(root["updated"], tz) if root and root.get("updated") else "",
    }


def setup_summary(entry):
    """For a root held for setup: the doctor's counts and next command (docs/setup.md §7)."""
    from .. import setup
    try:
        tg = setup.target(entry["path"])
        cs = setup.readiness(tg, tools=False)
    except (setup.SetupError, OSError) as e:
        return {"missing": None, "warnings": None, "next": str(e)}
    return {"missing": len(setup.missing(cs)),
            "warnings": sum(1 for c in cs if c.level == "warn"),
            "next": setup.next_step(tg, cs)}


def board(h=None, now=None, rows=None):
    """{column: [card]} for every registered project, plus projects that failed to load.
    Each card and each broken one names its ``board`` (docs/boards.md). Given a list,
    ``rows`` gets every packet of every project (``packet_rows``)."""
    now = now or clock.now()
    cols = {c: [] for c in COLUMNS}
    broken = []
    names = [b["name"] for b in registry.boards(h)]
    for e in archived.entries(h):
        on = registry.board_of(e, names)
        if not os.path.isdir(e["path"]):
            broken.append({"name": e["name"], "board": on, "why": "%s is missing" % e["path"]})
            continue
        try:
            nodes = tree(e, now)
            c = card(e, now, nodes)
        except (OSError, ValueError, KeyError) as ex:
            broken.append({"name": e["name"], "board": on, "why": str(ex)})
            continue
        c["board"] = on
        if rows is not None:
            rows += packet_rows(e, on, nodes)
        cols[c["column"]].append(c)
    # Sleepers soonest first; the rest by name.
    far = now + timedelta(days=36500)
    for c in cols.values():
        c.sort(key=lambda k: ((k["root"] or {}).get("wake_at") or far, k["name"]))
    return cols, broken


def packet_rows(entry, board, nodes):
    """The All packets table's rows for one project (docs/boards.md)."""
    out = []
    for n in nodes:
        last = max((s["end"] for s in n["steps"] if s["end"]), default=None)
        out.append({
            "board": board, "project": entry["name"], "wpid": n["wpid"],
            "short": n["short"], "name": n["name"] or n["short"], "depth": n["depth"],
            "state": "running" if n["running"] else (n["state"] or "?"),
            "step": n["step"], "attempts": n.get("attempts"), "last": last,
            "cost_usd": n["cost_usd"], "next": n["next"],
            "why": n["reason"] or n["summary"] or "",
        })
    return out


def only(cols, broken, board):
    """``board()``'s result cut down to one board."""
    return ({k: [c for c in v if c["board"] == board] for k, v in cols.items()},
            [b for b in broken if b["board"] == board])


def side(h, cols, broken):
    """The side tab's boards: ``[{"name", "title", "n", "needs"}]``, ``main`` first."""
    out = []
    for b in registry.boards(h):
        cards = [c for v in cols.values() for c in v if c["board"] == b["name"]]
        out.append({"name": b["name"], "title": b.get("title") or "",
                    "n": len(cards) + sum(1 for x in broken if x["board"] == b["name"]),
                    "needs": sum(1 for c in cards if c["column"] == "Needs you")})
    return out


def overview(cols, broken, side, burn, now=None, coming=8):
    """The Overview (docs/overview.md) from ``board()``, ``side()`` and
    ``tokens.board()``: headline ``tiles``, the ``attention`` list, a row per
    board, what is running, and the next wake-ups."""
    now = now or clock.now()
    cards = [c for v in cols.values() for c in v]
    ago = lambda t: relative(-(now - t).total_seconds()).replace(" ago", "") if t else ""
    needs = cols["Needs you"]
    attention = [{"kind": "needs", "card": c} for c in needs]
    attention += [{"kind": "failed", "card": c} for c in cols["Failed"]]
    attention += [{"kind": "trouble", "card": c} for c in cards
                  if c["trouble"] and c["column"] != "Failed"]
    attention += [{"kind": "setup", "card": c} for c in cards if c["setup"]]
    waits = [c["root"]["updated"] for c in needs if c["root"] and c["root"].get("updated")]
    fails = [c["root"]["updated"] for c in cols["Failed"]
             if c["root"] and c["root"].get("updated")]
    rows = []
    for b in side:
        mine = [c for c in cards if c["board"] == b["name"]]
        counts = {k: [c for c in mine if c["column"] == k] for k in COLUMNS}
        packets = {}
        for c in mine:
            for st, k in c["counts"]:
                packets[st] = packets.get(st, 0) + k
        last = max((c["last_end"] for c in mine if c["last_end"]), default=None)
        tk = burn.get("boards", {}).get(b["name"]) or {}
        rows.append({
            "name": b["name"], "title": b["title"], "n": len(mine),
            "counts": [(k, len(counts[k]),
                        ", ".join(c["name"] for c in counts[k])) for k in COLUMNS],
            "packets": sum(packets.values()),
            "packets_title": ", ".join("%s %s" % (k, st) for st, k in
                                       sorted(packets.items(), key=lambda kv: str(kv[0]))),
            "broken": sum(1 for x in broken if x["board"] == b["name"]),
            "last_step": relative(-(now - last).total_seconds()) if last else "never",
            "tk": tk})
    total = burn.get("total") or {}
    return {
        "tiles": {
            "needs": len(needs), "oldest": ago(min(waits)) if waits else "",
            "running": len(cols["Running"]),
            "failed": len(cols["Failed"]) + sum(c["trouble"] for c in cards
                                                 if c["column"] != "Failed"),
            "newest_fail": ago(max(fails)) if fails else "",
            "spend_today": sum(c["spend_today"] for c in cards),
            "spend": total.get("cost_usd"),
            "quota": next((w for w in burn.get("quota") or [] if w["label"] == "Weekly"),
                          None),
        },
        "attention": attention, "boards": rows, "running": cols["Running"],
        # What runs next: the ready (due now), then the sleepers by wake time.
        "coming": (cols["Ready"] + cols["Sleeping"])[:coming],
        "more_coming": max(len(cols["Ready"]) + len(cols["Sleeping"]) - coming, 0),
        "next_wake": cols["Sleeping"][0]["root"]["next"].split(", ")[-1]
                     if cols["Sleeping"] and cols["Sleeping"][0]["root"] else "",
    }


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
    pkt = Packet(layout.run_dir(entry["path"], wpid))
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
            m, b = Packet(layout.run_dir(entry["path"], c)).load_status()
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
        "summary": body.strip(), "summary_html": md(body.strip()), "memento": memento, "files": files, "children": kids,
        "parent": parent, "steps": list(reversed(steps(pkt))), "running": running(pkt, now),
        "next": _next(meta, now, tz), "journal": pkt.journal().records[-200:],
        "notes": notes_mod.queued(pkt),
        "questions": questions.of_packet(pkt),
        "report": report(entry, pkt) if meta.get("state") in ("COMPLETED", "FAILED") else None,
    }


def md(text, link=None, lines=False):
    """Markdown to HTML, raw HTML in it escaped; None without markdown-it-py
    (the page then shows the text as it is). `link` maps each relative link
    target (no scheme, not absolute, not an anchor) to the href to use. With
    `lines`, blocks carry their source lines, for marking up (docs/doc-markup.md)."""
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return None
    from . import markup
    m = markup.plugin(_md(MarkdownIt), lines)
    if link is not None:
        def core(state):
            for tok in state.tokens:
                for t in tok.children or ():
                    href = t.attrGet("href") if t.type == "link_open" else None
                    if href and not href.startswith(("/", "#")) and ":" not in href.split("/")[0]:
                        t.attrSet("href", link(href))
        m.core.ruler.push("relative_links", core)
    return m.render(text or "")


def file_link(entry, wpid, rel_dir="", step=None):
    """A md() `link` that sends a relative target, taken from inside the packet
    folder `rel_dir`, to the report's file view (app.deliverable); with `step`,
    to that step's copy of the files."""
    base = "/p/%s/%s/file?path=" % (urlquote(entry["name"]), wpid)
    tail = "&step=" + urlquote(step) if step else ""

    def link(href):
        path, _, frag = href.partition("#")
        path = os.path.normpath(os.path.join(rel_dir, path)) if path else rel_dir
        return base + urlquote(path) + tail + ("#" + frag if frag else "")
    return link


def doc_link(entry, rel_dir=""):
    """A md() `link` for a project file (app.doc): relative to `rel_dir`."""
    base = "/p/%s/doc?path=" % urlquote(entry["name"])

    def link(href):
        path, _, frag = href.partition("#")
        path = os.path.normpath(os.path.join(rel_dir, path)) if path else rel_dir
        return base + urlquote(path) + ("#" + frag if frag else "")
    return link


def work_doc(entry, rel):
    """(real path, is_dir) of ``rel`` (``work/...``) in the project's ``work/``;
    None for anything outside it, a symlink out of it included."""
    if not isinstance(rel, str):
        return None
    want = os.path.normpath(rel or "work")
    parts = want.split(os.sep)
    if os.path.isabs(want) or ".." in parts or parts[0] != "work":
        return None
    root = os.path.realpath(os.path.join(entry["path"], "work"))
    p = os.path.realpath(os.path.join(entry["path"], want))
    if not (p == root or p.startswith(root + os.sep)) or not os.path.exists(p):
        return None
    return p, os.path.isdir(p)


def doc_listing(p, rel):
    """The folders and Markdown files in folder ``p`` (``rel``), for its page."""
    out = []
    for n in sorted(os.listdir(p)):
        if n.startswith("."):
            continue
        d = os.path.isdir(os.path.join(p, n))
        if d or n.lower().endswith((".md", ".markdown")):
            out.append({"name": n + ("/" if d else ""), "path": os.path.join(rel, n), "dir": d})
    return sorted(out, key=lambda x: (not x["dir"], x["name"].lower()))


def md_inline(text):
    """One line of Markdown (no paragraph wrapper) to HTML; None as md() is."""
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return None
    return _md(MarkdownIt).renderInline(text or "")


def _md(MarkdownIt):
    # Agents write GitHub-flavoured Markdown: tables and ~~strikethrough~~.
    return MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def report(entry, pkt, _seen=None, path=None, kids=None, step=None):
    """The completion report for the packet page (docs/completion-report.md):
    outcome, deliverables with links, the body's sections, and the children's
    reports, recursively. None if the packet has none. ``path``: another report
    of the packet's, relative to its folder (one a hand-off archived, for a task);
    ``kids``: only these children (the task's); ``step``: the step folder that wrote
    it, whose copy of each deliverable (``snap`` "copied") its links then open."""
    rep = (report_mod.of_packet(pkt) if path is None
           else report_mod.load(os.path.join(pkt.path, path)))
    if rep is None:
        return None
    meta, body = rep
    seen = _seen if _seen is not None else set()
    seen.add(pkt.wpid)
    base = "/p/%s/%s/file?path=" % (urlquote(entry["name"]), pkt.wpid)
    idx = report_mod.snapshot_index(os.path.join(pkt.steps_dir, step)) if step else None
    dl = []
    for d in meta.get("deliverables") or ():
        if not isinstance(d, dict):
            continue
        rel = os.path.normpath(str(d.get("path") or ""))
        snap = idx.get(rel) if idx is not None else None
        dl.append({"path": d.get("path"), "what": d.get("what"), "commit": d.get("commit"),
                   "abs": os.path.join(pkt.steps_dir, step, report_mod.SNAP, rel)
                   if snap == "copied" else os.path.join(pkt.path, d.get("path") or ""),
                   "snap": snap, "href": base + urlquote(d.get("path") or "")
                   + ("&step=" + urlquote(step) if snap == "copied" else "")})
    link = file_link(entry, pkt.wpid, step=step if idx else None)
    secs = []
    for name, text in report_mod.sections(body).items():
        secs.append({"name": name, "text": text, "html": md(text, link) if text else None})
    names = spawn_names(pkt)
    kids = []
    for w, state in report_mod._kids(pkt):
        if kids is not None and w not in kids:
            continue
        child = Packet(os.path.join(os.path.dirname(pkt.path), w))
        sub = None if w in seen else report(entry, child, seen)
        kids.append({"wpid": w, "short": w[:8], "name": names.get(w), "state": state,
                     "report": sub})
    outcome = (meta.get("outcome") or "").strip()
    return {"wpid": pkt.wpid, "outcome": outcome, "outcome_html": md_inline(outcome),
            "deliverables": dl, "sections": secs, "children": kids,
            "snapshot": idx is not None}


def deliverable(entry, wpid, rel, step=None):
    """(real path, is_dir) of a file the packet's report lists, or of one inside a
    folder it lists; None for anything else, so the page serves only results.
    With ``step``, the copy that step took when it wrote its report (report.snapshot)."""
    if not schema.is_wpid(wpid) or not isinstance(rel, str):
        return None
    pkt = Packet(layout.run_dir(entry["path"], wpid))
    want = os.path.normpath(rel)
    if os.path.isabs(want) or ".." in want.split(os.sep):
        return None
    if step is not None:
        if not isinstance(step, str) or schema.parse_step_dir(step) is None:
            return None
        sd = os.path.join(pkt.steps_dir, step)
        for top, how in (report_mod.snapshot_index(sd) or {}).items():
            if how == "copied" and (want == top or want.startswith(top + os.sep)):
                p = os.path.join(sd, report_mod.SNAP, want)
                if os.path.lexists(p):
                    rp = os.path.realpath(p)
                    if rp.startswith(os.path.realpath(sd) + os.sep):
                        return rp, os.path.isdir(rp)
        return None
    for d in _deliverables(pkt):
        top = os.path.normpath(str((d or {}).get("path") or ""))
        if top.split(os.sep)[0] not in report_mod.ROOTS:
            continue
        if want == top or want.startswith(top + os.sep):
            p = os.path.join(pkt.path, want)
            if os.path.exists(p):
                return os.path.realpath(p), os.path.isdir(p)
    return None


def _deliverables(pkt):
    """What the packet's reports list: its current one, then those hand-offs archived
    (``state/history/report-*.md``), so an earlier task's results stay reachable."""
    reps = [report_mod.of_packet(pkt)]
    hist = os.path.join(pkt.state_dir, "history")
    if os.path.isdir(hist):
        reps += [report_mod.load(os.path.join(hist, n)) for n in sorted(os.listdir(hist))
                 if n.startswith("report-") and n.endswith(".md")]
    for rep in reps:
        for d in (rep[0].get("deliverables") or ()) if rep else ():
            yield d


def task(entry, tasks, n):
    """The task page (docs/packet-page.md §3): root task ``n`` of ``tasks()``, its
    report (``report()``, or None), its sub-task rows, and the tasks either side."""
    roots = [t for t in tasks if t["kind"] == "task"]
    hit = [t for t in roots if t["n"] == n]
    if not hit:
        return None
    t = hit[0]
    rows, on = [], False
    for r in tasks:
        if r["kind"] == "task":
            on = r["n"] == n
        elif on:
            rows.append(r)
    pkt = Packet(layout.run_dir(entry["path"], t["wpid"]))
    rep = None
    if t["report"]:
        rep = report(entry, pkt, path=None if t["report"] == "report.md" else t["report"],
                     kids=set(t["kids"]), step=t["report_step"])
    return {"task": t, "report": rep, "children": rows,
            "text_html": md(t["text"]) if t["text"] else None,
            "prev": n - 1 if n > 1 else None, "next": n + 1 if n < len(roots) else None}


def state_file(entry, wpid, rel):
    """(real path, is_dir, editable) of a file or folder in the packet's ``state/``
    (docs/plan-tree.md), or None. Editable only while the runner leaves the
    packet alone (OWNED), since a step replaces ``state/`` when it commits."""
    if not schema.is_wpid(wpid) or not isinstance(rel, str):
        return None
    want = os.path.normpath(rel)
    if os.path.isabs(want) or ".." in want.split(os.sep) or want.split(os.sep)[0] != "state":
        return None
    pkt = Packet(layout.run_dir(entry["path"], wpid))
    p = os.path.realpath(os.path.join(pkt.path, want))
    top = os.path.realpath(pkt.state_dir)
    if not (p == top or p.startswith(top + os.sep)) or not os.path.exists(p):
        return None
    try:
        st = pkt.load_status()[0].get("state")
    except (OSError, frontmatter.FrontMatterError):
        st = None
    return p, os.path.isdir(p), st in OWNED and not os.path.isdir(pkt.pending_dir)


SETTING_KEYS = ("model", "step_timeout", "step_budget_usd", "step_context_tokens",
                "max_attempts", "carry_session", "permission_mode")


def settings(entry):
    """The project page's Settings panel: allowed tools and the editable keys."""
    from ..project import settings as resolved
    try:
        d = load_project(entry["path"])
        st = resolved(entry["path"])
    except (ProjectError, OSError):
        return None
    perm = d.get("permissions") or {}
    rows = []
    for k in SETTING_KEYS:
        own = perm.get(k) if k == "permission_mode" else d.get(k)
        eff = getattr(st, "step_timeout_s" if k == "step_timeout" else k, None)
        show = lambda v: ("true" if v else "false") if isinstance(v, bool) else v
        rows.append({"key": k, "value": show(own), "effective": show(eff)})
    return {"tools": list(perm.get("allowed_tools") or schema.PERMISSION_DEFAULTS["allowed_tools"]),
            "rows": rows}


def transcript(path, limit=TOOL_RESULT_MAX):
    """A stream-json transcript as display blocks: text, tool calls, results, the end.
    ``limit`` cuts each tool result (None: never)."""
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
                                       "id": c.get("id"), "input": c.get("input"),
                                       "text": json.dumps(c.get("input"), indent=2)})
                    elif ct == "tool_result":
                        r = c.get("content")
                        if isinstance(r, list):
                            r = "\n".join(x.get("text", "") for x in r if isinstance(x, dict))
                        r = str(r if r is not None else "")
                        cut = limit is not None and len(r) > limit
                        blocks.append({"kind": "tool_result", "error": bool(c.get("is_error")),
                                       "use_id": c.get("tool_use_id"),
                                       "text": r[:limit] + ("\n... (%d more characters)"
                                                            % (len(r) - limit) if cut else "")})
            elif t == "result":
                blocks.append({"kind": "result", "error": bool(e.get("is_error")),
                               "text": "%s: %s turns, $%.4f, %.1fs" % (
                                   e.get("subtype"), e.get("num_turns"),
                                   e.get("total_cost_usd") or 0,
                                   (e.get("duration_ms") or 0) / 1000.0)})
    return blocks


def step(entry, wpid, dirname, view="blocks"):
    """Everything the step viewer shows, the transcript as blocks or (``view``
    "log") as a log. None if there is no such step folder."""
    if not schema.is_wpid(wpid) or schema.parse_step_dir(dirname) is None:
        return None
    pkt = Packet(layout.run_dir(entry["path"], wpid))
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
        "notes": notes_mod.of_step(sd, pkt, pkt.journal().records),
        "blocks": transcript(os.path.join(sd, "transcript.jsonl")) if view != "log" else None,
        "log": log(os.path.join(sd, "transcript.jsonl")) if view == "log" else None,
        "prev": dirs[i - 1] if i > 0 else None,
        "next": dirs[i + 1] if i + 1 < len(dirs) else None,
        "fork": "cd %s && claude --resume %s --fork-session" % (
            shlex.quote(pkt.path), session)
        if session else None,
    }


# --- the live view (docs/interaction.md I6) ------------------------------------

FEED_MAX = 80               # newest events shown in the live feed
_BOX = __import__("re").compile(r"^(\s*)[-*]\s+\[([ xX>+\-~])\]\s+(.*)$")
BOX_STATE = {" ": "pending", "x": "done", "X": "done", ">": "active", "+": "added",
             "-": "deferred", "~": "partial"}


def _one_line(text, n=160):
    line = " ".join((text or "").split())
    return line if len(line) <= n else line[:n - 1] + "…"


def _tool_label(name, inp):
    """A tool call as one line: the command, the path or the pattern."""
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        return inp.get("description") or inp.get("command") or "", inp.get("command") or ""
    for k in ("file_path", "path", "pattern", "url", "query"):
        if inp.get(k):
            return str(inp[k]), ""
    return "", ""


def activity(path):
    """The transcript as a feed: one event per model message, tool call and result.

    Returns ``{"events", "context", "output_tokens", "calls", "todos", "pending"}``:
    ``context`` is the last call's context size, ``todos`` the last TodoWrite
    list, and ``pending`` the tool call still waiting for its result, if any.
    """
    out = {"events": [], "context": None, "output_tokens": 0, "calls": 0, "todos": None,
           "pending": None, "ended": None}
    uses = {}
    try:
        fp = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fp:
        for line in fp:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            if t == "assistant":
                m = e.get("message") or {}
                u = m.get("usage") or {}
                if u:
                    out["calls"] += 1
                    out["context"] = sum(u.get(k) or 0 for k in (
                        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                    out["output_tokens"] += u.get("output_tokens") or 0
                for c in m.get("content") or ():
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "text" and c.get("text", "").strip():
                        out["events"].append({"kind": "text", "label": _one_line(c["text"], 400)})
                    elif c.get("type") == "tool_use":
                        name, inp = c.get("name"), c.get("input")
                        if name == "TodoWrite" and isinstance(inp, dict):
                            out["todos"] = [{"content": x.get("content"),
                                             "status": x.get("status"),
                                             "active": x.get("activeForm")}
                                            for x in inp.get("todos") or () if isinstance(x, dict)]
                        label, detail = _tool_label(name, inp)
                        ev = {"kind": "tool", "name": name, "label": _one_line(label),
                              "detail": _one_line(detail, 300) if detail != label else "",
                              "result": None, "error": False}
                        out["events"].append(ev)
                        uses[c.get("id")] = ev
            elif t == "user":
                for c in (e.get("message") or {}).get("content") or ():
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        ev = uses.pop(c.get("tool_use_id"), None)
                        if ev is None:
                            continue
                        r = c.get("content")
                        if isinstance(r, list):
                            r = "\n".join(x.get("text", "") for x in r if isinstance(x, dict))
                        lines = [ln for ln in str(r or "").splitlines() if ln.strip()]
                        ev["error"] = bool(c.get("is_error"))
                        ev["result"] = _one_line(lines[-1] if lines else "(no output)", 200)
            elif t == "result":
                out["ended"] = {"error": bool(e.get("is_error")), "cost": e.get("total_cost_usd"),
                                "turns": e.get("num_turns")}
    if uses:
        out["pending"] = list(uses.values())[-1]
    out["events"] = out["events"][-FEED_MAX:]
    return out


LOG_RESULT_MAX = 20000      # characters of one tool result in the log view


def log(path, limit=LOG_RESULT_MAX):
    """The transcript as a console log, the way CI shows one.

    Returns ``{"groups", "lines"}``. Each group is ``{"id", "kind", "title",
    "lines", "error", "done"}``: a tool call with its input and output
    (``kind`` "tool"), the model's text ("text", shown without a header),
    thinking, or a session line ("meta"). ``lines`` are ``(n, text, cls)``,
    numbered through the whole log; a group with a title takes a number
    for its header line, as a CI log's group line does.
    """
    groups, uses = [], {}
    pkt = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(path)))) + os.sep
    for b in transcript(path, limit):
        k = b["kind"]
        if k == "tool_use":
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            label, _ = _tool_label(b["name"], inp)
            if b["name"] == "Bash" and inp.get("command"):
                body = ["$ " + ln if i == 0 else "  " + ln
                        for i, ln in enumerate(inp["command"].splitlines())]
            else:
                body = _input_lines(inp, skip=label, pkt=pkt)
            label = label[len(pkt):] if label.startswith(pkt) else label
            g = {"kind": "tool", "title": "%s  %s" % (b["name"], _one_line(label, 200)),
                 "in": body, "out": [], "error": False, "done": False}
            groups.append(g)
            uses[b.get("id")] = g
        elif k == "tool_result":
            g = uses.pop(b.get("use_id"), None)
            if g is None:
                g = {"kind": "tool", "title": "result", "in": [], "error": False}
                groups.append(g)
            g["out"] = b["text"].splitlines() or ["(no output)"]
            g["error"], g["done"] = b["error"], True
        elif k == "thinking":
            groups.append({"kind": "thinking", "title": "thinking", "in": [],
                           "out": b["text"].splitlines(), "done": True})
        elif k in ("init", "result"):
            groups.append({"kind": "meta", "title": None, "in": [], "error": b.get("error"),
                           "out": ["%s: %s" % ("session" if k == "init" else "end", b["text"])]})
        else:
            groups.append({"kind": "text", "title": None, "in": [],
                           "out": b["text"].splitlines()})
    n = 0
    for i, g in enumerate(groups, 1):
        g["id"] = "g%d" % i
        if g["title"]:
            n += 1
            g["n"] = n
        lines = []
        for cls, src in (("cmd", g.pop("in")), ("err" if g.get("error") else "", g.pop("out"))):
            for ln in src:
                n += 1
                lines.append((n, ln, cls))
        g["lines"] = lines
    return {"groups": groups, "lines": n}


def _input_lines(inp, skip, pkt):
    """A tool's input as ``key: value`` lines, without the value in the title;
    a multi-line string goes under its key, indented."""
    out = []
    for key, v in inp.items():
        if isinstance(v, str) and v == skip:
            continue
        if isinstance(v, str) and "\n" in v:
            out.append("%s:" % key)
            out += ["  " + ln for ln in v.splitlines()]
        else:
            v = v if isinstance(v, str) else json.dumps(v)
            out.append("%s: %s" % (key, v[len(pkt):] if v.startswith(pkt) else v))
    return out


def log_text(lg):
    """``log()`` as plain text, for download."""
    out = []
    for g in lg["groups"]:
        if g["title"]:
            out.append("%s %s%s" % ("▶", g["title"], "  [error]" if g.get("error") else ""))
        out += [t for _, t, _ in g["lines"]]
    return "\n".join(out) + "\n"


def outline(pkt):
    """Checklist items from the packet's outline, newest copy first (.pending/ while a
    step runs). ``state/outline.md``, else the first state ``.md`` with a checklist."""
    cands = []
    for base in (os.path.join(pkt.pending_dir, "state"), pkt.state_dir):
        cands.append(os.path.join(base, "outline.md"))
    for base in (os.path.join(pkt.pending_dir, "state"), pkt.state_dir):
        try:
            cands += [os.path.join(base, n) for n in sorted(os.listdir(base)) if n.endswith(".md")]
        except OSError:
            pass
    for p in cands:
        text = _read(p)
        if not text:
            continue
        items = []
        for ln in text.splitlines():
            m = _BOX.match(ln)
            if m:
                items.append({"depth": len(m.group(1).expandtabs(2)) // 2,
                              "state": BOX_STATE[m.group(2)], "text": m.group(3).strip()})
        if len(items) >= 2:
            cur = next((i for i in items if i["state"] == "active"), None) or \
                next((i for i in items if i["state"] in ("pending", "added")), None)
            if cur:
                cur["current"] = True
            rel = os.path.relpath(p, pkt.path)
            return {"file": rel, "entries": items,
                    "done": sum(i["state"] == "done" for i in items), "total": len(items)}
    return None


def live(entry, wpid, now=None, view="feed"):
    """The live view of a packet: its newest step's feed (or, with ``view``
    "log", its log), the outline and the steps so far."""
    now = now or clock.now()
    if not schema.is_wpid(wpid):
        return None
    pkt = Packet(layout.run_dir(entry["path"], wpid))
    if not os.path.isdir(pkt.path):
        return None
    try:
        meta, _ = pkt.load_status()
    except (OSError, frontmatter.FrontMatterError):
        meta = {}
    all_steps = steps(pkt)
    run = running(pkt, now)
    cur = all_steps[-1] if all_steps else None
    tpath = os.path.join(pkt.steps_dir, cur["dir"], "transcript.jsonl") if cur else None
    feed = activity(tpath) if cur else None
    done = [s for s in all_steps if s["outcome"] == "committed"]
    return {
        "wpid": wpid, "short": wpid[:8], "meta": meta, "running": run, "step": cur,
        "feed": feed, "outline": outline(pkt), "questions": questions.of_packet(pkt),
        "history": list(reversed(done))[:30], "notes": notes_mod.queued(pkt),
        "procs": processes(pkt, run, cur),
        "log": log(tpath) if cur and view == "log" else None,
        "elapsed": _secs_short((now - run["since"]).total_seconds())
        if run and run.get("since") else None,
    }


def processes(pkt, run, cur):
    """The running step's processes (``procs.of_step``); ``{"remote": host}``
    when it runs on another machine; None when no step is running."""
    if not run or not cur:
        return None
    if run.get("host") != socket.gethostname():
        return {"remote": run.get("host")}
    try:
        pid = int((_read(os.path.join(pkt.steps_dir, cur["dir"], "model.pid")) or "").strip())
    except ValueError:
        pid = None          # no PID file: find them by their WPK_* tags alone
    return procs_mod.of_step(pid, pkt.wpid, run.get("step"))


def _secs_short(s):
    s = int(max(s, 0))
    return "%dm %02ds" % (s // 60, s % 60) if s >= 60 else "%ds" % s


# --- Compose (docs/dash-tasks.md §4) -------------------------------------------------

STAGES = (("project", "Project"), ("work", "Work repos"), ("inputs", "Inputs"),
          ("instruction", "Instruction"), ("limits", "Limits"))
LEVEL_RANK = {"ok": 0, "info": 1, "warn": 2, "missing": 3}
OWNED = ("COMPLETED", "NEEDS_INPUT", "PAUSED", "FAILED")


def _inputs(state_dir):
    from ..prompt import FILE_MAX
    out = []
    if not os.path.isdir(state_dir):
        return out
    for dp, dns, fns in os.walk(state_dir):
        dns.sort()
        for f in sorted(fns):
            p = os.path.join(dp, f)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            out.append({"rel": os.path.relpath(p, state_dir), "size": size,
                        "shown": size <= FILE_MAX})
    return out


def _carry_estimate(pkt, meta):
    """The last committed step's context peak: what a carried session rereads."""
    n = meta.get("step") or 0
    if n < 1:
        return None
    m = _json(os.path.join(pkt.step_dir(n), "meta.json")) or {}
    if not m.get("session_id"):
        return None
    return {"tokens": (m.get("context") or {}).get("peak"), "model": m.get("model"),
            "end": _ts(m.get("end"))}


def compose(entry, now=None):
    """Everything the Compose page shows for a project's root, or None.

    ``mode`` is ``setup`` (held for setup, nothing has run: the instruction is
    ``prompt.md``) or ``next`` (it has run: the instruction is the draft of the
    next batch). ``owned``: you may change it now (not the runner's).
    """
    from .. import actions, executor, setup, workspace
    from ..project import held_for_setup
    now = now or clock.now()
    try:
        tg = setup.target(entry["path"])
    except (setup.SetupError, OSError):
        return None
    meta = tg.status()
    if meta is None:
        return None
    run = running(tg.packet, now)
    state = meta.get("state")
    owned = run is None and state in OWNED
    mode = "next" if tg.started() else "setup"
    checks = setup.readiness(tg, tools=False)
    if mode == "next":        # the setup's instruction check is about prompt.md, long gone
        checks = [c for c in checks if c.group in ("work", "limits")]
        for repo, lines in sorted(workspace.dirty(tg.packet).items()):
            checks.append(setup.Check(
                "next.dirty.%s" % repo, "work", "missing",
                "work/%s has uncommitted changes" % repo,
                "The next step starts from a clean tree: commit or stash them (%d paths)."
                % len(lines),
                ["git -C %s add -A && git -C %s commit -m 'handoff: by hand'"
                 % ((setup.tilde(os.path.join(tg.packet_work, repo)),) * 2)]))
    groups = []
    for key, title in STAGES:
        cs = [c for c in checks if c.group == key]
        if not cs:
            continue
        worst = max(cs, key=lambda c: LEVEL_RANK.get(c.level, 0)).level
        groups.append({"key": key, "title": title, "level": worst, "checks": cs})
    records = tg.packet.journal().records
    if mode == "setup":
        text, where = setup.instruction(tg)
        draft = None
    else:
        draft = actions.load_draft(tg.packet)
        text, where = (draft or {}).get("instruction", ""), "draft"
    last = [r for r in records if r.get("type") == "handoff" and r.get("instruction")]
    return {
        "tg": tg, "meta": meta, "state": state, "running": run, "owned": owned,
        "mode": mode, "held_for_setup": held_for_setup(meta),
        "groups": groups, "missing": len(setup.missing(checks)),
        "instruction": text, "where": where, "draft": draft,
        "last_instruction": last[-1]["instruction"] if last else
        (_read(tg.prompt_path) or ""),
        "templates": setup.TEMPLATES,
        "inputs": _inputs(tg.state),
        "state_where": "the project's state/" if mode == "setup" else "the root packet's state/",
        "batch": executor.batch_of(records), "summary": tg.packet.load_status()[1].strip(),
        "archive_default": state == "COMPLETED",
        "carry": _carry_estimate(tg.packet, meta) if mode == "next" else None,
        "shell_dir": tg.proj if mode == "setup" else tg.packet.path,
    }



def model_choices(h=None):
    """For the New task form: ``{harness: [{"id", "label"}]}``. Each harness's own
    list, then the models registered projects use and the configured default
    (those are known to work here). The form also takes a model typed in."""
    from .. import harness as harness_mod
    try:
        cfg = registry.load_config(h)
    except registry.ConfigError:
        cfg = dict(schema.CONFIG_DEFAULTS)
    out = {}
    for name in harness_mod.names():
        out[name] = [{"id": m, "label": lbl} for m, lbl in harness_mod.get(name).models()]
    used = [(cfg["harness"], cfg["model"], "the default")]
    for e in archived.entries(h):
        try:
            d = load_project(e["path"])
        except (ProjectError, OSError):
            continue
        used.append((d.get("harness") or cfg["harness"], d.get("model") or cfg["model"],
                     "used by %s" % e["name"]))
    for hn, m, why in used:
        lst = out.setdefault(hn, [])
        hit = [x for x in lst if x["id"] == m]
        if hit:
            if why == "the default":
                hit[0]["label"] += " (the default)"
        elif m:
            lst.append({"id": m, "label": "%s (%s)" % (m, why)})
    return out
