"""The daily focus brief (docs/collaboration.md §9.4) and the end-of-day shutdown
(§9.5).

Each morning (``[focus] time``, weekdays) the board writes a brief that reads in a
minute: what happened overnight, what needs you, where to focus and why, what to
hand to the runner before you start, and housekeeping. It is kept, one per day, in
``$WPK_HOME/briefs/YYYY-MM-DD.json`` and ``.md``, so past briefs stay on the Desk.

A model writes it (briefagent.py, docs/focus-brief-review.md): the board, the
person's sessions and their repos are gathered into ``YYYY-MM-DD.bundle.json`` and
one call with no tools turns that into decisions, work to close out, uncommitted
work, focus by theme and housekeeping. The scored brief below is built every time
and stands when the model is off (``[focus] agent = false``) or fails.

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
import logging
import os
import re
import threading
import time
from datetime import date, datetime

from . import fsutil

log = logging.getLogger(__name__)

TIME = "08:30"
TOP = 3
PRIORITY_SCORE = {"now": 300, "next": 200, "later": 100, "someday": 0}
STALE_TURN_S = 24 * 3600    # a session waiting longer than this is not counted
DAY_FILE = re.compile(r"^\d{4}-\d\d-\d\d\.json$")   # not the .bundle.json beside it
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
    return sorted((x[:-5] for x in names if DAY_FILE.match(x)), reverse=True)[:n]


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


def _all_cards(home):
    from .dash import data
    cols, _ = data.board(home)
    return [c for cs in cols.values() for c in cs]


def _cards(home):
    return [c for c in _all_cards(home) if c.get("column") != "Done"]


def _overnight(home, cards, since):
    from . import views
    from .packet import Packet
    out = []
    for c in cards:
        root = c.get("root") or {}
        if not root.get("path"):
            continue
        pkt = Packet(root["path"])
        for ev in views.timeline(pkt, since=since, limit=20):
            if ev["actor"] == "runner" or ev["kind"] in ("failure",):
                text = ev["text"]
                if ": asked: " in text:     # the question in full, not cut short
                    from . import questions
                    qs = questions.of_packet(pkt)
                    if qs:
                        text = "%s: asked: %s" % (text.split(":")[0], " ".join(
                            " ".join(q["q"].split()) for q in qs))
                out.append({"project": c["name"], "t": ev["t"], "text": text,
                            "kind": ev["kind"]})
                break                   # the newest per project is enough
    return sorted(out, key=lambda x: x["t"], reverse=True)


def build(home, now=None, ask=None, agent=None):
    """Today's brief as a dict (and written to ``briefs/``).

    The scored brief always; then, unless ``[focus] agent = false`` (or ``agent``
    is False), a model writes the brief from a gathered bundle (briefagent.py) and
    its sections replace the scored ones. ``ask``: the model call, for tests."""
    now = time.time() if now is None else now
    all_cards = _all_cards(home)
    b = _scored(home, now, [c for c in all_cards if c.get("column") != "Done"])
    from . import briefagent
    cfg = briefagent.config(home)
    if agent is not False and (agent or cfg["agent"]):
        try:
            bundle = briefagent.gather(home, b["since"], now, cards=all_cards, cfg=cfg)
            briefagent.save_bundle(home, b["day"], bundle)
            got, cost, err = briefagent.write(home, bundle, cfg, ask_fn=ask)
        except Exception as e:          # noqa: BLE001: the scored brief stands
            got, cost, err = None, 0.0, "the brief could not be gathered: %s" % e
        if got:
            _take(b, got, all_cards, cfg["model"], cost)
        else:
            b["agent_error"] = err
    _save(home, b)
    return b


def _take(b, got, cards, model, cost):
    """The model's sections into ``b``; its focus becomes ``b["focus"]`` (one entry
    per theme, under its first project), so the overview and the repeat check work."""
    column = {c["name"]: c["column"] for c in cards}
    b["agent"] = dict(got, model=model, cost=round(cost, 4))
    b["scored_focus"] = b["focus"]
    b["focus"] = [{"project": f["projects"][0], "projects": f["projects"], "theme": f["theme"],
                   "why": [f["why"]] if f["why"] else [], "next": f["first_action"],
                   "column": column.get(f["projects"][0], "")} for f in got["focus"]]


def _save(home, b):
    os.makedirs(_dir(home), exist_ok=True)
    fsutil.atomic_write(path(home, b["day"]), json.dumps(b, indent=1) + "\n")
    fsutil.atomic_write(path(home, b["day"], "md"), render(b))


def apply_feedback(home, now=None):
    """After "not today" or "done already": today's brief without those projects.
    A scored brief is built again; a model's is filtered (no new model call)."""
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now).date().isoformat()
    b = load(home, day)
    if not b or not b.get("agent"):
        return build(home, now, agent=False)
    fb = feedback(home).get(day, {})
    b["focus"] = [f for f in b["focus"] if f["project"] not in fb]
    b["agent"]["focus"] = [f for f in b["agent"]["focus"] if f["projects"][0] not in fb]
    _save(home, b)
    return b


