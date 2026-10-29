"""DFM runs as the board shows them: the journals ``dash/events.py`` writes,
folded into what a run is doing, has done and plans to do (docs/dfm-events.md §5, §6).

A fold replays a whole journal. That is cheap at the sizes DFM produces, and a
journal only grows, so a fold is cached by the file's size and mtime.
"""

import json
import os
import time

from . import events

HEARTBEAT_S = 10.0          # DFM's default (DFM_EVENT_HEARTBEAT)
LOST_AFTER = 3              # heartbeats of silence before a run counts as lost
RUNNING = ("enter", "checking", "run")
QUIET = ("uptodate", "cache_hit", "base_hit")      # done without doing anything
LOG_TAIL = 256 << 10
MARKERS_SHOWN = 20

_cache = {}                 # path -> ((size, mtime), folded)


def heartbeat_s(env=None):
    env = os.environ if env is None else env
    try:
        return float(env.get("DFM_EVENT_HEARTBEAT", HEARTBEAT_S))
    except ValueError:
        return HEARTBEAT_S


def read(path):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            for line in fp:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    out.append(ev)
    except OSError:
        return None
    return out


def _node(nodes, order, rec):
    nid = rec.get("id")
    if not isinstance(nid, str):
        return None
    n = nodes.get(nid)
    if n is None:
        n = nodes[nid] = {"id": nid, "name": nid, "label": None, "kind": "leaf", "parent": None,
                          "needs": [], "rundir": None, "state": "pending", "status": None,
                          "changed": None, "dur": None, "log": None, "t_enter": None,
                          "t_done": None, "markers": [], "errors": 0, "warnings": 0,
                          "cmd": None, "logfile": None, "planned": False}
        order.append(nid)
    return n


def fold(lines):
    """The run model of one journal (``lines``: its parsed events)."""
    nodes, order = {}, []
    run = {"sid": None, "origin": {}, "partial": False, "gaps": 0, "end": None,
           "closed": None, "peer": None, "t0": None, "t_last": None, "alive": None,
           "scopes": 0}
    last_seq = None
    for ev in lines:
        kind, t = ev.get("ev"), ev.get("t")
        run["sid"] = run["sid"] or ev.get("sid")
        if isinstance(t, (int, float)):
            run["t_last"] = max(run["t_last"] or t, t)
        if ev.get("src") == "wpk":
            if kind == "conn.open":
                run["peer"] = ev.get("peer")
            elif kind == "conn.close" and run["end"] is None:
                run["closed"] = ev.get("why") or "closed"
            continue
        seq = ev.get("seq")
        if isinstance(seq, int):
            if last_seq is None and seq != 0:
                run["partial"] = True
            elif last_seq is not None and seq > last_seq + 1:
                run["gaps"] += seq - last_seq - 1
            last_seq = seq if last_seq is None else max(last_seq, seq)
        if kind == "run.start":
            run["origin"] = {k: v for k, v in ev.items()
                             if k not in ("v", "src", "sid", "seq", "t", "ev")}
            run["t0"] = t
        elif kind in ("graph.plan", "graph.extend"):
            if kind == "graph.extend":
                run["scopes"] += 1
            for rec in ev.get("nodes") or []:
                n = _node(nodes, order, rec if isinstance(rec, dict) else {})
                if n is None:
                    continue
                n["planned"] = True
                for k in ("name", "label", "kind", "parent", "rundir"):
                    if rec.get(k) is not None:
                        n[k] = rec[k]
                n["needs"] = [d.get("id") for d in rec.get("needs") or []
                              if isinstance(d, dict) and isinstance(d.get("id"), str)]
        elif kind == "task.state":
            n = _node(nodes, order, ev)
            if n is None:
                continue
            st = ev.get("state")
            if st == "enter" and n["t_enter"] is None:
                n["t_enter"] = t
            if st == "done":
                n["state"] = "done"
                n["t_done"] = t
                n["cmd"] = None
                for k in ("status", "changed", "dur", "log", "rundir"):
                    if ev.get(k) is not None:
                        n[k] = ev[k]
                n["quiet"] = "cache_hit" if ev.get("cache_hit") else \
                    "base_hit" if ev.get("base_hit") else \
                    "uptodate" if ev.get("changed") is False else None
            elif st in RUNNING or st in QUIET or st == "skipped":
                if n["state"] != "done":
                    n["state"] = st
        elif kind == "task.marker":
            n = _node(nodes, order, ev)
            if n is None:
                continue
            sev = str(ev.get("severity") or "info").lower()
            if sev == "error":
                n["errors"] += 1
            elif sev in ("warning", "warn"):
                n["warnings"] += 1
            if len(n["markers"]) < MARKERS_SHOWN:
                n["markers"].append({"severity": sev, "msg": ev.get("msg") or "",
                                     "loc": ev.get("loc")})
        elif kind == "task.exec":
            n = _node(nodes, order, ev)
            if n is None:
                continue
            if ev.get("phase") == "start":
                n["cmd"] = " ".join(str(a) for a in ev.get("cmd") or [])
                n["logfile"] = ev.get("logfile") or n["logfile"]
            elif ev.get("phase") == "end":
                n["cmd"] = None
        elif kind == "run.alive":
            run["alive"] = t
        elif kind == "run.end":
            run["end"] = {k: ev.get(k) for k in ("status", "result", "counts", "dropped")}
            run["end"]["t"] = t
            run["closed"] = None
    run["nodes"] = nodes
    run["order"] = order
    return run


