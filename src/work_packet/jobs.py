"""Jobs: a long command you run for a packet, as a worker on it (docs/collaboration.md
W7; docs/work-sessions.md stage 2's record; plan C7a).

``wpk run -- make sim`` in a packet folder runs the command as it would run
anyway (its output on your terminal) and records it as a **job** of the
project: while it runs, the ball is *external* ("waiting on make sim, 1h12m")
and the card waits; when it ends, a failure needs you and a success waits for
your review. The board's **Run a command** starts the same thing, detached.

A job is ``<project>/jobs/<id>/``: ``job.json`` (``id, cmd, cwd, host, pid,
by, start, end, exit``; times in epoch seconds), ``log`` (the output) and
``seen`` (written when you open its page). The root packet's journal gets
``job-start`` and ``job-end``. A job with no end whose process is gone on
this host is **lost**: the run was killed, or the host restarted.
"""

import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
import uuid

from . import fsutil, layout

KEEP = 50                   # finished jobs kept per project
TAIL = 64 * 1024            # the log tail a page shows


class JobError(Exception):
    pass


def _dir(proj):
    return os.path.join(proj, "jobs")


def _ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def label(cmd, n=40):
    """A job's command, short, for a card."""
    s = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
    return s if len(s) <= n else s[:n - 1] + "…"


def _root(proj):
    from .hookcmd import _root as root
    return root(proj)


def _journal(proj, rec):
    from .hookcmd import _journal as append
    try:
        append(proj, _root(proj), rec)
    except OSError:
        pass


def _write(proj, d):
    p = os.path.join(_dir(proj), d["id"], "job.json")
    fsutil.atomic_write(p, json.dumps(d, sort_keys=True) + "\n")


def start(proj, cmd, cwd, by=None, now=None, pid=None):
    """Record a job that starts now. Returns its record."""
    from .packet import user
    now = time.time() if now is None else now
    jid = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now)) + "-" + uuid.uuid4().hex[:6]
    d = {"id": jid, "cmd": list(cmd), "cwd": os.path.abspath(cwd),
         "host": socket.gethostname(), "pid": pid or os.getpid(), "by": by or user(),
         "start": now, "end": None, "exit": None}
    os.makedirs(os.path.join(_dir(proj), jid), exist_ok=True)
    _write(proj, d)
    _journal(proj, {"type": "job-start", "t": _ts(now), "job": jid, "cmd": label(cmd, 200),
                    "by": d["by"]})
    _prune(proj)
    return d


def end(proj, d, code, now=None):
    """Record ``d``'s end with exit status ``code``."""
    now = time.time() if now is None else now
    d = dict(d, end=now, exit=code)
    _write(proj, d)
    _journal(proj, {"type": "job-end", "t": _ts(now), "job": d["id"], "exit": code,
                    "cmd": label(d["cmd"], 200), "secs": int(now - d["start"])})
    return d


def log_path(proj, jid):
    return os.path.join(_dir(proj), jid, "log")


def _alive(d):
    if d.get("host") != socket.gethostname():
        return True                     # another host's: trust it
    try:
        os.kill(int(d["pid"]), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, KeyError, TypeError, ValueError):
        return True
    from . import procs
    return not procs.zombie(int(d["pid"]))


def get(proj, jid):
    """One job's record, with ``state``: running, ok, failed or lost; and
    ``seen``. None if there is no such job."""
    if not jid or "/" in jid or jid.startswith("."):
        return None
    try:
        with open(os.path.join(_dir(proj), jid, "job.json")) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or "id" not in d:
        return None
    if d.get("end") is None:
        d["state"] = "running" if _alive(d) else "lost"
    else:
        d["state"] = "ok" if d.get("exit") == 0 else "failed"
    d["seen"] = os.path.exists(os.path.join(_dir(proj), jid, "seen"))
    return d


def all_jobs(proj):
    """Every job, newest first."""
    try:
        ids = sorted(os.listdir(_dir(proj)), reverse=True)
    except OSError:
        return []
    return [d for d in (get(proj, i) for i in ids) if d]


def live(proj):
    return [d for d in all_jobs(proj) if d["state"] == "running"]