_building = threading.Lock()
_writing = None                         # when the model's brief was started, while it runs


def writing():
    """When the model started on today's brief (epoch), or None when it is not writing."""
    return _writing


def build_soon(home, now=None):
    """The scored brief now, the model's in a thread (it takes a few minutes), for
    the dash and the board's loop. False when one is already being built."""
    global _writing
    if not _building.acquire(blocking=False):
        return False
    try:
        build(home, now, agent=False)
    except Exception:                   # noqa: BLE001
        _building.release()
        raise
    if not briefagent_on(home):
        _building.release()
        return True
    _writing = time.time()

    def run():
        global _writing
        try:
            build(home, now)
        except Exception:               # noqa: BLE001
            log.exception("focus brief by the model failed")
        finally:
            _writing = None
            _building.release()
    threading.Thread(target=run, name="brief (model)", daemon=True).start()
    return True


def briefagent_on(home):
    from . import briefagent
    return bool(briefagent.config(home)["agent"])


def _scored(home, now, cards):
    """The brief from the board's own data, with no model (the fallback)."""
    today = datetime.fromtimestamp(now).date()
    day = today.isoformat()
    prev = next((load(home, d) for d in days(home) if d < day), None)
    since = (prev or {}).get("t") or now - 16 * 3600
    fb = feedback(home).get(day, {})
    needs, who = {}, {}
    for c in cards:
        k = (c.get("ball") or {}).get("kind")
        if c["column"] == "Needs you" and k:
            needs[k] = needs.get(k, 0) + 1
            who.setdefault(k, []).append(c["name"])
        for it in c.get("sessions") or ():
            if it["type"] == "your turn" and now - (it.get("since") or now) > STALE_TURN_S:
                continue                # a session left waiting for days: not a demand
            needs[it["type"]] = needs.get(it["type"], 0) + 1
            who.setdefault(it["type"], []).append(c["name"])
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
         "needs": needs, "needs_who": who, "focus": focus, "handoff": handoff,
         "housekeeping": housekeeping}
    try:                                # calendar fit (§9.5, plan F3f)
        from . import icsfeed
        cal = icsfeed.brief_part(home, now, needs.get("question", 0) + needs.get("review", 0))
    except Exception:                   # noqa: BLE001: a bad feed never stops the brief
        cal = None
    if cal:
        b["calendar"] = cal
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


def _hours(m):
    return "%dm" % m if m < 60 else "%.1fh" % (m / 60.0)


def _calendar(b):
    cal, out = b.get("calendar"), []
    if cal and (cal["meetings"] or cal["fit"]):
        out += ["## Today's calendar", ""]
        out += ["- %s-%s %s" % (m["start"], m["end"], m["title"]) for m in cal["meetings"]]
        f = cal["fit"]
        if f and f["fits"]:
            out.append("- %d min before %s: %d review%s or answer%s fit" % (
                f["minutes"], f["at"], f["fits"], "" if f["fits"] == 1 else "s",
                "" if f["fits"] == 1 else "s"))
        out.append("")
    return out


