"""Will it make it? A forecast for a project with a due date, and at risk
(docs/collaboration.md §9.3, plan F3b).

Part of the remaining work is the runner's, and the board has its history:

- **The runner's share**: the part of the current plan (``state/outline.md``)
  still to do, times this project's task wall time (a task: from its hand-off to
  the step that finished it, so queue waits and questions are in it). The 25th
  to the 75th percentile, for a range. A project with no finished task uses the
  board's tasks.
- **Your share**: each item that needs you (a question, a review, a failure, a
  session waiting on you, or the project being yours) times your answer time
  (questions, asked to answered): your own on the board once you have answered
  ``OWN_MIN``, else everyone's. With an estimate and some history of your pace
  on the project (hours a working day, last 14 days, from the time ledger), the
  estimate's hours left at that pace instead, laid on working days (weekends
  skipped).

A range, never a promise. No model: deterministic, from the journal. The board
only forecasts projects with a due date, and keeps the board-wide figures for
``CACHE_S``.
"""

import json
import os
import time
from datetime import date, datetime, timedelta

from . import clock, layout, planning, registry, timelog

CACHE_S = 600
DEFAULT_ITEM_S = (2 * 3600, 24 * 3600)      # one item of yours, with no history
NEAR_DAYS = 2                               # due this soon, and yours for a day: at risk
BLOCKED_DAYS = 7                            # due this soon, and blocked: at risk
PACE_DAYS = 14
OWN_MIN = 5                                 # your own answers before they are used
YOURS = ("question", "review", "failure", "blocked", "your turn")

_cache = {}


def _t(ts):
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()
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


def _history(entry):
    """``(task seconds, [(answer seconds, who answered)])`` from the root journal."""
    from .history import _tasks_and_questions
    from .packet import Packet
    if not entry.get("root"):
        return [], []
    tasks, qs = _tasks_and_questions(_recs(Packet(layout.run_dir(
        entry["path"], entry["root"])).journal_path))
    took = [_t(x["end"]) - _t(x["start"]) for x in tasks
            if x.get("outcome") == "done" and _t(x["end"]) and _t(x["start"])]
    ans = [(_t(q["answered"]) - _t(q["asked"]), _who(q.get("by"))) for q in qs
           if _t(q["answered"]) and _t(q["asked"])]
    return [s for s in took if s > 0], [(s, b) for s, b in ans if s > 0]


def _who(by):
    return (by or "").split("@")[0] or None


def history(entry):
    """``(task seconds, answer seconds)`` from the project's root journal."""
    took, ans = _history(entry)
    return took, [s for s, _ in ans]


def board_history(h=None, now=None, by=None):
    """Every project's ``history``, pooled; cached ``CACHE_S``. ``by``: answer
    times are that person's when they have ``OWN_MIN`` of them."""
    h = h or registry.home()
    now = time.time() if now is None else now
    got = _cache.get(h)
    if not got or now - got[0] >= CACHE_S:
        tasks, ans = [], []
        for e in registry.entries(h):
            try:
                t, a = _history(e)
            except Exception:           # noqa: BLE001: one project's journal can't break it
                continue
            tasks += t
            ans += a
        got = _cache[h] = (now, (tasks, ans))
    tasks, ans = got[1]
    mine = [s for s, b in ans if by and b == _who(by)]
    return tasks, mine if len(mine) >= OWN_MIN else [s for s, _ in ans]


def add_working(now, days):
    """Epoch ``days`` working days after ``now`` (weekends skipped; a part day is
    that part of 24 hours)."""
    t = datetime.fromtimestamp(now)
    whole, part = int(days), days - int(days)
    while whole > 0:
        t += timedelta(days=1)
        if t.weekday() < 5:
            whole -= 1
    t += timedelta(seconds=part * 86400)
    while t.weekday() >= 5:
        t += timedelta(days=1)
    return t.timestamp()


def spread(xs):
    """(low, high): the 25th and 75th percentiles; one or two samples widen to
    ×0.75 and ×1.5."""
    xs = sorted(xs)
    if not xs:
        return None
    if len(xs) < 3:
        m = sum(xs) / len(xs)
        return m * 0.75, m * 1.5
    return xs[int(0.25 * (len(xs) - 1))], xs[int(round(0.75 * (len(xs) - 1)))]


def left(entry):
    """``(left, total)`` items of the root packet's current plan, or None."""
    from .dash import plan as planmod
    if not entry.get("root"):
        return None
    p = os.path.join(layout.run_dir(entry["path"], entry["root"]), planmod.OUTLINE)
    try:
        with open(p, encoding="utf-8") as fp:
            done, total = planmod.count(planmod.parse(fp.read()))
    except OSError:
        return None
    return (total - done, total) if total else None


def pace(entry, now):
    """Your hours a working day on the project over the last ``PACE_DAYS``, or None."""
    today = datetime.fromtimestamp(now).date()
    d0 = today - timedelta(days=PACE_DAYS)
    rows = [(d, s) for d, s in timelog.by_day(entry["path"], d0.isoformat()) if s > 0]
    if not rows:
        return None
    wd = planning.working_days(date.fromisoformat(rows[0][0]), today)
    return sum(s for _, s in rows) / 3600 / max(wd, 1)


