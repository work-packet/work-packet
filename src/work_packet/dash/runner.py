"""The runner inside the board's process (docs/dash-tasks.md §7).

A thread that runs the scheduler's dispatcher (docs/scheduler.md §7): it
starts due packets in slots by class, share and size as slots free, and
waits for a poke (a hand-off, an answer, a wake from the board), a job's
end, or the next ``wake_at``. One runner per home, by ``wpkd.lease``.
"""

import logging
import threading

from .. import registry

log = logging.getLogger("wpk.runner")

MAX_WAIT_S = 60     # look again at least this often (a packet made by the CLI)


class RunnerBusy(Exception):
    pass


class Runner:
    def __init__(self, home=None, jobs=None, max_wait=MAX_WAIT_S, backend=None):
        self.home = home or registry.home()
        self.jobs = jobs
        self.max_wait = max_wait
        self._backend = backend
        self._poke = threading.Event()
        self._stopping = threading.Event()
        self._thread = None
        self._lease = None
        self.dispatcher = None

    def acquire(self):
        """Take the home's ``wpkd.lease`` (sched/home_lease.py), or raise ``RunnerBusy``
        naming the holder. It works across hosts that share the home."""
        from ..sched.home_lease import HomeBusy, HomeLease
        try:
            self._lease = HomeLease(self.home).acquire()
        except HomeBusy as e:
            raise RunnerBusy(str(e)) from None
        self._lease.start_refresher(on_lost=self._lost)

    def _lost(self):
        log.error("another wpkd took this home's lease; starting nothing more")
        self._stopping.set()
        self._poke.set()

    def start(self):
        from ..sched.dispatcher import Dispatcher
        if self._lease is None:
            self.acquire()
        self.dispatcher = Dispatcher(home=self.home, backend=self._backend, jobs=self.jobs,
                                     report=self._report)
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
        if self._lease is not None:
            self._lease.release()
            self._lease = None

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def busy(self):
        """Steps are running (jobs this runner started or adopted)."""
        d = self.dispatcher
        return bool(d is not None and d.live())

    @property
    def last(self):
        """The last few results, newest last."""
        return self.dispatcher.last if self.dispatcher is not None else []

    def _report(self, r):
        log.warning("%s %s: %s", r.due.project, r.due.wpid[:8], r.msg)

    def _loop(self):
        try:
            self.dispatcher.run(self._stopping, self._poke, max_wait=self.max_wait)
        except Exception:                      # say why the pool stopped
            log.exception("runner stopped")
