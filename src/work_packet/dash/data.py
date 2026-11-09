"""What the board shows, read straight from the files (no database).

Every function here takes paths and returns plain dicts and lists, so the
board can be tested without a web server.
"""

import json
import os
import shlex
import socket
from datetime import datetime, timedelta
from urllib.parse import quote as urlquote

from .. import (clock, frontmatter, lease as lease_mod, notes as notes_mod, procs as procs_mod,
               questions, registry, report as report_mod, schema, stats)
from .. import archived, layout, planning, views
from ..packet import Packet
from ..project import ProjectError, load_project
from ..views import packets, relative

# Board columns, in display order: by whose move it is (docs/collaboration.md §8.2).
COLUMNS = views.COLUMNS
# Each column's colour (a CSS variable of base.html) and its card's class.
COLUMN_COLOUR = {"Inbox": "muted", "Needs you": "NEEDS_INPUT", "Working: you": "RUNNABLE",
                 "Working: agent": "running", "Waiting": "SLEEPING", "Parked": "PAUSED",
                 "Done": "COMPLETED"}
COLUMN_CLASS = {"Inbox": "Inbox", "Needs you": "Needs", "Working: you": "You",
                "Working: agent": "Agent", "Waiting": "Waiting", "Parked": "Parked",
                "Done": "Done"}

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
            "cost_basis": stats.basis_of(meta), "worker": meta.get("worker") or "agent",
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


def _intent(body):
    """The ``Next:`` line of a status body (a checkpoint's), or None."""
    from ..checkpoint import next_of
    return next_of(body)


def intent(pkt, row):
    """What comes next, for a card's second line (docs/session-checkpoint.md §5):
    the status's ``Next:`` line, else what the next autonomous step starts from
    (the memento's first line) while the runner has it."""
    if row.get("intent"):
        return row["intent"]
    if row.get("state") not in ("RUNNABLE", "SLEEPING") or row.get("taken_by"):
        return None
    try:
        _, body = pkt.load_memento()
    except (OSError, frontmatter.FrontMatterError):
        return None
    return _first_line(body) or None


def since_checkpoint(entry, row, tz, now):
    """The card's "as of" marker: ``{"as_of", "active", "live", "edits"}``, where
    ``active`` says how long ago a session of the packet was last active after
    its status was written (None: none was)."""
    if not row or not row.get("updated"):
        return None
    from .. import ide_sessions, registry
    out = {"as_of": _local(row["updated"], tz)[-5:] if row["updated"].astimezone(tz).date()
           == now.astimezone(tz).date() else _local(row["updated"], tz),
           "active": None, "live": False, "edits": 0}
    try:
        got = ide_sessions.packet_activity(registry.home(), entry["name"], row["wpid"],
                                           since=row["updated"].timestamp())
    except Exception:              # the marker is a nicety; never fail the board for it
        got = None
    if got:
        out.update(active=relative(min(0, got["active_t"] - now.timestamp())), live=got["live"],
                   edits=got["edits"])
    return out


def tree(entry, now=None):
    """Every packet of a project, in tree order, with what a board row needs."""
    now = now or clock.now()
    tz = _zone(entry["path"])
    from ..actions import resumable
    from ..executor import stopped
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
            "intent": _intent(body), "updated": _ts(meta.get("updated")), "wake_at": _ts(meta.get("wake_at")),
            "stopped": _ts(meta.get("stopped")) if stopped(meta) else None,
            "seen": _ts(meta.get("seen")),
            "pausing": _pausing(pkt) is not None, "resumable": resumable(meta),
            "taken_by": meta.get("taken_by"), "taking": _taking(pkt),
            "waiting_on": meta.get("waiting_on"),
            # the person's facts (docs/collaboration.md §4.1); views derive the rest
            "lifecycle": meta.get("lifecycle"), "autonomy": meta.get("autonomy"),
            "review": meta.get("review"), "owner": meta.get("owner"),
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
    from ..checkpoint import BY_HAND, next_of
    root = nodes[0]
    recs = Packet(root["path"]).journal().records
    batch, of, why, ended, reports, spawned = 1, {}, {}, {}, {}, {}
    worker, fresh = {}, False       # fresh: a task a checkpoint began, with no step yet
    for r in recs:
        t = r.get("type")
        if t == "step-start" and isinstance(r.get("step"), int):
            of[r["step"]] = batch
            worker[r["step"]] = r.get("worker")
            fresh = False
        elif t == "commit-begin":
            d = r.get("decision") or {}
            for sp in d.get("spawn") or ():
                if sp.get("wpid"):
                    spawned[sp["wpid"]] = of.get(r.get("step"), batch)
            nxt = next_of(d.get("summary"))
            if nxt and (d.get("worker") or worker.get(r.get("step"))) in BY_HAND:
                ended[batch] = "COMPLETED"      # your checkpoint set what comes next (G5)
                batch += 1
                why[batch], fresh = nxt, True
        elif t == "handoff":
            if r.get("report"):
                reports[batch] = r["report"]
            if "instruction" in r:
                if not fresh:
                    ended[batch] = r.get("from")
                    batch += 1
                why[batch], fresh = r.get("instruction"), False
    subtrees, cur = {}, None
    for n in nodes[1:]:
        if n["depth"] == 1:
            cur = subtrees.setdefault(spawned.get(n["wpid"], batch), [])
        if cur is not None:
            cur.append(dict(n, kind="child"))
    out = []
    if (batch == 1 and not why and not root["steps"] and not root["running"] and not subtrees
            and not (_read(os.path.join(entry["path"], "prompt.md")) or "").strip()):
        return []                   # just made, nothing asked of it yet: no task
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


