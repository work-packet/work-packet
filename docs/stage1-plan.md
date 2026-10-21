# Stage 1 build plan: a packet that survives `kill -9`

Status (2026-10-21): M0–M5 done (repo, CI pair, spec v0.2, `wpk check`, resume
resolution, `wpk step`/`wpk recover`, spawn, crash safety). Next: M6 (projects
and the registry).
Status log is at the end. A fresh session should be able to resume from this
file alone.

## 1. What Stage 1 is

Stage 1 is roadmap **Phase 0** (spec and schema) plus **Phase 1** (steps that
are safe to retry), plus the **first slice** suggested at the end of
`docs/runner.md`: `wpk step` with `steps/` capture, `wpk new` with the blank
template, a registry, `wpk ps` and `wpk tick`. It also pulls a small piece of
Phase 2 forward: one-shot timers (`resume: in 10 days`, `resume: at <ISO>`)
and the `WPK_NOW` fake clock. Without them a packet cannot wait for anything,
and the first real projects we want to run are periodic checks.

At the end of Stage 1 you can:

```bash
wpk new count-demo --prompt "Increment state/count.md until it reaches 8, then spawn a child that writes Hello World"
wpk tick --until-idle
wpk ps
wpk log <WPID>
```

and the result is correct even if the machine is killed partway through.

### Exit criteria

Stage 1 is done when all of these pass, most of them in CI:

| # | Test | Where |
|---|---|---|
| E1 | Replaying `prototype/sub` with the fake model gives `count.md = 8`, exactly one child, and the child's `state/p.md` is `Hello World` | CI |
| E2 | `SIGKILL` at **every** fault point in the commit sequence, then `wpk step` again, gives the same final tree as a run with no fault (after normalising timestamps, costs and session IDs) | CI |
| E3 | A step whose model writes outside `.pending/` is rejected, and the committed files are byte-for-byte unchanged | CI |
| E4 | `resume: in 10 days` under `WPK_NOW`: not due on day 9, due on day 10, runs once | CI |
| E5 | A `wpk new` that fails part-way leaves no registry entry; `wpk new` then `wpk tick` runs step 1 | CI |
| E6 | `wpk check` passes on every packet that the test suite creates | CI |
| E7 | E1 with the real `claude -p` (Haiku), three runs in a row, all correct | `WPK_LIVE=1`, by hand |
| E8 | Two real projects run for a week under a cron `wpk tick` with no manual repair | by hand |
| E9 | CI is green on both Forgejo and GitHub | both forges |

## 2. Decisions taken for Stage 1

These close the roadmap's open questions as far as Stage 1 needs. Each can be
revisited; none is expensive to change before Stage 2.

- **Python, not a dv-flow task.** Date handling, file locking and subprocess
  control are all in the standard library. A dv-flow task can wrap
  `wpk step` later. Floor is **Python 3.10** because the Forgejo runner has
  3.10, so no `tomllib` (use `tomli`), and no `pip install -e` in CI.
- **Few dependencies.** `pyyaml` (front matter), `tomli` on 3.10, `tomli-w`
  (writing registry and project files). `argparse`, not click. The dashboard's
  web stack is an optional extra (`work-packet[dash]`) so the core stays light.
- **Packets always live in a project.** `packets/<WPID>/`, flat, as
  `docs/runner.md` says. There is no free-standing packet directory in Stage 1.
- **No git per packet yet.** The journal plus `steps/<n>/` is the history.
  Git snapshots are Phase 4.
- **Time zone is per project** (`project.toml: tz`), defaulting to the local
  zone. Stored times are UTC.
- **Leases live in `.lease`, not in `status.md`.** The roadmap lists
  `lease_holder` and `lease_expires` as status fields; `docs/runner.md` puts
  them in `.lease`. We follow `runner.md`, so a lease refresh does not rewrite
  `status.md` every minute.
- **The model never writes committed files.** It writes only into
  `.pending/`. The executor checks this after every step (E3) and can later
  enforce it with a hook (see §9).
