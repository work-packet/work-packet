# Orientation: catching up on a packet

Status: proposal, open decisions resolved (§4). Date: 2026-10-27.

A packet builds up a lot of history. This proposal covers how to use that history to answer the question someone asks when they come back to a packet, or take one over: *"what's going on here?"* It also proposes giving the owner a space in the packet for their own notes and plans.

Two situations matter:

- **Coming back after a gap.** It's the same person, so they don't need the whole story. They need to know *what changed, what's waiting on me, and what was I about to do?*
- **Taking over.** Someone new picks up the packet with no context. They need the whole story, short: the goal, the state, the decisions and why they were made, what has failed, and where to start.

One rule applies to both: **orientation is read-only.** Asking about a packet must never change the run's context, its memento or its session. Anything that should reach the agent goes through the channels that already exist: notes (the mailbox) or a hand-off.

---

## 1. What we already have

| Source | What it tells you | Where |
|---|---|---|
| `PACKET.md` | Goal and brief ("for someone arriving cold") | `docs/packet-format.md:150` |
| `journal.jsonl` | Timeline: steps, questions and answers, notes, hand-offs, admin actions | `journal.py` |
| `steps/NNNN/summary.md` | What each step did, in a few lines | `executor.py:682-770` |
| `steps/NNNN/meta.json` | Cost, tokens, session | same |
| `steps/NNNN/state.diff` | What changed in `state/` during the step | same |
| `steps/NNNN/transcript.jsonl` | The full evidence, but expensive to read | same |
| `state/outline.md` + `state/history/outline-<n>.md` | Plan progress, and how the plan has changed over time | `docs/plan-tree.md` |
| `report.md`, `state/history/report-<n>.md` | Outcomes, decisions, open items | `docs/completion-report.md` |
| `status.md`, `memento.md` | Where things are now, and the next intended move | |
| hand-off records | Who passed the packet to whom, why, and their note | `docs/long-running.md:422` |
| `mailbox/`, `notes.seen` | What the owner told the agent, and when the agent saw it | `notes.py` |

Gaps that limit orientation today:

1. **The memento is overwritten every step**, so the original instruction for a task is lost (`docs/history.md:18`). The `tasks/NNNN/` record proposed in `history.md` would fix this. It is a **prerequisite** for this proposal, because "what were we asked to do" is the first question anyone asks.
2. **Nothing records the *why*.** Summaries say what happened. Decisions only appear in completion reports, and only once a task ends. The scribe's `state/log.md` (`docs/work-sessions.md` §3.5) was meant to fill this gap, but nothing writes it yet.
3. **There is nowhere for the owner's own thinking.** The mailbox holds messages *to the agent*. It isn't for notes to yourself.
4. **Nothing tracks who has seen what**, so the tool can't say "since you were last here".

---

## 2. Proposal

There are five pieces. Each one works without the ones after it.

### 2.1 Owner space: `owner/`

A folder in the packet that belongs to the human owner. The executor and agents never write to it.

```
owner/
  notes.md      # free-form running notes; append or edit freely
  plan.md       # the owner's intentions: "next I want to try X, then Y"
  asks/         # Q&A saved as private (§2.4)
asks/           # saved Q&A from `wpk ask`, shared (the default), one file per question
```

- **Visibility to the agent** is a setting: `private`, `plan` (the default) or `all`.
  - With `plan`, `owner/plan.md` goes into the step prompt as owner intent. It is advisory and doesn't override the memento. `notes.md` stays private.
  - This is how you keep scratch thoughts out of the run while the agent still sees where you want it to go.
- **Edits are journaled.** When the dashboard or `wpk notes edit` saves a change, it appends an `owner-edit` journal record holding the file, a hash and a one-line diff stat. That keeps owner activity on the same timeline as the agent's, which matters for the dashboard. Packets are not always git repos, so the journal is the only reliable history.
- **On a hand-off**, `owner/` moves with the packet. The new owner inherits the previous owner's notes, marked with that owner's name. That's usually the most valuable thing in the packet.

### 2.2 The digest: a fast summary with no model call

`wpk brief <packet>` and a **Catch up** panel at the top of the packet page. It is built only from structured data, so it's instant, free and always correct:

```
Goal        <first paragraph of PACKET.md>
State       running | waiting on you | done (outcome) | failed | idle 12d
Current     task 3: "<original instruction>"  · outline 7/11 · step 23
Last move   s23 (2d ago): <summary.md first line>
Next        memento: resume=continue, "<reason>"
Waiting     2 questions for you · 1 note not yet seen by the agent
Trend       last 5 steps: ✓ ✓ ✗ ✗ ✗   ← 3 failures in a row
Your plan   <first lines of owner/plan.md>
Spend       $4.12 total, $1.30 since you were last here
```

The digest also flags things that need attention, using simple rules:

- **Stuck:** repeated `step-failed`, or the same outline item marked `[>]` across many steps.
- **Stale:** idle for more than N days.
- **Unread:** questions waiting on you, or reports you haven't seen.
- **Drift:** the outline has changed a lot since your last visit.

### 2.3 The chronicle: a running log the scribe writes

After each committed step, a cheap tool-less model call (the scribe from `work-sessions.md` §3.5) appends one entry to `state/log.md`. It reads the step's summary, `state.diff`, the outline diff and any notes, but not the full transcript:

```
## s23 · 2026-10-25 · task 3
Did: switched coverage collection to per-test merge
Why: s21 showed merged DB loses cross-test bins
Result: 2 of 3 regressions now pass; tb_axi still times out
Decision: drop the global DB approach (see s21)
Dead end: --fast-merge flag (corrupts DB, s22)
```

