# Packets as a way of working: review of the bigger picture and the IDE design

Status (2026-10-25): review for discussion. Nothing here is built. It
reviews `bigger_picture.md` and `docs/ide.md` against what is designed and
built elsewhere (long-running.md, setup.md §10, dash-tasks.md, server.md,
interaction.md), finds the sharp edges, and proposes a direction. Decisions
are marked **Proposed** and are for you to accept or reject.

Contents: §1 the picture · §2 will developers like it · §3 three kinds of
transfer · §4 sharp edges · §5 overlooked opportunities · §6 proposed
design · §7 build order · §8 questions for you · status log.

## 1. The picture

Pulling the documents together, the system you are describing is this:

> A **work packet** is a resumable unit of technical work with an
> address. It holds the instruction, the plan and notes (`state/`), the
> code it works on (`work/`), a journal of everything done, and the
> recipe to rebuild its workspace. Agents, people and batch jobs take
> turns working in it. One **board** shows every packet you have, what
> is running in each, and what is waiting for you. From any packet you
> can drop into a shell, a browser IDE or desktop VS Code at the right
> place, and you can hand the packet to the runner or assign it to a
> colleague. Where its files and steps live is the system's business.

What exists today (466 tests, not committed):

| Piece | State |
|---|---|
| Packet format, executor, atomic steps for `state/` | built (spec v0.2) |
| Runner in the board process (`wpk dash --run`), poke, lock | built (T1) |
| Board: answer, hand off, pause, notes, settings, live view, processes | built (I1–I3, I6 partial, I7) |
| New task, Compose, next batch, web shell (xterm.js + pty) | built (T2–T4) |
| Setup at the project root; packet `work/` = git worktrees on `wpk/<project>` | built (setup.md §10) |
| Tailnet login via Tailscale `whois` | built (S1); no TLS (S1b) |
| Ownership states v0.3 (`HELD`/`held_for`), `wpk take` | designed (L1), not built: the code still has `NEEDS_INPUT`/`PAUSED`/`FAILED` |
| Git reset/commit of work repos per step | designed (long-running §2), not built |
| Long jobs (`job:`, `resume: wait job:`) | sketched twice (long-running §10.1, stack-experiment), not designed |
| IDE (ide.md) | designed, not built |
| Multi-user, packet URLs across hosts, remote stores, templates "from X", resource-aware scheduling, non-agent job status | `bigger_picture.md` only |

The bigger picture moves the project from "an agent runner with a
board" to "a work container with a portal". That is the right instinct:
the agent loop is becoming a commodity (Claude Code, Codex, Cursor and
Devin all run background agents now), but nobody gives you a persistent,
addressable, on-prem unit of work that agents, people and simulators
share. That is where this can stand out.

## 2. Will developers like it?

Short answer: **yes, for the users with long, expensive, stateful work, if
the first five minutes are easy and the packet never surprises them about
which copy of the code they are editing.** For developers with a fast
edit-test loop it is overhead, and they will stay in Claude Code alone.

| Who | Pain today | Fit |
|---|---|---|
| DV engineer triaging regressions | a failing test means: find the revision, rebuild, rerun with the seed, open waves, keep notes somewhere, hand the bug to the owner with a wall of text | **strong.** A packet *is* the bug, with its reproduction |
| Firmware/HW developer with hour-long builds and sims | agent sessions die while sims run; four terminals, three tmux sessions, two machines | **strong**, once non-agent jobs report status (§4.6) |
| Lead/reviewer | can't see what five background agents are doing without attaching to each | **strong**: the board and "Needs you" |
| Web/app developer, seconds-long tests | none that a packet solves | weak: the ceremony costs more than it saves |

What developers will like:

- **One place to look.** Running, waiting, sleeping, done, across every
  project and host, with the question that is blocking each one. This is
  the "without hopping between terminals" goal, and the board already
  delivers most of it for agent work.
- **Nothing is lost.** Plans, notes and step history survive a closed
  laptop, a crashed session and a week away.
- **Hand-off is a button, not a write-up.** The recipient gets the
  context, not a summary of it.
- **It is files and git.** Inspectable, greppable, no lock-in. That matters
  in IP-sensitive shops.

What will put them off (each is a sharp edge below):

- **Vocabulary.** Packet, memento, seed, hand-off, batch, take, pause,
  identity, held-for. Each makes sense; together they are a lot before a
  first result. (§4.9)
- **Which copy is this?** Your clone at the project root, the packet's
  worktree on `wpk/<project>`, a smoke worktree in `.setup/`. (§4.1)
- **Advisory ownership.** The board says "the runner owns this", but your
  editor, formatter and git extension do not know. (§4.2)
- **Setup ceremony** before the first useful step. Compose helps; "create
  from X" templates (§5.2) would help more.
- **Trust.** A background agent with Bash on your account. The allow-list
  and no-push rule are good; they need to be visible on every card.

## 3. Three kinds of transfer

"Seamless transfer" means three different things in the documents, and
they need different mechanisms. Naming them keeps the design clear.

