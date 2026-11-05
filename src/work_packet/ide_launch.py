"""Who launched a web VS Code server, and where it ran (docs/vscode-monitor-plan.md §2.1).

A *launch* is one lifetime of a target's server: one local ``serve-web``
process or one IDE job. Each one has an id, ``L-<12 hex>``, that its process
gets as ``WPK_IDE_LAUNCH``. Every process the editor starts inherits it,
including the extension host, the extensions' ``claude`` and ``codex``, and
the terminals, so a harness session can be traced back to its launch.

Everything here is in the server's directory, ``ide/servers/<key>/``:

``launch``
    The current launch, as JSON.
``launches.jsonl``
    Its history. Each line is ``{"launch_id", "t", ...fields}``; the first
    line names the launch, and later lines add ``job_ref``, ``host`` or
    ``ended``. ``history`` folds them. A job's ID and host outlive its
    ``JobRecord``.
``opens.jsonl``
    One line per Open in VS Code: ``{"t", "project", "wpid", "by"}``. Several
    packets can open one target, and an open is what ties a launch to a
    packet.

Stdlib only: ``sched/ide_job.py`` imports it on the exec host.
"""

import json
import os
import secrets
import time

KEEP_LINES = 2000           # read at most this many lines from the end of a history file
ENV_LAUNCH = "WPK_IDE_LAUNCH"
ENV_KEY = "WPK_IDE_KEY"


def server_dir(home, key):
    return os.path.join(home, "ide", "servers", key)


def new_id():
    return "L-" + secrets.token_hex(6)


def env(launch_id, key):
    """What the server's process gets. Packet identity is not here: one
    server can serve several packets, and the opens decide later."""
    return {ENV_LAUNCH: launch_id, ENV_KEY: key}


def _append(path, rec):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(rec, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _write(path, rec):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fp:
        json.dump(rec, fp, sort_keys=True)
        fp.write("\n")
    os.replace(tmp, path)


def _lines(path):
    try:
        with open(path, "rb") as fp:
            fp.seek(0, os.SEEK_END)
            size = fp.tell()
            fp.seek(max(0, size - KEEP_LINES * 256))
            data = fp.read()
    except OSError:
        return []
    out = []
    for raw in data.splitlines()[-KEEP_LINES:]:
        try:
            d = json.loads(raw)
        except ValueError:
            continue                # the cut-off first line, or a torn write
        if isinstance(d, dict):
            out.append(d)
    return out


def start(home, key, target, backend, now=None, **fields):
    """A new launch for ``key``: it becomes the current one. Returns its id."""
    lid = new_id()
    rec = dict(fields, launch_id=lid, key=key, target=target, backend=backend,
               started=time.time() if now is None else now)
    d = server_dir(home, key)
    _write(os.path.join(d, "launch"), rec)
    _append(os.path.join(d, "launches.jsonl"), dict(rec, t=rec["started"]))
    return lid


def update(home, key, launch_id, now=None, **fields):
    """Add ``fields`` (``job_ref``, ``host``, ``pid``, ``ended``) to a launch.
    The current-launch file changes only when it is still that launch."""
    if not launch_id:
        return
    d = server_dir(home, key)
    t = time.time() if now is None else now
    _append(os.path.join(d, "launches.jsonl"), dict(fields, launch_id=launch_id, t=t))
    cur = current(home, key)
    if cur is not None and cur.get("launch_id") == launch_id:
        cur.update(fields)
        _write(os.path.join(d, "launch"), cur)


def current(home, key):
    try:
        with open(os.path.join(server_dir(home, key), "launch")) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) and d.get("launch_id") else None
    except (OSError, ValueError):
        return None


def history(home, key):
    """Every launch of ``key`` we still have, oldest first, its lines folded."""
    by = {}
    for d in _lines(os.path.join(server_dir(home, key), "launches.jsonl")):
        lid = d.get("launch_id")
        if not lid:
            continue
        rec = by.setdefault(lid, {})
        rec.update({k: v for k, v in d.items() if k != "t"})
    return sorted(by.values(), key=lambda r: r.get("started") or 0)


def find(home, launch_id):
    """The launch with this id, in any server, or None."""
    root = os.path.join(home, "ide", "servers")
    try:
        keys = os.listdir(root)
    except OSError:
        return None
    for key in keys:
        cur = current(home, key)
        if cur is not None and cur.get("launch_id") == launch_id:
            return cur
    for key in keys:
        for rec in history(home, key):
            if rec.get("launch_id") == launch_id:
                return rec
    return None


def record_open(home, key, project=None, wpid=None, by=None, now=None):
    _append(os.path.join(server_dir(home, key), "opens.jsonl"),
            {"t": time.time() if now is None else now, "project": project or None,
             "wpid": wpid or None, "by": by or None})


def opens(home, key):
    return _lines(os.path.join(server_dir(home, key), "opens.jsonl"))


def packet_of(home, key, since=None, until=None):
    """``(project, wpid)`` when the opens of ``key`` in ``[since, until]`` name
    exactly one; ``(project, None)`` when they agree only on the project; else
    ``(None, None)``. Ambiguity leaves a field empty and never guesses."""
    seen = set()
    for o in opens(home, key):
        t = o.get("t") or 0
        if since is not None and t < since or until is not None and t > until:
            continue
        seen.add((o.get("project"), o.get("wpid")))
    if len(seen) == 1:
        return next(iter(seen))
    projects = {p for p, _ in seen}
    if len(projects) == 1:
        return next(iter(projects)), None
    return None, None
