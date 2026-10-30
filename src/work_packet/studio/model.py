"""A packet's studio (docs/studio-plan.md S1.1): open, close, and what it shows.

The studio keeps its own files in ``<packet folder>/.studio/``:
``studio.json`` (the canvas, the layout, the session now open, and a log of
the sessions before) and ``baseline.json`` (each file's hash when the
session opened, for what it changed). Opening takes the packet
(``executor.take``); closing records the session as one step
(``record.record``) and releases it. Everything is in files, so a studio
left open over a restart can still be closed.

The folder is the root packet's packet folder, or a child's ``work/``; a
child with no ``work/`` has no studio (its run directory is wpk's).
"""

import json
import os
import time

from .. import executor, fsutil, layout
from ..packet import Packet
from . import kinds, watch

DIR = ".studio"
STATE = "studio.json"
BASELINE = "baseline.json"
LAYOUTS = ("tabs", "two-up")


class StudioError(Exception):
    """The studio cannot do that; the message says why."""


def folder(entry, wpid):
    """The folder the studio works in."""
    if wpid == entry.get("root"):
        return layout.packet_folder(entry["path"])
    w = os.path.join(layout.run_dir(entry["path"], wpid), "work")
    if os.path.isdir(w):
        return w
    raise StudioError("%s has no work/ folder to open a studio on" % wpid[:8])


def packet(entry, wpid):
    pkt = Packet(layout.run_dir(entry["path"], wpid))
    if not os.path.isfile(pkt.status_path):
        raise StudioError("no packet %s in %s" % (wpid[:8], entry["name"]))
    return pkt


def studio_dir(entry, wpid):
    return os.path.join(folder(entry, wpid), DIR)


def _load(entry, wpid):
    try:
        with open(os.path.join(studio_dir(entry, wpid), STATE), encoding="utf-8") as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        d = {}
    d.setdefault("wpid", wpid)
    d.setdefault("canvas", [])
    d.setdefault("layout", {"mode": "tabs", "open": []})
    d.setdefault("session", None)
    d.setdefault("sessions", [])
    return d


def _save(entry, wpid, d):
    sd = studio_dir(entry, wpid)
    os.makedirs(sd, exist_ok=True)
    fsutil.atomic_write(os.path.join(sd, STATE), json.dumps(d, indent=1, sort_keys=True) + "\n")


