"""Claude Code hooks in a packet folder (docs/collaboration.md §4.3, §10).

The board writes them into the folder's ``.claude/settings.local.json``, so every
Claude session there, in web or desktop VS Code, a terminal or a job, reports
its turns to the board (``hookcmd``). The file is merged, never replaced: wpk's
entries are the ones whose command runs ``work_packet.hookcmd``, and only those
are added, replaced or removed. With them goes wpk's ``statusLine``
(``statusline``), unless you have a status line of your own. In a git clone the
file is also listed in ``info/exclude``, as the card is. ``[ide] hooks = false``
turns it off.
"""

import json
import os
import shlex
import sys

from . import fsutil

REL = os.path.join(".claude", "settings.local.json")
MARK = "work_packet.hookcmd"
# Event -> matcher ("" for events that take none).
EVENTS = {"SessionStart": "", "UserPromptSubmit": "", "PermissionRequest": "*",
          "PostToolUse": "*", "Notification": "*", "Stop": "", "PreCompact": "",
          "SessionEnd": ""}
TIMEOUT_S = 10
LINE_MARK = "work_packet.statusline"


def statusline_command(python=None):
    return "%s -m %s" % (shlex.quote(python or sys.executable), LINE_MARK)


def _own_line(d):
    sl = d.get("statusLine")
    return isinstance(sl, dict) and LINE_MARK in str(sl.get("command", ""))


def _theirs(folder):
    """A status line you set yourself, which ours must not hide: in the folder's
    shared ``.claude/settings.json`` or your ``~/.claude/settings.json``."""
    for p in (os.path.join(folder, ".claude", "settings.json"),
              os.path.join(os.path.expanduser("~"), ".claude", "settings.json")):
        try:
            if _load(p).get("statusLine"):
                return True
        except HooksError:
            return True                 # can't tell: leave yours alone
    return False


class HooksError(Exception):
    pass


def command(event, python=None):
    return "%s -m %s %s" % (shlex.quote(python or sys.executable), MARK, event)


def _ours(group):
    return any(MARK in str(h.get("command", "")) for h in group.get("hooks") or ()
               if isinstance(h, dict))


def _load(p):
    """The settings at ``p`` ({} if none); HooksError if it is not a JSON object."""
    try:
        with open(p, encoding="utf-8") as fp:
            text = fp.read()
    except FileNotFoundError:
        return {}
    try:
        d = json.loads(text) if text.strip() else {}
    except ValueError as e:
        raise HooksError("%s is not valid JSON (%s): left as it is" % (p, e)) from None
    if not isinstance(d, dict):
        raise HooksError("%s is not a JSON object: left as it is" % p)
    return d


def merged(d, python=None, on=True, line=False):
    """``d`` (settings) with wpk's hook entries replaced (``on``) or removed.
    ``line``: also set wpk's ``statusLine`` (``wpk statusline``) if the file has
    none of its own; off, ours is removed (docs/collaboration.md §7.10)."""
    d = dict(d)
    if on and line and (not d.get("statusLine") or _own_line(d)):
        d["statusLine"] = {"type": "command", "command": statusline_command(python)}
    elif _own_line(d) and not (on and line):
        d.pop("statusLine")
    hooks = dict(d.get("hooks") or {})
    for ev in sorted(set(hooks) | set(EVENTS)):
        groups = [g for g in hooks.get(ev) or () if not (isinstance(g, dict) and _ours(g))]
        if on and ev in EVENTS:
            g = {"hooks": [{"type": "command", "command": command(ev, python),
                            "timeout": TIMEOUT_S}]}
            if EVENTS[ev]:
                g = {"matcher": EVENTS[ev], **g}
            groups.append(g)
        if groups:
            hooks[ev] = groups
        else:
            hooks.pop(ev, None)
    if hooks:
        d["hooks"] = hooks
    else:
        d.pop("hooks", None)
    return d


def install(folder, python=None):
    """Write wpk's hooks into ``folder``. Returns "installed", "unchanged", or raises
    HooksError (a settings file that is not JSON is never overwritten)."""
    return _write(folder, python, True)


def uninstall(folder):
    """Take wpk's hooks out of ``folder``; the rest of the file stays."""
    if not os.path.exists(os.path.join(folder, REL)):
        return "unchanged"
    return _write(folder, None, False)


def _write(folder, python, on):
    p = os.path.join(folder, REL)
    old = _load(p)
    new = merged(old, python, on, line=on and not _theirs(folder))
    if new == old:
        return "unchanged"
    if not on and not new and os.path.exists(p):
        os.unlink(p)                    # it held only ours
        return "removed"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fsutil.atomic_write(p, json.dumps(new, indent=2) + "\n")
    from . import workspace
    if workspace.is_git(folder):
        try:
            workspace.exclude(folder, [REL.replace(os.sep, "/")])
        except Exception:               # noqa: BLE001: the exclude is a nicety
            pass
    return "installed" if on else "removed"


def status(folder, python=None):
    """For ``wpk doctor`` and the board: "installed", "missing", "modified" (ours,
    but not as we write them now) or "unreadable"."""
    try:
        d = _load(os.path.join(folder, REL))
    except HooksError:
        return "unreadable"
    mine = {ev: [g for g in (d.get("hooks") or {}).get(ev) or ()
                 if isinstance(g, dict) and _ours(g)] for ev in EVENTS}
    if not any(mine.values()):
        return "missing"
    want = merged({}, python)["hooks"]
    return "installed" if all(mine[ev] == want[ev] for ev in EVENTS) else "modified"


def switch_path(home):
    return os.path.join(home, "ide", "hooks.json")


def enabled(cfg, home=None):
    """On unless turned off: the board's switch (``ide/hooks.json``) when it has
    been used, else ``[ide] hooks`` (default on)."""
    if home:
        try:
            with open(switch_path(home)) as fp:
                d = json.load(fp)
            if isinstance(d, dict) and isinstance(d.get("on"), bool):
                return d["on"]
        except (OSError, ValueError):
            pass
    return cfg.get("hooks", True) is not False


def set_enabled(home, on, by=None):
    """The board's switch; ``config.toml`` is the person's file and is not rewritten."""
    import time
    os.makedirs(os.path.dirname(switch_path(home)), mode=0o700, exist_ok=True)
    fsutil.atomic_write(switch_path(home), json.dumps(
        {"on": bool(on), "by": by, "t": time.time()}) + "\n")


def ensure(folders, cfg, python=None, home=None):
    """Install into each folder when hooks are on (``enabled``), else remove ours.
    Returns {folder: result or error text}; never raises."""
    on = enabled(cfg, home)
    out = {}
    for f in folders:
        if not os.path.isdir(f):
            continue
        try:
            out[f] = install(f, python) if on else uninstall(f)
        except (HooksError, OSError) as e:
            out[f] = str(e)
    return out


def packet_folder(entry):
    """The folder of a packet-layout project, where Claude runs; else None."""
    from . import layout
    if layout.is_packet_layout(entry["path"]):
        return layout.packet_folder(entry["path"])
    return None


def apply_all(home, cfg):
    """After the switch moved: install into (or take out of) every registered
    packet folder. Returns {project: result}."""
    from . import registry
    out = {}
    for e in registry.entries(home):
        f = packet_folder(e)
        if f:
            out[e["name"]] = ensure([f], cfg, home=home).get(f, "missing folder")
    return out