def _status(run, now, hb):
    if run["end"] is not None:
        return run["end"].get("result") or "ok"
    if run["closed"]:
        return "lost"
    if hb > 0 and run["t_last"] is not None and now - run["t_last"] > LOST_AFTER * hb:
        return "lost"
    return "running"


def _waiting(n, nodes):
    """The first unfinished need of a pending node, and how many there are."""
    open_ = [d for d in n["needs"] if nodes.get(d, {}).get("state") not in ("done", "skipped")]
    return (open_[0] if open_ else None), len(open_)


def view(run, now=None, hb=None):
    """What the pages show of a folded run: its status, progress and the three lists."""
    now = time.time() if now is None else now
    hb = heartbeat_s() if hb is None else hb
    nodes = run["nodes"]
    o = run["origin"]
    ctx = o.get("ctx") or {}
    status = _status(run, now, hb)
    live = status == "running"
    leaves = [nodes[i] for i in run["order"] if nodes[i]["kind"] != "compound"]
    running, pending, failed, done, quiet, skipped = [], [], [], [], [], []
    for n in leaves:
        st = n["state"]
        if st == "done":
            if n["status"]:
                failed.append(n)
            elif n.get("quiet"):
                quiet.append(n)
            else:
                done.append(n)
        elif st == "skipped":
            skipped.append(n)
        elif st in RUNNING or st in QUIET:
            # A node is still mid-flight only while the run is: a lost run's are cut off.
            n["for_s"] = (now if live else (run["t_last"] or now)) - (n["t_enter"] or now)
            running.append(n)
        else:
            n["waiting"], n["n_waiting"] = _waiting(n, nodes)
            pending.append(n)
    done.sort(key=lambda n: n["t_done"] or 0, reverse=True)
    running.sort(key=lambda n: n["t_enter"] or 0)
    finished = len(failed) + len(done) + len(quiet) + len(skipped)
    t_end = (run["end"] or {}).get("t") or (run["t_last"] if not live else now)
    argv = o.get("argv") or []
    return {
        "sid": run["sid"], "status": status, "live": live,
        "title": " ".join(str(a) for a in argv[1:]) or "dfm run",
        "roots": o.get("roots") or [], "argv": argv, "host": o.get("host"), "pid": o.get("pid"),
        "peer": run["peer"], "cwd": o.get("cwd"), "rundir": o.get("rundir"),
        "dfm_run_id": o.get("dfm_run_id"), "jobs": o.get("jobs"), "parent": o.get("parent"),
        "ctx": ctx, "project": ctx.get("WPK_PROJECT"), "wpid": ctx.get("WPK_WPID"),
        "step": ctx.get("WPK_STEP"), "attempt": ctx.get("WPK_ATTEMPT"),
        "t0": run["t0"], "elapsed": (t_end - run["t0"]) if run["t0"] and t_end else None,
        "total": len(leaves), "finished": finished,
        "pct": int(100 * finished / len(leaves)) if leaves else (100 if not live else 0),
        "running": running, "pending": pending, "failed": failed, "done": done,
        "quiet": quiet, "skipped": skipped, "counts": (run["end"] or {}).get("counts"),
        "dropped": (run["end"] or {}).get("dropped"), "closed": run["closed"],
        "partial": run["partial"], "gaps": run["gaps"], "scopes": run["scopes"],
        "markers": sum(n["errors"] + n["warnings"] for n in leaves),
    }


def load(home, sid):
    """The folded run ``sid``, or None."""
    path = events.journal(home, sid)
    if path is None:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_size, st.st_mtime_ns)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    lines = read(path)
    if lines is None:
        return None
    run = fold(lines)
    run["sid"] = run["sid"] or sid
    _cache[path] = (key, run)
    return run


def runs(home, now=None, wpid=None, step=None, limit=None):
    """Every journaled run, live ones first and then newest first; ``wpid`` (and
    ``step``) keep the runs a packet's steps started (through ``ctx``)."""
    d = events.journal_dir(home)
    try:
        names = [n[:-6] for n in os.listdir(d) if n.endswith(".jsonl")]
    except OSError:
        return []
    for p in list(_cache):
        if os.path.dirname(p) == d and os.path.basename(p)[:-6] not in names:
            _cache.pop(p, None)
    out = []
    for sid in names:
        run = load(home, sid)
        if run is None:
            continue
        v = view(run, now=now)
        if wpid is not None and v["wpid"] != wpid:
            continue
        if step is not None and str(v["step"]) != str(step):
            continue
        out.append(v)
    out.sort(key=lambda v: (not v["live"], -(v["t0"] or 0)))
    return out[:limit] if limit else out


def log_path(run, nid):
    """The log file of node ``nid``, if the journal names one inside the run's dirs."""
    n = run["nodes"].get(nid)
    if n is None:
        return None
    roots = [r for r in (run["origin"].get("rundir"), n.get("rundir")) if r]
    for p in (n.get("log"), n.get("logfile")):
        if not p:
            continue
        if not os.path.isabs(p) and n.get("rundir"):
            p = os.path.join(n["rundir"], p)
        rp = os.path.realpath(p)
        if os.path.isfile(rp) and any(rp.startswith(os.path.realpath(r) + os.sep) for r in roots):
            return rp
    return None


def log_tail(path, size=LOG_TAIL):
    """The last ``size`` bytes of a log, and whether it was cut."""
    with open(path, "rb") as fp:
        fp.seek(0, os.SEEK_END)
        n = fp.tell()
        fp.seek(max(0, n - size))
        return fp.read().decode("utf-8", "replace"), n > size
