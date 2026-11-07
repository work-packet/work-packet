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
step), F1 (planning: your priority, due dates, the Backlog and quick capture) and
F2 (the daily focus brief and the end of the day).

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

### Split: the runner works in a copy

When the packet's folder is a git checkout, Compose also offers **Split: the
runner works in a copy**. It's the third answer to uncommitted changes, after
Commit as WIP and hand off anyway. The board:
- makes a git worktree of your folder at `$WPK_HOME/splits/<name>-split`, on a
  new branch `wpk/<name>-split` from your `HEAD`;
- makes a project there (`<name>-split`) with your instruction and note, and
  hands it to the runner.

Your folder and your uncommitted edits are left alone, and you can go on
working; the split never works under you. Both project pages show the split
under **Split**: its commits, the files it changed or added, and the diff.

When it has finished:
- **Bring it into <name>** commits what it left uncommitted, then merges its
  branch into your folder. That's a fast-forward if you haven't committed
  since, else a merge commit.
  - If the merge would overwrite edits of yours, git refuses and nothing
    changes. Commit or put away your edits, then try again.
  - Brought in, the split is marked done.
- **Drop the split** marks it dropped.

Neither removes the split's folder or branch. Once the split is done or
dropped, its page has **Remove its folder**:
- the worktree goes and the split leaves the board;
- its journal is kept at `$WPK_HOME/splits/removed/<name>.journal.jsonl`;
- the branch is deleted only if it was brought in. A dropped split's branch
  stays, in case you want it later.

The split's card says **split of <name>**, linking back.

The split starts from your last commit, so your uncommitted and untracked
files aren't in it. Untracked tool folders (`packages`, `.venv`, `venv`,
`node_modules`) and untracked top-level links are linked in, so the runner
uses the same tools. Git ignores the links.

Not yet:
- splitting a plain folder (a copy in and a copy out);
- splitting a project that keeps its repositories in `work/`.

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
- you opened it in **desktop VS Code** from the board in the last 10 minutes;
- **files in the packet folder were changed** in the last 10 minutes, after
  the runner's last step and your last hand-off. This catches an editor opened
  by hand, with no Claude in it. The runner's queue says "files in it were
  edited by hand 2 min ago". Version-control, tool and cache folders (`.git`,
  `node_modules`, `.venv`, …) and the cards don't count. The board checks at
  most once a minute, and only for packets the runner is about to start.

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
  sessions' tokens, or their cost where a model profile has a price. That
  includes web VS Code, desktop VS Code and terminal sessions: the board reads a
  desktop or terminal session's transcript at the path its hook gives, and shows it
  in the project's sessions table. Budgets still count only the runner.
- **Needs you**: questions, failures and reviews as before, plus the Claude
  sessions you drive:
  - **BLOCKED**: Claude has waited at a permission prompt for 2 minutes;
  - **YOUR TURN**: Claude ended its turn 15 minutes ago (`[ide] idle_escalate`)
    and nothing has come since;
  - **QUIET**: a session that said it was working has been silent for an hour.

  Also listed, last:
  - **STALE**: a parked project untouched for longer than its priority allows
    (now 3 days, next 21, later 42, someday 91). It has **Plan ▾** (lower it,
    or someday), **Hand off…** and **Open**, and is never pushed.
  - **REVIEW** rows: besides **Open** and **Done**, they have **Next…** (hand
    the runner the next thing, in Compose) and **Open ▾** (work on it yourself).
  - **In progress** rows have **Open ▾** too.

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
Code (and "waited for you since 10:02" when a session waited past
`idle_escalate`), done and reopen, and settings changes. **Steps** keeps the
runner's detail.

A checkpoint whose **Next action** is filled in starts a new task on the
project's Tasks list, as a hand-off with a new instruction does. A hand-off
straight after it names that task rather than adding an empty one.

**Changing a queued project.** Compose can't change a project the runner has.
One that is only queued (not started yet, or asleep) has a **Save the
instruction** box, which changes what its next step starts from. A step
starting at the same moment wins, and the box tells you to send a note.

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
If nobody has recorded a checkpoint since the session started, it is told instead
to suggest `/wpk-checkpoint`, so where the packet stands isn't lost with the
compacted part.

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
- **Estimate** (`4h`, `2d`, `1w`), **blocked by**, an **area** tag and, on a
  board with milestones, a **milestone**, in the same menu; **rank** (order within a priority) is typed in on the Backlog.

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

## The daily focus brief

Each weekday morning (08:30, or `[focus] time`) the board writes a **brief**:

