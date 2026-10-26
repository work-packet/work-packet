"""The dispatcher: start due packets in slots by class, share and size, reap
their jobs, survive restarts (docs/scheduler.md §7, plan Q1.14).

``pass_once()`` is one reap and one fill, for tests and ``wpk tick``;
``run()`` is wpkd's loop, on a thread (plan decision 2).
"""

import logging
import os
import time

from .. import clock, frontmatter, registry, schema, scheduler
from ..packet import Packet
from . import authz, control, events, gates, jobs, queue
from . import config as sconfig
from .backends import DONE, LOST, PENDING, RUNNING, BackendError, Task
from .backends import get as get_backend

log = logging.getLogger("wpk.sched")

KILL_AFTER_S = 30          # SIGTERM, then SIGKILL this much later
FALLBACK_S = 30            # fill at least this often while jobs run
BACKOFF_S = (30, 600)      # a failing submit: 30 s, doubling to 10 min
LOW_CPU = 0.2              # a multi-core job that used less than this share of its cores


def _ts(dt):
    return schema.format_timestamp(dt)


def _last_line(path):
    try:
        with open(path, "rb") as fp:
            fp.seek(0, os.SEEK_END)
            n = fp.tell()
            fp.seek(max(0, n - 4096))
            lines = fp.read().decode("utf-8", "replace").strip().splitlines()
    except OSError:
        return ""
    msg = lines[-1] if lines else ""
    return msg[5:] if msg.startswith("wpk: ") else msg


