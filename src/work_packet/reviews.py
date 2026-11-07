"""Weekly review, standup and status drafts (docs/collaboration.md §9.5, plan F3e).

People write these by hand from facts the board already has. Every line here
comes from the journals, the time ledger (``timelog``), the plan fields and the
forecast, with no model call:

- **Weekly review** (GTD): done this week by you and by the runner; your time and
  the runner's; cost; what has waited on you for over a week; backlog that has
  gone untouched; estimates against actuals; next week's deadlines. The board
  builds it on ``[focus] review_day`` (default fri) after ``review_time``
  (default 16:00), into ``$WPK_HOME/reviews/<YYYY-Www>.json`` and ``.md``.
- **Standup**: yesterday (your last working day), today (the brief's focus),
  blocked.
- **Status**: a row per project of a board, or of one milestone.

Standup and status are drafted when you open their page; **Keep a copy** writes
the Markdown to ``$WPK_HOME/reports/``.
"""

import json
import os
import time
from datetime import date, datetime, timedelta, timezone

from . import clock, fsutil, planning, registry, timelog

REVIEW_DAY = "fri"
REVIEW_TIME = "16:00"
WAITED_DAYS = 7
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _ts(t):
    try:
        return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _recs(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fp:
            for ln in fp:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
    except OSError:
        pass
    return out


def _cards(h):
    from .dash import data
    cols, _ = data.board(h)
    return [c for v in cols.values() for c in v]


def _journal(entry):
    from . import layout
    from .packet import Packet
    if not entry.get("root"):
        return []
    return _recs(Packet(layout.run_dir(entry["path"], entry["root"])).journal_path)


def activity(entry, t0, t1):
    """What happened on a project between epochs ``t0`` and ``t1``:
    ``{"tasks": [instruction], "done": by|None, "dropped": by|None, "handoffs":
    [by], "notes": n, "you_s": {user: s}, "runner_s", "cost"}``."""
    from . import layout, stats
    from .history import _tasks_and_questions
    from .packet import Packet
    recs = _journal(entry)
    tasks, _ = _tasks_and_questions(recs)
    out = {"tasks": [x.get("instruction") or "its task" for x in tasks
                     if x.get("outcome") == "done" and t0 <= (_ts(x["end"]) or 0) < t1],
           "done": None, "dropped": None, "handoffs": [], "notes": 0,
           "runner_s": 0.0, "cost": 0.0}
    for r in recs:
        t = _ts(r.get("t"))
        if t is None or not t0 <= t < t1:
            continue
        if r.get("type") == "admin" and r.get("op") in ("done", "drop"):
            out["done" if r["op"] == "done" else "dropped"] = r.get("by") or "?"
        elif r.get("type") == "handoff" and r.get("by"):
            out["handoffs"].append(r["by"])
        elif r.get("type") == "note":
            out["notes"] += 1
    d0 = date.fromtimestamp(t0).isoformat()
    d1 = date.fromtimestamp(t1 - 1).isoformat()
    out["you_s"] = timelog.spent(entry["path"], d0, d1)
    try:
        wpids = sorted(os.listdir(layout.runs_dir(entry["path"])))
    except OSError:
        wpids = []
    for w in wpids:
        try:
            steps = stats.packet_steps(entry["name"], Packet(layout.run_dir(entry["path"], w)))
        except Exception:               # noqa: BLE001
            continue
        for s in steps:
            end = _ts(s.end)
            if end is not None and t0 <= end < t1:
                out["runner_s"] += s.duration_s or 0
                out["cost"] += s.cost or 0
    return out


def _week(now):
    d = date.fromtimestamp(now)
    monday = d - timedelta(days=d.weekday())
    y, w, _ = d.isocalendar()
    return "%d-W%02d" % (y, w), monday


def _start(d):
    return datetime(d.year, d.month, d.day).timestamp()


# --- the weekly review --------------------------------------------------------------

def _dir(h, *p):
    return os.path.join(h or registry.home(), *p)


def review_path(h, week, ext="json"):
    return _dir(h, "reviews", "%s.%s" % (week, ext))


def reviews(h=None, n=12):
    try:
        names = os.listdir(_dir(h, "reviews"))
    except OSError:
        return []
    return sorted({x[:-5] for x in names if x.endswith(".json")}, reverse=True)[:n]


def load_review(h, week):
    try:
        with open(review_path(h, week)) as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return None


def weekly(h=None, now=None, write=True):
    """This week's review (Monday to ``now``), as a dict; written to
    ``reviews/`` unless ``write`` is false."""
    from . import inbox, milestones
    h = h or registry.home()
    now = clock.now().timestamp() if now is None else now
    week, monday = _week(now)
    t0 = _start(monday)
    today = date.fromtimestamp(now)
    cards = _cards(h)
    done, worked, you_s, runner_s, cost = [], [], 0.0, 0.0, 0.0
    for c in cards:
        e = registry.get(c["name"], h)
        if e is None:
            continue
        a = activity(e, t0, now + 1)
        mine = sum(a["you_s"].values())
        you_s += mine
        runner_s += a["runner_s"]
        cost += a["cost"]
        if a["done"] or a["dropped"]:
            done.append({"project": c["name"], "how": "done" if a["done"] else "dropped",
                         "by": a["done"] or a["dropped"]})
        if a["tasks"] or mine or a["runner_s"]:
            worked.append({"project": c["name"], "tasks": len(a["tasks"]), "you_s": mine,
                           "runner_s": a["runner_s"]})
    worked.sort(key=lambda w: -(w["you_s"] + w["runner_s"]))
    waited = []
    for it in inbox.items(h):
        if now - (it.get("t") or now) > WAITED_DAYS * 86400:
            waited.append({"project": it.get("project") or "Inbox", "text": it["text"][:120],
                           "days": int((now - it["t"]) // 86400)})
    for c in cards:
        upd = (c.get("root") or {}).get("updated")
        if c["column"] == "Needs you" and upd and now - upd.timestamp() > WAITED_DAYS * 86400:
            waited.append({"project": c["name"], "text": c["ball"]["text"],
                           "days": int((now - upd.timestamp()) // 86400)})
    backlog = [{"project": c["name"], "priority": (c.get("plan") or {}).get("priority"),
                "days": c["rot"]["days"]} for c in cards if c.get("rot")]
    estimates = []
    for c in cards:
        est = (c.get("plan") or {}).get("estimate")
        e = registry.get(c["name"], h) if est and c.get("lifecycle") == "open" else None
        if e is not None:
            a = planning.actuals(e, now)
            estimates.append({"project": c["name"], "estimate": est,
                              "so_far": planning.actuals_text(a), "over": a["over"]})
    nxt = today + timedelta(days=7)
    deadlines = sorted(({"project": c["name"], "due": c["due_eff"], "kind": c.get("due_kind"),
                         "risk": c.get("at_risk"),
                         "forecast": (c.get("forecast") or {}).get("text")}
                        for c in cards if c.get("due_eff") and c["due_eff"] <= nxt.isoformat()),
                       key=lambda d: d["due"])
    ms = [{"board": b["name"], "name": m["name"], "date": m["date"]}
          for b in registry.boards(h) for m in milestones.of_board(b["name"], h)
          if today.isoformat() <= m["date"] <= (today + timedelta(days=14)).isoformat()]
    r = {"week": week, "t": now, "from": monday.isoformat(), "done": done, "worked": worked,
         "you_s": you_s, "runner_s": runner_s, "cost": cost, "waited": waited,
         "backlog": backlog, "estimates": estimates, "deadlines": deadlines, "milestones": ms}
    if write:
        os.makedirs(_dir(h, "reviews"), exist_ok=True)
        fsutil.atomic_write(review_path(h, week), json.dumps(r, indent=1) + "\n")
        fsutil.atomic_write(review_path(h, week, "md"), render_weekly(r))
    return r


def render_weekly(r):
    hrs = timelog.hours
    out = ["# Week %s · Review" % r["week"], "",
           "From %s. Your time %s, the runner's %s%s." % (
               r["from"], hrs(r["you_s"]), hrs(r["runner_s"]),
               ", cost $%.2f" % r["cost"] if r["cost"] else ""), ""]
    out += ["## Done", ""]
    out += ["- **%s**: %s by %s" % (d["project"], d["how"], d["by"]) for d in r["done"]] or \
        ["Nothing closed this week."]
    out.append("")
    if r["worked"]:
        out += ["## Worked on", ""]
        out += ["- **%s**: %s%s%s" % (
            w["project"], "%d task%s by the runner" % (w["tasks"], "" if w["tasks"] == 1 else "s")
            if w["tasks"] else "no runner task finished",
            ", you %s" % hrs(w["you_s"]) if w["you_s"] else "",
            ", runner %s" % hrs(w["runner_s"]) if w["runner_s"] else "") for w in r["worked"]]
        out.append("")
    if r["waited"]:
        out += ["## Waiting over a week", ""]
        out += ["- **%s**: %s (%d days)" % (w["project"], w["text"], w["days"])
                for w in r["waited"]]
        out.append("")
    if r["backlog"]:
        out += ["## Untouched backlog: keep, someday or drop?", ""]
        out += ["- **%s**: %s, untouched %d days" % (b["project"], b["priority"], b["days"])
                for b in r["backlog"]]
        out.append("")
    if r["estimates"]:
        out += ["## Estimates against actuals", ""]
        out += ["- **%s**: estimated %s; %s%s" % (e["project"], e["estimate"],
                                                  e["so_far"] or "nothing yet",
                                                  " (over)" if e["over"] else "")
                for e in r["estimates"]]
        out.append("")
    out += ["## Next week", ""]
    lines = ["- **%s**: due %s%s%s%s" % (d["project"], d["due"],
                                         " (hard)" if d["kind"] == "hard" else "",
                                         ", forecast %s" % d["forecast"] if d["forecast"] else "",
                                         ", **at risk**: %s" % d["risk"] if d["risk"] else "")
             for d in r["deadlines"]]
    lines += ["- milestone **%s** (%s): %s" % (m["name"], m["board"], m["date"])
              for m in r["milestones"]]
    out += lines or ["No deadlines."]
    out.append("")
    return "\n".join(out)


def review_due(h, cfg, now=None):
    """Is it time to build this week's review (``[focus] review_day`` and
    ``review_time``; ``review = false`` turns it off)?"""
    now = clock.now().timestamp() if now is None else now
    if cfg.get("review") is False:
        return False
    lt = time.localtime(now)
    day = DAYS.index(str(cfg.get("review_day") or REVIEW_DAY)[:3].lower())
    hh, mm = (int(x) for x in str(cfg.get("review_time") or REVIEW_TIME).split(":"))
    if lt.tm_wday != day or (lt.tm_hour, lt.tm_min) < (hh, mm):
        return False
    return not os.path.exists(review_path(h, _week(now)[0]))


def tidy(h, choices, by=None):
    """**Tidy the backlog**: ``{project: keep|someday|drop}``. Returns lines."""
    from . import executor, layout
    from .packet import Packet
    out = []
    for name, op in sorted(choices.items()):
        e = registry.get(name, h)
        if e is None or op == "keep":
            continue
        if op == "someday":
            planning.set_(e, {"priority": "someday"}, by)
            out.append("%s: someday" % name)
        elif op == "drop":
            r = executor.mark(Packet(layout.run_dir(e["path"], e["root"])), "drop", by=by,
                              note="dropped in the weekly review")
            out.append("%s: %s" % (name, getattr(r, "msg", "dropped")))
    return out


# --- standup and status ---------------------------------------------------------------

def last_working_day(today):
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def standup(h=None, now=None):
    """``{"day", "yesterday": [{project, lines}], "today": [{project, why}],
    "blocked": [{project, text}]}``. Yesterday is your last working day."""
    from . import brief
    h = h or registry.home()
    now = clock.now().timestamp() if now is None else now
    today = date.fromtimestamp(now)
    y = last_working_day(today)
    t0, t1 = _start(y), _start(y + timedelta(days=1))
    cards = _cards(h)
    yesterday = []
    for c in cards:
        e = registry.get(c["name"], h)
        if e is None:
            continue
        a = activity(e, t0, t1)
        lines = []
        mine = sum(a["you_s"].values())
        if mine:
            lines.append("worked on it (%s)" % timelog.hours(mine))
        if a["handoffs"]:
            lines.append("handed it to the runner")
        lines += ["the runner finished: %s" % t[:100] for t in a["tasks"]]
        if a["done"]:
            lines.append("marked it done")
        if a["dropped"]:
            lines.append("dropped it")
        if lines:
            yesterday.append({"project": c["name"], "lines": lines})
    b = brief.load(h, today.isoformat())
    if b:
        focus = [{"project": f["project"], "why": ", ".join(f["why"]) or "next up"}
                 for f in b.get("focus") or ()]
    else:
        ranked = sorted(((brief.score(c, today, now), c["name"]) for c in cards
                         if c.get("lifecycle") == "open" and c["column"] != "Done"),
                        key=lambda x: (-x[0][0], x[1]))[:brief.TOP]
        focus = [{"project": n, "why": ", ".join(s[1]) or "next up"} for s, n in ranked]
    done = {c["name"] for c in cards if c.get("lifecycle") == "done"}
    blocked = []
    for c in cards:
        if c.get("lifecycle") != "open":
            continue
        bb = [x for x in (c.get("plan") or {}).get("blocked_by") or () if x not in done]
        if bb:
            blocked.append({"project": c["name"], "text": "waits on %s" % ", ".join(bb)})
        for r in c.get("stalled") or ():
            blocked.append({"project": c["name"], "text": "request %s to %s is %s" % (
                r.get("id"), r.get("project"), r.get("state"))})
    return {"day": today.isoformat(), "yesterday_day": y.isoformat(), "yesterday": yesterday,
            "today": focus, "blocked": blocked}


def render_standup(s):
    d = date.fromisoformat(s["yesterday_day"])
    out = ["# Standup %s" % s["day"], "", "**Yesterday** (%s)" % d.strftime("%a"), ""]
    out += ["- %s: %s" % (y["project"], "; ".join(y["lines"])) for y in s["yesterday"]] or \
        ["- nothing recorded"]
    out += ["", "**Today**", ""]
    out += ["- %s (%s)" % (t["project"], t["why"]) for t in s["today"]] or ["- nothing open"]
    out += ["", "**Blocked**", ""]
    out += ["- %s: %s" % (b["project"], b["text"]) for b in s["blocked"]] or ["- nothing"]
    out.append("")
    return "\n".join(out)


def status(h=None, board=registry.DEFAULT_BOARD, milestone=None, now=None):
    """A status for a board, or one of its milestones: ``{"board", "milestone",
    "rows": [{project, column, ball, tasks, due, forecast, risk, lifecycle}],
    "done": [project]}`` (``tasks``: runner tasks finished this week)."""
    from . import milestones as ms_mod
    h = h or registry.home()
    now = clock.now().timestamp() if now is None else now
    _, monday = _week(now)
    t0 = _start(monday)
    m = ms_mod.get(board, milestone, h) if milestone else None
    rows, done = [], []
    for c in _cards(h):
        if c.get("board") != board:
            continue
        if milestone and (c.get("plan") or {}).get("milestone") != milestone:
            continue
        e = registry.get(c["name"], h)
        a = activity(e, t0, now + 1) if e else {"tasks": [], "done": None}
        if c.get("lifecycle") != "open":
            if a["done"]:
                done.append(c["name"])
            continue
        rows.append({"project": c["name"], "column": c["column"], "ball": c["ball"]["text"],
                     "tasks": len(a["tasks"]), "due": c.get("due_eff"),
                     "forecast": (c.get("forecast") or {}).get("text"),
                     "risk": c.get("at_risk")})
    rows.sort(key=lambda r: (r["due"] or "9999", r["project"]))
    return {"board": board, "milestone": m, "day": date.fromtimestamp(now).isoformat(),
            "rows": rows, "done": done}


def render_status(s):
    title = "%s · %s" % (s["board"], s["milestone"]["name"]) if s["milestone"] else s["board"]
    out = ["# Status: %s (%s)" % (title, s["day"]), ""]
    if s["milestone"]:
        out += ["Milestone %s on %s." % (s["milestone"]["name"], s["milestone"]["date"]), ""]
    out += ["| Project | Where | Next move | Runner tasks this week | Due | Forecast |",
            "|---|---|---|---|---|---|"]
    for r in s["rows"]:
        out.append("| %s | %s | %s | %d | %s | %s |" % (
            r["project"], r["column"], r["ball"].replace("|", "/"), r["tasks"], r["due"] or "",
            ("%s, **at risk**" % (r["forecast"] or "") if r["risk"] else r["forecast"] or "")))
    if s["done"]:
        out += ["", "Done this week: %s." % ", ".join(s["done"])]
    out.append("")
    return "\n".join(out)


def keep(h, kind, name, text, now=None):
    """**Keep a copy**: ``reports/<kind>-<name>-<day>.md``. Returns the path."""
    now = clock.now().timestamp() if now is None else now
    p = _dir(h, "reports", "%s%s-%s.md" % (kind, "-" + name if name else "",
                                           date.fromtimestamp(now).isoformat()))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, text)
    return p


def kept(h=None, n=20):
    try:
        names = os.listdir(_dir(h, "reports"))
    except OSError:
        return []
    return sorted((x for x in names if x.endswith(".md")), reverse=True)[:n]


# --- the board's loop -----------------------------------------------------------------

def tick(h=None, cfg=None, now=None):
    """The board's loop: the weekly review on its day, the milestones' daily
    snapshot, and the calendar feed (hourly). Returns what it did, as words."""
    from . import milestones
    h = h or registry.home()
    now = clock.now().timestamp() if now is None else now
    cfg = cfg or {}
    did = []
    if review_due(h, cfg, now):
        weekly(h, now)
        did.append("wrote this week's review")
    today = date.fromtimestamp(now).isoformat()
    need = any(m["date"] >= today and (not milestones.snaps(b["name"], m["name"], h) or
                                       milestones.snaps(b["name"], m["name"], h)[-1]["day"]
                                       != today)
               for b in registry.boards(h) for m in milestones.of_board(b["name"], h))
    if need and milestones.snap(_cards(h), h, now):
        did.append("took the milestones' snapshot")
    from . import icsfeed
    try:
        if icsfeed.fetch(h, now):
            did.append("fetched the calendar feed")
    except icsfeed.FeedError as e:
        did.append(str(e))
    return did
