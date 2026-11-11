"""The board's Settings page (plan C6, §2a): the ``config.toml`` keys a person
changes day to day, set from the dash.

``config.toml`` is yours, with your comments, so it is edited line by line, never
rewritten: a key's line is replaced, a missing key goes under its table, a
missing table at the end. A key set back to its default is removed. The result
is read back and must parse to exactly what was asked, and pass the config
checks; otherwise nothing is written ("edit config.toml by hand").
"""

import os
import re

import tomli_w

from . import fsutil, registry, schema
from .tomlio import tomllib

# (table, key, type, default, label). The Settings page shows these, in order.
KEYS = [
    ("packets", "root", str, "", "New packets go in (directory; <root>/<board>/<name>)"),
    ("packets", "layout", str, "board", "Packet folders: board (<root>/<board>/<name>) or "
     "flat (<root>/<name>)"),
    ("skills", "install", bool, True, "Install the wpk skills for Claude and Codex when a "
     "packet is made"),
    ("ide", "desktop", bool, False, "Offer \"Open in VS Code\" on the desktop (vscode:// links)"),
    ("ide", "presence_ttl", int, 600, "Presence lasts (seconds without a beat)"),
    ("ide", "idle_escalate", int, 900, "\"Your turn\" needs you after (seconds)"),
    ("focus", "time", str, "08:30", "Daily brief at (HH:MM)"),
    ("focus", "weekends", bool, False, "Brief on weekends too"),
    ("focus", "off", bool, False, "No daily brief"),
    ("focus", "review", bool, True, "Write the weekly review"),
    ("focus", "review_day", str, "fri", "Weekly review on (mon ... sun)"),
    ("focus", "review_time", str, "16:00", "Weekly review after (HH:MM)"),
    ("calendar", "ics", str, "", "Calendar feed (ICS URL or file): meetings in the brief, "
     "no pushes during them"),
    ("plan", "focus_wip", int, 3, "At most this many in \"now\""),
    ("plan", "review_wip", int, 5, "Warn on a hand-off with this many reviews waiting"),
    ("notify", "ntfy_url", str, "", "ntfy topic URL (pushes go here)"),
    ("notify", "ntfy_token", str, "", "ntfy access token (if the topic needs one)"),
    ("notify", "link", str, "", "Board URL for links in pushes"),
    ("notify", "question_after_s", int, 300, "Push a question after (seconds)"),
    ("notify", "max_per_hour", int, 6, "At most this many pushes an hour"),
    ("notify", "digest", str, "off", "Digest of the rest (off, hourly, daily)"),
    ("notify", "digest_at", str, "17:30", "Daily digest at (HH:MM)"),
    ("notify", "brief", bool, False, "Push the daily brief"),
]
SECRET = {("notify", "ntfy_token")}


class SettingsError(Exception):
    pass


def path(h=None):
    return os.path.join(h or registry.home(), "config.toml")


def current(h=None):
    """``{(table, key): value}`` in force (site config included), defaults filled."""
    try:
        cfg = registry.load_config_file(h)
    except registry.ConfigError:
        cfg = {}
    return {(t, k): (cfg.get(t) or {}).get(k, d) for t, k, _, d, _ in KEYS}


def parse(form):
    """The form's ``table.key`` fields as ``{(table, key): value}``, typed. A
    checkbox that is absent is false. A secret left empty is kept as it is."""
    out = {}
    for t, k, typ, d, label in KEYS:
        name = "%s.%s" % (t, k)
        v = form.get(name)
        if typ is bool:
            out[(t, k)] = v in ("1", "on", "true", True)
            continue
        if v is None or ((t, k) in SECRET and v == ""):
            continue
        v = v.strip()
        if typ is int:
            try:
                v = int(v)
            except ValueError:
                raise SettingsError("%s: a whole number, please" % label) from None
        out[(t, k)] = v
    return out


def _line(k, v):
    return tomli_w.dumps({k: v}).strip()


_HEAD = re.compile(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$")


def edit(text, changes):
    """``text`` with each ``(table, key): value`` set (None: removed)."""
    lines = text.splitlines()
    for (t, k), v in changes.items():
        start = end = None
        for i, ln in enumerate(lines):
            m = _HEAD.match(ln)
            if m:
                if start is not None:
                    end = i
                    break
                if m.group(1).strip() == t:
                    start = i
        if start is not None and end is None:
            end = len(lines)
        key = re.compile(r"^\s*%s\s*=" % re.escape(k))
        at = next((i for i in range(start + 1, end) if key.match(lines[i])), None) \
            if start is not None else None
        if v is None:
            if at is not None:
                del lines[at]
            continue
        if at is not None:
            lines[at] = _line(k, v)
        elif start is not None:
            last = max([i for i in range(start + 1, end) if lines[i].strip()
                        and not lines[i].lstrip().startswith("#")] or [start])
            lines.insert(last + 1, _line(k, v))
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ([""] if lines else []) + ["[%s]" % t, _line(k, v)]
    return "\n".join(lines) + "\n"


def save(changes, h=None):
    """Write ``changes`` (``{(table, key): value}``) to ``config.toml``: a default
    removes the key. Returns the keys that changed."""
    p = path(h)
    try:
        with open(p) as fp:
            text = fp.read()
    except FileNotFoundError:
        text = ""
    try:
        mine = tomllib.loads(text)
    except ValueError as e:
        raise SettingsError("config.toml does not parse (%s): edit it by hand" % e) from None
    defaults = {(t, k): d for t, k, _, d, _ in KEYS}
    todo = {}
    for tk, v in changes.items():
        have = (mine.get(tk[0]) or {}).get(tk[1])
        want = None if v == defaults[tk] else v
        if have != want:
            todo[tk] = want
    if not todo:
        return []
    new = edit(text, todo)
    try:
        got = tomllib.loads(new)
    except ValueError:
        raise SettingsError("could not edit config.toml safely: edit it by hand") from None
    for (t, k), v in todo.items():
        if (got.get(t) or {}).get(k) != v:
            raise SettingsError("could not set %s.%s in config.toml safely: edit it by hand"
                                % (t, k))
    probs = [x for x in schema.validate_config(got) if x.level == "error"]
    if probs:
        label = {"%s.%s" % (t, k): lb for t, k, _, _, lb in KEYS}.get(probs[0].field,
                                                                     probs[0].field)
        raise SettingsError("%s: %s" % (label, probs[0].msg))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, new)
    return sorted("%s.%s" % tk for tk in todo)
