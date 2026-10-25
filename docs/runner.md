# wpk runner, dashboard and `new` command: design

Status (2026-10-21): draft design, not built yet. Decided: projects live in
any directory; the dashboard is web-first; old steps are pruned by hand;
multi-machine sync is deferred. This design extends
`docs/roadmap.md` (phases P1–P3). Open questions are at the end.

## What we are adding

The roadmap so far describes a single packet tree that runs one step at a
time. To use work-packet every day we need three more pieces:

1. **A master runner.** One per user. It knows every project, decides which
   packet steps next, enforces limits, and wakes sleeping packets on time.
2. **A dashboard.** A kanban board of projects, with views of each packet
   tree, each step's transcript, upcoming wakes, and items waiting for a human.
3. **`wpk new`.** A command that creates a project (a root packet) from
   a prompt and an optional template, then registers it with the runner.

Terms used below:

- **Project**: a root packet and everything it spawns. A project has a
  name, such as `nightly-triage`.
- **Packet**: one directory, identified by a packet ID (WPID), as described
  in the roadmap. "Agents as processes" is still the idea behind it.
- **Step**: one `claude -p` call, run and committed by the executor.

## Layers

```
              wpk CLI               dashboard (browser)
          new / ps / send / ...     board, tree, transcripts
                    \                  /
                     \   (same code)  /
                      v              v
   +-------------------------------------------------------+
   |  runner (wpk runner / wpkd, one per user)              |
   |   registry  scheduler  worker pool  reaper  event log  |
   +-------------------------------------------------------+
                           |
                           v   wpk step <WPID>
   +-------------------------------------------------------+
   |  executor: runs exactly one step of one packet         |
   |   lease -> build prompt -> claude -p -> validate ->    |
   |   journal -> atomic commit -> release lease            |
   +-------------------------------------------------------+
                           |
                           v
             project directories on disk (source of truth)
```

The rules that keep this simple:

- **Files are the source of truth.** The runner holds no state that cannot be
  rebuilt by scanning directories. You can kill it at any time and restart it
  without losing anything.
- **The executor knows nothing about the runner.** `wpk step <WPID>`
  works on its own, from a shell or a test. The runner is just a scheduler that
  calls it.
- **The dashboard and the CLI share one code path for changes.** Pressing
  "Pause" in the browser runs the same function as `wpk pause`. The
  dashboard never edits packet files directly.

## On-disk layout

### Runner home: `~/.work-packet/` (override with `WPK_HOME`)

```
~/.work-packet/
  config.toml          global limits, default model, notification hooks
  projects/            the registry: one small file per project
    nightly-triage.toml
    uvm-port-research.toml
  templates/           user templates (see below)
  events.jsonl         append-only log of runner events
  runner.lock          held by the running runner (flock)
  runner.sock          control socket: "something changed, rescan"
```

A registry entry only says where the project lives:

```toml
# ~/.work-packet/projects/nightly-triage.toml
name     = "nightly-triage"
path     = "/home/mballance/work/nightly-triage"   # any directory
root     = "3f0c9a2e-..."           # root packet ID
created  = "2026-10-21T14:03:00Z"
template = "nightly-triage@1"
```

Using one file per project, rather than a database, keeps the registry easy to
edit, diff and back up. A project can live in any directory: inside the repo
it works on, in a scratch area, or anywhere else. The registry entry is the
only link between the runner and the project.

### Project directory

```
<project>/
  project.toml         name, template, model, limits, tz, permissions
  prompt.md            the original prompt, kept for reference
  packets/
    <WPID>/            one per packet; flat, not nested
      status.md        front matter: state, step, wake_at, parent, ...
      memento.md       next instruction
      identity/  state/  stack/  mailbox/
      children/        symlinks to ../<child WPID>
      journal.jsonl    one line per step
      steps/
        0007/
          prompt.md        exactly what the model was sent
          transcript.jsonl claude -p stream-json output, raw
          result.md        the model's proposal (.pending/ after validation)
          state.diff       what the step changed in state/
          meta.json        start, end, model, tokens, cost, exit code, session id
```

Packets sit side by side in `packets/` rather than nested inside each other.
This keeps paths short and stable, makes "every packet in the project" a
single directory listing, and still records the tree through `parent` in
`status.md` and the `children/` links.

The `steps/` folder is new. It is what makes transcripts browsable: every step
keeps its full prompt, its raw transcript and the change it made. The executor
writes it, so the model cannot forget to.

## The runner

`wpk runner` is a long-lived process, normally run as the `wpkd` systemd user
service.
It holds `runner.lock`, so only one can run at a time.

