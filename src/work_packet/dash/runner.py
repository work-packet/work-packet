"""The runner inside the board's process (docs/dash-tasks.md §7).

A thread that runs ``scheduler.tick`` until nothing is due, then waits for a
poke (a hand-off, an answer, a wake from the board) or for the next
``wake_at``. One runner per home, by a lock on ``runner.lock``.
"""

import fcntl
import logging
import os
import threading

from .. import clock, registry, scheduler

log = logging.getLogger("wpk.runner")

MAX_WAIT_S = 60     # look again at least this often (a packet made by the CLI)


class RunnerBusy(Exception):
    pass


class Runner:
    def __init__(self, home=None, jobs=None, max_wait=MAX_WAIT_S):
        self.home = home or registry.home()
        self.jobs = jobs
        self.max_wait = max_wait
        self._poke = threading.Event()
        self._stopping = threading.Event()
        self._thread = None
        self._lock_fd = None
        self.busy = False         # inside a scheduler pass
        self.last = []            # the last few results, newest last

    def acquire(self):
        """Take ``runner.lock``, or raise ``RunnerBusy``."""
        os.makedirs(self.home, exist_ok=True)
        fd = os.open(os.path.join(self.home, "runner.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise RunnerBusy("another runner holds %s"
                             % os.path.join(self.home, "runner.lock"))
        os.ftruncate(fd, 0)
        os.write(fd, b"%d\n" % os.getpid())
        self._lock_fd = fd

    def start(self):
        if self._lock_fd is None:
            self.acquire()
        self._thread = threading.Thread(target=self._loop, name="wpk-runner", daemon=True)
        self._thread.start()

    def poke(self):
        """Look for due packets now."""
        self._poke.set()

    def stop(self, timeout=None):
        """Start no new step, wait for running ones, release the lock."""
        self._stopping.set()
        self._poke.set()
        if self._thread is not None:
            self._thread.join(timeout)
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def _report(self, r):
        log.warning("%s %s: %s", r.due.project, r.due.wpid[:8], r.msg)
        self.last = (self.last + [r])[-20:]

    def _wait_s(self, entries):
        t = scheduler.next_wake(entries)
        if t is None:
            return self.max_wait
        return max(0.5, min(self.max_wait, (t - clock.now()).total_seconds() + 0.5))

    def _loop(self):
        while not self._stopping.is_set():
            self._poke.clear()
            try:
                es = registry.entries(self.home)
                jobs = self.jobs or registry.load_config(self.home)["max_concurrent"]
                self.busy = True
                try:
                    scheduler.tick(es, jobs=jobs, until_idle=True, report=self._report,
                                   stop=self._stopping.is_set)
                finally:
                    self.busy = False
                wait = self._wait_s(registry.entries(self.home))
            except Exception:                      # keep the runner alive; say why
                log.exception("runner pass failed")
                wait = self.max_wait
            self._poke.wait(wait)
