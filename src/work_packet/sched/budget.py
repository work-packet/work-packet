"""The budget: spend against pace, a ceiling per class (docs/scheduler.md §4).

Spend is read from each step's ``meta.json``, never estimated; a step that
is still running holds a reservation, its estimate, until its figures land.
"""

import fnmatch
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import fsutil, layout, plugins, schema
from .config import sched_dir
from .gates import Reason

MEASURES = ("usd", "tokens", "quota", "provider")
DEFAULT_STEP = {"usd": 0.50, "tokens": 2_000_000.0, "quota": 0.005}
HIGH_SHARE = 0.95
PACKET_HISTORY, PROJECT_HISTORY = 10, 20
log = logging.getLogger(__name__)
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
    start: Optional[str] = None
    route: str = ""                  # account@host (meta.json route)

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


def _route_of(r):
    if not isinstance(r, dict):
        return ""
    return "%s@%s" % (r.get("account") or "unknown", r.get("host") or "default")


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
                  tokens=m.get("tokens") or {}, quota=m.get("quota") or {},
                  start=m.get("start"), route=_route_of(m.get("route")))
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


# --- a budget provider (design E6): amount, period and spend from elsewhere ---------

GROUP = "work_packet.budget"
READING = "budget-reading.json"


class NeedsLogin(Exception):
    """The provider's credential is missing or expired; a person must renew it."""


class Unavailable(Exception):
    """The provider cannot answer now (portal down, timeout)."""


@dataclass
class BudgetReading:
    amount: float               # the period's budget, USD
    spent: float                # spend the provider knows, all sources
    period_start: datetime
    period_end: datetime
    tz: str                     # the billing zone, for period bounds
    as_of: datetime             # spend is complete up to here
    stage: Optional[str] = None  # the policy's label, e.g. "100%"
    blocked: bool = False       # new calls will be refused
    url: Optional[str] = None   # where a person sees and acts on it
    notes: list = field(default_factory=list)   # warnings to show

    _TIMES = ("period_start", "period_end", "as_of")

    def to_json(self):
        d = asdict(self)
        for k in self._TIMES:
            d[k] = schema.format_timestamp(d[k])
        d["notes"] = list(d["notes"] or [])
        return d

    @classmethod
    def from_json(cls, d):
        d = dict(d)
        for k in cls._TIMES:
            d[k] = schema.parse_timestamp(d[k])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class BudgetProvider:
    """The base of a ``work_packet.budget`` plugin (a class or an instance)."""

    def changed(self):
        """A cheap check that a new reading may differ; may always say True."""
        return True

    def read(self):
        """A BudgetReading; raises NeedsLogin or Unavailable."""
        raise NotImplementedError


def provider(name):
    """The loaded provider called ``name``, or None."""
    obj = plugins.loaded(GROUP).get(name)
    return obj() if isinstance(obj, type) else obj


def renew_command(name):
    """The command that renews provider ``name``'s login: its ``renew``, else that
    of the credential it names in ``credential`` (or its own name); "" if none."""
    from .. import credentials
    obj = plugins.loaded(GROUP).get(name)
    return getattr(obj, "renew", "") or credentials.renew_command(
        getattr(obj, "credential", None) or name)


def load_reading(h):
    """``sched/budget-reading.json``: {reading: BudgetReading or None, read_at, error,
    provider}, or None if no reading was ever tried."""
    try:
        with open(os.path.join(sched_dir(h), READING), encoding="utf-8") as fp:
            d = json.load(fp)
        d["reading"] = BudgetReading.from_json(d["reading"]) if d.get("reading") else None
        return d
    except (OSError, ValueError, TypeError, KeyError):
        return None


def refresh(h, name, now, p=None):
    """Ask provider ``name`` (or the instance ``p``) for a reading and cache it. A
    failure keeps the last reading and records why (``error``; ``needs_login``)."""
    old = load_reading(h) or {}
    d = {"provider": name, "reading": old.get("reading") if old.get("provider") == name else None,
         "read_at": old.get("read_at"), "tried_at": schema.format_timestamp(now),
         "error": None, "needs_login": False}
    if p is None:
        p = provider(name)
    try:
        if p is None:
            raise Unavailable("budget provider %r is not loaded (wpk doctor)" % name)
        r = p.read()
        if not isinstance(r, BudgetReading):
            raise Unavailable("budget provider %r returned %r" % (name, type(r).__name__))
        d["reading"], d["read_at"] = r, schema.format_timestamp(now)
    except NeedsLogin as e:
        d["error"], d["needs_login"] = str(e) or "needs login", True
    except Exception as e:                # a plugin's failure must not stop wpkd
        d["error"] = str(e) or type(e).__name__
    out = dict(d, reading=d["reading"].to_json() if d["reading"] else None)
    os.makedirs(sched_dir(h), exist_ok=True)
    fsutil.atomic_write(os.path.join(sched_dir(h), READING), json.dumps(out, indent=1) + "\n")
    return d


CHANGED_EVERY = timedelta(minutes=5)    # how often wpkd asks changed()
READ_EVERY = timedelta(hours=1)         # read at least this often


