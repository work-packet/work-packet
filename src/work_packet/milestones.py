"""Board milestones and their burn-down (docs/collaboration.md §9.3, plan F3d).

A board can have dated milestones ("rtl-freeze, Dec 1"). A project joins one
with its plan's ``milestone`` field, and inherits the date as a soft due when it
has none of its own (``effective_due``).

``$WPK_HOME/milestones/<board>.json``: ``[{"name", "date", "title", "made"}]``.
They are kept apart from ``boards/<name>.toml`` so that ``main``, which has no
file, can have them too.

The burn-down counts human and runner work together. The board's loop takes a
snapshot a day per milestone (``snap``), in
``$WPK_HOME/milestones/<board>/<name>.jsonl``: ``{"day", "runner", "yours",
"done", "projects"}``. ``runner``: plan items still to do in its open projects;
``yours``: items that need you, plus projects that are yours to work; ``done``:
its projects that are done. History starts the day it was made: no backfill.
"""

import json
import os
import time
from datetime import date

from . import fsutil, registry, schema


class MilestoneError(Exception):
    pass


def _dir(h):
    return os.path.join(h or registry.home(), "milestones")


def _path(board, h):
    return os.path.join(_dir(h), board + ".json")


def of_board(board, h=None):
    """The board's milestones, by date."""
    try:
        with open(_path(board, h)) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        return []
    d = [m for m in d if isinstance(m, dict) and m.get("name") and m.get("date")] \
        if isinstance(d, list) else []
    return sorted(d, key=lambda m: (m["date"], m["name"]))


def get(board, name, h=None):
    return next((m for m in of_board(board, h) if m["name"] == name), None)


def _save(board, ms, h):
    os.makedirs(_dir(h), exist_ok=True)
    fsutil.atomic_write(_path(board, h), json.dumps(ms, indent=1, sort_keys=True) + "\n")


def add(board, name, day, title=None, h=None, now=None):
    if not schema.is_name(name or ""):
        raise MilestoneError("a milestone's name is like rtl-freeze ([a-z0-9][a-z0-9_-]*)")
    try:
        day = date.fromisoformat(str(day)).isoformat()
    except ValueError:
        raise MilestoneError("its date is YYYY-MM-DD") from None
    ms = of_board(board, h)
    if any(m["name"] == name for m in ms):
        raise MilestoneError("%s has a milestone %s already" % (board, name))
    m = {"name": name, "date": day, "made": now or time.time()}
    if title and title.strip():
        m["title"] = title.strip()
    _save(board, ms + [m], h)
    return m


def remove(board, name, h=None):
    """Remove the milestone (projects keep the name in their plan; it no longer
    gives them a date)."""
    ms = of_board(board, h)
    if not any(m["name"] == name for m in ms):
        raise MilestoneError("no milestone %s on %s" % (name, board))
    _save(board, [m for m in ms if m["name"] != name], h)


def effective_due(plan, board, h=None, ms=None):
    """``(due, due_kind, milestone)``: the plan's own due, else its milestone's
    date as a soft due, else ``(None, None, milestone or None)``."""
    m = None
    if plan.get("milestone"):
        ms = of_board(board, h) if ms is None else ms
        m = next((x for x in ms if x["name"] == plan["milestone"]), None)
    if plan.get("due"):
        return plan["due"], plan.get("due_kind"), m
    if m:
        return m["date"], "soft", m
    return None, None, m


# --- the burn-down -------------------------------------------------------------------

def _snaps(board, name, h):
    return os.path.join(_dir(h), board, name + ".jsonl")


def snaps(board, name, h=None):
    out = []
    try:
        with open(_snaps(board, name, h)) as fp:
            for ln in fp:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("day"):
                    out.append(r)
    except OSError:
        pass
    return out


def count(cards, board, name, h=None):
    """The milestone's figures now, from the board's cards."""
    from . import forecast
    mine = [c for c in cards if c.get("board") == board
            and (c.get("plan") or {}).get("milestone") == name]
    runner = yours = done = 0
    for c in mine:
        if c.get("lifecycle") != "open":
            done += c.get("lifecycle") == "done"
            continue
        e = registry.get(c["name"], h)
        lr = forecast.left(e) if e else None
        runner += lr[0] if lr else 0
        ball = c.get("ball") or {}
        yours += (1 if ball.get("who") == "you" else 0) + len(c.get("sessions") or ())
    return {"runner": runner, "yours": yours, "done": done, "projects": len(mine),
            "names": [c["name"] for c in mine]}


def snap(cards, h=None, now=None):
    """Today's snapshot for every milestone not yet past, once a day. Returns how
    many were written."""
    h = h or registry.home()
    now = time.time() if now is None else now
    today = date.fromtimestamp(now).isoformat()
    n = 0
    for b in registry.boards(h):
        for m in of_board(b["name"], h):
            if m["date"] < today:
                continue
            got = snaps(b["name"], m["name"], h)
            if got and got[-1]["day"] == today:
                continue
            c = count(cards, b["name"], m["name"], h)
            p = _snaps(b["name"], m["name"], h)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a") as fp:
                fp.write(json.dumps({"day": today, "runner": c["runner"], "yours": c["yours"],
                                     "done": c["done"], "projects": c["projects"]},
                                    sort_keys=True) + "\n")
            n += 1
    return n


def chart(m, rows, width=420, height=120, pad=24):
    """An inline-SVG layout of the burn-down: ``{"w", "h", "runner", "yours",
    "ideal", "labels"}`` (polyline points), or None with no snapshot."""
    if not rows:
        return None
    d0 = date.fromisoformat(rows[0]["day"])
    d1 = max(date.fromisoformat(m["date"]), date.fromisoformat(rows[-1]["day"]))
    span = max((d1 - d0).days, 1)
    top = max(max(r["runner"] + r["yours"] for r in rows), 1)
    x = lambda d: round(pad + (width - 2 * pad) * (date.fromisoformat(d) - d0).days / span, 1)
    y = lambda v: round(height - pad - (height - 2 * pad) * v / top, 1)
    pts = lambda f: " ".join("%s,%s" % (x(r["day"]), y(f(r))) for r in rows)
    first = rows[0]["runner"] + rows[0]["yours"]
    return {"w": width, "h": height,
            "total": pts(lambda r: r["runner"] + r["yours"]),
            "yours": pts(lambda r: r["yours"]),
            "ideal": "%s,%s %s,%s" % (x(rows[0]["day"]), y(first), x(m["date"]), y(0)),
            "top": top, "start": rows[0]["day"], "end": m["date"],
            "x_end": x(m["date"]), "base": height - pad}
