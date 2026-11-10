"""Token use on the board (docs/token-dashboard.md): the same figures as
``wpk stats``, laid out for the board's SVG bar charts.

Front-end neutral: everything returned is plain data. A chart is
``{"width", "height", "max", "bars": [{x, w, label, title, link, failed,
"segs": [{cls, y, h}]}], "legend"}``.
"""

import os
import urllib.parse
from datetime import timedelta

from .. import clock, layout, schema, stats, toolcost
from ..packet import Packet

CONTEXT = (("cache_read", "tk-read", "cache read"), ("cache_write", "tk-write", "cache write"),
           ("input_tokens", "tk-new", "uncached"))
OUTPUT = (("text", "tk-out", "output"), ("thinking_tokens", "tk-think", "thinking"))


def _values(s):
    """A step's values for the charts; output is split into text and thinking."""
    out, think = s.output_tokens or 0, s.thinking_tokens or 0
    return {"cache_read": s.cache_read or 0, "cache_write": s.cache_write or 0,
            "input_tokens": s.input_tokens or 0, "thinking_tokens": min(think, out),
            "text": max(out - think, 0)}


def _sum_values(steps):
    tot = dict.fromkeys(("cache_read", "cache_write", "input_tokens", "thinking_tokens",
                         "text"), 0)
    for s in steps:
        for k, v in _values(s).items():
            tot[k] = tot.get(k, 0) + v
    return tot


def chart(cols, series, width=900, height=120, gap=2, label_h=16, left=40, bar_max=48,
          unit="tok"):
    """Stacked bars, one per column. ``cols``: [{label, title, link, failed,
    values}]; ``series``: [(key, css class, legend)], bottom first. ``unit``
    (``tok`` or ``usd``) is how the axis label reads."""
    if not cols:
        return None
    top = max([sum(c["values"].get(k, 0) for k, _, _ in series) for c in cols] + [1])
    plot_h = height - label_h
    w = min(max((width - left) / float(len(cols)), 2.0), bar_max)
    bars = []
    for i, c in enumerate(cols):
        y, segs = float(plot_h), []
        for k, cls, _ in series:
            h = plot_h * c["values"].get(k, 0) / top
            if h > 0:
                y -= h
                segs.append({"cls": cls, "y": round(y, 1), "h": round(max(h, 0.5), 1)})
        bars.append({"x": round(left + i * w, 1), "w": round(max(w - gap, 1.0), 1),
                     "label": c.get("label") or "", "title": c.get("title") or "",
                     "link": c.get("link"), "failed": c.get("failed"), "segs": segs})
    every = max(1, int(round(len(cols) / 12.0)))
    for i, b in enumerate(bars):
        if i % every:
            b["label"] = ""
    return {"width": width, "height": height, "plot_h": plot_h, "max": top, "bars": bars,
            "left": left, "unit": unit,
            "legend": [(cls, name) for _, cls, name in series]}


def _k(n):
    return stats._k(n)


def _title(label, v, cost=None):
    ctx = v["cache_read"] + v["cache_write"] + v["input_tokens"]
    out = v["text"] + v["thinking_tokens"]
    return "%s: context %s (cache read %s, write %s, uncached %s); output %s (thinking %s)%s" % (
        label, _k(ctx), _k(v["cache_read"]), _k(v["cache_write"]), _k(v["input_tokens"]),
        _k(out), _k(v["thinking_tokens"]), "; $%.2f" % cost if cost is not None else "")


def _local_day(s, tz):
    t = schema.parse_timestamp(s.end) if s.end else None
    return t.astimezone(tz).date() if t else None


def project_steps(entry):
    return stats.collect([(entry["name"], entry["path"])])[0]


def _names(entry):
    from .data import tree
    return {n["wpid"]: n["name"] or n["short"] for n in tree(entry)}