### Main loop

Every tick (default 30 s), and whenever the control socket or a file watch
says something changed, the runner:

1. **Rescans the registry** and reads `status.md` of every packet in every
   active project. With tens of projects, scanning is cheap. If it gets slow,
   add a SQLite cache that can be thrown away and rebuilt.
2. **Collects due work**:
   - `RUNNABLE` packets;
   - `SLEEPING` packets whose `wake_at` has passed;
   - `WAITING` packets whose event happened (child finished, mail arrived)
     or whose `until:` time passed.
3. **Applies limits** (next section) and orders what is left by priority, then
   by how long it has been due. Older work goes first, so a busy project
   cannot starve a quiet one.
4. **Starts steps** in a worker pool: each worker runs
   `wpk step <WPID>` as a subprocess, with output going to the step's
   own files.
5. **Reaps**: releases expired leases, marks packets whose step crashed
   (the P1 retry rules apply), and flags orphans.
6. **Writes events** to `events.jsonl`: step started or finished, state
   changed, wake scheduled, limit hit.

If the runner was down, step 2 picks up missed wakes when it restarts. Each
missed wake runs once, as the roadmap's catch-up rule says. No special
recovery code is needed.

`wpk tick` runs one pass of this loop and exits. That is enough for
cron-only setups and for tests that use the fake clock.

### Limits and budgets

Set in `config.toml` (global) and `project.toml` (per project):

| Limit | Example | When reached |
|---|---|---|
| Steps running at once | 4 global, 2 per project | Wait for a free slot |
| Steps per packet per hour | 20 | Stop for now; usually means a loop |
| Spend per project per day | $5 | Project moves to Paused, reason "budget" |
| Total steps in a project | 500 | Project moves to Paused, reason "step limit" |
| Step time | 20 min | Kill the step; P1 retry rules apply |
| API rate limit or overload | n/a | Back off with jitter, keep other projects going |

Budgets are checked from `meta.json` cost figures, so they come from what was
actually spent, not from estimates.

### Leases

Before a step, the executor creates `packets/<WPID>/.lease` with the runner's
host, PID, step number and an expiry time. It refreshes the lease while the
step runs. A lease past its expiry belongs to a dead worker and the reaper may
remove it. The executor refuses to start a step on a packet that has a live
lease, so a manual `wpk step` can never run at the same time as the
runner.

### Waking on events

The runner watches each project's `packets/*/mailbox/` and `status.md` files
(inotify on Linux), so a message or a child finishing wakes the waiting
packet within seconds instead of at the next tick. The tick stays as a
fallback in case a watch is missed.

## `wpk new`

```
wpk new <name>
    [--prompt "..." | --prompt-file prompt.md]
    [--template <name>[@version]] [--set key=value ...]
    [--dir <path>]               # any directory; default: ./<name>
    [--model <id>] [--every "monday 08:00"] [--tz Europe/London]
    [--budget 5/day] [--priority normal]
    [--identity name=/path ...]  # extra symlinks into identity/
    [--paused] [--dry-run]
```

Examples:

```
wpk new uvm-port-research --prompt "Survey how to port our UVM env to pyhdl-if; write findings to state/report.md"
wpk new nightly-triage --template nightly-triage --set suite=regress/full --every "daily 06:00"
```

What it does, in order:

1. **Checks the inputs.** The name must be unique in the registry. The
   template must exist, and every required parameter must have a value.
   Nothing is written if a check fails.
2. **Creates the project directory** with `project.toml`, `prompt.md` and the
   template's seed files.
3. **Creates the root packet** with a new WPID:
   - `identity/` holds symlinks: from the template, from `--identity`, and by
     default the working repo, so the packet can find its code;
   - `state/` gets the template's seed files;
   - `memento.md` is the template's first instruction with the prompt
     inserted, or just the prompt if there is no template;
   - `status.md` is `RUNNABLE` (or `PAUSED` with `--paused`), step 0, with
     `every:` if a schedule was given.
4. **Writes the registry entry**, last, with an atomic rename. A project
   that failed half-way is never registered.
5. **Tells the runner** through `runner.sock`. If no runner is running, it
   says so, and suggests `wpk tick` or starting the service.

`--dry-run` prints the files it would create. Related commands:

- `wpk adopt <dir>` registers an existing project directory, for
  example one checked out from git;
- `wpk archive <name>` moves a finished project out of the active
  registry but keeps all its files;
- `wpk rm <name>` removes the registry entry, and deletes files only
  with `--delete-files`;