def waits(nodes):
    """What a project's packets wait on that nobody is working on (docs/waiting-v1.md
    §5.3): ``stalled``, requests out whose delegate is paused, failed or asking;
    ``stuck``, sleeping packets with a stopped child they have not been woken for."""
    from .. import requests, waiting
    ids = {n["wpid"] for n in nodes}
    stalled = []
    for e in requests.entries():
        if e["state"] != "open" or e["from"]["wpid"] not in ids:
            continue
        d = requests.delegate_state(e)
        if d and d[0] in requests.STALLED:
            stalled.append({"id": e["id"], "title": e["title"], "project": e["to"]["project"],
                            "wpid": e["to"]["wpid"], "state": d[0], "step": d[1],
                            "reason": d[2]})
    stuck = []
    for n in nodes:
        if n["state"] != "SLEEPING":
            continue
        pkt = Packet(n["path"])
        try:
            meta, _ = pkt.load_status()
        except (OSError, frontmatter.FrontMatterError):
            continue
        kids = waiting.unseen_stops(pkt, meta) if meta.get("children") else []
        if kids:
            stuck.append({"wpid": n["wpid"], "short": n["short"], "name": n["name"],
                          "children": [{"short": w[:8], "state": st} for w, st in kids]})
    return stalled, stuck


def _hooks(entry):
    """The Claude Code hooks in a packet folder (docs/collaboration.md §4.3):
    "installed", "missing", "modified" or "unreadable"; None for the legacy layout."""
    from .. import sessionhooks
    folder = sessionhooks.packet_folder(entry)
    return sessionhooks.status(folder) if folder and os.path.isdir(folder) else None


def _ide_cfg():
    try:
        return registry.load_config_file().get("ide") or {}
    except Exception:                   # noqa: BLE001: a bad config is reported elsewhere
        return {}


def session_items(entry):
    """The project's Claude sessions that need you (``attention.session_items``)."""
    from .. import attention
    try:
        return attention.session_items(entry["path"], None, _ide_cfg().get("idle_escalate")
                                       or attention.IDLE_ESCALATE_S)
    except OSError:
        return []


def glance(c):
    """A card at a glance (docs/collaboration.md §7.10): ``status.json``, and the
    line ``wpk statusline`` prints. ``needs``: what waits on you there (its own
    question, failure or review, the sessions that need you, the jobs that ended)."""
    b = c["ball"]
    needs = (1 if b["kind"] in views.NEEDS_YOU else 0) + len(c.get("sessions") or ()) + \
        len(c.get("job_items") or ())
    return {"name": c["name"], "ball": b, "driver": c.get("driver"), "column": c["column"],
            "needs": needs, "jobs": len(c.get("jobs") or ()),
            "url": "/p/%s" % urlquote(c["name"])}


def job_state(entry):
    """The project's running jobs, and its attention items for jobs that ended
    and you have not opened (``jobs.items``)."""
    from .. import jobs
    try:
        return jobs.live(entry["path"]), jobs.items(entry["path"])
    except OSError:
        return [], []


def present(entry, now=None):
    """The project's live presence records (docs/collaboration.md §4.2), by the
    wall clock (``now`` is not used: records are written in real time, as leases are)."""
    from .. import presence
    try:
        return presence.live(entry["path"], None, _ide_cfg().get("presence_ttl")
                             or presence.TTL_S)
    except OSError:
        return []


def _milestones_of(entry):
    from .. import milestones
    try:
        return milestones.of_board(registry.board_of(
            entry, [b["name"] for b in registry.boards()]))
    except Exception:                   # noqa: BLE001
        return []


def _actuals(entry):
    """For the packet page's Now line: ``{"text", "over", "estimate"}`` (plan F3a)."""
    try:
        a = planning.actuals(entry)
    except Exception:                   # noqa: BLE001: never breaks the page
        return None
    text = planning.actuals_text(a)
    return {"text": text, "over": a["over"]} if text else None