- **Since the last brief**: what the runner did or what failed, per project;
- **Needs you**: how many questions, failures, reviews, blocked sessions;
- **Suggested focus**: the top three, each with why. The score is your priority
  (now, next, later, someday), then deadlines (overdue, within two days, within a
  week; more if someone depends on it), then a question the runner waits on, then
  anything else waiting on you, then how long it has gone untouched;
- **Hand off before you start**: parked projects with a Next, ready for the
  runner;
- **Housekeeping**: projects untouched too long, and any suggested three briefs
  running without being touched ("still now?") instead of being suggested again.

It comes from the board's own data; no model is asked. The Desk shows it under
**Today**, with **not today** and **done already** on each suggestion (remembered
for the day; the brief is rebuilt without it). **Brief** in the side tab shows the
whole brief, earlier days, and **Rebuild today's**. A Claude session that starts in
a packet that day is told today's focus in one line. From a shell: `wpk brief`
(`--rebuild`, `--day`).

## Deadlines: forecast, at risk and milestones

**Your time.** The board counts your time on each project from the same signs
of you that hold the runner off: Claude Code events, a visible web VS Code tab,
a board shell. Each sign adds the time since your previous one on that project,
when that was at most 5 minutes before. Two sessions open at once count once.
An idle or hidden tab, or a session that ended, adds nothing. There are no
timers to start. The ledger is `<project dir>/time/<day>.json`.

**Estimates against actuals.** Give a project an **estimate** under Plan ▾
(`4h`, `2d`, `1w`; a day is 8 hours, a week 5 days). Its packet page then says
"estimate 2d · so far 3 working days: you 5h, the runner 2h". When the working
days since its first activity pass the estimate, the brief's Housekeeping says
"you estimated 2d; 3 working days so far".

**Forecast.** A project with a due date gets a forecast, a range and never one
date:
- **The runner's share** is the part of its plan still to do, times how long
  this project's tasks took (hand-off to finish, so queue waits and questions
  are in it). The middle half of those times gives the range. A project with no
  finished task uses the board's.
