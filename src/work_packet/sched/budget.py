"""The budget: spend against pace, a ceiling per class (docs/scheduler.md §4).

Spend is read from each step's ``meta.json``, never estimated; a step that
is still running holds a reservation, its estimate, until its figures land.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import fsutil, layout, schema
from .config import sched_dir
from .gates import Reason

MEASURES = ("usd", "tokens", "quota")
DEFAULT_STEP = {"usd": 0.50, "tokens": 2_000_000.0, "quota": 0.005}
HIGH_SHARE = 0.95
PACKET_HISTORY, PROJECT_HISTORY = 10, 20
QUOTA_WINDOWS = {"seven_day": timedelta(days=7), "five_hour": timedelta(hours=5)}


# --- the ledger: every step's spend, from meta.json ------------------------------

@dataclass
class Rec:
    project: str
    wpid: str
    step: int
    failed: bool
    end: Optional[str]
    cost: Optional[float] = None
    tokens: dict = field(default_factory=dict)
    quota: dict = field(default_factory=dict)

    def amount(self, measure, cache_read_weight=0.1, window="seven_day"):
        """What the step spent in ``measure``, or None if it did not say."""
        if measure == "usd":
            return self.cost
        if measure == "tokens":
            t = self.tokens
            if not t:
                return None
            return float((t.get("input_tokens") or 0) + (t.get("cache_creation_input_tokens") or 0)
                         + (t.get("output_tokens") or 0)
                         + cache_read_weight * (t.get("cache_read_input_tokens") or 0))
        q = (self.quota or {}).get(window)
        if not q or q.get("last") is None:
            return None
        d = q["last"] - q.get("first", 0)
        return float(d if d >= 0 else q["last"])


_CACHE = {}          # meta.json path -> (mtime_ns, Rec or None)


def _read(path, project, wpid, name):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size, st.st_ino)   # a rewrite within one tick changes these
    hit = _CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    rec = None
    try:
        with open(path, encoding="utf-8") as fp:
            m = json.load(fp)
        n, _, run = name.partition(".failed-")
        rec = Rec(project=project, wpid=wpid, step=int(n), failed=bool(run), end=m.get("end"),
                  cost=m.get("cost_usd") if isinstance(m.get("cost_usd"), (int, float)) else None,
                  tokens=m.get("tokens") or {}, quota=m.get("quota") or {})
    except (OSError, ValueError, TypeError):
        rec = None
    _CACHE[path] = (key, rec)
    return rec


def ledger(entries):
    """Every step attempt of ``entries`` that has a ``meta.json``, oldest end first.
    Parsed files are cached by mtime, so a pass rereads only new steps."""
    out = []
    for e in entries:
        pdir = layout.runs_dir(e["path"])
        try:
            wpids = [w for w in os.listdir(pdir) if schema.is_wpid(w)]
        except OSError:
            continue
        for w in wpids:
            sdir = os.path.join(pdir, w, "steps")
            try:
                names = os.listdir(sdir)
            except OSError:
                continue
            for n in names:
                if schema.parse_step_dir(n) is None:
                    continue
                r = _read(os.path.join(sdir, n, "meta.json"), e["name"], w, n)
                if r is not None:
                    out.append(r)
    return sorted(out, key=lambda r: (r.end or "", r.project, r.wpid, r.step))


# --- periods and pace --------------------------------------------------------------

def _zone(name):
    if name:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    return datetime.now().astimezone().tzinfo


def period_bounds(kind, now, tz):
    """(start, end) of the ``day``, ``week`` (from Monday) or ``month`` holding
    ``now``, at local midnight in ``tz``, as aware UTC datetimes."""
    local = now.astimezone(tz)
    d = local.date()
    if kind == "day":
        s, e = d, d + timedelta(days=1)
    elif kind == "week":
        s = d - timedelta(days=d.weekday())
        e = s + timedelta(days=7)
    elif kind == "month":
        s = d.replace(day=1)
        e = (s + timedelta(days=32)).replace(day=1)
    else:
        raise ValueError(kind)

    def midnight(day):
        return datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
    return midnight(s), midnight(e)


def _weight(t, shape, tz):
    if not shape:
        return 1.0
    local = t.astimezone(tz)
    w = 1.0
    if shape.get("weekday"):
        w *= shape["weekday"][local.weekday()]
    if shape.get("hour"):
        w *= shape["hour"][local.hour]
    return w


def fraction(start, end, t, shape=None, tz=timezone.utc):
    """How much of the period's budget pace allows by ``t``: elapsed / length,
    or with ``shape`` the weighted share (per weekday and per hour)."""
    if t <= start:
        return 0.0
    if t >= end:
        return 1.0
    if not shape:
        return (t - start).total_seconds() / (end - start).total_seconds()
    total = done = 0.0
    step = timedelta(hours=1)
    cur = start
    while cur < end:
        nxt = min(end, cur + step)
        w = _weight(cur, shape, tz) * (nxt - cur).total_seconds()
        total += w
        if cur < t:
            done += _weight(cur, shape, tz) * (min(t, nxt) - cur).total_seconds()
        cur = nxt
    return done / total if total else 0.0


# --- the budget ---------------------------------------------------------------------

def _p75(xs):
    xs = sorted(xs)
    if not xs:
        return None
    k = 0.75 * (len(xs) - 1)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


@dataclass
class Window:
    name: str            # period | seven_day | five_hour
    start: datetime
    end: datetime
    spent: float
    reserved: float = 0.0
    stale: Optional[str] = None      # why the reading cannot be trusted


def fmt(measure, v):
    if v is None:
        return "-"
    if measure == "usd":
        return "$%.2f" % v
    if measure == "tokens":
        return "%.1fM" % (v / 1e6) if abs(v) >= 1e5 else "%dk" % round(v / 1e3)
    return "%.1f%%" % (100 * v)


class Budget:
    """The budget for one fill: spend, pace, ceilings and the running reservations."""

    def __init__(self, cfg, now, entries, records, projs, limits=None, h=None, recs=None):
        b = cfg["budget"]
        self.h = h
        self.measure = b["measure"]
        self.period = b.get("period", "week")
        self.amount = float(limits.budget_amount if limits is not None and
                            limits.budget_amount is not None else b["amount"])
        self.slack = float(b["slack"]) * self.amount
        self.hard_cap = float(b["hard_cap"]) or self.amount
        self.crw = float(b["cache_read_weight"])
        self.default_step = float(b["default_step"]) or DEFAULT_STEP[self.measure]
        self.shape = b.get("shape") or {}
        self.tz_name = b.get("tz") or cfg.get("tz") or ""
        self.tz = _zone(self.tz_name)
        self.stale_after = schema.parse_duration(b.get("stale_after") or "6h")
        self.now = now
        self.projs = projs
        self.recs = recs if recs is not None else ledger(entries)
        self.windows = self._windows()
        self._history()
        self.jobs = [r for r in records if r.kind == "step"]
        for r in self.jobs:
            self._hold(self.estimates_of(r.project, r.wpid))
        self.gated = []

    # -- spend ---------------------------------------------------------------

    def _windows(self):
        now = self.now
        if self.measure != "quota":
            s, e = period_bounds(self.period, now, self.tz)
            cut = schema.format_timestamp(s)
            spent = sum(r.amount(self.measure, self.crw) or 0 for r in self.recs
                        if (r.end or "") >= cut)
            return [Window("period", s, e, spent)]
        out = []
        for name, length in QUOTA_WINDOWS.items():
            got = None
            for r in self.recs:
                q = (r.quota or {}).get(name)
                if q and q.get("last") is not None and r.end:
                    got = (r.end, q)
            if got is None:
                if name == "seven_day":
                    out.append(Window(name, now - length, now, 0.0, stale="no reading yet"))
                continue
            at, q = got
            resets = q.get("resets_at")
            end = datetime.fromtimestamp(resets, timezone.utc) if resets else None
            if end is not None and end <= now:            # rolled over since: nothing used
                while end <= now:
                    end += length
                out.append(Window(name, end - length, end, 0.0))
                continue
            if end is None:
                end = schema.parse_timestamp(at) + length
            w = Window(name, end - length, end, float(q["last"]))
            age = (now - schema.parse_timestamp(at)).total_seconds()
            if age > self.stale_after:
                w.stale = "the reading is %dh old" % (age // 3600)
            out.append(w)
        return out

    def _history(self):
        self.by_packet, self.by_project = {}, {}
        for name in ("seven_day", "five_hour") if self.measure == "quota" else ("period",):
            for r in self.recs:
                v = r.amount(self.measure, self.crw, name if name != "period" else "seven_day")
                if v is None:
                    continue
                self.by_packet.setdefault((name, r.wpid), []).append(v)
                self.by_project.setdefault((name, r.project), []).append(v)

    # -- estimates and reservations ------------------------------------------

    def _estimate(self, window, project, wpid):
        xs = self.by_packet.get((window, wpid), [])[-PACKET_HISTORY:]
        est = _p75(xs) if xs else None
        if est is None:
            ys = self.by_project.get((window, project), [])[-PROJECT_HISTORY:]
            est = _p75(ys) if ys else None
        if est is None:
            est = self.default_step if window != "five_hour" else self.default_step * 4
        if self.measure == "usd":
            p = self.projs.get(project)
            cap = (p.limits.get("step_budget_usd") if p is not None else None)
            if cap:
                est = min(est, float(cap))
        return float(est)

    def estimates_of(self, project, wpid):
        """{window name: estimate} for the packet's next step."""
        return {w.name: self._estimate(w.name, project, wpid) for w in self.windows}

    def estimate(self, it):
        return self.estimates_of(it.project, it.wpid)[self.windows[0].name]

    def _hold(self, est):
        for w in self.windows:
            w.reserved += est.get(w.name, 0.0)

    def reserve(self, it):
        """``it`` is about to start in this fill: hold its estimate."""
        self._hold(self.estimates_of(it.project, it.wpid))
        self.jobs.append(it)

    # -- ceilings and the gate -----------------------------------------------

    def pace(self, w, t=None):
        return self.amount * fraction(w.start, w.end, t or self.now,
                                      self.shape if w.name != "five_hour" else None, self.tz)

    def ceiling(self, cls, w, t=None):
        if cls == "urgent":
            return self.hard_cap
        if cls == "high":
            return HIGH_SHARE * self.amount
        p = self.pace(w, t)
        return {"normal": p + self.slack, "low": p, "background": p - self.slack}[cls]

    def _clears(self, cls, w, need):
        """When the class's ceiling reaches ``need``: pace catching up, or the reset."""
        if cls in ("urgent", "high") or self.ceiling(cls, w, w.end) < need:
            return w.end
        lo, hi = self.now, w.end
        for _ in range(40):
            mid = lo + (hi - lo) / 2
            if self.ceiling(cls, w, mid) >= need:
                hi = mid
            else:
                lo = mid
        return hi

    def gate(self, it, ctx=None):
        cls = it.cls                       # the real class: aging is for order only
        est = self.estimates_of(it.project, it.wpid)
        for w in self.windows:
            if w.stale and cls not in ("urgent", "high"):
                if self.jobs or cls == "background":
                    return Reason("budget", "budget: quota %s; %s waits for a step to "
                                  "read it again" % (w.stale, cls))
                continue                   # nothing runs: this step reads it again
            need = w.spent + w.reserved + est[w.name]
            ceil = self.ceiling(cls, w)
            if need <= ceil:
                continue
            when = self._clears(cls, w, need)
            self._note_gated(cls, w, ceil)
            what = "the %s window" % w.name.replace("_", "-") if w.name != "period" \
                else "this %s" % self.period
            if cls == "urgent":
                text = "budget: the hard cap (%s) for %s is reached" % (
                    fmt(self.measure, self.hard_cap), what)
            elif cls == "high":
                text = "budget: %d%% of %s's %s is spent" % (
                    HIGH_SHARE * 100, what, fmt(self.measure, self.amount))
            else:
                text = "budget: %s waits until pace reaches %s (spent %s, reserved %s%s)" % (
                    cls, fmt(self.measure, need - (ceil - self.pace(w))),
                    fmt(self.measure, w.spent), fmt(self.measure, w.reserved),
                    ", in the five-hour window" if w.name == "five_hour" else "")
            return Reason("budget", text, schema.format_timestamp(when))
        return None

    def _note_gated(self, cls, w, ceil):
        """A ``gate`` event the first time each class is gated in a period."""
        if self.h is None:
            return
        from . import events
        path = os.path.join(sched_dir(self.h), "gated.json")
        key = schema.format_timestamp(w.start)
        try:
            with open(path) as fp:
                d = json.load(fp)
        except (OSError, ValueError):
            d = {}
        seen = d.get(w.name) if d.get(w.name + "_period") == key else []
        if cls in seen:
            return
        d[w.name], d[w.name + "_period"] = sorted(set(seen) | {cls}), key
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fsutil.atomic_write(path, json.dumps(d) + "\n")
        events.append("gate", h=self.h, cls=cls, window=w.name, period=key,
                      spent=round(w.spent, 6), reserved=round(w.reserved, 6),
                      ceiling=round(ceil, 6), measure=self.measure)

    # -- for wpk sched and the board -----------------------------------------

    def describe(self):
        w = self.windows[0]
        m = self.measure
        out = {"measure": m, "amount": self.amount, "slack": self.slack,
               "hard_cap": self.hard_cap, "shape": self.shape, "tz": self.tz_name,
               "windows": []}
        for x in self.windows:
            out["windows"].append({
                "name": x.name, "start": schema.format_timestamp(x.start),
                "end": schema.format_timestamp(x.end), "spent": x.spent,
                "reserved": x.reserved, "pace": self.pace(x), "stale": x.stale,
                "ceilings": {c: self.ceiling(c, x) for c in
                             ("urgent", "high", "normal", "low", "background")}})
        out["line"] = "%s: spent %s of %s, pace %s, reserved %s (%s to %s)%s" % (
            m if m != "quota" else "weekly quota", fmt(m, w.spent), fmt(m, self.amount),
            fmt(m, self.pace(w)), fmt(m, w.reserved), schema.format_timestamp(w.start),
            schema.format_timestamp(w.end), "; %s" % w.stale if w.stale else "")
        classes = []
        for c in ("urgent", "high", "normal", "low", "background"):
            room = self.ceiling(c, w) - w.spent - w.reserved
            classes.append({"class": c, "ceiling": self.ceiling(c, w), "room": room,
                            "line": "ceiling %s, room %s%s" % (
                                fmt(m, self.ceiling(c, w)), fmt(m, max(0.0, room)),
                                "" if room > 0 else "  GATED")})
        out["classes"] = classes
        if len(self.windows) > 1:
            f = self.windows[1]
            out["line"] += "; 5-hour: %s, pace %s" % (fmt(m, f.spent), fmt(m, self.pace(f)))
        return out


