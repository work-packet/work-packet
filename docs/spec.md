# work-packet packet format, v0.2

This is the on-disk contract between the executor (`wpk`), the model, and
anyone reading a packet by hand. `wpk check` enforces it
(`src/work_packet/schema.py`). It replaces `prototype/agent-proc.md` (v0.1),
where the model kept its own books.

Scope: Stage 1 (see `docs/stage1-plan.md`). Names reserved for later stages
are listed so that nothing else claims them.

## 1. Ownership

| Who | May write |
|---|---|
| The executor | everything in a packet, through the commit protocol (§7) |
| The model, during a step | only `.pending/` inside the packet it is running |
| A person | through `wpk` commands; hand edits are allowed but `wpk check` should pass afterwards |

Times stored anywhere are UTC, ISO 8601, second precision, with a `Z`
suffix: `2026-10-21T18:02:11Z`. Time zones are applied only when an
expression is resolved (§5) or a time is shown to a person.

## 2. Runner home

`~/.work-packet/`, or `$WPK_HOME`.

```
~/.work-packet/
  config.toml           global defaults (§2.1)
  projects/<name>.toml  registry: one file per project (§2.2)
  projects/.<name>.lock held while the entry is rewritten (§2.2)
  boards/<name>.toml    a board of the dash, other than main (§2.3)
  wpkd.lease            the one wpkd of this home: {host, pid, started, expires}; O_EXCL,
                        refreshed every 30 s, taken over 90 s after its last refresh or at
                        once if it names a dead PID on the taker's host
  events.jsonl          a symlink to the current month's sched/events-YYYY-MM.jsonl
  sched/                the scheduler's state (§2.4)
  run/wpkd.sock         the board, with [server] listen = "unix" (directory 0700)
  log/wpkd.log          wpk serve --detach's output
  requests/<wpid>--<id>.json  where each request stands: sending, open, delivering,
                        delivered (docs/delegation.md §4)
```

`templates/` is reserved (`docs/runner.md`). `runner.lock`, which an older
wpkd held with `flock`, is no longer used.

### 2.1 `config.toml`

All keys are optional. Unknown keys are errors.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `model` | string | `claude-opus-5-5` | model for new projects (and for projects that set none) |
| `harness` | string | `claude` | the agent CLI that runs steps (harness.md §3) |
| `max_concurrent` | int ≥ 1 | 1 | steps `wpk tick` runs at once |
| `step_timeout` | duration | `120m` | wall-clock limit for one model run |
| `max_attempts` | int ≥ 1 | 3 | failed attempts before a packet becomes `FAILED` |
| `step_budget_usd` | number > 0 | 1.00 | `--max-budget-usd` for one attempt |
| `step_context_tokens` | int ≥ 0 | 80000 | context at which a step is told to wrap up; 0 = off (context.md C3) |
| `carry_session` | bool | false | resume the previous step's session when allowed (context.md C4) |
| `max_step_budget_usd` | number > 0 | 10.00 | the most a question's `sets` may raise `step_budget_usd` to (docs/interaction.md §2); `wpk set` by hand is not limited |
| `carry_ttl` | duration | `55m` | longest gap after which a session is carried over |
| `carry_factor` | number > 1 | 4 | start fresh once a carried session's context reaches this multiple of its base |
| `[profiles.<name>]` | table | built-ins | extra profiles, checked before the built-in ones (harness.md §4) |

`step_context_tokens` and `carry_factor` may also come from the step's
profile; a value written in `config.toml` or `project.toml` wins over it.

A **duration** is a string `<int><unit>`, unit `s`, `m` or `h`: `90s`,
`20m`, `2h`.

