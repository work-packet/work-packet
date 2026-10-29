# Waiting on sub-work (v1)

Status: proposal, 2026-10-29. Nothing here is built yet.

## 1. What went wrong (fw-aes-demo, 2026-10-29)

Packet `f19975d2` (fw-aes-demo) needed two pieces of work done in other
repos. It lost about 3 hours, and its owner lost track of what it was
doing.

| Time | What happened | Why it went wrong |
|---|---|---|
| 01:20, 02:07 | Two requests were sent: `fw-hdl-v3-import` to new project fw-hdl (`8209c35a`) and `zuspec-arch-sched` to new project zuspec-synth (`68ffe6cb`). | Neither project was registered, so `requests.send` created each delegate **PAUSED**: "check the brief and the setup, then hand it off" (`requests.py:213`). Nobody handed them off. Both are still at step 0. |
| 02:14–02:27 | The requester asked three times whether to wait for "the agents". The owner replied "Rephrase?", then "we may have lost the sub-agents". | The requester's "## Requests" section shows only the index state (`out`), not the delegate's state (`PAUSED`, step 0). The requester and the owner both thought work was under way. |
| 02:28 | The owner said to do the work here. Step 31 spawned child `v3-import` and slept with `resume: in 2 hours`. | There is no `resume: wait` (`clock.py` `LATER["wait"] = "Stage 3"`), so the model used a long timer to poll. |
| 02:31 | The child COMPLETED after one step (3 min, $0.87). | Nothing wakes a parent when a child stops. The parent is due at 04:28 only because of its timer. |
| (planned) | After that it would spawn `arch-sched` and sleep another 2 h. | Every sequential child costs about 2 h of idle time. |

There are four separate faults:

- **F1. A child stopping does not wake its parent.** Request results already
  wake the requester: `requests.deliver` calls `admin(..., "wake")`.
  Children do not get the same treatment.
- **F2. There is no way to say "wait for this".** The model has to choose a
  timer. If the timer is short, it wastes steps. If it is long, it wastes
  hours.
- **F3. A request sent to an unregistered project stalls silently.** The
  owner's "yes, send it" reads as "start it", but it actually creates a
  paused packet. Nothing surfaces that the packet is paused.
- **F4. The wrong tool for the job.** `v3-import` was bounded work that
  fits in one step. It did not need its own packet, scheduler round-trip
  and report. The step's own Claude could have run it as a sub-agent and
  waited for it.

## 2. Which mechanism for which work

| Work | Mechanism | Who waits, and how |
|---|---|---|
| Bounded: fits in one step's time and budget, same machine, same permissions | **In-step sub-agent** (the step's `Agent` tool) | The step waits for the sub-agent and uses its result in the same step. No packet is created. |
| Multi-step, in this packet's world | **Child packet** (`spawn`) | Parent: `resume: wait children` (§4). A child stopping wakes the parent. |
| Another project's repo, owner or policy | **Request** | Requester: `resume: wait request <id>`. The delivered result wakes it, as it does today. |

`prompts/protocol.md` should state this order: use a sub-agent first, a
child packet if the work takes more than one step, and a request only for
another project.

## 3. In-step sub-agents (F4)

The model can already run sub-agents. Today it doesn't because of the
defaults.

1. **Allow it.** Add `Agent` to `PERMISSION_DEFAULTS["allowed_tools"]`
   (`schema.py:124`). Existing projects can opt in with
   `wpk allow <project> Agent`. Sub-agents inherit the step's
   permission mode and working directory, so they add no new reach.
2. **Budget and time.** The step limit is $1.00 and 120 min
   (`schema.py:40-42`). The v3-import child alone cost $0.87, so one
   sub-agent could use up the whole step budget. Choose one:
   - **(a, recommended)** Raise `step_budget_usd` to 3.00 when `Agent` is
     allowed, and tell the model the budget in the prompt (ctxhook already
     warns on time).
   - **(b)** Let a memento ask for a larger budget for its next step
     (`budget: 4 USD`, capped by the project). This is more flexible but
     adds a new field.
