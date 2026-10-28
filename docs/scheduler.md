# The scheduler: slots, token budget and priorities in wpkd

Status (2026-10-26): built through Q6 against a fake batch system; the
live runs on the farms (Q0, Q4.8, Q5.4, Q6.1, Q6.4) are next.
`docs/scheduler-plan.md` tracks the build, with what changed from this
design in its status log; `docs/sched-guide.md` is the user guide. A fresh
session should be able to pick up from those files and this one. Read with
`docs/server.md` (wpkd), `docs/long-running.md` §1 and §4 (ownership, the
runner loop) and `docs/vscode-plan.md` §4 (web VS Code).

## 1. What we are adding

wpkd today serves the board and, with `--run`, runs `scheduler.tick()` in
a thread: every due packet, oldest first, as a local subprocess, `-j` at a
time (`dash/runner.py`, `scheduler.py`). That is enough for one person on
one machine. To be the front end for real development work, the server
must hand out two scarce things and let people steer it:

1. **Compute slots.** A fixed number of LSF slots (commercial) or SLURM
   slots (private), or local processes (laptop, tests). A step runs in a
   slot. So does a web IDE opened on a packet.
2. **A token budget.** Dollars or tokens per period on an API or gateway
   account (commercial), or the share of a subscription's 5-hour and
   weekly quota (private).
3. **Priorities and controls.** Every packet has a priority. People change
   it on the fly from the board, pause packets and projects, and in the
   worst case halt all agentic work at once.

The rules from runner.md still hold, and shape everything below:

- **Files are the source of truth.** Every setting and control (a halt, a
  priority, a pause) is in a file and survives a restart. What lives only
  in memory (reservations, the queue order) is rebuilt from files and the
  batch system on start.
- **The executor knows nothing about the scheduler.** `wpk step <path>`
  is still the unit of work. The scheduler only decides *when* and *where*
  it runs.
- **The board and the CLI share one code path.** Every control is a
  function in `sched/control.py`; the board's POST and the `wpk sched`
  command both call it.
- **A step is never cut short**, except by the emergency stop (§6.1).
  Priority changes take effect at step boundaries. Steps are minutes long,
  so that is soon enough, and it keeps the commit protocol simple.

## 2. Terms

| Term | Meaning |
|---|---|
| **Slot** | What one task runs in: one LSF/SLURM job, or one local process, of some size |
| **Size** | A named job shape: cores, memory, run limit, partition/queue. `look` = 1 core, `sim` = 8 cores and 32 GB (§5.2) |
| **Task** | What occupies a slot: an **agent step** (`wpk step`) or an **IDE session** (a VS Code server for one target) |
| **Pool** | What one wpkd may use at once: cores, memory and jobs, and the budget, from `[sched]` in `config.toml`. One pool per user |
| **Backend** | How a task gets a slot: `local`, `slurm` or `lsf` (§5) |
| **Class** | A packet's priority level, one of five (§3) |
| **Pace** | The share of the period's budget that "should" be spent by now, if spending were even (§4.2) |

## 3. Priorities

### 3.1 Five classes

| Class | Value | Meant for | Budget gate (§4.3) |
|---|---|---|---|
| `urgent` | 0 | "needed today", unblocking someone | Runs until the hard cap |
| `high` | 1 | Current focus | Runs until 95% of the period's budget |
| `normal` | 2 | The default | Runs while spend is at most pace + slack |
| `low` | 3 | Can wait a day | Runs while spend is at most pace |
| `background` | 4 | Use spare capacity only | Runs while spend is below pace − slack, and only with a free slot to spare (§3.3) |

Named classes rather than free integers: they are easy to read on a card,
easy to say in a meeting, and each one has a clear budget rule. Five is
enough; more would just be argued about.

### 3.2 Where a priority comes from

The effective class of a packet is the first of:

1. a **per-packet override**, set from the board or `wpk prio <wpid>`;
2. the **project's class**, in its registry entry;
3. `normal`.

Children inherit the project's class unless they have their own override.
Both live in the project's registry entry,
`$WPK_HOME/projects/<name>.toml`, next to `board` (boards.md):

```toml
name = "fw-uart16550"
path = "/home/mballance/projects/fw-uart16550"
board = "featherweight"
priority = "high"          # the project's class
sched = "run"              # run | hold: hold = the scheduler starts nothing in this project

[packets.7Q2M4K]           # per-packet scheduling settings
priority = "urgent"
```

Why there and not in the packet: a priority is a fact about this pool,
not about the work. The packet is owned by the runner while it runs, so
the board must not write into it, and the registry entry is already the
one small file per project that this home owns. One rewrite of one file
changes a priority, as with boards.

**Run next** is a one-shot bump: `next = true` on the packet's entry puts
it at the head of its class for one step, then the scheduler clears it.

### 3.3 Order

Each time a slot frees, or something is poked (§7), the scheduler picks
from the due packets (RUNNABLE, SLEEPING past `wake_at`, later WAITING
with its event) that pass every gate in §6.2:

1. **Lowest class first.** Strict: a `high` packet always goes before a
   `normal` one. Starvation of lower classes is the point of a class; the
   budget gates (§4.3) and aging (below) keep it from lasting.
2. **Within a class, fair share by project.** The project with the fewest
   cores in use, divided by its `weight` (default 1), goes next. A project
   with forty runnable children cannot crowd out one with a single packet.
