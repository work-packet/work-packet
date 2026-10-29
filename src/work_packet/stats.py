"""Step statistics per harness, model and profile, with advice (docs/harness.md §6).

Read-only: everything comes from the step folders (``meta.json``,
``result.md``, ``state.diff``, ``ctxhook.fired``) and packet status. The
advice is printed, never applied.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from . import frontmatter, layout, schema
from .packet import Packet

MIN_STEPS = 30          # no advice below this many steps in a group
SHORT_CALLS = 3         # API calls: the first, plus at most two tool calls
SHORT_DIFF_LINES = 4    # changed lines in state.diff

_STEP_RX = re.compile(r"^(\d{4,})(?:\.failed-(\d+))?$")


@dataclass
class Step:
    project: str
    wpid: str
    step: int
    attempt: Optional[int]
    failed: bool
    harness: str
    model: str
    profile: str
    carried: bool = False
    cost: Optional[float] = None
    calls: Optional[int] = None
    base: Optional[int] = None
    peak: Optional[int] = None
    output_tokens: Optional[int] = None
    input_tokens: Optional[int] = None       # not from the cache
    cache_write: Optional[int] = None
    cache_read: Optional[int] = None
    thinking_tokens: Optional[int] = None
    cache_breaks: Optional[int] = None
    duration_s: Optional[float] = None
    api_s: Optional[float] = None
    item: Optional[str] = None   # the plan item, from the memento's ``item``
    hook: tuple = ()             # levels the context hook sent
    resume: Optional[str] = None
    diff_lines: Optional[int] = None
    end: Optional[str] = None
    dir: Optional[str] = None    # the step folder
    quota: Optional[dict] = None  # {window: {first, last, resets_at}}, subscriptions only
    tools: Optional[dict] = None  # tool-cost attribution, when read from the history store
    route: Optional[str] = None   # "account@host" from meta.json, when it was recorded

    @property
    def key(self):
        return (self.harness, self.model, self.profile)

    def quota_used(self, window="seven_day"):
        """The share of the subscription window the step used, as a fraction:
        the last reading less the first, or the last if the window reset in
        between. Readings are whole percents, the first is taken after the
        first call, and any other use of the account in the meantime counts."""
        q = (self.quota or {}).get(window)
        if not q or q.get("last") is None:
            return None
        d = q["last"] - q.get("first", 0)
        return d if d >= 0 else q["last"]

    @property
    def context_tokens(self):
        """Every input token the step's calls read: new, cache writes and reads."""
        n = [self.input_tokens, self.cache_write, self.cache_read]
        return None if all(v is None for v in n) else sum(v or 0 for v in n)


def tool_attrs(s):
    """The step's tool-cost attribution (``toolcost.attribute``): kept in the
    history store, else read from the step's transcript."""
    if s.tools is not None:
        return s.tools
    if s.dir and s.harness == "claude":
        from . import toolcost
        return toolcost.of_step(s.dir)
    return None


def is_short(s):
    """A committed step that stopped early: ``resume: now``, few calls, little
    change (harness.md §5). Instructions that ask for small steps look the same."""
    return (not s.failed and s.resume == "now" and s.calls is not None
            and s.calls <= SHORT_CALLS and (s.diff_lines or 0) <= SHORT_DIFF_LINES)


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            return fp.read()
    except OSError:
        return None


def _diff_lines(text):
    if text is None:
        return None
    return sum(1 for ln in text.splitlines()
               if ln[:1] in "+-" and not ln.startswith(("+++", "---")))


def _memento(path):
    try:
        mm, _ = frontmatter.load(path)
    except (OSError, frontmatter.FrontMatterError):
        return {}
    return mm if isinstance(mm, dict) else {}


def _resume(mm):
    r = mm.get("resume")
    return " ".join(r.split()) if isinstance(r, str) else None