- **Your share** is each thing waiting on you times how long you take to answer
  a question. Once you (the project's owner) have answered five, it uses your own
  answer times, else everyone's on the board. Two hours to a day each when
  there's no history. When you are working on it yourself and have set an
  estimate, it's the hours left at your pace on it over the last two weeks, laid
  on working days (a weekend doesn't count).

The card shows "forecast Thu-Mon"; hover for the parts.

**At risk.** A project is at risk when:
- the forecast's late end passes the due date;
- it is due within two days and has been yours for more than a day; or
- it is due within a week and is blocked by something not done.

The card shows **at risk**. The Desk lists it as a decision ("dv due Fri: 2 of
4 plan items for the runner (6h-1d); 1 item yours (2h-1d); at risk: forecast
Thu-Mon"), with **Hand it off now**, **Plan ▾** to move the date, and **Open**.
It is never pushed; it goes in the digest. The brief ranks it higher, with the
reason.

**Dates from your forge.** When a watched issue that is already a project has a
milestone with a due date (GitHub or Forgejo), the Inbox proposes it ("dv:
issue gh:o/r#7's milestone v1.2 is due 2026-12-01"). **Use this date** sets it
as the project's soft due. It's proposed once per date.

**Milestones.** A board can have dated milestones: **Add a milestone** under
Milestones on the board's page (name, date, what it is). A project joins one under
Plan ▾ and inherits its date as a soft due, unless it has its own.

Each milestone shows:
- its projects, with their at-risk marks;
- what's left: plan items for the runner, and things that are yours;
- the latest forecast among its projects;
- a **burn-down** of all the work left and yours, with a dashed line to the
  date. The board takes a snapshot a day from the day you add the milestone, so
  the line starts then.

Files: `$WPK_HOME/milestones/<board>.json` and `<board>/<name>.jsonl`.

## The weekly review, standup and status

These are drafts of what people write by hand, from the board's own facts, with
no model call. Each page has the Markdown in a box to paste, and **Keep a copy**
(written to `$WPK_HOME/reports/`).

- **Weekly review** (`/review`). The board writes it on Friday after 16:00
  (`[focus] review_day`, `review_time`; `review = false` turns it off) into
  `$WPK_HOME/reviews/<YYYY-Www>.md`. It covers:
  - what was closed, and by whom;
  - each project's runner tasks and your and the runner's time;
  - cost;
  - what has waited on you for over a week;
  - backlog that has gone untouched;
  - estimates against actuals;
  - next week's deadlines and milestones.

  **Tidy the backlog** sets each untouched project to keep, someday or drop in
  one go. Before Friday, the page shows the week so far; **Rebuild this week's**
  writes it now.
- **Standup** (`/standup`):
  - **Yesterday**, your last working day: your time, hand-offs, the runner's
    finished tasks, what you closed;
  - **Today**: the brief's focus;
  - **Blocked**: what each project waits on, and requests nobody works on.
- **Status** (`/status/<board>`, or `/status/<board>/<milestone>` from a
  milestone): a row per open project, with where it is, the next move, the
  runner tasks this week, the due date and the forecast, at risk in bold.

Linked from the Desk's Today panel, the Brief page and each board's Milestones.

## Your calendar

Set `[calendar] ics` (Settings) to your calendar's ICS address or a file:
- **The brief** lists today's meetings, and what fits before the next one ("45
  min before 11:00: 3 reviews or answers fit", at 15 minutes each).
- **Pushes wait while you are in a meeting** and go out after it.

The board fetches the feed at most hourly into `$WPK_HOME/calendar/feed.ics`. All-day
events, cancelled ones and ones marked free don't count.

**Not handled:** repeating events (only the first time counts).

## The end of the day

After 17:00 the Desk links **End of the day** (`/shutdown`, or `wpk shutdown`):

1. **Checkpoint** what you were working on (the projects that are yours).
2. **Load the night shift**: projects with a Next that nobody is running, ticked;
   one button hands them to the runner, each to start when you leave. Their
   results come back in tomorrow's brief.
3. **Tomorrow's first**: put one in *now*, ranked first.

## The Inbox: what might become work

Everything that might become work waits in the **Inbox** until you decide: the
board's Inbox column (that board's items), and the Backlog's Inbox (all of them).
Items come from:

- **you**: the capture box on the Desk, the Backlog or a board's Inbox column;
  `wpk todo "…"`; or `/wpk-todo` in a Claude session (linked to its packet);
- **a watcher** set to **to the Inbox** (`propose = true`): each new issue
  lands here instead of becoming a packet straight away. Watchers are added,
  edited and removed under **Watchers** on the board's page (name, repositories,
  labels, where the packet folders go, how often, a pull request when done,
  held, on). The board writes them to `boards/<board>.toml` and checks them
  first. It rewrites that file, so comments in it are lost. Keys the form doesn't
  show (`query`, `model`, …) are kept;
- **the runner**: a step that finds work outside its task (a second bug, a
  cleanup) lists it under `follow_ups:` in its memento, and each becomes an item
  naming the project it came from;
- **requests** from other projects that arrived but haven't started (the project
  they made is paused, waiting for you). These show with **Open**, and
  **Decline ▾**, which asks for a reason. The requesting project gets the answer
  "declined: <reason>" (and wakes, if it was waiting on it), and the project the
  request made is dropped, since it never ran.

On each item:

- **Make packet**: New, with the text as its objective. A watcher's issue is made
  straight away with the watcher's recipe.
- **Merge ▾**: add it to an open project as a note for its next step.
- **Tomorrow**: snooze it until tomorrow morning.
- **Until <project> moves** (an item that names a project, such as a follow-up
  or a `/wpk-todo`): snooze it until that project has a step, a checkpoint or a
  hand-off, for a week at most.
- **Drop**: decline it. A watcher won't propose the same issue again.

When an item's words overlap with an open project's, it says **looks like
<project>: merge instead?**, and Merge ▾ picks that project.

### Rules from your corrections

When you tell the runner the same thing again and again, the Inbox offers to
make it a rule. Something counts once you've said it three times, or in two
projects: a note, a note on a hand-off, or an answer to the runner's
questions, with near-duplicates counted together. The item reads *You have
said this 3 times (alpha, beta): …*.

**Keep it…** opens the rule, which you can edit, and the projects to give it to.
Kept, it's a bullet under `## Learned` in each project's `agent.md`, which every
later step reads, so you don't have to say it again. The rest of `agent.md`
stays as it is. **Drop** turns the offer down. Either way it's never offered
again. The board looks for these once an hour, and no model reads your notes
to do it.

## Pushes and the digest

Set an [ntfy](https://ntfy.sh) topic in **Settings** (`[notify] ntfy_url`) and
press **Send a test push**. Then:

- a **question** from the runner pushes after 5 minutes (`question_after_s`),
  and a Claude session **blocked** on a permission prompt pushes after 2;
- each pushes once. Nothing pushes while a web VS Code tab on that project is in
  front of you, or while you've snoozed it. *Your turn* never pushes;
- at most 6 pushes an hour (`max_per_hour`). The rest wait for the digest;
- the **digest** (`digest = "hourly"` or `"daily"`, at `digest_at`) lists the
  rest: finished work to review, failures, sessions waiting for you, and pushes
  held back. Items that have closed since are left out;
- `brief = true` also pushes the morning brief.

Set `link` to the board's address (for example its tailnet URL) so that tapping
a push opens the project.

**Browser notifications**: in Settings, **Turn on** (per browser). While a board
tab is open and hidden, the same questions and blocked sessions show as desktop
notifications.

## The review budget

The Desk's **Reviews** tile counts finished work you haven't looked at, and
says when you are at or over `[plan] review_wip` (default 5). At that point the
hand-off forms (Compose and the packet page) warn that handing off more makes
more to review.

## Jobs: a long command as a worker

A simulation, a regression or a build you start for a project is a **job**.
Run it with `wpk run` in the packet's folder (`wpk run -- make sim`), or type it
into **Run a command** under **Jobs** on the project page, which runs it there
in the background. `wpk run` behaves like the command itself: the output shows
in your terminal, and the exit status is the command's.

While a job runs and nobody is on the project, the card sits in **Waiting**, as
*waiting on make sim, 1h12m*. A question or a failure from the runner still
comes first.

When the job ends, the Desk lists it (JOB):
- a failure, or a job whose process vanished (**lost**), as a failure;
- a success as something to look at.

Neither sends a push; both go into the digest. Opening the job's page (the
command, times, exit status and the end of its output) takes it off the list.
The whole log is `jobs/<id>/log` in the project directory.

Not yet: jobs aren't picked up from a plain terminal without `wpk run`
(`work-sessions.md` stage 2's shell marks), and nothing keeps the board from
closing a shell that is still running a job.

## Your packet in Claude Code's status line

With the hooks on, a Claude session in a packet folder shows one line in its
status bar about the packet, for example `wpk uart-fix · needs you: the runner
finished: review it · 1 job ended (1 failed)`. It's built from the packet's own
files and never asks the board. It isn't set if you already have a status line,
in your `~/.claude/settings.json` or the folder's `.claude/settings.json`, and
turning the hooks off removes it. A VS Code extension can poll
`/p/<name>/status.json` for the same facts (whose move it is, how much needs
you, running jobs).

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

**A scribe draft is a proposal.** With the scribe on, a session that ends
(web or desktop VS Code, or a terminal) gets a status drafted from its end. The
card then says **draft checkpoint · Accept · Edit**, and the packet page shows
it above the Checkpoint form, filled in from the draft:
- **Accept** records the same text as your checkpoint, so its next action
  becomes what the runner starts from;
- **Edit** opens the form, so you can change it and **Record**.

A checkpoint by hand always wins over a draft.
Checkpoints that leave the packet paused now show up as notes, where before they
showed nothing.

## Settings

The **Settings** page (in the side bar) sets these. It edits `config.toml` line
by line, so your comments and other keys stay; a value set back to its default
is removed. You can also edit the file yourself.

| `config.toml` | Default | What it does |
|---|---|---|
| `[ide] hooks` | `true` | Claude Code hooks in packet folders (the board's switch overrides it) |
| `[ide] presence_ttl` | `600` | Seconds a sign of you (a Claude event, a tab's beat, a keystroke in a board shell) keeps the runner waiting |
| `[ide] idle_escalate` | `900` | Seconds after Claude ends its turn before it is a YOUR TURN item |
| `[plan] focus_wip` | `3` | How many projects *now* holds |
| `[plan] review_wip` | `5` | Reviews waiting before hand-offs warn |
| `[focus] time` | `"08:30"` | When the morning brief is written (weekdays) |
| `[focus] weekends` | `false` | Write it on weekends too |
| `[focus] off` | `false` | No morning brief (you can still build it by hand) |
| `[focus] review` | `true` | Write the weekly review |
| `[focus] review_day` | `"fri"` | The day it is written (`mon` ... `sun`) |
| `[focus] review_time` | `"16:00"` | After this time that day |
| `[calendar] ics` | none | Your calendar feed (URL or file): meetings in the brief, no pushes during them |
| `[notify] ntfy_url` | none | The ntfy topic URL; no pushes without it |
| `[notify] ntfy_token` | none | An access token, if the topic needs one |
| `[notify] link` | none | The board's URL, for links in pushes |
| `[notify] question_after_s` | `300` | A question pushes after this long |
| `[notify] max_per_hour` | `6` | Pushes an hour; the rest go to the digest |
| `[notify] digest` | `"off"` | `off`, `hourly` or `daily` |
| `[notify] digest_at` | `"17:30"` | When the daily digest goes |
| `[notify] brief` | `false` | Push the morning brief |

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

Your time is kept in `<project dir>/time/<YYYY-MM-DD>.json` (seconds per
person; no record of what you did). Presence records live in `<project dir>/presence/<source>.json`. The project dir
is the packet folder's `.work-packet/`, or the legacy project directory. They are
removed a day after they end.