3. **Within a project, oldest due first**, as today.

**Aging.** A packet that has waited more than `[sched] age_after`
(default 4 h) moves up one class for ordering (not for its budget gate),
and one more for each further `age_after`, up to `high`. So `low` work
that was due this morning gets a turn by afternoon without anyone touching
it, but never pushes `urgent` aside.

**Sizes and backfill.** Tasks have different sizes (§5.2), so "a slot is
free" means "the pool has the cores and memory for this task". When the
first task in line does not fit, smaller tasks behind it may start
(backfill), so eight `look` steps are not kept waiting by one `sim` step.
But once the first task has waited `[sched] backfill_for` (default 10 min),
backfill stops until it fits: the cores free up as steps end, and the big
task gets them. Without that rule a `sim` step would never find 8 cores
free while `look` steps keep arriving.

**Background keeps room spare.** A `background` packet starts only if the
pool could still start one task of `[sched] spare_size` (default `look`)
after it. That room is what an IDE or a newly urgent packet takes without
waiting for a step to end.

## 4. The token budget

### 4.1 What is measured

`[sched.budget] measure` picks one:

| Measure | Account | Spent so far comes from | Period |
|---|---|---|---|
| `usd` | API key, gateway, Bedrock/Vertex | `meta.json` `cost_usd` of every step in the period, across all projects of this home | `day`, `week` or `month`, in `[sched] tz` |
| `tokens` | Gateway that meters tokens, not dollars | `meta.json` token counts (input + output; cache reads weighted by `cache_read_weight`, default 0.1) | as above |
| `quota` | Claude Pro/Max subscription | the newest `rate_limit_event` reading (token-dashboard.md, "Subscription quota"): `seven_day.utilization` against `amount`, and `five_hour.utilization` as a second gate | the window itself, ending at `resetsAt` |

With `quota`, the reading is for the whole account, so your own use of
Claude outside work-packet counts too. That is right: the quota is shared,
and the scheduler should leave you room. `amount` is then the share of the
week work-packet may take (say 0.6), not 1.0.

Spend is read from `meta.json`, never estimated, as runner.md says. A
small cache (`$WPK_HOME/sched/spend.json`, thrown away and rebuilt when in
doubt) keeps the pass from rereading every step.

### 4.2 Pace

`pace(t) = amount × (elapsed / period)`. At 15:00 on a day with a $40
daily budget, pace is $25. `slack` (default 10% of `amount`) is how far
ahead of pace `normal` work may get. An optional `[sched.budget] shape`
gives a weekly or daily profile instead of a straight line (for example,
weekdays only, or more spend during working hours, when someone is there
to answer questions).

### 4.3 Gates by class

A packet of class *c* may start only if

    spent + reserved + estimate  ≤  ceiling(c, t)

| Class | `ceiling(c, t)` |
|---|---|
| `urgent` | `hard_cap` (default `amount`; may be set above it, for "spend from next period") |
| `high` | 0.95 × `amount` |
| `normal` | `pace(t) + slack` |
| `low` | `pace(t)` |
| `background` | `pace(t) − slack` |

With `quota`, the 5-hour window adds a second test with the same shape
(pace over five hours), so a burst of `high` steps cannot use up the
5-hour window and leave you locked out of interactive Claude for hours.

The effect, in words: if you are behind pace, everything runs; as spend
catches up with pace, background stops, then low, then normal; near the
end of the budget only high and urgent work runs; at the hard cap only an
explicit raise of the cap lets anything run. Because gates are in terms of
pace, an early-morning burst does not starve the evening.

### 4.4 Estimates and reservations

The cost of a step is not known until it ends. So when a step starts, the
scheduler **reserves** an estimate and replaces it with the actual figure
when `meta.json` is written:

- estimate = the 75th percentile of that packet's last 10 steps; else of
  the project's last 20; else `[sched.budget] default_step` ($0.50 or the
  token/quota equivalent);
- capped at the project's `step_budget_usd`, which the harness already
  enforces per step (`executor.py`, `budget_usd`), so a step can never
  overrun its reservation by much.

Reservations live in memory. After a restart they are rebuilt from the
running tasks (§5.4), each with a fresh estimate. Nothing is lost if they
are a little off: they only decide whether the *next* step starts.

### 4.5 Project caps

Per-project limits from long-running.md §4 stay as they are and apply on
top of the pool: `budget_usd_per_day` (and `budget_quota_per_week`, new)
per project, `max_steps_per_hour` per packet, and new `max_cores` per
project. A project over its own cap is held as `HELD`/`limit` and goes to
**Needs you**, because someone has to decide. A packet held back only by
the pool's gates just waits in the queue, with the reason shown (§6.3):
nothing is wrong with it.

## 5. Slots and backends

### 5.1 The backend interface

```python
class Backend:
    def submit(self, task) -> JobRef           # ask for a slot and start task in it
    def poll(self, refs) -> dict[JobRef, JobState]  # PENDING | RUNNING | DONE(code) | LOST(reason)
    def cancel(self, ref, hard=False)          # pending: withdraw; running: SIGTERM, then SIGKILL
    def list_ours(self) -> list[JobRef]        # every job this pool has in the batch system
```