- **Spawning is an executor operation.** The model asks for children in the
  memento's front matter; the executor creates them with deterministic IDs.
- **No external-effect journal in Stage 1.** The roadmap's idempotency keys for
  side effects outside the packet (`<WPID>:<step>:<n>`) are deferred, because
  nothing in Stage 1 needs them and the blank template does not allow `Bash`.
  The executor exports `WPK_WPID`, `WPK_STEP` and `WPK_ATTEMPT` so a tool can
  build such a key when the time comes.

## 3. Packet format v0.2 (summary)

The full text is `docs/spec.md` (written in M1). Where the two differ, the spec
wins; this section is kept as the summary the plan was written against.

### Layout

```
<project>/
  project.toml
  prompt.md
  packets/
    <WPID>/
      status.md          executor-owned: front matter + last step's summary
      memento.md         the next instruction (front matter + body)
      state/             private working files; copied (selectively) to children
      identity/          symlinks to outside resources; read-only by convention
      children/          symlinks ../../<child WPID>
      journal.jsonl      append-only, executor-owned
      steps/
        0001/            one per committed step
          prompt.md  transcript.jsonl  result.md  summary.md  state.diff  meta.json
        0002.failed-1/   an attempt that did not commit, kept for debugging
      .lease             present while a step runs
      .pending/          the model's proposal for the step in progress
```

`stack/` and `mailbox/` from the roadmap are reserved names. Stage 1 creates
neither and the checker accepts their absence.

### `status.md` front matter

```yaml
---
wpk: "0.2"
wpid: 3f0c9a2e-...
project: count-demo
state: RUNNABLE        # RUNNABLE | SLEEPING | PAUSED | COMPLETED | FAILED
step: 7                # last committed step; 0 = never run
attempts: 0            # failed attempts at step+1 so far
parent: null           # WPID or null
spawn_key: null        # "<parent WPID>:<step>:<index>" for children
children: []           # WPIDs, in spawn order
resume_expr: null      # what the model wrote, e.g. "in 10 days"
wake_at: null          # resolved UTC instant, ISO 8601
model: claude-haiku-4-5-20251001
reason: null           # why PAUSED or FAILED
updated: 2026-10-21T18:02:11Z
---
Incremented count to 7; next step increments again.
```

`WAITING` and `NEEDS_INPUT` are reserved for Phase 3; the Stage 1 checker
rejects them so they cannot appear by accident.

### `memento.md` front matter (written by the model into `.pending/`)

```yaml
---
resume: now            # now | done | fail | in <N> <unit> | at <ISO 8601>
reason: "..."          # required with fail
spawn:                 # optional
  - name: hello        # unique within this step
    instruction: |
      Write "Hello World" to state/p.md, then finish.
    copy: ["count.md"] # globs under the parent's state/ (after this step)
    model: null        # optional; default is the parent's model
---
Read state/count.md. If it is below 8, add one ...
```

- `resume` is required. Units for `in` are minutes, hours, days and weeks.
  `on 10 Jan`, `every:`, `wait:` and `ask:` are later stages. The parser
  rejects them with a message saying which stage adds them, so a memento
  written for a later stage fails loudly rather than being half-understood.
- With `resume: done` or `fail` the body may be empty.
- `.pending/summary.md` (required) is a few lines saying what this step did.
  It becomes the body of `status.md`, the step's `summary.md` and the journal
  record. This replaces the free-form, model-written `status.md` of the
  prototype.

### `journal.jsonl`

One JSON object per line, appended with `O_APPEND` and fsynced:

| `type` | Written when | Key fields |
|---|---|---|
| `step-start` | after the lease is taken | step, attempt, model, session_id |
| `step-failed` | an attempt ends without committing | step, attempt, why |
| `commit-begin` | before any committed file changes | step, the **whole resolved decision**: new status fields, spawn list with child WPIDs |
| `commit-end` | after every committed file is in place | step, cost_usd, tokens, duration |
| `admin` | `pause`, `resume`, manual edits through `wpk` | op, by |