def _from_transcript(d, meta):
    """(``context``, ``tokens``, ``quota``) for a step recorded before wpk saved
    all of them (context.md C1; thinking tokens, cache breaks and quota), from
    its transcript."""
    from . import harness, model
    path = os.path.join(d, "transcript.jsonl")
    if not os.path.isfile(path):
        return {}, {}, {}
    try:
        res = harness.get(meta.get("harness") or "claude").parse(path, model.StepResult())
    except (KeyError, OSError):
        return {}, {}, {}
    c = model.context_summary(res.context) or {}
    if c:
        old = meta.get("context") or {}
        c["base"] = old.get("base", c["first"])  # no context: never carried a session over
        c["cache_breaks"], c["cache_rewrite"] = res.cache_breaks, res.cache_rewrite
    return c, res.tokens, res.quota


def packet_steps(project, pkt):
    """Every step folder of a packet that has a ``meta.json``."""
    import json
    out = []
    try:
        names = sorted(os.listdir(pkt.steps_dir))
    except OSError:
        return out
    for n in names:
        m = _STEP_RX.match(n)
        if not m:
            continue
        d = os.path.join(pkt.steps_dir, n)
        try:
            with open(os.path.join(d, "meta.json"), encoding="utf-8") as fp:
                meta = json.load(fp)
        except (OSError, ValueError):
            continue
        ctx, tok = meta.get("context") or {}, meta.get("tokens") or {}
        quota = meta.get("quota")
        if "cache_breaks" not in ctx or "thinking_tokens" not in tok or "quota" not in meta:
            c, t, quota = _from_transcript(d, meta)
            ctx, tok = c or ctx, dict(tok, **t) if t else tok
        fired = _read(os.path.join(d, "ctxhook.fired"))
        mm = _memento(os.path.join(d, "pending-memento.md" if m.group(2) else "result.md"))
        out.append(Step(
            project=project, wpid=os.path.basename(pkt.path), step=int(m.group(1)),
            attempt=int(m.group(2)) if m.group(2) else meta.get("attempt"),
            failed=m.group(2) is not None,
            harness=meta.get("harness") or "claude", model=meta.get("model") or "?",
            profile=meta.get("profile") or "-", carried=bool(meta.get("carried_from")),
            cost=meta.get("cost_usd"), calls=ctx.get("calls"),
            base=ctx.get("base", ctx.get("first")), peak=ctx.get("peak"),
            output_tokens=tok.get("output_tokens"), input_tokens=tok.get("input_tokens"),
            cache_write=tok.get("cache_creation_input_tokens"),
            cache_read=tok.get("cache_read_input_tokens"),
            thinking_tokens=tok.get("thinking_tokens"), cache_breaks=ctx.get("cache_breaks"),
            duration_s=meta.get("duration_s"), api_s=meta.get("api_s"),
            hook=tuple(fired.split()) if fired else (),
            resume=None if m.group(2) else _resume(mm), item=schema.memento_item(mm),
            diff_lines=_diff_lines(_read(os.path.join(d, "state.diff"))),
            end=meta.get("end"), dir=d, quota=quota or None, route=_route(meta)))
    # A failed attempt that left no item belongs to the item its step committed.
    done = {s.step: s.item for s in out if not s.failed}
    for s in out:
        if s.failed and s.item is None:
            s.item = done.get(s.step)
    return out


def collect(projects, since=None):
    """(steps, finished) for ``projects``: a list of (name, directory).

    ``finished`` is [(key, steps, cost)] for each COMPLETED packet, keyed by
    its last step's harness, model and profile. ``since`` is a UTC timestamp
    string; older steps are left out.
    """
    steps, finished = [], []
    for name, proj in projects:
        pdir = layout.runs_dir(proj)
        try:
            wpids = sorted(w for w in os.listdir(pdir) if schema.is_wpid(w))
        except OSError:
            # The runs are gone (harvested and removed): read the history store.
            ss, ff = _from_history(name, since)
            steps += ss
            finished += ff
            continue
        for w in wpids:
            pkt = Packet(os.path.join(pdir, w))
            ss = [s for s in packet_steps(name, pkt) if not since or (s.end or "") >= since]
            steps += ss
            try:
                st, _ = pkt.load_status()
            except (OSError, frontmatter.FrontMatterError):
                continue
            done = [s for s in ss if not s.failed]
            if st.get("state") == "COMPLETED" and done:
                finished.append((done[-1].key, len(done), sum(s.cost or 0 for s in done)))
    return steps, finished