| Backend | `submit` | `poll` | `cancel` | `list_ours` |
|---|---|---|---|---|
| `local` | `Popen(wpk step …)`, its own session | `poll()` | `killpg` | job files whose PID lives |
| `slurm` | `sbatch --parsable -J wpk:<home>:<wpid>:<step> -t <time> -c <cpus> --mem <mem> [extra] --wrap "wpk step <path>"` | `squeue`, then `sacct` for finished jobs | `scancel [--signal=TERM]` | `squeue --me --name …` |
| `lsf` | `bsub -J wpk:<home>:<wpid>:<step> -W <time> -n <cpus> -R "rusage[mem=<mem>]" [extra] wpk step <path>` | `bjobs -a -o …` | `bkill [-s TERM]` | `bjobs -J "wpk:<home>:*"` |

**One job per step.** A slot is held from submission until the job ends,
including while it is pending in the batch queue: the pool's limits are
a promise to the farm, so pending jobs count against them. The job's size
(§5.2) gives its cores, memory and limits; the account/project code and
other flags common to every job come from `[sched.slurm]` / `[sched.lsf]`.

Why one job per step and not long-lived pilot jobs that pull work: it is
the simplest thing that fits how `wpk step` already works, it gives honest
accounting to the farm's admins, and most farms frown on idle held slots
and cap job run time anyway. If queue wait turns out to dominate step time
(measure it in Q0), pilots can be added as a fourth backend later with the
same interface.

### 5.2 Job sizes

Different tasks need different jobs. Looking around a repository, planning
or reviewing needs one core; running a simulation regression needs eight
cores (half a server) and 32 GB. A **size** is a named job shape in
`config.toml`:

```toml
[sched.sizes.look]
cpus = 1
mem  = "4G"

[sched.sizes.sim]
cpus = 8
mem  = "32G"
time = "4h"                  # run limit; default: the project's step_timeout
partition = "batch"          # slurm; `queue` for lsf
extra = []                   # more sbatch/bsub arguments for this size
```

The pool counts what its tasks hold: `[sched] cores`, `mem` and `jobs`
are its limits, and a task starts only if its size fits under all three
(pending jobs included). So with `cores = 32`, two `sim` steps and sixteen
`look` steps can run at once, or four `sim` steps.

**Which size a task gets**, the first of:

1. **For the next step only**: `size:` in the memento. The step before
   knows best what the next one will do ("next: run the regression"). It
   must be one of the project's `sizes` (below); any other name is
   refused like any bad memento: the model is nudged once with the allowed
   list, and if it does not fix it the attempt fails. A committed `size:`
   is kept as `next_size` in `status.md`, which the next commit replaces,
   so it holds for one step without any clearing code (plan decision 4).
2. **The packet's size**, set on the board (Compose, New task, the packet
   page) or with `wpk size <wpid> <size>`; kept in the registry entry's
   `[packets.<wpid>]` next to `priority` (§3.2).
3. **The project's `size`**, in its registry entry.
4. `[sched] default_size` (`look`).

An IDE asks for a size when it is opened (§8): `look` by default, `sim`
when you mean to build and simulate in its terminals.

Each project lists the sizes its steps may ask for (`sizes = ["look",
"sim"]` in `project.toml`, default `[default_size]`). That is the guard on
a model that asks for a big job every time: the person decides what a
project may use, the model only chooses among it. The prompt lists the
allowed sizes with their cores and memory, so the model knows what it is
choosing.

**Size does not change priority**: a `sim` step and a `look` step of the
same class are ordered the same way (§3.3); only backfill treats them
differently. Spend per step is still what the budget measures (§4), not
cores. A `sim` step that spends most of its time waiting on the model
holds 8 cores it does not use, so the board shows core-hours per size and
per project, and flags a `sim` step that used little CPU (`sacct`
`TotalCPU`), so you can tell the model to use `look` until it actually
runs something.

**Sub-jobs are outside the pool.** On LSF, a step may start its own jobs
through DFM (a regression farmed out to many slots). Those are DFM's and
the farm's business, not work-packet's: they do not count against the
pool, and the step's own job stays small. Locally, without DFM, a step
does its work in its own job, which is why it needs a `sim` size.

### 5.3 What a compute node needs

All checked in Q0, on both farms, before anything else is built:

- **The packets on a shared file system**, at the same path on wpkd's host
  and on every node. Projects already live "in any directory"; on a farm
  that directory must be on NFS/GPFS. `wpk doctor` checks it.
- **`wpk` and `claude` on the node**: the same install, on the shared
  file system, or through `[sched] node_env` (a module load or a
  venv activate line put in front of the command).
- **A route to the model**: compute nodes often have no internet. The
  commercial case likely needs a gateway or proxy (`ANTHROPIC_BASE_URL`,
  `HTTPS_PROXY`, Bedrock/Vertex) passed through `node_env`.
- **Credentials**: an API key or gateway token readable only by the user
  (a 0600 file, not on the command line); for the subscription, the
  Claude Code login in the shared home.
- **Clocks** within a few seconds of wpkd's host: leases compare
  `expires` across hosts. `lease.is_stale` can only check the PID on its
  own host (`lease.py`), so for remote steps the scheduler trusts the
  batch system's job state first and lease expiry second.
- **Atomic create on the shared file system** (`O_EXCL` for `.lease`,
  `rename` for commits). Fine on NFSv4 and GPFS; NFSv3 needs checking.

### 5.4 Job records and restart

