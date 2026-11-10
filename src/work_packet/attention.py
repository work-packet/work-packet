"""What needs you, from the sessions you drive (docs/collaboration.md §4.3), and
the snoozes you set on any item.

The board's own reasons (a question, a failure, finished work to review) come
from the packets' state (``dash/data.overview``). This adds the ones only
presence records know about:

- **blocked**: a Claude session waits on a permission prompt (after
  ``BLOCKED_AFTER_S``);
- **your turn**: a Claude session you drive ended its turn and nothing has come
  since (after ``[ide] idle_escalate``);
- **stale**: a session that says it is working has been silent for an hour.

None of them is raised while a web VS Code tab on the project is visible: you
already see it. Items are derived, never stored, so they close when their cause
does. A snooze is the only state: per person, in ``$WPK_HOME/attention/<user>.json``,
keyed by the item *and* when its cause began, so anything new brings it back.
"""

import json
import os
import re
import time

from . import fsutil, presence

BLOCKED_AFTER_S = 120
IDLE_ESCALATE_S = 900
STALE_S = 3600
URGENCY = {"question": 3, "blocked": 3, "failure": 3, "review": 2, "decision": 2,
           "your turn": 1, "stale": 1, "notify": 0}
_SAFE = re.compile(r"[^A-Za-z0-9_.@-]")


def _visible(recs):
    return any(r.get("kind") == "ide-web" and r.get("visible") for r in recs)


def session_items(proj, now=None, idle_escalate=IDLE_ESCALATE_S):
    """``[{"type", "since", "text", "source", "session", "tool"}]`` for ``proj``'s
    Claude and Codex sessions, oldest first."""
    now = time.time() if now is None else now
    recs = presence.records(proj, now, ttl=None)
    if _visible(presence.live(proj, now)):
        return []
    out = []
    for r in recs:
        if r.get("kind") not in presence.AGENTS:
            continue
        since = r.get("turn_since") or r.get("beat") or now
        name = presence.AGENTS[r["kind"]]
        where = presence.WHERE.get(r.get("via"), name)
        base = {"since": since, "source": r.get("source"), "session": r.get("session"),
                "tool": r.get("tool") or "", "via": r.get("via")}
        if r.get("turn") == "blocked" and now - since >= BLOCKED_AFTER_S:
            out.append(dict(base, type="blocked", text="%s (%s) wants to run %s" % (
                name, where, r.get("tool") or "a tool")))
        elif r.get("turn") == "waiting" and now - since >= idle_escalate:
            out.append(dict(base, type="your turn", text="%s (%s) is waiting for you"
                            % (name, where)))
        elif r.get("turn") == "working" and now - (r.get("beat") or now) >= STALE_S:
            out.append(dict(base, since=r.get("beat"), type="stale",
                            text="%s (%s) said it was working, and has been silent since"
                            % (name, where)))
    return sorted(out, key=lambda x: x["since"])


def log_waits(proj, root, now=None, idle_escalate=IDLE_ESCALATE_S):
    """The journal's ``turn-waiting`` record (docs/collaboration.md §4.5): a Claude
    or Codex session that has waited for you ``idle_escalate``, once per wait. Written by
    the board's loop, not by the hook. Returns how many it wrote."""
    from . import journal, layout
    now = time.time() if now is None else now
    n = 0
    for r in presence.records(proj, now, ttl=None):
        since = r.get("turn_since")
        if r.get("kind") not in presence.AGENTS or r.get("turn") != "waiting" or not since or \
                now - since < idle_escalate or r.get("waited") == since:
            continue
        wpid = r.get("wpid") or root
        if not wpid:
            continue
        ts = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        try:
            journal.append(os.path.join(layout.run_dir(proj, wpid), "journal.jsonl"), {
                "type": "turn-waiting", "t": ts(since + idle_escalate), "by": r.get("by"),
                "session": r.get("session"), "since": ts(since),
                "actor": {"kind": r["kind"], "via": r.get("via"), "session": r.get("session")}})
        except OSError:
            continue
        presence.mark(proj, r["source"], waited=since)
        n += 1
    return n


def key(project, item):
    """An item's identity for a snooze: what it is, and when its cause began."""
    return "%s|%s|%s|%d" % (project, item.get("type"), item.get("source") or "",
                            int(item.get("since") or 0))


def _path(home, user):
    return os.path.join(home, "attention", _SAFE.sub("_", user or "you") + ".json")


def snoozes(home, user, now=None):
    """``{key: until}`` still in force."""
    now = time.time() if now is None else now
    try:
        with open(_path(home, user)) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in (d if isinstance(d, dict) else {}).items()
            if isinstance(v, (int, float)) and v > now}


def snooze(home, user, k, until, now=None):
    """Hide item ``k`` until ``until`` (epoch). Expired snoozes are dropped."""
    now = time.time() if now is None else now
    d = snoozes(home, user, now)
    d[k] = until
    p = _path(home, user)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    fsutil.atomic_write(p, json.dumps(d, sort_keys=True) + "\n")


def until_of(choice, now=None, tz=None):
    """When a snooze choice ends: ``1h``, ``tomorrow`` (08:00 local), ``change``
    (until its cause changes: as long as it lasts)."""
    import datetime
    now = time.time() if now is None else now
    if choice == "1h":
        return now + 3600
    if choice == "tomorrow":
        d = datetime.datetime.fromtimestamp(now, tz) + datetime.timedelta(days=1)
        return d.replace(hour=8, minute=0, second=0, microsecond=0).timestamp()
    return now + 365 * 86400


SITTING_S = 1800            # views closer than this are one visit


def _visits(home, user):
    p = _path(home, user)[:-5] + ".visit.json"
    try:
        with open(p) as fp:
            d = json.load(fp)
        return p, d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return p, {}


def since(home, user, now=None):
    """When ``user``'s previous visit to the Desk ended (None before any): what
    "since you were last here" starts from. Views within ``SITTING_S`` of each
    other are one visit, so a reload keeps it. Reads only (a GET changes nothing)."""
    now = time.time() if now is None else now
    _, d = _visits(home, user)
    last = d.get("last")
    if not isinstance(last, (int, float)):
        return None
    return last if now - last > SITTING_S else d.get("since")


def visit(home, user, now=None):
    """Note that ``user`` is looking at the Desk now (the page's beacon, a POST).
    Returns ``since`` as it was before."""
    now = time.time() if now is None else now
    was = since(home, user, now)
    p, _ = _visits(home, user)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    fsutil.atomic_write(p, json.dumps({"last": now, "since": was}) + "\n")
    return was