def card(entry, now=None, nodes=None):
    """One project's card on the board. ``nodes``: its ``tree()``, if already read."""
    now = now or clock.now()
    tz = _zone(entry["path"])
    nodes = tree(entry, now) if nodes is None else nodes
    root = nodes[0] if nodes else None
    live = [n for n in nodes if n["running"]]
    facts = root or {"state": "?"}
    lease = live[0]["running"] if live else None
    here = present(entry, now)
    sessions = session_items(entry)
    plan = planning.get(entry)
    running_jobs, job_items = job_state(entry)
    column = views.column(facts, lease, here, running_jobs)
    ball = views.ball(facts, lease, here, running_jobs)
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
    stalled, stuck = waits(nodes)
    held = None
    if root and root["state"] == "PAUSED" and root.get("reason") == "setup" and not live:
        held = setup_summary(entry)
    unread = None
    # An archived project (its run gone, read from the history store) is never new.
    if root and root.get("stopped") and not live and not archived.is_archived(entry) and not any(
            n["state"] in ("RUNNABLE", "SLEEPING") for n in nodes):
        at = max(t for t in (root["stopped"], last) if t)
        if not root.get("seen") or root["seen"] < at:
            unread = finished(entry, nodes, at, tz, now)
    nxt = since = None
    if root and root.get("state") != "?":
        nxt = intent(Packet(root["path"]), root)
        since = since_checkpoint(entry, root, tz, now)
    return {
        "name": entry["name"], "column": column, "root": root, "running": run,
        "draft": _draft(root), "split_of": _split_of(entry),
        "css": COLUMN_CLASS[column] + (" Failed" if ball["kind"] == "failure" else ""),
        "ball": ball, "driver": views.driver(facts, lease, here), "present": here,
        "jobs": running_jobs, "job_items": job_items,
        "sessions": sessions,
        # your planning fields (docs/collaboration.md §9.2)
        "plan": plan, "due": planning.due_text(plan),
        "rot": planning.rotting(plan, max((t.timestamp() for t in (last, (root or {}).get(
            "updated")) if t), default=None)) if views.lifecycle(facts) == "open" else None,
        "lifecycle": views.lifecycle(facts), "autonomy": views.autonomy(facts),
        "setup": held, "intent": nxt, "since": since,
        "counts": sorted(counts.items(), key=lambda kv: str(kv[0])),
        "packets": len(nodes), "trouble": len(trouble),
        "stalled": stalled, "stuck": stuck,
        "spend_total": sum(n["cost_usd"] for n in nodes), "spend_today": spend_today,
        "last_step": relative(-(now - last).total_seconds()) if last else "never",
        "last_end": last,
        "finished": _local(root["updated"], tz) if root and root.get("updated") else "",
        "unread": unread,
        # Pause and Resume for the project (docs/pause-v1.md): how many packets each acts on.
        "pausable": sum(1 for n in nodes if n["state"] in ("RUNNABLE", "SLEEPING")
                        and not n.get("pausing")),
        "pausing": sum(1 for n in nodes if n.get("pausing")),
        "resumable": sum(1 for n in nodes if n.get("resumable")),
        # In the studio (docs/studio-plan.md P0.1): who has taken which packets.
        "studio": sorted({n["taken_by"] or n["taking"] for n in nodes
                          if n.get("taken_by") or n.get("taking")}),
    }


def finished(entry, nodes, at, tz, now):
    """A stopped project no one has looked at since (docs/overview-recent.md §1):
    ``kind`` done or stopped, ``at`` (the root's stop, or the tree's last step
    end if later), ``outcome`` (the report's, else the reason), the last task's
    ``cost_usd`` (its children's too) and the pull request, if one was opened."""
    from .. import pr
    root = nodes[0]
    rows = tasks(entry, nodes)
    n = max((r["n"] for r in rows if r["kind"] == "task"), default=1)
    cost, on = 0.0, False
    for r in rows:                  # the last task and the children it spawned
        on = r["n"] == n if r["kind"] == "task" else on
        cost += r["cost_usd"] if on else 0.0
    done = root["state"] == "COMPLETED"
    return {"kind": "done" if done else "stopped", "at": at, "local": _local(at, tz),
            "ago": relative(-(now - at).total_seconds()),
            "outcome": root["summary"] if done else root.get("reason") or "",
            "cost_usd": cost, "task": n, "pr": pr.recorded(entry)}


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
    deadlines([c for v in cols.values() for c in v], h, now)
    # Sleepers soonest first; the rest by name.
    far = now + timedelta(days=36500)
    for c in cols.values():
        c.sort(key=lambda k: ((k["root"] or {}).get("wake_at") or far, k["name"]))
    return cols, broken