`[sched]`: the scheduler (docs/scheduler.md §10). All keys are optional.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `backend` | string | `local` | `local`, `slurm` or `lsf`: where steps run |
| `cores`, `jobs` | int ≥ 0 | 0 | pool limits; every job's size counts, pending ones too. 0 cores: no limit; 0 jobs: `max_concurrent` |
| `mem` | memory | none | pool memory limit |
| `default_size` | name | `look` | the size a step gets when nothing names one |
| `spare_size` | name | `look` | a `background` step starts only if one job of this size would still fit |
| `backfill_for` | duration | `10m` | smaller jobs may start past a waiting bigger one until it has waited this long |
| `age_after` | duration | `4h` | a due packet moves up one class per this much waiting, up to `high` |
| `max_pending` | duration | `30m` | a job pending longer is reported (`pending_long`) |
| `poll` | duration | backend's | how often to poll the backend (local 0.25 s) |
| `tz` | IANA zone | host's | |
| `start_mode` | string | `run` | `run` or `drain`: the mode when `sched/control.toml` is missing |
| `node_env` | string | empty | put in front of the step command on a compute node |
| `[sched.sizes.<name>]` | table | `look` = 1 cpu, 4G | a job shape: `cpus` (int ≥ 1, required), `mem`, `time` (run limit; default the step timeout), `partition`, `queue`, `extra` (list of batch arguments), `resources` (LSF `-R` text such as `type==X86_64` or `select[...] same[...]`, merged into the one `-R`: selects and-ed, rusage added after `mem`, its `span` replaces `span[hosts=1]`), `constraint` (SLURM `--constraint`). Tables merge over the default, so adding `sim` keeps `look` |
| `[sched.budget]` | table | none | the budget (docs/scheduler.md §4): `measure` (`usd`, `tokens` or `quota`; empty: no budget), `amount` (dollars, tokens, or the share of the quota window, such as 0.6), `period` (`day`, `week` from Monday, `month`, in `tz`; ignored for `quota`, which uses the 7-day and 5-hour windows), `slack` (share of `amount`, 0.1), `hard_cap` (`urgent`'s ceiling; 0: `amount`), `default_step` (an estimate without history; 0: $0.50, 2M tokens, 0.5%), `cache_read_weight` (0.1), `stale_after` (`6h`: a quota reading older than this admits only `high` and `urgent` while a step runs), `tz`, `[shape]` (`weekday` = 7 weights from Monday, `hour` = 24 weights: pace follows them) |
| `[sched.slurm]` | table | none | flags for every job: `partition`, `account`, `extra` (list), `bin` (where `sbatch` and the rest are; empty: PATH), `poll` (duration, default 15 s) |
| `[sched.lsf]` | table | none | the same for LSF: `queue`, `project` (`-P`), `extra`, `bin`, `poll` |
| `[sched.ide]` | table | none | web VS Code in a slot (docs/scheduler.md §8): `slot` (bool; default true with a batch backend), `reserve` (a size agents never take; empty: none), `run_limit` (duration) |

A **memory** size is `<int>[K|M|G|T]`; a bare number is megabytes.

### 2.2 Registry entry: `projects/<name>.toml`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `name` | name | yes | equals the file stem |
| `path` | string | yes | absolute path of the project directory |
| `root` | WPID | yes | the project's root packet |
| `created` | timestamp | yes | |
| `template` | string | no | `<template>@<version>`, e.g. `blank@1` |
| `board` | name | no | the dash board the project is on; absent, or a board that does not exist, is `main` (§2.3) |
| `priority` | class | no | the project's class: `urgent`, `high`, `normal` (default), `low`, `background` (docs/scheduler.md §3) |
| `size` | name | no | the project's default job size (a `[sched.sizes]` name; an unknown one is ignored with a note) |
| `sched` | string | no | `run` (default) or `hold`: hold starts nothing in the project; `sched_by`, `sched_at`, `sched_reason` say who held it, when and why |
| `[packets.<WPID>]` | table | no | one packet's scheduling: `priority`, `size`, `next` (true: run next, once; the scheduler clears it) |

A **name** matches `[a-z0-9][a-z0-9_-]{0,63}`.

Every change to an entry goes through `registry.update`: it takes
`projects/.<name>.lock` (`O_EXCL`, waiting up to 5 s; a lock older than
30 s is taken over), rereads, changes, validates and writes the file
atomically, so the board and the CLI never lose each other's change.

### 2.3 Board: `boards/<name>.toml`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `name` | name | yes | equals the file stem; never `main` |
| `created` | timestamp | yes | |
| `title` | string | no | |

`main` is the default board: it has no file and cannot be deleted. Deleting
a board moves its projects to `main` (`docs/boards.md`).

### 2.4 The scheduler's files: `sched/`

Written only by wpkd's dispatcher and by the controls in
`sched/control.py` (docs/scheduler.md §6), each atomically.

| File | Written by | Holds |
|---|---|---|
| `control.toml` | `wpk sched halt\|stop\|resume`, the board | `mode` (`run`, `drain`, `stop`), `by`, `at`, `reason`. Missing: `[sched] start_mode` |
| `jobs/<id>.json` | the dispatcher | one per job it submitted and has not reaped: `id`, `backend`, `ref` (the backend's job ID; local: `<pid>:<start ticks>`), `kind` (`step`, `ide`), `project`, `wpid`, `path`, `by`, `cls`, `size`, `cpus`, `mem_mb`, `step`, `submitted`, `started`, `state` (`PENDING`, `RUNNING`), `lost`, `estimate`, `log`, `cancel`, `cancel_why`, `pending_long` |
| `jobs/<id>.log` | the job | the step's stderr; removed with the record |
| `lost/<WPID>.json` | Stop now, the reaper | `wpid`, `reason`, `by`, `t`, `step`: the packet's last attempt was ended by the scheduler or the farm, so its next launch passes `wpk step --lost REASON`. Removed when that launch is submitted |
| `grant.toml` | a front door (docs/scheduler.md §14), or by hand | `cores`, `mem`, `jobs`, `[budget] amount`, `by`, `expires`: limits that lower the config's, never raise them. Read every pass; once expired it is ignored, with one `grant_expired` event |
| `grant-expired` | the dispatcher | the `expires` of the last expired grant reported |
| `spend.json` | the dispatcher | the budget as of the last fill: windows, spent, reserved, pace, each class's ceiling. For readers; rebuilt every fill |
| `gated.json` | the dispatcher | per window, the period and the classes already gated in it (one `gate` event each) |
| `events-YYYY-MM.jsonl` | the dispatcher, the controls | one JSON object per line (below) |

A **principal** is `<scheme>:<name>`: `unix:<login>` from the CLI and the
board's loopback listener, `tailscale:<login>` from its tailnet listener.
Every control, event and job record carries one in `by`; what wpkd does on
its own is `by = "wpkd"`.

**Events**: `{"t", "type", "by", ...}`. Types: `mode` (`mode`, `was`,
`reason`), `hold` (`project`, `sched`), `prio` (`project`, `wpid`, `cls`,
`was`), `size` (`project`, `wpid`, `size`, `was`), `next`, `submitted`
(`job`, `ref`, `project`, `wpid`, `step`, `cls`, `aged`, `size`, `lost`,
`estimate`), `started`, `finished` (`job`, `kind`, `project`, `wpid`,
`step`, `size`, `cpus`, `code`, `submitted`, `started`, `end`, `cpu_s`,
`cancelled`, `lost`), `lost` (`why`), `cancelled` (`job`, `why`, `state`),
`pending_long`, `gate`, `backend_down`, `backend_up`, `adopted`,
`wpkd_start`, `wpkd_stop`, `grant_expired`, `cap`. Readers ignore types and
fields they do not know.
## 3. Project directory

```
<project>/
  project.toml
  prompt.md        the first instruction; copied into the root's memento.md at its first step
                   if that has none (docs/setup.md §10)
  state/           created by `wpk new`; copied into the root's state/ at its first step
  identity/        created by `wpk new`; links, added to the root's identity/ when a step starts
  work/            created by `wpk new`; what the task works on; the root's work/ references each entry
                   (a git worktree on wpk/<project> for a git repository, else a link)
  .setup/          setup records: smoke worktrees, logs and results, shell history; never
                   read by the executor
  agent.md         optional standing instructions added to every step's prompt
  packets/
    <WPID>/        one per packet, flat
    .tmp-<WPID>/   a child being built during a commit (§7); transient
```

### 3.1 `project.toml`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `name` | name | yes | |
| `root` | WPID | yes | root packet; must exist under `packets/` |
| `created` | timestamp | yes | |
| `template` | string | no | as in the registry |
| `tz` | IANA zone | no | zone for resolving `resume:`; default is the local zone |
| `model`, `harness` | string | no | override `config.toml`. Each packet keeps its own `model` in `status.md` (§4.1), copied when it is created; `wpk set model=` also passes the new model to the root packet and to every packet on the old one, but editing this file does not |
| `profile` | name | no | the profile to use; default: chosen by harness and model |
| `step_timeout`, `max_attempts`, `step_budget_usd`, `step_context_tokens`, `carry_session`, `carry_ttl`, `carry_factor` | as §2.1 | no | override `config.toml` |
| `[permissions]` | table | no | see below |
| `[setup]` | table | no | what the setup should contain: `[[setup.repo]]`, `[[setup.input]]`, `[[setup.link]]`, `[[setup.smoke]]`, `smoke_timeout` (docs/setup.md §4). Ignored by the executor |
| `sizes` | list of names | `[default_size]` | the job sizes this project's steps may ask for with `size:` (§4.2); `wpk set sizes=look,sim` |
| `weight` | number > 0 | 1 | fair share between projects of a class (docs/scheduler.md §3.3) |
| `max_cores` | int ≥ 0 | 0 | the most cores the project's jobs may hold at once; 0: no limit |
| `budget_usd_per_day`, `budget_quota_per_week`, `max_steps_per_hour` | number ≥ 0 (the last an int) | 0 | caps (docs/scheduler.md §4.5), also settable in `config.toml`: dollars the project spends per local day, share of the weekly quota per 7 days, steps per packet per hour. A packet over one is paused with `reason` naming the cap and the figures (`limit: …`, `HELD`/`limit` once L1 lands); 0: no cap |

`[permissions]`:

| Key | Type | Default | Passed as |
|---|---|---|---|
| `allowed_tools` | list of strings | `["Read", "Write", "Edit", "Glob", "Grep", "Bash"]` | `--allowedTools` |
| `permission_mode` | string | `acceptEdits` | `--permission-mode` |

`permission_mode` is one of the `claude --permission-mode` choices:
`acceptEdits`, `auto`, `bypassPermissions`, `dontAsk`, `manual`, `plan`.

## 4. Packet directory

A packet is `packets/<WPID>/`. A **WPID** is a lower-case UUID with hyphens.
Roots get a random (v4) WPID; children get a deterministic (v5) one (§6).

```
<WPID>/
  status.md          executor-owned (§4.1)
  report.md          the completion report, once the packet finishes (§4.7)
  memento.md         the next instruction (§4.2)
  state/             private working files
  identity/          symlinks to outside resources; read-only by convention
  work/              the root only: one entry per entry of the project's work/, a git
                     worktree or a relative link (docs/setup.md §10)
  children/          one symlink per child: <child WPID> -> ../../<child WPID>
  journal.jsonl      append-only, executor-owned (§4.3)
  steps/
    0001/            one folder per committed step (§4.4)
    0002.failed-1/   an attempt at step 2 that did not commit
  mailbox/           notes from the owner, waiting for a step (interaction.md §6a)
  .lease             present while a step runs (§4.5)
  .pending/          the model's proposal for the step in progress (§4.6)
  .state.old/        transient, during a commit only
```

Required: `status.md`, `memento.md`, `state/`, `journal.jsonl` (may be
empty). Optional: `identity/`, `children/`, `steps/`, `work/`, and the dot
entries. An entry of `work/` that is neither a git repository or worktree nor a
link is a warning.
Reserved and not created in Stage 1: `stack/`. `mailbox/` holds notes from the owner (`<id>.json`, docs/interaction.md §6a); it is outside the committed files, so it may change while a step runs. Anything else at
the top level is a warning.

### 4.1 `status.md`

Markdown with YAML front matter. The body is the summary of the last
committed step (empty at step 0). When that step finished the packet with a
report (§4.7), the body is the report's `outcome`, a blank line, then the
summary, so a view that shows the first line shows the outcome. Keys appear in this order; all are
present, unknown keys are errors.

| Key | Type | Meaning |
|---|---|---|
| `wpk` | string `"0.2"` | format version |
| `wpid` | WPID | equals the directory name |
| `project` | name | equals `project.toml: name` |
| `state` | enum | `RUNNABLE`, `SLEEPING`, `NEEDS_INPUT`, `PAUSED`, `COMPLETED`, `FAILED` |
| `step` | int ≥ 0 | last committed step; 0 = never run |
| `attempts` | int ≥ 0 | failed attempts at step `step + 1` so far |
| `parent` | WPID or null | |
| `spawn_key` | string or null | `<parent WPID>:<step>:<index>`; set exactly when `parent` is |
| `children` | list of WPID | in spawn order, no duplicates |
| `resume_expr` | string or null | what the model last wrote for `resume`, e.g. `in 10 days` |
| `wake_at` | timestamp or null | resolved instant; required when `SLEEPING`, null otherwise |
| `model` | string | model for the next step; a step may change it, and `wpk set model=` may (§3.1) |
| `reason` | string or null | required when `NEEDS_INPUT` (the question), `PAUSED` or `FAILED` |
| `updated` | timestamp | when the executor last wrote this file |
| `next_size` | name | optional: the job size the last committed memento asked for with `size:` (§4.2), for the next step only; the next commit replaces or removes it |
| `stopped` | timestamp | optional: when the packet's run stopped without anyone: set by the commit that makes it `COMPLETED`, or by a pause the scheduler makes for a budget or limit; only while `COMPLETED` or `PAUSED`; removed when it runs again (docs/overview-recent.md) |
| `seen` | timestamp | optional: when someone last looked at it after it stopped (`wpk seen`, or opening it on the board); with a `seen` journal record. Does not change `updated` |
| `children_seen` | map | optional: each child's WPID and the state the last step's prompt showed it in. A child now `COMPLETED`, `FAILED`, `NEEDS_INPUT` or `PAUSED` in a different state wakes a `SLEEPING` parent, at the child's commit or the next scheduler pass (docs/waiting-v1.md §4) |

`NEEDS_INPUT` means the last step asked a question (`ask:`, §4.2) and the
packet waits for a hand-off (`wpk handoff`); nothing runs it until then.
`WAITING` is reserved for Stage 3 and rejected in v0.2. When spec v0.3
replaces `PAUSED` and `FAILED` with `HELD` (long-running.md §7),
`NEEDS_INPUT` reads as `HELD` with `held_for: question`.

```markdown
---
wpk: "0.2"
wpid: 3f0c9a2e-6d1b-4c61-9a57-0d5e7f1b2c3d
project: count-demo
state: RUNNABLE
step: 7
attempts: 0
parent: null
spawn_key: null
children: []
resume_expr: now
wake_at: null
model: claude-haiku-4-5-20251001
reason: null
updated: 2026-10-21T18:02:11Z
---
Incremented count to 7; next step increments again.
```

### 4.2 `memento.md`

The model writes this, into `.pending/memento.md`. The front matter is the
model's decision about what happens after the step; the body is the
instruction for the next step.

| Key | Type | Required | Meaning |
|---|---|---|---|
| `resume` | resume expression (§5) | yes | when the packet runs next |
| `reason` | string | with `resume: fail` | why the work cannot be done |
| `ask` | non-empty string, or a list of questions (docs/interaction.md §2: `id`, `q`, optional `recommend`, `choices`, `grants`, `request`, `sets`) | no | questions for the owner: the step commits as `NEEDS_INPUT` with this as `reason`, whatever `resume` says; `resume` is kept in `resume_expr` as a record |
| `spawn` | list of spawn entries | no | children to create (§6) |
| `item` | string, number or a list of them | no | the plan item this step worked on (such as `2a`); it only labels the step for `wpk stats --by item` and the board. Missing or malformed is never an error: the step is just not charged to an item. A failed attempt is charged to its own pending memento's item, else to the item its step committed |
| `size` | name | no | the job size for the next step only (docs/scheduler.md §5.2): one of the project's `sizes` (§3.1), else the memento is refused like any bad one. Committed as `next_size` in `status.md` |

A spawn entry:

| Key | Type | Required | Meaning |
|---|---|---|---|
| `name` | name | yes | unique within this memento |
| `instruction` | string | yes | the child's first memento body |
| `copy` | list of globs | no | files under the parent's `state/` (as of the end of this step) to copy into the child's `state/`; relative, no `..` |
| `model` | string or null | no | default: the parent's model |

Rules:

- With `resume: done` or `fail` the body may be empty; otherwise it must not
  be.
- With `ask`, `resume` must not be `done` or `fail`, and the body must not
  be empty: it is the instruction for after the answer, which arrives as
  the hand-off note (§4.3, `handoff`) in the next step's prompt.
- Keys of later stages (`every`, `wait`) are rejected with a message
  naming the stage that adds them.
- A **committed** `memento.md` keeps the front matter of the step that wrote
  it, as a record; it has already been applied and is not re-read. A packet
  that has never run (root or child at step 0) has a memento with no front
  matter, or an empty one.

```markdown
---
resume: now
spawn:
  - name: hello
    instruction: |
      Write "Hello World" to state/p.md, then finish.
    copy: ["count.md"]
---
Read state/count.md. If it is below 8, add one and write it back.
```

### 4.3 `journal.jsonl`

One JSON object per line, appended with `O_APPEND` and fsynced. Every record
has `type` and `t` (timestamp). A truncated last line (a crash mid-append) is
a warning, not an error; the executor ignores it.

| `type` | Written when | Further required keys |
|---|---|---|
| `step-start` | after the lease is taken | `step`, `attempt`, `model`, `session_id` |
| `step-failed` | an attempt ends without committing | `step`, `attempt`, `why`; `run`, the folder's number (§4.4), since it was added; `counted: false` when the scheduler ended it (Stop now, a farm preemption: `wpk step --lost`), and `attempts` was not raised |
| `step-nudge` | the model's turn ended with `.pending/` incomplete; the session is resumed once | `step`, `attempt`, `why` |
| `commit-begin` | before any committed file changes | `step`, `decision` (below) |
| `commit-end` | after every committed file is in place | `step`; optional `cost_usd`, `tokens`, `duration_s` |
| `admin` | `pause`, `resume`, `wake` (a note's `--wake`), other changes made through `wpk` | `op`, `by` |
| `handoff` | `wpk handoff`: `NEEDS_INPUT`, `PAUSED` or `FAILED` to `RUNNABLE`; `wpk next` (the next batch, docs/dash-tasks.md §6): those or `COMPLETED` to `RUNNABLE`, with a new instruction | `by`, `from`, `to`; optional `asked` (the one-line summary, from `NEEDS_INPUT`), `questions` (the normalised list), `answers` (`{id: text}`), `note`, `heads` (`{repo: sha}` of the packet's `work/` repos) and `commits` (`{repo: ["sha subject", …]}` since the last step's `heads`). A next batch adds `batch` (2, 3, …), `instruction`, `outline` (where the finished `state/outline.md` went) and `carry_session`. The step prompt shows every `handoff` after the last `commit-end` under "Hand-off" |
| `config` | `wpk allow`, `deny`, `set` changed `project.toml` (root packet only) | `by`, `changes` (a list of strings) |
| `seed` | the root's first step copied the project's `state/` and `prompt.md` into it (docs/setup.md §10); at most once, and only if something was copied | `files` (the paths written) |
| `request` | a request to another project (docs/delegation.md): `sent` (requester: `to`, `title`), `received` (the delegate's root: `from`, `title`), `done` (requester: `outcome`, `note`, the id of the note that carried the result) | `op`, `id`, `by` |
| `seen` | someone looked at the packet after its run stopped (`wpk seen`, the board) | `by` |
| `note` | anything else worth recording (stale lease removed, ...) | `msg` |

`decision` holds everything needed to finish the commit without the model:
the new status fields (`state`, `resume_expr`, `wake_at`, `reason`,
`model`), the summary text, and `spawn`, a list of
`{name, wpid, spawn_key, instruction, copy, model}` with child WPIDs already
computed. When the step saw notes from the owner (docs/interaction.md §6a),
`notes` lists them (`id`, `t`, `by`, `text`, `how`: `prompt` or `hook`); the
commit removes them from `mailbox/`. When the packet has git repos under
`work/`, `heads` holds each one's `HEAD` at the end of the step
(`{repo: sha}`); a later hand-off lists the commits made after it.

Ordering rules the checker enforces: `step` values of `commit-end` records
increase by one starting at 1; every `commit-end` follows a `commit-begin`
for the same step; the last `commit-end` step equals `status.step` unless the
journal ends in an unfinished commit (a warning: run `wpk recover`).

### 4.4 `steps/NNNN/`

`NNNN` is the step number, zero-padded to four digits (more digits once past
9999). A committed step folder holds:

| File | Content |
|---|---|
| `prompt.md` | exactly what the model was sent |
| `system.md` | the protocol, appended to Claude Code's system prompt |
| `ctxhook.fired` | levels the context hook has sent (only if it fired) |
| `transcript.jsonl` | raw `claude -p --output-format stream-json` output |
| `stderr.log` | the model process's stderr |
| `result.md` | the proposed `memento.md` |
| `summary.md` | the proposed `summary.md` |
| `report.md` | the completion report (§4.7), with `commit` added; only on `done`/`fail` |
| `deliverables/` | a copy of each file or folder `report.md` lists, at its path (`state/…`, `work/…`), as it was at the commit; `.git` left out; only on `done`/`fail` |
| `deliverables.json` | `{path: "copied" \| "too large" \| "missing"}` for that copy; past 64 MiB a step copies only what fits |
| `state.diff` | `diff -ruN` of `state/` before and after |
| `meta.json` | start, end, harness, profile (`name@version`), model, session id, `carried_from`, exit code, cost (this step's; `session_cost_usd` is what Claude Code reported for the session), tokens (summed over the step's runs: `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `thinking_tokens`, `cache_write_1h`, `cache_write_5m`), `context` (`first`, `peak`, `last`, `calls`, `base`, `cache_breaks`, `cache_rewrite`), `duration_s`, `api_s` |

For every committed step `1..status.step` a folder `NNNN` exists, except
steps with no model run (none in Stage 1). Failed attempts are
`NNNN.failed-<run>` and may hold any subset of the files. The run counts
every start of the step, so unlike the attempt it does not go back to 1 when
a FAILED packet is resumed; it also picks the run's session ID
(`uuid5(WPID, "<step>:<run>")`), which Claude Code refuses to reuse.

### 4.5 `.lease`

JSON: `{"host", "pid", "step", "attempt", "expires"}`. Created with
`O_CREAT|O_EXCL`. A lease is stale when `expires` has passed, or when it is
on this host and the PID no longer exists. The checker warns about a stale
lease; it does not remove it.

### 4.5a `.pause`

A pause asked for while a step holds the lease (docs/pause-v1.md). JSON:
`{"by", "t"}`, optional `"reason"`. Written without the lease; a second
request keeps the first. The commit of the running step turns a decided
`RUNNABLE` or `SLEEPING` into `PAUSED` (reason `paused by <by> after step
<n>`, an `admin` record with `requested`), and removes the file whatever
it decided; a step that finds it at its start pauses instead of running.
`wpk resume`, a hand-off or `withdraw_pause` remove it. Not archived.

### 4.6 `.pending/`

Created by the executor at the start of a step. The model writes:

- `.pending/memento.md` (required): §4.2.
- `.pending/summary.md` (required): a few lines on what the step did. It
  becomes the body of `status.md`, the step's `summary.md` and part of the
  `commit-begin` record.
- `.pending/state/`: the executor copies `state/` here before the model runs;
  the model edits the copy.
- `.pending/report.md` (required with `resume: done` or `resume: fail`): the
  completion report, §4.7.

A step that says `resume: done` while `.pending/state/outline.md` has open
items (`[ ]`, `[>]`, `[+]`) is rejected. The message names the items and
points to `ask:` (when the next item is the owner's) or `resume: now`.

`.pending/` with no live lease is a crashed step: a warning, cleaned up by
`wpk recover` or the next `wpk step`.

### 4.7 `report.md`

The completion report (docs/completion-report.md): what the whole packet
did, for an owner who has seen none of its steps. The step that says
`resume: done` or `resume: fail` writes it as `.pending/report.md`; a step
without a valid one is rejected (and nudged, §7). Markdown with YAML front
matter:

| Key | Required | Content |
|---|---|---|
| `outcome` | yes | one line: what now exists, or why it failed |
| `deliverables` | yes (may be empty) | list of `{path, what}`; `path` is under `state/` or `work/`, relative to the packet, and must exist after the commit |

Each deliverable under `work/<repo>/` whose repo is a git checkout gets
`commit: <HEAD>` when the executor stores it. The body has the sections
`## Outcome`, `## Decisions`, `## Deliverables` and `## Open items`, in any
order; one with nothing to say says "none".

The executor stores it as `steps/NNNN/report.md`, copies the files it
lists to `steps/NNNN/deliverables/` (§4.4), copies it to
`report.md`, and the `commit-begin` decision gets `report: {outcome,
deliverables: [paths]}`. Leaving COMPLETED or FAILED (a next batch, a
resume or a hand-off) moves `report.md` to `state/history/report-<batch>.md`;
the `handoff` record names it as `report`.

Children's reports are not copied into the parent's: `wpk report`, `wpk
show` and the board's packet page roll them up (recursively) when they show
the parent, since a parent often finishes in the step that spawns them.

## 5. Resume expressions

| Expression | State after commit | `wake_at` |
|---|---|---|
| `now` | `RUNNABLE` | null |
| `done` | `COMPLETED` | null |
| `fail` | `FAILED` (`reason` required) | null |
| `in <N> <unit>` | `SLEEPING` | commit time + N units |
| `at <ISO 8601>` | `SLEEPING` | that instant; without an offset it is read in the project zone |

`N` is a positive integer; `unit` is `minute(s)`, `hour(s)`, `day(s)` or
`week(s)`. `in` days and weeks are calendar days in the project zone, so
`in 1 day` across a DST change is 23 or 25 hours. `at` accepts
`2027-01-10`, `2027-01-10 09:00`, `2027-01-10T09:00:00+01:00` and a `Z`
suffix; a date alone means midnight. An `at` in the past is accepted and
means "due now". `minute(s)` and `hour(s)` are elapsed time, so `in 24
hours` is always 24 hours.

A wall time that a DST change skips moves forward by the size of the gap
(`at 2027-03-28 01:30` in `Europe/London` is 02:30 BST). A wall time that
occurs twice means the first of the two. A project with no `tz` uses the
runner's local zone (`$TZ`, else `/etc/localtime`, else UTC).
`wake_at` is stored in UTC and truncated to whole seconds.

Rejected with the stage that adds them: `on <date>` and `every`
(Stage 2), `wait` (Stage 3). `ask` is not a resume value but a memento key
(§4.2).

## 6. Children

Child WPID: `uuid5(NS_WPK, "<parent WPID>:<step>:<index>")`, where `index`
is the entry's position in `spawn` (0-based) and `NS_WPK` is
`6f0c3e1a-8b7d-5c2e-9f4a-1d3b5e7a9c0b`. The same step proposing the same
spawn list therefore always names the same children, so a retried or
recovered step cannot create a second copy.

A new child has `state: RUNNABLE`, `step: 0`, `parent` and `spawn_key` set,
the instruction as the body of a memento with no front matter, the `copy`
files in `state/`, and the parent's `identity/` links.

Consistency the checker enforces within a project: every WPID in
`children` exists and links back through `parent`; `children/` holds exactly
those links; every packet with a `parent` is listed by it; exactly one packet
has no parent, and it is `project.toml: root`.

## 7. Commit protocol (summary)

Full detail: `docs/stage1-plan.md` §4.

1. `commit-begin` with the whole decision; fsync.
2. Children: build each missing one in `packets/.tmp-<WPID>/`, rename into
   place, add the `children/` link.
3. Rename `state` to `.state.old`, then `.pending/state` to `state`.
4. Rename `.pending/memento.md` to `memento.md`.
5. Write `status.md` (temp file, fsync, rename); copy the step's
   `report.md`, if any, to `report.md`.
6. `commit-end`; remove `.state.old` and `.pending/`; release the lease.

Each sub-step can tell whether it already happened, so recovery reads the
last `commit-begin` and redoes whatever is missing.

A step that does not reach `commit-begin` is a **failed attempt**: its
folder becomes `steps/NNNN.failed-<run>`, `status.md` gets `attempts`
set to that attempt's number, `step-failed` (with `run`) is appended, and `.pending/` is
removed. If the model changed any committed file, those files are restored
first. When `attempts` reaches `max_attempts` the packet becomes `FAILED`
with a reason naming the step and the last failure. A `step-start` with no
outcome (the executor died) is recorded the same way by the next `wpk step`
or `wpk recover`.

Before giving up on an attempt whose model ended its turn cleanly but left
`.pending/` incomplete (no memento, a memento that does not parse, no
summary, no valid report with `done` or `fail`), the executor **nudges** it once: it appends `step-nudge`, waits
up to 10 minutes for processes the step left running, then resumes the
session (forked, as in carry-over) with a message naming what is missing.
The second run is added to the same transcript, and `meta.json` gets
`nudged`. A timeout, a crash or a write to committed files is not nudged.

The failed folder keeps the `.pending/summary.md` and `memento.md` the
attempt left, as `pending-summary.md` and `pending-memento.md`. The retry's
prompt then has a "Last attempt" section: why it failed, its last 25 tool
calls, its last message and those files. That way it can pick up from what
the attempt left in `work/` rather than start again. The section also lists
why each earlier attempt at the step failed, one line each, and names every
failed attempt's folder, so the retry can grep a full `transcript.jsonl`
when the digest is not enough.

## 8. Changes from v0.1 (`prototype/agent-proc.md`)

- The executor, not the model, owns `status.md`, step numbers, spawning and
  the clock.
- Fixed file names; free-form plan files are gone.
- The model writes only `.pending/`.
- Children are flat siblings under `packets/` with deterministic IDs.
