# Working together: a dashboard and working model for people and agents

Status (2026-11-07): built, phases C0-C7 and F1-F3, with gaps listed per step in
`collaboration-plan.md`. Two parts are not built: §5.3 waits for triggers, and
the F2 brief is a board job, not a routine packet (plan D9). How to use it:
`collaboration-guide.md`. Proposed 2026-11-06. It reframes
`product.md` §1 principle 2 ("one owner at a time"). It builds on
`session-checkpoint.md`, `vscode-monitor-plan.md`, `orientation.md`,
`ergonomics.md`, `long-running.md` §1 (HELD) and `workflow-review.md`, and
supersedes parts of them (§14).

## 1. Why

work-packet was built for agents. A packet is something you hand to the runner;
the dashboard watches the runner. In practice a lot of the work happens the
other way round. You open the packet in VS Code, drive Claude Code by hand,
start a sim, hand a chunk to the runner, take it back, and so on. That mix is now
at least as common as unattended work, and the code fights it at every turn.

The symptoms you have hit, with what the code does (audit 2026-11-06, paths
under `src/work_packet/`):

| Symptom | Cause |
|---|---|
| New packet assumes a hand-off; launching VS Code instead is clunky | `new.html:20-22` offers only "Hand it to the runner at once" or held-for-setup. `made()` (`dash/app.py:1294`) goes to the packet or to Compose; the result has no "open in VS Code". Harness and model pickers are on the first form. |
| A packet the runner can't take shows as **Paused**, even while you have it open | Board columns map executor states one to one (`dash/data.py:22-25`). The only way to say "a person has it" is PAUSED with a reason (`setup`, `by hand`, `studio`). Opening VS Code at most pauses the packet (`app.py:1131`). |
| Recent activity is about agents | Tiles, Running now, Last step and Spend all read step `meta.json` and leases (`data.py:341-412, 511-573`). VS Code sessions are a separate table, shown only to the owner. |
| "Needs setup" until handed to an agent | `held_for_setup` = PAUSED + `reason == "setup"` (`project.py:121`). Only handoff/resume/continue clear it (`executor.py:1164`). A checkpoint keeps the reason (`executor.py:986`). The page hides Update status while in setup (`packet.html:87`). An empty `prompt.md` counts as "missing" (`setup.py:533`). |
| Can't tell from the dash whether Claude, in a session you drive, is waiting for you | An ordinary `end_turn` maps to **finished**, not waiting (`ide_sessions.py:225`). A pending permission prompt looks like **working** (the `tool_use` is there; the result is not). Turn state is a muted sub-line (`_vscode.html:11`) and feeds nothing. Desktop VS Code and terminal `claude` aren't collected at all (`dash/runner.py:128`). |

More that the audit found:

- A checkpoint, studio session or scribe draft is credited to **runner** in the
  card thread (`migrate.py:241-249`), and only COMPLETED/FAILED make a result entry.
- Tasks are cut only at `handoff` records (`data.py:245`). A person's work never
  makes a task.
- **Done** means the runner's root is COMPLETED. You can't mark a manual packet
  done.
- Compose (the only place to write the brief) refuses edits while the packet is
  RUNNABLE, and closes your shells when you hand off.
- Spend and Statistics count agent steps only. The tokens of sessions you drive
  are counted, then left out of every total.
- The packet layout writes no workspace file, so VS Code terminals lack
  `WPK_WPID`, and session attribution falls back to "workspace match" or
  "Shared editor".
- `wpk checkpoint` refuses while a step runs. That is the very case where you
  work while an agent works.
- There are four overlapping designs for recording a person's work: `worker:
  person` steps (`work-sessions.md`), studio steps, checkpoints
  (`session-checkpoint.md`) and `owner/` notes (`orientation.md`). Two of them
  disagree on whether a person's record takes the lease.

These are not separate bugs. They come from one assumption: **the executor's
state is the packet's state.** The executor's state answers only "what will the
runner do with this?". For a mixed packet the questions that matter are different:
who is on it, whose move is it, and what happened since I last looked.

## 2. What others have learned (summary)

Research notes and sources are in Appendix A. Seven lessons shape this design.

1. **Group by who has the ball, not by machine state.** Claude Code's Agent View
   (2026) groups sessions as Needs input, Ready for review, Working, Done, Idle.
   Linear separates the accountable *owner* (always a person) from the *delegate*
   (an agent), and has session states awaiting-input/active/complete/error.
2. **Type the attention items.** LangChain's Agent Inbox has three kinds of
   interrupt: *notify* (FYI), *question* (unblock me) and *review* (approve or edit
   this). Each needs different buttons and a different urgency. Antigravity's
   Inbox gathers approvals across every agent.
3. **Peek and reply without switching context.** Agent View shows the last
   message and takes a one-line reply in place. Copilot and Antigravity steer by
   comment on a diff or a plan.
4. **Pull by default; push only for real blockers, at breakpoints.** Mitchell
   Hashimoto turns agent notifications off and checks in at his own breakpoints.
   Interruption research (Iqbal and Bailey; Gloria Mark) says to defer to task
   breakpoints, because resuming costs minutes.
5. **Human review and attention are the bottleneck, not agent count.** Simon
   Willison: "I can only focus on reviewing and landing one significant change at
   a time." Tools converge on 3-5 parallel workspaces. Vibe Kanban's framing is
   that the bottleneck is planning and review.
6. **Take over in place, and make the move cheap both ways.** Devin lets you take
   over its machine. Sculptor's pairing mode syncs the agent's container with your
   IDE in both directions. Cursor and Claude Code move sessions between local and
   cloud. The complaints are about the one-way gaps.
7. **Keep the person in contact with the work.** The "ironies of automation"
   (Bainbridge, and a 2026 paper on coding agents) say that the better the
   automation, the rarer and harder each takeover becomes. Supervision effort
   concentrates in *planning* (Park et al., 2026). Situation awareness needs
   three things: what is happening, whether it is on plan, and what comes next
   (Endsley; Chen's SAT model).

Where work-packet already leads (`positioning-survey.md` §2): agents, people
**and** batch jobs take turns on one durable unit with one "needs you" lane. No
one else has that. This design is about making the "people" part true.

## 3. Principles

These replace `product.md` §1 principle 2. The others stand.

- **P1. The packet is shared work, not an agent's job.** People, interactive
  agent sessions, the runner and batch jobs are all *workers* on it. None of them
  is the default.
- **P2. One accountable owner; any number of workers.** The owner is a person
  (Linear's model). Who is *working* on it right now is a separate, derived fact.
- **P3. Presence, not locks.** A person who is on a packet is detected, not
  declared. Presence makes the runner hold off (§5.1). It doesn't block the person
  and it doesn't need a "take" first. *(Revised 2026-11-06, D15: opening VS Code
  from the board is an explicit claim, which lasts until you hand the packet
  back. Presence remains for work the board didn't open.)*
- **P4. Whose move is it?** Every packet, and every live session in it, has a
  *ball*: you, an agent, something external, or nobody. The dashboard sorts on
  the ball.
- **P5. Every worker leaves the same trace.** A person's session, an interactive
  Claude session and a runner step all write to the same journal with their actor
  named. Every surface is a view of that journal (`work-data-design.md` §3).
- **P6. Ration the person's attention.** The dashboard's main job is to decide
  what deserves your attention and when. It pulls by default, and pushes only for
  blockers that have waited.
- **P7. No mode is a detour.** Starting manual, staying manual, handing off,
  taking back and pairing are all first-class. Each takes one action and needs no
  "setup" state.

## 4. The model

### 4.1 Four facts instead of one state

The executor's state machine stays as it is. It is the **runner's** view, kept in
the run record. The dashboard shows four facts about a packet. Each is derived by
one function in `views.py`, shared by the CLI, board and TUI (`interaction.md`
§4: no logic in the board).

| Fact | Values | Derived from |
|---|---|---|
| **Lifecycle** | open · done · dropped | A person's `done`/`drop` (new), or runner COMPLETED on a packet whose autonomy is *runner* (§4.4). Done can be reopened. |
| **Driver** (who is on it now) | nobody · you · runner · you + runner | Presence (§4.2) and step leases. "you + runner" happens only under split (§5.4) or an explicit override. |
| **Ball** (whose move) | you · agent · external · scheduled · nobody | Attention items (§4.3), live session turn states, runner state, jobs and children. |
| **Autonomy** | manual · on hand-off · runner (with a review level) | A packet setting (§4.4). |

How the old states map onto it:

| Today | New view |
|---|---|
| RUNNABLE, step running | driver *runner*, ball *agent* |
| RUNNABLE, queued | ball *agent* ("queued"), driver *nobody* |
| SLEEPING | ball *scheduled* (wake time) |
| NEEDS_INPUT | ball *you* (question) |
| FAILED | ball *you* (failure) |
| PAUSED `setup` | **gone.** A new packet is open, driver *nobody* or *you*, ball *you* ("not started"). The readiness checks become a pre-flight for the hand-off button only. |
| PAUSED `by hand`, `studio` | driver *you* if present, otherwise ball *you* ("parked") |
| PAUSED, other | ball *you* ("paused: reason") |
| COMPLETED | lifecycle *done* (autonomy *runner*), or ball *you* ("runner finished; review") |

PAUSED survives in the executor as "the runner must not start a step". It stops
being something the dashboard shows. `long-running.md`'s HELD state isn't needed:
`held_for` becomes the ball's *reason*.

### 4.2 Presence

Presence is a heartbeat record, not a lease. One file per source:

```
<packet>/.work-packet/presence/<source-id>.json
  { "kind": "ide-web" | "ide-desktop" | "claude" | "codex" | "shell" | "studio" | "terminal",
    "host": "...", "pid": 1234, "launch": "<WPK_IDE_LAUNCH>", "session": "<sid>",
    "since": "...", "beat": "...", "turn": "working|waiting|asking|blocked|ended",
    "turn_since": "...", "attached": true }