The chronicle is what makes good answers cheap. Questions about *why*, or about dead ends, are answered from this file instead of 50 transcripts. Each entry cites its step, so every claim can be traced back. A `wpk chronicle --rebuild` command fills in the log for packets that already exist.

**Cost control:** each entry costs about one small-model call per step, and it can be turned off per project. Without it, §2.4 still works, just more expensively.

### 2.4 Ask: a read-only side agent

`wpk ask <packet> "what were we doing here?"`, plus an **Ask** box on the packet page.

- **It runs as a separate agent** with read-only tools (Read, Grep, Glob) and the packet as its working directory. It starts with this context:
  - the digest
  - the chronicle
  - `owner/`
  - the step index: one line per step
  - the latest report

  It reads summaries, diffs and transcripts only when the question needs that much detail.
- **It never touches the run.** It doesn't use the run's session, it doesn't use the memento, and its writes are refused. It can run safely while the runner owns the packet.
- **Answers cite their sources**, for example `[s21]`, `[task 2 report]` or `[your note, Oct 3]`. The dashboard renders each citation as a link, and an answer with no citation should be treated as a guess.
- **Answers can be kept.** Saving a Q&A writes it to the packet-level `asks/<t>-<slug>.md` and adds an `ask` journal record. Saved answers are shared by default: the dashboard history and later owners see them, and they move with the packet on a hand-off. `--private` saves to `owner/asks/` instead, and that copy stays out of the agent's view and off the shared timeline. **Send as note** turns the answer, or a follow-up you write, into a mailbox note. This is the only way anything from Ask reaches the run, and it's explicit.
- **Optional `--as-agent` mode**: forks the last step's session (`--resume <id> --fork-session`, in plan mode) so you are talking to the agent "itself", with its working memory. This gives higher fidelity, but it costs more and old sessions may have expired. This is the "Continue the conversation" idea in `docs/product.md:620`.

**Built-in questions** (buttons on the dashboard, and `wpk ask --q <name>`):

| Question | Main sources |
|---|---|
| What were we doing here? | digest, the latest task instruction, chronicle tail, `owner/plan.md` |
| What changed since I was last here? | journal since your last visit (§2.5) |
| What's waiting on me? | open questions, unread reports, an "ask" memento |
| Why did we decide X? / Why not Y? | chronicle "Decision:" lines, reports |
| What has been tried and failed? | chronicle "Dead end:" lines, failed steps |
| Is it stuck? What's it going in circles on? | failure streaks, repeated outline items, transcripts |
| What would you do next, and why? | memento, outline, open items |
| Does the agent's plan still match mine? | `owner/plan.md` compared with `state/outline.md`; any mismatch is flagged |
| Did it act on my notes? | `mailbox` + `notes.seen` + the steps after each note |
| Where is the evidence for claim Z? | transcripts, which it searches as needed |
| What did this cost, and was it worth it? | `meta.json` totals by task, outcomes |
| Brief me to take this over. | the hand-over brief (§2.6) |

### 2.5 "Since you were last here"

Each viewer gets their own marker, kept **outside the packet** at `~/.work-packet/seen/<packet-id>.json`. Several people can look at the same packet, and looking at it shouldn't count as changing it. The marker is updated when you open the packet page or run `wpk show`/`wpk brief`.

The digest and the dashboard then show a **delta** since that marker:

- steps run and their outcomes
- questions asked and answered
- notes delivered
- outline items added or completed
- money spent
- hand-offs

If the gap is longer than a threshold (say 3 days), the packet page opens with the catch-up panel expanded. `wpk ls --changed` lists the packets that have moved since you last looked.

### 2.6 Hand-over brief

When a packet is handed off (`docs/long-running.md`), the Ask agent produces `handover-<n>.md` and links it from the hand-off journal record. The template has these sections:

1. Purpose: what done looks like
2. Current state, and confidence in it
3. Decisions made, and why (with citations)
4. Dead ends: don't retry these
5. Assumptions and known risks
6. Open questions, and who can answer them
7. The previous owner's notes and plan (from `owner/`)
8. Where to look first: the 3–5 steps or files that matter
9. A suggested first action

The person handing off can edit the brief before it's committed. The brief is what the receiving owner sees first; the step prompt already carries the hand-off note to the agent. The same template, run on demand, answers "brief me to take this over".

---

## 3. Phasing

| Phase | Contents | Needs a model? |
|---|---|---|
| **O0** | `tasks/` record (the prerequisite from `history.md`); `owner/` with journaled edits; `wpk brief` and the catch-up panel; per-viewer seen markers and the delta | no |
| **O1** | Scribe chronicle `state/log.md` + `--rebuild` | small model, once per step |
| **O2** | `wpk ask` + Ask box, with the built-in questions, citations, saving and "send as note" | yes, on demand |
| **O3** | Hand-over brief generated at hand-off; `--as-agent` session fork | yes |

O0 alone covers most of the "I'm back after two weeks" case, at no cost. O1 is what makes O2 answers both cheap and good.

## 4. Decisions

Resolved on 2026-10-27:

1. **Visibility of `owner/plan.md`:** the default is `plan`. The agent sees `owner/plan.md` as advisory intent; `owner/notes.md` stays private.
2. **Where seen markers live:** per viewer, under `~/.work-packet/seen/`. They are not stored in the packet and don't move on a hand-off.
3. **Chronicle:** on by default. It can be turned off per project.
4. **Saved asks:** shared by default, in the packet-level `asks/`. `--private` keeps one in `owner/asks/`.
