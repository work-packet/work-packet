"""Packet cards: ``<name>.wp.md`` (docs/work-data-design.md §6).

A card is YAML front matter, a brief (the text before the first entry) and
a thread of entries. Each entry starts with a heading in a fixed form::

    ## <kind>[ <arg>] · <who> · <YYYY-MM-DD HH:MM:SSZ>

and may end with git-style trailers (``Key: value`` lines).

The reader is lenient: it never raises, and what it cannot make sense of is
kept in the text and listed in ``Card.problems``. The writer is strict and
canonical: ``render(parse(render(c))) == render(c)``. ``append()`` is the one
way to add to a card on disk. Numbers never come from cards (§6.5).
"""

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from . import frontmatter, fsutil

FORMAT = 1
SUFFIX = ".wp.md"

KINDS = ("sent", "request", "accepted", "declined", "question", "answer", "note",
         "handoff", "progress", "result", "pinned", "cancelled", "closed", "replied",
         "reopened")

# Keys in the order the writer puts them; others follow in their own order.
KEY_ORDER = ("packet", "id", "name", "title", "by", "to", "parent", "origin", "work",
             "inputs", "setup", "repro", "reply", "watch", "notify", "budget", "due",
             "tags", "state", "updated")
CACHE_KEYS = ("state", "updated")

NAME_RX = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
TIME_FMT = "%Y-%m-%d %H:%M:%SZ"
HEAD_RX = re.compile(
    r"^## (?P<kind>[a-z]+)(?: (?P<arg>[A-Za-z0-9][A-Za-z0-9._-]*))? · (?P<who>[^·\n]+?) · "
    r"(?P<at>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z)\s*$")
TRAILER_RX = re.compile(r"^(?P<k>[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*): (?P<v>.*\S)\s*$")
_FENCE_RX = re.compile(r"^\s{0,3}(```|~~~)")
_GUARD = "<!-- -->"   # ends a body whose last paragraph would read as trailers


@dataclass
class Entry:
    kind: str
    who: str
    at: str                       # "YYYY-MM-DD HH:MM:SSZ"
    body: str = ""
    trailers: List[Tuple[str, str]] = field(default_factory=list)
    arg: Optional[str] = None

    @property
    def key(self):
        return (self.at, self.who, self.kind, self.arg or "")

    def get(self, k, default=None):
        for kk, v in self.trailers:
            if kk == k:
                return v
        return default

    def all(self, k):
        return [v for kk, v in self.trailers if kk == k]

    def heading(self):
        kind = self.kind + (" " + self.arg if self.arg else "")
        return "## %s · %s · %s" % (kind, self.who, self.at)

    def to_json(self):
        d = {"kind": self.kind, "who": self.who, "at": self.at, "body": self.body,
             "trailers": [list(t) for t in self.trailers]}
        if self.arg:
            d["arg"] = self.arg
        return d


@dataclass
class Card:
    meta: dict = field(default_factory=dict)
    brief: str = ""
    entries: List[Entry] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)

    @property
    def name(self):
        return self.meta.get("name")

    @property
    def id(self):
        return self.meta.get("id")

    @property
    def title(self):
        return self.meta.get("title")

    def state(self):
        return derive_state(self.entries)

    def to_json(self):
        return {"packet": self.meta.get("packet", FORMAT), "meta": self.meta,
                "brief": self.brief, "entries": [e.to_json() for e in self.entries],
                "state": self.state(), "problems": list(self.problems)}