```

A packet is **attended** if any record has a beat within `presence_ttl` (default
10 minutes) and isn't `ended`. The sources:

- **Web VS Code.** The board already proxies `/ide/`. Count live WebSocket
  connections per server: a browser tab attached is the best presence signal
  there is (`attached`). Idle shutdown already exists.
- **Desktop VS Code and terminal sessions.** Hooks (§4.3) beat on every prompt
  and turn. The process scan in `ide_sessions.py` also checks the pid is alive.
- **Board shells, studio.** Already in-process. They just write the record.
- **Fallback activity.** Optionally, file mtimes under the packet, or a git
  index change, seen by a cheap scan. This gives "edited 4 min ago" even when no
  session is detected. It isn't git-bound: mtimes work in a plain folder.

Presence records hold no content. They are ephemeral, so they don't go in the
journal. The journal gets the coarse events (§4.5).

### 4.3 Attention: a typed inbox

Every reason for you to act becomes an **attention item** of one type. Each type
has its own buttons.

| Type | Source | Card buttons | Default urgency |
|---|---|---|---|
| **question** | runner `ask:`; interactive session's `AskUserQuestion` or plan approval | Answer inline (structured choices); Open session | high |
| **blocked** | interactive session waiting on a permission prompt | Open session (focus IDE tab); see the tool name | high, escalates after 2 min |
| **your turn** | interactive session ended its turn and no prompt has come since | Peek the last message (opt-in, §10); Open session | low; shown, escalates only after `idle_escalate` (15 min) |
| **review** | runner task finished (COMPLETED or a task boundary); child done; PR ready | Diff since hand-off; Take & open; Accept (done); Next batch | medium |
| **failure** | FAILED; job failed; hook or guard tripped | Log; Retry; Take & open | high |
| **decision** | trigger fired while attended (§5.3); request from another project; agent-proposed follow-up | Run now; Defer; Decline; Make packet | medium |
| **stale** | attended but no beat for an hour; packet driven by nobody with an intent that hasn't moved in N days | Checkpoint; Park; Drop | low |
| **notify** | runner progress milestones; job done | Dismiss | lowest; digest only |

Rules:

- **One inbox, everywhere.** The Overview's Attention list, the board's "Needs
  you" column, `wpk ps`, the phone push and the VS Code status bar (later) all
  read the same list.
- **Suppress what you already see.** A *your turn* or *blocked* item for a session
  whose web IDE tab is attached and focused (the tab reports `visibilityState`
  through the proxy's page) is shown on the card but never escalated or pushed.
- **Snooze** until a time or until new activity, whichever comes first (Linear
  triage).
- Items close on their own when the cause clears (the session gets a prompt, a
  question gets answered, the step restarts). An item never needs dismissing to
  stay correct.

#### Fixing "is Claude waiting for me?"

This is the hardest gap, and the most valuable fix. Today's monitor reads
transcripts and can't see permission prompts. The plan is to add **packet-local
Claude Code hooks**:

- When the board makes or opens a packet, it writes the packet folder's
  `.claude/settings.local.json` (merging, never replacing), and in a clone also
  adds it to `.git/info/exclude`, the same way the card is hidden. This answers
  `session-checkpoint.md`'s objection to editing the global
  `~/.claude/settings.json`. The hooks apply wherever Claude runs in that folder:
  web or desktop VS Code, a terminal, a slurm IDE job. This also closes the
  desktop gap.
- The hooks call `wpk _hook <event>` (fast, no model), which updates the presence
  record and appends coarse journal events:
  - `SessionStart` → presence `working`; journal `session-start`; *returns a
    briefing as `additionalContext`* (§7.1).
  - `UserPromptSubmit` → turn `working`; delivers pending notes (§7.2).
  - `PermissionRequest` → turn `blocked`, with the tool name. It fires at
    once; the spike (`collaboration-spike.md`) found it is the reliable signal.
    `PostToolUse` clears it after an approval.
  - `Notification` (`permission_prompt`) → turn `blocked`. It is a backstop
    that arrives about 6 s later.
  - `Notification` (`idle_prompt`) → turn `waiting`, marked as confirmed idle.
  - `Stop` → turn `waiting`, with `turn_since`. If its `background_tasks` still
    has some running (background sub-agents or shells), the turn stays `working`
    and the record's `background` says how many ("2 background agents"). Claude
    takes a turn of its own when they finish, and that turn's `Stop` sets
    `waiting`. Until then `idle_prompt` doesn't set `waiting` either.
  - `PreCompact`, `SessionEnd` → checkpoint prompt or scribe (§6.7); `ended`.
- In `ide_sessions.py`, a session that is *interactive* (it has an entrypoint
  marker or a hook record) treats `end_turn` as **waiting**, not finished.
  Finished stays the label for runner steps.
- Codex: use its `notify` hook for turn end. A permission wait is only inferred
  there. Say so on the card ("probably waiting"). *Not measured yet: Codex
  wasn't signed in for the spike, and `notify` lives in Codex's global config
  (plan §2a).*
- Hooks write no prompt or reply text. A last-message preview reads the transcript
  tail and is behind the existing opt-in (`[ide] sessions_scribe`, D2).

The C0 spike (`collaboration-spike.md`, 2026-11-06) confirmed that the CLI and
the VS Code extension's binary honour project `settings.local.json` hooks. It
also found that hook payloads carry prompt, reply and tool text, so the hook
command must allowlist the fields it keeps.

### 4.4 Autonomy

Each packet has an autonomy setting. It is shown on the card and can be changed
any time:

- **manual**: the runner never starts a step on its own. It runs a hand-off you
  make explicitly, then returns to manual. This is the default for packets you
  start in VS Code or studio.
- **on hand-off** (today's model): the runner works the task you hand it until it
  stops.
- **runner**: the runner may also act on triggers, schedules and children
  without asking. Review level: *each task* (default), *on failure only*, or
  *never*.

This is Feng et al.'s levels of autonomy (Operator → Observer) and Antigravity's
review-policy dial, collapsed to three settings that fit what the executor
already does. Triggers (`triggers.md`) check it: in *manual*, a firing becomes a
**decision** item, not a hand-off.

### 4.5 One journal, actors named

The journal gains these record types (no content, all small):

- `session-start` / `session-end`: actor `{kind: person|claude|codex, via: ide-web|ide-desktop|terminal|studio|shell, session}`
- `turn-waiting`: only when it lasts longer than `idle_escalate`, so the journal
  doesn't fill with every turn
- `checkpoint`: already a step with `worker: session|studio|scribe`
- `edit-burst`: optional, from the activity scan ("14 files, 10:02-10:47")
- `done` / `reopen` / `drop` / `autonomy`
- `job-start` / `job-end`: from `work-sessions.md` runs, when built

The card thread (`migrate.py:241`) credits each entry to its real actor: *you
(VS Code)*, *Claude in VS Code*, *runner*, *scribe (draft)*. A checkpoint that
ends PAUSED writes a `note` entry rather than nothing.

## 5. Concurrency: what the runner does while you're there

### 5.1 The rule

> **Revised 2026-11-06 (decision D15):** *opening* a project in VS Code from the
> board (or `wpk ide`) **claims** it. Every packet the runner would run is paused
> with reason `claimed` (a running step finishes first). It stays yours, however
> long the editor is open or closed, until you hand it back: a hand-off, next
> batch or resume of the root (which also releases the rest of the project), or
> Resume on the project. "I don't want agents trying to work under me." Presence,
> below, remains the safety net for work the board didn't open (a terminal
> `claude`, desktop VS Code opened by hand, a web tab reopened from a bookmark).

**Presence defers the runner.** If a packet is attended, the scheduler doesn't
*start* a step on it (the gate goes next to `gates.ide_first`). A step already
running finishes. This replaces "Pause and open": opening VS Code changes no
state, and the scheduler just waits.

Reasons:

- It is what you expect today. You open the IDE because you want the packet to
  hold still.
- It needs no take/release discipline, and it can't leave a packet stuck in
  "paused by hand" after you walk away. When presence lapses, the runner can
  resume, but only if autonomy allows and a hand-off is pending.

### 5.2 Hand off while present

If you hand off from inside a session (`/wpk-handoff` skill, or the board), the
hand-off records `defer: false` and the runner starts despite your presence. That
is an explicit choice to work alongside it. The card then shows **you + runner**
and the risk line: "both editing <folder>". On a git packet, the board suggests
split (§5.4).

### 5.3 Triggers, schedules and children while attended

*Awaits triggers (`triggers.md`, design only). The presence gate and the
**decision** item type are built and ready for it.*

They are queued as **decision** items ("trigger *nightly-regress* fired 09:12:
run now / after you leave / skip"). The default is *after you leave*. This
generalises `triggers.md` §3.1 (held on PAUSED/NEEDS_INPUT) to presence.

### 5.4 Split (later)

`packet-ux.md` U3 `--split`: the runner works in a worktree or a copied folder,
and its result lands as a branch or patch you review as a **review** item. This
is the only real concurrency. It is phase C7 (§13), because it needs merge UX and
only works well with git. Without git, copy-in and copy-out with a diff review is
possible but heavier.

### 5.5 Checkpoints while a step runs

`wpk checkpoint` currently refuses during a step. Change it so that during a step
a checkpoint is recorded as a **note** journal entry. It takes no lease, doesn't
touch status or memento, and is folded into the next step boundary. This is the
reconciliation `work-sessions.md` §4.6 and `session-checkpoint.md` §3 need:
*person records never take the runner's lease. They only redirect the runner when
they carry an explicit `--next` and no step is running.*

## 6. Workflows

Each workflow lists the steps and then what the dashboard shows. Starting points
are the board, VS Code and the CLI. Phone is a read-and-answer surface only.

### W1. Start a packet and work it yourself

1. **New** → source (folder, repo, issue) → name. *Brief* is optional ("what this
   is for"; it becomes the card's brief). No harness or model choice here.
2. **How do you want to start?** Three buttons of equal weight:
   **Open in VS Code** (web or desktop, remembered per board), **Open studio**,
   **Hand to runner** (asks for the instruction, and harness and model under
   "Advanced").
3. VS Code: the creation progress page turns into the launch. Web opens the IDE
   tab. Desktop shows a `vscode://` button, a click rather than a redirect because
   of the CSP. Hooks and the `/wpk-*` skills are already installed in the folder.
