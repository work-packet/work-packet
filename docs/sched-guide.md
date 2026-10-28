# The scheduler: a user guide

How to run work-packet's steps in a pool of slots under a budget, on your
own machine or on a SLURM cluster, with wpkd on a login node. The design
and its reasons are in `docs/scheduler.md`; this is how to use it. (LSF is
in the last section.)

## 1. With nothing configured

Nothing changes: steps run on this host, `max_concurrent` at a time, oldest
due first, as `wpk tick` and `wpk dash --run` always did. Every packet is
class `normal` and size `look` (1 core). `wpk sched` shows the queue and why
each due packet waits.

## 2. Priorities

```bash
wpk prio fw-uart16550 high       # the project's class
wpk prio 7q2m4k urgent           # one packet (a WPID prefix)
wpk prio 7q2m4k --clear          # back to the project's
wpk prio 7q2m4k --next           # at the head of the line for one step
```

Classes, highest first: `urgent`, `high`, `normal`, `low`, `background`.
A higher class always goes first; within a class, the project with the
fewest cores in use (per its `weight`) goes next, then the oldest due. A
packet that has waited 4 h (`[sched] age_after`) moves up a class for
ordering, up to `high`. `background` starts only if room for one more
`look` job would be left.

The same controls are on the board: the project page's and packet page's
**Scheduling** panels, and the bar above **All packets** for ticked rows.

## 3. Holding and halting

| You want | Do |
|---|---|
| Nothing new in one project this week | `wpk sched hold fw-uart16550 -m "not this week"`; `release` to undo. Its packets keep their state. |
| One packet to stop | `wpk pause <wpid>` (its pending job, if any, is withdrawn) |
| Nothing new anywhere, running steps finish | `wpk sched halt -m "why"`, or **Halt** on `/sched` |
| Running steps killed now (something is spending money it should not) | `wpk sched stop -m "why"`, or **Stop now**. The steps go back to their last commit; their next attempts are not counted as failures. |
| Run again | `wpk sched resume` |

A halt or stop is kept in `$WPK_HOME/sched/control.toml`, so it survives a
restart, and every page of the board shows a red banner while it lasts.
`[sched] start_mode = "drain"` makes a fresh home start halted.

## 4. Job sizes

Name the shapes of job your work needs in `config.toml`:

```toml
[sched]
cores = 32                 # the pool: every running or pending job counts
mem   = "128G"
jobs  = 24

[sched.sizes.sim]          # look (1 core, 4G) is there already
cpus = 8
mem  = "32G"
time = "4h"
```

Then let a project's steps choose: `wpk set fw-uart16550 sizes=look,sim`.
The step prompt lists the sizes, and a memento's `size: sim` gives the
next step (only) an 8-core job. Or set it yourself: `wpk size
fw-uart16550 sim` (every step of the project), `wpk size <wpid> sim` (one
packet). A big job waiting for cores lets small ones start past it for
10 min (`backfill_for`), then the cores drain to it.

`/sched` shows core-hours per size and per project, and flags a multi-core
step that used under 20% of its cores: tell the model to use `look` until
it runs something.

## 5. A budget

```toml
[sched.budget]
measure = "usd"            # usd | tokens | quota (a Claude subscription)
amount  = 40.0             # per period; for quota a share of the window, e.g. 0.6
period  = "day"            # day | week | month, local time
```

Spend is read from each step's `meta.json`. Pace runs from 0 at the start
of the period to `amount` at its end, and each class may spend up to its
ceiling: `background` to pace − slack, `low` to pace, `normal` to pace +
slack (slack 10% of the amount), `high` to 95% of the amount, `urgent` to
`hard_cap`. So when you are behind pace everything runs, and as spend
catches up, background stops first, then low, then normal. `wpk sched`
and `/sched` show the spend, the pace, each class's ceiling and room, and
for a waiting packet when its class will reopen.

With `measure = "quota"` the reading is the subscription's own (the
7-day window, and the 5-hour window as a second test), so leave yourself
room: `amount = 0.6` lets work-packet take 60% of the week.

Per project, as a backstop (`wpk set <project> budget_usd_per_day=5`):
`budget_usd_per_day`, `budget_quota_per_week`, `max_steps_per_hour`. A
packet over one is paused with the figures, and shows under Needs you.

## 6. On a SLURM cluster

```toml
[sched]
backend  = "slurm"
cores    = 64              # what the farm's admins give this pool
jobs     = 24
node_env = "module load python/3.12 && source /proj/tools/wpk/venv/bin/activate"

[sched.slurm]
account   = "dv"
partition = "batch"
extra     = []             # more sbatch arguments for every job
```

Each step is one `sbatch` job of its size (`-c`, `--mem`, `-t`, `-p`,
`--account`), named `wpk:<home id>:<wpid>:<step>`, running `<node_env> &&
wpk step <packet>`. A pending job holds its room in the pool. wpkd polls
with one `squeue` for all jobs every 15 s, and `sacct` for those that
left the queue.

What the farm needs (check it with **`wpk sched doctor`**, which submits a
small probe job):

- the packets and `$WPK_HOME` on a shared file system, at the same path
  on every node;
- `wpk` and `claude` on the node's PATH after `node_env`;
- a route from the nodes to the model (a proxy or gateway in `node_env`),
  and the credentials in the shared home;
