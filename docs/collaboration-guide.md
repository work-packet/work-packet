# Working together: a user guide

A packet is shared work. You, the Claude or Codex sessions you drive, the runner
and batch jobs all work on it, in turns or at once. The board shows each packet
by **whose move it is** rather than by the runner's state, so you can see at a
glance what needs you, what is being worked on and what is waiting.

Design: `docs/collaboration.md`. Build plan and status:
`docs/collaboration-plan.md`. This guide covers what is built: phase C1 (the
board's columns, Done, autonomy, and who did what), C2 (presence: the board
knows when you are working on a packet and whether Claude is waiting for you,
and the runner holds off while you are there) and C3 (ways to start, Open ▾, and
the hand-off), C4 (the Desk: what needs you, snoozes, since you were last
here, the timeline) and C5 (turnover both ways: a briefing for every session,
notes into your sessions, skills, checkpoints during a step, picking up a runner
step) and F1 (planning: your priority, due dates, the Backlog and quick capture).
Later phases add the daily focus brief.

## Starting a packet

**New** asks what the packet is (source, name, objective) and then **how do you
want to start?**

- **Open in VS Code**, in the browser or on the desktop (the board remembers which
  you chose last). The packet is made, and its page opens it in VS Code for you.
  Its Claude hooks and `/wpk-checkpoint` are already in the folder.
- **Open studio**: made, then opened in the studio.
- **Hand to runner**: made and handed to the runner with the objective as its
  instruction. It needs an objective.
- **Just make it**: made; you land on its page and nothing starts.

Only *Hand to runner* gives the runner anything: the others make the packet with
autonomy **manual**. The runner's harness and model are under **For the runner:
harness and model** on the first form.

## Open ▾

Every card has **Open ▾**: VS Code in the browser or on the desktop, the studio,
or **Shell and files** (Compose). Opening changes no state; the runner just waits
while you are there.

## Handing off

**Hand off…** on the packet page (or **Hand to runner…** for a packet that hasn't
started) opens Compose, which is the hand-off dialog:

- **Instruction**: what the runner should do next.
- **Note for the next step**: if your last checkpoint is newer than the runner's
  last step, it is drafted from it ("Context so far: …"), because the runner hasn't
  seen it. Edit it as you like.
- **Checks**: what `wpk doctor` finds missing. Uncommitted changes in a git work
  folder show here with **Commit as WIP**, which commits them as "WIP before
  hand-off"; or tick **hand off anyway** to include them as they are.
- **Start now** or **After I leave**. *Start now* starts the runner even while
  you're working on it, and the card warns that you are both in it. *After I
  leave* waits until nobody is working on the project.

Your board shells stay open after a hand-off. The packet page's short **Hand off**
form (for a paused, failed or asking packet) has the same **after I leave** box.

## The board's columns

| Column | What is in it |
|---|---|
| **Inbox** | New work not yet accepted (later phases fill it) |
| **Needs you** | A question for you, a failure, or work the runner finished that you haven't looked at yet |
| **Working: you** | You are working on it: a web VS Code tab, a Claude session, a board shell, or the studio |
| **Working: agent** | The runner is on it, or it is queued for the runner |
| **Waiting** | Asleep until a set time, or waiting on its child packets |
| **Parked** | Open, but nobody is on it and nothing is pending: not started yet, paused, stopped by a limit, or finished and already looked at |
| **Done** | Marked done or dropped |

The card's first line says why it is there: "Asks: …", "not started",
"paused: over the day's cap", "wakes …", and so on.

A packet you made without an instruction is **Parked, not started**. Nothing is
missing and nothing is wrong. Write the instruction in Compose (**Hand to
runner…**) when you want the runner to work on it. The readiness checks
(`wpk doctor`) show there, before the hand-off.

## Finishing: Done, Drop, Reopen

The runner finishing a task doesn't make the packet done; you decide that.

- Work the runner finished shows under **Needs you** and as **REVIEW** in the
  Overview's attention list. Opening it, or **Mark seen**, counts as having
  looked: it moves to **Parked** until you decide.
