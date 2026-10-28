# Experiment: does a task outline focus context?

Status: plan (2026-10-23). Nothing is built yet. This file holds the plan
and a status log, so a fresh session can pick up from it alone.

## 1. The question

The proposal: a packet carries an ordered outline of tasks with a cursor. The
executor shows the model only the current item, with its parents' goals in
one line each and the remaining items as titles. An item can expand into
sub-items, and it stays current until it is done. The questions:

1. Does focusing on one item lower the cost and context per finished item,
   without lowering quality?
2. Does an executor-owned outline add anything over a memento that the model
   keeps focused on the current item?
3. Can the model tell when a task is worth the structure, and pick the right
   amount of it?
4. Is Beads (`bd`) good enough as the store, so we build only the executor
   side?

## 1a. The shape

The shape is not settled. This is the candidate the experiment tests,
revised after the paper simulation
(`docs/experiments/stack-fw-proto-chi/simulation.md`, §9).

### Outline and cursor

An ordered tree. The board shows it as a checklist. Parallel work uses child
packets (`spawn`), not a dependency graph.

| Status | Meaning | Cursor |
|---|---|---|
| `pending` | not started | can take it |
| `active` | being worked on | stays on it |
| `done` | its checks passed | skips it |
| `blocked` | waits on a gate (below) | skips it |
| `deferred` | put off, with a reason; it moves to a later phase or to `Backlog` | skips it |
| `dropped` | will not be done, with a reason | skips it |

**The cursor** is the first leaf, in order, that is `active` or `pending`.
The simulation's worst failure was a cursor that stopped on work that had
been put off (the P1 remainders before P2; P3 before the formal work).
`deferred` and the operations `move`, `insert`, `defer` and `drop` fix that.

A phase can close with deferred children only by moving them, to a later
phase or to a top-level `Backlog` item. Deferred work stays visible and is
never lost.

### Item kinds

- **work**: `title`, `goal`, `refs` (paths and design-doc sections),
  `checks` (a list), `status`, `notes`, `children`.
- **research**: `question`, `deliverable` (a file or a design-doc section),
  `max_steps`. It is done when the deliverable exists and answers the
  question. Its outcome is usually questions filed to a gate, or new items.
  Examples from fw-proto-chi: the naming survey (L382), credits (L541),
  formal above RTL (L3100), dv-solve against Bitwuzla (L3925).
- **gate**: below.

### Gates collect questions; items depend on answers

A gate is a dedicated item, and questions can be added to it at any time,
not only by the item just before it:

```yaml
- gate: design-signoff
  mode: always            # always | if-open | notify
  questions:
    - id: q-socket-home
      text: Do fw_socket/fw_mirror live in fw-hdl, or stay local for now?
      recommend: fw-hdl
      raised_by: 1.2
      answer: null
      provisional: true   # work continues on the recommendation
  dependents: [5.1.2, 5.1.3]   # items that need an answer
```

- **Filing.** An item that hits a decision files a question to the next
  gate in the outline, or to a named one, and keeps going. Questions that
  arise during implementation (decision 1 asked again at L1506; xezim unable
  to parse fw-hdl) go to the gate of the current phase. The executor inserts
  that gate if the phase has none.
- **Dependents.** Each question lists the items that need its answer.
  - With `provisional: false`, those items are `blocked` until the answer
    comes.
  - With `provisional: true`, they go ahead on the recommendation and are
    marked as provisional. If the user answers differently, they reopen.
- **When it fires.** When the cursor reaches the gate, or earlier when
  every remaining item is blocked. Only then does the packet stop
  (`HELD`/`question`). The packet stops only when it truly cannot go on, and
  it asks its questions in batches, not one at a time.
- **Modes.**
  - `always`: block for sign-off, even with no questions (sign-off of the
    design itself).
  - `if-open`: block only if there are unanswered questions.
  - `notify`: go ahead on the recommendations, show them on the board, and
    let a later answer reopen dependents.
- **The step that stops at a gate writes the instruction for after it.**
  The memento's body is what to do once the questions are answered, so
  resuming after a gate needs no new instruction from you. (The dv-solve
  trial's first step wrote "do not start until answered" instead, which
  left you to write the next instruction by hand.)
