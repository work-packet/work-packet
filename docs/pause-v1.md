# Pausing work to re-prioritise (plan and status)

Started 2026-10-29. Status: **proposed**, waiting for a go and answers to
P-Q1 and P-Q2.

## Why

To re-prioritise, you have to be able to stop a piece of work from taking
more turns, and you have to be able to do it wherever you see that work.
Today you cannot do either.

## What exists today

- **Pause on a packet's own page** (`/p/<project>/<wpid>`). It is shown
  only while the packet is RUNNABLE or SLEEPING. You have to know to open
  that page; the project page you land on has no Pause.
- **Pause in the All packets bar.** It works on ticked packets, with the
  same rule.
- **Hold project** (in the All packets bar, `sched.control.hold`). The
  scheduler starts nothing new in a held project, and the packets
  themselves are not changed.
- **Halt** and **Stop now** on `/sched`. They act on the *whole pool*, not
  on one project.

The gap that hurts most is a packet whose step is running right now.
`executor.admin("pause")` needs the packet's lease, and a running step
holds it, so the pause is refused (`LEASED`). That running packet is
usually the one you want to stop.

Pausing the root packet also does not pause its children.

## Proposal

### 1. A pause that works on running packets

When a step is running, a pause is *requested* and takes effect when the
step ends:

- `executor.request_pause(pkt, by, reason)` writes
  `run/<wpid>/pause.request` (who, when, why). It needs no lease, and it is
  idempotent.
- **At commit** (`_apply`), a pending request turns a decided RUNNABLE or
  SLEEPING into PAUSED (reason "paused by X after step n"), and the request
  is removed. A COMPLETED, FAILED or NEEDS_INPUT decision stands, and the
  request is dropped, because there is nothing left to pause.
- **At the start of `executor.step`** (under the lease), a pending request
  pauses the packet instead of running it. This covers a failed or killed
  attempt, which leaves the packet RUNNABLE.
- `admin("pause")` on a packet that has a step running now returns
  "pause requested: after step n" instead of refusing.
- A request shows on the packet and the project: `PAUSING` (amber) in place
  of RUNNING, and the Running row says "pauses after this step". It can be
  withdrawn ("Don't pause").

**Stop now (one project).** Cancel its running steps the way the pool's
Stop now does (`control.cancel_jobs`, filtered to the project, `lost`, so
the attempt is not counted). Then the request pauses it. The step's
unfinished work is thrown away: the next run redoes that step from the
same memento. See P-Q1.

### 2. Pause a whole project

**Pause** acts on the project, not on one packet:

- It requests a pause for every packet in the tree that is RUNNABLE or
  SLEEPING or has a step running.
- One journal line goes on each packet, and the flash says "paused N
  packets (M after their step)".

**Resume** acts on every packet in the tree that was paused *by hand*.
Packets PAUSED for setup, by a limit, or for a question are left alone.

`wpk pause <project>` and `wpk resume <project>` do the same. Today they
take a packet; a project name will mean its tree.

### 3. Pause where you see the work

| Where | Control |
|---|---|
| Project page header (`_tabs.html`, on every tab) | Pause / Resume, and "Stop now" while a step runs |
| Overview: Running now, Coming up | a small Pause on each row |
| Board cards | Pause on the card's menu (and on a Running card) |
| Packet page | Pause shown while running too (it becomes a request) |
| All packets bar | Pause now also requests on running packets |

### P-Q1: what should Pause do to a step that is running?

- **A. Let it finish, then pause (recommended for the default button).**
  Nothing is lost. A step usually takes minutes; the turn it is in still
  costs.
- **B. Cancel it at once and pause.** It frees the slot and the spend now.
  The step's unfinished work is thrown away and redone later.
- Proposal: **Pause** does A. A separate **Stop now** does B, behind a
  confirmation.

### P-Q2: Pause or Hold?

- **Hold** is the scheduler's own lever for priority: it starts nothing
  new in a held project, and touches no packet state.
- **Pause** changes the packets: they become yours (editable in Compose),
  and the runner leaves them until you hand them off.
- For "not now, something else first", Hold is arguably the cleaner
  choice. It is quickly undone and keeps the packets as they are.
- Proposal: **one button, Pause**, which is the packet pause above,
  because that is the word you used and the state the board already shows.
  Hold stays in All packets for the pool's own use. The other option is a
  Pause that is really Hold. Say if you prefer that.

## Steps

- [ ] P1. `executor.request_pause` and `withdraw_pause`; honour a request
  in `_apply` and at `step` start; `admin(pause)` requests while a step
  runs; tests.
- [ ] P2. Project-level pause and resume (`actions.pause_project`,
  `resume_project`); `wpk pause|resume <project>`; tests.
- [ ] P3. Stop now for one project (`control.cancel_jobs` filtered to the
  project, plus the request); tests with the local backend.
- [ ] P4. Dashboard: Pause / Resume / Stop now on the project header; Pause
  on the Overview's Running and Coming up rows and on board cards; the
  packet page and the All packets bar on running packets; PAUSING shown.
- [ ] P5. Docs (`docs/interaction.md` §4 actions, `docs/spec.md` for
  `pause.request`); check in the browser.

## Status

- 2026-10-29: proposal written.
