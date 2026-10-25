# Long-running projects: hand-off, workspaces and the runner

Status (2026-10-21): design, not built. Read this before the build plan at
the end. A fresh session should be able to pick up from this file alone.

Stage 1 runs packets that count to 8 in `state/`. This document is about
packets that do real engineering over days and weeks: a packet that holds
a clone of a repository, builds and tests it, and moves through a plan,
with a person setting it up, steering it and answering its questions. The
first candidate is `fw-uart16550` (featherweight-ip): an 11-step plan in
its `docs/design/plan.md`, steps 0–2 done.

Three ideas carry the design:

1. **Ownership.** At any moment a packet belongs to exactly one party: a
   person or the runner. Control moves between them only by an explicit,
   journaled **hand-off**.
2. **The packet is self-contained.** The repository it works on is cloned
   *inside* the packet, under `work/`, each by its own name. Nothing points
   outside the packet.
3. **A runner daemon** (`wpk runner`) does the work in the background, and
   the **board** (`wpk dash`) is where a person hands packets off, takes
   them back and answers them.

Contents: §1 ownership · §2 the packet's `work/` · §3 walkthrough for
fw-uart16550 · §4 the runner · §5 the board · §6 commands · §7 format
changes (spec v0.3) · §8 safety · §9 failure cases · §10 open questions ·
§11 build plan · status log.

## 1. Ownership and hand-off

| Owner | Who may change the packet | States |
|---|---|---|
| **human** | You, with any tool: an editor, a shell, `git`. Nothing has to go through `wpk` | `HELD`, `COMPLETED` |
| **runner** | Only the executor, one step at a time. You may ask for the packet back | `RUNNABLE`, `SLEEPING` |

The owner follows from the state, so there is no separate field to keep in
step. `HELD` carries a `held_for` reason and a free-text `reason`:

| `held_for` | Set when | Board column |
|---|---|---|
| `setup` | `wpk new` created the packet | Setup |
| `question` | the model wrote `ask:` in its memento | **Needs you** |
| `failed` | a step failed `max_attempts` times | **Needs you** |
| `limit` | a budget or rate limit was hit (§4) | **Needs you** |
| `taken` | you took it back (`wpk take`) | Held |

`COMPLETED` (`resume: done`) is also yours. It is not a dead end: give it a
new instruction and hand it off again, and the project carries on.

### The hand-offs

| Transition | How | What the executor checks and records |
|---|---|---|
| created → human | `wpk new` | `HELD`, `held_for: setup`. No instruction is needed yet |
| human → runner | `wpk handoff` or the board's **Hand off** | `memento.md` has an instruction; `wpk check` passes for the packet; each work repo under `work/` is on a branch. Your uncommitted changes in each work repo are committed as one commit by you ("handoff: …"), so the runner starts from clean trees. Then `RUNNABLE`, and a `handoff` journal record with each work repo's commit |
| runner → human, its choice | `ask:` in a memento; a step failing for the last time; a limit | Set in the same commit as the step that caused it (§7): `HELD` with the reason, the question in `reason` |
| runner → human, your request | `wpk take` or **Take back** | Not running: at once (it takes the lease, like `pause` today). Running: the request is left in `.take-request`; the step finishes or fails as usual and its commit ends in `HELD`/`taken` instead of `RUNNABLE`/`SLEEPING`. A step is never cut short |

Answering a question is just another round trip: take nothing (the packet
is already yours), read the question on the board, change what you want
(edit `memento.md`, add a note to `state/`, fix something in a work repo), and
hand it off. The next step's prompt includes the hand-off record, so the
model sees what you changed: the note you wrote with the hand-off, and the
work repo commits, if any.

Children are owned separately. A spawned child starts with the runner.
`wpk take <project>` takes the root only; `--tree` takes every packet that
the runner owns in the project.

## 2. The packet's `work/` directory

```
packets/<WPID>/
  status.md  memento.md  journal.jsonl     as in Stage 1
  state/        the packet's own documents: plans, outline, questions, notes
  work/         NEW: the workspace, a folder of repositories
    fw-uart16550/   a git clone, on branch wpk/<project>
    fw-hdl/         another clone, if the task changes it too
  steps/NNNN/   as in Stage 1, plus work.diff (see below)
```

