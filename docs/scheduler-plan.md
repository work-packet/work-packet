# Scheduler: implementation, test and doc plan

Status (2026-10-26): Q1-Q6 built (638 tests pass); Q4-Q6 against the
fake batch system and a fake IDE. **What is left needs the farms**: Q0
(spikes), Q4.8 (a week on SLURM), Q5.4 (an IDE in a job, live), Q6.1 and
Q6.4 (LSF spikes and a live run). Start there with Q0.1: check the command
formats the backends parse, and copy real output into
`tests/fakebatch/samples/`. **This is the tracking
file**: tick each box when its task is done, and add a status-log entry
(at the end) whenever a milestone finishes or a decision changes. A fresh
session should be able to pick up from this file plus `docs/scheduler.md`,
the design it builds. Section numbers like "§5.2" refer to
`docs/scheduler.md`.

Contents: 1 ground rules · 2 what the code has today · 3 decisions made
for the build · 4 layout of the new code · 5 test infrastructure · 6
milestones Q0–Q6 (tasks, tests, docs) · 7 doc plan · 8 risks · status log.

## 1. Ground rules

- Build in milestone order (`Q0 → Q1 → … → Q6`). Each milestone ends with
  the full suite green, its own tests added, the docs in its "Docs" list
  updated, and a status-log entry with the pass count.
- Test output goes to a log (`python -m pytest -q > test.log 2>&1`); look
  at the tail or grep for failures.
- **Do not commit** unless asked; **never `git stash`** in this repo (the
  index carries a deliberate staged/unstaged split). Compare against old
  code with `git worktree add` in the scratchpad.
