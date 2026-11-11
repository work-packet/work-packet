"""The focus brief, written by a model (docs/focus-brief-review.md, "Revision").

The algorithm gathers; the model judges. ``gather`` builds one JSON bundle from
what the board, the person's Claude sessions and their git repos say about the
time since the last brief: every open packet with its open questions in full, its
status and report, the journal's events in the window; registry entries that will
not read; each interactive session, compressed to its prompts, its last reply and
its active minutes; the repos with uncommitted or unpushed work; the last briefs
and the person's feedback on them. ``write`` gives the bundle and
``prompts/brief.md`` to one model call with no tools, which answers with the
brief as JSON; ``validate`` keeps only what names a project in the bundle and
clips the rest. ``brief.build`` falls back to its scored brief when any of this
fails, so there is always a brief.

Session transcripts are read only when ``[focus] sessions`` is true; unset, it
follows the scribe's switch (``[ide] sessions_scribe``), the one place the person
said wpk may read what their sessions say.
"""

import glob
import json
import os
import re
import subprocess
import time

from . import fsutil

MODEL = "sonnet"
BUDGET_USD = 0.5
TIMEOUT_S = 300
MAX_SESSIONS = 40            # newest first
MAX_REPOS = 40
IDLE_S = 600                 # a gap longer than this in a session is not work
PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "brief.md")