- **Done** (on the card, the attention row or the packet page's Now line) takes
  it off the active views. A runner that still had it (queued or asleep) leaves
  it.
- **Reopen** brings a done packet back. Handing it off reopens it too.
- **Drop** (on the packet page) closes it without finishing.

Packets from before this change that the runner had finished count as done, as
the board showed them.

In the console drawer: `/done [@target] [note]`, `/drop`, `/reopen`. From a
shell: `wpk done [project] [-m note]`, `wpk drop`, `wpk reopen`.

A step that is running blocks Done and autonomy changes. The board says so; try
again when the step ends, or pause it first.

## Opening a packet makes it yours

**Opening a project in VS Code** (Open ▾, the packet page, **Open in VS Code** on
New, or `wpk ide`) **takes it from the runner**. Every packet of it that the runner
would run is paused with the reason *claimed*; a step that is running finishes
first. The card shows **Working: you** ("yours: hand it back when you're done").
It stays yours however long VS Code is open, and after you close it, until you
**hand it back**:

- **Hand off…** (Compose) or **Hand off** on the packet page, or `wpk handoff`,
  `/wpk-handoff`; or a next batch;
- **Resume** on the project.

Handing the root back hands back the rest of the project that you claimed. To open
it without taking it (to look while the runner works): `wpk ide <project> --look`.

## While you work on a packet, the runner also waits

Besides a claim, the board notices when you are working on a packet without
having opened it from the board, and holds the runner then too. Any of these
counts:

- a **web VS Code** tab on it is open (and, after two hours, only if it has been
  visible or something else in it is active: a tab left open overnight is not
  you);
- a **Claude Code session** in the packet's folder, in web or desktop VS Code or a
  terminal, has done something in the last 10 minutes;
- a **board shell** for it is open, or you typed in it;
- you opened it in **desktop VS Code** from the board in the last 10 minutes.

While you are there the card is in **Working: you** and says where, for example
"you · VS Code (web) · Claude ×2 (1 blocked)". The runner doesn't start a step on
it. A step that is already running finishes. When you leave, the runner carries
on with whatever was handed to it. A claim (above) doesn't lapse like this; it
lasts until you hand the packet back.

**Handing off while you are there starts the runner at once.** It is an explicit
choice to work alongside it, so the card then shows **you and the runner are both
working in it**. To hand off something for when you leave (for example, before
you close the laptop), use `wpk handoff <project> --after-me`.

## The Desk (`/`)

The Overview is now the Desk: what needs you, what is in progress, and what
happened while you were away.

- **Tiles**: Needs you, **Reviews** (finished work you haven't looked at, and
  the oldest), In progress, Failed, Spend today. Spend today also shows your own
  sessions' tokens, or their cost where a model profile has a price. Budgets still
  count only the runner.
- **Needs you**: questions, failures and reviews as before, plus the Claude
  sessions you drive:
  - **BLOCKED**: Claude has waited at a permission prompt for 2 minutes;
  - **YOUR TURN**: Claude ended its turn 15 minutes ago (`[ide] idle_escalate`)
    and nothing has come since;
  - **QUIET**: a session that said it was working has been silent for an hour.

  None of these is raised while a web VS Code tab on that project is visible:
  you already see it.
- **Snooze** on any row hides it for an hour, until tomorrow 08:00, or until it
  changes. Anything new about it (a new question, a new prompt) brings it back
  regardless. The heading says how many are snoozed. Snoozes are per person.
- **Boards** become a filter: **All boards** or one board's Desk (`/?board=…`).
- **Since you were last here** lists, per project, what happened after your last
  visit, newest first: runner steps, checkpoints, hand-offs, sessions, done. A
  visit is a sitting: views within 30 minutes of each other count as one, so a
  reload doesn't empty it.

## The packet's timeline

The packet page has a **Timeline**: everything that happened, by whoever did it.
That covers the runner's steps, your checkpoints and hand-offs, sessions in VS
Code, done and reopen, and settings changes. **Steps** keeps the runner's detail.

## Dragging cards

On a board, drag a card onto **Done** to mark it done (it asks first), onto
**Parked** to pause the runner, or onto **Working: agent** to open the hand-off.
Dragging onto a board in the side tab moves it to that board, as before.

## Is Claude waiting for you?

The sessions tables (the packet page, the project page and the Overview's Recent
VS Code sessions) say what each Claude session is doing:

- **working**;
- **waiting for you**: its turn ended, or it asked a question;
- **waiting for your permission (Bash)**: it is stopped at a permission prompt.
  Only the hooks below can see this one.

A session you drive (in VS Code or a terminal) whose turn ended is *waiting for
you*. A scripted one (`claude -p`) has *finished*.

### The hooks

To see this, the board adds Claude Code hooks to each packet folder's
`.claude/settings.local.json`: when it makes the packet, when you open it in VS
Code from the board, and when you convert a project. They run
`python -m work_packet.hookcmd <event>` on session start and end, each prompt, a
permission request, the end of a turn and the idle notice. They work wherever
Claude runs in the folder: web or desktop VS Code, a terminal, a job.

- **Your settings are kept.** Only wpk's own entries are added or replaced, and a
  settings file that isn't valid JSON is never touched. In a git clone the file is
  added to `.git/info/exclude`, so it never shows as a change.
- **Nothing you say is recorded.** The hooks receive your prompts and Claude's
  replies, but keep only identifiers, times, turn states and tool names. They write
  `<project>/presence/` records and a `session-start`/`session-end` line in the
  packet's journal.
- **Runner steps are not affected.** The runner starts Claude without project
  settings, and the hook ignores runner steps anyway.
- **A terminal session needs the folder trusted once.** The first time you run
  `claude` there it asks whether you trust the folder; project hooks run only
  after that. VS Code uses its own workspace trust.
- **Turning them off:** use the switch under the Overview's Recent VS Code
  sessions (it removes them from every packet folder), or set `[ide] hooks = false`
  in `config.toml`. If a packet folder's hooks are missing or were changed, its
  packet page says so and offers **Install** or **Repair**. `wpk doctor` lists
  them too, and `wpk hooks install|remove|status [project]` does the same from a
  shell.

Codex sessions don't have this yet: their waiting state comes only from the
transcript.

## Every Claude session starts oriented

When Claude starts in a packet folder (with the hooks installed), it is told:
the packet's name and brief, where it stands (your last checkpoint) and what's
next, the runner's state, and whether notes are waiting. You don't have to explain
the packet again. After a compaction it isn't told again; the summary keeps it.

**Notes reach your session too.** A note left on the board (the packet page,
the console's `/note`, or **Reply** on a Desk row) reaches a running runner step,
and also the Claude session you drive, with your next prompt there. Each session
sees a note once, and the runner still gets it. The board can't type into your
VS Code session, so a reply waits for your next prompt; Desk rows say so.

## Skills in your sessions

The board installs these for Claude Code and Codex:

| Skill | What it does |
|---|---|
| `/wpk-checkpoint` | Records where the packet stands (status, what changed, next action) |
| `/wpk-handoff` | Hands the next part to the runner (`--after-me` to start when you stop) |
| `/wpk-note` | Leaves the runner a note |
| `/wpk-done` | Marks the packet done, when you say so |

They work in the packet's folder (or below it), in any editor or terminal: the
`wpk` commands find the packet from the folder when `WPK_WPID` isn't set.

**A checkpoint while a runner step is running** doesn't wait or fail. It becomes
a note that the step sees, and an entry in the timeline. The status stays as the
step leaves it.

**Handing off a packet you started yourself** (no instruction yet): the hand-off's
message becomes its instruction.

## Picking up a runner step yourself

Each runner step is a Claude session. Its step page has **Continue this
conversation yourself**, with two commands to paste into a terminal (in VS Code,
say):

- `claude --resume <session> --fork-session` carries on from where the step left
  off, on a copy, so the step's record is unchanged;
- the same with `--permission-mode plan` asks it why it did what it did, without
  changing anything.

## Your priorities, due dates and the Backlog

Each project can carry **your** plan for it. Set it with **Plan ▾** on its card,
its packet page or the Backlog, or with `wpk plan`:

- **Priority**: *now* (what you are on), *next* (the default), *later*,
  *someday*. *now* holds at most 3 projects (`[plan] focus_wip`); a fourth asks
  you to move one down first, unless you tick "into now even if full".
- **Due** date, and whether someone depends on it (*hard*) or it's your own
  target. Cards show "due Fri", "due in 9 days" or, in red, "overdue 2 days".
- **Estimate** (`4h`, `2d`, `1w`), **blocked by** and an **area** tag, in the
  same menu; **rank** (order within a priority) is typed in on the Backlog.

The plan lives in the project's card (`<name>.wp.md`) as a `plan:` block; the
board never overwrites it. Each change is in the journal.

**The runner follows it.** When a project sets no scheduler class of its own,
*now* runs as high, *next* as normal, *later* and *someday* as low, and a due date
within two days moves it one class up (never above high).

**The Backlog** (`/backlog`, in the side tab) lists open projects by priority and
rank, your Inbox, and **Housekeeping**: projects untouched for longer than their
priority allows (*now* 3 days, *next* 3 weeks, *later* 6 weeks, *someday* a
quarter). Nothing is removed for you.

The Desk's top line shows your **Focus** (the projects in *now*, with their due
dates) and a capture box.

## Quick capture

Type a line into the capture box on the Desk, the Backlog or a board's **Inbox**
column; or `wpk todo "…"`, or `/wpk-todo` in a Claude session (it links the item
to the packet it was captured from). Items wait in the Inbox until you **Make
packet** (New, with the text as its objective) or **Drop** them.

## Autonomy

Each packet says how much the runner may do on its own. Set it on the packet
page's **Now** line (**Autonomy**), or with `wpk autonomy <mode> [project]`:

- **manual**: the runner runs only what you hand it. New packets made without
  an instruction start here.
- **on hand-off** (the default, and how packets always worked): the runner works
  a hand-off until it stops.
- **runner**: the runner may also act on schedules and children. `--review`
  says when you look: each task (default), on failure only, or never. With
  *never*, the runner finishing means done.

Cards show the autonomy when it isn't the default.

## Who did what

The packet's history credits each entry to whoever did it. A checkpoint you
record shows as *you (VS Code)* or *you (studio)*, and a scribe draft as *scribe
(draft)*. Done, drop, reopen and autonomy changes show with your name.
Checkpoints that leave the packet paused now show up as notes, where before they
showed nothing.

## Settings

| `config.toml` | Default | What it does |
|---|---|---|
| `[ide] hooks` | `true` | Claude Code hooks in packet folders (the board's switch overrides it) |
| `[ide] presence_ttl` | `600` | Seconds a sign of you (a Claude event, a tab's beat, a keystroke in a board shell) keeps the runner waiting |
| `[ide] idle_escalate` | `900` | Seconds after Claude ends its turn before it is a YOUR TURN item |
| `[plan] focus_wip` | `3` | How many projects *now* holds |

## The CLI

`wpk ps` shows a **BALL** column (`who:why`, for example `you:question` or
`agent:queued`) and leaves out projects that are done (`--all` shows them).
`--raw` shows the executor's state instead.

## What the board writes

| Field (`status.md`) | Values | Written by |
|---|---|---|
| `lifecycle` | open, done, dropped | new packets (open), Done, Drop, Reopen, a hand-off (open) |
| `autonomy` | manual, handoff, runner | new packets, Autonomy |
| `review` | each, failure, never | Autonomy (runner only) |
| `owner` | your user name | new packets |

Each change also adds an `admin` record to the journal, with `op` set to `done`,
`drop`, `reopen` or `autonomy`. Hand-offs, resumes and wakes now carry `defer`
(`false` unless `--after-me`). An interactive Claude session adds `session-start`
and `session-end` records naming the session and where it ran.

Presence records live in `<project dir>/presence/<source>.json`. The project dir
is the packet folder's `.work-packet/`, or the legacy project directory. They are
removed a day after they end.
