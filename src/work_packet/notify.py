"""Attention delivery (docs/collaboration.md §4.3, §7.6; plan C6): a push to your
phone when something needs you and you aren't looking, and a digest of the rest.

Only a **question** (the runner asked you something) and a **blocked** session
(Claude waits on a permission prompt) push, and only past their threshold, when
no web VS Code tab on that project is visible, and when you haven't snoozed it.
"Your turn" never pushes (D5). Each item pushes once; past ``max_per_hour`` the
rest wait for the digest. Everything else that needs you (finished work to
review, a failure, your turn) goes to the digest, if you turned one on:
``hourly``, or ``daily`` at ``digest_at``.

The channel is ntfy (D12): ``[notify] ntfy_url`` is the topic's URL (a public
ntfy.sh topic, or your own server); ``ntfy_token`` if it needs one. Nothing is
pushed without it. An open board tab can also show browser notifications
(``dash/notify.js``, from ``GET /attention.json``); that needs no config here.

What was pushed is kept in ``$WPK_HOME/notify/state.json``, so a restart of the
board doesn't push again.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import fsutil

PUSH = ("question", "blocked")
QUESTION_AFTER_S = 300          # give the board a chance first
MAX_PER_HOUR = 6
DIGEST_AT = "17:30"
KEEP = 200                      # digest lines kept at most
TIMEOUT_S = 10

# The Desk's attention kinds as the types of §4.3.
TYPE = {"needs": "question", "blocked": "blocked", "failed": "failure", "done": "review",
        "yourturn": "your turn", "trouble": "failure", "stalled": "decision",
        "stuck": "decision", "stale": "stale", "stopped": "review", "atrisk": "decision"}


class NotifyError(Exception):
    pass


def config(cfg):
    """``[notify]`` with its defaults."""
    t = dict(cfg or {})
    t.setdefault("ntfy_url", "")
    t.setdefault("ntfy_token", "")
    t.setdefault("question_after_s", QUESTION_AFTER_S)
    t.setdefault("max_per_hour", MAX_PER_HOUR)
    t.setdefault("digest", "off")
    t.setdefault("digest_at", DIGEST_AT)
    t.setdefault("brief", False)
    return t


# --- what needs you ---------------------------------------------------------------------

def items(cols, now=None):
    """Every attention item on the board, ``[{"key", "type", "project", "text",
    "since", "url"}]``, from ``data.board()``'s columns. The same list the Desk
    shows (before snoozes)."""
    from .dash import data
    now = time.time() if now is None else now
    cards = [c for v in cols.values() for c in v]
    rows = [{"kind": {"question": "needs", "failure": "failed"}[c["ball"]["kind"]], "card": c}
            for c in cols.get("Needs you", ()) if c["ball"]["kind"] in ("question", "failure")]
    rows += [{"kind": {"your turn": "yourturn"}.get(it["type"], it["type"]), "card": c,
              "item": it} for c in cards for it in c.get("sessions") or ()]
    rows += [{"kind": "job", "card": c, "item": it} for c in cards
             for it in c.get("job_items") or ()]
    rows += [{"kind": "atrisk", "card": c, "item": data.risk_item(c)} for c in cards
             if c.get("at_risk")]
    rows += [{"kind": c["unread"]["kind"], "card": c} for c in cards if c.get("unread")]
    out = []
    for a in rows:
        c = a["card"]
        typ = TYPE.get(a["kind"], "notify")
        if a["kind"] == "job":
            typ = "failure" if a["item"]["failed"] else "review"
        if a.get("item"):
            since, text = a["item"].get("since"), a["item"]["text"]
        else:
            at = (c.get("unread") or {}).get("at") if a["kind"] in ("done", "stopped") else \
                (c.get("root") or {}).get("updated")
            since = at.timestamp() if at else now
            text = c["ball"]["text"] if a["kind"] in ("needs", "failed") else \
                "finished: review it" if a["kind"] == "done" else "stopped"
        out.append({"key": data.attention_key(a), "type": typ,
                    "project": c["name"], "text": text, "since": since or now,
                    "url": "/p/%s/jobs/%s" % (c["name"], a["item"]["job"])
                    if a["kind"] == "job" else "/p/%s" % c["name"],
                    "seen": any(r.get("kind") == "ide-web" and r.get("visible")
                                for r in c.get("present") or ())})
    return out


def pushable(it, cfg, now):
    """Is ``it`` one to push now (its type, past its threshold)? Blocked sessions
    come already past ``attention.BLOCKED_AFTER_S``. Nothing pushes while a web VS
    Code tab on its project is visible (``seen``): you are looking at it."""
    if it["type"] not in PUSH or it.get("seen"):
        return False
    if it["type"] == "question":
        return now - it["since"] >= cfg["question_after_s"]
    return True


# --- state ------------------------------------------------------------------------------

def _path(home):
    return os.path.join(home, "notify", "state.json")


def load_state(home):
    try:
        with open(_path(home)) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    d.setdefault("sent", {})            # key -> when pushed (or queued for the digest)
    d.setdefault("log", [])             # push times, the last hour's
    d.setdefault("digest", [])          # lines waiting for the digest
    d.setdefault("digest_t", 0)
    d.setdefault("brief", "")           # the day whose brief was pushed
    return d


def _save(home, s):
    os.makedirs(os.path.dirname(_path(home)), mode=0o700, exist_ok=True)
    fsutil.atomic_write(_path(home), json.dumps(s, sort_keys=True) + "\n")


# --- the channel ------------------------------------------------------------------------

def post(cfg, title, body, click=None, priority=None, tags=None):
    """Send one message to ntfy. Raises ``NotifyError``."""
    url = cfg.get("ntfy_url")
    if not url:
        raise NotifyError("no [notify] ntfy_url")
    if not url.startswith(("https://", "http://")):
        raise NotifyError("ntfy_url must be an http(s) URL")
    h = {"Title": title.encode("utf-8").decode("latin-1", "replace")[:200],
         "Content-Type": "text/plain; charset=utf-8"}
    if click:
        h["Click"] = click
    if priority:
        h["Priority"] = str(priority)
    if tags:
        h["Tags"] = ",".join(tags)
    if cfg.get("ntfy_token"):
        h["Authorization"] = "Bearer " + cfg["ntfy_token"]
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise NotifyError("ntfy said %s %s" % (e.code, e.reason)) from None
    except (urllib.error.URLError, OSError) as e:
        raise NotifyError("ntfy: %s" % getattr(e, "reason", e)) from None


def _link(cfg, url):
    base = (cfg.get("link") or "").rstrip("/")
    return base + url if base else None


def _title(it):
    return {"question": "%s asks you" % it["project"],
            "blocked": "%s: Claude is blocked" % it["project"]}.get(
        it["type"], "%s: %s" % (it["project"], it["type"]))


def _digest_due(cfg, s, now):
    if cfg["digest"] == "hourly":
        return now - s["digest_t"] >= 3600
    if cfg["digest"] == "daily":
        dt = datetime.fromtimestamp(now)
        hh, _, mm = str(cfg["digest_at"]).partition(":")
        try:
            at = dt.replace(hour=int(hh), minute=int(mm or 0), second=0, microsecond=0)
        except ValueError:
            at = dt.replace(hour=17, minute=30, second=0, microsecond=0)
        return dt >= at and s["digest_t"] < at.timestamp()
    return False


def tick(home, cols, cfg, snoozed=(), now=None, send=post, brief_md=None, day=None,
         busy=None):
    """One pass (the board's loop): push what is new and pushable, queue the rest
    for the digest, send the digest when it is due, and today's brief if asked.
    ``snoozed``: keys you snoozed. Returns ``{"pushed": [key], "queued": [key],
    "digest": n lines sent, "errors": [str]}``. ``busy``: the meeting you are in
    (``icsfeed.busy``): nothing is pushed or sent until it ends (plan F3f), and
    what would have been pushed goes out on the first pass after."""
    now = time.time() if now is None else now
    cfg = config(cfg)
    out = {"pushed": [], "queued": [], "digest": 0, "errors": []}
    if not cfg["ntfy_url"]:
        return out
    s = load_state(home)
    s["log"] = [t for t in s["log"] if now - t < 3600]
    current = items(cols, now)
    keys = {it["key"] for it in current}
    for it in current:
        if it["key"] in s["sent"] or it["key"] in snoozed:
            continue
        if pushable(it, cfg, now):
            if busy:
                out.setdefault("held", []).append(it["key"])
                continue                         # pushed when the meeting ends
            if len(s["log"]) < int(cfg["max_per_hour"]):
                try:
                    send(cfg, _title(it), it["text"], click=_link(cfg, it["url"]),
                         priority=4, tags=["bell"])
                except NotifyError as e:
                    out["errors"].append(str(e))
                    continue                     # try again next pass
                s["log"].append(now)
                out["pushed"].append(it["key"])
            else:
                s["digest"].append({"key": it["key"], "line": "%s: %s" % (
                    _title(it), it["text"])})
                out["queued"].append(it["key"])
            s["sent"][it["key"]] = now
        elif it["type"] not in PUSH and it["type"] != "notify" and cfg["digest"] != "off":
            s["digest"].append({"key": it["key"], "line": "%s (%s): %s" % (
                it["project"], it["type"], it["text"])})
            s["sent"][it["key"]] = now
            out["queued"].append(it["key"])
    # An item that closed needs no digest line, and may come back as new.
    s["sent"] = {k: v for k, v in s["sent"].items() if k in keys}
    s["digest"] = [d for d in s["digest"] if d["key"] in keys][-KEEP:]
    if s["digest"] and _digest_due(cfg, s, now) and not busy:
        lines = [d["line"] for d in s["digest"]]
        try:
            send(cfg, "wpk: %d waiting for you" % len(lines),
                 "\n".join("- " + x for x in lines), click=_link(cfg, "/"), priority=2)
            out["digest"] = len(lines)
            s["digest"], s["digest_t"] = [], now
        except NotifyError as e:
            out["errors"].append(str(e))
    elif _digest_due(cfg, s, now):
        s["digest_t"] = now
    if cfg["brief"] and brief_md and day and s["brief"] != day and not busy:
        try:
            send(cfg, "Today's focus", brief_md, click=_link(cfg, "/brief"), priority=3)
            s["brief"] = day
        except NotifyError as e:
            out["errors"].append(str(e))
    _save(home, s)
    return out


def test(cfg):
    """The Settings page's "send a test push"."""
    post(config(cfg), "wpk: test", "Pushes from your board arrive here.", tags=["wave"])


def run(home, now=None, send=post):
    """The board's pass: ``tick`` over the board as it is now, with your snoozes
    and today's brief. Does nothing (and reads nothing) without ``ntfy_url``."""
    from . import attention, brief, executor, registry
    cfg = config(registry.load_config_file(home).get("notify"))
    if not cfg["ntfy_url"]:
        return None
    from .dash import data
    now = time.time() if now is None else now
    cols, _ = data.board(home)
    day = datetime.fromtimestamp(now).date().isoformat()
    b = brief.load(home, day) if cfg["brief"] else None
    try:
        from . import icsfeed
        busy = icsfeed.busy(icsfeed.events(home), now) if icsfeed.source(home) else None
    except Exception:                   # noqa: BLE001: a bad feed never stops a push
        busy = None
    return tick(home, cols, cfg, snoozed=attention.snoozes(home, executor._who(), now),
                now=now, send=send, brief_md=brief.render(b) if b else None, day=day,
                busy=busy)