def rows(steps, by, names=None):
    """Table rows for ``steps`` grouped ``by`` (``stats.ROLLUPS``), biggest first."""
    out = []
    for label, n, f in stats.rollup(steps, by):
        wpid = None
        if by in ("packet", "item"):
            short = label.split("/", 1)[1].split(" ", 1)[0]
            wpid = next((s.wpid for s in steps if s.wpid.startswith(short)), None)
            name = (names or {}).get(wpid, short)
            if by == "packet":
                label = name
            else:
                item = label.split(" ", 1)[1]
                one = len({s.wpid for s in steps}) == 1
                label = item if one else "%s · %s" % (item, name)
        out.append(dict(f, label=label, steps=n, wpid=wpid))
    out.sort(key=lambda r: -(r["context_tokens"] or 0))
    return out


def tools(entry, steps, kinds=12, n=10):
    """"Where the context went" (view 5) over ``steps``: rows by tool, by kind
    (a shell command's program, or a file), the lines read again and the
    biggest single results, each linked to its step. None without transcripts."""
    attrs, many = [], len({s.wpid for s in steps}) > 1
    for s in steps:
        a = stats.tool_attrs(s)
        if a:
            a["label"] = "%s%d%s" % (s.wpid[:8] + " · " if many else "", s.step,
                                     " (failed)" if s.failed else "")
            a["link"] = "/p/%s/%s/%s" % (urllib.parse.quote(entry["name"]), s.wpid,
                                         os.path.basename(s.dir))
            attrs.append(a)
    return _tools(attrs, kinds, n)


def _tools(attrs, kinds=12, n=10):
    if not attrs:
        return None
    links = {id(x): a["link"] for a in attrs for x in a["results"] if a.get("link")}
    top = []
    for a in attrs:
        for x in a["results"]:
            top.append(dict(x, step=a.get("label"), link=links.get(id(x))))
    top.sort(key=lambda x: -x["carried"])
    return {"by_tool": toolcost.rollup(attrs, "tool"),
            "by_kind": toolcost.rollup(attrs, "kind")[:kinds],
            "repeats": toolcost.repeats(attrs)[:n], "top": top[:n],
            "steps": len(attrs)}


# --- the sessions people drive, beside the runner (docs/session-cost-plan.md S4) -------

SOURCES = (("runner", "sp0", "runner"), ("sessions", "sp1", "your sessions (est.)"))
TOKEN_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
              "output_tokens")


def session_buckets(home, since=None, until=None, project=None):
    """Session tokens by hour and model, priced: ``[{t, model, usage, rec, tokens,
    usd}]`` (``usd`` None for a model with no price)."""
    from .. import cost, registry, session_usage
    home = home or registry.home()
    tables, prices, out = cost.price_tables(home), {}, []
    for t, m, u, r in session_usage.rows(home, since, until, project):
        if m not in prices:
            prices[m] = cost.model_price(m, tables=tables)
        out.append({"t": t, "model": m, "usage": u, "rec": r,
                    "tokens": sum(u.get(k, 0) for k in TOKEN_KEYS),
                    "usd": cost.session_usd(u, prices[m])})
    return out


def _sess_sum(bs):
    usd = [b["usd"] for b in bs if b["usd"] is not None]
    return {"usd": sum(usd) if usd else (0.0 if not bs else None),
            "tokens": sum(b["tokens"] for b in bs),
            "unpriced": sum(b["tokens"] for b in bs if b["usd"] is None),
            "sessions": len({(b["rec"]["harness"], b["rec"]["session_id"]) for b in bs})}


def _day_of(t, tz):
    from datetime import datetime
    return datetime.fromtimestamp(t, tz).date()


def spend_split(steps, buckets, dates, tz):
    """Runner and sessions side by side over ``dates`` (local days): ``{runner,
    sessions (``_sess_sum``), total, chart}``, the chart stacked by source."""
    first = dates[0] if dates else None
    st = [s for s in steps if first is None or (_local_day(s, tz) or first) >= first]
    bs = [b for b in buckets if first is None or _day_of(b["t"], tz) >= first]
    runner = sum(s.cost or 0 for s in st)
    sess = _sess_sum(bs)
    out = {"runner": runner, "sessions": sess, "total": runner + (sess["usd"] or 0),
           "chart": None}
    if len(dates) > 1:
        cols = []
        for d in dates:
            v = {"runner": sum(s.cost or 0 for s in st if _local_day(s, tz) == d),
                 "sessions": sum(b["usd"] or 0 for b in bs if _day_of(b["t"], tz) == d)}
            day = v["runner"] + v["sessions"]
            cols.append({"label": d.strftime("%m-%d"), "values": v,
                         "title": "%s: %s (runner %s, your sessions %s est.)" % (
                             d.isoformat(), _usd(day), _usd(v["runner"]), _usd(v["sessions"]))
                         if day else "%s: none" % d})
        out["chart"] = chart(cols, SOURCES, height=90, unit="usd")
    return out


