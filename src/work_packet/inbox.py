"""The Inbox (docs/collaboration.md W8, §9.6): what might become work, until you
decide. One file per item in ``$WPK_HOME/inbox/``. Items come from:

- quick capture: a line from the Desk, the phone, ``wpk todo`` or ``/wpk-todo``
  (``source``: board, cli, session, phone);
- a watcher with ``propose = true``: an issue it found (``source: watch``;
  ``ref``: the watcher and the issue key), made with the watcher's recipe on accept;
- the runner: ``follow_ups:`` in a step's memento (``source: agent``; ``project``
  and ``ref.wpid``: the packet that proposed it).

Requests from other projects that arrived but have not started are shown with
them (``requests``), derived and never stored. Actions: accept (make a packet),
drop (decline), merge into a project (a note to its root), snooze.
"""

import json
import os
import re
import time
import uuid

from . import fsutil

TEXT_MAX = 2000
_ID = re.compile(r"^[0-9a-f]{12}$")


def _dir(home):
    return os.path.join(home, "inbox")


def add(home, text, by=None, source=None, project=None, board=None, now=None, ref=None,
        iid=None):
    """Capture ``text``. ``source``: where it came from (board, cli, session, phone,
    watch, agent); ``project``: the project it was captured from, if any; ``ref``:
    what accepting it needs (a watcher's issue). Returns the item."""
    text = " ".join((text or "").split()) if "\n" not in (text or "") else (text or "").strip()
    if not text:
        raise ValueError("nothing to capture")
    if len(text) > TEXT_MAX:
        raise ValueError("over %d characters" % TEXT_MAX)
    item = {"id": iid or uuid.uuid4().hex[:12], "t": time.time() if now is None else now,
            "text": text, "by": by, "source": source, "project": project, "board": board}
    if ref:
        item["ref"] = ref
    os.makedirs(_dir(home), mode=0o700, exist_ok=True)
    fsutil.atomic_write(os.path.join(_dir(home), item["id"] + ".json"),
                        json.dumps(item) + "\n")
    return item


def items(home, now=None, snoozed=False):
    """Every item, oldest first; a snoozed one only with ``snoozed``."""
    now = time.time() if now is None else now
    out = []
    try:
        names = os.listdir(_dir(home))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json") or not _ID.match(n[:-5]):
            continue
        try:
            with open(os.path.join(_dir(home), n)) as fp:
                d = json.load(fp)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("text") and (
                snoozed or not (d.get("until") or 0) > now or _changed(home, d)):
            out.append(d)
    return sorted(out, key=lambda d: d.get("t") or 0)


CHANGE_MAX_S = 7 * 86400    # "until it changes" lasts at most this long


def _changed(home, d):
    """A snooze "until it changes" ends when the item's project has moved since
    (its root journal was written; plan G6)."""
    at = d.get("change_at")
    if not at or not d.get("project"):
        return False
    from . import layout, registry
    try:
        e = registry.get(d["project"], home)
        j = os.path.join(layout.run_dir(e["path"], e["root"]), "journal.jsonl") if e else None
        return bool(j) and os.path.getmtime(j) > at
    except (OSError, KeyError, TypeError):
        return False


def get(home, iid):
    return next((d for d in items(home, snoozed=True) if d["id"] == iid), None)


def snooze(home, iid, until, change=False, now=None):
    """Hide an item until ``until`` (epoch). ``change``: or until its project moves,
    for at most ``CHANGE_MAX_S``. True if it was there."""
    d = get(home, iid)
    if d is None:
        return False
    now = time.time() if now is None else now
    d["until"] = min(until, now + CHANGE_MAX_S) if change else until
    if change and d.get("project"):
        d["change_at"] = now
    else:
        d.pop("change_at", None)
    fsutil.atomic_write(os.path.join(_dir(home), iid + ".json"), json.dumps(d) + "\n")
    return True


# --- follow-ups the runner proposed -------------------------------------------------

FOLLOW_UPS_MAX = 5