def live_rows(home, b, cards=None):
    """For the dash: the model's Decide and Close out rows with what can be done
    about them now. ``{"decide": [{"project", "wpid", "items", "questions"}],
    "close_out": [{"project", "action", "wpid", "done"}]}``. ``questions`` are the
    packet's open ones (answered together: an answer hands the packet off), [] once
    answered or for a question asked in a session."""
    from . import questions
    from .packet import Packet
    a = (b or {}).get("agent")
    if not a:
        return None
    cards = _all_cards(home) if cards is None else cards
    by = {c["name"]: c for c in cards}

    def root(name):
        r = (by.get(name) or {}).get("root") or {}
        return r.get("wpid"), r.get("path")
    decide, seen = [], {}
    for x in a.get("decide") or ():
        if x["project"] in seen:
            seen[x["project"]]["items"].append(x)
            continue
        wpid, path = root(x["project"])
        qs = questions.of_packet(Packet(path)) if path else []
        row = {"project": x["project"], "wpid": wpid, "items": [x],
               "questions": [{"id": q["id"], "q": q["q"], "choices": q["choices"],
                              "recommend": q["recommend"] or ""} for q in qs]}
        seen[x["project"]] = row
        decide.append(row)
    close = []
    for x in a.get("close_out") or ():
        wpid, _ = root(x["project"])
        c = by.get(x["project"]) or {}
        close.append(dict(x, wpid=wpid, done=c.get("column") == "Done"
                          or c.get("lifecycle") in ("done", "dropped")))
    runs = []
    for i, x in enumerate(a.get("runs") or ()):
        wpid, _ = root(x["project"])
        state = ((by.get(x["project"]) or {}).get("root") or {}).get("state")
        runs.append(dict(x, i=i, wpid=wpid, state=state,
                         can=bool(wpid) and state in RUN_STATES and not x.get("launched")))
    return {"decide": decide, "close_out": close, "runs": runs}


RUN_STATES = ("COMPLETED", "PAUSED", "FAILED")


def launch(home, day, picks, by=None, now=None):
    """Hand the picked proposed runs to the runner: ``picks`` maps a run's index to
    its instruction (as the person left it). Each goes through
    ``actions.continue_`` and is recorded on the run in the day's brief (``launched``:
    when, by whom, the instruction sent and the outcome), so the brief keeps what was
    done from it. Returns ``[(project, Outcome)]``."""
    from . import actions, executor, registry
    from . import layout
    from .packet import Packet
    now = time.time() if now is None else now
    b = load(home, day)
    runs = ((b or {}).get("agent") or {}).get("runs") or []
    out = []
    for i, text in sorted(picks.items()):
        if not (0 <= i < len(runs)):
            continue
        r = runs[i]
        if r.get("launched"):
            out.append((r["project"], executor.Outcome(executor.USAGE, "already handed off")))
            continue
        e = registry.get(r["project"], home)
        if e is None:
            out.append((r["project"], executor.Outcome(executor.USAGE, "no such project")))
            continue
        text = (text or "").strip() or r["instruction"]
        pkt = Packet(layout.run_dir(e["path"], e["root"]))
        try:
            o = actions.continue_(pkt, text, note="Proposed by the focus brief of %s: %s" % (
                day, r.get("title") or ""), by=by)
        except Exception as ex:         # noqa: BLE001: one bad packet does not stop the rest
            o = executor.Outcome(executor.USAGE, str(ex))
        if o.code == executor.OK:
            r["launched"] = {"t": now, "by": by or executor._who(), "instruction": text,
                             "edited": text != r["instruction"], "outcome": o.msg}
        out.append((r["project"], o))
    if b:
        _save(home, b)
    return out


