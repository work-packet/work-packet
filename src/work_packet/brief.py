"""The daily focus brief (docs/collaboration.md §9.4) and the end-of-day shutdown
(§9.5).

Each morning (``[focus] time``, weekdays) the board writes a brief that reads in a
minute: what happened overnight, what needs you, where to focus and why, what to
hand to the runner before you start, and housekeeping. Every line comes from the
board's own data (cards, the journal, your plan fields); no model is asked. It is
kept, one per day, in ``$WPK_HOME/briefs/YYYY-MM-DD.json`` and ``.md``, so past
briefs stay on the Desk.

The focus score, highest first (each suggestion says why it is there):

- your priority: now 300, next 200, later 100, someday 0;
- deadline: overdue 160, due within 2 days 120, within a week 60; hard ×1.5;
- unblocks others: a question the runner waits on 90;
- waiting on you anyway (a failure, a review, a blocked session) 50;
- age: one point a day since anyone touched it, at most 30.

"Not today" and "done already" on a suggestion are remembered for the day. A
project suggested three briefs running with nothing done on it moves to
housekeeping ("still now?") instead of being suggested again.
"""

import json
import os
import time
from datetime import date, datetime

from . import fsutil

TIME = "08:30"
TOP = 3
PRIORITY_SCORE = {"now": 300, "next": 200, "later": 100, "someday": 0}
REPEAT = 3                  # suggested this many briefs running, untouched: ask instead


def _dir(home):
    return os.path.join(home, "briefs")


def path(home, day, ext="json"):
    return os.path.join(_dir(home), "%s.%s" % (day, ext))


def load(home, day):
    try:
        with open(path(home, day)) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def days(home, n=14):
    """The days with a brief, newest first."""
    try:
        names = os.listdir(_dir(home))
    except OSError:
        return []
    return sorted((x[:-5] for x in names if x.endswith(".json") and x[:4].isdigit()),
                  reverse=True)[:n]


# --- feedback ------------------------------------------------------------------------

def _feedback_path(home):
    return os.path.join(_dir(home), "feedback.json")


def feedback(home):
    try:
        with open(_feedback_path(home)) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def say(home, day, project, kind):
    """``kind``: "not today" or "done already", for ``project`` on ``day``."""
    if kind not in ("not today", "done already"):
        raise ValueError(kind)
    d = feedback(home)
    d.setdefault(day, {})[project] = kind
    for k in sorted(d)[:-30]:           # a month is plenty
        d.pop(k, None)
    os.makedirs(_dir(home), exist_ok=True)
    fsutil.atomic_write(_feedback_path(home), json.dumps(d, sort_keys=True) + "\n")


# --- the score -----------------------------------------------------------------------