def session_rows(buckets, names=None):
    """One row per session, most recent first: harness, client, packet, models,
    tokens, est. cost, last active."""
    from .. import ide_sessions
    by = {}
    for b in buckets:
        r = b["rec"]
        k = (r["harness"], r["session_id"])
        row = by.setdefault(k, {
            "harness": ide_sessions.HARNESS_LABEL.get(r["harness"], r["harness"]),
            "client": ide_sessions.CLIENT_LABEL.get(r.get("client") or "unknown", ""),
            "session": r["session_id"], "short": r["session_id"][:8],
            "wpid": r.get("wpid"), "task": (names or {}).get(r.get("wpid")) or
            (r.get("wpid") or "")[:8], "models": set(), "tokens": 0, "usd": 0.0,
            "unpriced": False, "last": 0})
        row["models"].add(b["model"])
        row["tokens"] += b["tokens"]
        if b["usd"] is None:
            row["unpriced"] = True
        else:
            row["usd"] += b["usd"]
        row["last"] = max(row["last"], b["t"])
    out = sorted(by.values(), key=lambda x: -x["last"])
    for row in out:
        row["models"] = ", ".join(sorted(row["models"]))
    return out


def project(entry, now=None, days=14, home=None, sessions=True):
    """The project page's Tokens panel: totals, a chart per day, and tables by
    packet and by item; with ``sessions``, the sessions people drove beside the
    runner (``spend``, ``sessions``). None when there is neither."""
    now = now or clock.now()
    from .data import _zone
    tz = _zone(entry["path"])
    steps = [s for s in project_steps(entry) if s.context_tokens is not None]
    buckets = session_buckets(home, project=entry["name"]) if sessions else []
    today = now.astimezone(tz).date()
    first = today - timedelta(days=days - 1)
    split = None
    if buckets:
        split = {"window": spend_split(steps, buckets,
                                       [first + timedelta(days=i) for i in range(days)], tz),
                 "all": spend_split(steps, buckets, [], tz), "days": days}
    if not steps:
        if not buckets:
            return None
        return {"steps": 0, "spend": split, "packets": [], "by_item": [], "tools": None,
                "sessions": session_rows(buckets, _names(entry)), "quota": [],
                "sess_by_task": {}}
    by_day = {}
    for s in steps:
        by_day.setdefault(_local_day(s, tz), []).append(s)
    first = min([d for d in by_day if d] + [today])
    first = max(first, today - timedelta(days=days - 1))
    cols = []
    d = first
    while d <= today:
        ss = by_day.get(d, [])
        v = _sum_values(ss)
        cost = sum(s.cost or 0 for s in ss)
        cols.append({"label": d.strftime("%m-%d"), "values": v,
                     "title": _title(d.isoformat(), v, cost) if ss else "%s: none" % d})
        d += timedelta(days=1)
    names = _names(entry)
    items = rows(steps, "item", names)
    by_task = {}
    for bk in buckets:
        w = bk["rec"].get("wpid")
        if w and bk["usd"] is not None:
            by_task[w] = by_task.get(w, 0.0) + bk["usd"]
    return {"figures": stats.token_figures(steps), "steps": len(steps),
            "quota": quota(steps, now), "days": chart(cols, CONTEXT), "days_out": chart(cols, OUTPUT, height=70),
            "packets": rows(steps, "packet", names), "tools": tools(entry, steps),
            "by_item": items if any(not r["label"].startswith("(no item)") for r in items)
            else [], "spend": split, "sessions": session_rows(buckets, names) if buckets else [],
            "sess_by_task": by_task}