def unseen(proj):
    """Ended (or lost) jobs you have not opened, newest first."""
    return [d for d in all_jobs(proj) if d["state"] != "running" and not d["seen"]]


def mark_seen(proj, jid):
    d = get(proj, jid)
    if d and d["state"] != "running" and not d["seen"]:
        fsutil.atomic_write(os.path.join(_dir(proj), jid, "seen"), _ts(time.time()) + "\n")


def _prune(proj):
    done = [d for d in all_jobs(proj) if d["state"] != "running"]
    import shutil
    for d in done[KEEP:]:
        shutil.rmtree(os.path.join(_dir(proj), d["id"]), ignore_errors=True)


def tail(proj, jid, n=TAIL):
    """The last ``n`` bytes of a job's log, as text."""
    try:
        with open(log_path(proj, jid), "rb") as fp:
            fp.seek(0, 2)
            size = fp.tell()
            fp.seek(max(0, size - n))
            data = fp.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    return ("…\n" + text.split("\n", 1)[-1]) if size > n else text


def items(proj, now=None):
    """Attention items (the shape of ``attention.session_items``) for jobs that
    ended and you have not seen: a failure or a lost job, or a finished one."""
    out = []
    for d in unseen(proj):
        bad = d["state"] != "ok"
        what = label(d["cmd"])
        text = ("%s was lost (its process is gone)" % what if d["state"] == "lost" else
                "%s failed (exit %s)" % (what, d["exit"]) if bad else "%s finished" % what)
        out.append({"type": "job", "source": d["id"], "since": d.get("end") or d["start"],
                    "text": text, "failed": bad, "job": d["id"]})
    return out


# --- running one ------------------------------------------------------------------------

def run(cmd, cwd=None, out=None, proj=None):
    """``wpk run``: run ``cmd`` (a list) in ``cwd``, its output teed to ``out``
    (your terminal) and, in a packet folder, to the job's log. Returns the exit
    status (128 + the signal's number if a signal ended it)."""
    from . import presence
    cwd = os.path.abspath(cwd or os.getcwd())
    proj = proj or presence.find_project(cwd)
    out = out if out is not None else sys.stdout.buffer
    if not cmd:
        raise JobError("no command: wpk run -- <command>")
    if not proj:
        return subprocess.call(cmd, cwd=cwd)
    d = start(proj, cmd, cwd)
    code = 127
    try:
        with open(log_path(proj, d["id"]), "ab") as log:
            env = dict(os.environ, WPK_JOB=d["id"], WPK_PROJECT_DIR=proj)
            try:
                p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
            except OSError as e:
                msg = ("wpk run: %s: %s\n" % (cmd[0], e.strerror)).encode()
                log.write(msg)
                out.write(msg)
                return code
            try:
                for chunk in iter(lambda: p.stdout.read1(65536), b""):
                    log.write(chunk)
                    log.flush()
                    try:
                        out.write(chunk)
                        out.flush()
                    except (OSError, ValueError):
                        pass
            except KeyboardInterrupt:
                p.send_signal(signal.SIGINT)
            code = p.wait()
            if code < 0:
                code = 128 - code
    finally:
        end(proj, d, code)
    return code


def run_detached(proj, text, cwd):
    """The board's **Run a command**: ``wpk run -- sh -c text`` in ``cwd``, in
    the background, with its own session. Returns the process id."""
    if not text.strip():
        raise JobError("no command")
    p = subprocess.Popen([sys.executable, "-m", "work_packet", "run", "--", "sh", "-c", text],
                         cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True,
                         env=dict(os.environ, WPK_PROJECT_DIR=proj))
    return p.pid


def folder(proj):
    """Where a job from the board runs: the packet folder, or a legacy project's
    single ``work/`` repository if it has exactly one, else the project."""
    if layout.is_packet_layout(proj):
        return layout.packet_folder(proj)
    w = os.path.join(proj, "work")
    try:
        names = [n for n in os.listdir(w) if not n.startswith(".")]
    except OSError:
        names = []
    return os.path.join(w, names[0]) if len(names) == 1 else proj


def quote(cmd):
    return " ".join(shlex.quote(c) for c in cmd)