def score(card, today, now_t):
    """(points, [reasons]) for one project's card."""
    plan = card.get("plan") or {}
    pts, why = PRIORITY_SCORE.get(plan.get("priority"), 200), []
    if plan.get("priority") in ("now", "later", "someday"):
        why.append(plan["priority"])
    due = card.get("due_eff") or plan.get("due")
    if due:
        try:
            n = (date.fromisoformat(str(due)) - today).days
        except ValueError:
            n = None
        if n is not None:
            add = 160 if n < 0 else 120 if n <= 2 else 60 if n <= 7 else 0
            if (card.get("due_kind") or plan.get("due_kind")) == "hard":
                add = int(add * 1.5)
            if add:
                pts += add
                why.append(card.get("due") or "due %s" % due)
    if card.get("at_risk"):
        pts += 100
        why.append("at risk: %s" % card["at_risk"])
    kind = (card.get("ball") or {}).get("kind")
    if kind == "question":
        pts += 90
        why.append("answering it lets the runner go on")
    elif kind in ("failure", "review") or card.get("sessions"):
        pts += 50
        why.append({"failure": "it failed", "review": "the runner finished: review it"}.get(
            kind, "Claude is waiting on you"))
    last = card.get("last_end") or (card.get("root") or {}).get("updated")
    if last:
        age = int((now_t - last.timestamp()) // 86400)
        if age > 0:
            pts += min(age, 30)
            if age >= 2:
                why.append("untouched %d days" % age)
    return pts, why


def _cards(home):
    from .dash import data
    cols, _ = data.board(home)
    return [c for col, cs in cols.items() if col != "Done" for c in cs]


def _overnight(home, cards, since):
    from . import views
    from .packet import Packet
    out = []
    for c in cards:
        root = c.get("root") or {}
        if not root.get("path"):
            continue
        for ev in views.timeline(Packet(root["path"]), since=since, limit=20):
            if ev["actor"] == "runner" or ev["kind"] in ("failure",):
                out.append({"project": c["name"], "t": ev["t"], "text": ev["text"],
                            "kind": ev["kind"]})
                break                   # the newest per project is enough
    return sorted(out, key=lambda x: x["t"], reverse=True)


def build(home, now=None):
    """Today's brief as a dict (and written to ``briefs/``). Deterministic."""
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).date()
    day = today.isoformat()
    cards = _cards(home)
    prev = next((load(home, d) for d in days(home) if d < day), None)
    since = (prev or {}).get("t") or now - 16 * 3600
    fb = feedback(home).get(day, {})
    needs = {}
    for c in cards:
        k = (c.get("ball") or {}).get("kind")
        if c["column"] == "Needs you" and k:
            needs[k] = needs.get(k, 0) + 1
        for it in c.get("sessions") or ():
            needs[it["type"]] = needs.get(it["type"], 0) + 1
    ranked = []
    for c in cards:
        if fb.get(c["name"]):
            continue
        pts, why = score(c, today, now)
        ranked.append({"project": c["name"], "score": pts, "why": why,
                       "next": c.get("intent") or "", "column": c["column"]})
    ranked.sort(key=lambda x: (-x["score"], x["project"]))
    housekeeping, focus = [], []
    history = [load(home, d) for d in days(home) if d < day][:REPEAT - 1]
    for r in ranked:
        streak = sum(1 for b in history if b and r["project"] in
                     [f["project"] for f in b.get("focus", [])])
        touched = any(c["name"] == r["project"] and c.get("last_end") and
                      c["last_end"].timestamp() > since for c in cards)
        if streak >= REPEAT - 1 and not touched:
            housekeeping.append({"project": r["project"],
                                 "text": "suggested %d briefs running and not touched: "
                                         "still %s?" % (REPEAT, "now" if "now" in r["why"]
                                                        else "worth doing")})
            continue
        if len(focus) < TOP:
            focus.append(r)
    handoff = [{"project": c["name"], "next": c["intent"]} for c in cards
               if c.get("intent") and (c.get("ball") or {}).get("kind") == "parked"
               and c["name"] not in [f["project"] for f in focus]][:3]
    for c in cards:
        if c.get("rot"):
            housekeeping.append({"project": c["name"], "text": "%s, untouched %d days" % (
                (c.get("plan") or {}).get("priority", "next"), c["rot"]["days"])})
    housekeeping += _estimates(home, cards, now)
    b = {"day": day, "t": now, "since": since, "overnight": _overnight(home, cards, since),
         "needs": needs, "focus": focus, "handoff": handoff, "housekeeping": housekeeping}
    try:                                # calendar fit (§9.5, plan F3f)
        from . import icsfeed
        cal = icsfeed.brief_part(home, now, needs.get("question", 0) + needs.get("review", 0))
    except Exception:                   # noqa: BLE001: a bad feed never stops the brief
        cal = None
    if cal:
        b["calendar"] = cal
    os.makedirs(_dir(home), exist_ok=True)
    fsutil.atomic_write(path(home, day), json.dumps(b, indent=1) + "\n")
    fsutil.atomic_write(path(home, day, "md"), render(b))
    return b


def _estimates(home, cards, now):
    """"You estimated spi-boot at 2d; 3 working days so far" (§9.6, plan F3a)."""
    from . import planning, registry
    out = []
    for c in cards:
        est = (c.get("plan") or {}).get("estimate")
        e = registry.get(c["name"], home) if est else None
        if e is None:
            continue
        try:
            a = planning.actuals(e, now)
        except Exception:               # noqa: BLE001: a project that won't read is skipped
            continue
        if a["over"]:
            out.append({"project": c["name"], "text": "you estimated %s; %d working days so "
                        "far" % (est, a["days"])})
    return out