def _render_agent(b, skip=()):
    a = b["agent"]
    d = datetime.fromisoformat(b["day"])
    out = [] if "head" in skip else ["# %s · Focus" % d.strftime("%a %d %b"), ""]
    if a.get("headline") and "head" not in skip:
        out += ["_%s_" % a["headline"], ""]
    if a["decide"] and "decide" not in skip:
        out += ["## Decide", ""]
        for x in a["decide"]:
            opts = " / ".join(x["options"])
            out.append("- **%s**%s%s: %s%s%s" % (
                x["project"], " (asked in a session)" if x["from_session"] else "",
                ", waiting %s" % x["waiting"] if x["waiting"] else "", x["question"],
                " Options: %s." % opts if opts else "",
                " Recommend: %s" % x["recommend"] if x["recommend"] else ""))
        out.append("")
    if a["close_out"] and "close_out" not in skip:
        out += ["## Close out", ""]
        out += ["- **%s**: %s" % (x["project"], x["action"]) for x in a["close_out"]]
        out.append("")
    if a.get("runs") and "runs" not in skip:
        out += ["## Proposed runs", ""]
        for x in a["runs"]:
            done = x.get("launched")
            out.append("- **%s**: %s%s%s" % (
                x["project"], x["title"], " _(pushes or sends outside)_" if x["outward"] else "",
                " · handed off %s" % time.strftime("%H:%M", time.localtime(done["t"]))
                if done else ""))
            out += ["  > " + ln for ln in x["instruction"].splitlines() if ln.strip()]
        out.append("")
    out += ["## Suggested focus", ""]
    for i, f in enumerate(a["focus"], 1):
        more = [p for p in f["projects"] if p != f["theme"]]
        out.append("%d. **%s**%s: %s%s" % (
            i, f["theme"], " (%s)" % ", ".join(more) if more else "", f["why"] or "next up",
            " · First: %s" % f["first_action"] if f["first_action"] else ""))
    if not a["focus"]:
        out.append("Nothing suggested.")
    out.append("")
    if a["uncommitted"]:
        out += ["## Uncommitted", ""]
        for x in a["uncommitted"]:
            out.append("- **%s**%s: %s%s" % (
                x["project"] or x["repo"], " (`%s`)" % x["repo"] if x["project"] and x["repo"]
                else "", x["what"], " → %s" % x["action"] if x["action"] else ""))
        out.append("")
    if a["yesterday"]:
        out += ["## Since the last brief", ""]
        for x in a["yesterday"]:
            out.append("- **%s**%s: %s" % (
                x["theme"], " (%s)" % _hours(x["minutes"]) if x["minutes"] else "", x["what"]))
        out.append("")
    out += _calendar(b)
    if a["housekeeping"]:
        out += ["## Housekeeping", ""]
        out += ["- %s%s" % ("**%s**: " % x["project"] if x["project"] else "", x["text"])
                for x in a["housekeeping"]]
        out.append("")
    out.append("<small>Written by %s from `briefs/%s.bundle.json` ($%.2f).</small>" % (
        a.get("model") or "a model", b["day"], a.get("cost") or 0.0))
    return "\n".join(out)


def render(b, skip=()):
    """The brief as Markdown (for the file, a push, or a mail). ``skip``: sections
    of a model's brief left out (the dash draws "decide" and "close_out" itself)."""
    if b.get("agent"):
        return _render_agent(b, skip)
    d = datetime.fromisoformat(b["day"])
    out = ["# %s · Focus" % d.strftime("%a %d %b"), ""]
    if b.get("agent_error"):
        out += ["_The model's brief failed (%s); this is the scored one._" % b["agent_error"], ""]
    if b["overnight"]:
        out += ["## Since the last brief", ""]
        out += ["- **%s**: %s" % (o["project"], o["text"]) for o in b["overnight"]]
        out.append("")
    if b["needs"]:
        who = b.get("needs_who") or {}
        out += ["## Needs you", ""]
        out += ["- %d %s%s" % (n, k, ": " + ", ".join(who[k]) if who.get(k) else "")
                for k, n in sorted(b["needs"].items())]
        out.append("")
    out += _calendar(b)
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
    """The board's loop: build today's brief when it is due: the scored one now, the
    model's in a thread (so the loop does not wait on it). Returns it or None."""
    if due(home, cfg, now) and build_soon(home, now):
        return load(home, datetime.fromtimestamp(time.time() if now is None else now)
                    .date().isoformat())
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