def packet(entry, wpid):
    """The packet page's Tokens panel: totals, one bar per attempt, and the items."""
    pkt = Packet(layout.run_dir(entry["path"], wpid))
    steps = [s for s in stats.packet_steps(entry["name"], pkt) if s.context_tokens is not None]
    if not steps:
        return None
    steps.sort(key=lambda s: (s.step, not s.failed, s.attempt or 0))
    cols = []
    for s in steps:
        d = schema.step_dir_name(s.step) + (".failed-%s" % s.attempt if s.failed else "")
        name = "step %d%s" % (s.step, " attempt %s (failed)" % s.attempt if s.failed else "")
        if s.item:
            name += " · " + s.item
        v = _values(s)
        cols.append({"label": str(s.step), "values": v, "failed": s.failed,
                     "link": "/p/%s/%s/%s" % (urllib.parse.quote(entry["name"]), wpid, d),
                     "title": _title(name, v, s.cost)})
    items = rows(steps, "item")
    return {"figures": stats.token_figures(steps), "steps": len(steps),
            "chart": chart(cols, CONTEXT), "chart_out": chart(cols, OUTPUT, height=70),
            "tools": tools(entry, steps),
            "by_item": items if any(not r["label"].startswith("(no item)") for r in items)
            else []}


QUOTA_WINDOWS = (("seven_day", "Weekly"), ("five_hour", "5-hour"))