class Dispatcher:
    def __init__(self, home=None, backend=None, now=None, cfg=None, jobs=None,
                 report=None, entries=None, by=None):
        """``now``: a callable giving the time (tests pass a fake clock).
        ``cfg``: a fixed ``[sched]`` config; None reads ``config.toml`` each pass.
        ``jobs``: overrides the pool's job limit (``wpk tick -j``).
        ``entries``: a callable giving the registry entries to schedule.
        ``report(scheduler.Ran)``: called for each step job that ends."""
        self.h = home or registry.home()
        self._cfg = cfg
        self.backend = backend or get_backend(self.cfg(), self.h)
        self.now = now or clock.now
        self.jobs = jobs
        self.report = report or (lambda r: None)
        self.entries = entries or (lambda: registry.entries(self.h))
        self.by = by or authz.principal_cli()
        self.last = []                  # recent scheduler.Ran, newest last
        self.mine = set()               # job IDs this dispatcher submitted or adopted
        self.backoff_until = None
        self.backoff_s = 0
        self.last_plan = None           # (items, reasons, ctx) of the last fill
        self._sent = set()              # job IDs this dispatcher sent a cancel to

    def cfg(self):
        return self._cfg if self._cfg is not None else sconfig.load(self.h)

    # --- restart -------------------------------------------------------------

    def adopt(self):
        """Take over the jobs a previous wpkd left (§5.4): records are kept for
        jobs that still run; a job in the batch system with our name and no
        record is adopted, or cancelled if its packet is not runnable."""
        recs = jobs.all(self.h)
        for r in recs:
            self.mine.add(r.id)
        try:
            ours = self.backend.list_ours()
        except BackendError as e:
            log.warning("cannot list jobs: %s", e)
            ours = {}
        known = {r.ref for r in recs if r.ref}
        for ref, name in ours.items():
            if ref in known:
                continue
            got = self._from_name(name)
            if got is None:
                continue
            e, pkt, step = got
            try:
                meta, _ = pkt.load_status()
            except (OSError, frontmatter.FrontMatterError):
                meta = {}
            if meta.get("state") not in ("RUNNABLE", "SLEEPING"):
                self.backend.cancel(ref)
                events.append("cancelled", h=self.h, job=ref, project=e["name"],
                              wpid=pkt.wpid, why="orphan job for a packet that is %s"
                              % meta.get("state"))
                continue
            rec = jobs.JobRecord(id=jobs.new_id(), backend=self.backend.name, kind="step",
                                 project=e["name"], wpid=pkt.wpid, path=pkt.path, by=self.by,
                                 step=step, submitted=_ts(self.now()), ref=ref)
            jobs.save(rec, self.h)
            self.mine.add(rec.id)
            events.append("adopted", h=self.h, job=rec.id, ref=ref, project=e["name"],
                          wpid=pkt.wpid)
        return self.reap()

    def _from_name(self, name):
        parts = (name or "").split(":")
        if len(parts) != 4 or parts[0] != "wpk":
            return None
        _, _, wpid, step = parts
        for e, path in registry.find_packets(wpid, self.h):
            if os.path.basename(path) == wpid:
                return e, Packet(path), int(step) if step.isdigit() else None
        return None

    # --- reap ----------------------------------------------------------------

    def reap(self):
        """Look at every job: note starts, end the finished, cancel the stuck.
        Returns the scheduler.Ran of each step job that ended."""
        recs = [r for r in jobs.all(self.h) if r.backend == self.backend.name]
        if not recs:
            return []
        now = self.now()
        cfg = self.cfg()
        live = [r for r in recs if r.ref]
        try:
            states = self.backend.poll([r.ref for r in live])
        except BackendError as e:
            log.warning("cannot poll jobs: %s", e)
            return []
        out = []
        max_pending = schema.parse_duration(cfg.get("max_pending", "30m"))
        for r in recs:
            if not r.ref:               # wpkd died between the record and the submit
                if r.id not in self.mine or self._age(r.submitted, now) > 60:
                    jobs.remove(r.id, self.h)
                continue
            st = states.get(r.ref)
            if st is None:
                continue
            if r.cancel and r.id not in self._sent and st.state in (PENDING, RUNNING):
                # A control in another process (the CLI) asked; its backend may not
                # reach this job (the local one only knows its own children).
                self._sent.add(r.id)
                self.backend.cancel(r.ref)
            if st.state == PENDING:
                self._pending(r, now, max_pending)
            elif st.state == RUNNING:
                if r.state != RUNNING:
                    r.state, r.started = RUNNING, st.started or _ts(now)
                    jobs.save(r, self.h)
                    events.append("started", h=self.h, job=r.id, project=r.project,
                                  wpid=r.wpid, step=r.step, size=r.size)
                if r.cancel and self._age(r.cancel, now) >= KILL_AFTER_S:
                    self.backend.cancel(r.ref, hard=True)
            else:
                ran = self._ended(r, st, now)
                if ran is not None:
                    out.append(ran)
        return out

    def _age(self, ts, now):
        try:
            return (now - schema.parse_timestamp(ts)).total_seconds()
        except (TypeError, ValueError):
            return 0.0

    def _pending(self, r, now, max_pending):
        if r.cancel:
            return
        if r.kind == "step":
            try:
                meta, _ = Packet(r.path).load_status()
                state = meta.get("state")
            except (OSError, frontmatter.FrontMatterError):
                state = None
            if state not in ("RUNNABLE", "SLEEPING"):
                control.cancel_jobs(lambda x: x.id == r.id, events.SYSTEM,
                                    "packet is %s" % state, h=self.h, backend=self.backend,
                                    lost=False)
                self._sent.add(r.id)
                return
        if not r.pending_long and max_pending and self._age(r.submitted, now) > max_pending:
            r.pending_long = True
            jobs.save(r, self.h)
            events.append("pending_long", h=self.h, job=r.id, project=r.project, wpid=r.wpid,
                          size=r.size, since=r.submitted)

    def _ended(self, r, st, now):
        lost = (st.state == LOST or not st.counted) and not r.cancel   # ours: already noted
        if lost:
            why = st.reason or "lost"
            if r.kind == "step":
                jobs.mark_lost(r.wpid, why, events.SYSTEM, _ts(now), r.step, self.h)
            events.append("lost", h=self.h, job=r.id, project=r.project, wpid=r.wpid,
                          step=r.step, size=r.size, why=why)
        if r.kind == "step" and self.backend.name != "local":
            self._free_lease(r)
        started = r.started or st.started
        wall = None
        try:                  # the batch system's own clock when it says, else ours
            if st.started and st.ended:
                wall = (schema.parse_timestamp(st.ended) -
                        schema.parse_timestamp(st.started)).total_seconds()
            elif started:
                wall = (now - schema.parse_timestamp(started)).total_seconds()
        except ValueError:
            wall = None
        wall = max(0.0, wall) if wall is not None else None
        low = bool(st.cpu_s is not None and wall and r.cpus > 1 and wall > 60 and
                   st.cpu_s < LOW_CPU * r.cpus * wall)
        msg = _last_line(r.log) if r.log else ""
        events.append("finished", h=self.h, job=r.id, kind=r.kind, project=r.project,
                      wpid=r.wpid, step=r.step, size=r.size, cpus=r.cpus, code=st.code,
                      submitted=r.submitted, started=started, end=_ts(now), wall_s=wall,
                      cpu_s=st.cpu_s, low_cpu=low or None, cancelled=r.cancel_why,
                      lost=st.reason if lost else None, how=st.reason if not lost else None)
        jobs.remove(r.id, self.h)
        if r.kind == "ide":                 # closed, idle or out of time: asked for again
            from . import ide                # when someone opens it
            ide.withdraw(r.wpid, self.h)
            try:
                os.unlink(ide.endpoint_path(r.wpid, self.h))
            except OSError:
                pass
        if r.log:
            try:
                os.unlink(r.log)
            except OSError:
                pass
        self.mine.discard(r.id)
        self._sent.discard(r.id)
        if r.kind != "step":
            return None
        if not msg:
            msg = r.cancel_why or ("exit %s" % st.code if st.code is not None else "finished")
        ran = scheduler.Ran(scheduler.Due(r.submitted or "", r.project, r.wpid, r.path, ""),
                            st.code if st.code is not None else -1, msg)
        self.last = (self.last + [ran])[-20:]
        try:
            self.report(ran)
        except Exception:                # noqa: BLE001: a report never stops the pool
            log.exception("report failed")
        return ran

    def _free_lease(self, r):
        """A step's job has ended, but its lease names another host, where the
        PID cannot be checked: the batch system says that process is gone, so the
        lease is (Q4.3: live until its expiry or the job's end, whichever is first)."""
        import socket
        from .. import journal, lease
        pkt = Packet(r.path)
        held = lease.read(pkt.lease_path)
        if not held or held.get("host") == socket.gethostname() or \
                (r.step is not None and held.get("step") != r.step):
            return
        try:
            os.unlink(pkt.lease_path)
        except OSError:
            return
        journal.append(pkt.journal_path, {
            "type": "note", "t": _ts(self.now()),
            "msg": "removed the lease of job %s, which has ended (host %s, pid %s)" % (
                r.ref, held.get("host"), held.get("pid"))})

    # --- fill ----------------------------------------------------------------

    def context(self, now=None, cfg=None, projs=None):
        """The gate context and the due items, as the next fill would see them."""
        cfg = cfg or self.cfg()
        now = now or self.now()
        es = self.entries()
        projs = projs if projs is not None else queue.projects(es, cfg)
        items = queue.build(es, cfg, now, projs)
        recs = jobs.all(self.h)
        ctx = gates.Ctx(cfg=cfg, now=now, mode=control.read_mode(self.h, cfg),
                        limits=sconfig.pool_limits(cfg, self.h, now, jobs=self.jobs),
                        usage=gates.Usage.of(recs), projs=projs,
                        backfill_for_s=schema.parse_duration(cfg["backfill_for"]),
                        spare=sconfig.size(cfg, cfg["spare_size"]))
        self._extend(ctx, recs)
        res = ((cfg.get("ide") or {}).get("reserve") or "")
        ctx.reserve = sconfig.size(cfg, res) if res else None
        return items, ctx

    def _extend(self, ctx, recs):
        """The budget gate (§4) and the spend ledger, when a budget or a project
        cap is set."""
        from . import budget
        ctx.ledger = None
        if ctx.cfg["budget"].get("measure") or budget.caps_set(ctx.projs):
            ctx.ledger = budget.ledger([p.entry for p in ctx.projs.values()])
        ctx.budget = budget.gate_for(ctx, recs, self.h, recs=ctx.ledger)

    def _caps(self, items, ctx):
        """Hold packets over their project's caps (§4.5): paused with the figures
        until L1's HELD/limit, so they show under Needs you. Returns the rest."""
        from .. import executor
        from . import budget
        if ctx.ledger is None:
            return items
        tz = budget._zone(ctx.cfg["budget"].get("tz") or ctx.cfg.get("tz"))
        out = []
        for it in items:
            p = ctx.projs.get(it.project)
            why = budget.over_cap(it, p, ctx.ledger, ctx.now, tz) if p is not None else None
            if why is None:
                out.append(it)
                continue
            got = executor.admin(Packet(it.path), "pause", by=events.SYSTEM, reason=why)
            if got.code == 0:
                events.append("cap", h=self.h, project=it.project, wpid=it.wpid, why=why)
        return out

    def fill(self, only=None, limit=None):
        """Submit what may start now. ``only``: item keys to consider (one pass of
        ``wpk tick``). Returns the new job records."""
        now = self.now()
        if self.backoff_until is not None and now.timestamp() < self.backoff_until:
            return []
        items, ctx = self.context(now)
        if only is not None:
            items = [it for it in items if it.key in only]
        items = self._caps(items, ctx)
        out_ide = self._ides(ctx, now) if only is None else []
        start, reasons = gates.plan(items, ctx, queue.order, limit)
        if ctx.budget is not None:
            from .budget import write_spend
            write_spend(self.h, ctx.budget)
        self.last_plan = (items, reasons, ctx)
        out = list(out_ide)
        for it in start:
            rec = self.submit(it, ctx)
            if rec is None:
                break
            out.append(rec)
        return out

    def _ides(self, ctx, now):
        """Start the IDE jobs asked for (§8): first in line, never gated by the
        mode or the budget, never preempting; the reserve is theirs. A request
        with no room yet holds back all agent work (``gates.ide_first``)."""
        from . import ide
        have = {r.wpid for r in jobs.all(self.h) if r.kind == "ide"}
        cfg = ctx.cfg
        limit = (cfg.get("ide") or {}).get("run_limit")
        out = []
        for rq in ide.requests(self.h):
            if rq["key"] in have:
                continue
            z = sconfig.size(cfg, rq.get("size") or "") or sconfig.size(cfg, cfg["default_size"])
            if limit:
                import dataclasses
                z = dataclasses.replace(z, time_s=schema.parse_duration(limit))
            if gates._free_after(ctx, z.cpus, z.mem_mb) is not None:
                ctx.ide_waiting.append(rq)
                continue
            rec = jobs.JobRecord(id=jobs.new_id(), backend=self.backend.name, kind="ide",
                                 project="ide", wpid=rq["key"], path=rq.get("target", ""),
                                 by=rq.get("by") or self.by, cls="urgent", size=z.name,
                                 cpus=z.cpus, mem_mb=z.mem_mb, submitted=_ts(now))
            rec.log = jobs.log_path(rec.id, self.h)
            jobs.save(rec, self.h)
            self.mine.add(rec.id)
            task = Task(job_id=rec.id, kind="ide", project="ide", wpid=rq["key"],
                        path=rec.path, size=z, log=rec.log, argv=rq["argv"],
                        name="wpk:%s:ide-%s:0" % (home_id(self.h), rq["key"]))
            try:
                rec.ref = self.backend.submit(task)
            except BackendError as e:
                jobs.remove(rec.id, self.h)
                self._backoff(str(e))
                break
            if not self.backend.holds_room_while_pending:
                rec.state, rec.started = RUNNING, _ts(now)
            jobs.save(rec, self.h)
            ctx.usage.add("ide", z.cpus, z.mem_mb, z.name, "ide")
            events.append("submitted", h=self.h, job=rec.id, ref=rec.ref, kind="ide",
                          key=rq["key"], size=z.name, by=rec.by)
            out.append(rec)
        return out

    def submit(self, it, ctx=None):
        now = self.now()
        try:
            meta, _ = Packet(it.path).load_status()
            step = meta["step"] + 1
        except (OSError, frontmatter.FrontMatterError, KeyError, TypeError):
            step = None
        lost = jobs.lost(it.wpid, self.h)
        rec = jobs.JobRecord(id=jobs.new_id(), backend=self.backend.name, kind="step",
                             project=it.project, wpid=it.wpid, path=it.path, by=self.by,
                             cls=it.cls, size=it.size.name, cpus=it.size.cpus,
                             mem_mb=it.size.mem_mb, step=step, submitted=_ts(now),
                             lost=lost["reason"] if lost else None)
        rec.log = jobs.log_path(rec.id, self.h)
        if ctx is not None and ctx.budget is not None:
            rec.estimate = ctx.budget.estimate(it)
        jobs.save(rec, self.h)              # first, so a crash after submit is found
        self.mine.add(rec.id)
        task = Task(job_id=rec.id, kind="step", project=it.project, wpid=it.wpid,
                    path=it.path, size=it.size, log=rec.log, step=step, lost=rec.lost,
                    name=job_name(self.h, it.wpid, step))
        try:
            rec.ref = self.backend.submit(task)
        except BackendError as e:
            jobs.remove(rec.id, self.h)
            self.mine.discard(rec.id)
            self._backoff(str(e))
            return None
        if self.backoff_s:
            events.append("backend_up", h=self.h, backend=self.backend.name)
        self.backoff_s, self.backoff_until = 0, None
        if not self.backend.holds_room_while_pending:
            rec.state, rec.started = RUNNING, _ts(now)
        jobs.save(rec, self.h)
        if lost:
            jobs.clear_lost(it.wpid, self.h)
        if it.next:
            control.clear_next(it.project, it.wpid, self.h)
        events.append("submitted", h=self.h, job=rec.id, ref=rec.ref, project=it.project,
                      wpid=it.wpid, step=step, cls=it.cls, aged=it.aged, size=it.size.name,
                      lost=rec.lost, estimate=rec.estimate)
        if rec.state == RUNNING:
            events.append("started", h=self.h, job=rec.id, project=it.project, wpid=it.wpid,
                          step=step, size=it.size.name)
        return rec

    def _backoff(self, why):
        lo, hi = BACKOFF_S
        first = not self.backoff_s
        self.backoff_s = min(hi, self.backoff_s * 2) if self.backoff_s else lo
        self.backoff_until = self.now().timestamp() + self.backoff_s
        if first:
            events.append("backend_down", h=self.h, backend=self.backend.name, why=why,
                          retry_s=self.backoff_s)
        log.warning("submit failed (%s); retrying in %ds", why, self.backoff_s)

    @property
    def backend_down(self):
        return self.backoff_until is not None

    # --- loops ---------------------------------------------------------------

    def pass_once(self):
        """One reap, then one fill: (ended Ran list, submitted records)."""
        ran = self.reap()
        return ran, self.fill()

    def live(self):
        """The job records this dispatcher is responsible for."""
        return [r for r in jobs.all(self.h) if r.id in self.mine]

    def tick_pass(self, keys, limit=None, stop=lambda: False):
        """One ``wpk tick`` pass: start each of ``keys`` at most once, wait for
        them all. Returns the Ran list."""
        ran, started = [], set()
        while True:
            ran += self.reap()
            subs = []
            if not stop() and (limit is None or len(started) < limit):
                subs = self.fill(only=set(keys) - started,
                                 limit=None if limit is None else limit - len(started))
                started |= {(r.project, r.wpid) for r in subs}
            if not subs and not self.live():
                return ran
            time.sleep(0.02)

    def run(self, stopping, poke, max_wait=60.0, drain_timeout=None):
        """wpkd's loop until ``stopping`` is set. Fills on a poke, a job's start
        or end, the next ``wake_at``, or every FALLBACK_S; polls the backend
        every ``poll``. On stop, starts nothing more and, for the local backend,
        waits for running steps (they are this process's children)."""
        self.adopt()
        events.append("wpkd_start", h=self.h, backend=self.backend.name, pid=os.getpid())
        last_fill = 0.0
        want_fill = True
        while not stopping.is_set():
            poked = poke.is_set()
            poke.clear()
            try:
                ended = self.reap()
                if poked or ended or want_fill or time.monotonic() - last_fill > FALLBACK_S:
                    self.fill()
                    last_fill = time.monotonic()
                want_fill = False
                wait = self.wait_s(max_wait)
            except Exception:                  # keep the pool alive; say why
                log.exception("dispatcher pass failed")
                wait = max_wait
            if poke.wait(wait):
                continue
            want_fill = self._timer_due()
        self._drain(drain_timeout)
        events.append("wpkd_stop", h=self.h, pid=os.getpid())

    def _timer_due(self):
        t = self._next_wake
        return t is not None and t <= self.now()

    def wait_s(self, max_wait=60.0):
        """How long to sleep: the backend's poll interval while jobs are out,
        else until the next ``wake_at`` (at most ``max_wait``)."""
        cfg = self.cfg()
        poll = schema.parse_duration(cfg["poll"]) if cfg.get("poll") else self.backend.poll_s
        self._next_wake = scheduler.next_wake(self.entries())
        wait = max_wait
        if self._next_wake is not None:
            wait = max(0.5, min(wait, (self._next_wake - self.now()).total_seconds() + 0.5))
        if self.live() or jobs.all(self.h):
            wait = min(wait, poll)
        if self.backoff_until is not None:
            wait = min(wait, max(0.5, self.backoff_until - self.now().timestamp()))
        return wait

    _next_wake = None

    def _drain(self, timeout):
        if self.backend.name != "local":
            return
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.backend.running() and (deadline is None or time.monotonic() < deadline):
            self.reap()
            time.sleep(0.05)
        self.reap()


def home_id(h):
    import hashlib
    return hashlib.sha256(os.path.abspath(h).encode()).hexdigest()[:8]


def job_name(h, wpid, step):
    return "wpk:%s:%s:%s" % (home_id(h), wpid, step if step is not None else 0)