def deadlines(cards, h=None, now=None):
    """Each open card's effective due date (its own, else its milestone's), and
    for those with one, a forecast and at risk (docs/collaboration.md §9.3, plan
    F3b): ``due_eff``, ``due_kind``, ``milestone``, ``forecast`` (with ``text``)
    and ``at_risk``."""
    from .. import forecast, milestones
    now = now or clock.now()
    now_t = now.timestamp()
    today = now.astimezone().date()
    done = {c["name"] for c in cards if c.get("lifecycle") == "done"}
    ms = {}
    for c in cards:
        c.update({"due_eff": None, "due_kind": None, "milestone": None, "forecast": None,
                  "at_risk": None})
        plan = c.get("plan") or {}
        b = c.get("board") or registry.DEFAULT_BOARD
        if plan.get("milestone") and b not in ms:
            ms[b] = milestones.of_board(b, h)
        due, kind, m = milestones.effective_due(plan, b, h, ms.get(b, []))
        c["milestone"] = m
        if not due or c.get("lifecycle") != "open":
            continue
        c["due_eff"], c["due_kind"] = due, kind
        if not plan.get("due"):
            c["due"] = "%s %s" % (m["name"], planning.due_text({"due": due}, today))
        e = registry.get(c["name"], h)
        if e is None:
            continue
        try:
            fc = forecast.forecast(e, c, now_t, h)
        except Exception:               # noqa: BLE001: a forecast never breaks the board
            fc = None
        if fc:
            fc["text"] = forecast.range_text(fc, today)
        c["forecast"] = fc
        c["at_risk"] = forecast.at_risk(due, kind, fc, c, today, now_t, done)


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


def risk_item(c):
    """A card at risk as an attention item (plan F3b): keyed by its due date and
    the kind of risk, so a new date or reason brings a snoozed one back."""
    from .. import forecast
    return {"type": "atrisk", "source": "%s:%s" % (c["due_eff"], c["at_risk"].split()[0]),
            "since": 0, "text": forecast.decision_text(c["name"], c.get("due") or "",
                                                       c.get("forecast"), "at risk: " +
                                                       c["at_risk"])}


def attention_key(a):
    """A Needs-you row's identity for a snooze (``attention.key``): its kind, its
    project and packet, and when its cause began, so anything new brings it back."""
    from .. import attention
    c = a["card"]
    if a.get("item"):
        return attention.key(c["name"], a["item"])
    root = c.get("root") or {}
    at = (c.get("unread") or {}).get("at") if a["kind"] in ("done", "stopped") else \
        root.get("updated")
    sub = (a.get("req") or {}).get("id") or (a.get("pkt") or {}).get("wpid") or ""
    return attention.key(c["name"], {"type": a["kind"], "source": sub,
                                     "since": at.timestamp() if at else 0})


def session_spend(home, now=None):
    """Today's tokens in the Claude and Codex sessions people drive (docs/collaboration.md
    §7.5), and their cost where a model profile has a price: ``{"tokens", "usd"}``.
    Budgets stay on the runner's spend; this is shown beside it."""
    import time
    from .. import cost, ide_sessions, profiles
    now = time.time() if now is None else now
    start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0,
                                                microsecond=0).timestamp()
    tokens, usd, priced_any = 0, 0.0, False
    try:
        profs = profiles.load()
    except Exception:                   # noqa: BLE001: a bad profile file: tokens only
        profs = []
    for r in ide_sessions.cached_records(home):
        if (r.get("last_activity_t") or 0) < start or not r.get("usage_reported"):
            continue
        u = r.get("usage") or {}
        tokens += ide_sessions.total(u)
        try:
            prof = profiles.select(profs, r.get("harness"), r.get("model"))
        except Exception:               # noqa: BLE001: no profile for it
            prof = None
        got = cost.priced(u, getattr(prof, "price", None)) if prof else None
        if got is not None:
            usd, priced_any = usd + got, True
    return {"tokens": tokens, "usd": usd if priced_any else None}


def backlog(cols):
    """The Backlog (docs/collaboration.md §9): open projects by your priority, then
    rank, then name; ``{"now": [card], ..., "rot": [card]}``."""
    out = {p: [] for p in planning.PRIORITIES}
    for col, cards in cols.items():
        if col == "Done":
            continue
        for c in cards:
            out[c["plan"]["priority"]].append(c)
    for p in out:
        out[p].sort(key=lambda c: (c["plan"]["rank"] if isinstance(c["plan"]["rank"], int)
                                   else 1 << 30, c["name"]))
    out["rot"] = [c for cards in cols.values() for c in cards if c.get("rot")]
    return out


def since_last(cards, since, per=3, cap=30):
    """Since you were last here (docs/collaboration.md §8.1): each project's events
    after ``since`` (epoch), newest first, ``per`` at most per project; ``[{"card",
    "events", "more"}]``, the most recently active project first."""
    out = []
    for c in cards:
        if not c.get("root") or c["root"].get("state") == "?":
            continue
        evs = views.timeline(Packet(c["root"]["path"]), since=since, limit=per + 20)
        if evs:
            out.append({"card": c, "events": evs[:per], "more": len(evs) - per
                        if len(evs) > per else 0, "t": evs[0]["t"]})
    out.sort(key=lambda x: x["t"], reverse=True)
    return out[:cap]