def gate_for(ctx, records, h, entries=None, recs=None):
    """The budget gate for a fill, or None when ``[sched.budget] measure`` is unset."""
    b = ctx.cfg.get("budget") or {}
    if b.get("measure") not in MEASURES or not b.get("amount") and not (
            ctx.limits is not None and ctx.limits.budget_amount):
        return None
    if entries is None:
        entries = [p.entry for p in ctx.projs.values()]
    return Budget(ctx.cfg, ctx.now, entries, records, ctx.projs, ctx.limits, h, recs)


def write_spend(h, budget):
    """``sched/spend.json``: the last figures, for readers that do not compute."""
    os.makedirs(sched_dir(h), exist_ok=True)
    fsutil.atomic_write(os.path.join(sched_dir(h), "spend.json"),
                        json.dumps(budget.describe(), indent=1) + "\n")


# --- project caps (§4.5) ----------------------------------------------------------

def caps_set(projs):
    keys = ("budget_usd_per_day", "budget_quota_per_week", "max_steps_per_hour")
    return any(p.limits.get(k) for p in projs.values() for k in keys)


def over_cap(it, proj, recs, now, tz):
    """Why ``it`` must be held by its project's caps, with the figures, or None."""
    lim = proj.limits
    mine = [r for r in recs if r.project == it.project and r.end]
    cap = lim.get("max_steps_per_hour") or 0
    if cap:
        cut = schema.format_timestamp(now - timedelta(hours=1))
        n = sum(1 for r in mine if r.wpid == it.wpid and r.end >= cut)
        if n >= cap:
            return "limit: max_steps_per_hour %d reached (%d in the last hour)" % (cap, n)
    cap = lim.get("budget_usd_per_day") or 0
    if cap:
        start, _ = period_bounds("day", now, tz)
        cut = schema.format_timestamp(start)
        spent = sum(r.cost or 0 for r in mine if r.end >= cut)
        if spent >= cap:
            return "limit: budget_usd_per_day $%.2f reached ($%.2f today)" % (cap, spent)
    cap = lim.get("budget_quota_per_week") or 0
    if cap:
        cut = schema.format_timestamp(now - timedelta(days=7))
        used = sum(r.amount("quota") or 0 for r in mine if r.end >= cut)
        if used >= cap:
            return "limit: budget_quota_per_week %s reached (%s in 7 days)" % (
                fmt("quota", cap), fmt("quota", used))
    return None