`commit-begin` carries everything needed to finish the commit without the
model. That is what makes recovery deterministic.

## 4. One step, in detail

`wpk step <WPID>` runs exactly one step. Let `n = status.step + 1` and
`a = status.attempts + 1`.

**Before the model runs**

1. **Lease.** Create `.lease` with `O_CREAT|O_EXCL`, containing host, PID,
   step, attempt and expiry (now + step timeout + margin). A live lease means
   exit 3. A stale lease (expired, or same host and the PID is gone) is
   removed, with a journal note.
2. **Recover.** If the journal ends in `commit-begin` with no `commit-end`,
   roll that commit forward (below) and stop: that counts as the step.
   If it ends in `step-start` with no outcome, the previous attempt died
   before committing: write `step-failed` for it and rename its step folder
   to `steps/NNNN.failed-<a>`.
3. **Check state.** Only `RUNNABLE`, or `SLEEPING` with `wake_at <= now`,
   may step (exit 2 otherwise, unless `--force`). `attempts >= max_attempts`
   means set `FAILED` and stop.
4. **Prepare.** Remove any `.pending/`. Create `.pending/` and copy `state/`
   to `.pending/state/`. The model edits that copy, which is how state changes
   become part of the atomic commit.
5. **Snapshot** the committed files (hash of `memento.md`, `status.md`,
   `journal.jsonl`, everything under `state/`, the `children/` links).