Each submitted task gets `$WPK_HOME/sched/jobs/<id>.json`: backend, job
ID, kind (step or IDE), project, WPID, step, class, submitted and started
times, estimate. It is removed when the job is reaped. On start, wpkd:

1. reads every job record and asks the backend for each one's state;
2. asks the backend for `list_ours()`, and adopts any job with our name
   but no record (a crash between `sbatch` and writing the record), or
   cancels it if its packet is no longer runnable;
3. rebuilds slot use and reservations from what is pending or running.

A job that is pending when its packet stops being runnable (taken back,
paused, held) is cancelled. One that starts anyway is harmless: the
executor refuses a packet that is not runnable or has a live lease, and
exits without spending anything.

### 5.5 When the farm ends a job

| Seen as | Cause | Counted as a failed attempt? |
|---|---|---|
| `TIMEOUT` / `TERM_RUNLIMIT` | Over `step_timeout` | Yes, as today's step timeout |
| `PREEMPTED`, `NODE_FAIL`, `TERM_OWNER` by admin, `LOST` | The farm, not the work | No: retried at the head of its class |
| Pending longer than `[sched] max_pending` | Farm busy | No: shown on the board; the slot stays held |
| `sbatch`/`bsub` fails or times out | Scheduler unreachable | No: back off (30 s doubling to 10 min), the pool shows "backend down" |

The executor's P1 retry rules decide what happens to the packet. The
scheduler only has to tell it whether the attempt counts: it keeps a lost
marker (`sched/lost/<wpid>.json`) and launches the packet's next step as
`wpk step <path> --lost REASON`, which records the unfinished attempt with
`counted: false` and leaves `attempts` alone (plan decision 3). A step
killed while wpkd is not running is counted, as before.

## 6. Controls

### 6.1 Pool modes

`$WPK_HOME/sched/control.toml`, written by every mode change and read on
start, so a halt survives a wpkd restart or a crash:

```toml
mode = "run"            # run | drain | stop
by = "matt.ballance@gmail.com"
at = 2026-10-26T14:02:00Z
reason = "gateway bill looks wrong"
```

| Mode | Starts new steps | Running steps | IDE sessions |
|---|---|---|---|
| **run** | yes | run on | open as usual |
| **drain** ("Halt") | no | finish and commit | open as usual |
| **stop** ("Stop now") | no | pending jobs cancelled; running ones get SIGTERM, then SIGKILL after 30 s; **not** counted as failed attempts | stay open |

Drain is the normal halt: nothing is lost and nothing half-done is left.
Stop is for "something is spending money it should not": a killed step
leaves its packet at the last commit (the commit protocol guarantees it)
and its next attempt starts clean. Both stop only agent work; IDEs are
people working, and are closed one by one if needed.

A missing `control.toml` means `run`. `[sched] start_mode = "drain"` makes
a fresh home start halted, for a first look at a new farm.

### 6.2 What can hold a packet back

Every gate the scheduler applies, in the order it checks them. The first
that fails is the reason shown for the packet (§6.3).

| Gate | Set by | Effect |
|---|---|---|
| Pool mode not `run` | Halt / Stop | Nothing starts |
| Project `sched = "hold"` | Project page, `wpk sched hold <project>` | Nothing in the project starts; packets keep their state and owner |
| Packet not due | Its state (`PAUSED`, `HELD`, `SLEEPING` before `wake_at`, …) | — |
| Live lease or pending job | A step already running | — |
| Project caps (§4.5) | `project.toml` | Moves to `HELD`/`limit` |
| Budget gate for its class (§4.3) | `[sched.budget]` | Waits; shown with when it will clear |
| No room for its size (or the spare-room or backfill rule) | `[sched] cores`/`mem`/`jobs`, project `max_cores` | Waits |

**Pause a packet** is the existing `wpk pause` (`PAUSED`, taking the
lease), and becomes `HELD`/`taken` when L1 lands. While a step runs it is
a request carried out at the end of the step (long-running.md §1, the
`.take-request`), and any pending job for it is cancelled. **Hold a
project** is lighter: it changes nothing in any packet, only whether the
scheduler starts anything there, so it is the right control for "not this
week" without taking ownership of every packet in a tree.

### 6.3 Every waiting packet says why

The queue view lists every due packet in the order it would start, with
its class (and aged class), the gate holding it, and when that gate is
likely to clear: "budget: normal resumes when pace reaches $31 (~16:40)",
"slot: 3rd in line, next slot free in ~4 min (est.)", "project on hold by
matt, 2 h ago". A scheduler you cannot see into is one people work
around; this list is what makes priorities trustworthy.

### 6.4 Commands

| Command | Does |
|---|---|
| `wpk sched` | Pool mode, cores, memory and jobs in use (steps, IDEs, pending; by size), budget against pace, the queue with reasons |
| `wpk sched halt [-m WHY]` / `stop [-m WHY]` / `resume` | Pool modes (§6.1) |
| `wpk sched hold <project>` / `release <project>` | Project hold |
| `wpk prio <project\|wpid> <class>` / `wpk prio <wpid> --clear` | Set or clear a priority |
| `wpk prio <wpid> --next` | Run next, once |
| `wpk size <project\|wpid> <size>` / `wpk size <wpid> --clear` | Set or clear a default job size (§5.2) |
| `wpk pause` / `resume` / `wake` | As today and in long-running.md |
| `wpk sched jobs` | Each job record with its backend state |

## 7. The dispatcher in wpkd