- Keep `wpk step` ignorant of the scheduler (§1). The two places the
  executor learns something new (an uncounted attempt, a step's size) are
  plain arguments and plain status fields, usable without wpkd.
- Every control is one function in `sched/control.py`. The CLI command
  and the board POST call it; neither has logic of its own.
- Every new file under `$WPK_HOME` is written atomically
  (`fsutil` write-temp-rename) and validated by `schema.py`, with its
  format in `docs/spec.md`.

## 2. What the code has today

Found in a survey on 2026-10-26; these are the seams the plan uses.

| Area | Today | Where |
|---|---|---|
| Runner | `Runner`: `flock` on `runner.lock`, a daemon thread that calls `scheduler.tick(until_idle=True)`, woken by `poke()` (a `threading.Event`) or `next_wake()` (clamped 0.5–60 s). Public: `acquire, start, poke, stop, alive, busy, last` | `dash/runner.py` |
| Who uses it | `cmd_dash` makes it when `[server] run`; `Board` starts it and on SIGTERM calls `runner.stop` in an executor; `app.back(…, poke_runner=True)` pokes after a successful action | `cli.py:707`, `dash/server.py:217–250`, `dash/app.py:270–274` |
| Scheduler | `due()` (RUNNABLE, or SLEEPING past `wake_at`, minus live leases; oldest first), `next_wake()`, `run_pass()` (Popen `wpk step`, 20 ms poll, waits for the whole pass), `tick()` | `scheduler.py` |
| Executor | Exit codes `OK, FAILED, NOT_RUNNABLE, LEASED, USAGE = 0..4`. `step()` takes the lease, runs `_recover` for an unfinished earlier attempt (**always counted**), checks `_due`, runs. `admin(pkt, op, …)` does pause/wake/resume/handoff/continue under a short lease | `executor.py:21, 281, 343, 451, 743` |
| Memento | `MEMENTO_FIELDS = (resume, reason, ask, spawn, item)`; `validate_memento`; read in `_validate_pending`, used in `_run`, persisted by `_apply` | `schema.py:26, 321`; `executor.py:155, 380, 662` |
| Registry | `projects/<name>.toml`: `name, path, root, created, template?, board?`; `validate_registry_entry`; `_set_board` rewrites with `save_toml` | `registry.py`, `schema.py:555` |
| Config | `load_config` = `CONFIG_DEFAULTS` + top level (shallow); `[server]`, `[ide]` have their own defaults and validators; `validate_config` allows only known tables | `registry.py:27–55`, `schema.py:34–60, 419–470`, `ide.py:360` |
| Project limits | `LIMITS`, `Settings`, `settings()`, `validate_project` `known`, `SETTABLE`, `set_values` (`wpk set`) | `project.py:10–90, 257, 316` |
| Spend | `meta.json` has `cost_usd`, `tokens`, `quota` (`five_hour`/`seven_day`, `first/last/resets_at`). `stats.collect(projects, since)`, `token_figures`, `latest_quota`, `Step.quota_used` | `executor.py:510`, `stats.py:24–364` |
| Prompt | `prompt.system()` (protocol + sizing + harness files), `prompt.build()` fills `prompts/step.md` | `prompt.py:112, 247` |
| Events | **`events.jsonl` does not exist.** Only reserved (spec §2). The per-packet `journal.jsonl` is the only event log | `docs/spec.md:34`, `journal.py` |
| Board | Starlette `Route` list; CSRF in `Guard` middleware (tests build `create_app()` directly and skip it); POST pattern `form → run_in_threadpool → back()`; side tab macro in `_side.html`; overview data in `dash/data.py` | `dash/app.py:79–770`, `dash/guard.py:184` |
| IDE | `Backend`: unix socket under `$WPK_HOME/ide/servers/<key>/`, local `Popen` with its own session, `_connectable` (AF_UNIX), `client()` (httpx uds), `proxy_ws` (`unix_connect`), idle loop, `Backends` with LRU and `max_servers` | `dash/ide.py:56–330, 402, 442` |
| CLI | argparse subparsers, `set_defaults(func=…)` | `cli.py:797` |
| Tests | 30 flat `tests/test_*.py`; fake model `tests/fakemodel/fake_claude.py` via `WPK_CLAUDE`, behaviours via `WPK_FAKE_BEHAVIOR`; fake clock `WPK_NOW`; `fake` and `make_project` fixtures in `conftest.py`; `test_tick.py` `home`/`new` for registered projects; `tests/fake_ide.py` stands in for `serve-web` | `tests/` |

## 3. Decisions made for the build

These fill gaps the design left, or correct it against the code.

1. **New package `src/work_packet/sched/`.** `scheduler.py` stays as the
   home of `due()` and `next_wake()` (both reused) and of `tick()`, which
   becomes a thin wrapper over a synchronous dispatcher pass with the
   local backend, so `wpk tick` and its tests keep working.
2. **The dispatcher runs on a thread, not on the asyncio loop.** The
   design said "on wpkd's asyncio loop". The existing `Runner` is a
   thread, backend calls (`sbatch`, `squeue`) are blocking subprocesses,
   and a thread keeps the board's loop free. `dash/runner.Runner` keeps
   its public API and wraps a `sched.Dispatcher`, so `app.py`,
   `server.py` and `cli.py` change only where they must.
3. **Uncounted attempts are an executor argument.** `wpk step --lost
   REASON` (and `executor.step(…, lost=REASON)`): `_recover` then writes
   its `step-failed` record with `counted: false` and does not raise
   `attempts`. The dispatcher passes it on the next launch of a packet
   whose previous job was stopped by **Stop now** or ended by the farm
   (§5.5). The reason is kept in `$WPK_HOME/sched/lost/<wpid>.json`
   until that launch, so a restart does not lose it. A step that is
   killed while wpkd is not running is counted, as today.
4. **A step's size lives in `status.md`.** `size:` in the memento is
   validated in `executor._validate_pending` against the project's
   allowed `sizes` (the schema check alone cannot know them), and `_apply`
   writes it to status as `next_size`. The scheduler reads `next_size`
   from status like it reads `wake_at`. The next commit overwrites it, so
   "for the next step only" needs no clearing code.
5. **Config table is `[sched]`** with sub-tables `budget`, `sizes.<name>`,
   `slurm`, `lsf`, `ide`; defaults in `schema.SCHED_DEFAULTS`, loader
   `sched.config.load(h)` (deep merge for the sub-tables), validator
   `schema._validate_sched`, added to `validate_config`'s allowed tables.
6. **`events.jsonl` is built in Q1** (`sched/events.py`), not assumed.
   One JSON object per line: `{"t", "type", …}`. It also carries each
   finished job's size, cpus, start/end and CPU time, which is where
   core-hours (Q4) come from. Rotation: monthly files
   `events-YYYY-MM.jsonl`, `events.jsonl` a symlink to the current one.
7. **Registry writes go through one function**, `registry.update(name,
   fn, h)`: read, apply `fn`, validate, write-temp-rename, under a
   per-entry `O_EXCL` lock file with a 5 s wait. The board and the CLI can
   then change the same entry at once without losing either change.
   `_set_board` moves onto it.
8. **Pool limits on the local backend are bookkeeping only**: cores and
   memory are counted, not enforced (no cgroups). Enough for laptops and
   tests.
9. **Fake batch system first, real cluster second.** Every backend
   behaviour is tested against `tests/fakebatch/` before the live runs.
10. **Multi-user later, behind a front door** (scheduler.md §14). Q1
    builds the three things that keep it cheap: a required `by`
    principal (`<scheme>:<name>`) on every control, event and job record;
    pool limits lowered by an optional `sched/grant.toml`; one
    authorization function, `sched/authz.check`.

## 4. Layout of the new code

```
src/work_packet/sched/
  __init__.py
  config.py      [sched] loading, sizes, pool limits (Q1)
  classes.py     classes, effective class, aging (Q1)
  queue.py       due list + order: class, fair share, oldest; backfill (Q1)
  gates.py       the §6.2 gates, each returning a Reason or None (Q1, Q2)
  control.py     modes, hold, prio, size, next: the only writers (Q1)
  authz.py       check(principal, action, target): the one place for roles (Q1)
  jobs.py        job records $WPK_HOME/sched/jobs/, lost markers (Q1)
  events.py      events.jsonl (Q1)
  dispatcher.py  Dispatcher: fill, reap, adopt, run loop (Q1)
  explain.py     the queue with reasons, for wpk sched and /sched (Q1)
  budget.py      spend, pace, ceilings, estimates, reservations (Q2)
  backends/
    __init__.py  Backend, JobRef, JobState, get(cfg) (Q1)
    local.py     (Q1)
    slurm.py     (Q4)
    lsf.py       (Q6)
  home_lease.py  wpkd.lease in place of runner.lock's flock (Q4)
src/work_packet/dash/
  sched.py       /sched routes and data (Q3)
  templates/sched.html (Q3)
  sched.js       budget chart, queue refresh (Q3)
tests/
  test_sched_classes.py  test_sched_queue.py  test_sched_control.py
  test_sched_dispatch.py test_sched_budget.py test_sched_dash.py
  test_sched_slurm.py    test_sched_lsf.py    test_sched_ide.py
  test_sched_login.py
  fakebatch/  sbatch squeue sacct scancel bsub bjobs bkill  fakebatch.py
```

## 5. Test infrastructure

Built before the code that needs it.

- **T-a: Dispatcher under test (Q1).** `Dispatcher` takes `clock` and
  `backend` and exposes `pass_once()` (reap, then fill) so tests drive it
  step by step with `WPK_NOW`, no threads, no sleeps. The threaded `run()`
  is tested separately with a few real-time tests (each under 3 s).
- **T-b: A controllable local backend (Q1).** `FakeLocal` in
  `tests/conftest.py`: `submit` records the task and starts nothing until
  the test says `start(ref)` / `finish(ref, code)` / `lose(ref, why)`.
  Ordering, gates and accounting tests use it; the real `local` backend
  gets its own end-to-end tests with the fake model.
- **T-c: Fake model behaviours (Q1, Q2).** Add to
  `tests/fakemodel/behaviors/`: `sized` (writes `size: sim` in the
  memento on odd steps), `spender` (reports a cost given by
  `WPK_FAKE_COST`), `quota` (emits `rate_limit_event` readings given by
  `WPK_FAKE_QUOTA`). Check how `_step_cost` and `_add_quota` read the
  fake's stream before writing them.
- **T-d: Fake batch system (Q4, used again in Q5, Q6).**
  `tests/fakebatch/fakebatch.py` plus seven tiny wrappers named like the
  real commands. State in `$WPK_FAKEBATCH_DIR` (one JSON file per job).
  The backends find commands through `[sched.slurm] bin` / `[sched.lsf]
  bin` (a directory prefix, default empty = PATH), which tests point at
  `tests/fakebatch/`. Each job is run as a local process group once the
  fake "schedules" it. Knobs, per job name pattern, in
  `$WPK_FAKEBATCH_DIR/rules.json`: `pend_s`, `preempt_after_s`,
  `node_fail`, `submit_fails`, `timeout`, `exit`. `sacct`/`bjobs` report
  states, exit codes and `TotalCPU` in the real commands' formats (copy
  sample output from the cluster in Q0 into `tests/fakebatch/samples/`).