6. **Build the prompt** from the executor's step template
   (`src/work_packet/prompts/step.md`), and write it to
   `steps/NNNN/prompt.md`. It contains: the packet protocol (what to read,
   that only `.pending/` may be written, the memento schema, "do not sleep,
   count steps or create packets yourself"); the time now and, for a timer
   wake, when it was due and how late it is; step and attempt numbers; the
   last summary; a table of children with their state and last summary; the
   project's `agent.md`, if any; and the memento body.
7. Write `step-start` to the journal.

**The model**

8. Run, with the packet directory as working directory and the prompt on
   stdin:

   ```
   claude -p --output-format stream-json --verbose
          --model <model> --session-id <uuid5(WPID, n, a)>
          --permission-mode <project> --allowedTools <project>
          --max-budget-usd <step budget> [--add-dir <resolved identity targets>]
   ```

   stdout goes to `steps/NNNN/transcript.jsonl`, stderr to `stderr.log`.
   `WPK_CLAUDE` replaces the `claude` executable (tests use the fake model).
   A timeout kills the process group. The lease is refreshed every 60 s while
   it runs.

**After the model**

9. **Verify the snapshot.** If any committed file changed, the step is
   rejected (E3). Nothing is committed and the attempt counts as failed.
10. **Read the result** event from the transcript: exit status, `is_error`,
    `total_cost_usd`, token usage, session ID. Write `meta.json`.
11. **Validate** `.pending/`: `memento.md` parses and matches the schema,
    `summary.md` exists, spawn names are unique, `copy` globs stay inside
    `state/`. Any failure means `step-failed`, `attempts += 1` in `status.md`,
    the step folder becomes `NNNN.failed-<a>`, and the step exits 1.
12. **Resolve.** Turn `resume` into a state and `wake_at` using the executor's
    clock and the project time zone. Compute the child WPIDs as
    `uuid5(NS_WPK, "<WPID>:<n>:<index>")`. Write `state.diff`
    (`diff -ruN state .pending/state`) and copy `.pending/memento.md` to
    `steps/NNNN/result.md`.

**Commit**, with a fault point after each sub-step (§7):

13. Append `commit-begin` with the full resolved decision. fsync.
14. **Children.** For each spawn entry whose packet directory does not exist:
    build it in `packets/.tmp-<child>/`, then rename it into place; then
    create the `children/<child>` link if it is missing. Each child starts
    `RUNNABLE` at step 0 with the instruction as its memento, the `copy` files
    from `.pending/state/`, the parent's identity links, and `spawn_key` set.
15. **State.** Rename `state` to `.state.old`, then `.pending/state` to
    `state`.
16. **Memento.** Rename `.pending/memento.md` to `memento.md`.
17. **Status.** Write `status.md` (temp file, fsync, rename) with `step = n`,
    `attempts = 0`, and the resolved fields.
18. Append `commit-end`. Remove `.state.old` and `.pending/`. Release the
    lease.

**Roll-forward** reads the `commit-begin` record and redoes 14–18. Every
sub-step can tell whether it has already happened: the child directory
exists; `.pending/state` is gone; `.pending/memento.md` is gone; `status.md`
already says `step = n`. So recovery after a crash at any point gives the same
result as an uninterrupted commit, and E2 tests exactly that.

Exit codes: 0 committed, 1 attempt failed (retry later), 2 not runnable,
3 lease held, 4 usage or configuration error.

## 5. Commands in Stage 1

| Command | Does |
|---|---|
| `wpk new <name> [--prompt … \| --prompt-file …] [--dir …] [--model …] [--tz …] [--paused] [--dry-run]` | `docs/runner.md` steps 1–4 with the `blank` template; prints the permissions the steps will run with. Step 5 (notify the runner) is a message saying "run `wpk tick`" |
| `wpk adopt <dir>` / `wpk rm <name>` | Register an existing project / remove the registry entry only |
| `wpk step <WPID>` | §4. Accepts a unique WPID prefix or `<project>` (its root) |
| `wpk recover <WPID>` | Only steps 1–2 of §4: finish or clean up a crashed step, run no model |
| `wpk tick [-j N] [--until-idle] [--max-steps N] [--dry-run] [--project P]` | One scheduler pass: find due packets in every registered project (`RUNNABLE`, or `SLEEPING` and due), skip leased ones, oldest-due first, run up to N `wpk step` subprocesses. `--until-idle` repeats until nothing is due, bounded by `--max-steps` |
| `wpk ps [--all] [--project P]` | Project, short WPID, state, step, next wake (absolute and relative), last summary line. Hides finished projects unless `--all` |
| `wpk show <WPID>` | `status.md`, `memento.md`, children |
| `wpk log <WPID> [--step N]` | The journal as a table; with `--step`, that step's summary, diff and meta |
| `wpk pause <WPID\|project>` / `wpk resume …` | Set `PAUSED` (reason "by hand") or back to `RUNNABLE`, through the same commit path, with an `admin` journal line |
| `wpk check [path]` | The schema checker: every packet under a project or the registry. Used by E6 |

`pause` and `resume` are in Stage 1 because they are the only safe way for a
person to stop a runaway packet, and they are small.

Runner home is `~/.work-packet/` (`WPK_HOME` overrides it) with
`config.toml` and `projects/<name>.toml`, as in `docs/runner.md`.
`config.toml` holds Stage 1 defaults: model, `max_concurrent` (1),
`step_timeout` (20m), `max_attempts` (3), `step_budget_usd` (1.00).
`project.toml` may override each, plus `tz` and `[permissions]`. The blank
template allows `Read, Write, Edit, Glob, Grep` and nothing else.

## 6. Code layout

```
src/work_packet/
  cli.py          argparse front end; one function per subcommand
  fsutil.py       atomic_write, fsync_dir, copytree, safe rename helpers
  frontmatter.py  read and write Markdown with YAML front matter
  clock.py        now() honouring WPK_NOW; resume-expression parser and resolver
  schema.py       status, memento, project and config validation; used by `check`
  check.py        `wpk check`: walk a packet, project or runner home; cross-file rules
  packet.py       Packet: paths, load and save status, children, identity
  journal.py      append and read records; find an unfinished step or commit
  lease.py        acquire, refresh (thread), release, stale detection
  prompt.py       build the step prompt from prompts/step.md
  prompts/step.md the executor's step template (versioned with the code)
  model.py        run claude or WPK_CLAUDE; parse stream-json into StepResult
  spawn.py        child WPIDs and idempotent child creation
  executor.py     step() and recover(): §4
  faults.py       WPK_FAULT_AT kill points
  registry.py     WPK_HOME, config, projects/*.toml, WPID lookup
  project.py      new and adopt
  scheduler.py    tick
tests/
  conftest.py     temporary WPK_HOME, fake-model environment, tree normaliser
  fakemodel/fake_claude.py   stands in for `claude -p`
  fakemodel/behaviors/       add_one.py, hello.py, write_outside.py, ...
  test_<module>.py
```

## 7. How it is tested

- **Fake model.** `tests/fakemodel/fake_claude.py` accepts the same arguments
  as `claude -p`, reads the prompt from stdin, and runs a behaviour module
  named by `WPK_FAKE_BEHAVIOR`. A behaviour reads the packet like a model
  would and writes `.pending/`. The fake emits stream-json `system`,
  `assistant` and `result` events with a made-up cost, so `meta.json` and
  budgets are exercised. `WPK_FAKE_FAULT` makes it crash, hang, exit
  non-zero, write bad front matter, or write outside `.pending/`.
- **Fault points.** `WPK_FAULT_AT=<name>` makes the executor `SIGKILL`
  itself at that point: `after-model`, `after-commit-begin`, `mid-spawn`,
  `after-state-swap-1`, `after-state-swap-2`, `after-memento`,
  `after-status`, `before-cleanup`. E2 runs `prototype/sub` once per point,
  killing at step 4, then finishes the run and compares with a clean run.
  One more test sends a real `SIGKILL` from outside at a random moment.
- **Fake clock.** `WPK_NOW` for E4 and for every test with a timer.
- **Normaliser.** Compares two project trees ignoring timestamps, durations,
  costs, session IDs and `*.failed-*` folders.
- **Checker everywhere.** A fixture runs `wpk check` on every project a test
  creates (E6).
- **Live tests** (`@pytest.mark.live`) call the real `claude` with Haiku and
  run only with `WPK_LIVE=1`. They never run in CI.
- **The prototype as fixtures.** The `prototype/sub` instructions become the
  `add_one` behaviour and the E1 and E7 scenario. The bf474803 case (said "5
  times", wrote 6 lines) becomes a live test once the prompt template exists.

## 8. Milestones

Each milestone ends with its tests passing in CI on both forges. Tick the
boxes as you go and add a line to the status log.

### M0: Repository (done 2026-10-21)

- [x] `work-packet/work-packet` on Forgejo, seeded from `agent-proc`
- [x] Python skeleton (`wpk --version`), CI pair from `forgejo-ops/templates`
- [x] CI steps trial-run in `catthehacker/ubuntu:act-22.04`
- [x] First CI run is green on Forgejo (Build and test, Release authority)
- [x] The repo appears on GitHub after the next sync cycle, and GitHub CI is
      green (`git-sync status`: all aligned)

### M1: Spec v0.2 and schema checker (done 2026-10-21)

- [x] `docs/spec.md`: the full text of §3, plus `project.toml` and
      `config.toml`
- [x] `fsutil.py`, `frontmatter.py`, `schema.py`, `packet.py` (plus
      `journal.py` read/append, and `clock.now()` / `parse_resume()` pulled
      forward from M2 because the checker needs them)
- [x] `wpk check [path] [--strict] [-q]`
- Tests: round-trip front matter; good and bad fixtures for each schema;
  `check` reports file and field for each error.

### M2: Clock and resume expressions (done 2026-10-21)

- [x] `clock.py`: `resolve()` with zone handling (`now()` and
      `parse_resume()` landed in M1)
- Tests: each form; DST change in the project zone; `in 10 days` across a
  month end; rejected later-stage forms name their stage.

### M3: Executor core (`wpk step`, `wpk recover`) (done 2026-10-21)

- [x] `journal.py`, `lease.py`, `prompt.py` + `prompts/step.md`, `model.py`
- [x] `executor.py` §4; `steps/NNNN/` capture (seven files, spec §4.4)
- [x] Fake model with `add_one` and the fault behaviours
- Tests: one step commits and captures every file; each fake fault gives
  `step-failed` and `attempts + 1`; three failures give `FAILED`; a live lease
  gives exit 3; a stale lease is cleared; E3.

### M4: Spawn (done 2026-10-21)

- [x] `spawn.py`; children table in the prompt
- Tests: deterministic WPIDs; `copy` globs; a retried commit creates no second
  child; E1.

### M5: Crash safety (done 2026-10-21)

- [x] `faults.py`; roll-forward; `steps/NNNN.failed-<a>` handling
- Tests: E2 for every fault point; an external `SIGKILL` at a random time.

### M6: Projects and the registry

- [ ] `registry.py`, `project.py`; `new`, `adopt`, `rm`, `ps`, `show`, `log`,
      `pause`, `resume`
- Tests: E5; `--dry-run` writes nothing; name clash; WPID prefix lookup;
  `ps` output for each state.

### M7: `wpk tick`

- [ ] `scheduler.py`: due set, ordering, `-j`, `--until-idle`, `--max-steps`
- Tests: E4; leased packets are skipped; oldest-due first across two
  projects; `-j 2` never runs more than two steps at once; `--until-idle` on
  `prototype/sub` ends with everything `COMPLETED`.

### M8: Real use

- [ ] E7: live `prototype/sub` with Haiku, three runs
- [ ] A cron entry (`*/5 * * * * wpk tick -j 2`) and two real projects, for
      example a weekly check of a dv-flow regression and a research packet
      that fans out to children
- [ ] Notes on what the board and Stage 2 need, written to the roadmap
- Exit: E8.

### M9 (cut to Stage 2 if M8 runs late): read-only board

- [ ] `wpk dash` (`work-packet[dash]`: Starlette, Jinja2, uvicorn): board
      with the columns from `docs/runner.md` that exist in Stage 1 (Running,
      Ready, Sleeping, Paused, Failed, Done), project page with the packet tree,
      step viewer with prompt, transcript, diff and meta. Refreshes every 10 s;
      server-sent events come in Stage 2.
- Tests: every Stage 1 state lands in the right column, from fixture trees.

## 9. Risks

| Risk | Plan |
|---|---|
| The model edits `state/` directly instead of `.pending/state/` | Detected every step (E3). If E7 shows it often, enforce it: pass `--settings` with a `PreToolUse` hook that denies `Write`/`Edit` outside `.pending/`. Try this in M3 if it is cheap |
| A retried step repeats a side effect outside the packet | Blank template has no `Bash`. Idempotency keys are Stage 2, before any template that allows `Bash` |
| Identity symlinks point outside the working directory and the model cannot read them | Resolve them and pass `--add-dir`. Check in M3 against the installed `claude` |
| Python 3.10 floor | `tomli` fallback; `zoneinfo` is fine; CI catches the rest |
| Full copy of `state/` every step uses disk | Fine while state is small. Revisit with `wpk prune` in Stage 2 |
| Cost of failed attempts | `step_budget_usd` per attempt and `max_attempts` per step |

## 10. Not in Stage 1

`every:`, `on <date>`, catch-up notes and changes in `identity/` (Stage 2,
with `wpkd`, limits and budgets); `wait:`, `ask:`, mailbox, supervision and
the reaper for orphans (Stage 3); git snapshots, rewind and fork (Stage 4);
templates other than `blank`; notifications; `prune`, `archive`;
multi-machine use.

## 11. Before the first release tag

The `work-packet` name is still free on PyPI. The CI pair publishes on a `v*`
tag from whichever forge the release-authority switch names (the default
today). Decide release authority and add the `PYPI_API_TOKEN` secret before
tagging. No tag is planned in Stage 1.

## Status log

- 2026-10-21: M0. Repo created on Forgejo and seeded with `docs/`,
  `slides/` and the prototype (`prototype/`, was `agent-proc/test/`). Python
  skeleton and CI pair added; CI steps pass in the Forgejo runner image
  (Python 3.10.12). Plan written. First Forgejo CI run green; GitHub mirror
  pending the next sync cycle.
- 2026-10-21: M0 closed: GitHub mirror created by the sync cycle, GitHub CI
  green.
- 2026-10-21: M1. `docs/spec.md` (v0.2) written. Decisions made while
  writing it: `children/` links are `../../<WPID>`; `project.toml` carries
  `root` as well as the registry entry; a committed memento keeps its front
  matter as a record and may have none at step 0; crash leftovers
  (`.pending/` with no lease, torn journal tail, unfinished commit,
  `.tmp-<WPID>`, stale lease) are warnings, not errors; `NS_WPK` fixed at
  `6f0c3e1a-8b7d-5c2e-9f4a-1d3b5e7a9c0b`. Modules: `fsutil`, `frontmatter`
  (timestamps stay strings), `clock` (now, parse_resume), `schema`,
  `journal`, `packet`, `check`. `wpk check` exits 1 on errors (`--strict`:
  on warnings too) and prints `level: path: field: message` relative to the
  checked directory. 147 tests pass on 3.12 and in the runner image (3.10).
  `tests/conftest.py: make_project()` builds a valid project with committed
  steps and a child; M3 should produce the same tree through the real
  executor.

### 2026-10-21: M2 done

`clock.resolve(resume, committed, tz)` returns `(state, wake_at)`. Minutes
and hours are elapsed time; days and weeks are calendar days in the
project zone. A skipped wall time moves forward by the gap and a repeated
one takes the first occurrence (both `fold=0`); this rule is now in spec
§5. With no `tz`, the zone is `$TZ`, then `/etc/localtime`, then UTC.
27 new tests (London and New York DST in both directions, month and year
ends, explicit offsets, sub-second truncation, later-stage rejections);
174 in all.

### 2026-10-21: M3, M4 and M5 done

`wpk step <dir>` and `wpk recover <dir>` work end to end with the fake
model (`tests/fakemodel/`). The target is a packet or project directory for
now; WPID prefixes and project names come with the registry in M6. New
modules: `lease`, `model`, `prompt` (+ `prompts/step.md`), `executor`,
`spawn`, `faults`, `tomlio`, and the settings half of `registry` and
`project` (defaults, then `config.toml`, then `project.toml`).

Decisions made while building:

- **E3 restores, not just rejects.** The executor keeps an in-memory copy of
  the committed files (status, memento, journal, `state/`, `children/`,
  `identity/`) taken after `step-start`. If the model changed any of them,
  they are put back byte for byte before `step-failed` is written.
- **The last allowed failure sets `FAILED` at once**, with the reason, rather
  than waiting for the next `wpk step` to notice.
- **Recovery sets `attempts` to the crashed attempt's number** instead of
  adding one, so recovering twice cannot double-count. A failed attempt
  writes `status.md` before `step-failed` for the same reason.
- **`state.diff` is made in Python** (difflib), so the executor does not need
  `diff` on the host.
- **Fault points take `<point>@<step>`**, e.g. `WPK_FAULT_AT=mid-spawn@8`.
  E2 kills at step 8, the step that spawns, so `mid-spawn` is exercised.
- **The checker allows a half-done commit.** While the journal has an
  unfinished `commit-begin`, a child link or a parent's missing listing for
  a child that commit is creating, and `state/` missing during the swap, are
  covered by the "unfinished commit" warning instead of being errors.
- **Recovery removes `.tmp-*` files** that a killed `atomic_write` leaves.
- Python 3.10's `fromisoformat` takes only 3 or 6 fraction digits;
  `clock.parse_iso` pads the fraction (found by the runner-image trial).

E1 (fake model), E2 (all eight fault points plus random external kills),
E3 and E4 pass. 208 tests, green on 3.12 locally and 3.10 in the runner
image.
