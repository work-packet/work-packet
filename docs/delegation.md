# Requests: handing work to another agent

A packet sometimes runs into work it can't do in its own tree. The first case:
`pss-registers-up-planning` (step 8) found that `pssc sv-native` does not
generate register access for `reg_c`. The fix belongs in the pssc repo. The
packet only uses pssc as a `dev-src` package and may write only its own `work/`.
Until now the only path was by hand: read the packet's notes, write a brief,
start an agent in the other repo, and hand the result back later.

A **request** makes that path official. The packet writes a self-contained
brief, the owner approves sending it, `wpk` gives it to a packet in another
project, and when that packet finishes, its outcome comes back to the requester
as a note.

## 1. How it fits with what exists

| Mechanism | Who does the work | Where the result goes |
|---|---|---|
| Child (`spawn`, spec §6) | a packet in the same project, created by the step | the parent reads the child's files |
| Hand-off / answer | the same packet, after the owner acts | — |
| Note (interaction.md §6a) | — | text into a packet's `mailbox/` |
| **Request** (this doc) | the root packet of **another project** (new or existing), or someone outside `wpk` | a note into the requester's mailbox, plus a `request` journal record |

A request is never automatic: the owner approves each one, because it starts
work, and spends money, in another repo.

## 2. The brief: `state/requests/<id>.md`

The step writes it under `.pending/state/requests/`. `<id>` is a name
(`[a-z0-9][a-z0-9_-]*`).

```markdown
---
title: Lower reg_c register access in pssc sv-native
to: pssc-reg-lowering            # the project that does it: a registered one, or a new one by this name
repo:                            # optional; only used when a new project is created: its [[setup.repo]]
  - name: pssc
    from: ~/projects/pssc
---
## Background
What the requester is doing, only as much as the other agent needs.

## Task
What to change, in the other repo's terms.

## Reproduce
A minimal input and the exact command, with what it prints now.

## Done when
The check that shows it works, which the requester will also run on its side.

## Meanwhile
What the requester does while it waits (a workaround, other items).
```

- `title` and `to` are required; the body must not be empty. The sections
  are what the protocol asks for; they are not checked.
- The receiving agent knows nothing of the requester. The brief must stand
  alone: paths in the other repo, not in the packet.

## 3. Asking to send it

The step asks, with a question that names the request:

```yaml
ask:
  - id: pssc
    q: Send request pssc-reg (lower reg_c in pssc) to a new project pssc-reg-lowering?
    recommend: "yes"
    request: pssc-reg               # state/requests/pssc-reg.md must exist
```

Answering yes (`wpk answer … pssc=yes`, or **Take the recommendations**)
sends the request before the hand-off, the way `grants` runs `wpk allow`. A
request can also be sent without a question: `wpk request send`.

## 4. Sending: `wpk request send <wpid> <id>`

| Target | What happens |
|---|---|
| `to` is a registered project | its root gets the brief as its next batch (`wpk next`): it must be stopped (`COMPLETED`, `NEEDS_INPUT`, `PAUSED`, `FAILED`). A running one is refused. |
| `to` is not registered | `wpk new <to>` in the requester project's parent directory (or `--dir`), with the brief as the prompt, `[setup] repo` from `repo:`, and the root `PAUSED`. The owner then sets it up (`wpk setup <to> --apply`) and hands it off. |
| `--external NOTE` | no packet: the owner takes it elsewhere (an interactive session, a colleague). The result comes back with `wpk request done`. |

`--to NAME` overrides `to:`. Sending writes:

- the index entry `$WPK_HOME/requests/<requester wpid>--<id>.json`:
  `{id, title, from: {project, wpid}, to: {project, wpid, batch} | {external},
  sent, by, state: "open"}`;
- a `request` record in the requester's journal (`op: sent`, `id`, `by`,
  `to`, `title`);
- a `request` record in the delegate root's journal (`op: received`, `id`,
  `by`, `from`).

## 5. The result comes back

`requests.sync()` runs at the start of every `wpk tick` and every pass of
wpkd's dispatcher, and as `wpk request sync`. For each open entry whose
delegate is `COMPLETED` or `FAILED` in the batch the request started:

1. The entry gets `state: delivering` and a note id.
2. A note goes into the requester's `mailbox/`: the request, the delegate's
   final state, its report's outcome line and deliverables, and the paths to
   `report.md` and the delegate's work repos. The note is not written again
   if it is in the mailbox or a step already consumed it.
3. A `SLEEPING` requester is woken. A stopped one keeps the note until its
   hand-off, as any note does.
4. Under the requester's lease: a `request` record (`op: done`, `id`,
   `outcome`, `note`). Then `state: delivered`. If a step holds the lease, the
   next sync tries again; the note is already there.

`wpk request done <wpid> <id> -m TEXT` delivers by hand: the result of an
external request, or an override for a packet request.

The requester's step prompt lists its requests under "Requests", each with
its state, so a step knows what is still out.

## 6. Commands

| Command | Does |
|---|---|
| `wpk request send <wpid> <id> [--to NAME] [--dir D] [--external NOTE]` | §4 |
| `wpk request list [target]` | requests, from the index: id, from, to, state |
| `wpk request done <wpid> <id> -m TEXT` | §5, by hand |
| `wpk request sync` | §5, now |

`wpk show` lists a packet's requests too.

## 7. Not in this round

- `wait: request <id>` (sleep until it comes back). For now the step goes on
  with its workaround, or sleeps with `resume: in N hours`, and the note
  wakes it early.
- The board: requests on the packet page, and a **Send** button. `wpk answer`
  with a yes covers it from the board's Answer panel, since that calls
  `actions.answer`.
- Requests between packets of one project (that is a child).

## Plan and status

- [x] R0 design (this file)
- [x] R1 `requests.py`: brief checks, index, `send`, `sync`/`deliver`, `done`
- [x] R2 schema: `request` journal type; `request:` on questions; a step whose
  question names a missing or bad brief is rejected (`_validate_pending`)
- [x] R3 `actions.answer` sends a request answered yes; `wpk request
  send|list|done|sync`; `wpk show` lists requests
- [x] R4 sync at the start and after each pass of `wpk tick`, and before each
  fill in wpkd's dispatcher; "Requests" section in the step prompt
- [x] R5 protocol.md "Requests: work for another agent"; spec.md (journal
  type, `requests/` in the runner home); interaction.md (`request` key)
- [x] R6 `tests/test_requests.py`, 10 tests; full suite 710 passed, 4 skipped

### 2026-10-26: R1–R6 built

- `send` writes the index entry as `sending` first, so a send that stops
  part-way shows in `wpk request list`; sending again picks it up.
- A new delegate project is created `PAUSED`, with the reason "a request from
  <project>: check the brief and the setup, then hand it off". Nothing runs in
  the other repo until you hand it off.
  **Changed 2026-10-29 (docs/waiting-v1.md §5.1):** your yes starts it. Send runs
  the safe setup fixes (the clones `wpk doctor --fix` runs) and makes the
  delegate `RUNNABLE`. It stays `PAUSED` only when something is still missing,
  and its reason names what that is. The project goes beside the requester's
  folder, no longer inside it.
- Delivery is only for the batch the request started (`to.batch`), so an
  existing project's earlier `COMPLETED` doesn't count.
- The result note has a fixed id (`<time>-req-<id>`), so a retried delivery
  never sends two notes.
- Not yet tried with a real model: whether a step writes a brief that stands
  alone. The first real case is pss-registers-up-planning's pssc blocker.