3. **Accounting.** Check that the step's `cost_usd`/`tokens` include
   sub-agent usage. The harness reports totals per session, but this
   needs a test. `toolcost.py:89` already labels Agent/Task calls, so the
   dashboard step page can list sub-agents by description.
4. **Protocol text.** For a bounded task, run it as a sub-agent in this
   step and wait for it. Don't spawn a child or send a request for work
   you can finish now. Give the sub-agent the files and checks it needs.
   Record its result in your notes, because the sub-agent's transcript is
   not kept as a packet.

## 4. `resume: wait` (F1, F2)

This builds the part of `work-data-design.md` §9 that is needed now.

**Syntax**, parsed in `clock.parse_resume`:

```
resume: wait children                      # every child spawned and not yet stopped
resume: wait any children
resume: wait <name>[, <name>...]           # spawn names or request ids
resume: wait any <name>[, ...]
resume: wait request <id>
... , at most in 4 hours                   # optional fallback timer
```

**State.** A waiting packet is `SLEEPING` with `waiting_on: [wpid, ...]`
and `wait_mode: all|any` in `status.md`. The fallback timer is stored in
`wake_at` (default 24 h, so a lost child still brings the parent back).
These are two new optional `status.md` fields (`schema.py:22`).

**Waking.** All three paths share one helper, `wake_waiters(pkt)`:

- **Child commit** (`executor.py`, after a commit to COMPLETED / FAILED /
  STOPPED / NEEDS_INPUT / PAUSED). If the child has a `parent` that is
  `SLEEPING`, recheck the parent's wait and run `admin(parent, "wake")`
  when it is satisfied. NEEDS_INPUT and PAUSED count as "stopped": the
  parent wakes and sees that its child needs someone. Otherwise it would
  sleep on a child that is waiting for an answer.
- **Request delivery** (`requests.deliver`) stays as it is. It also
  removes the request from `waiting_on`.
- **Scheduler backstop** (`scheduler.due`). A `SLEEPING` packet whose wait
  is already satisfied counts as due. This covers a crash between the
  child's commit and the wake, and packets that predate this change.

**Default when there's no wait expression.** If a step spawns children
and resumes with `in …`, treat any child stopping as a wake anyway. The
timer becomes the fallback. Waking early costs at most one short step
that goes back to sleep. Sleeping 2 h on finished work is the fault we
are fixing.

**Prompt.** The "## Children" table (`prompt.py:28`) gains a column
showing why the step woke: `woke: v3-import COMPLETED` or
`woke: timer (waiting on arch-sched, RUNNING step 4)`.

## 5. Requests: start them or surface them (F3)

1. **Answering "yes" starts it.** When the owner answers yes to a request
   question, the delegate starts RUNNABLE, as it already does for a
   registered target. It is created PAUSED only when a setup check finds
   a problem: the workspace can't be cloned, `doctor` fails, or the repo
   is missing. The reason then names what failed. The "check the brief"
   gate is redundant: the owner just read the brief to answer the
   question.
2. **Live delegate state in the requester's prompt.** `requests.describe`
   (`requests.py:371`) reads the delegate's `status.md` and shows lines
   like `fw-hdl-v3-import: out → fw-hdl 8209c35a PAUSED step 0 (waiting
   for owner hand-off)`. A model that sees PAUSED at step 0 asks the
   right question: hand off or do it here. It no longer asks "wait for
   the agents?".
3. **Dashboard.** A request that is out with a delegate in
   PAUSED / NEEDS_INPUT / FAILED appears in Overview → Needs attention
   under the requester, with a one-click hand-off. A SLEEPING packet
   whose wait is satisfied, or whose children all stopped, is flagged
   as stuck. With §4 this should never happen; if it does, it is a bug
   worth seeing.
4. **Superseding.** `wpk request cancel <id> --reason "done in-step"` marks
   the index entry `cancelled` and stops the delegate if it never ran.
   §9.5 already names `cancelled` as an outcome.

