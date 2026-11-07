"""``wpk statusline``: Claude Code's status line in a packet folder
(docs/collaboration.md §7.10, plan C7b).

Claude Code runs the ``statusLine`` command after each turn with its status
JSON on stdin. This prints one line about the packet the session works in, from
local files only (no board, no network): its name, whose move it is, and the
jobs that ended and wait for you. It never fails: anything wrong prints a plain
``wpk``. The board's hooks switch sets it (``sessionhooks``) in a packet
folder that has no status line of its own.
"""

import json
import os
import time

WHO = {"agent": "runner", "scheduled": "scheduled", "external": "job"}


def _project(ev):
    from . import presence
    proj = os.environ.get("WPK_PROJECT_DIR")
    if proj and os.path.isfile(os.path.join(proj, "project.toml")):
        return proj
    cwd = (ev.get("workspace") or {}).get("current_dir") or ev.get("cwd") or os.getcwd()
    return presence.find_project(cwd)


def describe(proj, now=None):
    """The line for project directory ``proj``."""
    from . import jobs, layout, lease, presence, views
    from .hookcmd import _root
    from .packet import Packet
    from .tomlio import load_toml
    now = time.time() if now is None else now
    name = load_toml(os.path.join(proj, "project.toml")).get("name") or "?"
    root = _root(proj)
    pkt = Packet(layout.run_dir(proj, root))
    meta, _ = pkt.load_status()
    lz = lease.read(pkt.lease_path)
    running = lz if lz and not lease.is_stale(lz) else None
    here = presence.live(proj, now)
    live = jobs.live(proj)
    b = views.ball(meta, running, here, live, now)
    parts = ["wpk %s" % name]
    if b["kind"] in views.NEEDS_YOU:
        parts.append("needs you: %s" % b["text"])
    elif b["kind"] == "working" and b["who"] == "you":
        parts.append("yours")
    elif b["who"] in ("agent", "scheduled", "external"):
        parts.append("%s: %s" % (WHO[b["who"]], b["text"]))
    else:
        parts.append(b["text"])
    ended = jobs.items(proj)
    if ended:
        bad = sum(1 for it in ended if it["failed"])
        parts.append("%d job%s ended%s" % (len(ended), "s" if len(ended) != 1 else "",
                                            " (%d failed)" % bad if bad else ""))
    return " · ".join(parts)


def line(stdin=None):
    try:
        raw = stdin.read() if stdin is not None else ""
        ev = json.loads(raw) if raw.strip() else {}
        if not isinstance(ev, dict):
            ev = {}
        proj = _project(ev)
        return describe(proj) if proj else "wpk"
    except Exception:                   # noqa: BLE001: a status line never fails
        return "wpk"


if __name__ == "__main__":
    import sys
    print(line(sys.stdin))