**`work/` is a folder, not a repository.** Each directory directly under it
that is a git repository is a **work repo**. It keeps its own name, so paths
read `work/fw-uart16550/src/…` in prompts, refs and logs. A task that
changes several repositories clones each of them here.

- Repositories nested deeper are not work repos. The IVPM clones in
  `work/fw-uart16550/packages/` are an example. To change a dependency, you
  clone it at the top level on purpose (`work/fw-hdl`), and point the
  dependent repo at it.
- Anything else directly under `work/` that is not a repository is a warning
  from `wpk check`. Scratch files belong in `state/` or in a repo's ignored
  build directories.

**Plan documents live in `state/`, never in a work repo.** The design doc, the
plan, the outline, questions and progress notes are the packet's, not the
project's. `state/` versions them per step and rolls them back with a failed
step, and they stay out of the code's history. Commits in a work repo hold
code, tests and the project's own docs only.

**Steps and commits.** `state/` keeps its Stage 1 rule: the model edits a
copy in `.pending/state/`, and a failed step leaves no trace. That cannot
work for `work/`: a clone with its `packages/` (Verilator, Yosys, dv-flow
libraries) can be gigabytes, too much to copy every step. The model edits
the work repos in place, and **git** makes the step atomic instead. Every
rule below applies to each work repo separately:

| Point in the step (stage1-plan §4) | What happens in each work repo |
|---|---|
| Prepare | Record `base` = `HEAD` and the branch. The tree must be clean (it is, by construction: every hand-off and every step ends committed) |
| Model runs | Steps run with the packet as their working directory, so the model works in `work/<repo>/` directly. `.pending/` is unchanged |
| Step fails (any reason) | `git reset --hard base` and `git clean -fd`. Ignored files (`packages/`, `rundir/`, build output) are kept, so dependencies are not fetched again. Commits the model made are dropped from the branch (still in the reflog) |
| Commit | Inside the commit protocol, after `commit-begin`: in each repo that changed, stage everything and make one commit, message `step N: <first line of summary.md>`, with trailers `Wpk-Packet: <WPID>` and `Wpk-Step: N`. A repo with nothing to commit gets no commit. Save `git diff --stat base..HEAD` and the diff of every repo (with a header per repo, cut at 256 KiB in all) to `steps/NNNN/work.diff` |
| Crash in the middle | Roll-forward is idempotent, per repo: if `HEAD` already carries `Wpk-Step: N`, that repo is done; otherwise commit what is there. Roll-back is the failed-step reset of every repo |

Rules the executor enforces, each a failed attempt if broken:

- in each work repo, the branch must be the same at the end as at the
  start, and `HEAD` must descend from `base`;
- the set of work repos must not change during a step. Adding a repo
  (cloning) is setup: yours, or a step that asks for it.

The model may run `git commit` itself; the step commit then takes whatever
is left. The model must not push (§8).

Commits are authored by you (your git identity). The trailers say which
packet and step made them, and the board links each step to its commits.

**Environment for steps.** Tools such as `iverilog` and `yosys` come from a
repo's `packages/` through `direnv`. Claude Code's Bash tool does not load
`.envrc` on its own, so `project.toml` can name the repo whose environment
the steps run in:

```toml
step_env = "direnv:fw-uart16550"   # run claude under `direnv exec work/fw-uart16550`; default "none"
```

One environment per step is enough for the first version. The other repos'
tools are reached by path.

**Children** get no `work/` in the first version: only the root holds the
clones, and it works through the plan in order. A child that needs its own
workspace (a `git worktree` of each repo it needs) is §10.

## 3. Walkthrough: fw-uart16550

This is the process the build plan (§11) has to make work. Commands that
do not exist yet are marked *(new)*.

### 1. Create the project (you own it)

```bash
wpk new uart-dev --dir ~/work-packet-runs/uart-dev --model claude-sonnet-5
```

With no `--prompt`, the root is `HELD` for `setup` and has no instruction.
`wpk new` prints the root's directory. The board shows `uart-dev` under
**Setup**.

### 2. Set it up by hand

