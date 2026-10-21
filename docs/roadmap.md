# work-packet roadmap

Naming (2026-10-21): the project is **work-packet**, and the command is `wpk`
(the runner daemon is `wpkd`). A **packet** is what the earlier notes called an
agent process: a directory holding everything needed to pick the work up
again. A packet ID (`WPID`) replaces the APID. "Agents as processes" is still
how we explain the idea. The prototype in `prototype/` keeps its old names.

Status (2026-10-21): roadmap drafted. Nothing below has been built yet. The
`work-packet/work-packet` repo exists, seeded from the original `agent-proc`
notes. Stage 1 (Phase 0, Phase 1 and the first slice of `docs/runner.md`) is
planned in detail in `docs/stage1-plan.md`.
Runner, dashboard and `wpk new` design: `docs/runner.md`.
Slides: `slides/work-packet.pptx` (25 slides; "User experience" section is slides 15–21), built from
`slides/build_deck.js`, `slides/prior_art.js` and `slides/ux.js`.

## The main lesson from the prototype

In the prototype, the model does the executor's bookkeeping itself. It
counts, spawns children, sleeps and names its own files. Every gap we found
comes from that:

- `prototype/sub`: the last step ran twice. `count.md` is 9 against a limit of 8,
  and there are two identical children.
- bf474803: it reported "5 times" but wrote 6 lines.
- File names drift between packets.
- Steps sleep inside a single model call instead of yielding.

The roadmap splits the work in two:

- **The executor** is a small, deterministic program. It owns the clock,
  step numbers, commits, scheduling and spawning.
- **The model** does one unit of work. It proposes the next state, but the
  executor commits it.

Durable-execution systems (Temporal, Restate, DBOS) split it the same way:
non-deterministic work runs inside steps, and a deterministic runtime records
them.

## Scheduled resumption (resume later)

A packet can ask to be woken at a future time. This lets one packet run
periodically for weeks or months, and it costs nothing while it waits.

| What the agent writes | Meaning |
|---|---|
| `resume: now` | The default: runnable again straight away |
| `resume: in 10 days` | A one-shot timer, relative to when the step commits |
| `resume: 2027-01-10 09:00` / `resume: on 10 Jan` | A one-shot timer at an absolute time; "10 Jan" means the next one in the future |
| `every: monday 08:00` | A recurrence rule kept by the executor |
| `wait: child <WPID>` / `wait: message` | Wake on an event, optionally with a time limit (`until: in 3 days`) |

### Design rules

1. **The model never does date arithmetic.**
   - The agent writes the expression.
   - The executor resolves it to an absolute UTC `wake_at` at commit time,
     using its own clock (`date -d`, dateutil or similar) and the packet's
     time zone.
   - It stores both the original expression and the resolved instant, so a
     wrong resolution is visible in `status.md`.
2. **Recurrence belongs to the executor, not the memento.**
   - If the agent re-schedules itself each time, one failed or forgetful step
     ends the cycle.
   - With `every:`, the executor re-arms the timer even after a failed step.
   - The agent can still override the next wake once, for example "build
     still red, check again in 2 days".
3. **Missed wakes catch up once.** If the machine was off at `wake_at`, the
   packet runs once at the next tick, not once per missed slot. This is the
   policy of systemd `Persistent=true` and anacron. The wake prompt says how
   late it is: "due 2027-01-10 09:00, running 3 days late".
4. **The wake prompt carries the context.** It includes:
   - the current time and the scheduled time;
   - why it slept (the original expression);
   - what changed in `identity/` since it slept (dependency versions, dv-flow
     cache) and which model is running now.
5. **Timers can be changed from outside.**
   - A human or the parent can edit `wake_at` or cancel the timer.
   - A message in the mailbox can wake the packet early. This is a race
     between the timer and the event, like a Temporal signal with a timer.
6. **Long sleeps need a pinned environment.**
   - Record the model version and an identity snapshot when the packet goes
     to sleep.
   - On wake, warn or fail if the model has been retired or credentials have
     expired.
7. **Use a fake clock for tests.**
   - `WPK_NOW` overrides the executor's clock, so tests of "in 10 days"
     and "every Monday" finish in seconds.
   - This copies Temporal's time-skipping test server.

### How prior art handles "later"

| System | One-shot | Recurring | Cost while waiting |
|---|---|---|---|
| Temporal | Durable timers (`workflow.sleep`) | Schedules | Worker idle; server keeps the timer |
| Cloudflare Agents | `schedule(delay \| Date, cb)` | `schedule(cron, cb)` | Durable Object sleeps; alarm wakes it |
| Inngest | `step.sleep`, `step.sleepUntil` | Cron triggers | None on your side |
| Restate / DBOS | Durable sleep, delayed calls | DBOS scheduled workflows | Runtime keeps the timer |
| LangGraph | None in the open-source library | Platform cron jobs | Thread checkpoint in the DB |
| cron / at / systemd timers | `at` | cron, `OnCalendar` | None |
| Ralph loop, Quine, Claude SDK sessions | None built in (they run continuously or use an external cron) | External | A live process, or nothing |
| **work-packet** | `resume: in / on` in the memento | `every:` in status | **None: a directory on disk** |

work-packet stands out by combining three things:

- The agent decides when it wakes, in plain language.
- No server is needed: cron or a systemd timer ticks the scheduler.
- The sleeping packet is just files you can read and edit.

## Roadmap

Each phase ends with tests. Most of these turn bugs we have already seen into
regression tests.

### Phase 0: Spec and schema

- [ ] Rewrite `prototype/agent-proc.md` as spec v0.2. Fixed file names:
  - `memento.md`: the next instruction, with versioned front matter;
  - `status.md`: front matter plus free text;
  - `journal.jsonl`, `state/`, `stack/`, `children/`, `mailbox/`.