def overview(cols, broken, side, burn, now=None, coming=8):
    """The Overview (docs/overview.md) from ``board()``, ``side()`` and
    ``tokens.board()``: headline ``tiles``, the ``attention`` list, a row per
    board, what is running, and the next wake-ups."""
    now = now or clock.now()
    cards = [c for v in cols.values() for c in v]
    ago = lambda t: relative(-(now - t).total_seconds()).replace(" ago", "") if t else ""
    needs = cols["Needs you"]
    # Questions and failures; finished work to review comes in below, with the rest
    # finished since anyone looked.
    kind = {"question": "needs", "failure": "failed"}
    attention = [{"kind": kind[c["ball"]["kind"]], "card": c} for c in needs
                 if c["ball"]["kind"] in kind]
    attention += [{"kind": "trouble", "card": c} for c in cards
                  if c["trouble"] and c["ball"]["kind"] != "failure"]
    attention += [{"kind": "stalled", "card": c, "req": r} for c in cards
                  for r in c.get("stalled") or ()]
    attention += [{"kind": "stuck", "card": c, "pkt": k} for c in cards
                  for k in c.get("stuck") or ()]
    # The sessions you drive: blocked, your turn, gone quiet (docs/collaboration.md §4.3)
    attention += [{"kind": {"your turn": "yourturn"}.get(it["type"], it["type"]), "card": c,
                   "item": it} for c in cards for it in c.get("sessions") or ()]
    # Jobs that ended since you looked (W7): a failure is a failure, the rest a review.
    attention += [{"kind": "job", "card": c, "item": it} for c in cards
                  for it in c.get("job_items") or ()]
    # At risk of missing a due date (§9.3): a decision for you, never pushed.
    attention += [{"kind": "atrisk", "card": c, "item": risk_item(c)} for c in cards
                  if c.get("at_risk")]
    # Parked and untouched for longer than its priority allows (F1 rot, plan G5).
    attention += [{"kind": "rot", "card": c, "item": {
        "type": "rot", "source": "%s:%d" % (c["plan"].get("priority"), c["rot"]["limit"]),
        "since": 0, "text": "untouched for %d days (%s allows %d)" % (
            c["rot"]["days"], c["plan"].get("priority"), c["rot"]["limit"])}}
        for c in cards if c.get("rot") and c["column"] == "Parked"
        and c.get("lifecycle") == "open"]
    # Finished (to review) or stopped by a limit since anyone looked.
    unread = sorted((c for c in cards if c["unread"]), key=lambda c: c["unread"]["at"],
                    reverse=True)
    attention += [{"kind": c["unread"]["kind"], "card": c} for c in unread]
    order = {"needs": 0, "failed": 0, "blocked": 0, "trouble": 1, "stalled": 1, "stuck": 1,
             "atrisk": 1,
             "done": 2, "stopped": 2, "yourturn": 3, "stale": 3, "rot": 4}
    attention.sort(key=lambda a: order.get(a["kind"], 2) if a["kind"] != "job" else
                   1 if a["item"]["failed"] else 2)       # stable: in-kind order kept
    for a in attention:
        a["key"] = attention_key(a)
    reviews = [a for a in attention if a["kind"] == "done" and a["card"]["lifecycle"] == "open"]
    waits = [c["root"]["updated"] for c in needs if c["root"] and c["root"].get("updated")]
    failed = [c for c in needs if c["ball"]["kind"] == "failure"]
    fails = [c["root"]["updated"] for c in failed if c["root"] and c["root"].get("updated")]
    agent = cols["Working: agent"]
    running = [c for c in agent if c["running"]]
    sleepers = [c for c in cols["Waiting"] if c["root"] and c["root"]["state"] == "SLEEPING"]
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
            "progress": len(cols["Working: you"]) + len(agent), "done": len(unread),
            "reviews": len(reviews),
            "oldest_review": ago(min(a["card"]["unread"]["at"] for a in reviews))
            if reviews else "",
            "failed": len(failed) + sum(c["trouble"] for c in cards
                                        if c["ball"]["kind"] != "failure"),
            "newest_fail": ago(max(fails)) if fails else "",
            "spend_today": sum(c["spend_today"] for c in cards),
            "spend": total.get("cost_usd"),
            "quota": next((w for w in burn.get("quota") or [] if w["label"] == "Weekly"),
                          None),
        },
        "attention": attention, "boards": rows, "running": running,
        "you": cols["Working: you"],
        # What runs next: the queued (due now), then the sleepers by wake time.
        "coming": ([c for c in agent if not c["running"]] + sleepers)[:coming],
        "more_coming": max(len(agent) - len(running) + len(sleepers) - coming, 0),
        "next_wake": sleepers[0]["root"]["next"].split(", ")[-1] if sleepers else "",
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