```bash
cd ~/work-packet-runs/uart-dev/packets/<root>     # or: wpk shell uart-dev (new)
mkdir work && git clone ~/projects/featherweight-ip/fw-uart16550 work/fw-uart16550
cd work/fw-uart16550
git remote set-url origin "$(git -C ~/projects/featherweight-ip/fw-uart16550 remote get-url origin)"
git switch -c wpk/uart-dev
# dependencies, once the repo has an ivpm.yaml (plan step 4 adds it):
#   ivpm update && direnv allow
```

Cloning from the local checkout needs no network and keeps the real remote
for when you push. The branch `wpk/uart-dev` holds everything the runner
does; `main` is untouched until you merge.

### 3. Set limits and permissions

`~/work-packet-runs/uart-dev/project.toml`:

```toml
model = "claude-sonnet-5"
step_timeout = "30m"
step_budget_usd = 2.00
budget_usd_per_day = 10.00        # (new) over this, the project is HELD for "limit"
max_steps_per_hour = 6            # (new) per packet; catches loops
step_env = "direnv:fw-uart16550"  # (new)

[permissions]
permission_mode = "acceptEdits"
allowed_tools = ["Read", "Write", "Edit", "Glob", "Grep",
                 "Bash(git status *)", "Bash(git diff *)", "Bash(git log *)",
                 "Bash(git add *)", "Bash(git commit *)",
                 "Bash(dfm *)", "Bash(verilator *)", "Bash(make *)",
                 "Bash(python *)", "Bash(ls *)"]
```

No `git push`, no `ivpm` (network) and no `rm -rf`: anything that needs
those comes back to you as a question.

### 4. Write the first instruction

Edit `memento.md` in the root (or `wpk instruct uart-dev`, *new*, which
opens your editor):

```markdown
You are working on the repository in work/fw-uart16550/ (branch
wpk/uart-dev). Read work/fw-uart16550/docs/design/plan.md §9 and continue with the first step that is
not started and lives in this repository (4, 5 or 6; step 3 is a separate
repository, skip it). Do one bounded piece of that step per run: write or
change the files, run the smoke checks the plan names (never the full
formal or upstream bench, they take hours), and update the step's status
in plan.md §9. Keep a short running log in state/progress.md.
If you need a decision, a tool you do not have, or network access, stop
and ask (put the question in `ask:`). Continue with resume: now.
```

### 5. Hand it off

```bash
wpk handoff uart-dev -m "Clone ready on wpk/uart-dev; start with step 4"   # (new)
```

or **Hand off** on the card. `wpk` checks the instruction and the clone,
records the hand-off and the work repo's commit, and the card moves to the
runner's side (**Ready**).

### 6. Let the runner work

Once, per machine *(new)*:

```bash
systemctl --user enable --now wpk-runner.service wpk-dash.service
```

The runner picks `uart-dev` up within seconds. Each step is one Claude
Code session in the packet; each committed step is one commit on
`wpk/uart-dev`. Watch it on the board: the card in **Running**, the
timeline growing, the step viewer showing the transcript as it runs and
the `work/` diff when it commits.

### 7. When it needs you

The model writes, say,

```yaml
resume: now
ask: "Plan §7 wants DFM_JOBS=2 but the U-tests time out at 30m. Raise step_timeout, or split the tests?"
```

and the step commits as `HELD`/`question`. The card moves to **Needs you**
with the question on it (and, later, a desktop notification). You read
the last steps, make a change (raise `step_timeout` in `project.toml`, or
write the answer in the instruction), and **Hand off** with a note. The
next prompt includes your note.

### 8. Taking it back and reviewing

Any time: **Take back** (or `wpk take uart-dev`). If a step is running, it
finishes first. Then the packet is yours: look at `git log wpk/uart-dev`
in `work/fw-uart16550/`, fix things, and push the branch when you are happy:

```bash
cd ~/work-packet-runs/uart-dev/packets/<root>/work/fw-uart16550 && git push -u origin wpk/uart-dev
```

Then hand it off again, or leave it held.

## 4. The runner daemon

`wpk runner` runs in the foreground; the systemd user unit runs it in the
background. It is `wpk tick` in a loop, plus what a loop needs:

- **One per runner home.** It holds an `flock` on `$WPK_HOME/runner.lock`;
  a second one exits with a message naming the first one's PID.