- [ ] `status.md` front matter fields:
  - state: RUNNABLE / SLEEPING / WAITING / NEEDS_INPUT / PAUSED / COMPLETED /
    FAILED (NEEDS_INPUT and PAUSED come from `docs/runner.md`);
  - step, wake_at, resume_expr, every, tz, model;
  - parent, children, lease_holder, lease_expires.
- [ ] Define what goes in `state/` (copied on spawn) and what goes in
  `identity/` (symlinked, read-only).
- [ ] Borrowed from: Beads (a structured ledger instead of free-form plan
  files) and Manus (re-reading `todo.md`).
- Exit test: a schema checker passes on every packet that a test run creates.

### Phase 1: Steps that are safe to retry

- [ ] A thin executor script (Python or bash) wraps `claude -p`. The model
  writes its proposal into `.pending/`. The executor then:
  1. validates it;
  2. increments `step`;
  3. appends to `journal.jsonl`;
  4. renames the proposal into place in one atomic step.
- [ ] Side effects outside the packet directory carry an idempotency key
  (`<WPID>:<step>:<n>`) and are recorded before they run.
- [ ] Spawning a child is an executor operation keyed by
  `<parent WPID>:<step>`, so a retried step cannot create a second child.
- [ ] Borrowed from: the Temporal, Restate and DBOS step journals and
  idempotency keys.
- Exit tests:
  - Re-running `prototype/sub` gives `count.md = 8` and exactly one child.
  - A `kill -9` partway through a step, followed by a restart, gives the same
    result.

### Phase 2: Time and the scheduler

- [ ] `resume:` / `every:` / `wait:` as described above, with the executor
  resolving every time.
- [ ] Scheduler tick: a systemd user timer or cron entry runs every few
  minutes. Each tick it:
  - scans for packets whose `wake_at` has passed;
  - takes a lease on each one;
  - runs one step.
- [ ] Missed-wake catch-up, a lateness note in the prompt, and changes to
  `identity/` since the packet went to sleep.
- [ ] `WPK_NOW` fake clock.
- [ ] A `wpk ps` command lists packet ID, state, next wake and the last
  line of status.
- [ ] Borrowed from:
  - Cloudflare `schedule()` and Inngest `sleepUntil`, for the API shape;
  - systemd `Persistent=`, for catch-up;
  - Temporal, for time skipping in tests.
- Exit tests, all run with the fake clock:
  - "in 10 days" wakes once, on day 10.
  - "on 10 Jan" resolves to the next 10 Jan.
  - A weekly job survives a failed step.
  - A wake missed while the machine was off runs exactly once.

### Phase 3: Packet trees, messaging and supervision

- [ ] `wait: child` (join) and a `wait: any` that races a timer against
  events.
- [ ] A `mailbox/` directory per packet. A message delivered there wakes a
  packet that is waiting.
- [ ] Failures go to the parent, which can restart, give up or escalate, in
  the style of OTP. The reaper finds orphans such as `860b5f22` and packets
  whose leases have expired.
- [ ] Borrowed from: OTP supervision trees, Gas Town (mail between agents and
  Witness liveness checks) and AutoGen Core addressing.
- Exit tests:
  - A parent sleeps until both children finish.
  - A child killed with `kill -9` is restarted, and its parent hears about it.

### Phase 4: Snapshots, rewind and branching

- [ ] One git commit per step per packet, or a single repo for the packet
  tree. `wpk log <WPID>` and `wpk diff <WPID> <step>`.
- [ ] Fork from any past step: a new packet starting from that step's state.
- [ ] Borrowed from: LangGraph time-travel and the Crab and DeltaBox
  checkpoint/fork sandboxes.
- Exit test: rewinding `prototype/sub` to step 4 and running it forward
  reproduces the same files.

### Phase 5: Evaluate and decide

- [ ] Benchmark on a real dv-flow task (nightly regression triage is a
  natural periodic job) against a Ralph-style loop and LangGraph. Measure:
  - tokens per step;
  - recovery after a crash;
  - correct wakes over a simulated month;
  - how easily a human can work out what happened.
- [ ] Build-or-buy decision: keep our own executor, or put the same directory
  layout on top of DBOS or Temporal and use their journal and timers.
- [ ] Write-up that positions work-packet against Quine, Gas Town and the
  Anthropic long-running harness.

## Using the research we have collected

1. **Design inputs.** Each phase above names the idea it borrows and where
   that idea comes from. The full list is in the deck's "From prior art to
   roadmap" slide.
2. **Regression tests.** Prior art and the prototype failures give known
   failure modes: double-run, wrong report, orphan child, drifting file names
   and missed wakes. Each one becomes a test before its fix lands.
3. **Benchmark baselines.** The Ralph loop and LangGraph are cheap to set up
   and make honest comparisons (Phase 5).
4. **Build-or-buy.** DBOS, a Postgres library, is the lightest durable
   backend if our own journal turns out not to be enough.
5. **Positioning.** Use the comparison matrix and the "distinctive" list for
   any external write-up.
6. **Sources to re-check.** Many 2026 sources were found only through search
   results:
   - Quine, Agent libOS and Crab (arXiv preprints);
   - the Gas Town docs;
   - the Cloudflare Agents API.

   Read the originals before citing them, and check them again before
   Phase 5.

## Open questions

- Should the executor be Python (easy date parsing and locking) or a
  dv-flow task (closer to the target use)?
- One git repo per packet tree, or one per packet?
- Time zone: one per packet tree, or per packet? The default could be the
  user's local zone.
- Should a recurring packet keep one packet ID forever, or spawn a fresh child
  for each run so that each run has a clean history?
