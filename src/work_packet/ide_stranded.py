"""VS Code servers a desk has left behind (docs/ide-split-desk-plan.md).

``code serve-web`` starts a second server for a desk when a newer VS Code
client arrives, and keeps the old one, with its terminals and the agent
sessions in them, where no tab can reach it. Its own idle ending kills only
the ``sh`` wrapper: ``server-main`` is reparented to init and lives on.

This finds a desk's servers from ``/proc`` (their ``WPK_IDE_KEY``), tells
which are stranded, and ends them. Only the servers and the agents (claude,
codex) under them are signalled: a job a terminal started with ``nohup`` is
left alone. Stdlib only.
"""

import os
import re
import signal
import time

SERVER = re.compile(r"/serve-web/([0-9a-f]{40})/out/server-main\.js\Z")
AGENTS = ("claude", "codex")
STOP_S = 3.0


def _read(pid, name):
    try:
        with open("/proc/%d/%s" % (pid, name), "rb") as fp:
            return fp.read()
    except OSError:
        return None


def _argv(pid):
    raw = _read(pid, "cmdline")
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a] if raw else []


def _env(pid, name):
    raw = _read(pid, "environ")
    if not raw:
        return None
    pre = name.encode() + b"="
    for kv in raw.split(b"\0"):
        if kv.startswith(pre):
            return kv[len(pre):].decode("utf-8", "replace")
    return None


def _stat(pid):
    """``(ppid, start ticks)`` or None."""
    raw = _read(pid, "stat")
    if not raw:
        return None
    try:
        f = raw.rsplit(b")", 1)[1].split()
        return int(f[1]), int(f[19])
    except (IndexError, ValueError):
        return None


def _pids():
    try:
        return [int(n) for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return []


def _children():
    """ppid -> [pid], for every process now."""
    out = {}
    for pid in _pids():
        st = _stat(pid)
        if st is not None:
            out.setdefault(st[0], []).append(pid)
    return out


def subtree(pid, kids):
    """``pid`` and everything under it."""
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        todo.extend(kids.get(p, ()))
    return out


def is_agent(argv):
    """A claude or codex process (its program, or the script node runs)."""
    names = [os.path.basename(a) for a in argv[:2]]
    return any(n in AGENTS for n in names)


def servers(key):
    """The VS Code servers of desk ``key`` on this host, oldest first:
    ``[{"pid", "commit", "start", "launch"}]``."""
    out = []
    for pid in _pids():
        argv = _argv(pid)
        m = SERVER.search(argv[1]) if len(argv) > 1 else None
        if m is None or _env(pid, "WPK_IDE_KEY") != key:
            continue
        st = _stat(pid)
        out.append({"pid": pid, "commit": m.group(1), "start": st[1] if st else 0,
                    "launch": _env(pid, "WPK_IDE_LAUNCH")})
    return sorted(out, key=lambda s: s["start"])


def stranded(key, release=None, kids=None):
    """The servers of ``key`` that no tab reaches: all but the one serving
    ``release`` (``stable-<commit>``, the desk's pin), else all but the newest.
    Each gets ``agents``: ``[{"pid", "argv"}]`` of the sessions under it."""
    srv = servers(key)
    if len(srv) < 2:
        return []
    commit = (release or "").rsplit("-", 1)[-1]
    keep = next((s for s in srv if s["commit"] == commit), srv[-1])
    kids = _children() if kids is None else kids
    out = []
    for s in srv:
        if s is keep:
            continue
        s["agents"] = [{"pid": p, "argv": " ".join(_argv(p))[:120]}
                       for p in subtree(s["pid"], kids) if is_agent(_argv(p))]
        out.append(s)
    return out


def targets(server_pids, kids=None):
    """What ending these servers signals: each server and the agents under it."""
    kids = _children() if kids is None else kids
    out = []
    for sp in server_pids:
        out.append(sp)
        out.extend(p for p in subtree(sp, kids)[1:] if is_agent(_argv(p)))
    return out


def end(pids, wait=STOP_S):
    """SIGTERM ``pids``, then SIGKILL what is left after ``wait``. Returns how
    many are gone."""
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    until = time.monotonic() + wait
    while time.monotonic() < until and any(_alive(p) for p in pids):
        time.sleep(0.1)
    for p in pids:
        if _alive(p):
            try:
                os.kill(p, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    return sum(1 for p in pids if not _alive(p))


def _alive(pid):
    raw = _read(pid, "stat")
    return bool(raw) and raw.rsplit(b")", 1)[-1].split()[0] != b"Z"


def end_server(key, pid):
    """End stranded server ``pid`` of desk ``key`` and the agents under it.
    False when ``pid`` is not one of that desk's servers."""
    if not any(s["pid"] == pid for s in servers(key)):
        return False
    end(targets([pid]))
    return True


def desk_keys(home, wpid):
    """The desks an Open in VS Code of packet ``wpid`` used."""
    from . import ide_launch
    root = os.path.join(home, "ide", "servers")
    try:
        keys = sorted(os.listdir(root))
    except OSError:
        return []
    return [k for k in keys if any(o.get("wpid") == wpid for o in ide_launch.opens(home, k))]


def for_packet(home, wpid):
    """The stranded servers of the desks packet ``wpid`` opened, each with its
    ``key``, for the packet's page."""
    from . import ide_launch
    out = []
    for key in desk_keys(home, wpid):
        rel = (ide_launch.current(home, key) or {}).get("release")
        for s in stranded(key, rel):
            out.append(dict(s, key=key))
    return out