def _clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _epoch(ts):
    """``2026-11-08T20:52:33Z`` or ``…33.123Z`` to epoch seconds, or None."""
    import calendar
    if not isinstance(ts, str):
        return None
    try:
        return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def _iso(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else None


def config(home):
    """``[focus]`` agent settings, with defaults."""
    from . import registry
    try:
        f = registry.load_config_file(home).get("focus") or {}
    except Exception:                   # noqa: BLE001: a bad config.toml: the defaults
        f = {}
    return {"agent": f.get("agent", True), "model": f.get("model") or MODEL,
            "budget_usd": float(f.get("budget_usd") or BUDGET_USD),
            "sessions": f.get("sessions")}


def sessions_allowed(home, cfg=None):
    cfg = cfg or config(home)
    if cfg.get("sessions") is not None:
        return bool(cfg["sessions"])
    from . import scribe
    return scribe.enabled(home)


# --- packets ---------------------------------------------------------------------------

def _events(pkt, since, limit=6):
    """The journal's commits since ``since``, newest first, not cut short."""
    out, workers = [], {}
    try:
        recs = pkt.journal().records
    except Exception:                   # noqa: BLE001: an unreadable journal has no events
        return out
    for r in recs:
        if r.get("type") == "step-start":
            workers[r.get("step")] = r.get("worker")
        if r.get("type") != "commit-begin":
            continue
        t = _epoch(r.get("t"))
        if t is None or t <= since:
            continue
        d = r.get("decision") or {}
        w = d.get("worker") or workers.get(r.get("step")) or "runner"
        out.append({"t": _iso(t), "step": r.get("step"),
                    "by": "runner" if w in ("agent", "model") else w,
                    "state": d.get("state"), "summary": _clip(d.get("summary"), 700),
                    "reason": _clip(d.get("reason"), 700) or None})
    return out[::-1][:limit]


def _folder(entry):
    from . import layout
    return layout.packet_folder(entry["path"]) if (entry or {}).get("path") else None


def _packet(card, entry, since):
    from . import questions, report
    from .packet import Packet
    root = card.get("root") or {}
    ball = card.get("ball") or {}
    p = {"project": card["name"], "board": card.get("board"), "column": card.get("column"),
         "ball": {"who": ball.get("who"), "kind": ball.get("kind"),
                  "text": _clip(ball.get("text"), 300)},
         "state": root.get("state"), "step": root.get("step"),
         "plan": {k: v for k, v in (card.get("plan") or {}).items() if v not in (None, [], "")},
         "due": card.get("due") or None, "at_risk": card.get("at_risk"),
         "intent": card.get("intent") or None,
         "last_activity": _iso(card["last_end"].timestamp()) if card.get("last_end") else None,
         "folder": _folder(entry)}
    if not root.get("path"):
        return p
    pkt = Packet(root["path"])
    try:
        meta, body = pkt.load_status()
        p["status"] = _clip(body, 900)
        p["reason"] = _clip(meta.get("reason"), 300) or None
    except Exception:                   # noqa: BLE001
        pass
    qs = questions.of_packet(pkt)
    if qs:
        p["questions"] = [{k: (_clip(v, 1500) if isinstance(v, str) else v)
                           for k, v in q.items() if v not in (None, "", [])} for q in qs]
    r = report.of_packet(pkt)
    if r:
        p["report"] = {"outcome": _clip((r[0] or {}).get("outcome"), 700),
                       "body": _clip(r[1], 1200)}
    from . import scribe
    asks = scribe.open_asks(pkt)
    if asks:
        p["session_questions"] = [{"q": a["q"], "asked": _iso(a["t"])} for a in asks]
    ev = _events(pkt, since)
    if ev:
        p["events"] = ev
    return {k: v for k, v in p.items() if v not in (None, {}, [])}


# --- sessions --------------------------------------------------------------------------

def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def session_digest(path, since, max_prompts=8):
    """One Claude Code transcript, compressed: ``{"session", "cwd", "start", "end",
    "minutes", "prompts", "last_reply"}``; None for a scripted (``claude -p``) one or
    one with nothing in the window."""
    cwd = sid = None
    prompts, last, ts = [], "", []
    try:
        fp = open(path, errors="replace")
    except OSError:
        return None
    with fp:
        for line in fp:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if d.get("entrypoint") == "sdk-cli":
                return None                     # a runner step, the scribe, the console
            if d.get("isSidechain"):
                continue
            t = _epoch(d.get("timestamp"))
            if t is None or t <= since:
                continue
            cwd = cwd or d.get("cwd")
            sid = sid or d.get("sessionId")
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("type") == "user" and not d.get("isMeta"):
                text = _text_of(msg.get("content")).strip()
                if text and not text.startswith("<"):
                    prompts.append(_clip(text, 300))
                ts.append(t)                    # a tool's result is work too
            elif d.get("type") == "assistant":
                text = _text_of(msg.get("content")).strip()
                if text:
                    last = text
                ts.append(t)
    if not ts or not prompts:
        return None
    ts.sort()
    active = sum(min(b - a, IDLE_S) for a, b in zip(ts, ts[1:]) if b - a < IDLE_S * 3)
    if len(prompts) > max_prompts:              # the start and the end say the most
        prompts = prompts[:3] + ["…"] + prompts[-(max_prompts - 3):]
    return {"session": sid, "cwd": cwd, "start": _iso(ts[0]), "end": _iso(ts[-1]),
            "minutes": int(active // 60), "prompts": prompts,
            "last_reply": _clip(last, 900)}


def sessions(since, claude_dir=None, limit=MAX_SESSIONS):
    """Every interactive Claude Code session with work since ``since``, newest first."""
    from . import ide_sessions
    d = claude_dir or ide_sessions.claude_dir(os.environ)
    files = []
    for f in glob.glob(os.path.join(d, "projects", "*", "*.jsonl")):
        try:
            m = os.path.getmtime(f)
        except OSError:
            continue
        if m > since:
            files.append((m, f))
    out = []
    for _, f in sorted(files, reverse=True):
        s = session_digest(f, since)
        if s:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def project_of(path, entries):
    """The registered project whose folder holds ``path`` (the deepest), or None."""
    from . import layout
    best = None
    path = os.path.realpath(path) if path else path
    for e in entries:
        p = os.path.realpath(layout.packet_folder(e["path"])) if e.get("path") else ""
        if p and (path == p or (path or "").startswith(p + "/")):
            if best is None or len(p) > len(best[1]):
                best = (e["name"], p)
    return best[0] if best else None


# --- git -------------------------------------------------------------------------------

def _git(cwd, *args, timeout=10):
    try:
        p = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _repos_under(path):
    """``path``'s repo, or the repos one level down (and under ``work/``) when it is not one."""
    if not path or not os.path.isdir(path):
        return []
    top = _git(path, "rev-parse", "--show-toplevel", timeout=5)
    if top:
        return [top.strip()]
    out = []
    for pat in ("*/.git", "work/*/.git"):
        out += [os.path.dirname(g) for g in glob.glob(os.path.join(path, pat))]
    return out


def repo_state(top):
    """Uncommitted files and unpushed commits of one repo, or None when it is clean."""
    st = _git(top, "status", "--porcelain")
    if st is None:
        return None
    dirty = [ln[3:] for ln in st.splitlines() if ln.strip()]
    branches = []
    for ln in (_git(top, "for-each-ref", "--format=%(refname:short)\t%(upstream:short)\t"
                    "%(upstream:track)\t%(committerdate:unix)", "refs/heads") or "").splitlines():
        name, up, track, when = (ln.split("\t") + ["", "", "", ""])[:4]
        m = re.search(r"ahead (\d+)", track)
        if m or (not up and when.isdigit() and time.time() - int(when) < 14 * 86400):
            branches.append({"branch": name, "upstream": up or None,
                             "ahead": int(m.group(1)) if m else None})
    if not dirty and not branches:
        return None
    head = (_git(top, "log", "-1", "--format=%h %s (%cr)") or "").strip()
    cur = (_git(top, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    return {"repo": top, "branch": cur, "head": _clip(head, 160),
            "uncommitted": len(dirty), "files": [_clip(f, 120) for f in dirty[:8]],
            "unpushed": branches[:6]}


def git_state(paths, limit=MAX_REPOS):
    seen, out = set(), []
    for p in paths:
        for top in _repos_under(p):
            if top in seen:
                continue
            seen.add(top)
            s = repo_state(top)
            if s:
                out.append(s)
            if len(seen) >= limit:
                return out
    return out


# --- the bundle ------------------------------------------------------------------------

def gather(home, since, now, cards=None, cfg=None, claude_dir=None):
    """The bundle the model writes the brief from (a dict, JSON-ready)."""
    from . import brief, registry
    from .dash import data
    cfg = cfg or config(home)
    if cards is None:
        cols, _ = data.board(home)
        cards = [c for cs in cols.values() for c in cs]
    entries = registry.entries(home)
    by_name = {e["name"]: e for e in entries}
    open_cards = [c for c in cards if c.get("column") != "Done"]
    on_board = {c["name"] for c in cards}
    packets = [_packet(c, by_name.get(c["name"]), since) for c in open_cards]
    unreadable = []
    for e in entries:
        if e["name"] in on_board:
            continue
        p = _folder(e) or ""
        unreadable.append({"project": e["name"], "folder": p,
                           "problem": "its folder is gone" if not os.path.isdir(p)
                           else "not on the board: its status will not read"})
    sess = sessions(since, claude_dir) if sessions_allowed(home, cfg) else None
    for s in sess or ():
        s["project"] = project_of(s.get("cwd"), entries)
    paths = [_folder(e) for e in entries if e["name"] in {c["name"] for c in open_cards}]
    paths += [s["cwd"] for s in sess or () if s.get("cwd")]
    past = []
    for d in brief.days(home):
        b = brief.load(home, d)
        if b and b.get("t", now) < now - 60:
            past.append({"day": d, "focus": [f.get("project") for f in b.get("focus") or ()]})
        if len(past) >= 3:
            break
    out = {"now": _iso(now), "since": _iso(since), "packets": packets,
           "unreadable": unreadable, "git": git_state(dict.fromkeys(p for p in paths if p)),
           "past_briefs": past, "feedback": brief.feedback(home)}
    if sess is not None:
        out["sessions"] = sess
    else:
        out["sessions_note"] = "session transcripts are not read ([focus] sessions is off)"
    return out


# --- the model -------------------------------------------------------------------------

def ask(prompt, home=None, model=MODEL, budget=BUDGET_USD, timeout=TIMEOUT_S):
    """One model call with no tools: ``(text, cost, error or None)``."""
    from . import scribe
    return scribe.call_model(prompt, home, budget=budget, timeout=timeout, model=model)


def parse(text):
    a, b = (text or "").find("{"), (text or "").rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        d = json.loads(text[a:b + 1])
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


LIMITS = {"yesterday": 8, "decide": 12, "close_out": 12, "runs": 12, "uncommitted": 12,
          "focus": 3, "housekeeping": 12}
RUN_STATES = ("COMPLETED", "PAUSED", "FAILED")     # what actions.continue_ takes


def validate(d, bundle):
    """The model's brief with every item that names an unknown project dropped and
    every string clipped; None when nothing usable is left."""
    known = {p["project"] for p in bundle.get("packets", ())} | {
        u["project"] for u in bundle.get("unreadable", ())}
    runnable = {p["project"] for p in bundle.get("packets", ())
                if p.get("state") in RUN_STATES
                and (p.get("ball") or {}).get("kind") not in ("studio", "claimed")}

    def s(v, n=600):
        return _clip(v, n) if isinstance(v, (str, int, float)) else ""

    def names(v):
        v = v if isinstance(v, list) else [v] if isinstance(v, str) else []
        return [x for x in v if isinstance(x, str) and x in known]

    out = {"headline": s(d.get("headline"), 300)}
    for key, cap in LIMITS.items():
        items = []
        for it in d.get(key) or ():
            if not isinstance(it, dict):
                continue
            if key == "yesterday":
                x = {"theme": s(it.get("theme"), 80), "projects": names(it.get("projects")),
                     "minutes": int(it["minutes"]) if isinstance(it.get("minutes"), (int, float))
                     else None, "what": s(it.get("what"))}
            elif key == "decide":
                if it.get("project") not in known or not s(it.get("question")):
                    continue
                x = {"project": it["project"], "question": s(it.get("question"), 1500),
                     "options": [s(o, 200) for o in it.get("options") or () if s(o)][:6],
                     "waiting": s(it.get("waiting"), 40), "recommend": s(it.get("recommend")),
                     "from_session": bool(it.get("from_session"))}
            elif key == "close_out":
                if it.get("project") not in known or not s(it.get("action")):
                    continue
                x = {"project": it["project"], "action": s(it.get("action"))}
            elif key == "runs":
                if it.get("project") not in runnable or not s(it.get("instruction")):
                    continue
                x = {"project": it["project"], "title": s(it.get("title"), 100)
                     or s(it.get("instruction"), 100),
                     "instruction": str(it["instruction"]).strip()[:4000],   # lines kept
                     "why": s(it.get("why")), "outward": bool(it.get("outward"))}
            elif key == "uncommitted":
                if not s(it.get("repo")) and it.get("project") not in known:
                    continue
                x = {"repo": s(it.get("repo"), 200),
                     "project": it.get("project") if it.get("project") in known else "",
                     "what": s(it.get("what")), "action": s(it.get("action"))}
            elif key == "focus":
                ps = names(it.get("projects"))
                if not ps:
                    continue
                x = {"theme": s(it.get("theme"), 80) or ps[0], "projects": ps,
                     "why": s(it.get("why")), "first_action": s(it.get("first_action"))}
            else:
                if not s(it.get("text")):
                    continue
                x = {"project": it.get("project") if it.get("project") in known else "",
                     "text": s(it.get("text"))}
            items.append(x)
            if len(items) >= cap:
                break
        out[key] = items
    if not any(out[k] for k in LIMITS) and not out["headline"]:
        return None
    return out


def write(home, bundle, cfg=None, ask_fn=None):
    """The brief from ``bundle``: ``(validated dict or None, cost, error or None)``."""
    cfg = cfg or config(home)
    with open(PROMPTS) as fp:
        prompt = fp.read() + json.dumps(bundle, indent=1, default=str) + "\n"
    fn = ask_fn or ask
    got = fn(prompt, home=home, model=cfg["model"], budget=cfg["budget_usd"])
    text, cost = got[:2]
    if not text:
        return None, cost, (got[2] if len(got) > 2 else None) or "the model did not answer"
    d = parse(text)
    if d is None:
        return None, cost, "the model's answer was not JSON"
    v = validate(d, bundle)
    if v is None:
        return None, cost, "the model's answer named nothing on the board"
    return v, cost, None


def save_bundle(home, day, bundle):
    from . import brief
    os.makedirs(brief._dir(home), exist_ok=True)
    fsutil.atomic_write(brief.path(home, day, "bundle.json"),
                        json.dumps(bundle, indent=1, default=str) + "\n")