`scheduler.tick(until_idle=True)` waits for a whole pass before it starts
anything new, which wastes slots once steps run for minutes in a batch
queue. It is replaced by an event-driven dispatcher on its own thread in
wpkd (`sched/dispatcher.py`; a thread, not the asyncio loop, because
backend calls such as `sbatch` block, and the board's loop must not; plan
decision 2):

```
events ──► queue (rebuilt) ──► gates ──► backend.submit ──► job record
  ▲                                                            │
  └─── poke (board/CLI action), job state change, wake_at, ────┘
       budget reading, every 30 s fallback
```

- **Fill on every event.** Whenever something changes, rebuild the due
  list (cheap: tens of projects, cached `status.md` reads), order it
  (§3.3), and submit while a slot and the gates allow.
- **Poll the backend** every `[sched] poll` (local: 1 s; batch: 15 s;
  `squeue`/`bjobs` are rate-limited politely, one call for all jobs).
- **Events** go to `events.jsonl` (new: until now it was only reserved in spec §2), including `submitted`, `started`,
  `pending_long`, `lost`, `gate` (first time a class is gated in a
  period), `mode`, `prio`. The board's live view reads them.
- `wpk tick` stays: one synchronous pass with the local backend, for
  tests and cron. It goes through the same dispatcher, so the pool's mode,
  holds, classes and sizes apply to it too.

### 7.1 On a login node

wpkd should be able to run on a farm's login node, next to `sbatch` and
`bsub`, with no VM of its own. A login node is shared with other people,
often has no systemd user session, and is watched for heavy processes.
So:

- **Light.** One Python process; target under 300 MB resident and near
  zero CPU when idle. No model calls, builds, editors or simulations run
  on it: with a batch backend, steps and IDEs run in jobs. One `squeue`/
  `bjobs` call every `poll` for all jobs, not one per job.
- **No file watches across hosts.** inotify does not see writes that
  other hosts make over NFS, and steps now write from compute nodes. The
  dispatcher learns that a step ended from the backend's job state, then
  rereads that packet; the 30 s rescan is the fallback.
- **Not reachable by other users.** Today's loopback listener has no
  identity check (server.md §3), which on a shared host means any user on
  the node could drive your board, and its shell runs as you. On a shared
  host, wpkd listens on a **unix socket** in a 0700 directory instead
  (`$WPK_HOME/run/wpkd.sock`), and you reach it with `ssh -L
  7878:/path/to/wpkd.sock login-node`. OpenSSH forwards to unix sockets,
  so this needs nothing on the farm. `[server] listen = "unix"` (the
  default when `wpk doctor` finds other users logged in) refuses to open a
  TCP loopback port.
- **No systemd.** `wpk serve --detach` forks, writes its PID and host to
  `server.json`, and logs to `$WPK_HOME/log/wpkd.log` (rotated).
  `wpk serve --ensure` starts it only if it is not running, so a crontab
  line (`*/10 * * * * wpk serve --ensure`) restarts it after a reboot or
  a cleanup, where the site allows cron. With systemd, `--install-unit` as
  server.md says.
- **More than one login node.** `$WPK_HOME` is usually in a shared home,
  and `flock` on NFS is not reliable across hosts. `runner.lock` becomes
  a lease, like a packet's (`$WPK_HOME/wpkd.lease`: host, PID, expiry,
  refreshed every 30 s): a second wpkd on another login node sees a live
  lease, names the host it is on, and exits. `wpk url` and the ssh line
  it prints use that host.
- **The browser shell** runs on the login node, as an ssh session there
  would, for small things. Builds and simulations belong in an IDE's
  terminal in a `sim` job (§8), or later a shell in a job.

## 8. An IDE on a packet takes a slot

vscode-plan.md §4 runs one VS Code server per target, on wpkd's host,
reached through a unix socket. With a batch backend, the editor (and its
terminals, where people build and simulate) should run on a compute node,
in a slot, like the agent:

- **Opening** a target submits an IDE task: `openvscode-server` (the
  backend that suits sharing, vscode-plan §4.4) with `--host 0.0.0.0
  --port 0` and `--connection-token-file` (0600, made by wpkd), as a job
  of the size you pick in the Open menu (`look` by default, `sim` to build
  and simulate in its terminals), with `[sched.ide] run_limit` (default
  8 h). The job writes
  `host:port` to `$WPK_HOME/ide/servers/<key>/endpoint` when it listens.
- **The proxy** (`dash/ide.py`) gains a TCP transport: same paths, same
  Guard, plus the connection token on the upstream request. A unix socket
  cannot cross hosts, and the TCP port on a shared node is open to other
  farm users, so the token is required, not optional.
- **Priority.** An IDE request goes ahead of all agent work: it takes the
  next free slot. If none is free, the board says "waiting for a slot
  (next free in ~N min)" and the request holds first place in line;
  `[sched.ide] reserve` (default none) keeps room for one IDE of that
  size that agents never use. An IDE never preempts a running step.
- **Budget.** An IDE uses no model tokens of ours, so no budget gate.
- **Release.** `[ide] idle_minutes` with no open WebSocket ends the job
  and frees the slot, as the lifecycle already does for local servers.
  `max_servers` becomes "at most this many IDE jobs".
- **Local backend**: unchanged, the unix socket on wpkd's host.