- **A permission request is a question too** ("needs Bash for builds and
  tests"). Answering it grants the permission (`wpk allow`), so you don't
  edit `project.toml`.
- **Answers** come from the board or the hand-off note: per question, or
  "take the recommendations". The answers are recorded in the gate, so
  "why is it like this?" has one place to look.

### Checks accumulate

`chi_flow_check` was reopened four times. Each time, a later item brought a
stronger check. So:

- When an item closes, its `checks` join its phase's **regression set**.
- Later steps in the phase run the set, or a cheap part of it, before their
  own close.
- A later item can add a check to an earlier one (`add-check`).
- A regression that fails does not silently reopen the closed item. It
  inserts a fix item linked to it (`fixes: 5.3.4`), so the history shows
  the rework. Reopen counts are a metric in §6.

### Workspaces with several repos

Repositories that the work changes are cloned into the packet, each under
its own name in `work/` (`work/fw-proto-chi`, `work/fw-hdl`). Every git
repository directly under `work/` is in scope; the IVPM clones nested in a
repo's `packages/` are not (long-running.md §2).

- **The step commit covers every clone in scope.** The journal records one
  commit per clone per step.
- **Item `refs` name paths**, so the repo follows from the path. No separate
  `repo` field is needed.
- **Pushing is never a step action.** A gate grants it, per repo, or you do
  it at take-back. Commits on `wpk/` branches are the packet's own record.
  Your rule ("nothing committed until I ask") applies to your branches and
  to pushes.
- `long-running.md` §2 now describes this (2026-10-23).

### Long jobs

A step that starts a job taking hours (the 25–90 minute mutation runs; the
2.5-hour ones) ends with `resume: wait job:<id>`. The runner wakes the
packet when the job's exit file appears, or at a timeout. This is a resume
expression (spec §5), not an outline feature.

### Triage

The first step sorts the request into a template:

| Template | When | Outline |
|---|---|---|
| `direct` | a bounded change, clear from the request | none: the memento only, as today |
| `list` | several known pieces, nothing to decide | a handful of work items, no gates |
| `project` | new design, open questions, many sessions | design → gate → detailed plan → gate → implement, and `Backlog` |

The model adapts the template. For fw-proto-chi, the simulation folds the
plan into the design doc's phase table and makes the plan gate `notify`. The
model can promote a task later. You see only the checklist and the gate
questions.

### Sessions

The simulation shows that a fresh session for every leaf costs too much in
cache writes: input cost falls only 31–42%, while context per call falls
about 3×. So:

- **Carry the session within a phase.**
- **Start fresh** at a phase boundary, after a gate, or when the C3 budget
  hook fires.

E2 measures both.

### One place for each fact

- The outline holds order, status, checks and questions.
- The design doc holds the reasoning.
- No status goes in the design doc. In fw-proto-chi, §13 grew to about 200
  lines that every resume re-read.

## 2. What the history already tells us

fw-proto-chi (`~/projects/featherweight-ip/fw-proto-chi`) was built in two
Claude Code sessions on 2026-10-10..12. The extracted prompts and per-segment
statistics are in `docs/experiments/stack-fw-proto-chi/` (`users.txt`,
`seg1.txt`, `seg2.txt`, and the scripts that made them).

| Session | API calls | Peak context | Cache read | Output |
|---|---|---|---|---|
| main | 665 | 620k | 168M | 849k |
| docs | 154 | 428k | 45M | 132k |

- Orientation (re-reading the design doc, §13, and code after a resume) was
  about 40–50 calls, roughly 6% of all calls.
- The average context per call was about 250k, and the user ran `/compact`
  six times (at 398k, 621k, 275k, 189k, 393k and 58k).

So almost all the cost came from **carrying context**, not from re-reading the
plan. The hypothesis to test is therefore mostly about **item boundaries as
session boundaries**: start a fresh session per item, and keep each item's
context bounded. Fewer orientation calls is secondary.

## 3. The corpus: fw-proto-chi, phases P0 and P1

Why this slice:

- Its seed prompt survives verbatim (transcript `e0d42399…`, line 5), plus
  two early corrections: "as long as the unit tests have the transactor APIs,
  it doesn't matter what implements them", and "I'm not positive that
  fw-proto-core is still relevant".
- The design doc's §10 gives each phase a "Done when" check, and §13.2 names
  the exact commands (`dfm run tests`, `fv`, `fv-prove`, `fv-cover`,
  `fv-teeth`, `ci/run.sh`).
- P0 and P1 stayed close to the plan. Later work (F3 mutation testing, F4
  proofs, dv-solve, Sphinx) was scope the user added after the plan, which a
  replay cannot reproduce fairly. The slice ends at P1.

What is missing, and how we fill it:

| Gap | Fill |
|---|---|
| The user never signed off on the plan (§12 items 2–8 unanswered; Claude took its own recommendations) | Scripted gate answers: the design gate gets "proceed to implement" plus the decisions actually made (the `fw_socket #(I,E)` / `fw_mirror #(I,E)` names; socket/mirror live in fw-hdl). Any other `ask` gets "take your recommendation" |
| No pass/fail was recorded per item at the time | We write a reference item list for P0+P1, each with a `check:` command, from §10, §13.1 and the narration at transcript lines ~577–1616 |
| The original design doc was committed only in its final state | Recover the 2026-10-10 version from the 49 KB Write input in the transcript (near line 331), then apply the naming decision |
| Dependencies have moved on (fw-hdl has the socket now, `d5d17c1`) | Pin fw-hdl and the other `packages/` to commits from before 2026-10-10 |

## 4. Two experiments

### E1: planning (cheap)

Input: the seed prompt, the recovered design doc, and the item "create a plan
from the design". Output: the items the model pushes.

Score it against the reference list: coverage (does every reference item map
to one?), granularity (how many steps per item, once executed), and whether
each item has a runnable check. Use 3 runs. This tells us whether the
model's own expansion is usable, separately from execution.

**Triage** (E1b, first step only, very cheap): give the model a mix of
requests and check which template it picks.

- fw-proto-chi's seed (expect `project`);
- a fw-uart16550 plan step (expect `list` or `direct`);
- a few one-line fixes from the work-packet history (expect `direct`).

Also check that its design-gate questions for fw-proto-chi include the
decisions that were actually made: the socket names, and socket/mirror
living in fw-hdl.

### E2: execution (the real test)

Every arm starts from the same snapshot and the same signed-off design doc.
Every arm gets the **same reference item list**, so planning variance does
not confound the comparison.

| Arm | What the model sees each step | Sessions |
|---|---|---|
| A: plan doc | Instruction in the fw-uart16550 style: "read the plan, continue with the first item not done, update its status" | C4 rules as today |
| B: focused memento | The model keeps the memento body to the current item, with refs and a check; the plan is in a file it may read | C4 rules as today |
| C: executor outline | The top item in full, parent goals in one line, the remaining items as titles; changes go through memento front matter | Carried within a phase; fresh at phase boundaries, after gates and on the budget hook (a variant C-leaf starts fresh per leaf). The executor runs the item's checks and the regression set before it accepts done |
| C′: Beads | Like C, but the store is `.beads/` in `work/`; the executor uses `bd ready --json` and checks the close | Same as C |

- A vs B measures what focusing the prompt is worth.
- B vs C measures what the outline mechanism adds (session boundaries,
  checks, less drift).
- C vs C′ decides whether we need our own format.

## 5. Driver

The runner's `work/` support (long-running.md L2) is not built yet, so the
first driver is a standalone script, `experiments/stack/run.py`:

- one git worktree of the snapshot per arm and run;
- a loop of `claude -p` steps, reusing `harness/claude.py`, the hooks and the
  C1 usage records from `meta.json`;
- the prompt layout per arm, built by the script;
- a fake user that answers gates from the script in §3.

The script also prototypes the prompt layout before we fix a format in the
spec.

## 6. Metrics

Per arm and run, per finished item and in total:

- cost, API calls, mean and peak context per call, wall time;
- end state: §10's P0 and P1 checks (`l1_basic` in `tlm` and `xtor`, the
  socket tests, `l0_link` in both views, `fv`, `fv-cover`, `ci/run.sh`);
