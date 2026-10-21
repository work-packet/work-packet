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
```

`templates/`, `events.jsonl`, `runner.lock` and `runner.sock` are reserved
(`docs/runner.md`); Stage 1 does not create them.

### 2.1 `config.toml`

All keys are optional. Unknown keys are errors.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `model` | string | `claude-haiku-4-5-20251001` | model for new projects |
| `max_concurrent` | int ≥ 1 | 1 | steps `wpk tick` runs at once |
| `step_timeout` | duration | `20m` | wall-clock limit for one model run |
| `max_attempts` | int ≥ 1 | 3 | failed attempts before a packet becomes `FAILED` |
| `step_budget_usd` | number > 0 | 1.00 | `--max-budget-usd` for one attempt |

A **duration** is a string `<int><unit>`, unit `s`, `m` or `h`: `90s`,
`20m`, `2h`.

### 2.2 Registry entry: `projects/<name>.toml`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `name` | name | yes | equals the file stem |
| `path` | string | yes | absolute path of the project directory |
| `root` | WPID | yes | the project's root packet |
| `created` | timestamp | yes | |
| `template` | string | no | `<template>@<version>`, e.g. `blank@1` |

A **name** matches `[a-z0-9][a-z0-9_-]{0,63}`.

## 3. Project directory

```
<project>/
  project.toml
  prompt.md        the prompt the project was created from; never read by the executor
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
| `model` | string | no | overrides `config.toml` |
| `step_timeout`, `max_attempts`, `step_budget_usd` | as §2.1 | no | override `config.toml` |
| `[permissions]` | table | no | see below |

`[permissions]`:

| Key | Type | Default | Passed as |
|---|---|---|---|
| `allowed_tools` | list of strings | `["Read", "Write", "Edit", "Glob", "Grep"]` | `--allowedTools` |
| `permission_mode` | string | `acceptEdits` | `--permission-mode` |

`permission_mode` is one of the `claude --permission-mode` choices:
`acceptEdits`, `auto`, `bypassPermissions`, `dontAsk`, `manual`, `plan`.

## 4. Packet directory

A packet is `packets/<WPID>/`. A **WPID** is a lower-case UUID with hyphens.
Roots get a random (v4) WPID; children get a deterministic (v5) one (§6).

```
<WPID>/
  status.md          executor-owned (§4.1)
  memento.md         the next instruction (§4.2)
  state/             private working files
  identity/          symlinks to outside resources; read-only by convention
  children/          one symlink per child: <child WPID> -> ../../<child WPID>
  journal.jsonl      append-only, executor-owned (§4.3)
  steps/
    0001/            one folder per committed step (§4.4)
    0002.failed-1/   an attempt at step 2 that did not commit
  .lease             present while a step runs (§4.5)
  .pending/          the model's proposal for the step in progress (§4.6)
  .state.old/        transient, during a commit only
```

Required: `status.md`, `memento.md`, `state/`, `journal.jsonl` (may be
empty). Optional: `identity/`, `children/`, `steps/`, and the dot entries.
Reserved and not created in Stage 1: `stack/`, `mailbox/`. Anything else at
the top level is a warning.

### 4.1 `status.md`

Markdown with YAML front matter. The body is the summary of the last
committed step (empty at step 0). Keys appear in this order; all are
present, unknown keys are errors.

| Key | Type | Meaning |
|---|---|---|
| `wpk` | string `"0.2"` | format version |
| `wpid` | WPID | equals the directory name |
| `project` | name | equals `project.toml: name` |
| `state` | enum | `RUNNABLE`, `SLEEPING`, `PAUSED`, `COMPLETED`, `FAILED` |
| `step` | int ≥ 0 | last committed step; 0 = never run |
| `attempts` | int ≥ 0 | failed attempts at step `step + 1` so far |
| `parent` | WPID or null | |
| `spawn_key` | string or null | `<parent WPID>:<step>:<index>`; set exactly when `parent` is |
| `children` | list of WPID | in spawn order, no duplicates |
| `resume_expr` | string or null | what the model last wrote for `resume`, e.g. `in 10 days` |
| `wake_at` | timestamp or null | resolved instant; required when `SLEEPING`, null otherwise |
| `model` | string | model for the next step |
| `reason` | string or null | required when `PAUSED` or `FAILED` |
| `updated` | timestamp | when the executor last wrote this file |

`WAITING` and `NEEDS_INPUT` are reserved for Stage 3 and rejected in v0.2.

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
| `spawn` | list of spawn entries | no | children to create (§6) |

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
- Keys of later stages (`every`, `wait`, `ask`) are rejected with a message
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
| `step-failed` | an attempt ends without committing | `step`, `attempt`, `why` |
| `commit-begin` | before any committed file changes | `step`, `decision` (below) |
| `commit-end` | after every committed file is in place | `step`; optional `cost_usd`, `tokens`, `duration_s` |
| `admin` | `pause`, `resume`, other changes made through `wpk` | `op`, `by` |
| `note` | anything else worth recording (stale lease removed, ...) | `msg` |

`decision` holds everything needed to finish the commit without the model:
the new status fields (`state`, `resume_expr`, `wake_at`, `reason`,
`model`), the summary text, and `spawn`, a list of
`{name, wpid, spawn_key, instruction, copy, model}` with child WPIDs already
computed.

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
| `transcript.jsonl` | raw `claude -p --output-format stream-json` output |
| `stderr.log` | the model process's stderr |
| `result.md` | the proposed `memento.md` |
| `summary.md` | the proposed `summary.md` |
| `state.diff` | `diff -ruN` of `state/` before and after |
| `meta.json` | start, end, model, session id, exit code, cost, tokens |

For every committed step `1..status.step` a folder `NNNN` exists, except
steps with no model run (none in Stage 1). Failed attempts are
`NNNN.failed-<attempt>` and may hold any subset of the files.

### 4.5 `.lease`

JSON: `{"host", "pid", "step", "attempt", "expires"}`. Created with
`O_CREAT|O_EXCL`. A lease is stale when `expires` has passed, or when it is
on this host and the PID no longer exists. The checker warns about a stale
lease; it does not remove it.

### 4.6 `.pending/`

Created by the executor at the start of a step. The model writes:

- `.pending/memento.md` (required): §4.2.
- `.pending/summary.md` (required): a few lines on what the step did. It
  becomes the body of `status.md`, the step's `summary.md` and part of the
  `commit-begin` record.
- `.pending/state/`: the executor copies `state/` here before the model runs;
  the model edits the copy.

`.pending/` with no live lease is a crashed step: a warning, cleaned up by
`wpk recover` or the next `wpk step`.

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
(Stage 2), `wait` and `ask` (Stage 3).

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
5. Write `status.md` (temp file, fsync, rename).
6. `commit-end`; remove `.state.old` and `.pending/`; release the lease.

Each sub-step can tell whether it already happened, so recovery reads the
last `commit-begin` and redoes whatever is missing.

## 8. Changes from v0.1 (`prototype/agent-proc.md`)

- The executor, not the model, owns `status.md`, step numbers, spawning and
  the clock.
- Fixed file names; free-form plan files are gone.
- The model writes only `.pending/`.
- Children are flat siblings under `packets/` with deterministic IDs.