# --- ids and times ----------------------------------------------------------------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(ms=None):
    """A ULID: 48 bits of milliseconds and 80 random bits, Crockford base32."""
    ms = int(time.time() * 1000) if ms is None else ms
    n = (ms << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


def stamp(dt=None):
    """``dt`` (default now) as an entry time."""
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime(TIME_FMT)


def stamp_iso(s):
    """``2026-10-27T09:12:03Z`` (the v0.2 journal form) as an entry time."""
    return s.replace("T", " ")[:19] + "Z"


def name_from(title):
    """A card name from a title: lower case, dashes, at most 48 characters."""
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    s = s[:48].rstrip("-")
    return s or "packet"


def is_name(s):
    return isinstance(s, str) and bool(NAME_RX.match(s))


# --- reading ----------------------------------------------------------------------

def _plain(v):
    """YAML values as JSON-compatible ones (datetimes become strings)."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _split_trailers(lines):
    """(body lines, trailers) from an entry's lines (blank edges already trimmed)."""
    i = len(lines)
    while i > 0 and lines[i - 1].strip():
        i -= 1
    tail = lines[i:]
    if not tail or not all(TRAILER_RX.match(ln) for ln in tail):
        return lines, []
    body = lines[:i]
    while body and not body[-1].strip():
        body.pop()
    return body, [(m.group("k"), m.group("v")) for m in map(TRAILER_RX.match, tail)]


def _trim(lines):
    a, b = 0, len(lines)
    while a < b and not lines[a].strip():
        a += 1
    while b > a and not lines[b - 1].strip():
        b -= 1
    return lines[a:b]


def parse(text):
    """A Card from ``text``. Never raises; see ``Card.problems``."""
    card = Card()
    text = (text or "").replace("\r\n", "\n")
    try:
        meta, rest = frontmatter.parse(text)
    except frontmatter.FrontMatterError as e:
        card.problems.append("front matter: %s" % e)
        meta, rest = {}, text
    card.meta = _plain(meta or {})
    lines = rest.split("\n")
    fenced = False
    cur, buf, brief = None, [], None
    for ln in lines:
        if _FENCE_RX.match(ln):
            fenced = not fenced
        m = None if fenced else HEAD_RX.match(ln)
        if m is None:
            if not fenced and ln.startswith("## ") and " · " in ln:
                card.problems.append("not an entry heading, kept as text: %r" % ln[:80])
            buf.append(ln)
            continue
        if cur is None:
            brief = buf
        else:
            _finish(card, cur, buf)
        cur, buf = Entry(kind=m.group("kind"), arg=m.group("arg"),
                         who=m.group("who").strip(), at=m.group("at")), []
    if cur is None:
        brief = buf
    else:
        _finish(card, cur, buf)
    if fenced:
        card.problems.append("a code fence is not closed")
    card.brief = "\n".join(_trim(brief))
    return card


def _finish(card, e, buf):
    lines = _trim(buf)
    body, e.trailers = _split_trailers(lines)
    if body and body[-1].strip() == _GUARD:
        body = _trim(body[:-1])
    e.body = "\n".join(body)
    if e.kind not in KINDS:
        card.problems.append("unknown entry kind %r at %s" % (e.kind, e.at))
    card.entries.append(e)


def load(path):
    with open(path, encoding="utf-8", errors="replace") as fp:
        return parse(fp.read())


# --- writing ----------------------------------------------------------------------

def _escape(text):
    """Text with any line that would read as an entry heading escaped."""
    out, fenced = [], False
    for ln in (text or "").replace("\r\n", "\n").split("\n"):
        if _FENCE_RX.match(ln):
            fenced = not fenced
        out.append("\\" + ln if not fenced and HEAD_RX.match(ln) else ln.rstrip())
    return "\n".join(_trim(out))


def _ordered(meta):
    d = {k: meta[k] for k in KEY_ORDER if k in meta and meta[k] is not None}
    d.update((k, v) for k, v in meta.items() if k not in d and v is not None)
    return d


def render(card):
    """The canonical text of ``card``."""
    out = frontmatter.dump(_ordered(card.meta), "") if card.meta else ""
    brief = _escape(card.brief)
    out += brief + "\n" if brief else ""
    for e in card.entries:
        out += "\n" + e.heading() + "\n"
        body = _escape(e.body)
        if body:
            blines = body.split("\n")
            if _split_trailers(blines)[1]:
                body += "\n" + _GUARD
            out += "\n" + body + "\n"
        if e.trailers:
            out += "\n" + "".join("%s: %s\n" % (k, " ".join(str(v).split()))
                                  for k, v in e.trailers)
    return out


def refresh(card):
    """Update the cached ``state`` and ``updated`` keys from the thread."""
    if card.entries:
        card.meta["state"] = card.state()
        card.meta["updated"] = max(e.at for e in card.entries)
    elif "state" in card.meta or card.meta.get("packet"):
        card.meta["state"] = "draft"
    return card


def save(path, card):
    fsutil.atomic_write(path, render(refresh(card)))


def _lock_path(path):
    from . import registry
    d = os.path.join(registry.home(), "locks")
    os.makedirs(d, exist_ok=True)
    h = hashlib.sha256(os.path.abspath(path).encode()).hexdigest()[:24]
    return os.path.join(d, "card-" + h)


def append(path, *entries):
    """Add ``entries`` to the card at ``path``, under a lock, atomically.

    Entries already there (same key) are skipped, so a repeated append is
    harmless. Returns the card as written.
    """
    import fcntl
    with open(_lock_path(path), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        card = load(path)
        have = {e.key for e in card.entries}
        for e in entries:
            if e.key not in have:
                card.entries.append(e)
                have.add(e.key)
        save(path, card)
        return card


def merge(a, b):
    """The union of two copies' threads (§6.3); ``a``'s front matter wins."""
    seen, out = set(), []
    for e in sorted(a.entries + b.entries, key=lambda e: e.at):
        if e.key not in seen:
            seen.add(e.key)
            out.append(e)
    return refresh(Card(meta=dict(a.meta), brief=a.brief, entries=out))


def sha(card):
    return hashlib.sha256(render(card).encode("utf-8")).hexdigest()


# --- state ------------------------------------------------------------------------

STATES = ("draft", "open", "working", "needs-input", "done", "failed", "declined",
          "cancelled", "closed")


def open_questions(entries):
    asked = {}
    for e in entries:
        if e.kind == "question":
            asked[e.arg or e.at] = e
        elif e.kind == "answer":
            asked.pop(e.arg or "", None)
    return list(asked.values())


def derive_state(entries):
    """The packet's state, read from its thread (§8.1)."""
    st, asked = "draft", set()
    for e in entries:
        k = e.kind
        if k in ("sent", "request"):
            st = "open"
        elif k in ("accepted", "handoff"):
            st = "working"
        elif k == "question":
            asked.add(e.arg or e.at)
        elif k == "answer":
            asked.discard(e.arg or "")
        elif k == "result":
            out = (e.get("Outcome") or "done").split()[0].lower()
            st = "failed" if out == "failed" else "done"
            asked.clear()
        elif k in ("declined", "cancelled", "closed"):
            st = k
        elif k == "reopened":
            st = "open"
    if asked and st in ("open", "working"):
        return "needs-input"
    return st


# --- checking ---------------------------------------------------------------------

def check(card, text=None):
    """Problems with a card, strictly: [(level, message)]."""
    out = [("error", p) for p in card.problems]
    m = card.meta
    if not m.get("title"):
        out.append(("error", "no title"))
    if m.get("packet") not in (None, FORMAT):
        out.append(("error", "packet: %r is not a format this wpk reads" % m.get("packet")))
    if m.get("name") is not None and not is_name(m["name"]):
        out.append(("error", "name %r: lower case letters, digits and dashes, 48 at most"
                    % m["name"]))
    if m.get("state") and m["state"] != card.state():
        out.append(("warning", "cached state %r; the thread says %r"
                    % (m["state"], card.state())))
    last = ""
    for e in card.entries:
        if e.at < last:
            out.append(("warning", "entry at %s is earlier than the one before it" % e.at))
        last = max(last, e.at)
        if e.kind in ("question", "answer") and not e.arg:
            out.append(("error", "%s at %s has no id" % (e.kind, e.at)))
    if text is not None and render(card) != text.replace("\r\n", "\n"):
        out.append(("info", "not in canonical form (wpk card fmt rewrites it)"))
    return out


def as_json(card):
    return json.dumps(card.to_json(), indent=2, ensure_ascii=False)


def find_up(start):
    """The card of the task folder holding ``start``: the nearest directory
    ``d`` with ``d/<basename(d)>.wp.md``. None if there is none."""
    d = os.path.abspath(start)
    while True:
        p = os.path.join(d, os.path.basename(d) + SUFFIX)
        if os.path.isfile(p):
            return p
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


__all__ = ["Card", "Entry", "parse", "render", "load", "save", "append", "merge",
           "derive_state", "check", "new_id", "stamp", "stamp_iso", "name_from"]
