"""Restarting wpkd in place (docs/serve-restart-plan.md).

``wpk serve --restart`` writes a request and sends SIGUSR2. The board closes
down without stopping the VS Code servers, then ``exec``s itself: same pid,
so systemd kills nothing and the lease stays ours, and the new image adopts
the servers. A bare SIGUSR2 (``systemctl reload``) is a request with no file:
wait for running steps, no one to report to.

``$WPK_HOME/run/restart.json``: the request (id, force, by), taken by the board.
``$WPK_HOME/run/restart-status.json``: how it went, for the CLI that asked:
``{"ids": [...], "state": "waiting"|"failed"|"done", "msg", "pid", "at"}``.
"""

import contextlib
import json
import logging
import os
import secrets
import subprocess
import sys
import time

from .. import fsutil
from ..sched.home_lease import RESTART_ENV as ENV

# The new image runs these modules first: if they do not load, do not exec.
PREFLIGHT = "import work_packet.cli, work_packet.dash.server, work_packet.dash.app"
PREFLIGHT_S = 60
# Flags of the process that asked for the detach, not of the one that runs.
DROP = {"--detach", "--ensure", "--restart", "--force"}


def run_dir(home):
    return os.path.join(home, "run")


def request_path(home):
    return os.path.join(run_dir(home), "restart.json")


def status_path(home):
    return os.path.join(run_dir(home), "restart-status.json")


def request(home, force=False, by=None):
    """Leave a request for the board; returns its id."""
    rid = secrets.token_hex(6)
    os.makedirs(run_dir(home), mode=0o700, exist_ok=True)
    fsutil.atomic_write(request_path(home), json.dumps(
        {"id": rid, "force": bool(force), "by": by, "at": time.time()}) + "\n")
    return rid


def take(home):
    """The request, removed; ``{}`` when there is none (a bare SIGUSR2)."""
    p = request_path(home)
    try:
        with open(p) as fp:
            d = json.load(fp)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        d = {}
    with contextlib.suppress(OSError):
        os.unlink(p)
    return d if isinstance(d, dict) else {}


def set_status(home, ids, state, msg=""):
    ids = [i for i in ids if i]
    if not ids:
        return
    with contextlib.suppress(OSError):
        os.makedirs(run_dir(home), mode=0o700, exist_ok=True)
        fsutil.atomic_write(status_path(home), json.dumps(
            {"ids": ids, "state": state, "msg": msg, "pid": os.getpid(),
             "at": time.time()}) + "\n")


def status(home, rid):
    """The status that answers request ``rid``, or None (not yet)."""
    try:
        with open(status_path(home)) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and rid in (d.get("ids") or ()) else None


def preflight():
    """Why the code on disk would not start (an upgrade that broke it), or None."""
    try:
        r = subprocess.run([sys.executable, "-c", PREFLIGHT], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=PREFLIGHT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    if r.returncode:
        lines = r.stderr.strip().splitlines()
        return lines[-1] if lines else "exit %d" % r.returncode
    return None


def argv():
    """This process's command line, as ``python -m work_packet``."""
    return [sys.executable, "-m", "work_packet"] + [a for a in sys.argv[1:] if a not in DROP]


def exec_self(ids):
    """Become a fresh wpkd. Only returns by raising (``OSError``)."""
    for f in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            f.flush()
    logging.shutdown()
    env = dict(os.environ)
    env[ENV] = ",".join(i for i in ids if i) or "-"
    os.execve(sys.executable, argv(), env)


def restarted():
    """The request ids this image was exec'd for (``["-"]`` for a bare signal),
    or None on a normal start. Taken out of the environment, so no child sees it."""
    v = os.environ.pop(ENV, None)
    if v is None:
        return None
    return [i for i in v.split(",") if i]