As built (Q5): `[sched.ide] slot` turns it on (default: on with a batch
backend, off with `local`, where it can also be switched on). The board's
request is `$WPK_HOME/sched/ide/<key>.json`; the job runs
`python -m work_packet.sched.ide_job`, which picks a free port (rather
than `--port 0`, whose port the server only prints), starts the server
with `--host 0.0.0.0 --port N --connection-token-file`, and writes
`endpoint` once it listens. The proxy adds the token as the `vscode-tkn`
cookie; the browser never sees it. While a request waits for room, every
agent item waits behind it ("an IDE is waiting for room, and goes
first"), and the page answers 503 with a 5 s refresh. IDE jobs are not
stopped by Halt or Stop now (people are working in them), only by idling
out, `run_limit` or the farm; when one ends its request is withdrawn, so
it starts again only when someone opens it. A board restart re-attaches
through the job record and the endpoint file.

The browser shell (`dash/shells.py`) stays on wpkd's host for now: it is
for setup and small checks. A shell in a slot (`srun --pty` / `bsub -Is`
behind the same WebSocket) can come later.

## 9. The board

A **Scheduler** entry in the side tab (`/sched`), and controls where
people already look:

| Where | Shows | Actions |
|---|---|---|
| `/sched` | Pool mode, who set it and why; use against the pool by size: running steps, IDEs, pending (with wait), free cores and memory; core-hours per size and project; the budget chart (spend, pace, the class ceilings as lines, reservations shaded); the queue in order with reasons (§6.3); recent `lost`/`pending_long` events | **Halt**, **Stop now** (confirm, typed reason), **Resume** |
| Overview headline | Mode (red banner when not `run`), cores used/total, budget against pace | Link to `/sched` |
| Project page | Class, hold state, cores in use, spend against its caps | Class select, size select, **Hold** / **Release** |
| Card, packet page | Effective class (with "aged" or "override"), why it waits | Class select, size select, **Run next**, **Pause** / **Resume**, **Wake now** |
| All packets | Class and "waiting on" columns, sortable | Bulk: set class, pause, resume, hold project (completes boards.md B8) |

Every action is a POST behind the Guard and CSRF token, calls the same
`sched/control.py` function as the CLI, writes the file, and pokes the
dispatcher. The flash says what changed.

As built (Q3): `GET /sched` and `/sched.json` (the same data as `wpk sched
--json`); `POST /sched/mode` (`mode` = halt, stop, resume; `reason`, which
Stop needs); `POST /p/<project>/prio|size|hold` and
`/p/<project>/<wpid>/prio|size|next` (field `value`; empty clears; hold
takes `value=release`); `POST /packets/bulk` (`op` = pause, resume, hold,
prio, size; `value`; a `pick` per `project/wpid`). The requester's
principal (`authz.principal_of`) is the `by` of each change, and a
principal `authz.check` refuses gets a 403. The mode banner is inside
`<main>`, so the live refresh keeps it current; the budget chart is an SVG
drawn on the server, like the token charts, so no new script or library.
Not built: core-hours per size (Q4.5, with `sacct`), "Wake now" (the
packet page's note box already wakes a sleeping packet).

Who may do what is the same as today: the node owner (server.md §2). With
a shared board later, Halt and pool settings would be for an admin role
and class changes for project members; that is part of open question 1.

## 10. Config

```toml
[sched]
backend     = "slurm"        # local | slurm | lsf
cores       = 32             # pool limits; every task's size counts, pending included
mem         = "128G"
jobs        = 24
default_size = "look"
spare_size  = "look"         # background leaves room for one of these
backfill_for = "10m"
age_after   = "4h"
max_pending = "30m"          # flag a job pending longer than this
tz          = ""             # empty = the host's time zone
start_mode  = "run"          # run | drain
node_env    = "source /proj/tools/wpk/env.sh"

[sched.budget]
measure  = "quota"           # usd | tokens | quota
amount   = 0.6               # usd: dollars; tokens: tokens; quota: share of the window
period   = "week"            # day | week | month (ignored for quota)
slack    = 0.1               # share of amount
hard_cap = 0.6
default_step = 0.005         # same unit as amount

[sched.sizes.look]
cpus = 1
mem  = "4G"

[sched.sizes.sim]
cpus = 8
mem  = "32G"
time = "4h"

[sched.slurm]                # flags common to every job
partition = "batch"
account   = "dv"
extra     = []

[sched.lsf]
queue   = "normal"
project = "dv-agents"
extra   = []

[sched.ide]
reserve   = "look"           # room agents never use; "" for none
run_limit = "8h"

[server]
listen = "unix"              # unix | loopback | tailnet (§7.1)
```

Per project (`project.toml`): `max_cores`, `weight`, `budget_usd_per_day`,
`budget_quota_per_week`, `sizes` (allowed), and `[slurm]` / `[lsf]`
overrides of the common flags. The project's default `size` is in its
registry entry, with its priority. Pool settings change by `wpk set --pool …` or the `/sched` page and
take effect on the next dispatch.

## 11. Failure cases

| Case | What happens |
|---|---|
| wpkd killed with jobs pending and running | Jobs carry on; on start, §5.4 adopts them. Nothing runs twice: the lease and the state check stop a second step |
| Batch system down | Submits back off; running jobs are polled again later; board shows "backend down since …" |
| A node loses the shared file system | The step fails to commit; its lease expires; P1 retry rules |
| Budget reading stale (no step in hours, `quota`) | The last reading is used, aged: after `[sched.budget] stale_after` (2 h) only `high` and `urgent` start until a fresh reading arrives (the next step brings one) |
| A runaway project | Its own caps hold it (`HELD`/`limit`); the pool gates protect everyone else |
| Halt while a step is mid-commit | Drain waits for it; Stop's SIGTERM is handled by the commit protocol (the step lands or rolls back) |
| Clock skew between nodes | Leases of remote steps are judged by job state first; `wpk doctor` warns at more than 5 s |

## 12. Build plan

Each milestone keeps the suite green and adds tests with the fake model,
the fake clock and, from Q4, a fake batch system (a small `sbatch`/
`squeue`/`sacct` and `bsub`/`bjobs`/`bkill` in `tests/` that run jobs as
local processes and can be told to pend, preempt or lose them).

```
Q0 (spikes) ──► Q1 ──► Q2 ──► Q3 ──► Q4 (slurm) ──► Q5 (IDE in a slot) ──► Q6 (lsf)
```

### Q0: Spikes (nothing kept)

- [ ] On the SLURM cluster: `sbatch` from wpkd's host; `wpk step` on a
      node on a packet on the shared FS, with the fake model, then with
      Claude (route, login); queue wait for a `look` and a `sim` job at a
      few times of day; clock skew; `O_EXCL` on the FS.
- [ ] wpkd on a login node: resident size and idle CPU; `ssh -L` to a
      unix socket from the laptop; whether cron is allowed; whether the
      login nodes share `$WPK_HOME`.
- [ ] openvscode-server in a SLURM job, reached from wpkd's host by TCP
      with a connection token.
- [ ] The same on an LSF farm, when one is available, with the gateway.

### Q1: Priorities, controls and the dispatcher (local backend)

- [ ] `sched/` package: classes, effective class, order (§3.3), gates
      (§6.2 without budget), `control.toml`, project hold, run next.
- [ ] Registry fields `priority`, `sched`, `[packets.*]`; schema.
- [ ] Event-driven dispatcher on wpkd's loop replacing `tick(until_idle)`;
      `Backend` interface with `local`; job records; restart adoption.
- [ ] Sizes: `[sched.sizes]`, pool cores/mem/jobs, `size:` in the
      memento (spec, `wpk check`, prompt), packet and project sizes,
      `wpk size`; backfill and `backfill_for`.
- [ ] `wpk sched`, `wpk prio`; `wpk tick` on the same code.
- Tests: strict class order; fair share between projects; aging; spare
  room; drain and stop (stop not counted as an attempt); halt survives a
  restart; a slot is refilled within 1 s of a step ending; a `sim` step
  is not starved by a stream of `look` steps; a memento asking for a size
  the project does not allow.

### Q2: The budget

- [ ] Spend from `meta.json` (`usd`, `tokens`) and the quota reading;
      spend cache; pace and shape; class ceilings; estimates and
      reservations; 5-hour gate.
- [ ] Project caps from long-running.md §4 (`budget_usd_per_day`,
      `max_steps_per_hour`) and the new ones, to `HELD`/`limit`.
- Tests: each measure; gates close in order as spend passes pace; a
  restart rebuilds reservations; a stale quota reading.

### Q3: The board

- [ ] `/sched` page with the queue and reasons, budget chart, mode
      buttons; Overview headline; class and hold controls on project,
      card and packet pages; All packets columns and bulk operations
      (boards.md B8).
- Tests: each POST equals its CLI command; refused without the token;
  render check in Chrome at 1400 and phone width.

### Q4: SLURM

- [ ] `slurm` backend; sizes as `-c`/`--mem`/`-t`; `node_env`; the lost/
      preempted/timeout table (§5.5), and how "does not count" reaches the
      executor; `max_pending`; backoff.
- [ ] `wpk doctor`: shared FS, `wpk` and `claude` on a node, clock skew.
- [ ] Login node (§7.1): unix-socket listener, `--detach`/`--ensure`,
      `wpkd.lease` in place of the flock, job-state-driven rereads.
- [ ] Core-hours per size and project on the board; low-CPU `sim` flag.
- [ ] Live: a week of a real project on the cluster.

### Q5: An IDE in a slot

- [ ] IDE tasks through the backend, with a size picked at open; endpoint
      file; TCP proxy with connection token; IDE first in line and
      `reserve`; idle release.
- [ ] Live: from the iPad over the tailnet (needs S1b).

### Q6: LSF

- [ ] `lsf` backend on the same interface and tests; live trial on the
      commercial farm with the gateway and `usd` or `tokens` budget.

## 13. Open questions

1. *Decided 2026-10-26:* **one pool per user** for now. A team trial
   would run one wpkd per person, with the team's budget split by
   `amount`. Several users are added later in front of per-user daemons,
   not by making wpkd a shared service (§14).
2. *Decided 2026-10-26:* **wpkd runs on a login node** (§7.1).
3. *Decided 2026-10-26:* long simulations on LSF are sub-jobs a step
   starts through DFM, outside work-packet (§5.2). Locally (SLURM), steps
   get a size per task (§5.2). long-running.md §10.1's `job:` directive
   is still open for long runs that should outlive a step.
4. **Cost per class or per project for reporting?** The board can show
   spend by class for a period, so you can see whether `urgent` is being
   used for everything. Worth it once there are several people.
5. **Does the model choose sizes well?** If steps ask for `sim` and then
   only read files, the low-CPU flag (§5.2) will show it. If it happens
   a lot, the fallback is to let only people set sizes, and drop `size:`
   from the memento.
6. **Login-node limits.** Some sites kill processes on login nodes after
   a CPU-time or wall-time limit. If ours do, `--ensure` from cron is the
   answer; if cron is not allowed either, wpkd runs as a long job and the
   ssh line moves with it.

## 14. Multi-user later

*Decided 2026-10-26:* wpkd stays one daemon per user, running as that
user. Several users come later, in front of it, not inside it.

**Why not a shared service now.** Logging in is the easy part: the
Guard already has pluggable login (Tailscale now; token, PAM and SSO
later, server.md S3). The hard part is **whose account the work runs
as**. Every step, IDE and shell runs as you, and that is what makes the
packet files yours, git commits yours, your Claude login or API key
usable, and the farm's accounting right. A shared service would have to
either run everyone's work as one service account (file ownership,
credentials, authorship and accounting all break, and anyone who can
reach the board acts as everyone), or run each person's work as that
person (root, sudo rules or submit-on-behalf on LSF/SLURM: a security
review on any commercial farm, made harder by a browser shell that runs
code as the user). Neither is worth doing before there is a second user.

**The shape it would take: a front door over per-user daemons.**

```
  browser ──► front door (SSO login, team views, team pool)
                 │  unix socket per user, identity passed in a header
                 ├──► wpkd (alice, runs as alice) ──► LSF/SLURM as alice
                 └──► wpkd (bob, runs as bob)     ──► LSF/SLURM as bob
```

- Each user's wpkd is the one in this design: per-user pool, on a login
  node, listening on a unix socket (§7.1).
- The front door does the login and forwards each request to that user's
  wpkd. Only the front door can reach the sockets (a group-readable
  socket directory, or `SO_PEERCRED` checked by wpkd), so the identity it
  passes can be trusted. It runs no work and needs no privileges.
- **Team pool**: the front door splits the team's slots and budget and
  writes each user's share as a grant (below). Team views gather each
  wpkd's board data. The collaboration model in product.md §11 (inbox,
  outbox, connections) fits the same shape.