| Transfer | Example | Mechanism | State |
|---|---|---|---|
| **Turn**: person ↔ runner | hand off, take back, answer | ownership in `status.md`, lease, journal record | built (as pause/handoff); v0.3 names designed |
| **Surface**: board ↔ shell ↔ IDE ↔ phone | start a clone in the browser shell, continue it in VS Code's terminal, check on it from the iPad | sessions that belong to the packet, not to a window | partly: web shells live 30 min and die with the server |
| **Custody**: person ↔ person, CI → person | CI fails → packet → colleague opens it on their machine | a portable packet bundle, a store, an address | `bigger_picture.md` only |

Host to host is **not a user concern**. Which machine holds a packet's
files, and where its steps and jobs run (another host, a SLURM node),
is placement: the runner and the hub decide it, and the user sees one
address that resolves to wherever the packet is (§6.3). It uses the
same export and import underneath, with no command of its own.

**Proposed:** keep "hand off" for *turn* only; person to person is
**assign**, and the file is made by
**export** and read by **import** (§3.1). Today's documents use
"hand-off" for both, and the journal needs the distinction (`handoff`
records `to: runner|human`; an `assign` record has `from_user`,
`to_user`).

### 3.1 Names (question 6, researched)

What established tools call the same operations:

| Operation | Agent tools | Trackers and ops | Infrastructure |
|---|---|---|---|
| person → agent, and back | Devin `/handoff`, Codex "Handed off to local", Vibe Kanban "hand off"; Cursor and Devin **take over**; Linear **delegate** (to an agent, you stay accountable); Copilot **assign** an issue to Copilot | — | — |
| person → person | — | GitHub, Jira, Linear **assign** / reassign (a field changes, no data moves); GitHub **transfer** (the whole issue moves with its history); PagerDuty reassign vs escalate | — |
| to and from a file | Jules `remote pull` (applies a diff) | — | Podman `checkpoint -e` / `restore -i`; Docker `save`/`load` (complete) vs `export`/`import` (flattened, loses metadata); `git bundle` |

Sources: docs.devin.ai (`cli/handoff`, session tools), cursor.com changelog
0.50, github.com/openai/codex issues 34238 and 50021, linear.app/docs
(assigning issues), docs.github.com (Copilot cloud agent; transferring an
issue), support.pagerduty.com (reassign),
podman.io/docs/checkpoint, git-scm.com/docs/git-bundle, ampcode.com/news/handoff.

**Proposed names:**

| Operation | Verb | Why | Pitfall and how we handle it |
|---|---|---|---|
| person ↔ runner | **hand off** / **take** (say "take over" in prose) | the agent tools' own words | Amp's `/handoff` means "start a new thread from a summary". The docs say the packet moves whole. Take always stops the runner first, as Devin does, so the two never edit together (already the design) |
| person → person | **assign** | every tracker's verb; it matches the hub, where ownership changes in the index and the recipient fetches the bundle | in trackers, assign moves no data. Here it means "ownership changes, and the bundle is waiting for you"; Open imports it. `transfer` (GitHub's "the object and its history move") is the alternative if assign reads too lightweight |
| to and from a file | **export** / **import**; the file is a **bundle** | Podman and Docker | Docker's `export` drops metadata; ours is complete (instruction, notes, journal, repo commits, unpushed work as a git bundle), and the docs say so. Export alone is a copy. Not `push`/`pull`: packets hold git worktrees, so readers would think of git refs |

Not used: **delegate**. Linear's meaning (give the work to an agent,
stay accountable) is our hand-off, and using it for people would
collide.

## 4. Sharp edges

Ordered by how soon they bite.

### 4.1 ide.md is written for the superseded workspace model

ide.md §1–§2 follows long-running.md §2: clones live *inside* the packet
under `work/`. What was built (setup.md §10) is different: your clone is
at `<project>/work/<repo>`, and the packet holds a **git worktree** of it
on branch `wpk/<project>`. Consequences for the IDE:

- There are two editable trees of the same repo. Edits in your clone (on
  your branch) never reach the packet; the runner's commits land on
  `wpk/<project>`, which you **cannot check out in your clone** while the
  packet's worktree has it.
- Before the seed you set up at the root; after it the shell starts in the
  packet (dash-tasks §5.4). The IDE must follow the same rule, or the
  button opens the wrong tree.
- The workspace file's folder list must say which tree each folder is.
  Opening both, unlabelled, invites edits in the wrong one.

**Proposed:** the workspace file follows dash-tasks §5.4. Before the seed
it opens the project root (`work/*`, `state/`, `prompt.md`); after it, the
packet's worktrees, named `dv-solve (packet: wpk/dvs-enh)`. Your own clone
is never in the packet's workspace. ide.md §2 is rewritten on this basis
before I1.

### 4.2 Ownership is advisory, and VS Code is busy

`files.readonlyInclude` stops a save. It does not stop:

- **VS Code's git extension.** It runs `git status` on every change and,
  with `git.autofetch`, `git fetch`. Both can hold `.git/index.lock` (in
  a worktree, `.git/worktrees/<n>/index.lock`) at the moment the executor
  commits or resets. A step failing with "index.lock exists" is a likely
  first bug. *To check:* whether VS Code passes `--no-optional-locks`
  everywhere; whether `fetch` touches shared refs the step reads.
- **Format on save, linters, language servers** writing caches
  (`.mypy_cache`, `__pycache__`, `compile_commands.json`, `.metals`) into
  the tree. Most are ignored files and survive a reset; some are not.