def _left(secs):
    m = int(secs // 60)
    d, h = m // 1440, m % 1440 // 60
    return "%dd %dh" % (d, h) if d else "%dh %02dm" % (h, m % 60)


def quota(steps, now=None):
    """The subscription quota as last seen by any step: [{label, used, resets,
    left, reset, at}], weekly first. Empty for API-key accounts, whose
    transcripts carry no ``rate_limit_event``."""
    from datetime import datetime
    now = now or clock.now()
    q = stats.latest_quota(steps, now.timestamp())
    out = []
    for key, label in QUOTA_WINDOWS:
        w = q.get(key)
        if not w:
            continue
        r = w["resets_at"]
        out.append({"label": label, "used": w["used"], "reset": w["reset"], "at": w["at"],
                    "resets": datetime.fromtimestamp(r).astimezone().strftime("%a %H:%M")
                    if r else None,
                    "left": _left(r - now.timestamp()) if r and not w["reset"] else None})
    return out


WINDOWS = (1, 7, 30)


def board(entries, now=None, days=7, on=None, home=None, sessions=False):
    """The Overview's token use over the last ``days`` days: a row per project
    (biggest first, with a bar per day and its ``board``), a summary per board
    (``boards``), the whole (``total``, with a full chart per day), and the quota
    (``quota``) as of the newest step of any project. ``on``: the board names
    (``registry.board_of``)."""
    from .. import registry
    from .data import _zone
    now = now or clock.now()
    out, every, by_board, days_all = [], [], {}, {}
    # the sessions people drove (docs/session-cost-plan.md S4), from a day early so
    # every project's local window is covered; each project keeps its own days
    ltoday = now.astimezone().date()
    lstart = ltoday - timedelta(days=days - 1)
    sess_all = session_buckets(home, since=(now - timedelta(days=days + 1)).timestamp()) \
        if sessions else []
    sess_by_board, all_steps, all_bs = {}, [], []
    for e in entries:
        if not os.path.isdir(e["path"]):
            continue
        tz = _zone(e["path"])
        today = now.astimezone(tz).date()
        start = today - timedelta(days=days - 1)
        ps = project_steps(e)
        every += ps
        steps = [s for s in ps if s.context_tokens is not None
                 and (_local_day(s, tz) or start) >= start]
        bs = [x for x in sess_all if x["rec"].get("project") == e["name"]
              and start <= _day_of(x["t"], tz) <= today]
        all_steps += steps
        all_bs += bs
        if not steps and not bs:
            continue
        b = registry.board_of(e, on or [registry.DEFAULT_BOARD])
        if bs:
            sb = sess_by_board.setdefault(b, {"usd": 0.0, "days": {}})
            for x in bs:
                i = (_day_of(x["t"], tz) - start).days
                sb["usd"] += x["usd"] or 0
                sb["days"][i] = sb["days"].get(i, 0.0) + (x["usd"] or 0)
        if not steps:
            ss = _sess_sum(bs)
            out.append(dict(stats.token_figures([]), name=e["name"], board=b, steps=0,
                            spark=None, sess_usd=ss["usd"], sess_unpriced=ss["unpriced"],
                            total_usd=ss["usd"] or 0))
            continue
        bb = by_board.setdefault(b, {"steps": [], "days": {}})
        bb["steps"] += steps
        cols = []
        for i in range(days):
            d = start + timedelta(days=i)
            ss = [s for s in steps if (_local_day(s, tz) or start) == d]
            bb["days"].setdefault(i, []).extend(ss)
            days_all.setdefault(i, (d, []))[1].extend(ss)
            v = _sum_values(ss)
            cols.append({"values": v, "title": _title(d.isoformat(), v)})
        ss = _sess_sum(bs)
        f = stats.token_figures(steps)
        out.append(dict(f, name=e["name"], board=b, steps=len(steps),
                        spark=chart(cols, CONTEXT, width=140, height=28, gap=1,
                                    label_h=0, left=0), sess_usd=ss["usd"] if bs else None,
                        sess_unpriced=ss["unpriced"],
                        total_usd=(f["cost_usd"] or 0) + (ss["usd"] or 0)))
    out.sort(key=lambda r: (-(r["context_tokens"] or 0), -(r["total_usd"] or 0)))
    boards = {}
    for b, bb in by_board.items():
        cols = []
        for i in range(days):
            v = _sum_values(bb["days"].get(i, []))
            cols.append({"values": v, "title": _title("day %d" % (i + 1), v)})
        boards[b] = dict(stats.token_figures(bb["steps"]), steps=len(bb["steps"]),
                         spark=chart(cols, CONTEXT, width=140, height=28, gap=1,
                                     label_h=0, left=0))
    total = None
    if out and not by_board:            # sessions only: no runner figures
        total = dict(stats.token_figures([]), steps=0, chart=None)
    elif out:
        cols = []
        for i in sorted(days_all):
            d, ss = days_all[i]
            v = _sum_values(ss)
            cols.append({"label": d.strftime("%m-%d"), "values": v,
                         "title": _title(d.isoformat(), v, sum(s.cost or 0 for s in ss))
                         if ss else "%s: none" % d})
        total = dict(stats.token_figures([s for r in by_board.values() for s in r["steps"]]),
                     steps=sum(len(r["steps"]) for r in by_board.values()),
                     chart=chart(cols, CONTEXT, height=90) if days > 1 else None)
    dates = [lstart + timedelta(days=i) for i in range(days)]
    return {"rows": out, "boards": boards, "total": total, "days": days,
            "quota": quota(every, now),
            "spend": spend(by_board, dates, on, sess_by_board),
            "split": spend_split(all_steps, all_bs, dates, None) if sessions else None}


SPEND_COLOURS = 8  # --sp0 .. --sp7 in base.html; boards past that reuse them


def _usd(v):
    return "$%.2f" % v


def spend(by_board, dates, on=None, sess=None):
    """Spend by board (docs/stats-spend.md): a bar per board that spent
    anything, biggest first, with its ``share`` of the whole and ``w``, its
    length against the biggest (0..1); ``idle``, the boards in ``on`` that spent
    nothing; ``chart``, spend per day stacked by board (None for one day).
    ``by_board``: {board: {"steps", "days": {i: steps}}}; ``dates``: the day of
    each index. ``sess``: {board: {"usd", "days": {i: usd}}}, the sessions people
    drove, added in. None when nothing was spent."""
    sess = sess or {}
    cost = {b: sum(s.cost or 0 for s in bb["steps"]) for b, bb in by_board.items()}
    for b, sb in sess.items():
        cost[b] = cost.get(b, 0.0) + sb["usd"]
    total = sum(cost.values())
    if total <= 0:
        return None
    names = sorted([b for b in cost if cost[b] > 0], key=lambda b: (-cost[b], b))
    top = cost[names[0]]
    cls = {b: "sp%d" % (i % SPEND_COLOURS) for i, b in enumerate(names)}
    bars = [{"name": b, "cost": cost[b], "share": cost[b] / total, "w": cost[b] / top,
             "cls": cls[b]} for b in names]
    idle = [b for b in (on or []) if b not in cls]
    days_chart = None
    if len(dates) > 1:
        cols = []
        for i, d in enumerate(dates):
            v = {b: sum(s.cost or 0 for s in by_board.get(b, {}).get("days", {}).get(i, []))
                 + sess.get(b, {}).get("days", {}).get(i, 0.0) for b in names}
            day = sum(v.values())
            parts = ", ".join("%s %s" % (b, _usd(v[b])) for b in names if v[b] > 0)
            title = "%s: %s%s" % (d.isoformat(), _usd(day), " (%s)" % parts
                                  if len(names) > 1 else "") if day else "%s: none" % d
            cols.append({"label": d.strftime("%m-%d"), "values": v, "title": title})
        days_chart = chart(cols, [(b, cls[b], b) for b in names], height=90, unit="usd")
    return {"total": total, "bars": bars, "idle": idle, "chart": days_chart}


def calls(transcript_path):
    """Per main-thread API call: [{cache_read, cache_write, input_tokens}], one
    entry per message (a message split over several events counts once)."""
    import json
    out, seen = [], set()
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fp:
            lines = fp.read().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant" or ev.get("parent_tool_use_id"):
            continue
        msg = ev.get("message") or {}
        u = msg.get("usage")
        if not isinstance(u, dict) or (msg.get("id") and msg["id"] in seen):
            continue
        seen.add(msg.get("id"))
        out.append({"cache_read": u.get("cache_read_input_tokens") or 0,
                    "cache_write": u.get("cache_creation_input_tokens") or 0,
                    "input_tokens": u.get("input_tokens") or 0})
    return out


def step(sd, meta):
    """The step page's Tokens panel: the breakdown and the context of each call."""
    t = (meta or {}).get("tokens") or {}
    if not t:
        return None
    ctx = (meta or {}).get("context") or {}
    if "thinking_tokens" not in t or "cache_breaks" not in ctx or "quota" not in meta:
        # recorded before them
        c, more, quota_of = stats._from_transcript(sd, meta)
        t, ctx = dict(t, **more), c or ctx
    else:
        quota_of = (meta or {}).get("quota") or {}
    read, write = t.get("cache_read_input_tokens") or 0, t.get("cache_creation_input_tokens") or 0
    new, out = t.get("input_tokens") or 0, t.get("output_tokens") or 0
    total = read + write + new
    cs = calls(os.path.join(sd, "transcript.jsonl"))
    cols = []
    for i, c in enumerate(cs):
        n = c["cache_read"] + c["cache_write"] + c["input_tokens"]
        cols.append({"label": str(i + 1), "values": c,
                     "title": "call %d: context %s (cache read %s, write %s, uncached %s)" % (
                         i + 1, _k(n), _k(c["cache_read"]), _k(c["cache_write"]),
                         _k(c["input_tokens"]))})
    return {"context": total, "cache_read": read, "cache_write": write, "new": new,
            "write_1h": t.get("cache_write_1h"), "write_5m": t.get("cache_write_5m"),
            "output": out, "thinking": t.get("thinking_tokens"),
            "hit": read / float(total) if total else None,
            "calls": ctx.get("calls"), "peak": ctx.get("peak"), "first": ctx.get("first"),
            "cache_breaks": ctx.get("cache_breaks"), "api_s": (meta or {}).get("api_s"),
            "quota": [dict(q, label=label) for key, label in QUOTA_WINDOWS
                      for q in [quota_of.get(key)] if q and q.get("last") is not None],
            "chart": chart(cols, CONTEXT, height=110),
            "tools": _tools([a for a in [toolcost.of_step(sd)] if a])}