def _exclude_from_git(dirpath):
    """Add ``.studio/`` to the git excludes of the repository ``dirpath`` is the
    top of (``.git/info/exclude``: nothing tracked changes). No git: nothing."""
    info = os.path.join(dirpath, ".git", "info")
    if not os.path.isdir(os.path.join(dirpath, ".git")):
        return False
    path = os.path.join(info, "exclude")
    try:
        have = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    except OSError:
        return False
    if any(ln.strip() in ("/.studio/", ".studio/", "/.studio", ".studio")
           for ln in have.splitlines()):
        return True
    os.makedirs(info, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(("" if not have or have.endswith("\n") else "\n") +
                 "# wpk studio (docs/studio-plan.md)\n/.studio/\n")
    return True


def state(entry, wpid):
    """What the studio page shows: ``{wpid, folder, canvas, layout, session,
    sessions, taken_by, taking, open}``. ``session`` is the one open now
    (None when closed)."""
    d = _load(entry, wpid)
    meta, _ = packet(entry, wpid).load_status()
    d.update(folder=folder(entry, wpid), taken_by=meta.get("taken_by"),
             taking=executor.taking(packet(entry, wpid)),
             open=d["session"] is not None)
    return d


def open_studio(entry, wpid, user, conv=None, now=None):
    """Take the packet for ``user`` and start a session (or return to the one
    ``user`` has open). Refused while someone else has it. ``conv``: the
    conversation id of the session's agent. Returns the state."""
    pkt = packet(entry, wpid)
    root = folder(entry, wpid)
    d = _load(entry, wpid)
    s = d["session"]
    if s is not None and s["by"] != user:
        raise StudioError("%s's studio is open on it" % s["by"])
    out = executor.take(pkt, by=user)
    if out.code != 0:
        raise StudioError(out.msg)
    if s is None:
        w = watch.Watcher(root)
        sd = studio_dir(entry, wpid)
        os.makedirs(sd, exist_ok=True)
        fsutil.atomic_write(os.path.join(sd, BASELINE), json.dumps(w.hashes_now()) + "\n")
        _exclude_from_git(root)
        d["project"] = entry["name"]           # for wpk studio exec|query in the folder
        d["session"] = {"by": user, "opened": now or time.time(), "conv": conv,
                        "step": pkt.load_status()[0]["step"]}
    elif conv and not s.get("conv"):
        s["conv"] = conv
    _save(entry, wpid, d)
    return state(entry, wpid)


def set_conv(entry, wpid, conv):
    d = _load(entry, wpid)
    if d["session"] is None:
        raise StudioError("the studio is not open")
    d["session"]["conv"] = conv
    _save(entry, wpid, d)


def find(start):
    """``(project name, wpid, folder)`` of the open studio whose folder holds
    ``start`` (a path), or None: how ``wpk studio exec|query`` finds its studio."""
    d = os.path.abspath(start)
    while True:
        try:
            with open(os.path.join(d, DIR, STATE), encoding="utf-8") as fp:
                st = json.load(fp)
            if st.get("session") and st.get("project"):
                return st["project"], st["wpid"], d
        except (OSError, ValueError):
            pass
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def changed(entry, wpid):
    """(created, modified, deleted) since the session opened."""
    root = folder(entry, wpid)
    try:
        with open(os.path.join(studio_dir(entry, wpid), BASELINE), encoding="utf-8") as fp:
            before = json.load(fp)
    except (OSError, ValueError):
        before = {}
    return watch.diff(before, watch.Watcher(root).hashes_now())


def _artifact(root, rel):
    p = os.path.normpath(os.path.join(root, rel))
    if p == root or not p.startswith(root + os.sep):
        raise StudioError("%s is not in the studio's folder" % rel)
    real = os.path.realpath(p)
    if not real.startswith(os.path.realpath(root) + os.sep):
        raise StudioError("%s leads out of the studio's folder" % rel)
    rel = os.path.relpath(p, root).replace(os.sep, "/")
    if rel.split("/")[0] in (DIR, ".work-packet", ".git"):
        raise StudioError("%s is not an artifact" % rel)
    return rel


def pin(entry, wpid, path, by, now=None):
    """Put ``path`` (relative to the folder) on the canvas."""
    root = folder(entry, wpid)
    rel = _artifact(root, path)
    if not os.path.isfile(os.path.join(root, rel)):
        raise StudioError("no file %s" % rel)
    k = kinds.kind_of(rel)
    d = _load(entry, wpid)
    if not any(a["path"] == rel for a in d["canvas"]):
        d["canvas"].append({"path": rel, "kind": k.name if k else None, "by": by,
                            "t": now or time.time()})
    if rel not in d["layout"]["open"]:
        d["layout"]["open"] = (d["layout"]["open"] + [rel])[-2:] \
            if d["layout"]["mode"] == "two-up" else [rel]
    _save(entry, wpid, d)
    return d


def unpin(entry, wpid, path):
    root = folder(entry, wpid)
    rel = _artifact(root, path)
    d = _load(entry, wpid)
    d["canvas"] = [a for a in d["canvas"] if a["path"] != rel]
    d["layout"]["open"] = [p for p in d["layout"]["open"] if p != rel]
    _save(entry, wpid, d)
    return d


def set_layout(entry, wpid, mode=None, open_paths=None):
    d = _load(entry, wpid)
    if mode is not None:
        if mode not in LAYOUTS:
            raise StudioError("layout is one of %s" % ", ".join(LAYOUTS))
        d["layout"]["mode"] = mode
    if open_paths is not None:
        pinned = {a["path"] for a in d["canvas"]}
        bad = [p for p in open_paths if p not in pinned]
        if bad:
            raise StudioError("not on the canvas: %s" % ", ".join(bad))
        d["layout"]["open"] = list(open_paths)[:2 if d["layout"]["mode"] == "two-up" else 1]
    _save(entry, wpid, d)
    return d


def close_studio(entry, wpid, user, how="resume", summary=None, force=False, home=None,
                 now=None):
    """End the session: record it as a step (when it did anything), then
    release the packet (``how``: resume or hold). Closing a closed studio
    does nothing. Returns ``{recorded: step number or None, released: msg}``."""
    from . import record
    d = _load(entry, wpid)
    s = d["session"]
    if s is None:
        return {"recorded": None, "released": None, "msg": "the studio is not open"}
    if s["by"] != user and not force:
        raise StudioError("%s's studio: only they can close it" % s["by"])
    pkt = packet(entry, wpid)
    n = record.record(entry, wpid, s, summary=summary, home=home, now=now)
    out = executor.release(pkt, how=how, by=s["by"], force=True)
    d["sessions"].append(dict(s, closed=now or time.time(), step=n, how=how))
    d["session"] = None
    _save(entry, wpid, d)
    try:
        os.unlink(os.path.join(studio_dir(entry, wpid), BASELINE))
    except OSError:
        pass
    from . import content, kernel
    content.TOKENS.revoke_root(folder(entry, wpid))
    kernel.stop(folder(entry, wpid))
    return {"recorded": n, "released": out.msg, "msg": "closed" + (
        ": step %d recorded" % n if n else ": nothing to record")}