- `wpk prune <name> [--before <date> | --keep-last N] [--dry-run]`
  deletes old `steps/<n>/` folders. Nothing is ever pruned automatically;
  `journal.jsonl` keeps one line per step, so the history stays complete even
  after the step folders are gone.

### Templates

A template is a directory:

```
templates/nightly-triage/
  template.toml        version, description, parameters, defaults
  memento.md           first instruction; uses {{prompt}} and {{params}}
  agent.md             standing role instructions added to every step's prompt
  state/               seed files copied into the root's state/
  identity.toml        symlinks to create (e.g. dv-flow cache, ivpm deps)
```

```toml
# template.toml
version     = 1
description = "Run the regression nightly, triage new failures, file a summary"
[params]
suite = { required = true, help = "dv-flow suite to run" }
[defaults]
model  = "claude-sonnet-5"
every  = "daily 06:00"
budget = "3/day"
permissions = { allowed_tools = ["Read", "Edit", "Bash(dfm *)"] }
```

Templates are found in this order: `<repo>/.work-packet/templates/`, then
`~/.work-packet/templates/`, then those built into work-packet. Built-in starting
set:

- `blank`: the prompt becomes the first instruction, nothing else.
- `periodic`: a recurring check that writes one report per run.
- `research`: plan, fan out to children per sub-question, merge the findings.
- `nightly-triage`: the dv-flow job proposed for the Phase 5 benchmark.

The project records the template name and version, so a later change to the
template does not silently change a project that is already running.

## The dashboard

`wpk dash` starts a local web server (default `127.0.0.1:7878`). It
binds to localhost only and has no login. Remote access goes through an SSH
tunnel. *(Superseded for remote access by `docs/server.md`: the board
listens on the tailnet and checks Tailscale identity.)* A terminal version (`wpk top`) can come later, built on the
same queries.

### Kanban board (home page)

One card per project. The project's column comes from its root packet state,
and the runner, not the user, sets it:

| Column | Root state | Card shows |
|---|---|---|
| Running | a step is running anywhere in the tree | which packet, step number, time so far |
| Ready | `RUNNABLE`, waiting for a slot | why it is waiting (limit or slot) |
| Sleeping | `SLEEPING` | next wake ("in 3 days, Mon 06:00"), recurrence |
| Waiting | `WAITING` on children or mail | what it waits for, its time limit |
| Needs you | `NEEDS_INPUT`, or anything in the tree is | the question, how long it has waited |
| Paused | `PAUSED` | reason: by hand, budget, step limit |
| Failed | `FAILED` | last error, which packet |
| Done | `COMPLETED` | finish time, final summary line |

The board is not a free-form kanban: dragging a card does not move it. The
columns show state, and each card has buttons that run commands (Pause,
Resume, Wake now, Cancel, Reply). This avoids the board and the files
disagreeing about where a project is.

Every card also shows: the last status line, spend today and in total, number
of packets with small per-state counts, and a badge if anything below the
root failed or needs input. That last point matters: a root can be quietly
`WAITING` while one of its children is stuck.

Filters: by tag, template, or text search. Sort within a column by due time.

### Project page

- **Packet tree**: each node shows packet ID (short), its state, step count and
  next wake. Click a node to open it.
- **Timeline**: steps across the whole tree on a time axis, coloured by
  packet, with sleep periods shown as gaps. It shows "what happened
  overnight" at a glance.
- **Files**: `state/`, `memento.md` and `status.md` for the selected packet,
  rendered as Markdown.
- **Actions**: Pause, Resume, Wake now, Edit wake time, Send message, Fork
  from step (needs P4), Archive.

### Step and transcript viewer

For one step, from `steps/<n>/`:

- the prompt as sent;
- the transcript, with the model's text, tool calls and tool results shown as
  collapsible blocks and long outputs truncated;
- what changed: `state.diff`, plus memento before and after;
- `meta.json`: duration, tokens, cost and model;
- the step's session ID, with a copy-ready command to open it in Claude Code
  for debugging. That command should fork the session rather than resume it,
  so the recorded history stays unchanged.

Previous and next buttons move between steps of the same packet. A search
box searches transcripts across one project.

### Other views

- **Upcoming**: a calendar or list of every scheduled wake in the next 30
  days across all projects. This is where you find "why will 12 projects all
  wake at 06:00 on Monday".
- **Inbox**: every `NEEDS_INPUT` item, newest first, with a reply box. A reply
  is written to the packet's `mailbox/`, which wakes it.
- **Spend**: cost per project per day, against each budget.

### How it updates