- **The integrated terminal.** ide.md says so already.
- **Watchers.** A worktree with `packages/` (Verilator, Yosys) or a sim
  `rundir/` has hundreds of thousands of files. VS Code's watcher and
  search will be slow and can exhaust inotify watches, which then breaks
  other tools on the host.

**Proposed:** the generated workspace sets, while the runner owns the
packet, `git.autorefresh: false`, `git.autofetch: false`,
`editor.formatOnSave: false`; and always `files.watcherExclude` and
`search.exclude` for `**/packages/**`, `**/rundir/**`, `**/build*/**`,
the packet's `steps/` and `.pending/`. The executor retries a git command
once on `index.lock`. Read-only stays a guard against mistakes, and the
board says so.

### 4.3 The workspace file is shared with VS Code

VS Code writes to the `.code-workspace` file when you add a folder or
change a workspace setting from the UI. ide.md has wpk rewrite the whole
file on hand-off, take and every step commit, which will overwrite your
changes, and VS Code will offer a "file changed on disk" dialog at
awkward times.

Also: listing `..` (the packet) as a folder alongside `../work/x` and
`../state` shows every file twice in the explorer and in search, plus the
journal and every transcript.

**Proposed:** wpk updates only the keys it owns (`folders`, and the
settings in §4.2), merging into the JSONC; it rewrites only when those
change, not on every step commit. The packet folder gets
`files.exclude` for `work/`, `state/`, `steps/`, `.pending/`.

### 4.4 Web VS Code needs HTTPS, and may need the internet

- VS Code web uses service workers for webviews (Markdown preview, most
  extension UIs). Browsers allow service workers and the clipboard API
  only in a secure context: `https://` or `localhost`. The board on
  `http://a9550:7878` over the tailnet is neither. **I3 depends on S1b
  (Tailscale TLS)**, which ide.md does not list.
- `code serve-web` downloads the matching server build from Microsoft on
  first use and on each update, and webviews may load from a
  Microsoft-hosted origin. *To check in the I3 spike:* behaviour with no
  internet. Many EDA sites are air-gapped.
- The VS Code Server licence allows personal remote use; hosting it for
  other people is restricted. That is fine for one user's wpkd and not
  fine for the multi-user server in `bigger_picture.md`.

This answers the "should we consider the OSS version?" question: **yes,
as the second backend.** `openvscode-server` (or code-server) is the
answer for air-gapped and multi-user installs; `serve-web` is the
convenient one for a single user with internet. The proxy should not care
which it fronts (both take a socket or port and a base path).

### 4.5 Ownership names and `take` are not built

ide.md §5 and I2 are written in v0.3 terms (`HELD`, `RUNNABLE`, take
during a step). The code has `NEEDS_INPUT`/`PAUSED`/`FAILED` and
`pause`, which does not wait for a running step. I2 can ship on today's
states (`pause` when not running; button disabled while running) and
gain "take after this step" with L1. Otherwise I2 waits on L1, which is
not scheduled.

### 4.6 Non-agent jobs have no home

Three things point at the same missing piece:

- `bghook.py` blocks background Bash because the step ends before the
  result arrives (dv-solve trial, steps 16–17);
- long-running §10.1 and stack-experiment both sketch `resume: wait
  job:<id>` for 17-minute to 2.5-hour runs;
- `bigger_picture.md` wants a dv-flow-mgr run started in a packet, by a
  person, to show progress on the board.

Nothing designs it yet, and the live view's process panel only sees a
step's own processes. Without it, "track background work without hopping
terminals" holds for agents only, and a DV engineer's longest-running
work (sims, regressions, formal) is still in a terminal somewhere. This
is the largest gap between the vision and the plan. §6.2 proposes a
design.

### 4.7 Multi-user breaks "the board is a shell"

server.md §1 rests on one rule: logging into the board equals a shell on
the daemon's account. A multi-user server that runs packets for several
people either runs everyone's agents as one Unix user (everyone can read
and change everyone's work, and commits carry the wrong identity), or
runs a privileged daemon that switches users (root, PAM, a real security
review). Both are large.

**Proposed:** federation, not multi-tenancy. Each person keeps their own
wpkd, as now. A small shared **hub** knows packet addresses and where
each packet is, and holds bundles (§6.3). Passing a packet moves a
bundle between two people's daemons; nobody's daemon runs someone else's
code. The rule in server.md §1 stays true.

You confirmed this direction (2026-10-25): per-user dashboard servers
that connect to a central hub, as an incremental step that does not
commit to one central multi-user server. It also leaves that option
open: the hub's index, addresses and store are what a central server
would need first anyway. The steps:

1. **No hub.** Bundles go by file (§6.3). Already enough for CI artefacts.
2. **Hub as index and store.** Each wpkd registers its packets (address,
   owner, state, host, board URL) and pushes a summary on each event.
   The hub shows a read-only board of everyone's packets, "Assigned to
   you", and links back to the owner's wpkd for anything else. The
   hub never runs steps and never holds a shell.
3. **Later, if wanted:** hosted runners on the hub, which is the
   point where per-user identity and isolation (above) must be solved.