def _pausing(pkt):
    """A pending pause request, not a take (``_taking``)."""
    from ..executor import pause_request
    req = pause_request(pkt)
    return None if req is None or req.get("take") else req


def _studio_ok(entry, wpid):
    """The packet can have a studio (docs/studio-plan.md S1.9): the root, or a child
    with a work/ folder."""
    from ..studio import model
    try:
        model.folder(entry, wpid)
        return True
    except model.StudioError:
        return False


def _taking(pkt):
    from ..executor import taking
    return taking(pkt)


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
    live = running(pkt, now)
    here = present(entry, now) if wpid == entry.get("root") else []
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
        "pausing": _pausing(pkt),
        "taken_by": meta.get("taken_by"), "taken": _ts(meta.get("taken")),
        # whose move it is (docs/collaboration.md §4.1), for the Now line
        "ball": views.ball(meta or {"state": "?"}, live, here),
        "driver": views.driver(meta, live, here), "present": here,
        "hooks": _hooks(entry) if wpid == entry.get("root") else None,
        "plan": planning.get(entry) if wpid == entry.get("root") else None,
        "actuals": _actuals(entry) if wpid == entry.get("root") else None,
        "milestones": _milestones_of(entry) if wpid == entry.get("root") else None,
        "lifecycle": views.lifecycle(meta),
        "autonomy": views.autonomy(meta), "review": meta.get("review"),
        "taking": _taking(pkt), "studio": _studio_ok(entry, wpid),
        "fields": [(k, meta.get(k)) for k in schema.STATUS_FIELDS if k in meta],
        "summary": body.strip(), "summary_html": md(body.strip()),
        "status_line": _first_line(body), "intent": _intent(body), "memento": memento, "files": files, "children": kids,
        "draft": _checkpoint_draft(pkt),
        "parent": parent, "steps": list(reversed(steps(pkt))), "running": live,
        "timeline": views.timeline(pkt, limit=60),
        "next": _next(meta, now, tz), "journal": pkt.journal().records[-200:],
        "notes": notes_mod.queued(pkt),
        "questions": questions.of_packet(pkt),
        "report": report(entry, pkt) if meta.get("state") in ("COMPLETED", "FAILED") else None,
    }


def md(text, link=None, lines=False):
    """Markdown to HTML, raw HTML in it escaped; None without markdown-it-py
    (the page then shows the text as it is). `link` maps each relative link
    or image target (no scheme, not absolute, not an anchor) to the URL to use. With
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
                    attr = {"link_open": "href", "image": "src"}.get(t.type)
                    href = t.attrGet(attr) if attr else None
                    if href and not href.startswith(("/", "#")) and ":" not in href.split("/")[0]:
                        t.attrSet(attr, link(href))
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
    want = work_rel(entry, rel)
    parts = want.split(os.sep)
    if os.path.isabs(want) or ".." in parts or parts[0] != "work":
        return None
    if layout.is_packet_layout(entry["path"]):
        # The packet folder is the work, seen as work/<folder> as in a run.
        folder = layout.packet_folder(entry["path"])
        if len(parts) < 2 or parts[1] != os.path.basename(folder) or \
                (len(parts) > 2 and parts[2] == layout.DOT):
            return None
        root = os.path.realpath(folder)
        p = os.path.realpath(os.path.join(folder, *parts[2:]))
    else:
        root = os.path.realpath(os.path.join(entry["path"], "work"))
        p = os.path.realpath(os.path.join(entry["path"], want))
    if not (p == root or p.startswith(root + os.sep)) or not os.path.exists(p):
        return None
    return p, os.path.isdir(p)


def work_rel(entry, rel):
    """``rel`` normalized; a packet's bare ``work`` is ``work/<folder>``."""
    want = os.path.normpath(rel or "work") if isinstance(rel, str) else "work"
    if want == "work" and layout.is_packet_layout(entry["path"]):
        want = os.path.join("work", os.path.basename(layout.packet_folder(entry["path"])))
    return want


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
    # Continue the step's conversation yourself (docs/collaboration.md §7.3): it is an
    # ordinary Claude session, resumed where it ran (Claude finds it by folder).
    resume = None
    if session and (meta or {}).get("harness", "claude") == "claude" and \
            (info.get("worker") or "agent") == "agent":
        folder = layout.packet_folder(entry["path"]) if layout.is_packet_layout(
            entry["path"]) else pkt.path
        resume = {"cwd": folder, "fork": "cd %s && claude --resume %s --fork-session" % (
            shlex.quote(folder), session),
                  "why": "cd %s && claude --resume %s --fork-session --permission-mode plan"
                  % (shlex.quote(folder), session)}
    return {
        "wpid": wpid, "short": wpid[:8], "dir": dirname, "info": info, "meta": meta,
        "resume": resume,
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
    pkt = _run_prefix(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(path)))))
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
            label = pkt.sub("", label, count=1)
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