4. The packet appears in **Working — you**, autonomy *manual*. It isn't Paused
   and has no setup checklist.

Dashboard: card "You · VS Code (web) · Claude ×1 working · started 10:02".

### W2. Work by hand, with Claude in the session

You drive. Claude runs, asks, waits.

- When Claude stops and waits on a permission prompt for more than 2 minutes
  while the tab isn't visible, a **blocked** item appears. It is pushed if you
  allow push.
- When Claude ends a turn, the card shows "Claude waiting · 4 min" in muted text.
  After 15 minutes it becomes a **your turn** item.
- On SessionStart, Claude gets the packet briefing automatically (§7.1). You
  don't have to explain the packet again.

### W3. Leave and come back (shift turnover with yourself)

1. On leaving (session end, PreCompact, IDE idle shutdown, or 30 minutes idle),
   the hook offers `/wpk-checkpoint`. If the scribe is opted in, it drafts a
   checkpoint: status, what was done, next. **A scribe draft is a proposal.** The
   card shows "draft checkpoint · accept / edit" until you act. It never
   overwrites a checkpoint you wrote.
2. On coming back, the packet page opens on **Since you were last here**
   (`orientation.md`, per-viewer seen markers): checkpoints, steps, sessions,
   jobs, notes and questions since your last visit, newest first.