- **T-e: Fake IDE over TCP (Q5).** Extend `tests/fake_ide.py` to take
  `--host/--port 0/--connection-token-file`, write the bound port where
  the real job would, and refuse requests without the token.
- **T-f: Chrome render checks (Q3, Q5)** as in boards.md B7: headless
  Chrome at 1400 and 390 wide, no CSP errors, screenshots in the
  scratchpad, findings noted in the status log.

## 6. Milestones

### Q0: Spikes on the SLURM cluster (nothing kept)

Goal: know that the farm can do what §5.3 and §7.1 assume, before code
depends on it. Record every finding in the status log; copy sample
command output into `tests/fakebatch/samples/`.

- [ ] Q0.1 `sbatch --parsable`, `squeue --me -o`, `sacct -j … -o
      JobID,State,ExitCode,Start,End,TotalCPU -P`, `scancel --signal=TERM`
      from the login node; save the output formats.
- [ ] Q0.2 A packet on the shared FS: `wpk step` in a job with the fake
      model, then with Claude (route to the API, the login in the shared
      home); note `node_env` needed.
- [ ] Q0.3 Queue wait for a `look` (1 core) and a `sim` (8 cores, 32 GB)
      job at three times of day.
- [ ] Q0.4 Clock skew login ↔ nodes; `O_EXCL` create and `rename` on the
      shared FS from two hosts at once (a 20-line script).
- [ ] Q0.5 openvscode-server in a job, `--host 0.0.0.0 --port 0
      --connection-token-file`, reached from the login node with curl and
      a WebSocket; how the job reports its port.
- [ ] Q0.6 wpkd on the login node: `wpk dash --run` resident size and idle
      CPU over an hour; `ssh -L 7878:/path/wpkd.sock login` from the
      laptop to a unix-socket listener (a two-line uvicorn test); whether
      cron is allowed; whether the login nodes share `$WPK_HOME`;
      whether the site kills long-lived login processes.
- [ ] Q0.7 Decide from Q0.3 whether queue wait is small enough for one
      job per step (§5.1). If not, stop and revise the design (pilots).

Docs: status log only.

### Q1: Priorities, sizes, controls and the dispatcher (local backend)

Goal: wpkd schedules by class, fair share and size with the local
backend; Halt, Stop now, hold, priority, size and Run next work from the
CLI; the state survives restarts. No budget yet; no board UI yet.

Format and config:

- [x] Q1.1 `schema.py`: `SCHED_DEFAULTS`, `_validate_sched` (classes,
      sizes with `cpus` ≥ 1, `mem` as `<n>[KMGT]`, durations, backend
      name); allow `sched` in `validate_config`.
- [x] Q1.2 `sched/config.py`: `load(h)` with deep merge; `Size`
      dataclass (`name, cpus, mem_mb, time_s, partition, queue, extra`);
      `pool_limits(cfg, h, now)`, the lower of config and an unexpired
      `sched/grant.toml` (`cores`, `mem`, `jobs`, `budget.amount`, `by`,
      `expires`), read every pass; an expired grant falls back to config
      with a `grant_expired` event; `size(cfg, name)`.
- [x] Q1.3 Registry entry fields `priority`, `size`, `sched`
      (`run|hold`), `[packets.<wpid>]` with `priority`, `size`, `next`;
      `validate_registry_entry` checks them (class names, size names
      known to config are a warning, not an error, so a config change does
      not break entries). `registry.update(name, fn)` with the entry lock
      (decision 7); `_set_board` moved onto it.
- [x] Q1.4 `project.toml`: `sizes` (allowed list), `weight`,
      `max_cores`; through `LIMITS`/`Settings`/`settings()`/`known`/
      `SETTABLE` (list in §2), so `wpk set sizes=look,sim` works.
- [x] Q1.5 Memento `size:`: `MEMENTO_FIELDS`; type check in
      `validate_memento`; allowed-list check in `_validate_pending`
      (refused → the step fails validation like any bad memento, with a
      message naming the allowed sizes); `next_size` in `STATUS_FIELDS`
      and `_apply`.
- [x] Q1.6 Prompt: one line per allowed size (name, cpus, mem, limit) and
      how to ask for one, in `prompts/step.md` as `$sizes` (varies by
      project) via a new `build(sizes=…)` kwarg; omitted when the project
      allows only one size. Protocol text for `size:` in
      `prompts/protocol.md`.

Executor:

- [x] Q1.7 `step(target, force=False, lost=None)` and `wpk step --lost
      REASON`: `_recover` records `step-failed` with `counted: false` and
      leaves `attempts` alone; journal schema allows `counted`.

Scheduler core:

- [x] Q1.8 `sched/classes.py`: `CLASSES`, `effective(entry, wpid)`
      (override → project → `normal`), `aged(cls, waited_s, age_after)`
      (never above `high`).
- [x] Q1.9 `sched/queue.py`: `Item` (project, wpid, path, state, due,
      class, aged class, size, next); `build(entries, cfg, now)` from
      `scheduler.due()` plus registry and status reads; `order(items,
      usage)` = run-next first, then aged class, fair share by
      `cores_in_use / weight`, oldest due.
- [x] Q1.10 `sched/gates.py`: one function per §6.2 gate, in order, each
      returning `Reason(code, text, clears_at=None)` or None: `mode`,
      `project_hold`, `job_pending` (a job record for this packet),
      `project_cores`, `fits` (pool cores/mem/jobs), `spare_room`
      (background), `backfill` (head of line waited > `backfill_for`).
      Budget gates come in Q2.
- [x] Q1.11 `sched/jobs.py`: `JobRecord` (id, backend, ref, kind
      step|ide, project, wpid, step, class, size, cpus, mem_mb, submitted,
      started, estimate), `save/load/all/remove`; lost markers
      (decision 3).
- [x] Q1.12 `sched/events.py`: `append(type, **fields)`, monthly
      rotation, `read(since, types)`; event types `mode, prio, hold,
      size, submitted, started, finished, lost, pending_long, gate,
      backend_down, wpkd_start, wpkd_stop`.
- [x] Q1.13 `sched/backends/__init__.py`: `Backend` (§5.1), `JobRef`,
      `JobState`; `get(cfg)`. `local.py`: `Popen([python, -m,
      work_packet, step, path, (--lost R)], start_new_session=True)`,
      stderr to the job record's log; `poll` via `Popen.poll` and, for
      adopted jobs, PID liveness checked against the PID's start time
      (`procs._stat`); `cancel` = `killpg` TERM, KILL after 30 s;
      `list_ours` = records whose PID lives.