def _run_prefix(run_dir):
    """A pattern for the run directory at the start of a path: where it is
    now, or where it was when the step ran (``packets/<wpid>/`` before
    ``wpk convert``, ``runs/<wpid>/`` after)."""
    import re
    wpid = re.escape(os.path.basename(run_dir))
    return re.compile(r"^(?:%s|/\S*/(?:%s|%s)/%s/)" % (
        re.escape(run_dir + os.sep), layout.LEGACY_RUNS, layout.RUNS, wpid))


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
            out.append("%s: %s" % (key, pkt.sub("", v, count=1)))
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
                "The next step starts from a clean tree: commit them as work in progress, "
                "or hand off anyway to include them as they are (%d paths)." % len(lines),
                ["git -C %s add -A && git -C %s commit -q -m 'WIP before hand-off'"
                 % ((shlex.quote(os.path.join(tg.packet_work, repo)),) * 2)], safe=True))
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
    summary = tg.packet.load_status()[1].strip()
    return {
        # Where it stands, when a person wrote it after the runner's last step: the
        # runner has not seen it, so it is the hand-off note's draft (W4).
        "context": summary if mode == "next" and _by_hand_last(tg.packet) else "",
        "tg": tg, "meta": meta, "state": state, "running": run, "owned": owned,
        "queued": _memento(tg.packet) if not owned and not run and state in (
            "RUNNABLE", "SLEEPING") else None,
        "mode": mode, "held_for_setup": held_for_setup(meta),
        "groups": groups, "missing": len(setup.missing(checks)),
        "instruction": text, "where": where, "draft": draft,
        "last_instruction": last[-1]["instruction"] if last else
        (_read(tg.prompt_path) or ""),
        "templates": setup.TEMPLATES,
        "inputs": _inputs(tg.state),
        "state_where": "the project's state/" if mode == "setup" else "the root packet's state/",
        "batch": executor.batch_of(records), "summary": summary,
        "archive_default": state == "COMPLETED",
        "carry": _carry_estimate(tg.packet, meta) if mode == "next" else None,
        "shell_dir": tg.proj if mode == "setup" else tg.packet.path,
    }



def _split_of(entry):
    """The project this one is a split of (plan G7), or None."""
    from .. import split
    d = split.info(entry)
    return d["of"] if d else None


def _draft(root):
    """The card's root has the scribe's draft as its last checkpoint (plan G3)."""
    done = [s for s in (root or {}).get("steps") or () if s.get("outcome") == "committed"]
    return bool(done) and done[-1].get("worker") == "scribe"


def _checkpoint_draft(pkt):
    from .. import checkpoint
    try:
        return checkpoint.draft_of(pkt)
    except Exception:                   # noqa: BLE001: a nicety; never fail the page
        return None


def _memento(pkt):
    try:
        with open(pkt.memento_path, encoding="utf-8") as fp:
            return fp.read().strip()
    except OSError:
        return ""


def _by_hand_last(pkt):
    """The packet's last step was a person's checkpoint (or the scribe's)."""
    from .. import checkpoint
    got = checkpoint.last(pkt)
    return bool(got) and got["worker"] in ("session", "studio", "scribe")


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


_ORIGIN = {}


def origin(entry):
    """Where a packet came from (``project.toml [origin]``, docs/starters-v1.md):
    {label, url, forge (it can be handed off as a pull request), pr ([pr]: url,
    number)}, or None."""
    path = os.path.join(entry["path"], "project.toml")
    try:
        mt = os.stat(path).st_mtime_ns
    except OSError:
        return None
    hit = _ORIGIN.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    from ..tomlio import load_toml
    try:
        d = load_toml(path)
    except (OSError, ValueError):
        d = {}
    o, pr = d.get("origin"), d.get("pr")
    out = None
    if isinstance(o, dict) and o:
        if o.get("kind") == "issue":
            label = "%s#%s %s" % (o.get("repo", ""), o.get("number", ""), o.get("title", ""))
        else:
            label = o.get("title") or o.get("repo") or o.get("url") or o.get("kind", "")
        out = {"label": label.strip(), "url": o.get("url") or "",
               "forge": bool(o.get("forge") and o.get("repo")),
               "pr": pr if isinstance(pr, dict) and pr.get("url") else None}
    _ORIGIN[path] = (mt, out)
    return out