## 6. Plan

| # | Step | Files | Check |
|---|---|---|---|
| 1 | Child stop wakes a SLEEPING parent (any child, no wait syntax yet), plus the scheduler backstop | `executor.py` commit path, `scheduler.py:41` | test: parent `in 2 hours` + child COMPLETED → parent RUNNABLE |
| 2 | `requests.describe` shows delegate live state | `requests.py` | test: PAUSED delegate shows in section |
| 3 | `resume: wait …` parse, `waiting_on`, wait-all/any, fallback timer | `clock.py`, `schema.py`, `executor.py`, `spawn.py` | tests per form |
| 4 | Answering yes starts unregistered delegates unless setup fails | `requests.py:165-215` | test both paths |
| 5 | `Agent` in default tools, budget rule, protocol text | `schema.py`, `prompts/protocol.md` | test: new project has Agent; prompt text |
| 6 | Dashboard: stalled requests + stuck sleepers in Needs attention | `dash/data.py`, templates | test_dash |
| 7 | `wpk request cancel` | `requests.py`, `cli.py` | test |

Steps 1 and 2 are small, and they alone would have saved most of the
fw-aes-demo delay. The other steps can follow in any order.

## 7. Open questions

- **Budget rule (§3.2).** Option (a), raising the default when `Agent` is
  allowed, or (b), a per-step budget request in the memento?
- **Wake on child NEEDS_INPUT.** Wake the parent so it can answer or
  escalate (work-data-design §9.5), or send the child's question straight
  to the owner and leave the parent asleep? Recommend: wake the parent,
  since it often knows the answer.
- **Request auto-start (§5.1).** Does auto-start need the `[requests]
  send = "auto"` policy, or is the owner's yes enough? Recommend: the
  owner's yes is enough. The policy only governs sending without asking.

## 8. Fixing fw-aes-demo now

- `wpk note f19975d2 --wake -m "v3-import child COMPLETED at 02:31; proceed"`
- `zuspec-arch-sched`: tell it to run as an in-step sub-agent (after §3.1:
  `wpk allow fw-aes-demo Agent`, and raise its step budget), or let
  it spawn `arch-sched` as planned.
- Retire the stale delegates `8209c35a` (fw-hdl) and `68ffe6cb`
  (zuspec-synth) so they don't run the same work later.

## 9. Status

Decisions (2026-10-29): §7 Q1 is option (a), raise the budget when `Agent` is
allowed. Q2: yes, a child in NEEDS_INPUT wakes its parent. Q3: yes, the
owner's yes is enough to start a request.

| # | Step | State |
|---|---|---|
| 1 | Child stop wakes parent + `due` backstop | done (uncommitted): `waiting.py`, `executor.py` (`_wake_parent`, `children_seen`, `_due`), `scheduler.due`, `schema.py`, spec §4.1, protocol text; `tests/test_waiting.py` |
| 2 | Delegate live state in "## Requests" | done (uncommitted): `requests.delegate_state`/`_live`; `test_requests.py::test_the_prompt_shows_the_delegates_live_state` |
| 3 | `resume: wait …` | todo |
| 4 | Answering yes starts the delegate | done (uncommitted): `requests._start` runs safe setup fixes, resumes, or leaves PAUSED naming what's missing; new delegate projects go beside the requester's folder (they went inside it); 2 tests + updated send test |
| 5 | `Agent` default + budget rule + protocol | done (uncommitted): `Agent` in `PERMISSION_DEFAULTS` (new projects only; existing ones `wpk allow <p> Agent`); `AGENT_BUDGET_USD = 3.00` unless `step_budget_usd` is set; protocol: sub-agents, choice order, request wake/stall text. fw-aes-demo has `Agent` and `step_budget_usd = 4` |
| 6 | Dashboard: stalled requests, stuck sleepers | todo |
| 7 | `wpk request cancel` | todo |

`wpk serve` must be restarted to pick up steps 1–2.