**What this design does now so that stays cheap:**

1. **Every change names who made it.** Each control, event and job
   record carries `by`, a principal of the form `<scheme>:<name>`
   (`unix:mballance` from the CLI, `tailscale:matt.ballance@gmail.com`
   from the board; later `sso:…`). It is required, not inferred from
   "the owner".
2. **Pool limits can come from a grant.** If `$WPK_HOME/sched/grant.toml`
   exists (`cores`, `mem`, `jobs`, `budget.amount`, `by`, `expires`), each
   limit in force is the lower of the config's and the grant's, read
   every pass. An expired grant falls back to the config limits, with an
   event and a banner on `/sched`. Nothing writes it yet; a front door
   would.
3. **One authorization check.** Every control goes through
   `sched/authz.check(principal, action, target)`. Today it allows any
   principal that passed the Guard, plus the local Unix user. Roles
   (admin for Halt and pool settings, members for priorities, §9) go
   there later and nowhere else.
4. **The unix-socket listener** (§7.1) is the interface a front door
   would use.
5. **No state outside `$WPK_HOME`** and the project directories, so many
   homes can sit behind one front door.

## Status log

### 2026-10-26: design

Written after the user asked for a server that serves the board and does
prioritized scheduling of agent steps and IDEs against a number of LSF
(commercial) or SLURM (private) slots and a token budget, with board
controls for halting, priorities and pausing. Decided here, for review:
five named classes with strict order and aging; fair share by project
within a class; budget gates as ceilings relative to pace, per class; one
batch job per step, pending jobs counting against slots; IDEs first in
line for slots but never preempting; drain and stop as the two halts,
persisted in `control.toml`; priorities in the registry entry, not in the
packet. Not built.