### W4. Hand a chunk to the runner

From VS Code (`/wpk-handoff "write the coverage tests for fifo"`) or the board:

1. The board gathers the hand-off note: your instruction, and a draft "context so
   far" from the latest checkpoint or scribe (editable). It also gathers the
   uncommitted changes: *commit as WIP*, *include as-is*, or *split* (git only).
   This replaces `dash-tasks.md` §6.6's block-on-dirty.
2. By default you stay present, so the hand-off records `defer: false` (§5.2).
   With `--after-me`, it starts when presence lapses: "do this when I close the
   laptop".
3. Card: "Runner · step 1 · started from your hand-off 15:40". The task opens
   with *you* as its requester.

### W5. Review what the runner did, and take it back

1. A **review** item: summary, files changed, tests and checks run (evidence
   first, from the Park et al. and PR studies), cost and time.
2. Buttons:
   - **Accept**: done, or back to manual.
   - **Next batch**: a new instruction.
   - **Take & open in VS Code**: opens on the diff since hand-off.
   - **Continue the runner's conversation**: opens a terminal in the IDE with
     `claude --resume <step session> --fork-session`. The runner's step sessions
     are ordinary Claude sessions, so this costs only a command line.
3. Taking changes nothing in state. Presence does the rest (§5.1).

### W6. Pair: you and the runner at once

This needs split (§5.4). Until then it is "hand off while present" with the risk
line showing. The board offers **split** whenever both would edit the same git
folder.

### W7. Long jobs you start yourself

A sim or regression started from a board shell or a VS Code terminal (`wpk run
-- make sim`, or automatically through OSC marks as in `work-sessions.md`)
becomes a **job** on the packet. The ball is *external* ("waiting on sim, 1h12m").
When it ends, a **notify** item appears, or a **failure** item if it failed. The
journal records it, so the packet's history shows the sims, not just the agent
steps. This is `work-sessions.md` stages 1-4, now tied to the ball.

### W8. Intake and triage

New packets from watchers (`watch.py`), triggers in manual packets, agent-proposed
follow-ups ("I found a second bug, make a packet?") and requests from other
projects (`requests.py`) all land in **Inbox** (§8.1). From there they can be
accepted (made or started as W1 or W4), declined, merged into an existing packet,
or snoozed until new activity.

### W9. Finish

**Mark done** is on every packet. If there is a forge, it is combined with **Open
PR** (`pr.py`). Done asks for a closing note (scribe draft available) and then
leaves the active views. Reopen is one click. A runner COMPLETED on a *manual* or
*on hand-off* packet is a **review**, not done: a person decides when the work is
finished.

## 7. Opportunities we aren't using yet

These matter as much as the redesign. Most reuse things that are already built.

### 7.1 Briefing every interactive session automatically

A `SessionStart` hook can return `additionalContext`. Return a short briefing,
built from data the board already has: the brief, the latest checkpoint and next
action, open questions, runner state, notes waiting and a pointer to the card.
Every Claude you open in a packet then starts oriented. This is the interactive
equivalent of the memento, and it is the cheapest high-value item here.
(`orientation.md`'s `wpk brief`, delivered where it is needed.)

### 7.2 Notes reach interactive sessions too

Today notes reach running steps through PostToolUse (`ctxhook.py`). A
`UserPromptSubmit` hook can deliver the same mailbox to *your* Claude on its next
prompt: "Note from the board (14:05): the regression on node 3 is a known infra
issue." This gives one channel from the board, phone or another project into
whatever is working the packet. A note from your phone reaches your VS Code
Claude.

### 7.3 Runner sessions are resumable

Every runner step is a Claude session with an id in `meta.json`. "Continue this
step's conversation in VS Code" (W5) and "Ask the runner why" (fork, read-only,
plan mode) both cost one command line. `ide.md` §6 designed this. It was never
wired.

### 7.4 Presence from the web IDE proxy

The board proxies every web IDE, so it knows which tabs are attached and, through
a tiny script in the IDE page, whether they are visible. That is accurate presence
and focus with no polling and no extension. It also drives the "suppress what you
already see" rule (§4.3).

### 7.5 All the cost, honestly split

Show a packet's total cost as runner + interactive sessions (+ studio). Keep the
split, and keep budgets on runner spend only. Today interactive tokens are counted
and then thrown away. For a semi-manual packet, that leaves most of the spend
off the dashboard.

### 7.6 The attention budget

Show the review WIP on the Overview ("4 waiting for review, oldest 2 days"), and
warn when you hand off with more than `review_wip` (default 5) reviews pending.
Willison's bottleneck becomes a number on screen.

### 7.7 Learn from corrections