def _from_history(name, since):
    from . import history
    if not os.path.exists(history.db_path()):
        return [], []
    try:
        return history.collect([name], since)
    except Exception:
        return [], []


# --- figures -----------------------------------------------------------------------

def _pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, max(0, int(round(p / 100.0 * len(xs) + 0.5)) - 1))]


def _fit(points):
    """Least-squares line through (x, y): (a, b) for y = a + b·x, or None."""
    if len(points) < 5:
        return None
    n = float(len(points))
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in points) / sxx
    return my - b * mx, b


@dataclass
class Group:
    key: tuple
    steps: List[Step] = field(default_factory=list)
    finished: list = field(default_factory=list)

    def figures(self):
        ok = [s for s in self.steps if not s.failed]
        failed = [s for s in self.steps if s.failed]
        fresh = [s.cost for s in ok if not s.carried and s.cost is not None]
        carried = [s for s in ok if s.carried and s.cost is not None]
        f = {
            "steps": len(ok), "failed_attempts": len(failed),
            "retry_rate": len(failed) / float(len(self.steps)) if self.steps else 0.0,
            "calls_median": _pct([s.calls for s in ok], 50),
            "calls_p90": _pct([s.calls for s in ok], 90),
            "output_tokens_median": _pct([s.output_tokens for s in ok], 50),
            "base_median": _pct([s.base for s in ok], 50),
            "peak_median": _pct([s.peak for s in ok], 50),
            "peak_p90": _pct([s.peak for s in ok], 90),
            "short_rate": sum(1 for s in ok if is_short(s)) / float(len(ok)) if ok else 0.0,
            "hook_soft_rate": (sum(1 for s in ok if "soft" in s.hook) / float(len(ok))
                               if ok else 0.0),
            "hook_hard": sum(1 for s in self.steps if "hard" in s.hook),
            "cost_fresh_median": _pct(fresh, 50), "fresh_n": len(fresh),
            "cost_carried_median": _pct([s.cost for s in carried], 50),
            "carried_n": len(carried),
            "finished": len(self.finished),
            "finished_steps_median": _pct([n for n, _ in self.finished], 50),
            "finished_cost_median": _pct([c for _, c in self.finished], 50),
            "break_even_factor": None, "carried_max_factor": None,
        }
        f.update(token_figures(self.steps))
        f["context_tokens_median"] = _pct([s.context_tokens for s in ok], 50)
        pts = [(s.peak / float(s.base), s.cost) for s in carried if s.peak and s.base]
        if pts:
            f["carried_max_factor"] = max(x for x, _ in pts)
        fit = _fit(pts)
        if fit and fit[1] > 0 and f["cost_fresh_median"] is not None:
            f["break_even_factor"] = (f["cost_fresh_median"] - fit[0]) / fit[1]
        return f

    def advice(self, min_steps=MIN_STEPS):
        """[str]: what the figures suggest, each with the numbers behind it."""
        f = self.figures()
        if f["steps"] < min_steps:
            return []
        out = []
        if f["short_rate"] > 0.40:
            out.append("Stops early: %.0f%% of steps end `resume: now` after <= %d calls with "
                       "little change. Try `sizing = \"persistent\"` and `carry_session = true` "
                       "(unless the instructions ask for small steps)."
                       % (100 * f["short_rate"], SHORT_CALLS))
        if f["hook_soft_rate"] > 0.25 or f["hook_hard"]:
            out.append("Steps run long: the context hook fired on %.0f%% of steps (%d hard). "
                       "Tighten the instructions, or raise `step_context_tokens` if the "
                       "model's context window allows." % (100 * f["hook_soft_rate"],
                                                           f["hook_hard"]))
        be, mx = f["break_even_factor"], f["carried_max_factor"]
        if be is not None and mx is not None:
            if mx > be:
                out.append("Carried steps above %.1fx base cost more than a fresh step "
                           "(median $%.4f); lower `carry_factor` to about %.1f."
                           % (be, f["cost_fresh_median"], be))
            elif mx < 0.6 * be and f["carried_n"] >= min_steps:
                out.append("Carried chains end by %.1fx base, well under the break-even "
                           "(about %.1fx); `carry_factor` can go up to about %.1f."
                           % (mx, be, be))
        if f["retry_rate"] > 0.10:
            out.append("%.0f%% of attempts failed: look at the failures (harness or protocol "
                       "trouble), not at step size." % (100 * f["retry_rate"]))
        return out


