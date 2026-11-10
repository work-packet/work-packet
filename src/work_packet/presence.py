"""Presence: who is working on a project now (docs/collaboration.md §4.2).

A heartbeat record per source (a Claude session, a web VS Code tab, a board
shell), in ``<project dir>/presence/<source>.json``. Records hold who and when,
never what was said: a source writes them, readers decide from their age. A
project is *attended* while a record is fresh and not ended; that makes the
runner hold off (§5.1).

Stdlib only, plus ``fsutil``: the Claude Code hook (``hookcmd``) imports this on
every prompt, so it has to start fast.
"""

import json
import os
import re
import time

from . import fsutil, timelog

DIR = "presence"
TTL_S = 600                 # a record this old is gone (``[ide] presence_ttl``)
ATTACH_CAP_S = 7200         # a web tab with no other sign of you counts this long
KEEP_ENDED_S = 86400        # ended records are removed after this
KINDS = ("claude", "codex", "ide-web", "ide-desktop", "shell", "studio", "terminal")
TURNS = ("working", "waiting", "blocked", "ended")
# What a record may hold: identifiers, times and states; no prompt or reply text.
FIELDS = ("source", "kind", "via", "host", "pid", "session", "launch", "wpid", "by",
          "since", "beat", "active", "turn", "turn_since", "tool", "attached", "visible",
          "idle_since", "transcript", "waited")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def path(proj, source):
    return os.path.join(proj, DIR, _SAFE.sub("_", source)[:120] + ".json")


def _load(p):
    try:
        with open(p) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def get(proj, source):
    return _load(path(proj, source))


def beat(proj, source, now=None, **fields):
    """Create or refresh ``source``'s record with ``fields`` (only ``FIELDS``
    are kept). ``beat`` is now; ``since`` is set the first time. Returns it."""
    now = time.time() if now is None else now
    p = path(proj, source)
    rec = _load(p) or {}
    if rec.get("turn") == "ended" and fields.get("turn") != "ended":
        rec = {}                        # a new session under an old id
    was = rec.get("turn")
    rec.update({k: v for k, v in fields.items() if k in FIELDS and v is not None})
    rec["source"] = source
    rec.setdefault("since", now)
    rec["beat"] = now
    if rec.get("turn") != was:
        rec["turn_since"] = now
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, json.dumps(rec, sort_keys=True) + "\n")
    if rec.get("by"):
        try:
            timelog.add(proj, rec["by"], now, timelog.counts(fields))
        except OSError:
            pass                        # the ledger never breaks presence
    return rec


def mark(proj, source, **fields):
    """Set ``fields`` on a record without a beat (the board's own notes on it)."""
    p = path(proj, source)
    rec = _load(p)
    if rec is None:
        return None
    rec.update({k: v for k, v in fields.items() if k in FIELDS})
    fsutil.atomic_write(p, json.dumps(rec, sort_keys=True) + "\n")
    return rec


def end(proj, source, now=None):
    """The source has gone: its record says ``ended`` until it is cleaned up."""
    if os.path.exists(path(proj, source)):
        return beat(proj, source, now, turn="ended", attached=False)
    return None


def records(proj, now=None, ttl=TTL_S):
    """The live records of ``proj``: fresh and not ended (``ttl`` None: not ended,
    however old; a session waiting for you beats only when something happens).
    Records ended or silent for a day are removed."""
    now = time.time() if now is None else now
    d = os.path.join(proj, DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    out = []
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(d, n)
        rec = _load(p)
        if rec is None:
            continue
        age = now - (rec.get("beat") or 0)
        if rec.get("turn") == "ended" or age > (KEEP_ENDED_S if ttl is None else ttl):
            if age > KEEP_ENDED_S:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            continue
        out.append(rec)
    return out


def every(proj):
    """Every record of ``proj``, ended ones too, as they are (nothing removed)."""
    d = os.path.join(proj, DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [r for r in (_load(os.path.join(d, n)) for n in names if n.endswith(".json"))
            if r is not None]


def reap(proj, host, now=None, alive=None):
    """End the records of processes on ``host`` that are gone (a session killed
    without its SessionEnd hook). ``alive(pid)``: default, a /proc check that
    counts a zombie as gone. Returns how many ended."""
    alive = alive or _alive
    n = 0
    for rec in records(proj, now, ttl=None):
        pid = rec.get("pid")
        if isinstance(pid, int) and rec.get("host") == host and not alive(pid):
            end(proj, rec["source"], now)
            n += 1
    return n


def _alive(pid):
    try:
        with open("/proc/%d/stat" % pid) as fp:
            return fp.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def counts(rec, recs, now):
    """Does this live record say a person is here? A web tab alone counts only
    while it was visible, or something else beat, in the last ``ATTACH_CAP_S``
    (a tab left open overnight is not you)."""
    if rec.get("kind") != "ide-web":
        return True
    last = max([rec.get("active") or rec.get("since") or 0] +
               [r.get("beat") or 0 for r in recs if r.get("kind") != "ide-web"])
    return now - last <= ATTACH_CAP_S


def live(proj, now=None, ttl=TTL_S):
    """The records that say a person is here now (``counts``)."""
    now = time.time() if now is None else now
    recs = records(proj, now, ttl)
    return [r for r in recs if counts(r, recs, now)]


# The agents a person drives whose turn presence records carry (Claude's hooks;
# the session collector for Codex, docs/agent-state-plan.md).
AGENTS = {"claude": "Claude", "codex": "Codex"}
WHERE = {"ide-web": "VS Code (web)", "ide-desktop": "VS Code", "vscode": "VS Code",
         "terminal": "a terminal", "shell": "a board shell", "studio": "the studio"}


def where(recs):
    """Where the person is, for a card: "VS Code (web) · Claude ×2 (1 blocked) · Codex ×1"."""
    places = sorted({WHERE.get(r.get("via") or r.get("kind"), r.get("via") or "")
                     for r in recs if r.get("kind") not in AGENTS} - {""})
    if not places:
        places = sorted({WHERE.get(r.get("via"), "") for r in recs
                         if r.get("kind") in AGENTS} - {""})
    for kind in AGENTS:
        cl = [r for r in recs if r.get("kind") == kind]
        if not cl:
            continue
        blocked = sum(1 for r in cl if r.get("turn") == "blocked")
        waiting = sum(1 for r in cl if r.get("turn") == "waiting")
        bits = ["%d blocked" % blocked] if blocked else []
        bits += ["%d waiting" % waiting] if waiting else []
        places.append("%s ×%d%s" % (AGENTS[kind], len(cl),
                                    " (%s)" % ", ".join(bits) if bits else ""))
    return " · ".join(places)


def attended(proj, now=None, ttl=TTL_S):
    """``(True, since)`` when a person is working on ``proj`` (``since``: the
    earliest live record's start), else ``(False, None)``."""
    now = time.time() if now is None else now
    got = live(proj, now, ttl)
    if not got:
        return False, None
    return True, min(r.get("since") or now for r in got)


def find_project(start):
    """The project directory a path is in, walking up: a packet folder's
    ``.work-packet/``, or a legacy project directory (``project.toml`` beside
    ``packets/``). None outside any."""
    d = os.path.abspath(start)
    while True:
        dot = os.path.join(d, ".work-packet")
        if os.path.isfile(os.path.join(dot, "project.toml")):
            return dot
        if os.path.isfile(os.path.join(d, "project.toml")) and (
                os.path.isdir(os.path.join(d, "packets")) or os.path.basename(d) == ".work-packet"):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def _handoffs(journal_path):
    """A person's go-aheads in the packet's journal, oldest first: ``handoff``
    records, and ``admin`` resume and wake (a torn last line is skipped)."""
    out = []
    try:
        with open(journal_path, encoding="utf-8") as fp:
            for line in fp:
                if '"defer"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and (r.get("type") == "handoff" or (
                        r.get("type") == "admin" and r.get("op") in ("resume", "wake"))):
                    out.append(r)
    except OSError:
        pass
    return out