When the same note or answer recurs across steps or packets ("use the uvm_info
macro, not $display"), offer to promote it to the packet's or board's skills
(`skills.py`) or to the starter. Devin's Knowledge and Park et al.'s third
strategy. Later; it needs the scribe.

### 7.8 One-line replies from the board

Questions already take structured answers. For interactive sessions, the board
can't type into your VS Code Claude. It can **queue a reply as a note**,
delivered on your next prompt (§7.2), or, for sessions hosted by the board (studio,
board shells), type it directly. That is the honest limit of "peek and reply". The
card says which applies.

### 7.9 Stop asking for setup; check when it matters

The readiness checks (`setup.py`) are useful as a pre-flight *for the runner*.
Run them when you press Hand off, show what's missing in the hand-off dialog, and
otherwise keep quiet.

### 7.10 The VS Code side (later)

A small extension, or just the status line through the hook data, can show the
same inbox in VS Code's status bar ("wpk: 2 need you"), with
checkpoint/hand-off/answer commands. `product.md` §10 planned it. The hooks and
presence records here are its data source, so it becomes a thin view.

## 8. The dashboard

### 8.1 Overview becomes **Desk**

The `/` page answers, top to bottom: *what needs me, what am I in the middle
of, what is working for me, what's new.*

```
┌ Needs you (5) ─────────────────────────────── [all] [questions] [reviews] ┐
│ ● fifo-cov    question   "Use 4 or 8 entries for the stress test?"  [4] [8] [answer…] │
│ ● dma-bug     blocked    Claude (VS Code desktop) wants to run: make sim · 3m [open] │
│ ● uart-lint   review     runner finished task 2 · 6 files · tests ✓ · $0.41 [diff] [accept] │
│ ○ spi-boot    your turn  Claude waiting 22m                    [peek] [open] [snooze] │
│ ○ nightly     decision   trigger fired 09:12 while you were in it [run now] [after] │
└─────────────────────────────────────────────────────────────────────────┘
┌ In progress ──────────────────────────────────────────────────────────────┐
│ You    dma-bug    VS Code desktop · Claude ×2 (1 blocked) · since 10:02 · 23 edits │
│ You    spi-boot   VS Code web · idle 22m · last checkpoint 11:40 "boot ROM reads OK" │
│ Runner uart-lint  step 3 · task "fix lint" from your hand-off · 6m   [note] │
│ Job    regress-7  sim 1h12m on farm (slurm 88123)                         │
└─────────────────────────────────────────────────────────────────────────┘
┌ Waiting / scheduled ─────┐  ┌ Since you were last here (Tue 18:10) ──────┐
│ nightly   wakes 02:00    │  │ 09:40 runner  uart-lint step 2 ✓           │
│ fifo-cov  waits on child │  │ 09:12 trigger nightly fired (deferred)     │
│ pcie      PR #41 review  │  │ 08:55 you     spi-boot checkpoint          │
└──────────────────────────┘  │ 08:30 job     regress-6 failed (3/120)     │
                              └────────────────────────────────────────────┘
Tiles: Needs you 5 · In progress 4 · Reviews 1 (oldest 3h) · Today $3.10 (runner $1.20 / sessions $1.90) · Pool
Inbox (3 new)  — watcher issues, follow-ups, requests              [triage]
```

Above *Needs you* sits a one-line **Today** strip from the focus brief (§9.4):
"Focus: dma-bug (due Fri, at risk) · answer fifo-cov · spi-boot  [brief]".

- *Needs you* is the typed inbox (§4.3), sorted by urgency then age. Answer and
  accept work in place.
- *In progress* mixes people, agents and jobs. That is the point of the page.
- *Since you were last here* replaces "Recent VS Code sessions" and Running now.
  It is the merged journal, collapsed per packet when busy, with per-viewer seen
  markers.
- Boards become a filter (`?board=`) rather than a row each.

### 8.2 Board columns

Columns come from the ball and the driver, not the executor state:

**Inbox · Needs you · Working: you · Working: agent · Waiting · Parked · Done**

- *Waiting* covers scheduled, child, job, PR and external.
- *Parked* means open, nobody on it, nothing pending. That is where today's
  "Paused" and "Setting up" packets go, without the alarm.
- Drag between columns maps to actions: to *Working: agent* is hand off; to *Done*
  is mark done; to *Parked* is pause the runner and close.

### 8.3 The card

```
dma-bug                                    [manual]  ● you
Fix DMA descriptor wrap at 4K boundary
Now:  You · VS Code desktop · Claude ×2 (1 blocked 3m)
As of 11:40 (checkpoint): wrap repro'd in sim; fix in dma_ctl.sv:212
Next: run regress-dma; then hand off coverage tests
2 sessions today · $1.90 sessions · runner idle since Mon
[Open ▾] [Hand off…] [Checkpoint] [Done]
```

The card has three lines for situation awareness: **Now** (perception),
**As of** (comprehension: the last checkpoint or summary, from whichever actor),
**Next** (projection: the intent, `session-checkpoint.md` D3). **Open ▾** is the
primary button on every card (web VS Code, desktop VS Code, studio, shell), not
something you reach through the project page.

### 8.4 The packet page

- A **Now** panel at the top: driver, live sessions with turn states, open
  attention items, autonomy setting, and Open ▾ / Hand off / Checkpoint / Done.
- The **Timeline** tab replaces Steps as the default history view. It shows every
  actor (steps, checkpoints, sessions, jobs, notes, hand-offs, answers) with
  filters. Steps stays as the runner's detail view. This also gives the history
  `dashboard-is-central` asks for: a session from last week still shows who, how
  long and what it left behind.
- **Tasks** are cut at hand-offs *and* at checkpoints with a `--next`, so work
  done by hand gets tasks too.
- **Cost** shows runner and sessions, split.

### 8.5 Wording

| Today | Proposed |
|---|---|
| Hand it to the runner at once | Hand to runner |
| Setting up · N missing | (gone; pre-flight in the hand-off dialog) |
| Paused (by hand) | Parked, or Working: you |
| Pause and open | Open (presence defers the runner) |
| Update status | Checkpoint |
| Note for the next step | Note (reaches the runner or your session, whichever is next) |
| Last step | Last activity (who) |
| Running (tile) | In progress |
| IN STUDIO | You · studio |

## 9. Making sense of your work: pending, priorities, backlog, deadlines

§4-§8 answer "what is happening right now". A person running a dozen packets
also needs the questions a to-do list or a planner answers: *what am I on the
hook for, what matters most, what's due, what can wait, and where should today
go.* Today wpk has almost none of this:

- Priority is a scheduler class (`sched/classes.py`) that orders the runner's
  queue. It says nothing about what matters to *you*, and it doesn't apply to
  work you do yourself.
- There are no due dates. `wake_at` is a runner alarm, not a deadline.
- The "backlog" is whatever sits in Paused or Setting up.
- `orientation.md` §2.2 designed a digest with no model call, and
  `routines-and-outputs.md` R5 a push digest. Neither is built.

### 9.1 What a person looks for, and where wpk can find it

| Need | Question | Where the data comes from |
|---|---|---|
| **Pending** | What is waiting on me, and what am I waiting on? | The inbox (§4.3) plus a *waiting-for* list in both directions: you → runner, job, child, person (`requests.py`), PR reviewer; and they → you. Each item shows its age. |
| **Priorities** | Of all this, what matters most? | A *personal* priority on the packet (below), plus derived urgency: a deadline is near, something else is blocked on it, a question has aged. |
| **Backlog** | What could I do next, and is anything rotting? | Parked packets, Inbox, quick captures, agent-proposed follow-ups. Staleness from the journal. |
| **Deadlines** | What's due, and will it make it? | A `due` on the packet; dates from sources (issue milestone, PR review request, a board milestone); a forecast from history for the runner's share. |
| **Commitments** | What did I promise, and to whom? | Requests you accepted, reviews you were asked for, notes that say "I'll…". |
| **Time** | Where did my week go? | Presence (§4.2) gives your time per packet; steps give the runner's. Free, like WakaTime, with no timers. |

### 9.2 Planning fields: owned by the person, kept in the card

The card's front matter gets a small `plan:` block. It lives in the card file
(`work-data-design.md` §3: files are the source of truth). It is human-owned:
agents may *propose* changes as decision items, never write them.

```yaml
plan:
  priority: now        # now | next | later | someday   (default: next)
  rank: 3              # order within the priority (dragged on the board)
  due: 2026-11-14      # optional
  due_kind: hard       # hard (someone depends on it) | soft (my target)
  estimate: 2d         # optional, your guess; compared with actuals later
  blocked_by: [dma-bug, "PR #41"]   # packets, requests or free text
  area: dv             # free tag: grouping and filters
```

Rules:

- **now** has a WIP limit (`focus_wip`, default 3). Putting a fourth packet in
  *now* asks which one to demote. This is the human-side counterpart of the
  review WIP (§7.6).
- The runner's scheduler class follows the personal priority unless it is set
  explicitly: now → high, next → normal, later and someday → low. The two are
  related, but they are not the same fact.
- A packet with a near `due` and work the runner could do gets the runner's
  queue boost (aging already exists) without anyone setting a class.
- Setting a priority or due date is one click on the card and works from the
  phone. Quick capture asks only for a line of text.

### 9.3 Deadlines that know about the agents

A deadline on a mixed packet is different from one on a to-do item. Part of the
remaining work is the runner's, and wpk has history to forecast it with
(`positioning-survey.md` §2, "sizing from history").

- **Forecast.** Remaining runner tasks × the packet's (or board's) typical task
  time and queue wait, plus your open items × your recent pace on the packet
  (from presence). Show the result as a range, not a promise.