def forecast(entry, card, now=None, h=None):
    """``{"low", "high" (epoch), "runner": (lo, hi) s, "yours": (lo, hi) s, "why":
    [str]}``, or None when nothing is known to be left."""
    now = clock.now().timestamp() if now is None else now
    ball = card.get("ball") or {}
    why, runner, yours = [], (0.0, 0.0), (0.0, 0.0)
    autonomy = card.get("autonomy")
    lr = left(entry)
    frac = None
    if lr and lr[0] > 0 and autonomy != "manual":
        frac = lr[0] / float(lr[1])
        what = "%d of %d plan items" % lr
    elif ball.get("who") in ("agent", "scheduled"):
        frac, what = 0.5, "the runner's current task"
    if frac:
        mine, _ = history(entry)
        s = spread(mine) or spread(board_history(h, now)[0])
        if s:
            runner = (s[0] * frac, s[1] * frac)
            why.append("%s for the runner (%s)" % (what, _span(runner)))
    n = 1 if ball.get("kind") in YOURS or (ball.get("who") == "you" and
                                            ball.get("kind") == "working") else 0
    n += sum(1 for it in card.get("sessions") or () if it.get("type") in YOURS)
    if ball.get("who") == "you" and ball.get("kind") == "working":
        est = planning.estimate_hours((card.get("plan") or {}).get("estimate"))
        p = pace(entry, now)
        if est and p:
            spent = sum(timelog.spent(entry["path"]).values()) / 3600
            hrs = max(est - spent, 0.0)
            days = hrs / p
            yours = (add_working(now, days * 0.8) - now, add_working(now, days * 1.5) - now)
            why.append("%.0fh of your %s estimate left at your pace (%.1fh a day)" % (
                hrs, card["plan"]["estimate"], p))
            n = 0
    if n:
        me = card.get("owner") or (card.get("root") or {}).get("owner")
        _, ans = _history(entry)
        own = [s for s, b in ans if me and b == _who(me)]
        s = spread(own if len(own) >= OWN_MIN else [x for x, _ in ans]) or \
            spread(board_history(h, now, me)[1]) or DEFAULT_ITEM_S
        yours = (yours[0] + s[0] * n, yours[1] + s[1] * n)
        why.append("%s yours (%s)" % ("1 item" if n == 1 else "%d items" % n,
                                      _span((s[0] * n, s[1] * n))))
    if not why:
        return None
    return {"low": now + runner[0] + yours[0], "high": now + runner[1] + yours[1],
            "runner": runner, "yours": yours, "why": why}


def _span(r):
    def one(s):
        if s < 3600:
            return "%dm" % max(round(s / 60), 1)
        if s < 2 * 86400:
            return "%dh" % round(s / 3600)
        return "%dd" % round(s / 86400)
    a, b = one(r[0]), one(r[1])
    return a if a == b else "%s-%s" % (a, b)


def range_text(fc, today=None):
    """"Thu-Mon", "today", or "12 Nov-20 Nov"."""
    today = today or date.today()

    def day(t):
        d = datetime.fromtimestamp(t).date()
        if d == today:
            return "today"
        return d.strftime("%a") if (d - today).days < 7 else d.strftime("%d %b").lstrip("0")
    a, b = day(fc["low"]), day(fc["high"])
    return a if a == b else "%s-%s" % (a, b)


def at_risk(due, due_kind, fc, card, today, now, done=()):
    """Why a project may miss ``due`` (a date), or None:
    - the forecast's high end passes it;
    - it is due within ``NEAR_DAYS`` and has been yours for more than a day;
    - it is due within ``BLOCKED_DAYS`` and is blocked by something not done
      (``done``: the names of projects that are done)."""
    if not due:
        return None
    try:
        d = date.fromisoformat(str(due))
    except ValueError:
        return None
    if d < today:
        return None                     # overdue says it already
    n = (d - today).days
    if fc and datetime.fromtimestamp(fc["high"]).date() > d:
        return "forecast %s" % range_text(fc, today)
    ball = card.get("ball") or {}
    upd = (card.get("root") or {}).get("updated")
    if n <= NEAR_DAYS and ball.get("who") == "you" and upd and \
            now - upd.timestamp() > 86400:
        return "yours for %d days" % ((now - upd.timestamp()) // 86400)
    blocked = [b for b in (card.get("plan") or {}).get("blocked_by") or () if b not in done]
    if n <= BLOCKED_DAYS and blocked:
        return "blocked by %s" % ", ".join(blocked)
    return None


def decision_text(name, due_txt, fc, why_risk):
    """The Desk item: "fifo-cov due Fri: 2 of 5 plan items for the runner
    (3h-6h), 1 item yours (2h-1d); forecast Thu-Mon"."""
    parts = "; ".join(fc["why"]) if fc else ""
    return "%s %s: %s%s" % (name, due_txt, parts + "; " if parts else "", why_risk)