- rework: item checks that failed, items reopened, files rewritten after
  their item closed;
- focus: how much of each step's diff lies outside the item's refs (scope
  creep), and items done ahead of their turn;
- interventions: asks, C3 budget-hook firings, stalls.

## 7. Cost control

- Start with **P0 only, Sonnet, one run per arm**. It is small and has a
  clean done check.
- Go on to P0+P1 with 2 runs per arm only if P0 shows differences larger
  than the run-to-run variance we saw in E7.
- Set a per-run budget cap (`--max-budget-usd`) and a wall-clock cap.

## 8. Build plan

- [ ] X1: Recover the 2026-10-10 design doc from the transcript; apply the
  naming decision.
- [ ] X2: Make the snapshot: fw-proto-chi at `b13ffe3` plus `design.md` and
  the spec, with `packages/` pinned to commits from before 2026-10-10. Check
  that `dfm run tests` builds an empty suite.
- [ ] X3: Write the reference item list for P0 and P1, each with a goal,
  refs and a `check:`.
- [ ] X4: Write `experiments/stack/run.py` with arms A and B; then C; then
  C′.
- [ ] X5: Run E1 (3 runs) and the E1b triage set.
- [ ] X6: Run E2 on P0, one run per arm; write up the results here.
- [ ] X7: Decide: go on to P1, change the shape, or drop it.

## Status log

### 2026-10-23: plan
Reviewed fw-proto-chi's design doc and both session transcripts. There is
enough material for a seed prompt, a reference plan, and scoring for P0 and
P1. The history points at carried context, not plan re-reading, as the cost
to cut.

### 2026-10-23: shape revised
The paper simulation (`docs/experiments/stack-fw-proto-chi/simulation.md`)
led to the §1a changes: `deferred` and `blocked`, research items, gates that
collect questions and have dependents, regression sets, several clones in
`work/`, `resume: wait job`, and sessions carried within a phase.