The page subscribes to a server-sent events stream fed from `events.jsonl`.
When a step finishes, the card moves and the timeline grows, without a page
reload. The server reads the same files as the runner. It needs no database
of its own.

Suggested stack: Python (same language as the executor if we choose Python),
Starlette or FastAPI, server-rendered HTML with htmx for the buttons, and SSE
for live updates. No front-end build step.

## Asking a human

Add one memento directive and one state, so a packet can stop and ask:

```
ask: "Three new failures look like the same AXI timeout. File one bug or three?"
choices: [one, three]       # optional
until: in 2 days            # optional; after that, wake with no answer
```

The executor sets the state to `NEEDS_INPUT` and writes the question into
`status.md`. The question appears in the dashboard inbox and in a notification.
The answer goes to `mailbox/` and wakes the packet, which sees the answer in
its next prompt. With `until:`, the packet wakes anyway when the time is up
and is told no one answered.

## Notifications

`config.toml` lists hooks per event type:

```toml
[notify]
needs_input = ["desktop", "webhook:https://hooks.example/wpk"]
failed      = ["desktop"]
completed   = []
budget      = ["desktop"]
```

`desktop` uses `notify-send`. `webhook` posts a small JSON event. Each event
links to the right dashboard page. Notifications are sent after the event is
written to `events.jsonl`, so they never change packet state.

## Permissions and safety

- Each project's `project.toml` sets what its steps may do: allowed tools,
  permission mode, and working directory, passed to `claude -p`. A template
  supplies defaults; `wpk new` prints them so the user sees them before
  the first step runs.
- Children cannot have more permissions than their parent.
- Credentials are never copied into `state/`. They stay in the user's
  environment or behind `identity/` links.
- The dashboard binds to localhost and checks the `Host` header, so a page in
  the browser cannot drive it from another site. Off localhost it needs
  authentication, plus Origin and CSRF checks: `docs/server.md` §4.

## Failure cases

| What fails | What happens |
|---|---|
| Runner killed | Leases expire; steps that were running are retried under P1 rules; missed wakes run once on restart |
| Worker killed mid-step | Same as above, for that one step |
| Two runners started | The second cannot get `runner.lock` and exits with a message |
| Manual `wpk step` while runner runs | The lease stops one of them |
| Project directory moved or deleted | The runner marks the registry entry missing and shows it on the board; nothing is deleted |
| A step loops forever on `resume: now` | Per-packet steps-per-hour limit pauses it |
| Model retired during a long sleep | Wake fails clearly (roadmap rule 6); card goes to Needs you |

## How this fits the roadmap

| Piece | Lands with | Exit test |
|---|---|---|
| `steps/<n>/` capture, `wpk step`, leases | P1 | A step's prompt, transcript and diff are all on disk after `kill -9` and retry |
| `wpk new` (blank template), registry, `adopt`, `ps` | P1 | `new` then `tick` runs step 1; a failed `new` leaves no registry entry |
| `wpk runner` and `tick`, limits, catch-up | P2 | Fake clock: 3 projects with mixed schedules over 30 days give exactly the expected steps, with at most 2 running at once |
| Dashboard, read-only: board, project page, step viewer | P2 | Every state in the column table shows up correctly from fixture directories |
| `ask:` / `NEEDS_INPUT`, inbox, mailbox wakes, notifications | P3 | A packet asks, a reply through the dashboard wakes it, and the answer is in its next prompt |
| Templates library, budgets, Spend view | P3 | Budget hit moves the project to Paused with reason "budget" |
| Fork from step, timeline across forks | P4 | Fork button creates a new packet that starts from step N |

Suggested first slice, small enough to finish and use: `wpk step`
with `steps/` capture, `wpk new` with the blank template,
`wpk tick`, and a read-only board. That is enough to run two or three
real projects and learn what the board is missing.

## Decisions

- **Projects live in arbitrary directories.** `--dir` takes any path; the
  registry records it. The runner never assumes a project is inside a repo or
  under `~/.work-packet/`.
- **Web dashboard first.** A terminal view may follow later, built on the
  same queries.
- **Transcripts are kept until pruned by hand** with `wpk prune`.
  No automatic compression or expiry for now. The Spend view can show disk
  use per project so you know when to prune.
- **Multi-machine sync is deferred but in scope.** Keep it possible: leases
  already include the host name, and registry entries and project files are
  plain files that could later sync through git.

## Open questions

- **One runner per user, or per machine?** Per user is simpler and matches
  systemd user services. A shared machine with several users may want one
  per machine later.
- **Board columns for big trees.** Is the root's state enough, or do large
  projects need a second board per project with one card per packet?