def watchers(h, board):
    """A board's watchers (docs/starters-v1.md) with what they have done:
    [{name, repos, labels, on, branches, workflows, every, enabled, polled, made, failed,
    errors, problems}]."""
    from .. import watch
    out = []
    for w in watch.watchers(h):
        if w["board"] != board:
            continue
        if w.get("problems"):
            out.append({"name": "?", "problems": w["problems"]})
            continue
        s = watch.load_state(w, h)
        out.append({"name": w["name"], "repos": w["repos"], "labels": w.get("labels") or [],
                    "on": w.get("on", "issues"), "branches": w.get("branches") or [],
                    "workflows": w.get("workflows") or [],
                    "every": w.get("every", "15m"), "enabled": w.get("enabled", True),
                    "hold": w.get("hold", True), "dir": w["dir"],
                    "propose": w.get("propose", False), "pr": w.get("pr", "off"),
                    "polled": _ago(s.get("polled")), "made": sorted(s["seen"].items()),
                    "failed": sorted(s["failed"].items()), "errors": s.get("errors") or []})
    return out


def _ago(t):
    if not t:
        return "never"
    import time as _t
    d = int(_t.time() - t)
    return "%ds ago" % d if d < 90 else "%dm ago" % (d // 60) if d < 5400 else \
        "%dh ago" % (d // 3600) if d < 172800 else "%dd ago" % (d // 86400)


def review_load(h=None, now=None):
    """The attention budget (docs/collaboration.md §7.6): finished work waiting for
    your review, ``{"n", "oldest", "limit", "over"}``. Reads each root's status
    only, so a hand-off form can say it cheaply."""
    from .. import views
    now = now or clock.now()
    stops = []
    for e in archived.entries(h):
        try:
            meta, _ = Packet(layout.run_dir(e["path"], e["root"])).load_status()
        except (OSError, frontmatter.FrontMatterError, KeyError, TypeError):
            continue
        if views.ball(meta)["kind"] == "review":
            stops.append(_ts(meta.get("stopped")) if isinstance(meta.get("stopped"), str)
                         else meta.get("stopped"))
    try:
        limit = int((registry.load_config_file(h).get("plan") or {}).get("review_wip") or 5)
    except (registry.ConfigError, ValueError, TypeError):
        limit = 5
    at = [t for t in stops if t]
    return {"n": len(stops), "limit": limit, "over": len(stops) >= limit,
            "oldest": relative(-(now - min(at)).total_seconds()).replace(" ago", "")
            if at else ""}


def _about(card):
    """The root's instruction, shortened: what a project is about."""
    root = card.get("root") or {}
    try:
        _, body = Packet(root["path"]).load_memento()
    except (KeyError, TypeError, OSError, frontmatter.FrontMatterError):
        return ""
    return body[:600]


INBOX_FROM = {"watch": "a watcher", "agent": "the runner", "session": "a Claude session",
              "cli": "the command line", "phone": "your phone",
              "learn": "your corrections", "date": "an issue's milestone"}


def inbox_view(h, cols, board=None):
    """The Inbox (docs/collaboration.md W8) for a page: items (one board's, given
    ``board``) with where each came from and the open projects it looks like, and
    the requests that have not started. ``{"entries", "requests", "projects"}``."""
    from .. import inbox
    cards = [c for v in cols.values() for c in v]
    its = inbox.items(h or registry.home())
    if its:                     # what each project is about, for the duplicate hint
        cards = [dict(c, intent="%s %s" % (c.get("intent") or "", _about(c))) for c in cards]
    items = []
    for d in its:
        if board and (d.get("board") or registry.DEFAULT_BOARD) != board:
            continue
        d = dict(d, came=INBOX_FROM.get(d.get("source") or "", ""),
                 like=inbox.similar(d["text"], cards))
        items.append(d)
    reqs = [r for r in inbox.requests(h)
            if not board or any(c["name"] == r["project"] for c in cards)]
    return {"entries": items, "requests": reqs,
            "projects": sorted(c["name"] for c in cards if c.get("lifecycle", "open") == "open")}


def milestones_view(h, cols, board, now=None):
    """The board page's Milestones panel (plan F3d): each milestone with its
    projects, today's figures, the burn-down chart, and the latest forecast."""
    from .. import forecast, milestones
    now = now or clock.now()
    today = now.astimezone().date()
    cards = [c for v in cols.values() for c in v]
    out = []
    for m in milestones.of_board(board, h):
        mine = [c for c in cards if (c.get("plan") or {}).get("milestone") == m["name"]]
        rows = milestones.snaps(board, m["name"], h)
        fcs = [c["forecast"] for c in mine if c.get("forecast")]
        late = max(fcs, key=lambda f: f["high"]) if fcs else None
        try:
            days = (datetime.fromisoformat(m["date"]).date() - today).days
        except ValueError:
            days = None
        out.append(dict(m, cards=mine, now=milestones.count(cards, board, m["name"], h),
                        chart=milestones.chart(m, rows), days=days,
                        forecast=forecast.range_text(late, today) if late else None,
                        late=bool(late and datetime.fromtimestamp(late["high"]).date().isoformat()
                                  > m["date"]),
                        risky=[c["name"] for c in mine if c.get("at_risk")]))
    return out
