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
WATCH_TICK_S = 60   # look for due watchers this often (docs/starters-v1.md)


class RunnerBusy(Exception):
    pass


class Runner:
    def __init__(self, home=None, jobs=None, max_wait=MAX_WAIT_S, backend=None,
                 watch_tick=WATCH_TICK_S):
        self.home = home or registry.home()
        self.jobs = jobs
        self.max_wait = max_wait
        self._backend = backend
        self._poke = threading.Event()
        self._stopping = threading.Event()
        self._thread = None
        self._watcher = None
        self._sessions = None
        self.watch_tick = watch_tick
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
        if self.watch_tick:
            self._watcher = threading.Thread(target=self._watch_loop, name="wpk-watch",
                                             daemon=True)
            self._watcher.start()
        if self.watch_tick:
            self._sessions = threading.Thread(target=self._sessions_loop,
                                              name="wpk-ide-sessions", daemon=True)
            self._sessions.start()

    def poke(self):
        """Look for due packets now."""
        self._poke.set()

    def stop(self, timeout=None, release=True):
        """Start no new step, wait for running ones, release the lock.
        ``release=False``: keep the lease file for the image an in-place
        restart execs into (docs/serve-restart-plan.md)."""
        self.halt()
        if self._thread is not None:
            self._thread.join(timeout)
        for t in (self._watcher, self._sessions):
            if t is not None:
                t.join(timeout)
        if self._lease is not None:
            if release:
                self._lease.release()
            else:
                self._lease.keep()
            self._lease = None

    def halt(self):
        """Start no new step; the running ones go on (``stop`` waits for them)."""
        self._stopping.set()
        self._poke.set()

    def abandon(self):
        """Stop waiting for running steps: they go on, and the next wpkd adopts
        them (sched/dispatcher.py ``adopt``)."""
        if self.dispatcher is not None:
            self.dispatcher.no_drain = True

    def running(self):
        """How many steps this process waits for on a stop."""
        d = self.dispatcher
        try:
            return len(d.backend.running()) if d is not None else 0
        except (AttributeError, NotImplementedError):
            return 0

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

    def _sessions_loop(self):
        """Claude and Codex sessions in the board's own web VS Code servers
        (docs/vscode-monitor-plan.md §2.4); a server in a job watches its own.
        Off with ``[ide] web = false`` or ``[ide] sessions = false``. With
        ``[ide] sessions_scribe``, the scribe drafts a status for those that
        ended (docs/session-checkpoint.md §4.2)."""
        import time
        from .. import ide, ide_sessions, scribe
        collectors, pruned = {}, 0.0
        while not self._stopping.is_set():
            try:
                cfg = ide.load_config(self.home)
            except Exception:
                cfg = {}
            every = float(cfg.get("sessions_poll_s") or 5)
            if cfg.get("web") and cfg.get("sessions", True):
                try:
                    ide_sessions.local_pass(self.home, collectors)
                    scribe.pass_once(self.home, cfg)
                    _reap_presence(self.home)
                    if time.time() - pruned > 3600:
                        ide_sessions.prune(self.home, time.time(),
                                           keep_days=cfg.get("sessions_keep_days") or 30)
                        pruned = time.time()
                except Exception:              # keep watching; say why
                    log.exception("VS Code session pass failed")
            else:
                collectors.clear()
            if cfg.get("sessions", True):
                try:                           # desktop VS Code and terminals, by their hooks
                    ide_sessions.hook_pass(self.home)
                    _log_waits(self.home, cfg)
                except Exception:
                    log.exception("hooked session pass failed")
            self._stopping.wait(every)

    def _watch_loop(self):
        """Poll the boards' watchers that are due; poke the dispatcher when one
        made a packet; open the pull requests of their packets that completed
        (pr.sync). Only here, so one runner per home polls."""
        from .. import pr, watch

        def report(w, r):
            for k, name in r["made"]:
                log.warning("watch %s/%s: %s made from %s", w["board"], w["name"], name, k)
            for k in r.get("proposed") or ():
                log.warning("watch %s/%s: %s put in the Inbox", w["board"], w["name"], k)
            for k, e in r["failed"].items():
                log.warning("watch %s/%s: %s: %s", w["board"], w["name"], k, e)
            for e in r["errors"]:
                log.warning("watch %s/%s: %s", w["board"], w["name"], e)
        while not self._stopping.is_set():
            try:                               # the morning brief (collaboration.md §9.4)
                from .. import brief
                cfg = registry.load_config_file(self.home).get("focus") or {}
                if brief.maybe_build(self.home or registry.home(), cfg):
                    log.warning("wrote today's focus brief")
            except Exception:
                log.exception("focus brief failed")
            try:                               # pushes and the digest (collaboration.md §4.3)
                from .. import notify
                r = notify.run(self.home or registry.home())
                for e in (r or {}).get("errors") or ():
                    log.warning("notify: %s", e)
            except Exception:
                log.exception("notify pass failed")
            try:                               # weekly review, milestone snapshots (§9.3, §9.5)
                from .. import reviews
                cfg = registry.load_config_file(self.home).get("focus") or {}
                for what in reviews.tick(self.home or registry.home(), cfg):
                    log.warning("reviews: %s", what)
            except Exception:
                log.exception("reviews pass failed")
            try:                               # recurring corrections (collaboration.md §7.7)
                from .. import learn
                got = learn.maybe_propose(self.home or registry.home())
                if got:
                    log.warning("learn: proposed %d rule(s) in the Inbox", len(got))
            except Exception:
                log.exception("learn pass failed")
            try:
                if watch.poll_due(self.home, report=report):
                    self.poke()
            except Exception:                  # keep polling; say why
                log.exception("watch pass failed")
            try:
                pr.sync(self.home, report=lambda name, msg, ok: log.warning(
                    "pr %s: %s%s", name, "" if ok else "not opened: ", msg))
            except Exception:
                log.exception("pull request pass failed")
            self._stopping.wait(self.watch_tick)


def _reap_presence(home):
    """Presence records of sessions on this host whose process is gone
    (docs/collaboration.md §4.2): their project is no longer attended."""
    import socket
    from .. import presence, registry
    host = socket.gethostname()
    for e in registry.entries(home):
        try:
            presence.reap(e["path"], host)
        except OSError:
            pass


def _log_waits(home, cfg):
    """``turn-waiting`` journal records for sessions that waited for you
    ``[ide] idle_escalate`` (docs/collaboration.md §4.5)."""
    from .. import attention, registry
    idle = cfg.get("idle_escalate") or attention.IDLE_ESCALATE_S
    for e in registry.entries(home):
        try:
            attention.log_waits(e["path"], e.get("root"), None, idle)
        except OSError:
            pass