- clocks within a few seconds (leases compare times across hosts).

When the farm ends a job: a preemption, node failure or an admin's cancel
is retried at the head of its class and **not** counted as a failed
attempt; a timeout (the step ran past its limit) is counted. A job pending
longer than `[sched] max_pending` (30 min) shows on `/sched`. If `sbatch`
fails, wpkd backs off (30 s, doubling to 10 min) and `/sched` says the
batch system is down.

## 7. wpkd on a login node

```toml
[server]
listen = "unix"            # the board on $WPK_HOME/run/wpkd.sock, not a TCP port
```

On a shared host a port on 127.0.0.1 is open to every user there; a unix
socket in a 0700 directory is yours alone. Start wpkd and keep it up from
cron:

```bash
wpk serve --ensure         # starts it in the background unless it runs; log in $WPK_HOME/log/
crontab -e                 # */5 * * * * /path/to/wpk serve --ensure
wpk url                    # prints the ssh line for your laptop
```

On the laptop, run the line `wpk url` printed (`ssh -N -L
7878:<home>/run/wpkd.sock you@login`), then open http://localhost:7878/.

One wpkd per home, across login nodes that share it: `$WPK_HOME/wpkd.lease`
names the host and PID and is refreshed every 30 s. A second `wpk serve`
says who holds it and exits; if the holder dies, the lease is taken over
90 s after its last refresh. A wpkd that restarts adopts the jobs the last
one left in the batch system: running ones are watched to their end, and
pending ones whose packets were paused meanwhile are withdrawn.

## 7a. VS Code in a slot

With a batch backend, web VS Code (`[ide] web = true`) runs in a job of the
pool on a compute node, so its terminals build and simulate there:

```toml
[sched.ide]
slot      = true           # the default with slurm or lsf
reserve   = "look"         # room for one IDE that agents never take; "" for none
run_limit = "8h"
```

Pick a size beside **In the browser** (`look`, or `sim` to build and
simulate). The IDE goes ahead of all agent work but never stops a running
step; while it waits for room the page says so and reloads by itself.
It closes after `[ide] idle_minutes` with no window open, which frees the
room. Halt and Stop now leave IDEs alone. The node needs the VS Code server
on its PATH (`openvscode-server`, or `code` for `serve-web`).

## 8. Reading `/sched`

- The **mode** and the **Halt**, **Stop now** and **Resume** buttons.
- **Tiles**: cores and jobs in use against the pool's limits, how many
  wait, and the budget spent against pace.
- **Budget**: the chart of spend against pace and each class's ceiling,
  and the room each class has left.
- **Queue**: every due packet in the order it would start, its class (and
  the class aging gives it), its size, and what it waits on: the mode, a
  hold, its job, its project's cores, the budget (with when it reopens),
  room, or a bigger job ahead of it.
- **Jobs**, **core-hours** for the last 7 days, and **recent** events:
  mode changes, holds, lost and cancelled jobs, gates, the batch system
  going down and coming back.

`wpk sched --json` and `/sched.json` give the same data.

## 9. When something is wrong

| You see | It means | Do |
|---|---|---|
| Spend climbing too fast | | **Stop now** with a reason; look at the step pages of what ran |
| "budget: normal waits until pace reaches …" | normal work is ahead of pace | wait, raise the class of what matters, or raise `amount` |
| "no room for a sim job" for a long time | the pool's cores are busy | it gets them within `backfill_for` of waiting; or raise `cores` |
| "too big" | the size needs more cores or memory than the pool has | a smaller size, or a larger pool |
| "batch system is not answering" | `sbatch` or `squeue` fail | check the controller; wpkd retries by itself |
| A job pending for hours | the farm is full | nothing; it holds its room until it starts |
| Paused with "limit: …" | a project cap was reached | raise the cap, or resume it tomorrow |

## 10. On an LSF farm

```toml
[sched]
backend  = "lsf"
cores    = 64
node_env = "source /proj/tools/wpk/env.sh"   # wpk, claude, and the gateway's variables

[sched.lsf]
queue   = "normal"
project = "dv-agents"       # -P, for the farm's accounting
extra   = []                # more bsub arguments for every job
```

Each step is `bsub -J wpk:<home id>:<wpid>:<step> -W <limit> -n <cpus> -R
"rusage[mem=<MB>] span[hosts=1]" -q -P -o <log> bash -c "<node_env> && wpk
step <packet>"`. wpkd polls with one `bjobs -a -o … -json` for all its jobs.
A size may name its own `queue`.

When the farm ends a job: `TERM_PREEMPT`, `TERM_ADMIN`, `TERM_OWNER` (when
wpkd did not ask), `UNKWN` and `ZOMBI` are retried without counting the
attempt; `TERM_RUNLIMIT` counts, as a step timeout does.

**DFM sub-jobs** are outside the pool: a step that farms a regression out
through DFM starts jobs of its own, which the pool neither counts nor
cancels. The step's own job can then stay `look`-sized.

For a budget through a gateway that reports dollars, use `measure = "usd"`
(`tokens` if it meters tokens), and put the gateway's variables
(`ANTHROPIC_BASE_URL`, the token file) in `node_env`. `wpk sched doctor`
checks `bsub`, `bjobs` and `bkill`, and a probe job's view of the shared
file system, `wpk` and `claude`.