def follow_ups(home, pkt, meta, project, by="runner", step=0):
    """A committed memento's ``follow_ups:`` to Inbox items (at most
    ``FOLLOW_UPS_MAX`` a step). Returns the items."""
    got = meta.get("follow_ups") if isinstance(meta, dict) else None
    if isinstance(got, str):
        got = [got]
    out = []
    import hashlib
    for i, t in enumerate((got or [])[:FOLLOW_UPS_MAX]):
        if isinstance(t, str) and t.strip():
            iid = hashlib.sha1(("%s:%s:%d" % (pkt.wpid, step, i)).encode()).hexdigest()[:12]
            try:
                out.append(add(home, t, by=by, source="agent", project=project,
                               ref={"wpid": pkt.wpid, "step": step}, iid=iid))
            except (ValueError, OSError):
                continue
    return out


# --- duplicates ---------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]{4,}")
_COMMON = {"that", "this", "with", "from", "have", "make", "should", "into", "when",
           "then", "they", "them", "what", "which", "there", "would", "could", "about",
           "issue", "packet", "work", "need", "needs"}


def _words(text):
    return {w for w in _WORD.findall((text or "").lower()) if w not in _COMMON}


def similar(text, cards, at_least=0.34):
    """The open projects whose name and intent share enough words with ``text``
    (a duplicate hint on accept): ``[(name, overlap)]``, best first."""
    mine = _words(text)
    if len(mine) < 2:
        return []
    out = []
    for c in cards:
        if c.get("lifecycle", "open") != "open":
            continue
        theirs = _words("%s %s" % (c["name"].replace("-", " "), c.get("intent") or ""))
        if not theirs:
            continue
        o = len(mine & theirs) / float(min(len(mine), len(theirs)))
        if o >= at_least and len(mine & theirs) >= 2:
            out.append((c["name"], round(o, 2)))
    return sorted(out, key=lambda x: -x[1])[:3]


# --- requests that have not started ------------------------------------------------

def requests(h=None):
    """Requests from other projects that made or reached a project which has not
    started on them (it is PAUSED, waiting for its owner): ``[{"id", "title",
    "from", "from_wpid", "project", "reason"}]``."""
    from . import requests as reqs
    out = []
    for e in reqs.entries(h):
        if e.get("state") != "open" or "project" not in e["to"]:
            continue
        d = reqs.delegate_state(e)
        if d and d[0] == "PAUSED":
            out.append({"id": e["id"], "title": e["title"], "from": e["from"]["project"],
                        "from_wpid": e["from"]["wpid"],
                        "project": e["to"]["project"], "reason": d[2] or ""})
    return out


def decline_request(from_wpid, rid, reason, by=None, h=None):
    """Say no to a request that hasn't started (plan G6): the requester gets the
    answer "declined" (it wakes, if it waits on it), and the project the request
    made, which never ran, is dropped. Returns a message."""
    from . import executor
    from . import requests as reqs
    from .packet import Packet
    by = by or executor._who()
    e = reqs.get(from_wpid, rid, h)
    if e is None or e.get("state") != "open":
        raise reqs.RequestError("no open request %s" % rid)
    why = (reason or "").strip() or "no reason given"
    text = "Request `%s` (%s) was declined by %s: %s" % (rid, e["title"], by, why)
    if not reqs.deliver(e, text, "declined", by, h):
        return "declined; %s gets the answer when its running step ends" % e["from"]["project"]
    t = e["to"]
    if t.get("path"):
        dpkt = Packet(t["path"])
        try:
            if dpkt.load_status()[0]["step"] == 0:
                executor.mark(dpkt, "drop", by, "declined request %s: %s" % (rid, why))
        except Exception:               # noqa: BLE001: the answer went; the project stays
            pass
    return "declined; %s has the answer" % e["from"]["project"]


def drop(home, iid):
    """Remove an item (made into a packet, or dropped). True if it was there."""
    if not _ID.match(iid or ""):
        return False
    try:
        os.unlink(os.path.join(_dir(home), iid + ".json"))
        return True
    except OSError:
        return False