- **Loop.** Every `interval` (30 s), or at once when poked, run one
  scheduler pass (`scheduler.run_pass`): due packets, oldest first, up to
  `max_concurrent` (`-j`) at a time, each `wpk step` as a subprocess. It
  does not wait for a pass to finish before it can start the next step:
  a free slot is filled at the next wake.
- **Poke.** The board and the CLI touch `$WPK_HOME/runner.poke` after a
  hand-off; the runner checks its mtime every second, so a hand-off starts
  running within about a second instead of at the next interval.
- **Limits**, checked before starting a step, from `meta.json` costs (what
  was spent, not estimates):
  - `budget_usd_per_day` per project, in the project's time zone;
  - `max_steps_per_hour` per packet.
  Over a limit, the packet goes to you as `HELD`/`limit`, with the figures
  in `reason`. `max_concurrent` (global) just waits for a slot.
- **Events.** One JSON line per event in `$WPK_HOME/events.jsonl`: step
  started, committed or failed; hand-off either way; limit hit; runner
  started or stopped. The board will use it for live updates (Stage 2
  SSE) and notifications; nothing reads it to make decisions.
- **Stopping.** `SIGTERM`: start nothing new, wait for running steps to
  end, exit. A second `SIGTERM`, or the unit's stop timeout, ends the
  runner but not the steps: each step is its own process with its own
  lease and finishes or fails on its own; the next runner sees the
  outcome. `kill -9` of the runner loses nothing either.
- **Logs.** One line per step to stderr (the journal under systemd), the
  same lines `wpk tick` prints.

Units, installed by `wpk runner --install-units` *(new)* into
`~/.config/systemd/user/`:

```ini
# wpk-runner.service
[Unit]
Description=work-packet runner
[Service]
ExecStart=%h/.local/bin/wpk runner
Restart=on-failure
TimeoutStopSec=35min
[Install]
WantedBy=default.target
```

`wpk-dash.service` is the same with `wpk dash`. `loginctl enable-linger`
keeps both running when you are logged out. *(`docs/server.md` §5 replaces
the two units with one daemon, `wpkd`, which also puts the board on the
tailnet with a login.)*

## 5. The board, with actions

The board stays a reader of the files, and gains a few **POST** actions,
each one exactly a CLI command (no logic of its own):

