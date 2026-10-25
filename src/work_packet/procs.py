"""The processes of a running step, read from ``/proc`` (Linux only).

The model runs in its own session (``model.run``), so everything it starts
has its PID as the session ID, unless it called ``setsid()``. Those are
still found by the ``WPK_WPID`` and ``WPK_STEP`` the executor puts in the
step's environment, as long as they kept it.
"""

import os
import re
import shlex
import time

PROC = "/proc"
CMD_MAX = 200
# Claude Code's Bash tool runs ``bash -c 'source <snapshot> ... && eval '<cmd>'
# < /dev/null && pwd -P >| <file>'``; the panel shows only ``<cmd>``.
WRAPPED = re.compile(r"\beval ('(?:[^']|'\\'')*')\s*< /dev/null")


def _read(path, mode="r"):
    try:
        with open(path, mode) as fp:
            return fp.read()
    except OSError:
        return None


def _boot_time():
    for line in (_read(os.path.join(PROC, "stat")) or "").splitlines():
        if line.startswith("btime "):
            return int(line.split()[1])
    return None


def _stat(pid):
    """``/proc/<pid>/stat`` as a dict, or None. The fields after the command
    name, which is in parentheses and may hold spaces, start at field 3."""
    text = _read(os.path.join(PROC, str(pid), "stat"))
    if not text or ")" not in text:
        return None
    name = text[text.index("(") + 1:text.rindex(")")]
    f = text[text.rindex(")") + 2:].split()
    try:
        return {"pid": pid, "name": name, "state": f[0], "ppid": int(f[1]),
                "sid": int(f[3]), "ticks": int(f[11]) + int(f[12]),
                "start": int(f[19]), "rss_pages": int(f[21])}
    except (IndexError, ValueError):
        return None


def _tagged(pid, wpid, step):
    env = _read(os.path.join(PROC, str(pid), "environ"), "rb")
    if not env:
        return False
    env = env.split(b"\0")
    return (("WPK_WPID=%s" % wpid).encode() in env
            and ("WPK_STEP=%s" % step).encode() in env)


def _unwrap(args):
    if len(args) == 3 and args[1] == "-c" and "shell-snapshots" in args[2]:
        m = WRAPPED.search(args[2])
        if m:
            try:
                return "$ " + shlex.split(m.group(1))[0]
            except ValueError:
                pass
    return None


def _cmdline(pid, name):
    raw = _read(os.path.join(PROC, str(pid), "cmdline"), "rb")
    args = [a.decode("utf-8", "replace") for a in (raw or b"").split(b"\0") if a]
    cmd = _unwrap(args) or (shlex.join(args) if args else "[%s]" % name)
    return cmd if len(cmd) <= CMD_MAX else cmd[:CMD_MAX - 1] + "…"


def of_step(root_pid, wpid=None, step=None, now=None):
    """The step's processes as ``{"procs": [...], "count", "rss", "cpu_s"}``,
    or None where there is no ``/proc``. With no ``root_pid`` (a step started
    before the executor wrote ``model.pid``), the tags alone find them.

    ``procs`` is a tree, parents before children, each with ``depth``,
    ``pid``, ``ppid``, ``cmd``, ``state``, ``cpu_s``, ``rss`` (bytes) and
    ``age_s``.
    """
    if not os.path.isdir(PROC):
        return None
    tick = os.sysconf("SC_CLK_TCK")
    page = os.sysconf("SC_PAGE_SIZE")
    boot = _boot_time()
    now = time.time() if now is None else now
    uid = os.getuid()
    found = {}
    for d in os.listdir(PROC):
        if not d.isdigit():
            continue
        pid = int(d)
        st = _stat(pid)
        if st is None:
            continue
        if root_pid is None or not (pid == root_pid or st["sid"] == root_pid):
            try:
                mine = os.stat(os.path.join(PROC, d)).st_uid == uid
            except OSError:
                continue
            if not (mine and wpid and step is not None and _tagged(pid, wpid, step)):
                continue
        found[pid] = st
    kids = {}
    for st in found.values():
        kids.setdefault(st["ppid"] if st["ppid"] in found else None, []).append(st["pid"])
    out = []

    def walk(pid, depth):
        st = found[pid]
        out.append({
            "pid": pid, "ppid": st["ppid"], "depth": depth, "state": st["state"],
            "cmd": _cmdline(pid, st["name"]), "cpu_s": st["ticks"] / tick,
            "rss": st["rss_pages"] * page,
            "age_s": max(now - (boot + st["start"] / tick), 0) if boot else None})
        for k in sorted(kids.get(pid, [])):
            walk(k, depth + 1)
    for top in sorted(kids.get(None, []), key=lambda p: (p != root_pid, p)):
        walk(top, 0)
    return {"procs": out, "count": len(out), "rss": sum(p["rss"] for p in out),
            "cpu_s": sum(p["cpu_s"] for p in out)}