The connection is outbound from each wpkd to the hub (so a wpkd behind
NAT or on a laptop works), authenticated by the user's identity on the
hub (Tailscale `whois` on a shared tailnet, or a token). The hub shows
packet summaries, not files, so a viewer on the hub cannot read code
or transcripts unless the owner bundles them.

### 4.8 Packets are not portable today

A packet points outside itself in several ways: `identity/` holds
absolute symlinks; `work/<repo>` is a worktree whose `.git` file names
the root clone's path; plain `work/` entries are relative links to the
root; `steps/*/transcript.jsonl` holds absolute paths and whatever the
model read, which may be proprietary. Uploading a packet as-is to S3 or a
CI artifact gives something that cannot be opened elsewhere, and may leak
IP.

`bigger_picture.md` asks for "teardown that expunges derived data, by
default before hand-off". That conflicts with the industry-survey's gap
2 ("keep the expensive artifacts"). Both are right, for different
transfers: a *turn* keeps everything; an *assign* ships the core
and leaves or references the rest. §6.3 makes the tiers explicit.

### 4.9 Too many words, surfaces and documents

- 15 design documents, several partly superseded (long-running §2 by
  setup.md §10; `pause` by `take`; `NEEDS_INPUT` by `HELD`). A fresh
  session or a new user cannot tell which is current.
- Front ends: CLI, board, TUI, web shell, VS Code tasks, maybe an
  extension. `actions.py` keeps the logic in one place, which is good,
  but each front end is UI to maintain and test.

**Proposed:** a short `docs/concepts.md` (glossary, the three transfers,
the current state machine, which document is current for what), and
treat the board and VS Code as the primary surfaces. The TUI (I5) drops
to "if asked".

### 4.10 Smaller edges

- **Several hosts** (ide.md open question 2): the link must name the host
  where the packet's files are, not wpkd's. With federation (§4.7) every
  packet's files are on its own daemon's host, which settles it.
- **Continue in VS Code** (ide.md §6) runs an interactive `claude` in a
  VS Code task terminal, which is awkward (tasks are for commands that
  end). Use a terminal profile instead. And what the conversation finds
  goes nowhere: offer "send as a note" at the end (§5.6).
- **Web shells die with the server** (dash-tasks §5.2) and with a 30-min
  detach. For "resumable mini-containers" that is too short (§6.1).
- **Notifications** are still open (long-running §10.5). Without them the
  board must be watched, which is terminal-hopping by another name.
- **Resource limits** are one global `max_concurrent`. On a DV host the
  scarce resources are simulator and formal **licences**, CPU and memory,
  not agent sessions.

## 5. Overlooked opportunities

### 5.1 "Step into the bug": the flagship flow

The single most persuasive demo for a DV audience:

1. A CI regression fails. The CI script (below)
   runs `wpk export --from-ci`, which writes a small packet bundle: repo
   URL and commit, the test and seed, the command, the log tail, and
   optionally waves. It uploads it as a CI artifact or to the hub.
2. The board shows a card on the owner's board: "test `uart_rx_overrun`
   seed 42 failed at abc123".
3. **Open** materializes it: worktree at abc123, setup recipe run, and
   the reproduction is the setup's smoke check (setup.md `[[setup.smoke]]`).
   "Reproduced in 3 min" or "did not reproduce".
4. Hand to the agent ("find the root cause; don't fix"), or **Open in VS
   Code** at the failing line with the log beside it, or assign it to the
   RTL owner.

Each piece mostly exists: `[setup]` is already a recipe (repos, inputs,
links, smoke). The new parts are the bundle, import and the CI hook.
This flow is worth building end to end before broadening.

**Where to try it** (your answer to question 3): featherweight-ip first,
then fvutils `dv-solve`, `pyvsc` and `pyhdl-if`.

- featherweight-ip's repos run CI as a **pair** of workflows,
  `.forgejo/workflows/ci.yml` and `.github/workflows/ci.yml`, that both
  call `ci/run.sh`, which also runs on a laptop (`fw-ic-chi`,
  `fw-proto-chi`). dv-solve and pyhdl-if have both forges too. So the
  bundle is written by the script, not by a forge-specific action:
  `ci/run.sh` calls `wpk export --from-ci` for each failing test (a no-op
  when `wpk` is not installed), and each side's existing artifact upload
  (`forgejo/upload-artifact`, `actions/upload-artifact`) adds the bundle
  files. Nothing new on either forge, and the pair stays in step.
- `wpk export --from-ci` reads what the forge already sets
  (`GITHUB_SERVER_URL`, `GITHUB_REPOSITORY`, `GITHUB_SHA`, `GITHUB_RUN_ID`;
  Forgejo sets the same names) for the repo URL, commit and a link back
  to the run. The test name, seed and command come from arguments.
- featherweight-ip is the DV case (sims, seeds, waves); the three fvutils
  repos are the Python/C++ case (pytest failures, no waves). If the same
  bundle and smoke-as-reproduction work for both, the design is general.
- Importing a bundle with only a forge artifact link needs a token for
  the forge's API. The first version takes a downloaded file; fetching by
  URL comes with the hub's stores (§6.3).

### 5.2 Templates "create from X" are recipes, not prompts

