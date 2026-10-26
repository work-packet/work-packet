"""The ``local`` backend: ``wpk step`` as a child process on this host.

Cores and memory are counted, not enforced (plan decision 8). A job's ref
is ``<pid>:<start ticks>``, so a restarted wpkd can tell a job it started
from a new process that reused the PID.
"""

import os
import signal
import subprocess
import sys

from ... import procs
from . import DONE, PENDING, RUNNING, Backend, JobState


def _alive(pid, start):
    st = procs._stat(pid)
    return st is not None and st["state"] != "Z" and (start is None or st["start"] == start)


def _split(ref):
    pid, _, start = ref.partition(":")
    return int(pid), (int(start) if start else None)


def step_argv(path, lost=None):
    argv = [sys.executable, "-m", "work_packet", "step", path]
    if lost:
        argv += ["--lost", lost]
    return argv


class Local(Backend):
    name = "local"
    poll_s = 0.25                         # Popen.poll is cheap
    holds_room_while_pending = False      # nothing pends: a job starts at once

    def __init__(self, h=None):
        self.h = h
        self._kids = {}                   # ref -> Popen, for the jobs this process started

    def submit(self, task):
        argv = task.argv or step_argv(task.path, task.lost)
        os.makedirs(os.path.dirname(task.log), exist_ok=True)
        with open(task.log, "ab") as err:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=err, start_new_session=True,
                                 env=dict(os.environ, **task.env) if task.env else None)
        st = procs._stat(p.pid)
        ref = "%d:%s" % (p.pid, st["start"] if st else "")
        self._kids[ref] = p
        return ref

    def poll(self, refs):
        out = {}
        for ref in refs:
            p = self._kids.get(ref)
            if p is not None:
                code = p.poll()
                if code is None:
                    out[ref] = JobState(RUNNING)
                else:
                    del self._kids[ref]
                    out[ref] = JobState(DONE, code=code)
                continue
            try:
                pid, start = _split(ref)
            except ValueError:
                out[ref] = JobState(DONE)
                continue
            out[ref] = JobState(RUNNING) if _alive(pid, start) else JobState(DONE)
        return out

    def cancel(self, ref, hard=False):
        try:
            pid, start = _split(ref)
        except ValueError:
            return
        if ref not in self._kids and not _alive(pid, start):
            return
        try:
            os.killpg(pid, signal.SIGKILL if hard else signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def list_ours(self):
        """Local jobs are only known from their records; the dispatcher has those."""
        return {}

    def running(self):
        return [r for r, p in self._kids.items() if p.poll() is None]


__all__ = ["Local", "PENDING", "RUNNING", "DONE"]