### 2026-10-26: answers on pools, login nodes and sizes

Decided with the user: one pool per user for now; wpkd should be able to
run on a farm login node (§7.1: light, a unix socket behind `ssh -L`
because a shared host makes the loopback listener unsafe, no systemd, a
lease in place of the flock, job state instead of inotify); on LSF, steps
may start sub-jobs through DFM, outside work-packet; on SLURM, tasks get
job sizes (§5.2), `look` = 1 core and `sim` = 8 cores and 32 GB, chosen
by `size:` in the memento within the sizes the project allows, or set by
a person per packet and project. The pool is now limited by cores, memory
and jobs instead of a slot count, with backfill that stops after
`backfill_for` so big jobs are not starved.

### 2026-10-26: multi-user later (§14)

Asked whether to start as a multi-user service with login. Decided with
the user: no; one wpkd per user running as that user, and later a front
door with SSO over per-user daemons. The hard part of multi-user is
running work as each user, not the login. Built now so later stays cheap:
a required `by` principal on every change, an optional `grant.toml` that
can lower pool limits, and one authorization function.

### 2026-10-26: built (Q1-Q6, without the farms)

Built as designed, with the changes recorded in scheduler-plan.md's
status log: the dispatcher on a thread, uncounted attempts by `wpk step
--lost`, `next_size` in status, a disallowed `size:` nudged, Run next first
of all classes, the stale-quota probe, the IDE's port chosen by its job's
wrapper. 638 tests pass. What is left needs the clusters.