runner.md has `templates/` for prompts. `bigger_picture.md`'s "create
from repo/ref", "from issue", "from CI failure" are really **setup
recipes plus a prompt**: which repos at which refs, what inputs to
fetch, what smoke to run, which profile. Make a template a `project.toml`
`[setup]` fragment with parameters plus an instruction template. The
Compose page then starts with checks already green.

### 5.3 A JSON API, then a small VS Code extension, sooner

The board has HTML routes only. The VS Code extension (ide.md I4,
"maybe") is the best answer to "track background work without hopping":
a status-bar item with the Needs-you count across all packets, a tree of
packets with their state, notifications, hand off and take as commands.
VS Code is where developers already are; the tasks in ide.md §2 are a
stop-gap they will not discover.

It needs a read API (`/api/board`, `/api/p/<wpid>`, an SSE stream from
`events.jsonl`). The same API serves the hub, the TUI over the network,
CI, and scripts. **Proposed:** define the API in S2 and move the
extension from "maybe" to after I1.

### 5.4 Review is the commonest reason to open the IDE

ide.md opens a packet to *edit* it. After a batch, most visits will be to
*review* what the runner did: the commits on `wpk/<project>` since the
hand-off. Add **Review in VS Code**: opens the worktree and the diff of
`base..HEAD` (the journal has both heads, T2). And **Open at step N**: a
detached worktree at that step's commits, to see the code as the model
saw it. Both are cheap given the heads already recorded.

### 5.5 One progress protocol for every tool

If any tool can report progress by appending JSON lines to a file named
in `$WPK_PROGRESS`, the board can show it, and an adapter per tool is
optional (§6.2). Tools that do not write it get an **adapter in wpk**
that reads what the tool already prints and writes. dv-flow-mgr is the
first: its graph, console log and per-task `exec_data.json` are enough
for the "graph and what is covered" view with no change to dv-flow-mgr
(§6.2.1). pytest, make/ninja and SLURM's `sacct` follow the same
pattern.

### 5.6 Fold conversations back

A forked conversation (ide.md §6), a web shell session and a VS Code
session all produce knowledge the packet then forgets. At close, offer
"add a note": a short summary into `mailbox/` (written by you, or
summarised by the model and shown to you first). The next step sees it.

### 5.7 Packets as the unit of measurement

Every packet has a cost, a duration, a step count and an outcome
(`stats.py`). Across many, that answers questions managers ask: what a
triage costs, how often the agent reproduced the bug, time from failure
to root cause. The industry survey says nobody connects board and
statistics. A per-template report is cheap.

### 5.8 Licence-aware scheduling

`bigger_picture.md` asks for resource-aware scheduling. For DV, the
resource that matters is licences (Xcelium, VCS, JasperGold seats).
Named resource pools (`[resources] xcelium = 4`, a step or job declares
`needs = ["xcelium"]`) are a simple model that SLURM's GRES or licence
counters can back later. No agent product does this.

## 6. Proposed design

Four pieces, each usable alone. Sizes are rough.

### 6.1 Packet sessions: one shell per packet, reachable from anywhere

A **packet session** is a shell that belongs to the packet, not to a
window. It starts where dash-tasks §5.4 says, with the wizard's rc file
and environment, and is reachable from every surface:

- the board's xterm.js attaches to it, as now;
- VS Code gets a terminal profile "packet shell" in the workspace file
  that runs `wpk attach <session>`: the same session, in the IDE;
- SSH: `wpk attach <target>`.

It outlives the browser, a server restart and a closed laptop. That is
what makes the packet feel like a container.

**tmux is optional** (your answer to question 2). Some users want it,
others do not, so sessions have two backends behind one interface
(`start`, `attach`, `list`, `is_idle`, `close`):

| `[sessions] backend` | How a session is held | For |
|---|---|---|
| `wpk` (default) | a small **holder** process per session (`wpk _hold`, in the style of `dtach`): it owns the pty, keeps the 256 KB replay buffer, and listens on `$WPK_HOME/sessions/<id>.sock` (0700 directory). wpkd, `wpk attach` and the VS Code profile are all clients of the socket. The holder is not a child of wpkd, so a server restart leaves it running | everyone; no new dependency |
| `tmux` | a tmux session named `wpk-<project>-<short wpid>`; attach is `tmux attach -t`; the board's pty runs that | people who live in tmux and want the packet's shell in their own tmux, with its key bindings and splits |

The holder moves today's `dash/shells.py` sessions out of the server
process; the WebSocket side stays as it is. With the tmux backend, a
user's own `tmux ls` shows the packet sessions, and `wpk attach` is just
a short way to name one.

**Idle or active**, the question in `bigger_picture.md`. Both backends can
tell: the holder compares the pty's foreground process group
(`tcgetpgrp`) with the shell's PID and records the time of the last
output; tmux reports `#{pane_current_command}` and `#{window_activity}`.
If the foreground process is the shell and nothing has been written for
`idle_minutes`, the session is **idle**: the board shows it dimmed and
may reap it after `idle_hours`. A session with a foreground process is
**active** and is never reaped. **Restore** is a new session in the same
directory with the same history file; process state is not kept, and
nobody expects it to be. Long work that must survive belongs in a job
(§6.2), not in a shell.