- **At risk.** The forecast passes `due`; or `due` is near and the ball has been
  *you* for more than a day; or the packet is blocked by something without a
  date. An at-risk packet becomes a **decision** item: "fifo-cov due Fri: 2 runner
  tasks and your review remain; forecast Thu-Mon. Hand the tests off now / move
  due / drop scope."
- **Dates from outside.** Issue milestones and due dates (`forges.py`, `watch.py`),
  and PR review requests, fill `due` as *proposals* that you accept once per
  packet.
- **Board milestones.** A board can have dated milestones ("tapeout RTL freeze,
  Dec 1"). Packets attach to one and inherit its date as a soft `due`. The board
  page then shows a burn-down that counts human and runner work together.

### 9.4 The daily focus brief

*Built without routines (plan D9): the board builds the brief each morning and
keeps it under `$WPK_HOME/briefs/`.*

Each morning (time set per person, default 08:30 on weekdays) wpk writes a
**brief**. It is short enough to read in a minute and has four parts:

```
Thu 6 Nov · Focus

Overnight
  ✓ uart-lint  runner finished task 2 (6 files, tests ✓)   → review (5 min)
  ✗ regress-7  3/120 failed, same seed as Tue              → look
  · nightly    trigger fired, ran, nothing new

Needs you (3)   1 question (fifo-cov, 18h) · 1 review · 1 failure

Suggested focus
  1. dma-bug     now · due Fri (hard) · at risk: forecast Fri-Mon
                 last: "fix in dma_ctl.sv:212; run regress-dma"   [open]
  2. fifo-cov    answer the question first; it unblocks 2h of runner work
  3. spi-boot    now · idle 2 days, nothing blocking            [open]

Hand off before you start
  · pcie-docs and lint-sweep are well specified (brief + next) and runner-safe.
    Runner budget left today: $8.40.                       [hand off both]

Housekeeping
  · 4 parked packets untouched for 3 weeks → keep / someday / drop
  · You estimated spi-boot at 2d; 3.5d so far.
```

How it is built:

- **Deterministic first.** Every line comes from the journal, the inbox, the plan
  fields and the forecast, with no model call (the `orientation.md` digest). The
  ranking is a documented score: priority, then deadline pressure, then "unblocks
  others" (questions that gate runner work count high), then age. Each suggestion
  says *why* it is there.
- **Optional narration.** If the scribe is enabled, a cheap model call turns the
  brief into a short paragraph and can spot patterns (e.g. "the same seed failed
  twice"). It only rephrases or flags. It never reorders silently.
- **The brief is itself a routine packet** (`routines-and-outputs.md`). Its runs
  are kept, so last Thursday's brief is still on the dashboard. That gives
  history for free.
- **Where it goes:** the top of Desk until dismissed; push or email if chosen
  (`routines-and-outputs.md` R5); and as part of the SessionStart briefing (§7.1)
  in the day's first interactive session, as one line ("today's focus: dma-bug").
- **Feedback.** "Not today" and "done already" on a suggestion are recorded and
  used next time. Ignoring the same suggestion three days running raises a
  **stale** item ("still now?") rather than repeating it forever.

### 9.5 Other rhythms

- **Start-of-session pickup.** Opening a focus item from the brief opens the IDE
  and gives Claude the briefing (§7.1). It goes from "what was I doing?" to
  working in one click.
- **End-of-day shutdown** (Cal Newport's shutdown ritual). On request, or when the
  last presence lapses after 17:00, wpk asks three things:
  1. Checkpoint the open sessions (a scribe draft if enabled).
  2. **Load the night shift**: packets whose next action is runner-safe, sized to
     the budget and quota left. Results come back in tomorrow's *Overnight*.
  3. Pick tomorrow's first item.

  This is where human and agent schedules mesh best: the runner works while you
  don't.
- **Weekly review** (GTD). Friday: done this week by you and by the runner;
  cost; waiting-for items over a week old; backlog older than N weeks (keep,
  someday, drop in bulk); estimates against actuals; next week's deadlines.
- **Standup and status drafts.** "Yesterday / today / blocked" for one person, or
  a status per board or milestone for a manager. Drafted from the journal (no
  model needed for the list; the scribe for prose), and kept as a routine output.
  People already write these by hand from the same facts.
- **Calendar fit (later).** With a calendar feed (ICS URL), the brief can say
  "45 minutes before your 11:00: two reviews fit", and avoid pushing anything
  during meetings.

### 9.6 Other ways to surface what matters

- **"Unblocks others" as a first-class signal.** Answering one question can free
  hours of runner work. Rank questions by the work queued behind them, and say so
  ("answering this releases ~2h of runner work").
- **Commitments list.** Requests you accepted, reviews asked of you, and
  checkpoints whose *next* line names a person or date. Each shows its age. GTD's
  "waiting for" in reverse.
- **Fast capture everywhere.** A line from the phone, `/wpk-todo` in any Claude
  session (it captures into the board's Inbox with a link back to the packet and
  session), a follow-up an agent proposes, a watcher issue. All land in Inbox with
  their source. Capture must cost under five seconds, or the backlog lives
  elsewhere.
- **Duplicates and links.** When a capture or follow-up looks like an existing
  packet (title and brief similarity, no model needed for a first pass), offer to
  merge rather than create.
- **Rot detection.** A packet in *now* untouched for 3 days, *next* for 3 weeks,
  or *someday* for a quarter shows up under Housekeeping. Nothing is deleted
  automatically.
- **Estimates against actuals.** The estimate you set against presence time and
  runner time. This helps your estimating, and over time gives the forecast a
  per-person calibration.
- **Ask the board.** The console (`console.md`) already scopes a read-only agent
  to a page. On Desk, it can answer "what's on my plate for the DMA milestone?" or
  "what did the runner do on pcie this week?" from the journal.
- **Phone view = brief + inbox.** On a phone you want the brief, the questions
  and a capture box, not the board.

### 9.7 Guardrails

- **Suggest, don't decide.** wpk never changes a priority, due date or rank by
  itself. Changes from agents or sources arrive as proposals.
- **Each suggestion explains itself.** One reason line per item.
- **No nagging.** Each item is raised once per brief, at most. Repeated ignoring
  becomes one stale question, then silence.
- **Cheap by default.** Everything in §9 works without a model call. The model
  only narrates.

## 10. Privacy and trust

- Presence and hooks record identifiers, times, turn states and tool *names*. They
  never record prompt, reply or tool content. This is the same rule as VS Code
  monitoring.
- Peek (the last message of a session) and the scribe read the transcript only
  with the existing single opt-in (`[ide] sessions_scribe`, `session-checkpoint.md`
  D2). The card says "peek is off" rather than hiding the button.
- Writing `.claude/settings.local.json` into a folder is announced the first time
  per board, and can be switched off (`[ide] hooks = false`). It merges with your
  existing hooks, and `wpk doctor` shows what was added.
- Session data stays owner-only on a multi-user tailnet board, as today.

## 11. Data and code changes (by area)

| Area | Change |
|---|---|
| `views.py` (new home for derivation) | `lifecycle()`, `driver()`, `ball()`, `attention_items()`, `presence()`. Used by `dash/data.py`, `cli.py` (`ps`) and the TUI. |
| `schema.py` | Status gains `lifecycle`, `autonomy`, `owner`. `PAUSED/setup` is no longer written (`SETUP_REASON` read-only, for migration). |
| `project.py`, `starters/` | Creation without an instruction gives open/manual, not PAUSED/setup. `start` mode on create: `ide-web\|ide-desktop\|studio\|handoff\|none`. |
| `executor.py` | Hand-off records `defer`. `checkpoint` during a step becomes a note (§5.5). `done`, `reopen`, `drop`, `autonomy` admin verbs in `actions.py`. |
| `sched/gates.py` | `presence_defers` gate. Trigger and schedule firings while attended become decision items. |
| new `presence.py`, `hookcmd.py` | Heartbeat records, `wpk _hook <event>`, writing and merging `settings.local.json`, the SessionStart briefing, UserPromptSubmit note delivery. |
| `ide_sessions.py` | Interactive `end_turn` means waiting. Consume hook records when present. Desktop and terminal sessions come in through hooks rather than the process scan. |
| `dash/ide.py` | Proxy counts WebSocket attachments; a visibility beacon. |
| `migrate.py` | Real actors in the card thread; a note entry for PAUSED checkpoints. |
| `dash/` templates | Desk, columns, card, Now panel, Timeline, new-packet start modes, wording. |
| card front matter, `views.py` | `plan:` block (§9.2); `focus()` score with reasons; `forecast()` from step and presence history. |
| routines | A built-in *focus brief* routine (§9.4), plus shutdown and weekly-review routines. |
| `stats.py` | Session tokens as a separate worker class in totals; budgets stay runner-only. |
| `skills.py` | Add `/wpk-handoff`, `/wpk-note`, `/wpk-done` next to `/wpk-checkpoint`. |

### Migration

- `PAUSED/setup` packets show as *Parked*, autonomy *on hand-off*.
- `PAUSED/by hand` and `studio` show as *Parked*, or *Working: you* if present.
- Existing runner packets get autonomy *on hand-off*, and *runner* if they have
  triggers or schedules.
- Nothing is rewritten on disk until the packet is next touched. The derivation
  handles both.

## 12. Distributed and job-hosted IDEs

Hooks write presence into the packet folder. When the IDE runs in a slurm job on
a shared file system, that just works. Under `distributed.md` (no shared file
system), `wpk _hook` sends instead to wpkd's listener over the job's existing
mTLS channel (`vscode-monitor-plan.md` S4b, the push channel). Presence is small
and loss-tolerant, so a missed beat only delays a column change. That should be
designed into S4b now so it isn't retrofitted.

## 13. Phases

Each phase can be used on its own. The order follows value per unit of work.

| Phase | What | Fixes |
|---|---|---|
| **C0** | Spike: Claude extension and project-local hooks; `Notification` matchers; Codex `notify`; WebSocket attachment counting. | De-risks C2 |
| **C1** | Derived view (`views.py`), new columns and wording, *Parked* instead of Paused/Setting up, **Mark done**, checkpoint visible in every state, real actors in the card thread. No new data. | "paused while I have it open", "needs setup", done |
| **C2** | Presence and hooks: `wpk _hook`, `settings.local.json`, interactive `end_turn` = waiting, blocked via Notification, presence gate in the scheduler (replaces Pause and open). | "can't tell Claude is waiting"; desktop gap |
| **C3** | New-packet start modes (W1); Open ▾ on every card; hand-off dialog with pre-flight and the dirty-tree choice (W4). | "new packet assumes hand-off" |
| **C4** | Desk: typed inbox, In progress, Since you were last here, Timeline tab, split cost. | "recent activity ignores humans" |
| **F1** | Planning fields (`plan:` in the card: priority, rank, due, blocked_by), *now* WIP limit, priority→class mapping, Backlog view, quick capture into Inbox, rot detection. Deterministic only. Can run alongside C2-C4. | pending, priorities, backlog |
| **F2** | Daily focus brief (deterministic score with reasons), built as a board job rather than a routine packet (plan D9), on Desk and in the first SessionStart briefing; end-of-day shutdown with "load the night shift". | "here's where to focus" |
| **C5** | SessionStart briefing, notes into interactive sessions, continue a runner step in VS Code, `/wpk-handoff`. | turnover in both directions |
| **C6** | Push notifications (blockers past threshold), digest, attention budget, snooze, Inbox triage. | attention |
| **C7** | Split / pairing, jobs as workers (`work-sessions.md` 1-4), learn-from-corrections, VS Code status bar. | concurrency, history |
| **F3** | Deadline forecast and at-risk decisions, dates from forges, board milestones with a mixed burn-down, weekly review, standup and status drafts, estimates against actuals, calendar fit. | deadlines, reporting |

## 14. How this relates to existing designs

- `product.md` §1 principle 2 is replaced by P2 and P3. "Board is where you look,
  IDE is where you work" stands, and gets stronger.
- `long-running.md` HELD: not built. The ball's reason covers it.
- `ergonomics.md` `wpk work` and `run`: still good CLI verbs. `wpk work` becomes
  "open the packet's session here and write presence", with no state change. They
  are not needed for the board.
- `interaction.md` §6b take/release: kept for the studio, but no longer the way
  to say "I'm working on it". Presence is.
- `session-checkpoint.md`: kept. Its D1 and D2 stand. Its open questions are
  answered in §5.5 (lease) and W3 (scribe vs manual: the draft is a proposal).
  Checkpoints are the person's record.
- `work-sessions.md`: the scribe and runs stay. The `worker: person` step is
  folded into checkpoints with `worker: session`.
- `orientation.md`: "Since you were last here" and seen markers are built in C4.
  The `owner/` space is deferred; checkpoint intent covers most of it.
- `triggers.md`: §3.1 generalised to presence (§5.3) and autonomy (§4.4).
- `dash-tasks.md` §2 rule 4 ("a hand-off ends your turn"): no longer true by
  default (§5.2).

## 15. Questions for review

| # | Question | Recommendation |
|---|---|---|
| Q1 | Should presence defer the runner by default, or only when a step would touch files you've edited? | Defer by default (§5.1). It is simple and predictable, and override is one click. |
| Q2 | Install packet-local Claude hooks by default? | Yes, announced once, with `[ide] hooks = false` to turn off. Without them the waiting signal stays guesswork. |
| Q3 | Does a runner COMPLETED on an *on hand-off* packet mean done, or review? | Review. A person decides done. *runner* autonomy with review level *never* can auto-close. |
| Q4 | Is `presence_ttl` (10 m) right, given VS Code tabs left open overnight? | Attachment alone counts for at most 2 h without a hook beat or edit. After that, ball *stale*. |
| Q5 | Should "your turn" items (Claude ended a turn) ever push? | No. Only *blocked* and *question* push, and only past a threshold and when not visible. |
| Q6 | Owner as a field now, even with one user? | Yes, write it (`owner = $USER`) so multi-user boards (`workflow-review.md` custody) don't need a migration. |
| Q7 | Inbox triage as its own column, or a section on Desk only? | Column on the board, a collapsed strip on Desk. |
| Q8 | Keep "Next batch" as a name? | Rename to "Hand off…" with the instruction field; "next batch" is an implementation word. |
| Q9 | Should board shells and the studio write presence with their own `kind`, or share one "board" kind? | Own kinds. The card wants to say where you are. |
| Q10 | Personal priority: four buckets (now/next/later/someday) or numeric P1-P4? | Buckets plus a dragged rank. Buckets read better on a card; rank gives the order. |
| Q11 | Brief time and channel: Desk only, or push too? | Desk always. Push opt-in, once a day, never more. |
| Q12 | Should the focus score ever reorder the runner's queue? | Only through the priority → class mapping and the due-date boost (§9.2). The brief itself only suggests. |

---

## Appendix A. Research notes

How far to trust these: about 40 searches and 6 pages fetched in full. Items
marked † were confirmed only from search summaries or secondary blogs, and the
dates and numbers should be checked before they are quoted elsewhere.

**Products**

- Claude Code Agent View (`claude agents`), 2026†: sessions grouped Needs input,
  Ready for review, Working, Done, Idle. It shows a last-response preview and
  takes an inline reply. `/bg`; sessions run under a per-user supervisor.
  https://claudefa.st/blog/guide/agents/agent-view
- Claude Code hooks: `Notification` (`permission_prompt`, `idle_prompt`), `Stop`,
  `SessionStart`/`UserPromptSubmit` with `additionalContext`, `PreCompact`,
  `SessionEnd`†. https://code.claude.com/docs/en/hooks
- Claude Code checkpoints and `/rewind`: these don't track edits made by hand or
  by another session†. https://code.claude.com/docs/en/checkpointing
  Lesson: workspace-level history has to cover both.
- Teleport and Remote Control: move sessions between cloud, local and phone. The
  one-way gaps are the complaint†.
- Anthropic, "Measuring AI agent autonomy in practice": experienced users
  auto-approve more *and* interrupt more; supervision shifts to monitoring and
  intervening†. https://www.anthropic.com/research/measuring-agent-autonomy
- GitHub Agent HQ and Mission Control: assign, steer and track across agents;
  steer mid-run by typing or by commenting on the diff†.
  https://github.blog/changelog/2025-10-28-a-mission-control-to-assign-steer-and-track-copilot-coding-agent-tasks/
- Cursor 3 Agents Window: local and cloud agents in one list; move to and from
  the cloud†. https://cursor.com/changelog/cli-jan-16-2026
- OpenAI Codex app: worktrees, review pane, Automations into a review queue,
  best-of-N†. https://developers.openai.com/codex/changelog
- Google Antigravity: Manager view; Inbox of approvals; artifacts (plans,
  screenshots) you comment on to steer; review-policy dial†.
  https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/
- Devin: sessions sleep and wake; take over the machine; Knowledge and
  Playbooks†. https://docs.devin.ai/release-notes/overview
- Linear for Agents: assign to people, delegate to agents; the person stays
  accountable; typed activity (thought, action, elicitation, response, error).
  https://linear.app/now/our-approach-to-building-the-agent-interaction-sdk
- Conductor, Nimbalyst (Crystal), Vibe Kanban: one task = one worktree = one
  card; 3-5 in parallel; the bottleneck is planning and review†.
- Sculptor (Imbue) pairing mode: the agent's container syncs with your IDE in
  both directions†. https://rywalker.com/research/sculptor
- Terragon shut down in Feb 2026 and was released as open source†. A caution
  against depending on a hosted runner.
- Warp: notifications when any CLI agent finishes or needs input, sent to the
  parent only for orchestrated agents†. Zed: follow the agent; per-hunk review;
  ACP†. Amp: shared, searchable threads†. Jules: Planning Critic on auto-approved
  plans†. Kiro: specs and steering files†. Factory: missions†. claude-squad,
  uzi, workmux: tmux plus worktrees†. Gas Town (Yegge): a coordinating agent and
  git-backed work items†.

**Research**

- Horvitz, "Principles of mixed-initiative user interfaces", CHI '99: weigh the
  cost of interrupting; pair automation with direct manipulation.
  https://erichorvitz.com/chi99horvitz.pdf
- Feng, McDonald and Zhang, "Levels of Autonomy for AI Agents", arXiv 2506.12469:
  operator, collaborator, consultant, approver, observer; autonomy is a design
  choice.
- Park et al., "The Work Behind Delegation", arXiv 2609.24234: supervision effort
  goes into planning, delegated review, and templates.
- Mitchell, Ghosh and Passi, "AI Agents Push Humans Out of the Loop", arXiv
  2608.23642, and Bainbridge, "Ironies of Automation" (1983): skill fade among
  those who oversee.
- Endsley's situation awareness; Chen et al.'s SAT transparency model: what,
  why, what next.
- Iqbal and Bailey, CHI '07: interrupt at breakpoints. Gloria Mark: about 23
  minutes to resume†.
- LangChain ambient agents and Agent Inbox: notify, question, review.
  https://github.com/langchain-ai/agent-inbox

**Practitioners**

- Simon Willison, "Embracing the parallel coding agent lifestyle" (Oct 2025):
  review is the bottleneck; "where does this feature live?" confusion.
  https://simonwillison.net/2025/Oct/5/parallel-coding-agents/
- Mitchell Hashimoto, "My AI Adoption Journey" (2026): one background agent next
  to deep manual work; notifications off†.
  https://mitchellh.com/writing/my-ai-adoption-journey
- Armin Ronacher, "Agentic Coding Recommendations"†. Anthropic, "Claude Code best
  practices": plan before code, writer/reviewer pairs†.
- Study of Claude Code PRs (arXiv 2509.14745)†: most merge, many without change;
  less experienced developers skip CI more often. Show the evidence on review.

**Human work-management analogues**

Kanban WIP limits (here, the limit that binds is review). GTD "waiting for" (both
directions in one view). Linear triage with snooze-until-activity. WakaTime-style
heartbeats as free activity capture.