def _sum(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) if xs else None


def _share(a, b):
    return a / float(b) if a is not None and b else None


def token_figures(steps):
    """Token totals over ``steps``, failed attempts included, with the shares
    that matter for tuning: how much input came from the cache, how much
    output was thinking, and how much of the whole went on failed attempts."""
    ctx = _sum([s.context_tokens for s in steps])
    out = _sum([s.output_tokens for s in steps])
    failed = _sum([s.context_tokens for s in steps if s.failed])
    return {
        "context_tokens": ctx, "input_tokens": _sum([s.input_tokens for s in steps]),
        "cache_write": _sum([s.cache_write for s in steps]),
        "cache_read": _sum([s.cache_read for s in steps]),
        "output_tokens": out, "thinking_tokens": _sum([s.thinking_tokens for s in steps]),
        "cost_usd": _sum([s.cost for s in steps]),
        "cache_hit": _share(_sum([s.cache_read for s in steps]), ctx),
        "thinking_share": _share(_sum([s.thinking_tokens for s in steps]), out),
        "failed_share": _share(failed or 0, ctx),
        "cache_breaks": _sum([s.cache_breaks for s in steps]),
        "quota_week": _sum([s.quota_used("seven_day") for s in steps]),
        "quota_5h": _sum([s.quota_used("five_hour") for s in steps]),
    }


def latest_quota(steps, now=None):
    """The newest reading of each subscription window over ``steps``:
    {window: {used, resets_at, at, reset}}; ``reset`` is true when the window
    has rolled over since, so ``used`` is stale. Empty when no step has one."""
    import time
    now = time.time() if now is None else now
    out = {}
    for s in sorted([s for s in steps if s.quota and s.end], key=lambda s: s.end):
        for name, q in s.quota.items():
            if q.get("last") is not None:
                out[name] = {"used": q["last"], "resets_at": q.get("resets_at"), "at": s.end}
    for q in out.values():
        q["reset"] = bool(q["resets_at"] and q["resets_at"] <= now)
    return out


def _route(meta):
    r = meta.get("route")
    if not isinstance(r, dict):
        return None
    return "%s@%s" % (r.get("account") or "unknown", r.get("host") or "default")


ROLLUPS = {
    "project": lambda s: s.project,
    "packet": lambda s: "%s/%s" % (s.project, s.wpid[:8]),
    "model": lambda s: s.model,
    "route": lambda s: s.route or "(not recorded)",
    "item": lambda s: "%s/%s %s" % (s.project, s.wpid[:8], s.item or "(no item)"),
    "day": lambda s: (s.end or "?")[:10],
    "step": lambda s: "%s/%s/%04d%s" % (s.project, s.wpid[:8], s.step,
                                         ".%s" % s.attempt if s.failed else ""),
}


def rollup(steps, by):
    """[(label, steps, token_figures)] with ``steps`` grouped by one of
    ``ROLLUPS``: the rows of a token trend (by day) or of who burns tokens
    (by project or packet)."""
    rows = {}
    for s in steps:
        rows.setdefault(ROLLUPS[by](s), []).append(s)
    return [(k, len(v), token_figures(v)) for k, v in sorted(rows.items())]