class Poller:
    """wpkd's cadence for the provider (design E6): ``changed()`` every few minutes,
    ``read()`` when it says so, after an error, or at least hourly. The last try
    is in the cache, so a restarted wpkd does not read again at once."""

    def __init__(self, h):
        self.h = h
        self.name, self.p, self.checked = None, None, None

    def poll(self, cfg, now):
        """True when a reading was tried (the gates may have changed)."""
        b = cfg.get("budget") or {}
        name = b.get("provider") if b.get("measure") == "provider" else None
        if not name:
            return False
        if name != self.name:
            self.name, self.p, self.checked = name, provider(name), None
        c = load_reading(self.h)
        tried = c.get("tried_at") if c and c.get("provider") == name else None
        if tried is not None and now - schema.parse_timestamp(tried) < READ_EVERY:
            if self.checked is not None and now - self.checked < CHANGED_EVERY:
                return False
            self.checked = now
            if not c.get("error"):
                try:
                    if self.p is not None and not self.p.changed():
                        return False
                except Exception as e:     # read() will record the failure
                    log.warning("budget provider %s: changed() failed: %s", name, e)
        self.checked = now
        d = refresh(self.h, name, now, self.p)
        if d["error"]:
            log.warning("budget provider %s: %s", name, d["error"])
        return True


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
        self.via = None                  # provider name, when measure = "provider"
        self.cached = None               # its last cached reading (load_reading)
        self.route = b.get("route") or ""
        if self.measure == "provider":
            self.measure, self.via = "usd", b.get("provider") or ""
            self.cached = load_reading(h) if h is not None else None
            if self.cached and self.cached.get("provider") != self.via:
                self.cached = None
        self.reading = (self.cached or {}).get("reading")
        self.period = b.get("period", "week")
        self.amount = float(limits.budget_amount if limits is not None and
                            limits.budget_amount is not None else b["amount"])
        if self.reading is not None:
            self.amount = float(self.reading.amount)
        self.slack = float(b["slack"]) * self.amount
        self.hard_cap = float(b["hard_cap"]) or self.amount
        self.crw = float(b["cache_read_weight"])
        self.default_step = float(b["default_step"]) or DEFAULT_STEP[self.measure]
        self.shape = b.get("shape") or {}
        self.tz_name = (self.reading.tz if self.reading is not None and self.reading.tz
                        else b.get("tz") or cfg.get("tz") or "")
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
        if self.via is not None:
            return [self._provider_window()]
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

    def _provider_window(self):
        """The period and spend of the provider's reading, plus the local spend of
        steps that started after its ``as_of`` (portals lag; only wpk sees those)."""
        r, now = self.reading, self.now
        mine = [x for x in self.recs if not self.route or fnmatch.fnmatchcase(x.route, self.route)]
        if r is None:
            s, e = period_bounds(self.period, now, self.tz)
            cut = schema.format_timestamp(s)
            spent = sum(x.cost or 0 for x in mine if (x.end or "") >= cut)
            err = (self.cached or {}).get("error")
            return Window("period", s, e, spent,
                          stale=err or "no reading yet from provider %r" % self.via)
        cut = schema.format_timestamp(r.as_of)
        spent = float(r.spent) + sum(x.cost or 0 for x in mine
                                     if (x.start or x.end or "") > cut)
        w = Window("period", r.period_start, r.period_end, spent)
        read_at = self.cached.get("read_at")
        age = (now - schema.parse_timestamp(read_at)).total_seconds() if read_at else 0
        if self.cached.get("error"):
            w.stale = self.cached["error"]
        elif r.period_end <= now:
            w.stale = "the reading is for a past period"
        elif age > self.stale_after:
            w.stale = "the reading is %dh old" % (age // 3600)
        return w

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
        if self.reading is not None and self.reading.blocked:
            return Reason("budget", "budget: %s says new calls are refused%s" % (
                self.via, " (%s)" % self.reading.stage if self.reading.stage else ""))
        for w in self.windows:
            if w.stale and self.via is not None:
                if cls not in ("urgent", "high"):
                    return Reason("budget", "budget: %s; %s waits for a fresh reading" % (
                        w.stale, cls))
                if self.reading is None and self.amount <= 0:
                    continue               # no amount known: high and urgent go on
            elif w.stale and cls not in ("urgent", "high"):
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
        if self.via is not None:
            r = self.reading
            out["provider"] = {
                "name": self.via, "route": self.route,
                "read_at": (self.cached or {}).get("read_at"),
                "error": (self.cached or {}).get("error"),
                "needs_login": bool((self.cached or {}).get("needs_login")),
                "reading": r.to_json() if r is not None else None}
            if out["provider"]["needs_login"]:
                out["provider"]["renew"] = renew_command(self.via)
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
    if b.get("measure") not in MEASURES:
        return None
    if b["measure"] == "provider":
        if not b.get("provider"):
            return None
    elif not b.get("amount") and not (ctx.limits is not None and ctx.limits.budget_amount):
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
