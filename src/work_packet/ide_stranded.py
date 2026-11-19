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

# serve-web's cache, or wpk's own releases (ide_releases): .../<commit>/out/server-main.js
SERVER = re.compile(r"/(?:serve-web|releases/[a-z0-9-]+)/([0-9a-f]{40})/out/server-main\.js\Z")
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


def _opt(argv, name):
    """The value of ``name`` in ``argv`` (``--x v`` or ``--x=v``), or None."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a[len(name) + 1:]
    return None


def servers(key):
    """The VS Code servers of desk ``key`` on this host, oldest first:
    ``[{"pid", "commit", "start", "launch", "socket"}]``."""
    out = []
    for pid in _pids():
        argv = _argv(pid)
        m = SERVER.search(argv[1]) if len(argv) > 1 else None
        if m is None or _env(pid, "WPK_IDE_KEY") != key:
            continue
        st = _stat(pid)
        out.append({"pid": pid, "commit": m.group(1), "start": st[1] if st else 0,
                    "launch": _env(pid, "WPK_IDE_LAUNCH"), "socket": _opt(argv, "--socket-path")})
    return sorted(out, key=lambda s: s["start"])


def all_servers():
    """Every desk's VS Code server on this host: ``[{"pid", "commit", "key"}]``."""
    out = []
    for pid in _pids():
        argv = _argv(pid)
        m = SERVER.search(argv[1]) if len(argv) > 1 else None
        key = _env(pid, "WPK_IDE_KEY") if m else None
        if key:
            out.append({"pid": pid, "commit": m.group(1), "key": key})
    return out


def stranded(key, release=None, kids=None, keep_pid=None):
    """The servers of ``key`` that no tab reaches: all but ``keep_pid`` (the
    one the board proxies to), else the one serving ``release``
    (``stable-<commit>``), else all but the newest. Each gets ``agents``:
    ``[{"pid", "argv"}]`` of the sessions under it."""
    srv = servers(key)
    if len(srv) < 2:
        return []
    commit = (release or "").rsplit("-", 1)[-1]
    keep = next((s for s in srv if s["pid"] == keep_pid), None) or \
        next((s for s in srv if s["commit"] == commit), srv[-1])
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


def started_at(pid):
    """When ``pid`` started (epoch seconds), or None."""
    st = _stat(pid)
    raw = _read_text("/proc/stat")
    if st is None or not raw:
        return None
    for ln in raw.splitlines():
        if ln.startswith("btime "):
            return int(ln.split()[1]) + st[1] / os.sysconf("SC_CLK_TCK")
    return None


def _read_text(path):
    try:
        with open(path) as fp:
            return fp.read()
    except OSError:
        return None


def inside(pid, kids=None):
    """What runs in server ``pid``: ``{"agents": [{"pid", "argv", "since"}],
    "terminals": n}`` (its terminals' shells)."""
    kids = _children() if kids is None else kids
    agents, terms = [], 0
    for p in subtree(pid, kids)[1:]:
        argv = _argv(p)
        if is_agent(argv):
            agents.append({"pid": p, "argv": " ".join(argv)[:120], "since": started_at(p)})
        elif any("shellIntegration" in a for a in argv[1:3]):
            terms += 1
    return {"agents": agents, "terminals": terms}


def agents_under(pid, kids=None):
    """How many agents (claude, codex) run under ``pid``."""
    kids = _children() if kids is None else kids
    return sum(1 for p in subtree(pid, kids)[1:] if is_agent(_argv(p)))


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
        cur = ide_launch.current(home, key) or {}
        for s in stranded(key, cur.get("release"), keep_pid=cur.get("server_pid")):
            out.append(dict(s, key=key))
    return out