This partly reverses dash-tasks §5.2 ("not kept across a server
restart"), without making tmux a dependency.

Hand-off closes the packet's sessions (dash-tasks rule 4), unchanged.

### 6.2 Jobs: background work that is not an agent

A **job** is a command started in a packet that outlives whoever started
it: a person in a packet session, or a step.

```
wpk job start [--name N] [--needs xcelium] [--slurm] -- dfm run regress
```

Writes `jobs/<id>/` in the packet (outside the committed files, like
`mailbox/`):

```
jobs/<id>/
  job.json        cmd, cwd, who, started, host, pid or slurm id, needs
  log             stdout and stderr
  progress.jsonl  optional, appended by the tool via $WPK_PROGRESS
  graph.json      optional, a task graph (nodes, edges), for tools that have one
  exit            written when it ends: {"code": 0, "t": ...}
```

- The process runs in its own session under a small supervisor (`wpk job
  _run`), which writes `exit`. A backend interface (`local`, `slurm`) is
  the pluggable launcher `bigger_picture.md` asks for; SLURM jobs are
  polled with `sacct`.
- **Progress protocol:** one JSON object per line, all keys optional:
  `{"t", "phase", "done", "total", "msg", "node", "node_state"}`. The board
  shows the latest line, a bar if `total` is set, and the graph coloured by
  `node_state` if `graph.json` exists. Adapters (`wpk job start --adapter
  pytest|ninja|dfm`) parse a tool's output into the same lines.
- **From a step:** the model runs `wpk job start ...` and ends its turn
  with `resume: wait job:<id>` (stack-experiment). The runner wakes the
  packet when `exit` appears, and the next prompt shows the exit code, the
  log tail and the last progress line. `bghook.py`'s message points the
  model at `wpk job start` instead of refusing with no alternative.
- **Ownership:** a job belongs to the packet, not to an owner. A job you
  started keeps running after you hand off; the step prompt lists running
  jobs. Take and hand off do not kill jobs; `wpk job stop <id>` does.
- **Resources:** `--needs` counts against named pools in `config.toml`; a
  job waits for a free unit. Steps can declare `needs` too.
- **Board:** a Jobs panel on the packet page and a jobs count on each card
  ("2 jobs, regress 61%").

#### 6.2.1 The dv-flow-mgr adapter

Your direction (question 4): keep cross-project dependencies small, and
have work-packet understand dv-flow. So the adapter lives in wpk
(`work_packet/adapters/dfm.py`) and uses only what dv-flow-mgr already
offers. Checked against `~/projects/dv-flow/dv-flow-mgr` at bfb54a7
(paths under `src/dv_flow/mgr/`):

| Need | Source in dv-flow-mgr today | When available |
|---|---|---|
| the task graph | `dfm graph <task> [-D …] --json` (`cmds/cmd_graph.py`): DOT text between `<<<DFM_GRAPH_BEGIN>>>`/`<<<DFM_GRAPH_END>>>` markers | before the run, one extra elaboration |
| per-task state, live | the console listener with `-u log -v` (`task_listener_log.py`): `>> [n] Task X` when a task starts, `<< [n] Task X (up-to-date\|cache\|base) 1.2s` when it ends, failures marked | during the run, in the job's `log` |
| per-task result | `exec_data.json` in each task's directory (`task_node.py:318`), with `result.status`, `rundir`, `logfile`, `needs`; written as each task finishes. An up-to-date task does not rewrite it | during the run, by polling mtimes against the job's start |
| timings | `rundir/log/<pkg>.trace.json` (Chrome/Perfetto) | at the end only, and not written if the run raises |

What the adapter does, for `wpk job start --adapter dfm -- dfm run <task> …`
(or `dfm` detected as the command):

1. Runs `dfm graph` with the same task and `-D` options, parses the DOT
   into `graph.json` (nodes, edges). The board draws it.
2. Adds `-u log -v` if the command has no `-u`, and tails the log: `>>`
   sets a node `running`, `<<` sets it `done`, `skipped` (up-to-date,
   cache, base) or `failed`. Each change is a `progress.jsonl` line with
   `node` and `node_state`.
3. Polls `exec_data.json` files newer than the job's start, to confirm
   results and link each node to its `logfile` (the board's node opens
   the task's log). This also covers a run started with another `-u`,
   at lower fidelity.
4. Progress is done ÷ graph nodes, shown as approximate ("~61%"): the
   runtime count also includes compound sentinels and matrix or loop
   expansions that the static graph does not.
5. At the end, reads `trace.json` if present for per-task timings.

Known limits, none blocking:

- "skipped" and "not reached yet" look the same on disk; the log lines
  tell them apart, so step 2 is the main source.
- With `dfm daemon` running, leaf tasks dispatched to it are also
  visible through its `monitor.subscribe` socket (`daemon.py`); the
  adapter can use it later, but does not need it.
- Not used: patching `TaskSetRunner` to add a listener. It would give
  exact totals, at the price of depending on dv-flow-mgr internals.

Changes in dv-flow-mgr that would help, if it wants them for its own
sake (none is needed): a JSON-lines event stream (`--events <file>`), a
nodes-and-edges JSON from `dfm graph`, a run-in-progress marker in
`rundir/`, and `exec_data.json` for failed remote tasks. The adapter
would prefer them when present.

### 6.3 Bundles, stores and addresses

**Address.** A packet's address is `wpk:<wpid>`, plus an `https://` form
on the hub (`https://<hub>/p/<wpid>`) that resolves to wherever the
packet is now and offers Open. Board URLs today are
`/p/<project>/<wpid>`; a `/p/<wpid>` redirect on every wpkd makes the
WPID alone enough.

**Tiers.** A packet has three tiers of data:

| Tier | What | In a bundle | Kept on a turn |
|---|---|---|---|
| **core** | `status.md`, `memento.md`, `state/`, `journal.jsonl`, step summaries and diffs, `project.toml` (with `[setup]`), `prompt.md`, notes | always | yes |
| **record** | step transcripts and logs, job logs | by choice; scrubbed of absolute paths | yes |
| **derived** | work trees, builds, sim outputs, waves, coverage | never by default; named artefacts by choice (`--with waves/*.fst`), or a pointer to where they are | yes |

**Bundle.** `wpk export <target> [-o file|--to store]` writes a tar of the
core (and chosen record and derived files) with a manifest: wpid, source
host, each work repo as URL + branch + commit, unpushed commits as a git
bundle, `identity/` links as names to be rebound, not paths.
`wpk import <bundle|url>` creates the project and packet, and
**materialize** runs the setup recipe: clone at the recorded commits,
apply the git bundle, rebind identity links (asking for ones it cannot
find), run smoke. Teardown is `wpk clean <target>`: remove the derived
tier, keep the recipe. **Clean before export** is the default; **clean
before turn** never is.

**Transcripts in a bundle** (question 5, asked again). The question:
*when a packet leaves your machine, should the model's raw step
transcripts go with it?* What is at stake:

- Every step already leaves a curated record that always travels: its
  `summary.md`, the memento it wrote, `work.diff`, the journal (decisions,
  hand-offs, answers, notes, costs). That is enough to understand what
  happened and why.
- A transcript (`steps/NNNN/transcript.jsonl`) is the full conversation:
  every file the model read, every command's output. It is the only
  place to answer "why did it do that?" in detail, it is large (often
  megabytes per step), and it is where IP and secrets end up: source and
  RTL from outside the packet (the dv-solve trial read `~/xezim_research/`),
  environment dumps, tokens printed by a tool.
- Scrubbing absolute paths makes a transcript portable. It does not make
  it safe to share: the content is the risk, not the paths.

**Proposed resolution: out by default, kept at the source, fetched on
request.**

1. A bundle carries, for each step, the transcript's size and SHA-256 and
   where it is (`wpk:<wpid>/steps/0007/transcript` on the source wpkd),
   not the file.
2. The recipient's step page says "transcript on <owner>'s server" with
   **Request**. The request goes through the hub to the source wpkd; the
   owner sees it on their board and approves or declines per step or per
   packet. Approved files come back through the store and are checked
   against the hash.
3. `wpk export --with transcripts` includes them on purpose. They are
   path-scrubbed (`$HOME`, the project path and the host name become
   placeholders), and the command lists the paths outside the packet that
   the transcripts read, so you see what you are about to share before it
   goes.
4. CI bundles have no transcripts (no model ran). When the system
   relocates a packet between your own hosts (below), they go with it,
   since nothing leaves your custody.

If you would rather keep it simpler for the first version: leave
transcripts out with no request path (step 1 and 3 only), and add the
request when the hub exists. Your choice: (a) the full proposal, (b) the
simple version first, or (c) something else.

**Stores.** A store is a URL scheme with put, get and list: `file://`,
`s3://` and `r2://` (one S3 client), `gh-artifact://` (read only). The hub
is a store plus an index of addresses, owners and locations.

**Assign.** `wpk assign <target> <user>` exports, uploads to the hub,
changes the owner in the hub's index and records an `assign` journal
record; the local copy becomes read-only (`ASSIGNED`, with the address).
The recipient's board shows it under "Assigned to you"; Open imports it.

**Placement** (internal, no user command). When the runner or the hub
moves a packet between hosts (to where a licence, a GPU or a SLURM
partition is, or off a machine being retired), it exports, imports on
the target wpkd, retires the source, and updates the address in the
hub's index. Board and IDE links resolve through the address, so they
keep working. The journal records it (`placed`, `from_host`, `to_host`)
for the record, not for the user to act on.

This keeps every daemon single-user (§4.7), works with no hub at all
(bundle to a file, send it), and makes the CI flow (§5.1) a bundle
producer.

### 6.4 The IDE, revised

ide.md stands, with these changes:

1. Workspace folders follow the built layout (§4.1); the packet's
   worktrees are labelled; your clone is not included after the seed.
2. Generated settings for watchers, search and git while the runner owns
   the packet (§4.2); the executor retries on `index.lock`.
3. Merge-only updates of the workspace file; packet folder excludes
   (§4.3).
4. A "packet shell" terminal profile (`wpk attach`) on the packet
   session (§6.1), instead of a plain terminal.
5. **Review in VS Code** and **Open at step N** (§5.4).
6. Web IDE depends on S1b TLS; spike checks offline behaviour; the proxy
   supports `serve-web` and `openvscode-server` (§4.4).
7. I2 ships on today's states with `pause`, gains take-after-step with L1
   (§4.5).
8. Continue in VS Code uses a terminal profile and ends with "send as a
   note" (§4.10, §5.6).
9. The extension follows I1, on the JSON API (§5.3).

## 7. Build order

Proposed, with the reason for each position:

| # | What | Why here | Depends on |
|---|---|---|---|
| 0 | `docs/concepts.md`; rewrite ide.md §2 on the built layout | cheap; stops building on the old model | — |
| 1 | IDE I1 with §6.4 items 1–3 | the first daily-use win; nothing new needed | — |
| 2 | Packet sessions: holder by default, tmux optional (§6.1) | the surface-transfer goal; makes I1's terminal right | — |
| 3 | Jobs, local backend, progress protocol (§6.2) | closes the largest gap; unblocks long sims in steps | — |
| 4 | JSON API + SSE (part of S2), notifications | needed by the extension, hub and CI | — |
| 5 | VS Code extension: status bar, tree, notify | "track without hopping", where developers are | 4 |
| 6 | Bundles, `import`, materialize, `clean`; file store (§6.3) | portability, before any server | — |
| 7 | CI action + "step into the bug" (§5.1) | the flagship demo | 6 |
| 8 | S1b TLS, then web IDE I3 | needed for the iPad; lower than the desktop flow | S1b |
| 9 | Hub: per-user wpkd registers outbound; addresses, read-only cross-user board, S3/R2 store, assign | multi-person, without a shared server | 4, 6 |
| 10 | Resource pools, SLURM backend | when a second host or licences bite | 3 |

L1 (v0.3 states, take) and the work-repo reset/commit (long-running §2)
should be scheduled alongside 1–3. The IDE makes the absence of work-repo
atomicity visible: today a failed step leaves its edits in the worktree.

## 8. Questions for you

1. ~~Federation vs. one shared server~~ Settled: per-user wpkd plus a
   hub (§4.7). Open: what the hub shows to people other than the owner
   (state only, or summaries and the question as well)?
2. ~~tmux as a dependency~~ Settled: optional. The default is wpk's own
   session holder; tmux is a backend for those who want it (§6.1).
3. ~~Where the flagship flow starts~~ Settled: featherweight-ip, then
   fvutils dv-solve, pyvsc and pyhdl-if; the bundle is written by
   `ci/run.sh`, so both forges get it (§5.1). Open: which fw repo and
   which failing test to use first (fw-uart16550, as in long-running §3?)
4. ~~dv-flow-mgr~~ Settled: wpk reads dv-flow-mgr as it is (graph
   command, `-u log -v` lines, `exec_data.json`); no change upstream
   (§6.2.1). Open: is matching the console log text acceptable, given it
   may change between dv-flow-mgr versions? (The adapter would pin the
   patterns with a test against a recorded run.)
5. **Transcripts in a bundle** (§6.3, asked again with a proposal): out
   by default, kept at the source and fetched on the owner's approval;
   `--with transcripts` to include them, scrubbed of paths. Take the full
   proposal, or the simple version first (out, no request path)?
6. **Names** (§3.1, researched): hand off / take, **assign**,
   **export** / **import**; host to host is internal placement, with no
   user verb. Accept, or prefer `transfer` to `assign`?

## Status log

### 2026-10-25: review written

Read `bigger_picture.md`, ide.md, and the related designs and status logs.
Checked in the code: the board has no JSON routes (`dash/app.py`); states
are still v0.2 (`schema.py`: `NEEDS_INPUT`, `PAUSED`, `FAILED`); there is
no `take`; packet `work/` entries are worktrees of the root clone
(setup.md §10). Claims about VS Code (git locks, service workers needing
a secure context, `serve-web` downloads and licence) are from general
knowledge and should be checked in the I1 live check and the I3 spike.

### 2026-10-25: hub direction settled

You chose per-user dashboard servers connecting to a central hub over a
central multi-user server, as the incremental step. §4.7 now lists the
steps (no hub, then hub as index and store, then hosted runners if
wanted); question 1 is closed; build-order row 9 updated.

### 2026-10-25: MSB comments addressed

- Q2 tmux: optional. §6.1 now has a wpk session holder (dtach-style, a
  socket per session, survives server restarts) as the default, tmux as
  a backend.
- Q3 flagship: featherweight-ip, then fvutils dv-solve, pyvsc, pyhdl-if.
  Their CI is a Forgejo/GitHub workflow pair around `ci/run.sh`, so the
  bundle is written there (§5.1).
- Q4 dv-flow: researched dv-flow-mgr at bfb54a7; §6.2.1 adapter uses
  `dfm graph`, `-u log -v` lines and `exec_data.json`, no upstream change.
- Q5 transcripts: asked again with a proposal (out by default, fetch on
  the owner's approval, `--with transcripts` scrubbed), §6.3.
- Q6 names: researched (§3.1). Proposed hand off / take, assign,
  migrate, export / import; `wpk bundle` and "pass" renamed throughout.

### 2026-10-25: host to host is not a user concern

You noted that moving a packet between hosts is not something users do.
§3 and §3.1 drop `migrate` as a user verb; §6.3 describes it as internal
placement by the runner and the hub, behind the packet's address.