def rollup_report(rows):
    w = max([28] + [len(k) for k, _, _ in rows])
    head = ("%-*s %5s %9s %6s %8s %7s %7s %6s %6s %6s %5s"
            % (w, "", "steps", "cost", "week", "context", "write", "output", "think", "hit",
               "failed", "brk"))
    lines = [head]
    for label, n, f in rows:
        lines.append("%-*s %5d %9s %6s %8s %7s %7s %6s %6s %6s %5s" % (
            w, label, n, _usd2(f["cost_usd"]), _pc(f["quota_week"]), _k(f["context_tokens"]),
            _k(f["cache_write"]), _k(f["output_tokens"]), _pc(f["thinking_share"]),
            _pc(f["cache_hit"]), _pc(f["failed_share"]),
            "-" if f["cache_breaks"] is None else f["cache_breaks"]))
    return lines


def groups(steps, finished):
    gs = {}
    for s in steps:
        gs.setdefault(s.key, Group(s.key)).steps.append(s)
    for key, n, cost in finished:
        if key in gs:
            gs[key].finished.append((n, cost))
    return [gs[k] for k in sorted(gs)]


# --- report ------------------------------------------------------------------------

def _k(n):
    if n is None:
        return "-"
    if n >= 10 ** 6:
        return "%.1fM" % (n / 1e6)
    return "%.1fk" % (n / 1000.0) if n >= 1000 else str(n)


def _usd(x):
    return "-" if x is None else "$%.4f" % x


def _usd2(x):
    return "-" if x is None else "$%.2f" % x


def _pc(x):
    return "-" if x is None else "%.0f%%" % (100 * x)


def report(gs, min_steps=MIN_STEPS):
    """Plain-text report lines."""
    lines = []
    for g in gs:
        f = g.figures()
        lines.append("%s / %s / %s" % g.key)
        lines.append("  steps %d, failed attempts %d (%.0f%%)"
                     % (f["steps"], f["failed_attempts"], 100 * f["retry_rate"]))
        lines.append("  calls/step median %s, p90 %s; output tokens median %s"
                     % (_k(f["calls_median"]), _k(f["calls_p90"]),
                        _k(f["output_tokens_median"])))
        lines.append("  context base median %s; peak median %s, p90 %s"
                     % (_k(f["base_median"]), _k(f["peak_median"]), _k(f["peak_p90"])))
        if f["context_tokens"] is not None:
            lines.append("  tokens: context %s (cache read %s, write %s), output %s "
                         "(thinking %s); per step median context %s; failed attempts %s; "
                         "cache breaks %s"
                         % (_k(f["context_tokens"]), _pc(f["cache_hit"]),
                            _pc(_share(f["cache_write"], f["context_tokens"])),
                            _k(f["output_tokens"]), _pc(f["thinking_share"]),
                            _k(f["context_tokens_median"]), _pc(f["failed_share"]),
                            f["cache_breaks"] if f["cache_breaks"] is not None else "-"))
        lines.append("  short steps %.0f%%; context hook soft %.0f%%, hard %d"
                     % (100 * f["short_rate"], 100 * f["hook_soft_rate"], f["hook_hard"]))
        be = f["break_even_factor"]
        lines.append("  cost/step fresh %s (n=%d), carried %s (n=%d)%s"
                     % (_usd(f["cost_fresh_median"]), f["fresh_n"],
                        _usd(f["cost_carried_median"]), f["carried_n"],
                        "; break-even carry_factor about %.1f" % be if be else ""))
        if f["finished"]:
            lines.append("  finished packets %d: median %s steps, %s"
                         % (f["finished"], _k(f["finished_steps_median"]),
                            _usd(f["finished_cost_median"])))
        adv = g.advice(min_steps)
        if f["steps"] < min_steps:
            lines.append("  advice: none yet (needs %d steps)" % min_steps)
        elif not adv:
            lines.append("  advice: none")
        for a in adv:
            lines.append("  advice: " + a)
        lines.append("")
    return lines


def as_json(gs, min_steps=MIN_STEPS):
    return [{"harness": g.key[0], "model": g.key[1], "profile": g.key[2],
             "figures": g.figures(), "advice": g.advice(min_steps)} for g in gs]