def _epoch(ts):
    import calendar
    try:
        return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


# --- by-hand edits (design §4.2 fallback) ------------------------------------------

EDIT_SKIP = frozenset((".git", ".hg", ".svn", ".work-packet", ".vscode", ".claude", ".codex",
                       "node_modules",
                       ".venv", "venv", "__pycache__", "packages", ".tox", ".mypy_cache",
                       ".pytest_cache", ".ruff_cache"))
EDIT_MAX = 20000            # entries looked at; a bigger tree is only partly seen
EDIT_EVERY_S = 60
_edits = {}


def edited(folder, now=None, limit=EDIT_MAX):
    """The newest change time of a file under the packet ``folder``, or None. Version
    control, tool and cache folders, the board's own folder and the cards
    (``*.wp.md``) are left out. Cached ``EDIT_EVERY_S``. It sees an editor with no
    Claude session in it (desktop VS Code opened by hand) and works in a plain
    folder."""
    now = time.time() if now is None else now
    got = _edits.get(folder)
    if got and 0 <= now - got[0] < EDIT_EVERY_S:
        return got[1]
    newest, seen, stack = None, 0, [folder]
    while stack and seen < limit:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for de in it:
                seen += 1
                try:
                    if de.is_dir(follow_symlinks=False):
                        if de.name not in EDIT_SKIP:
                            stack.append(de.path)
                    elif de.is_file(follow_symlinks=False) and not de.name.endswith(".wp.md"):
                        m = de.stat(follow_symlinks=False).st_mtime
                        if m <= now + 60 and (newest is None or m > newest):
                            newest = m
                except OSError:
                    continue
    _edits[folder] = (now, newest)
    return newest


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def edits_hold(proj, journals, now=None, ttl=TTL_S):
    """Files in the packet folder changed in the last ``ttl``, after anything the
    runner or the board wrote to ``journals`` (so the runner's own writes, and
    edits made before a hand-off, don't count): ``"N min ago"``, else None. Only
    the packet layout: a legacy project opens read-only."""
    from . import layout
    if not layout.is_packet_layout(proj):
        return None
    now = time.time() if now is None else now
    m = edited(layout.packet_folder(proj), now)
    after = max([_mtime(j) for j in journals] + [0.0])
    if m is None or m <= after + 1 or now - m > ttl:
        return None
    return "%d min ago" % max(1, round((now - m) / 60))


def holds(proj, journals, now=None, ttl=TTL_S):
    """Why the runner should not start a step in ``proj`` now (docs/collaboration.md
    §5.1), or None. Someone is working on it, and the newest hand-off in
    ``journals`` (paths: the packet's and its root's) was not made while they were
    there with ``defer: false`` (§5.2: hand off while present, and it starts)."""
    now = time.time() if now is None else now
    on, since = attended(proj, now, ttl)
    if not on:
        ago = edits_hold(proj, journals, now, ttl)
        return ("files in it were edited by hand %s; it starts once they are quiet for "
                "%d min, or when you hand it off" % (ago, ttl // 60)) if ago else None
    hs = sorted((h for j in journals for h in _handoffs(j)), key=lambda h: h.get("t") or "")
    if hs and hs[-1].get("defer") is False:
        t = _epoch(hs[-1].get("t"))
        if t is not None and t >= since - 1:
            return None
    kinds = sorted({r.get("via") or r.get("kind") for r in records(proj, now, ttl)} - {None})
    return "someone is working on it (%s); it starts when they leave or hand it off" % (
        ", ".join(kinds) or "present")
