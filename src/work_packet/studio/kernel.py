"""The studio's kernel, from wpk's side (docs/studio-plan.md S2.1).

``call(folder, op, ...)`` sends one request to the kernel of the studio in
``folder``, starting it first if it is not up (``ensure``). The kernel
(``kernel_main.py``) runs in the folder, as the user, in the packet's own
Python when that has DuckDB (an IVPM ``packages/python``), else in wpk's.
Its socket is under the temp dir (``/tmp/wpk-<uid>/``, mode 0700: a unix
socket's path is short) and ``.studio/kernel.json`` says which process it
is. A call that runs over its time limit kills the kernel (the next call
starts a new one, with a fresh namespace) and says so.

The board and ``wpk studio exec|query|datasets`` both use it; whichever
comes first starts the kernel. It exits by itself when idle
(``[studio] kernel_idle_minutes``), and ``stop`` ends it when the studio
closes.
"""

import fcntl
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time

from .. import fsutil

INFO = "kernel.json"
LOG = "kernel.log"
START_S = 15.0
_PY = {}                    # python path -> has duckdb (cached per process)
PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class KernelError(Exception):
    """The kernel could not answer; the message says why."""


def sock_path(folder):
    d = os.path.join(tempfile.gettempdir(), "wpk-%d" % os.getuid())
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    h = hashlib.sha1(os.path.abspath(folder).encode()).hexdigest()[:16]
    return os.path.join(d, "k-%s.sock" % h)


def _has_duckdb(py):
    if py not in _PY:
        try:
            r = subprocess.run([py, "-c", "import duckdb"], capture_output=True, timeout=30)
            _PY[py] = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _PY[py] = False
    return _PY[py]


def python_for(folder):
    """The Python the kernel runs in: the packet's IVPM venv when it has
    DuckDB, else wpk's own (which may lack it: the kernel then says so)."""
    venv = os.path.join(folder, "packages", "python", "bin", "python")
    if os.access(venv, os.X_OK) and _has_duckdb(venv):
        return venv
    return sys.executable


def _sdir(folder):
    return os.path.join(folder, ".studio")


def info(folder):
    try:
        with open(os.path.join(_sdir(folder), INFO), encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return None


def _send(sock, req, timeout):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock)
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            got = s.recv(1 << 16)
            if not got:
                break
            buf += got
    finally:
        s.close()
    if not buf:
        raise ConnectionError("the kernel closed the connection")
    return json.loads(buf)


def _ping(folder):
    try:
        return _send(sock_path(folder), {"op": "ping"}, 5.0)
    except (OSError, ValueError):
        return None


def _same_folder(rep, folder):
    """The kernel that answered works in ``folder`` (not in one that was
    removed and made again at the same path: its socket name is the same)."""
    try:
        st = os.stat(folder)
    except OSError:
        return False
    return rep.get("here") == [st.st_dev, st.st_ino]


def alive(folder):
    rep = _ping(folder)
    return bool(rep and rep.get("ok") and _same_folder(rep, folder))


def ensure(folder, idle_s=1800.0):
    """Start the kernel for ``folder`` if it is not up; its ``kernel.json``."""
    folder = os.path.abspath(folder)
    if alive(folder):
        return info(folder)
    os.makedirs(_sdir(folder), exist_ok=True)
    with open(os.path.join(_sdir(folder), "kernel.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if alive(folder):
            return info(folder)
        stale = _ping(folder)
        if stale and stale.get("pid"):
            _kill(stale["pid"])                 # its folder is gone: a new one replaces it
        sock = sock_path(folder)
        py = python_for(folder)
        env = dict(os.environ)
        env["PYTHONPATH"] = PKG_PARENT + (os.pathsep + env["PYTHONPATH"]
                                          if env.get("PYTHONPATH") else "")
        env.pop("WPK_PROTECT", None)
        log = open(os.path.join(_sdir(folder), LOG), "ab")
        p = subprocess.Popen([py, "-m", "work_packet.studio.kernel_main", "--sock", sock,
                              "--idle", str(float(idle_s))],
                             cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)
        log.close()
        end = time.time() + START_S
        while time.time() < end:
            if p.poll() is not None:
                raise KernelError("the kernel did not start (exit %s): see %s"
                                  % (p.returncode, os.path.join(_sdir(folder), LOG)))
            if alive(folder):
                d = {"pid": p.pid, "sock": sock, "python": py, "started": time.time()}
                fsutil.atomic_write(os.path.join(_sdir(folder), INFO),
                                    json.dumps(d, indent=2) + "\n")
                return d
            time.sleep(0.05)
        _kill(p.pid)
        raise KernelError("the kernel did not answer within %ds" % START_S)


def _kill(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def call(folder, op, timeout=60.0, idle_s=1800.0, **kw):
    """One request; the reply dict (``ok`` false with ``error`` for a refused
    one). KernelError when the kernel cannot answer."""
    folder = os.path.abspath(folder)
    d = ensure(folder, idle_s)
    req = dict(kw, op=op)
    try:
        return _send(sock_path(folder), req, timeout)
    except socket.timeout:
        _kill((d or {}).get("pid") or 0)
        raise KernelError("the call ran over %ds: the kernel was stopped; the next call "
                          "starts a new one (what exec had loaded is gone)" % timeout)
    except (OSError, ValueError) as ex:
        raise KernelError("the kernel stopped while answering (%s); the next call starts "
                          "a new one" % ex)


def stop(folder, wait_s=5.0):
    """End the kernel of ``folder``, if it is up; it is gone on return (it
    answers no more pings; killed if it has not gone in ``wait_s``)."""
    folder = os.path.abspath(folder)
    d = info(folder)
    rep = _ping(folder)
    pid = (rep or {}).get("pid") or (d or {}).get("pid")
    try:
        _send(sock_path(folder), {"op": "shutdown"}, 5.0)
    except (OSError, ValueError):
        pass
    end = time.time() + wait_s
    while _ping(folder) is not None and time.time() < end:
        time.sleep(0.05)
    if _ping(folder) is not None and pid:
        _kill(pid)
    try:
        os.unlink(os.path.join(_sdir(folder), INFO))
    except OSError:
        pass


# --- history (S2.5) -----------------------------------------------------------------

def export_history(entry, folder, max_age_s=30.0):
    """Write the project's steps to ``.studio/history/steps.jsonl`` for the
    kernel's ``history.steps`` (unless it was written in the last
    ``max_age_s``)."""
    from .. import stats
    from . import data
    path = os.path.join(folder, data.HISTORY_FILE)
    try:
        if time.time() - os.path.getmtime(path) < max_age_s and os.path.getsize(path):
            return path
    except OSError:
        pass
    steps = stats.collect([(entry["name"], entry["path"])])[0]
    lines = []
    for s in steps:
        d = {k: getattr(s, k, None) for k in data.HISTORY_COLUMNS if k not in ("packet",)}
        d["packet"] = s.wpid
        lines.append(json.dumps(d))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsutil.atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))
    return path