def render(b):
    """The brief as Markdown (for the file, a push, or a mail)."""
    d = datetime.fromisoformat(b["day"])
    out = ["# %s · Focus" % d.strftime("%a %d %b"), ""]
    if b["overnight"]:
        out += ["## Since the last brief", ""]
        out += ["- **%s**: %s" % (o["project"], o["text"]) for o in b["overnight"]]
        out.append("")
    if b["needs"]:
        out += ["## Needs you", "", "- " + " · ".join(
            "%d %s" % (n, k) for k, n in sorted(b["needs"].items())), ""]
    cal = b.get("calendar")
    if cal and (cal["meetings"] or cal["fit"]):
        out += ["## Today's calendar", ""]
        out += ["- %s-%s %s" % (m["start"], m["end"], m["title"]) for m in cal["meetings"]]
        f = cal["fit"]
        if f and f["fits"]:
            out.append("- %d min before %s: %d review%s or answer%s fit" % (
                f["minutes"], f["at"], f["fits"], "" if f["fits"] == 1 else "s",
                "" if f["fits"] == 1 else "s"))
        out.append("")
    out += ["## Suggested focus", ""]
    if b["focus"]:
        for i, f in enumerate(b["focus"], 1):
            out.append("%d. **%s**: %s%s" % (i, f["project"], ", ".join(f["why"]) or "next up",
                                            " · Next: %s" % f["next"] if f["next"] else ""))
    else:
        out.append("Nothing open.")
    out.append("")
    if b["handoff"]:
        out += ["## Hand off before you start", ""]
        out += ["- **%s**: %s" % (h["project"], h["next"]) for h in b["handoff"]]
        out.append("")
    if b["housekeeping"]:
        out += ["## Housekeeping", ""]
        out += ["- **%s**: %s" % (h["project"], h["text"]) for h in b["housekeeping"]]
        out.append("")
    return "\n".join(out)


def due(home, cfg=None, now=None):
    """Is today's brief due (a weekday, past ``[focus] time``, not built yet)?"""
    now = time.time() if now is None else now
    dt = datetime.fromtimestamp(now)
    cfg = cfg or {}
    if cfg.get("off") or (dt.weekday() >= 5 and not cfg.get("weekends")):
        return False
    hh, _, mm = str(cfg.get("time") or TIME).partition(":")
    try:
        at = dt.replace(hour=int(hh), minute=int(mm or 0), second=0, microsecond=0)
    except ValueError:
        at = dt.replace(hour=8, minute=30, second=0, microsecond=0)
    return dt >= at and load(home, dt.date().isoformat()) is None


def maybe_build(home, cfg=None, now=None):
    """The board's loop: build today's brief when it is due. Returns it or None."""
    if due(home, cfg, now):
        return build(home, now)
    return None


def focus_line(home, now=None):
    """Today's focus in one line, for the day's Claude sessions, or ""."""
    now = time.time() if now is None else now
    b = load(home, datetime.fromtimestamp(now).date().isoformat())
    if not b or not b.get("focus"):
        return ""
    return "Today's focus on the board: " + ", ".join(f["project"] for f in b["focus"])


# --- the end of the day (§9.5) -------------------------------------------------------

def shutdown(home):
    """What to do before you stop: ``{"open": [card] (yours, to checkpoint),
    "night": [card] (could go to the runner overnight), "tomorrow": [card]}``."""
    cards = _cards(home)
    mine = [c for c in cards if c["column"] == "Working: you"]
    night = [c for c in cards if c.get("intent") and (c.get("ball") or {}).get("kind") in (
        "parked", "claimed")]
    tomorrow = sorted(cards, key=lambda c: -score(c, date.today(), time.time())[0])[:5]
    return {"open": mine, "night": night, "tomorrow": tomorrow}


def shutdown_hint(now=None):
    """Offer the shutdown after 17:00."""
    now = time.time() if now is None else now
    return datetime.fromtimestamp(now).hour >= 17