| Where | Action | Same as |
|---|---|---|
| Card, packet page | **Hand off** (with a note box) | `wpk handoff <wpid> -m …` |
| Card, packet page | **Take back** | `wpk take <wpid>` |
| Packet page (yours) | **Instruction** editor | writes `memento.md` (only while you own it) |
| Board | **New project** form: name, directory, model | `wpk new` |
| Packet page (runner's, sleeping) | **Wake now** | `wpk wake <wpid>` *(new)*: `SLEEPING` → `RUNNABLE` |
| Project page (yours) | **Settings**: limits, model, allowed tools | `wpk set` / `wpk allow` / `wpk deny` |
| Needs-you card | **Answer** each question, or **Take the recommendations**; a permission question has **Grant** | writes the answers into the hand-off note, runs `wpk allow` for a grant, then `wpk handoff` |

Columns, in two lanes:

| Yours | | | | Runner's | | |
|---|---|---|---|---|---|---|
| **Needs you** (question, failed, limit) | Setup | Held | Done | Running | Ready | Sleeping |

A card in **Needs you** shows the question or the failure, and how long it
has waited. The project page links each step to its work repo commits and
shows `work.diff` in the step viewer.

Because the board can now change things: it binds to `127.0.0.1` only;
every POST must carry a token that the server puts in its own pages
(generated at start), and a matching `Host`/`Origin`, so another site in
your browser cannot drive it. Reaching it from Windows is an SSH tunnel,
as now.

### Viewing (later)

Two improvements to what the board shows. Both stay read-only.

**Session status and the raw transcript.** Today the step viewer turns
`transcript.jsonl` into blocks (`dash/data.py`, `transcript()`): model text,
tool calls, results and thinking. On a long step that is too much to follow,
and the original records cannot be seen at all. The step viewer gets three
views of the same file:

- **Status:** a feed of what the session is doing, one line per event: the
  model's text, each tool call as its name plus the command or path, test
  and build results as pass/fail when the tool output shows it, and context
  size and cost from each message's `usage`. While a step runs, the latest
  line also shows on the board's card and the packet page ("running
  `pytest -q`, 4 min, 61k context").
- **Transcript:** the blocks, as today.
- **Raw:** the JSONL records as they are, pretty-printed, one per record,
  with a link to download the file.

Two things the status feed could use, if they prove worth it:

- the model's own progress notes. Claude Code's `TodoWrite` calls are in
  the transcript already, and the feed could show the current list;
- the C3 budget hook's messages.

**Rendered Markdown.** The state viewer (packet page), the memento, step
summaries and the step's "memento it wrote" show Markdown as plain text.
They get a rendered view, with a toggle back to the source. Plans and
outlines in `state/` are most of what you read on the board. The text is
written by the model, so render it safely:

- raw HTML off, and links limited to `http`, `https` and relative paths;
- render on the server (for example `markdown-it-py` in the `dash` extra),
  so the page needs no script;
- show only `.md` files rendered; other files stay as text.


## 6. Commands

| Command | Does |
|---|---|
| `wpk new <name> [--prompt …]` | Without a prompt: root `HELD`/`setup`. With one: as Stage 1, but still `HELD` unless `--handoff` |
| `wpk shell <target>` | A shell in the packet directory (in `work/<repo>` if there is exactly one), with `WPK_WPID` set. A convenience; you can just `cd` |
| `wpk instruct <target> [--file F]` | Edit `memento.md` in `$EDITOR` (yours only) and validate it |
| `wpk handoff <target> [-m NOTE]` | human → runner (§1); pokes the runner |
| `wpk take <target> [--tree]` | runner → human, now or at the end of the running step |
| `wpk wake <target>` | `SLEEPING` → `RUNNABLE` early |
| `wpk runner [-j N] [--interval 30s] [--install-units]` | The daemon (§4) |
| `wpk pause` / `wpk resume` | Kept as aliases of `take` / `handoff` |
| `wpk set <target> key=value …` | Change a `project.toml` setting (limits, `model`, `step_env`) with the same checks as `wpk check`; journal record `config`. Allowed while you own the packet |
| `wpk allow <target> <tool>…` / `wpk deny <target> <tool>…` | Add or remove `[permissions] allowed_tools` entries, e.g. `wpk allow dvs-enh Bash` or `'Bash(git commit *)'`; journal record `config` |

## 7. Format changes (spec v0.3)

- `status.md`: states `RUNNABLE`, `SLEEPING`, `HELD`, `COMPLETED`.
  `PAUSED` and `FAILED` are read as `HELD` with `held_for: taken` and
  `failed`. New field `held_for` (required when `HELD`). `wpk` writes
  `wpk: 0.3`; `wpk check` accepts 0.2 packets and says how they map.
- `memento.md`: new optional `ask: <question>`. With `ask:`, the step
  commits as `HELD`/`question` whatever `resume` says; `resume` is kept
  as the plan for after the hand-off back. Optional `choices: [...]` for
  the board to show as buttons later.
- Journal records:
  - `handoff`: `t`, `to` (`runner`/`human`), `by`, `why` (`setup`,
    `question`, `failed`, `limit`, `taken`, or `handoff`), `note`,
    `work_head` (a map: repo → commit);
  - `take-request`: `t`, `by` (the request made while a step runs);
  - `commit-begin`'s decision gains `work_base` (a map: repo → commit)
    and `held_for`.
- `.take-request` in the packet: present while a take waits for a step to
  end. Like `.lease`, it is not part of the committed files, so writing
  it during a step does not trip E3.
- `steps/NNNN/work.diff`: the step's change to every work repo, one
  section per repo.
- `work/`: optional; a directory whose entries are git repositories (work
  repos). `wpk check` warns about an entry that is not a repository, and
  about a dirty tree while the runner owns the packet.
- `step_env`: `"none"` or `"direnv:<repo>"`.
- Journal: `work_head` (in `handoff`) and `work_base` (in `commit-begin`)
  become maps from repo name to commit.
- The step prompt gains: who handed the packet over and their note, each
  work repo's branch and `HEAD`, and that work repos are edited in place.
- `state/` is where plan documents live; the protocol prompt says so, and
  that they are never committed to a work repo.

## 8. Safety

- **Bash** is what makes this useful and what makes it risky. The allowed
  list is per project and shown on the board. A Bash-capable model can
  write anywhere your user can; the E3 check (snapshot of the committed
  files) still catches writes to the packet's own files, and the reset of
  the work repos catches stray edits in them, but nothing stops a write to
  `~/` beyond the allow-list itself. Keep the list narrow; prefer named
  commands to `Bash(*)`.
- **No network by default.** `ivpm update`, `git fetch`, `pip install` are
  yours, during setup or when the packet asks.
- **No push.** Pushing is yours, after review. (If that changes, it is
  `Bash(git push origin wpk/*)` and nothing wider.)
- **Spend** is bounded per step (`step_budget_usd`), per project per day
  (`budget_usd_per_day`), and per hour of looping (`max_steps_per_hour`).
- **Reads are not confined to the packet.** Claude Code's Read, Glob and
  Grep reach any path your user can read; the dv-solve trial read
  `~/xezim_research/` with no `identity/` link. The packet boundary holds for
  writes only, unless reads are denied by path in the permission settings.
- **Side effects outside `work/` are not rolled back** on a failed step.
  Idempotency keys (roadmap Phase 1) are still to come; until then,
  allowed commands should be ones that are safe to repeat.

## 9. Failure cases

| What fails | What happens |
|---|---|
| A step fails | `state/` as in Stage 1; each work repo reset to its `base`. After `max_attempts`, `HELD`/`failed` (Needs you) |
| Runner killed | Running steps carry on as their own processes and finish; nothing new starts until a runner is back |
| Machine off | Leases expire; the next runner's pass recovers crashed steps (work repo resets included) and runs what is due |
| You edit a packet the runner owns | The E3 check fails the step if it is one of the committed files; edits in a work repo are lost by the reset of a failing step or folded into the next step's commit. The board says "the runner owns this; take it first" |
| Take requested during a step that then fails | The failed attempt is recorded as usual; then `HELD`/`taken`, not a retry |
| Model asks every step | `max_steps_per_hour` does not help (each ask waits for you); the board's Needs-you age shows it |
| Clone grows large | Only `steps/*/work.diff` is per step; the work repos are not copied |

## 10. Open questions

1. **Long runs.** A full formal run takes 17 min; the upstream bench, up to
   two hours. A step should not sit in Claude Code that long. Likely
   answer: a `job:` directive. The step starts a command in the
   background (in its own session, so it outlives the step), the packet
   sleeps, and the runner wakes it when the job exits, with the exit code
   and log tail in the next prompt. Needs the runner to track jobs.
2. **Children with workspaces.** A child that works on its own branch in a
   `git worktree` of each of the parent's work repos it needs; merging back is the parent's
   step. Not needed for a single packet working through a plan.
3. **Messages without a hand-off.** "Use fw_fifo" sent to a sleeping
   packet without taking it. A `mailbox/` read into the next prompt
   (roadmap Phase 3). Take, edit and hand off covers it for now.
4. **Model per step.** A cheap model for routine steps and a stronger one
   when stuck (`model:` in the memento).
5. **Notifications** for Needs you: `notify-send`, or a webhook to the
   phone.

## 11. Build plan

Each milestone keeps every Stage 1 test green, adds its own tests against
the fake model, and updates the status log below.

The server milestones S1–S3 (`docs/server.md` §7) slot in around these:
S1 (board on the tailnet, with login) can be built now, S2 (one daemon)
follows L3, and L4's POST actions sit behind S1's checks.

### L1: Ownership in the format

- [ ] Spec v0.3 (§7) in `docs/spec.md`; schema and `wpk check`, reading
      0.2 packets.
- [ ] `HELD` + `held_for` replace `PAUSED`/`FAILED` in the executor;
      failure after `max_attempts` hands off with `failed`.
- [x] `ask:` in the memento (2026-10-23, docs/l1a-plan.md). For now the
      commit ends `NEEDS_INPUT`, which v0.3 will read as `HELD`/`question`.
      Why it came first: the dv-solve trial stands in for a gate with `resume: fail`,
      and the packet shows as `FAILED` (red on the board) when it only
      wants a review. The body of a memento with `ask:` is the instruction
      for *after* the answer, so the step after a gate needs no new
      instruction from you; your answers arrive as the hand-off note.
- [x] `wpk set`, `wpk allow`, `wpk deny` (§6; 2026-10-23). Editing `project.toml` by
      hand stays possible at setup, but is not the way to change a running
      project.
- [x] `wpk handoff [-m NOTE | --note-file F]` (2026-10-23): from
      `NEEDS_INPUT`, `PAUSED` or `FAILED`; the note and the question are in
      the next step's prompt. Ownership (`by`) is recorded but not yet
      enforced.
- [ ] `wpk new` without a prompt; `wpk take` (including
      `.take-request` at the end of a running step), `wpk instruct`,
      `wpk wake`, `wpk shell`.
- Tests: every hand-off in §1, including take during a running step
  that commits and one that fails, and the crash points between them.

### L2: `work/`

- [ ] Base, reset, step commit and `work.diff` per work repo (§2), inside
      the commit protocol, with new fault points (`after-work-commit`, …) in the
      crash suite.
- [ ] Hand-off commits your changes in each work repo; checks branches and
      clean trees.
- [ ] `step_env = "direnv:<repo>"`.
- [ ] Prompt section for `work/`; plan documents in `state/`.
- Tests: a fake behaviour that edits two work repos and fails; one that
  commits itself; one that switches branch (must fail); one that adds a
  repo during a step (must fail); a SIGKILL at each new
  fault point leaves every work repo either at `base` or at the step commit.

### L3: The runner

- [ ] `wpk runner`: lock, loop, poke, limits, events, SIGTERM.
- [ ] `--install-units`; docs for `enable-linger`.
- Tests: with the fake model and fake clock: one runner per home; a
  hand-off is picked up within 2 s of a poke; daily budget holds a
  project; a SIGTERM waits for steps; a killed runner loses nothing.

### L4: Board actions

- [ ] Two lanes and the new columns; Needs-you cards with the question.
- [ ] POST actions with token and Host/Origin checks; instruction editor;
      New project form; links from steps to `work/` commits.
- Tests: each action through the app equals its CLI command; a POST
  without the token or from another origin is refused.

### L4b: Board viewing (later)

- [ ] Step viewer: Status, Transcript and Raw views of `transcript.jsonl`;
      the running step's latest status line on the card and packet page.
- [ ] Rendered Markdown with a source toggle: `state/*.md`, the memento,
      summaries.
- Tests: a transcript with each record kind gives the right status lines;
  Markdown with raw HTML, `javascript:` links and images is rendered inert.

### L5: fw-uart16550 for real

- [ ] Walk through §3 by hand, with Sonnet, for a week of steps. Record
      cost, steps, questions asked, and what went wrong.
- [ ] Decide on §10.1 (long runs) from what it shows.

## Status log

### 2026-10-21: design

Written after E7. Decided with the user: a packet is owned by a person or
the runner, never both, and control moves only by hand-off; the clone
lives inside the packet in `work/`; the runner runs as a daemon. Not yet
decided: the model and budget for fw-uart16550 (the walkthrough assumes
Sonnet and $10 a day), and whether the runner may ever push.

### 2026-10-23: `work/` is a folder of repositories
Decided with the user: `work/` holds one or more clones, each under its own
name, instead of being the clone. Every §2 rule applies per repo;
`step_env` names a repo; `work_head` and `work_base` become maps. Plan
documents live in `state/` and are never committed to a work repo. Found
while setting up the dv-solve trial (`docs/trial-dv-solve.md`).

### 2026-10-23: board viewing added (later)
Asked for by the user while starting the dv-solve trial: session status
updates and the raw transcript in the step viewer, and rendered Markdown in
the state viewer. §5 "Viewing (later)" and L4b.

### 2026-10-23: from the dv-solve trial's first step
The planning step stopped as told, with `resume: fail` standing in for a
gate. It shows as `FAILED`, which is wrong for "please review": `ask:` and
`HELD`/`question` (L1) come first. Settings and permissions must be changed
from the CLI or the board (`wpk set`, `wpk allow`; L1, L4), not by editing
`project.toml`. And the step after a gate must not need a new instruction:
the gate step writes the instruction for after the answer, and the answer
comes as the hand-off note. The step could also read `~/xezim_research/`
without an `identity/` link: Claude Code's Read reaches outside the packet,
so §8's boundary holds for writes only.