- [x] Q1.14 `sched/dispatcher.py`: `Dispatcher(home, cfg, backend,
      clock)`; `adopt()` at start (§5.4: records vs `list_ours`);
      `reap()` (finished → remove record, `finished` event, poke;
      lost/preempted → lost marker); `fill()` (build, order, gate, submit,
      record, `submitted` event; cancel pending jobs whose packet is no
      longer due); `pass_once()`; `run(stop)` loop waking on poke, job
      poll interval, next `wake_at`, 30 s fallback.
- [x] Q1.15 `sched/control.py`: `set_mode(mode, by, reason)` (writes
      `sched/control.toml`; `stop` also cancels jobs and writes lost
      markers), `hold/release(project)`, `set_prio(target, cls|None)`,
      `set_size(target, size|None)`, `run_next(wpid)`, each taking a
      required `by` principal, calling `authz.check(by, action, target)`
      first, returning an `executor.Outcome` and writing an event with
      `by`. `start_mode` honoured only when `control.toml` is missing.
- [x] Q1.15a Principals: `sched/authz.py` `principal_cli()` →
      `unix:<login>`, `principal_of(request)` → `tailscale:<login>` (or
      the Guard's other modes); `check()` allows any principal that
      passed the Guard and the home's Unix user, and raises `Denied`
      otherwise. Job records and `control.toml` store `by`.
- [x] Q1.16 `sched/explain.py`: `queue(h, now)` → ordered rows with
      class, aged, size, first failing gate and its text and
      `clears_at`; `pool(h)` → usage by size and kind.
- [x] Q1.17 `dash/runner.Runner` wraps `Dispatcher` (same public API;
      `busy` = jobs running, `last` from `finished` events). `wpk tick`
      = `Dispatcher(local).pass_once()` until idle, output unchanged.
- [x] Q1.18 Pause/take with a pending or running job: `act`'s pause
      path and `wpk pause` cancel a *pending* job for that packet;
      a running one finishes as today (the `.take-request` work stays
      with long-running.md L1).

CLI:

- [x] Q1.19 `wpk sched [--json]` (mode, pool use, queue with reasons),
      `wpk sched halt|stop|resume [-m WHY]`, `wpk sched hold|release
      <project>`, `wpk sched jobs`, `wpk prio <target> <class>|--clear|
      --next`, `wpk size <target> <size>|--clear`.

Tests (Q1):

- `test_sched_classes.py`: effective class order; aging steps and cap at
  `high`; `urgent` never passed by aged work.
- `test_sched_queue.py`: strict class order; fair share (project with 40
  due children vs one with 1, both get turns); weight; oldest first
  within a project; run next once, then cleared; backfill lets `look`
  past a waiting `sim`, stops after `backfill_for`, `sim` starts when
  cores free (no starvation over 50 simulated arrivals); spare room for
  background; pool cores/mem/jobs each the binding limit in turn;
  `max_cores` per project.
- `test_sched_control.py`: each control writes its file and event,
  both carrying `by`; a control without `by` is a `TypeError`; a
  principal `check()` refuses gets code 4 and changes nothing (patch
  `check` to deny); a grant lowers cores below config, a grant above
  config changes nothing, an expired grant falls back with one event;
  `registry.update` with two writers in threads loses neither change;
  `control.toml` missing → `run`, or `start_mode`; a bad class/size is
  refused with code 4.
- `test_sched_dispatch.py` (fake model, real local backend unless noted):
  a slot is refilled within 1 s of a step ending (threaded); drain: running
  step commits, nothing new starts; stop: running step killed, packet at
  its last commit, next attempt not counted (`attempts` unchanged,
  journal `counted: false`); halt survives a Dispatcher restart; a
  Dispatcher killed with a job running adopts it on start and does not
  start a second step; a pending job is cancelled when its packet is
  paused (FakeLocal); `size: sim` in a memento makes the next job `sim`
  and the one after the packet's default; a disallowed size fails
  validation with the allowed list in the message; `wpk tick` output and
  `test_tick.py` unchanged.
- Existing: `test_tick.py`, `test_dash.py`, `test_dash_tasks.py` pass
  unchanged (the Runner API is kept).

Docs (Q1): spec.md §2 (`sched/` directory, `events.jsonl` format,
`control.toml`, job records, lost markers, `grant.toml`, the principal
format), §2.1 (`[sched]`), §2.2
(registry fields), §3.1 (`sizes`, `weight`, `max_cores`), §4.1
(`next_size`), §4.2 (`size:`), §4.3 (`counted`); scheduler.md: fix §7's
"events … as now" (events.jsonl is new), note decisions 2–4 where they
change the design text; README command list (`wpk sched`, `wpk prio`,
`wpk size`); `wpk --help` texts.

### Q2: The budget

Goal: spending is paced by class against a dollar, token or quota budget;
per-project caps hold projects.

- [x] Q2.1 `sched/budget.py` `Spend`: period bounds (day/week/month in
      `tz`; for `quota`, from `resets_at`); `spent(h, now)` from
      `stats.collect(since=period_start)` + `token_figures` (`usd`,
      `tokens` with `cache_read_weight`), or `stats.latest_quota` (`quota`:
      7-day and 5-hour); cache in `sched/spend.json` keyed by period and
      the newest step's end, rebuilt when missing or older than the newest
      `meta.json`.
- [x] Q2.2 `pace(t)` with optional `shape` (per-weekday weights, per-hour
      weights); `ceiling(cls, t)` per §4.3; the 5-hour second test for
      `quota`.
- [x] Q2.3 Estimates (p75 of the packet's last 10 steps, else the
      project's last 20, else `default_step`; capped at `step_budget_usd`
      converted to the measure) and reservations held by the dispatcher
      per running job; rebuilt from job records by `adopt()`.
- [x] Q2.4 Gate `budget` in `gates.py` with `clears_at` (when pace
      reaches the needed spend, or the window reset); `gate` event the
      first time each class is gated in a period; `stale_after` rule.
- [x] Q2.5 Project caps: `budget_usd_per_day`, `budget_quota_per_week`,
      `max_steps_per_hour` in `LIMITS`; over a cap → `executor.admin`
      to `HELD`/`limit` (today `PAUSED` with `reason` naming the cap
      until L1 lands), figures in `reason`.
- [x] Q2.6 `wpk sched` and `explain` show spend, pace, each class's
      ceiling and which classes are gated.

Tests (Q2, `test_sched_budget.py`, fake clock + `spender`/`quota`
behaviours): period bounds across a DST change and month end; each
measure's `spent`; spend cache rebuilt after a new step; gates close in
order `background → low → normal → high` as spend passes the ceilings
and reopen at the period start; `urgent` runs to the hard cap and not past
it; estimates from history and the fallback; a restart rebuilds
reservations; 5-hour gate blocks while the 7-day one is open; stale quota
reading admits only `high`/`urgent`; a project over its daily cap goes
to held with the figures while other projects run.

Docs (Q2): spec.md §2.1 (`[sched.budget]`), §3.1 (caps); scheduler.md
status log; token-dashboard.md: a line that the scheduler reads the quota
readings described there.

### Q3: The board

Goal: everything Q1–Q2 can do from the CLI can be done and seen on the
board.

- [x] Q3.1 `dash/sched.py`: `GET /sched` (mode banner with who/when/why,
      pool use by size and kind, budget chart data, queue from
      `explain.queue`, recent `lost`/`pending_long`/`gate` events); `GET
      /sched.json` for live refresh.
- [x] Q3.2 POST `/sched/mode` (halt, stop with required reason and
      `data-confirm`, resume), `/p/<project>/prio`, `/p/<project>/size`,
      `/p/<project>/hold`, `/p/<project>/<wpid>/prio`, `…/size`, `…/next`;
      each `form → run_in_threadpool(control.x, by=authz.principal_of(request)) →
      back(…, poke_runner=True)`; a `Denied` is a 403.
- [x] Q3.3 `templates/sched.html`, `sched.js` (budget chart as inline
      SVG: spend line, pace line, one line per class ceiling,
      reservations shaded; no new vendored library), side-tab entry in
      `_side.html`, red mode banner in `base.html` when mode ≠ `run`.
- [x] Q3.4 Overview headline tiles: mode, cores used/total, spend vs pace
      (`dash/data.overview`).
- [x] Q3.5 Project page: class, size, hold, cores in use, spend vs caps,
      with selects and buttons. Card and packet page: effective class
      (aged/override), size, "waiting on …" line, Run next.
- [x] Q3.6 All packets: class, size and "waiting on" columns; checkbox per
      row and a bar for set class, set size, pause, resume, hold project
      (boards.md B8): one POST with a list of `project/wpid`, one outcome
      line per packet in the flash.
- [x] Q3.7 Live refresh: `/sched` and the "waiting on" lines refresh with
      the existing live mechanism (`live.js`).

Tests (Q3, `test_sched_dash.py`, TestClient): each POST has the same
effect as its CLI command (compare files and events), with `by` from the
request's identity; a POST through the
Guard without the token or with a foreign Origin is 403 (one test with the
Guard on, as server tests do); stop without a reason is refused; the
queue on `/sched` matches `wpk sched --json`; the banner shows on every
page when halted; bulk operation over three packets, one of them leased,
gives three outcome lines. T-f render check at 1400 and 390 wide.

Docs (Q3): scheduler.md §9 brought in line with what was built;
boards.md B8 ticked and pointed here; overview.md (new tiles).

### Q4: SLURM, and wpkd on a login node

Goal: a real project runs on the SLURM cluster for a week, steps sized by
task, with wpkd on the login node.

- [x] Q4.1 `backends/slurm.py`: `submit` (`sbatch --parsable -J
      wpk:<home-id>:<wpid>:<step> -t -c --mem [-p] [--account] [extra]
      -o <log> --wrap "<node_env> && wpk step <path> [--lost R]"`;
      `home-id` = 8 hex of the home path's hash); `poll` (one `squeue`
      for all live jobs, `sacct` for those that left the queue); `cancel`
      (`scancel`, `--signal=TERM` then plain after 30 s); `list_ours`
      (`squeue --me --name` prefix match).
- [x] Q4.2 State mapping per §5.5 (`TIMEOUT` counted; `PREEMPTED`,
      `NODE_FAIL`, admin cancel, unknown-after-`sacct` uncounted via lost
      marker); `max_pending` → `pending_long` event; submit backoff
      (30 s doubling to 10 min) with `backend_down` event and pool status.
- [x] Q4.3 Remote leases: the dispatcher treats a packet with a RUNNING
      job as busy whatever the lease says, and a lease from another host
      as live until its expiry or the job's end, whichever is first.
- [x] Q4.4 Job-state-driven rereads (no inotify across hosts); 30 s
      rescan fallback.
- [x] Q4.5 `finished` events carry `TotalCPU`; core-hours per size and
      project in `explain.pool` and on `/sched`; the low-CPU `sim` flag
      (CPU time < 20% of `cpus × wall`).
- [x] Q4.6 Login node (§7.1): `[server] listen = "unix"` (uvicorn on
      `$WPK_HOME/run/wpkd.sock`, dir 0700; the Guard treats the unix
      socket like loopback with the CSRF and Origin checks kept); `wpk
      url` prints the `ssh -L` line; `wpk serve [--detach] [--ensure]`
      (the S2 name from server.md, with logs in `$WPK_HOME/log/`);
      `home_lease.py` replaces the `flock` (host, PID, expiry, 30 s
      refresh, 90 s TTL; a second wpkd names the holder and exits).
- [x] Q4.7 `wpk doctor` checks: shared FS (packet path visible from a
      `look` job), `wpk` and `claude` on a node (a 1-minute probe job),
      clock skew > 5 s, other users on the host → suggest `listen =
      "unix"`.
- [ ] Q4.8 Live: one week of a real project (dv-solve or fw-uart16550)
      on the cluster, `look` and `sim` sizes, `quota` budget. Record queue
      wait, steps, sizes asked for vs CPU used, lost jobs, budget gating,
      and wpkd's resident size.

Tests (Q4, `test_sched_slurm.py` and `test_sched_login.py`, fake batch):
submit argv per size and with `extra`; a pending job holds pool room; a
job pending past `max_pending` raises one event; preempted and node-fail
jobs give an uncounted retry at the head of their class; timeout counts;
`submit_fails` backs off and recovers; a wpkd restart adopts running and
pending jobs and cancels one whose packet was paused meanwhile; a job
whose record was never written (crash after `sbatch`) is adopted from
`list_ours`; `sacct` sample formats from Q0 parse; core-hours sum; the
low-CPU flag. Login: unix listener refuses a TCP port when set; `--ensure`
twice starts one; a second wpkd on a "different host" (faked hostname)
sees the home lease and exits naming the holder; a stale home lease is
taken over.

Docs (Q4): new **`docs/sched-guide.md`**, the user guide: setting up a
pool on SLURM (config walk-through, sizes, `node_env`, `wpk doctor`,
running wpkd on a login node with cron and `ssh -L`, reading `/sched`,
what to do when Halt is needed); spec.md §2 (`wpkd.lease` replaces
`runner.lock`, `run/`, `log/`); server.md §5–§6 (`wpk serve`, `listen =
"unix"`, S2 status); long-running.md §4 and runner.md "The runner":
a pointer that scheduler.md supersedes the loop, limits and lock text;
README.

### Q5: An IDE in a slot

Goal: opening a packet's IDE on the board starts openvscode-server in a
job of the chosen size, proxied over TCP.

- [x] Q5.1 `dash/ide.py`: split `Backend` into a transport (`UnixEndpoint`
      as today; `TcpEndpoint(host, port, token)`) and a launcher (`LocalLaunch`
      as today; `JobLaunch` through `sched` backends). `client()`,
      `_connectable`, `proxy_ws` and stop/adopt go through the endpoint
      and launcher; the existing unix path keeps its tests green.
- [x] Q5.2 IDE tasks in the dispatcher: `kind = "ide"`, ahead of all agent
      work, never gated by budget, `[sched.ide] reserve` room, run limit;
      the job writes `host:port` to `servers/<key>/endpoint`; token file
      0600 made by wpkd; idle stop cancels the job and frees its room.
- [x] Q5.3 Board: size choice in the Open menu (`look` default); "waiting
      for room (first in line)" page that refreshes until the endpoint
      appears; `max_servers` counts IDE jobs.
- [ ] Q5.4 Live: open a packet IDE as `sim`, build and simulate in its
      terminal, from the laptop over `ssh -L` and from the iPad over the
      tailnet (needs server.md S1b).

Tests (Q5, `test_sched_ide.py`, fake batch + T-e): the IDE job jumps the
agent queue; waits when the pool is full and starts on the next free
room without preempting; `reserve` keeps room agents cannot use; the
proxy forwards HTTP and WebSocket with the token and the upstream refuses
without it; idle stop ends the job and an agent step takes the room; a
wpkd restart re-attaches to a running IDE job via its endpoint file; all
existing `test_ide.py` tests pass.

Docs (Q5): vscode-plan.md §4 (TCP endpoint, IDE in a job), scheduler.md
§8 brought in line; sched-guide.md IDE section.

### Q6: LSF

Goal: the same on the commercial LSF farm, with a `usd` or `tokens`
budget through the gateway.

- [ ] Q6.1 Q0.1–Q0.6 on the LSF farm (formats of `bsub`, `bjobs -o
      … -json`, `bkill`, `bhist`; sample output into
      `tests/fakebatch/samples/lsf/`; gateway route from a node).
- [x] Q6.2 `backends/lsf.py`: `bsub -J -W -n -R "rusage[mem=…]
      span[hosts=1]" [-q] [-P] [extra] -o`; `bjobs -a -J "wpk:<home-id>:*"
      -o "jobid stat exit_code start_time finish_time cpu_used" -json`;
      `bkill -s TERM` then `bkill`; state mapping (`EXIT` with
      `TERM_RUNLIMIT` counted; `TERM_PREEMPT`, `TERM_OWNER` by admin,
      `UNKWN`/`ZOMBI` uncounted).
- [x] Q6.3 Fake batch: the three LSF commands on the same engine.
- [ ] Q6.4 Live: a project on the farm for a few days with the gateway
      and a `usd` budget; DFM sub-jobs from a step, confirmed outside the
      pool's accounting.

Tests (Q6, `test_sched_lsf.py`): the Q4 backend test list run against
LSF (parametrise the shared cases over both backends in one module,
`test_sched_batch.py`, so the two cannot drift).

Docs (Q6): sched-guide.md LSF section (queue, project code, `node_env`
with the gateway variables, DFM note); spec.md `[sched.lsf]`.

## 7. Doc plan

| Doc | Changes | When |
|---|---|---|
| `docs/scheduler.md` | Design kept true to what is built: §7 events (new), decisions 2–4, §9 board, §8 IDE; status log per milestone | Q1–Q5 |
| `docs/scheduler-plan.md` | This file: ticks and status log | every task |
| `docs/spec.md` | §2 home files (`sched/`, `events.jsonl`, `control.toml`, `wpkd.lease`, `run/`, `log/`), §2.1 `[sched]`, §2.2 registry fields, §3.1 project limits, §4.1 `next_size`, §4.2 `size:`, §4.3 `counted` | Q1, Q2, Q4, Q6 |
| `docs/sched-guide.md` (new) | User guide: pool setup on SLURM and LSF, sizes, budget, login node, `/sched`, emergencies | Q4, Q5, Q6 |
| `docs/server.md` | `wpk serve`, `--detach`/`--ensure`, `listen = "unix"`; S2 status | Q4 |
| `docs/long-running.md`, `docs/runner.md` | Pointers: loop, limits and lock superseded by scheduler.md | Q4 |
| `docs/vscode-plan.md` | IDE over TCP in a job | Q5 |
| `docs/boards.md` | B8 done via Q3.6 | Q3 |
| `docs/overview.md` | Scheduler tiles | Q3 |
| `docs/token-dashboard.md` | The scheduler reads the quota readings | Q2 |
| `README.md` | Commands; doc list (`sched-guide.md`) | Q1, Q4 |
| Prompts | `prompts/protocol.md` (`size:`), `prompts/step.md` (`$sizes`) | Q1 |

## 8. Risks

| Risk | Watch for | Response |
|---|---|---|
| Queue wait on the cluster dominates step time | Q0.3, Q4.8 | Pilot-job backend behind the same interface (design §5.1) |
| Compute nodes cannot reach the model | Q0.2 | Proxy/gateway in `node_env`; else steps stay on the login node's host via `local` and only IDEs/sims go to jobs |
| Shared FS semantics (`O_EXCL`, rename, attribute caching delays seeing `status.md`) | Q0.4, Q4.8 | Reread after job end with a short retry; `actimeo` note in the guide |
| The model asks for `sim` without need | Q4.5 flag, Q4.8 | Allow only `look` for steps by default; people set `sim` |
| Login node kills wpkd | Q0.6 | `--ensure` from cron; else wpkd in a long job (design §13.6) |
| Registry entry write races between board and CLI | Q1 tests | `registry.update` lock (decision 7) |
| Runner API change breaks the board | Q1.17 | Keep `Runner`'s public API; existing dash tests unchanged |

## Status log

### 2026-10-26: plan

Written from `docs/scheduler.md` after a code survey. Survey findings
that shaped it: `events.jsonl` was only reserved, never written (built in
Q1.12); every unfinished attempt is counted, so "not counted" needs an
executor argument (decision 3); `tick(until_idle)` waits for a whole pass
(replaced by the dispatcher, Q1.14); the IDE backend assumes a local
child and a unix socket (split in Q5.1). Baseline test count: see the
next entry.

### 2026-10-26: baseline

Full suite on the uncommitted tree: 529 passed, 4 skipped (2 min 15 s).
One earlier run failed `tests/test_ide.py::test_web_proxy_websocket`
(`assert 1 == 0`); it passed on its own and in the next full run, so it
is flaky. Look at it before Q5.1 reworks that proxy, so a Q5 failure is
not blamed on the flake.

### 2026-10-26: multi-user later

Decided: wpkd stays per user; several users come later through a front
door over per-user daemons (scheduler.md §14). Added to Q1: decision 10,
grant-lowered pool limits in Q1.2, a required `by` and `authz.check` in
Q1.15, principals in Q1.15a, and their tests; `by` from the request in
Q3.2 and its tests.

### 2026-10-26: Q1 done (573 passed, 4 skipped)

Built: `src/work_packet/sched/` (config, classes, queue, gates, control,
authz, jobs, events, dispatcher, explain, backends/local); `wpk sched`,
`wpk prio`, `wpk size`, `wpk step --lost`; the memento's `size:` and
status `next_size`; `registry.update` with the entry lock; `Runner` and
`wpk tick` over the dispatcher. Tests: test_sched_classes (3),
test_sched_queue (13), test_sched_control (12), test_sched_dispatch (16);
every earlier test passes unchanged. Docs: spec.md §2, §2.1, §2.2, §2.4
(new: `sched/` files, events, principals), §3.1, §4.1, §4.2, §4.3;
scheduler.md §5.2, §5.5, §7; README.

Q0 is not done: this machine has no SLURM. Q1 does not need it; Q4.8, Q5.4
and Q6 live runs do.

Decisions and findings while building:

- **A disallowed `size:` is nudged, not failed.** The executor's existing
  nudge (one more turn when `.pending/` fails its check) gives the model
  the allowed list; only if it does not fix it does the attempt fail.
  Better than the plan's "fails validation".
- **Run next goes first of all classes**, as the plan said (the design
  said "head of its class"). The button means "next".
- **Backfill uses the head's wait since it became due**, not since it was
  first blocked: stateless, so `wpk sched` in another process shows the
  same queue as wpkd.
- **Stop now and SIGTERM**: `wpk step` turns SIGTERM into an unwinding
  exception (and ignores a second one), and `model.run` kills the model's
  own session on the way out, so a stopped step leaves no model running
  and its lease is released. The dispatcher sends SIGKILL 30 s later if
  the step is still there.
- **Cancels from another process**: a control run from the CLI marks the
  record and cancels through its own backend; the dispatcher also sends
  the cancel through its backend once (the local backend can only poll
  its own children).
- `jobs = 0` means `max_concurrent`, so an unconfigured home behaves as
  before; `cores = 0` and an empty `mem` mean no limit.

### 2026-10-26: Q2 done (590 passed, 4 skipped)

Built: `sched/budget.py` (ledger, periods, pace with `shape`, ceilings,
estimates, reservations, the quota windows, the gate with `clears_at`,
`gate` events, project caps); the caps `budget_usd_per_day`,
`budget_quota_per_week`, `max_steps_per_hour` in `LIMITS` and
`CONFIG_DEFAULTS`; `executor.admin(..., reason=)` for a cap's pause;
`wpk sched` budget lines. Tests: test_sched_budget (17). Docs: spec.md
§2.1 `[sched.budget]`, §2.4 `spend.json`, `gated.json`, §3.1 caps;
token-dashboard.md.

Decisions while building:

- **The spend cache is in memory, keyed by each `meta.json`'s mtime, size
  and inode**, not a `spend.json` rebuilt by rule: a pass stats every step
  file and parses only new ones. `sched/spend.json` is written each fill as
  a snapshot for readers.
- **A stale quota reading** admits only `high` and `urgent` while a step
  is running; with nothing running, one step of any class but `background`
  may start to take a fresh reading. Without that, a quiet week leaves
  normal work waiting for a reading only a step can take. No reading at
  all counts as stale.
- **Estimates are capped at the project's `step_budget_usd`** for `usd`
  only; tokens and quota have no per-step cap to convert.
- **Fake-model spend knobs are environment variables** (`WPK_FAKE_COST`,
  `WPK_FAKE_QUOTA`) on every behaviour, not separate `spender`/`quota`
  behaviours.
- **The gate uses the packet's own class**; aging only changes the order,
  as the design says.
- The caps can be set in `config.toml` too, as defaults for every project.

### 2026-10-26: Q3 done (599 passed, 4 skipped)

Built: `dash/sched.py` (snapshot, banner, packet/project info, tiles, the
budget chart), `templates/sched.html`, `_sched.html` (the project and
packet panels), `sched.js` (confirm, tick all); routes in `app.py`; the
banner in `base.html`; a Scheduler entry in the side tab; Overview tiles;
the "waiting on" line on Ready cards; All packets class, size and
waiting columns with the bulk bar (B8). Tests: test_sched_dash (9),
including one through the Guard (no token, foreign Origin, and a loopback
user who is not the home's owner are refused). Docs: scheduler.md §9,
boards.md B8, overview.md tiles.

T-f render check (headless Chrome over CDP, the pages at 1400 and an
emulated 390 wide): no horizontal overflow on /sched, /packets, the
project and packet pages, the Overview or a board; no CSP errors (one 404,
the favicon). `--window-size=390` alone does not narrow the layout in new
headless Chrome, which looked like overflow; the CDP script
(`Emulation.setDeviceMetricsOverride`) is the right check. Fixed from the
screenshots: Stop now wrapping in its button.

Decisions: the chart is server-side SVG (no `sched.js` chart); the queue
refreshes with the page's live swap, not a separate JSON poll; the class
lines show each class's ceiling and the room under it rather than
open/closed, which depends on the next step's estimate.

### 2026-10-26: Q4 built against the fake batch system (618 passed, 4 skipped)

Built: `tests/fakebatch/` (sbatch, squeue, sacct, scancel on one engine,
rules per job name: `pend_s`, `preempt_after_s`, `node_fail`,
`submit_fails`, `timeout_s`, `exit`; jobs run as process groups with the
submitter's environment); `sched/backends/slurm.py`; job-state mapping
(§5.5); finished events with the batch system's wall time and `TotalCPU`;
the low-CPU flag; core-hours on `/sched` and in `wpk sched --json`;
"backend down" on `/sched` and `wpk sched`; a lease from another host freed
when its job has ended (Q4.3); `sched/home_lease.py` (`wpkd.lease`) in
place of `runner.lock`; `[server] listen = "unix"`; `wpk serve
[--detach] [--ensure]`; `wpk url`'s ssh line; `wpk sched doctor` with a
probe job. Tests: test_sched_slurm (13), test_sched_login (6). Docs:
**docs/sched-guide.md** (new), spec.md §2, server.md §6 and status log,
long-running.md §4 and runner.md pointers, README.

Not done: **Q4.8**, the live week, and **Q0**, which it depends on. The
formats the backend parses (`squeue -o "%i|%T|%j"`, `sacct -X -n -P -o
JobID,State,ExitCode,Start,End,TotalCPU`, `sbatch --parsable`) are from
the SLURM documentation, not from the cluster: Q0.1 must check them, and
copy real output into `tests/fakebatch/samples/` for
`test_sacct_formats`.

Decisions while building:

- **`scancel --signal=TERM --full`** for a running step (the batch shell
  and its children get the TERM; `wpk step` unwinds and kills its model),
  plain `scancel` when that fails because the job is still pending, and
  plain `scancel` 30 s later as the hard kill.
- **A cancel the dispatcher did not ask for** (an admin's) is `LOST`,
  uncounted; one it asked for is not reported as lost again.
- **`OUT_OF_MEMORY` and `TIMEOUT` count**: they are the work's own doing,
  as a step timeout always was.
- **Wall time comes from the batch system** (`Start`, `End`) when it gives
  them, so core-hours are right even when wpkd polled late.
- **The home lease uses wall-clock time** (`clock.real_now`), never
  `WPK_NOW`, since it is compared between processes.
- With `listen = "unix"` the Guard accepts any port with a loopback Host
  name (the laptop's `-L` port), and keeps the Origin and CSRF checks.

### 2026-10-26: Q5 built (625 passed, 4 skipped)

Built: `sched/ide.py` (requests, endpoints, `[sched.ide] slot`),
`sched/ide_job.py` (the job's wrapper), IDE requests in the dispatcher
(first in line, the `ide_first` gate, the reserve, `run_limit`; not gated
by mode or budget; withdrawn when the job ends); `dash/ide.py`
`JobBackend` (TCP endpoint, the token as a cookie, the waiting page,
re-attach after a restart, idle stop cancels the job) with the proxy
going through `url()`, `headers()` and `ws_connect()` on either backend;
a size select in the Open menu; `tests/fake_ide.py` TCP mode with the
token (T-e). Tests: test_sched_ide (7); every test_ide.py test passes.
Docs: scheduler.md §8, vscode-plan.md §4.3a, sched-guide.md §7a.

The flaky `test_web_proxy_websocket` (baseline entry): `proxy_ws`
decremented the client count only after awaits in its `finally`, so a task
cancelled while cleaning up never lowered it. The decrement now comes
first. That fits the symptom (`clients` stuck at 1); five runs in a row
passed, but the flake was rare, so watch for it.

Not done: **Q5.4**, the live run on the cluster and from the iPad.

Decisions while building:

- **The port is chosen by the job's wrapper**, not `--port 0`: the server
  only prints the port it got, in a format Q0.5 was to find out; picking a
  free port and passing it has a tiny race and no parsing.
- **The design's "split into transport and launcher"** became one subclass,
  `JobBackend`, overriding where the server runs and how it is reached;
  the unix path is untouched.
- **A waiting IDE holds back every agent item**, not just those that would
  take its room: simpler, and the design's "first in line" says the same.

### 2026-10-26: Q6 built against the fake batch system (638 passed, 4 skipped)

Built: `sched/backends/lsf.py` (`bsub -J -W -n -R "rusage[mem] span[hosts=1]"
-q -P -o … bash -c`, one `bjobs -a -o … -json` per poll, `bkill -s TERM`
then `bkill`, the EXIT-reason mapping); `tests/fakebatch/lsf.py` (bsub,
bjobs, bkill on the same engine). The Q4 behaviour tests moved to
**test_sched_batch.py**, run for slurm and lsf (9 cases × 2);
test_sched_slurm.py keeps the sbatch command line, sacct parsing, the
low-CPU flag and the remote lease; test_sched_lsf.py has the bsub command
line and bjobs parsing (4). Docs: sched-guide.md §10, spec.md §2.1
`[sched.slurm]`, `[sched.lsf]`, `[sched.ide]`.

Not done: **Q6.1** (spikes on the LSF farm) and **Q6.4** (a live run with
the gateway and DFM sub-jobs).

Decisions while building:

- **`bjobs -o "…" -json`** rather than a delimiter: field names, not
  positions, and `ERROR` records for jobs bjobs no longer knows (those are
  LOST, uncounted, as on SLURM after `sacct` has nothing).
- **`bkill -s TERM`** is the soft cancel whatever the state (LSF kills a
  pending job it is signalled); plain `bkill` 30 s later.
- **`TERM_OWNER`** is a farm loss unless wpkd asked for the cancel, the
  same rule as SLURM's `CANCELLED by`.
- The times bjobs prints are local, with no year in the short form; they
  are read in this host's zone and this year.

## Summary of the build (2026-10-26)

| Milestone | State | Tests |
|---|---|---|
| Q0 spikes | waits for the cluster | - |
| Q1 priorities, sizes, controls, dispatcher | done | 44 |
| Q2 budget | done | 17 |
| Q3 board | done (render-checked at 1400 and 390 wide) | 9 |
| Q4 SLURM, login node | done against the fake; Q4.8 live waits | 13 + 6 + shared |
| Q5 IDE in a slot | done against the fakes; Q5.4 live waits | 7 |
| Q6 LSF | done against the fake; Q6.1, Q6.4 wait | 4 + shared 18 |

Suite: 529 tests before the build, 638 after. No earlier test was
changed; the fakes gained knobs (`WPK_FAKE_COST`, `WPK_FAKE_QUOTA`, the
`sized` behaviour, `fake_ide.py`'s TCP mode) and conftest a `FakeLocal`.
Nothing is committed.
