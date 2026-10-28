# work-packet: product design

Status (2026-10-25): design for review. Nothing in this document beyond
what §2 lists as built exists yet. It turns `docs/workflow-review.md`
(the review of `bigger_picture.md` and `docs/ide.md`, with your
decisions) into one design for the product. Where it changes an earlier
design document, it says so; the earlier document is then updated when
that part is built.

Decisions still open are in §13, each with the default this design
assumes.

Contents: §1 the product · §2 starting point · §3 who it is for · §4
concepts · §5 architecture · §6 the packet · §7 wpkd · §8 sessions · §9
jobs · §10 the IDE · §11 export, import and the hub · §12 security ·
§13 open decisions · §14 releases · §15 not in scope · status log.

## 1. The product

**work-packet makes a piece of technical work into a thing you can
leave, come back to, hand over and watch.**

A **packet** is that thing: the instruction, the plan and notes, the code
it works on, the jobs it has run, and a journal of every step, with a
recipe to rebuild its workspace and an address. Agents, people and
long-running tools take turns in it. A **board** shows every packet you
have, what is running in each, and what is waiting for you. From any
packet you drop into a shell, VS Code or a browser IDE at the right
place. You can hand a packet to the runner and take it back, send
copies to coworkers for their input, or assign it to a colleague, after
which it is theirs.

Five principles carry the design:

1. **The packet is the unit.** Not the repository, the branch, the chat
   or the terminal. Everything about a piece of work is in or reachable
   from its packet.
2. **One owner at a time.** A packet belongs to one person or to the
   runner. Control moves only by an explicit, recorded hand-off or
   assign. Asking others for input sends them copies, which are new
   packets with their own owners.
3. **Your machine, your account.** Each person runs their own daemon,
   `wpkd`, on their own hosts. The board is equal to a shell on that
   account and is guarded like one. A shared hub connects daemons; it
   never runs anyone's work.
4. **Files and git.** A packet is a directory. You can read it, grep it,
   back it up and fix it by hand. Nothing important is only in a
   database.
5. **Meet developers where they are.** The terminal, VS Code and a phone
   browser are all first-class. The board is where you look; the IDE is
   where you work.
6. **Grow without migrating.** One person gets value from `wpk dash`
   alone. A small team links their daemons by agreement. An organization
   stands up a hub. Each step up is configuration, not a migration, and
   nothing at a smaller scale depends on a larger one (§5.1).

## 2. Starting point

Built (466 tests, not committed; details in the design documents named):

| Area | What exists | Where |
|---|---|---|
| Packet format v0.2, executor, atomic steps for `state/` | yes | spec.md |
| Questions, answers, notes, hand-off, next batch | yes | interaction.md, dash-tasks.md |
| Board with actions, live view, process panel, Compose, web shell | yes | dash-tasks.md T1–T4 |
| Runner inside the board process (`wpk dash --run`) | yes | dash-tasks.md §7 |
| Setup at the project root; packet `work/` as git worktrees on `wpk/<project>` | yes | setup.md §10 |
| Tailnet login by Tailscale identity | yes, without TLS | server.md S1 |
| Harness adapters, profiles, stats, context controls | yes | harness.md, context.md |

Not built, and needed by this design: v0.3 ownership states and `take`
(long-running.md L1), git reset and commit of work repos per step
(long-running.md §2), TLS (server.md S1b), a REST API, jobs, persistent
sessions, the IDE integration, export and import, the hub.

## 3. Who it is for

| User | Their job to be done | What the product gives them |
|---|---|---|
| **DV engineer** | triage a failing regression: reproduce, debug, hand to the owner | a packet per failure, created by CI, that reproduces itself and opens at the failing revision (§14 R4) |
| **HW/firmware developer** | move a plan forward over days, with hour-long builds and sims | the runner works through the plan; sims run as jobs with progress on the board; nothing is lost between sessions |
| **Lead or reviewer** | know what five pieces of background work are doing, and review the results | one board, a "Needs you" column, notifications, **Review in VS Code** |
| **Colleague receiving work** | pick up someone else's packet without a briefing | the packet arrives with its plan, journal and recipe; Open materializes it |
| **Bug reporter and maintainer** (open source, or a customer and a vendor) | report a bug so it can be reproduced; reproduce a stranger's bug without a week of back-and-forth | a **report**: a stripped packet with the recipe and the failing command. The maintainer imports it and it reproduces; questions go back to the reporter's board (§11.6) |

Not the target: work with a fast edit-test loop and nothing to carry
between sessions. Claude Code alone serves that better.

## 4. Concepts

The whole vocabulary. Anything not here is an implementation detail.

| Term | Meaning |
|---|---|
| **project** | a named piece of work with a setup (repos, inputs, limits, permissions) and a root packet. Lives in a directory on one host |
| **packet** | a unit of work in a project: `memento.md` (the next instruction), `state/` (plan, notes), `work/` (worktrees of the project's repos), `jobs/`, `journal.jsonl`, `steps/`. Has a WPID and an address |
| **address** | `wpk:<wpid>`, or `https://<hub>/p/<wpid>`. Resolves to wherever the packet is now |
| **owner** | who may change the packet now: **you** (a person) or **the runner**. Follows from the state |
| **step** | one run of the agent on a packet, committed atomically or not at all |
| **hand off / take** | move ownership to the runner / back to you |
| **question** | what the agent asks when it needs you; answered on the board |
| **note** | a message to a packet in any state, read at the agent's next tool call or step |
| **batch** | one instruction's worth of work; a finished packet takes a next batch |
| **job** | a non-agent command started in a packet that outlives whoever started it (a sim, a regression, a build) |
| **session** | a shell that belongs to a packet, reachable from the board, VS Code and SSH |
| **surface** | where you look at or work on a packet: board, shell, VS Code, browser IDE, phone |
| **recipe** | the `[setup]` that rebuilds a packet's workspace: repos at commits, inputs, links, a smoke check |
| **template** | a recipe with parameters, plus an instruction: "create from X" |
| **bundle** | a file holding a packet's core, made by **export** and read by **import** |
| **report** | a stripped packet for someone outside your organization: what is wrong, the recipe, the failing command, chosen files. No history, no transcripts. A bug report is a report |
| **link** | an agreement between two daemons (or a daemon and a hub) to share summaries and accept bundles |
| **assign** | give a packet to another person; afterwards it is theirs, not yours |
| **consult** | send copies of a packet to one or more people and ask for their input; the packet stays yours |
| **copy** | a new packet made from another, with `origin` pointing back; owned by whoever made or received it |
| **reply** | a coworker's input on a consultation: text, answers, and optionally their changes |
| **hub** | a shared service that knows addresses and owners and stores bundles. Runs nothing |

Not user concepts: which host holds a packet and where its steps run
(**placement**, §11.5), leases, `.pending/`, the commit protocol.

## 5. Architecture

```
 laptop / phone                     your host(s)                               shared
┌──────────────┐   tailnet    ┌───────────────────────────────────────┐   ┌───────────────┐
│ browser      │─────HTTPS───►│ wpkd (one per user, per host)         │   │ hub           │
│  board       │              │  board (HTML) + API (JSON, SSE)       │──►│  address index│
│  web shell   │◄──WebSocket──│  runner: steps, jobs, placement       │   │  summaries    │
│  web VS Code │              │  session holders (one per shell)      │   │  bundle store │
├──────────────┤              │  serve-web / openvscode (on demand)   │   │  (S3/R2/file) │
│ VS Code      │──Remote-SSH─►│  notifications                        │   └───────▲───────┘
│  + extension │  (ext host   │                                       │           │
│              │   on host,   │  projects/ → packets/ (files, git)    │   CI: ci/run.sh
└──────────────┘   talks to   └───────────────────────────────────────┘   wpk export --from-ci
                   wpkd over          │ steps: claude -p (harness)
                   a socket)          │ jobs: local, or SLURM
```

- **wpkd** is the only daemon. It is today's `wpk dash --run` plus the
  rest of server.md S2: the board, the runner, the API, sessions, the
  web IDE proxy, and the hub connection. `wpk runner` (no board) and
  `wpk dash` (no runner) remain for headless hosts and for viewing.
- **One wpkd per user per host.** A user with several hosts has several
  daemons; links join them into one board (§7.4).
- **The CLI** stays complete. Every board action is an `actions.py`
  function with a CLI command; the board, the API, the VS Code extension
  and the TUI add no logic of their own (dash-tasks.md rule 1).

### 5.1 Four scales, one protocol

The product has to spread the way developer tools spread: one person
tries it, a few colleagues join, then an organization adopts it, and
then work moves between organizations, the way bug reports and support
cases do today. Each scale must be worth having on its own, and moving
up must not mean starting again.

| Scale | What you run | What you get | What you need |
|---|---|---|---|
| **One user** | `pip install 'work-packet[dash]'`, then `wpk dash` | the board on loopback with the runner in it; New task, Compose, hand-off, questions; sessions; jobs and progress; Open in VS Code; browser notifications; export and import to files | nothing else: no account, no server, no network, no root. Optional: `wpk serve --install-unit` to keep it running, `--tailnet` for the phone |
| **Small team** | the same, plus `wpk link` between members | teammates' packets on your board (what they share); assign directly to a teammate; transcript requests; "Assigned to you" notifications | the daemons can reach each other (a shared tailnet or a LAN); each pair agrees once to link. No server |
| **Organization** | a hub: `wpk hub` (the same package, in hub mode), plus a store | one index and directory; bundles in S3/R2, so sender and recipient need not be online together; CI bundles land on the owner's board; sign-in through the organization's identity; policy on sharing, export and retention; an audit log | one small service and a bucket. Members run `wpk link add <hub>`; nothing else changes |
| **Between organizations** (the internet) | nothing new to start: a report file attached to an issue; or hubs linked to each other; or a project's public intake | file a bug as a report that reproduces itself; send a case to a vendor; get the maintainer's questions back on your own board; follow the state of what you reported | a report works with no hub at all (a file on an issue). Hub-to-hub links and public intake need a hub reachable over HTTPS (§11.6) |

Rules that keep the scales compatible:

1. **Configuration, not migration.** The packet format, the project
   layout and the journal are the same at every scale. Linking up or
   joining a hub adds files under `$WPK_HOME/links/` and nothing else.
2. **One protocol.** Your own hosts, a teammate's daemon and the hub
   all speak the same **peer API** (§7.4). The hub is a peer that holds
   no packets and that everyone links to.
3. **Smaller scales keep working.** With the hub down, links and local
   work carry on; with a teammate's daemon down, your board still works
   and their cards show how old they are.
4. **No dependency upward.** Export to a file works without a link;
   assign works over a link without a hub; CI can write a bundle to an
   artifact without either.
5. **Linking is mutual and explicit.** Nobody's packets appear on
   another board until both sides have agreed, and each side decides
   what it shares (§13 D5).
6. **The further it goes, the less it carries.** A turn keeps
   everything; an assign within a team carries the core; a report to
   another organization carries only what reproduces the problem. The
   export profile follows the scale (§11.1).
7. **What comes from outside is data.** A packet from another
   organization never runs, and its text never reaches an agent as an
   instruction, until its new owner says so (§12).

## 6. The packet

Format v0.3. The changes from spec.md v0.2, in one place:

```
packets/<WPID>/
  status.md          state, held_for, owner_user (new), model, attempts, reason
  memento.md         the next instruction; ask: for questions
  state/             plan, outline, notes; versioned per step
  work/<repo>/       git worktree on wpk/<project>; reset or committed per step (new: enforced)
  jobs/<id>/         NEW: job.json, log, progress.jsonl, graph.json, exit (§9)
  mailbox/           notes waiting for a step
  identity/          links to outside resources, by name
  journal.jsonl      append-only record
  steps/NNNN/        summary.md, result.md, work.diff, transcript.jsonl, meta.json
  .wpk/              NEW: generated files for surfaces (the VS Code workspace); not part of the format
```

**States** (long-running.md §1, now required):

| State | Owner | Board column |
|---|---|---|
| `HELD` with `held_for`: `setup`, `question`, `failed`, `limit`, `taken` | you | Setup, **Needs you**, Held |
| `COMPLETED` | you | Done (takes a next batch) |
| `RUNNABLE`, `SLEEPING` | runner | Ready, Running, Sleeping |
| `ASSIGNED` | someone else (read-only here, with the address) | Assigned away |

A consultation in progress is not a state: the packet stays in its
column, with "consulting 3 · 2 replied" on its card. Copies you were
sent sit under **Asked for your input** until you open them.

`SLEEPING` gains `resume: wait job:<id>` (§9.3). `owner_user` is the
login of the person who owns the packet when it is yours; it changes
only on import of an assigned bundle.

**Data tiers** decide what travels (§11):

| Tier | Contents | Exported | Removed by `wpk clean` |
|---|---|---|---|
| core | status, memento, `state/`, journal, step summaries, results and diffs, `project.toml`, `prompt.md`, notes | always | never |
| record | step transcripts and logs, job logs | by choice (§13 D1) | no |
| derived | work trees, builds, sim output, waves, coverage | named files by choice; otherwise a pointer | yes |

**Work repos are atomic per step.** Built as long-running.md §2
describes, adapted to worktrees: record each worktree's `HEAD` before
the step; on failure `git reset --hard` and `git clean -fd` (ignored
files kept); on success one commit per changed repo with `Wpk-Packet`
and `Wpk-Step` trailers. A git command that meets an `index.lock` waits
and retries once (an editor's git extension may hold it). This must ship
before the IDE does (§14 R1), because the IDE makes a half-finished step
visible.

## 7. wpkd

### 7.1 The board

Today's board, with these additions:

- **Jobs** on every card and packet page ("regress 61%, 2 running").
- **Sessions**: the packet's open shells, idle ones dimmed, with Attach
  and Close.
- **Open in VS Code**, **Open in browser**, **Review in VS Code** (§10).
- **Assign** and an **Assigned to you** column (§11).
- **New from template** (§7.5).

### 7.2 The REST API

The scales in §5.1 only stay "one protocol" if there is one protocol.
So everything a daemon or a hub does is a **resource in one versioned
REST API**, `/api/v1/`, and every client uses it: the VS Code
extension, the TUI, scripts, CI, your other hosts, teammates' daemons,
hubs, and the CLI when it drives a daemon on another host. What differs
between those callers is not the API but the **scope** they hold.

**Design rules**

1. **Resources are the packet's own things.** Projects, packets, steps,
   jobs, sessions, notes, questions, bundles, links. The files on disk
   stay the truth; the API reads them and changes them through
   `actions.py`, as the CLI does.
2. **One action, three faces.** Every action is an `actions.py`
   function, a CLI command and an endpoint. A test enumerates the
   actions and fails if one lacks either face.
3. **Ownership changes are explicit resources,** not side effects:
   hand-off and take are a `PUT` of the packet's owner, recorded in the
   journal with the caller's identity.
4. **Safe to retry.** Every `POST` takes an `Idempotency-Key`; links
   retry deliveries from an outbox, so a repeated delivery must be a
   no-op.
5. **Safe to race.** A packet carries an `ETag` (its journal's last
   sequence number). Changes take `If-Match`, so an edit made against a
   stale view (Compose open for an hour while the runner moved on) is
   refused with `412`, not applied.
6. **Stable.** Additive changes only within `v1`; an OpenAPI document at
   `/api/v1/openapi.json`, generated from the code; errors as RFC 9457
   `application/problem+json`; cursor pagination.

**Resources**

| Resource | Methods | Notes |
|---|---|---|
| `/projects`, `/projects/{name}` | `GET`, `POST` (from a template), `PATCH` (settings) | `POST` is New task; `PATCH` is `wpk set`/`allow`/`deny` |
| `/packets` | `GET` | the board: filter by `state`, `owner`, `project`, `waiting`; across self links when `?all` |
| `/packets/{wpid}` | `GET` | status, outline, open questions, heads, jobs, sessions, address |
| `/packets/{wpid}/owner` | `PUT {"to": "runner", "note"}` / `{"to": "me"}` | hand off / take (take during a step returns `202` and lands at its end) |
| `/packets/{wpid}/instruction` | `GET`, `PUT` | the next batch (dash-tasks.md §6); drafts at `/instruction/draft` |
| `/packets/{wpid}/answers` | `POST {id: text}`, `?recommended` | answer questions, with grants |
| `/packets/{wpid}/notes` | `GET`, `POST` | notes at any time |
| `/packets/{wpid}/steps`, `/steps/{n}` | `GET` | summary, diff, cost; `/steps/{n}/transcript` is record tier (scope below) |
| `/packets/{wpid}/jobs`, `/jobs/{id}` | `GET`, `POST`, `DELETE` | start, read, stop; `/jobs/{id}/progress`, `/jobs/{id}/log` |
| `/packets/{wpid}/sessions`, `/sessions/{id}` | `GET`, `POST`, `DELETE`; WebSocket to attach | the shell |
| `/packets/{wpid}/bundle?profile=team` | `GET` | export (§11.1) |
| `/packets/{wpid}/assignment` | `PUT {"to": user}` | assign (§11.7) |
| `/packets/{wpid}/consults`, `/consults/{id}` | `GET`, `POST {"to": [...], "message", "questions", "due"}`, `DELETE` (close) | consult (§11.7) |
| `/packets/{wpid}/replies` | `GET`; `POST` on a copy sends a reply to its origin | replies; `/replies/{id}/forward` and `/replies/{id}/apply` act on one |
| `/inbox`, `/inbox/{id}` | `GET`, `POST` (deliver), `POST /inbox/{id}/accept`, `DELETE` (decline) | what others sent you: assignments, consultations, replies |
| `/requests`, `/requests/{id}` | `GET`, `POST`, `POST /requests/{id}/approve` | asking for record-tier files |
| `/reports` | `POST` | public intake (§11.6) |
| `/where/{wpid}` | `GET` | "do you have this packet?", to resolve an address without a hub |
| `/links`, `/links/{name}` | `GET`, `POST`, `DELETE` | §7.4 |
| `/events` | `GET` (Server-Sent Events, `?since=<cursor>`) | every change above, filtered to the caller's scope |
| `/tokens` | `GET`, `POST`, `DELETE` | personal tokens for scripts and CI |

`GET /p/{wpid}` (HTML) redirects to the packet's page, so the WPID alone
is enough in a link.

**Scopes.** Each endpoint declares which scopes may call it; the guard
checks it before any handler runs.

| Scope | Who holds it | May |
|---|---|---|
| `owner` | you: the board's login, `wpkd.sock` (0600), a self link, a personal token with full scope | everything |
| `read` | a personal token for dashboards and scripts | every `GET` except record-tier files |
| `ci` | a token for a CI job | `POST /inbox` with bundles made by `--from-ci`; nothing else |
| `peer` | a teammate's daemon or a hub, over a link | `GET /packets` and `/events` for what you share with them (§13 D5); `POST /inbox`; `POST /requests`; `GET /where` |
| `public` | anyone, at a hub's intake | `POST /reports`, with limits (§12) |

Nothing in `peer`, `ci` or `public` starts a step, opens a session,
changes a packet or runs a command. That is the line between "linked
to you" and "logged in as you" (§12).

**Transport and identity.** Browsers use the board's guard (Tailscale
identity, Host and Origin checks, a CSRF token on changes). Local
clients use `wpkd.sock`. Other daemons and hubs use HTTPS with the
link's key (§13 D8) or the hub-issued key. Scripts and CI use bearer
tokens from `/tokens`, each with one scope and an expiry.

**The CLI as a client.** `wpk --at <url|link>` (or `WPK_AT`) runs a
command against another daemon through the API: `wpk --at buildsrv ps`,
`wpk --at buildsrv handoff dvs-enh`. With no `--at` it works on the
local files directly, as now, so the one-user scale needs no daemon.

### 7.3 Notifications

From the event stream, for: a packet needs you (question, failed,
limit), a batch completed, a job ended. Channels: the board (a badge and
the browser's Notification API), the VS Code extension, and one push
channel configured in `config.toml` (an ntfy topic or a webhook), so
the phone hears about it. Each channel has a per-event-type switch.
Quiet hours follow the project's time zone.

### 7.4 Links: your hosts and your teammates

A **link** is an agreement between two daemons to show each other's
packets and accept each other's bundles. The same mechanism joins your
own hosts into one board, joins a small team, and connects a daemon to
a hub.

**Making a link.** `wpk link add <url>` on one side, confirmed on the
other (a prompt on its board, or `wpk link accept`). On a shared
tailnet, each side knows the other's login from Tailscale `whois`, so
the confirmation is all it takes. Off a tailnet, the first command
prints a one-time code that the other side enters; the pair then
exchange keys (§13 D8). Each link is a file,
`$WPK_HOME/links/<name>.toml`: URL, the other side's identity, keys,
and what you share with it. `wpk link ls`, `wpk link rm`.

**Two kinds of link**, decided by identity:

| Link | When | What it allows |
|---|---|---|
| **self** | both daemons belong to the same login (your laptop and your build server) | one board: all packets, and actions forwarded to the daemon that holds the packet |
| **peer** | different logins (a teammate, or the hub) | summaries of what the other side shares; delivering a bundle to its inbox; requesting a record-tier file. Never an action on the other side's packets |

**What a link may do** is the `peer` scope of the REST API (§7.2): read
the summaries you share, follow their events, deliver a bundle to your
inbox, request a record-tier file, and ask where a packet is. A self
link holds `owner`. No peer call starts a step, opens a session, edits a
packet or runs a command. Linking a teammate never gives them what
logging into your board gives (§12).

**Assigning and consulting over a link.** `wpk assign <target>
<teammate>` exports and posts the bundle to their inbox; their board
shows it under **Assigned to you**; Accept imports it on their daemon,
and your copy becomes `ASSIGNED`, pointing at theirs. `wpk consult`
posts copies the same way, and replies come back to your inbox (§11.7).
If a daemon is unreachable, the delivery waits in the outbox and is
retried; the card says so.

**Size.** Links form a full mesh: fine for a handful of people, tedious
past about ten. That is the point at which a hub pays for itself, not
before.

### 7.5 Templates: create from X

A template is a directory under `$WPK_HOME/templates/<name>/`:

```
template.toml     name, description, parameters (name, type, prompt, default)
setup.toml        a [setup] fragment with {{param}} placeholders: repos and refs, inputs, links, smoke
instruct.md       the first instruction, with placeholders
project.toml      limits, profile, permissions preset
```

**New from template** asks for the parameters, writes the project, runs
the recipe and opens Compose with the checks already green. Built-in
templates:

| Template | Parameters | Recipe | Instruction |
|---|---|---|---|
| `from-repo` | repo URL, ref | clone at ref | yours |
| `from-issue` | issue URL | clone the issue's repo at its default branch; the issue text as an input | "Read the issue; propose a plan; ask before implementing" |
| `from-ci-failure` | a bundle (§11) | the bundle's recipe; smoke = the failing command | "Reproduce, then find the root cause; don't fix" |
| `plan` | repo, plan document | clone; the plan as an input | "Work through the plan" (the long-running.md walkthrough) |

### 7.6 Resources and placement

- **Pools.** `[resources]` in `config.toml` names countable resources:
  `agent = 3`, `xcelium = 4`, `cpu = 32`. A step uses one `agent`; a job
  declares what it `needs`. The runner starts work only when its needs
  are free; otherwise it waits (the card says for what).
- **Backends.** Steps and jobs run `local` by default. A `slurm` backend
  submits with `sbatch` and polls with `sacct`; pools can map to SLURM
  licences (`-L`) and GRES. Heavy jobs belong there, as
  `bigger_picture.md` says.
- **Placement** is internal. Which host holds a packet is the runner's
  and the hub's business (§11.5).

## 8. Sessions

A **session** is a shell that belongs to a packet. It starts where
dash-tasks.md §5.4 says (the project root before the seed, the packet
after), with the wizard's rc file and `WPK_*` environment.

**Backends** (`[sessions] backend`), one interface: start, attach, list,
idle, close.

| Backend | Holder | Notes |
|---|---|---|
| `wpk` (default) | `wpk _hold`: one small process per session, in the style of `dtach`. Owns the pty, keeps a 256 KB replay buffer, listens on `$WPK_HOME/sessions/<id>.sock` in a 0700 directory. Not a child of wpkd | no dependency; survives a wpkd restart |
| `tmux` | a tmux session `wpk-<project>-<short wpid>` | for tmux users; their `tmux ls` shows packet sessions |

**Clients:** the board's xterm.js (through wpkd, over the WebSocket
built in dash-tasks.md T4), VS Code's "packet shell" terminal profile
(`wpk attach <session>`), and SSH (`wpk attach <target>`). One session,
every surface.

**Idle and active.** The holder compares the pty's foreground process
group (`tcgetpgrp`) with the shell's PID and records the time of the
last output; tmux gives `#{pane_current_command}` and
`#{window_activity}`. Foreground is the shell and no output for
`idle_minutes` (30): **idle**, dimmed on the board. Idle for
`idle_hours` (12): reaped. A session running a command is **active** and
never reaped. **Restore** opens a new session in the same place with the
same history; process state is not kept. Work that must survive belongs
in a job.

**Ownership.** You can open a session only on a packet you own. Hand-off
closes the packet's sessions (`SIGHUP`, then `SIGKILL` after 5 s), as
now.

## 9. Jobs

Priority (2026-10-27): jobs a person starts by hand come first, not only
those an agent starts from a step. They are the way in for engineers
who keep many long runs going in terminals; `docs/positioning/messaging.md`
§3a and §5.3 list what that adds here (a prefix for any terminal, a
notice when a job ends, finished jobs under "Needs you", the run in the
packet's history).

### 9.1 What a job is

A command started in a packet that outlives whoever started it: you, in
a session, or the agent, in a step.

```
wpk job start [<target>] [--name N] [--needs xcelium] [--backend slurm] [--adapter dfm] -- <command…>
wpk job ls [<target>]     wpk job log <id> [-f]     wpk job stop <id>
```

```
jobs/<id>/
  job.json        command, cwd, who, started, host, backend, pid or SLURM id, needs, adapter
  log             stdout and stderr
  progress.jsonl  progress events (§9.2)
  graph.json      optional task graph: {"nodes": [{id, label, logfile?}], "edges": [[from, to]]}
  exit            {"code", "t"} when it ends
```

`jobs/` is outside the committed files, like `mailbox/`: a job may write
while a step runs. A small supervisor (`wpk job _run`) starts the
command in its own session and writes `exit`. A job belongs to the
packet, not to an owner: hand-off and take leave it running; `wpk job
stop` ends it. Its working directory is in the packet, so its output is
in the packet's derived tier.

### 9.2 Progress

Any tool can report progress by appending JSON lines to the file named
by `$WPK_PROGRESS`. Every key is optional:

```json
{"t": "2026-10-25T18:02:11Z", "phase": "sim", "done": 41, "total": 67, "msg": "uart_rx_overrun seed 42", "node": "sim.uart_rx", "node_state": "running"}
```

`node_state` is one of `pending`, `running`, `done`, `skipped`,
`failed`. The board shows the latest `msg`, a bar when `total` is known,
and the graph coloured by `node_state` when `graph.json` exists.

Tools that do not write progress get an **adapter** in wpk
(`work_packet/adapters/`), which reads what the tool already writes and
produces the same lines. Adapters are chosen by `--adapter` or by the
command name.

| Adapter | Reads |
|---|---|
| `dfm` | dv-flow-mgr, unchanged (§9.4) |
| `pytest` | `-rA` result lines, or `--junitxml` at the end |
| `ninja`, `make` | `[n/m]` lines (ninja); target lines (make, no total) |
| `slurm` | `sacct` state for the job's array |

### 9.3 Jobs from a step

The agent starts a job with `wpk job start … -- <cmd>` and ends its turn
with `resume: wait job:<id>`. The packet sleeps; the runner wakes it
when `exit` appears or at the job's timeout. The next prompt shows the
exit code, the log tail and the last progress line. `bghook.py`'s
message, which today only refuses a background command, points the
agent at `wpk job start`. `protocol.md` gains a short section.

Steps may start jobs only if `Bash(wpk job start *)` is in the
project's allowed tools; the step's `needs` and the job's `needs` both
count against the pools.

### 9.4 The dv-flow-mgr adapter

wpk understands dv-flow-mgr; dv-flow-mgr needs no change. Checked
against `~/projects/dv-flow/dv-flow-mgr` at bfb54a7 (details in
workflow-review.md §6.2.1):

1. **Graph:** `dfm graph <task> [-D …] --json` before the run gives DOT
   between markers; the adapter converts it to `graph.json`.
2. **Live state:** the adapter adds `-u log -v` when the command has no
   `-u`, and maps `>> [n] Task X` to `running` and `<< [n] Task X (…)`
   to `done`, `skipped` (up-to-date, cache, base) or `failed`.
3. **Results:** each task's `exec_data.json` newer than the job's start
   confirms the result and gives the node's `logfile`, so a node on the
   board opens its log.
4. **Progress:** done ÷ graph nodes, shown as approximate, since
   runtime expansion adds tasks the static graph lacks.
5. **Timings:** `rundir/log/<pkg>.trace.json` at the end, if written.

The log patterns are pinned by a test against a recorded run, so a
dv-flow-mgr release that changes them fails a wpk test, not a user's
board (§13 D4).

## 10. The IDE

ide.md stands, with the changes from workflow-review.md §4.1–§4.4 and
§6.4. In summary:

### 10.1 The workspace file

`<packet>/.wpk/packet.code-workspace`, generated by wpk:

- **Folders** follow the built layout: before the seed, the project
  root's `work/*`, `state/` and `prompt.md`; after it, the packet's
  worktrees, labelled `dv-solve (packet: wpk/dvs-enh)`, plus `state/`
  and the packet (with `files.exclude` for `work/`, `state/`, `steps/`,
  `.pending/`, so nothing shows twice). Your own clone is never in a
  packet's workspace.
- **Settings, always:** `files.watcherExclude` and `search.exclude` for
  `**/packages/**`, `**/rundir/**`, `**/build*/**`; the terminal
  profile "packet shell" (`wpk attach`) as the default.
- **Settings while the runner owns the packet:**
  `files.readonlyInclude: {"**": true}`, `git.autorefresh: false`,
  `git.autofetch: false`, `editor.formatOnSave: false`. A guard against
  mistakes, not a boundary; the board says so.
- **Merge, not overwrite.** wpk updates only the keys it owns, and only
  when they change (on hand-off, take and seed, not on every step).

### 10.2 Desktop VS Code

**Open in VS Code** is a `vscode://vscode-remote/ssh-remote+<host>/…`
link to the workspace file, where `<host>` is the host that holds the
packet (from its address, §11.5). SSH is however it already works (the
tailnet, keys). Not `code tunnel`.

### 10.3 The extension

A VS Code extension, published as a workspace extension so it runs in
the remote extension host, next to wpkd, and talks to it over
`wpkd.sock` (§7.2):

- a status-bar item: this packet's state and owner, and the Needs-you
  count across every packet;
- a **Packets** view: the board as a tree, from `/api/v1/packets`;
- commands: hand off, take, answer, note, start job, review;
- notifications from `/api/v1/events`;
- **Review**: the multi-diff of the packet's commits since the last
  hand-off (`base..HEAD` from the journal's heads); **Open at step N**:
  a detached worktree at that step's commits.

The tasks in ide.md §2 remain for anyone without the extension.

### 10.4 Browser IDE

wpkd proxies a VS Code server under `/ide/`, behind the board's guard,
on a unix socket (ide.md §4). Two backends, one proxy:

| `[ide] web` | Server | For |
|---|---|---|
| `serve-web` | Microsoft's `code serve-web` | one user with internet access |
| `openvscode` | openvscode-server (Open VSX extensions) | air-gapped sites; anything beyond personal use, given the VS Code Server licence |

Needs TLS (server.md S1b): webviews use service workers, which browsers
allow only on HTTPS or localhost. The first spike checks offline
behaviour.

### 10.5 Ownership in the IDE

As ide.md §5: on a packet you own, **Open**; on the runner's, **Take
over & open** (take now if idle, at the end of the step if running,
read-only until then) and **Open read-only**. **Continue the
conversation** opens a session running `claude --resume <id>
--fork-session` (plan mode while the runner owns the packet), and offers
**Send as a note** when you leave it, so what you learned reaches the
packet.

## 11. Export, import and the hub

### 11.1 Bundles

`wpk export <target> [-o file | --to <store>] [--with transcripts] [--with <glob>…]`
writes a bundle: a tar of the core tier, chosen record and derived
files, and `manifest.json`:

```json
{"wpk": "0.3", "wpid": "…", "project": "dvs-enh", "source": {"user": "…", "host": "…"},
 "repos": {"dv-solve": {"url": "…", "branch": "wpk/dvs-enh", "commit": "…", "unpushed": "repos/dv-solve.bundle"}},
 "identity": ["xezim_research"], "transcripts": {"0007": {"sha256": "…", "bytes": 1840022}},
 "derived": {"waves/uart.fst": "kept at source"}}
```

- Unpushed commits travel as a `git bundle`; pushed ones as URL and
  commit.
- `identity/` links travel as names, to be rebound on import.
- Export lists every path outside the packet that the included files
  refer to, before writing, so you see what you are about to share.
- `wpk clean <target>` removes the derived tier and keeps the recipe.
  Export cleans nothing; assign asks whether to clean the local copy.

**Export profiles** (`--as`), chosen by where the bundle is going:

| Profile | Used by | Carries | Leaves out |
|---|---|---|---|
| `full` | placement between your own hosts | everything, including transcripts and named derived files | nothing |
| `team` (default) | assign over a link or a hub | the core tier (§6) | record and derived tiers unless asked for (§13 D1) |
| `report` | another organization: a bug report, a support case | a description (from a template: expected, observed, environment), the recipe, the failing command as the smoke check, tool versions, the log tail, files you name | the journal, step history, `state/` (unless named), transcripts, identity links, author paths and host names |

A `report` export refuses to go out while the recipe points at a
repository the recipient cannot reach. It offers the choices: the
public upstream at the nearest commit, the needed commits as a git
bundle, or a minimal test case you name. It then shows the full list of
what will leave, file by file.

`wpk import <bundle | address>` creates the project and packet, then
**materializes**: clone at the recorded commits, apply the git bundles,
create the worktrees, ask for identity links it cannot rebind, run the
smoke check. The packet arrives `HELD`/`setup` until the checks pass.

### 11.2 From CI

`wpk export --from-ci --test <name> [--seed N] --cmd '<command>' [--with <glob>…]`
builds a bundle with no packet behind it: repo URL and commit from the
forge's environment (`GITHUB_SERVER_URL`, `GITHUB_REPOSITORY`,
`GITHUB_SHA`, `GITHUB_RUN_ID`; Forgejo sets the same names), the
test, seed, command and log tail, and the recipe's smoke check set to
the failing command. It is called from the repo's CI script (`ci/run.sh`
in featherweight-ip), so the Forgejo and GitHub workflows of each pair
both get it, and their existing artifact upload carries it. Importing it
with the `from-ci-failure` template is "step into the bug".

First repos: featherweight-ip, then fvutils dv-solve, pyvsc and
pyhdl-if.

### 11.3 Stores

A store has `put`, `get`, `list`. Schemes: `file://` (a directory, or a
shared filesystem), `s3://` and `r2://` (one S3 client), and
`gh-artifact://` for reading CI artifacts with a forge token. The hub
uses one of them.

### 11.4 The hub

The organization's scale (§5.1). A hub is a peer (§7.4) that holds no
packets and that everyone links to. It knows things; it does not run
them. It is `wpk hub`: the same package, with no runner and no
sessions.

Joining is `wpk link add https://hub.example.com`, the same command as
linking a teammate. What the hub adds over a mesh of links:

- **Index and directory:** every published packet's address, owner,
  project, title, state, waiting since and holding daemon; and the
  organization's people and teams, so `wpk assign` takes a name, not a
  URL. Addresses resolve through the index.
- **Store and relay:** bundles go to the hub's store (S3, R2, or a
  shared filesystem), so the recipient need not be online when you
  assign. Summaries and events are relayed, so each daemon keeps one
  connection, outbound (a WebSocket, falling back to HTTPS polling),
  which works behind NAT.
- **CI intake:** CI uploads bundles to the hub; a mapping (CODEOWNERS,
  or a table) puts the card on the owner's board.
- **Identity:** Tailscale `whois` on a shared tailnet, or the
  organization's sign-in (OIDC); each daemon's link is a key issued at
  join time.
- **Policy:** sharing defaults per team and project (§13 D5); what may
  be exported (for example, transcripts never leave); bundle retention.
- **Audit:** a log of assignments, requests and approvals.
- **Boards:** a read-only board per team, with links to the owning
  daemons for anything more. No shells, no files, no transcripts.

Moving from links to a hub changes nothing in any packet. Direct links
can stay (useful while the hub is down) or be removed.

### 11.5 Placement

Not a user operation. When the runner or the hub moves a packet between
a user's hosts (to reach a licence pool, a SLURM partition, or off a
retiring machine), it exports, imports on the target wpkd, retires the
source (a tombstone pointing to the address) and updates the index. The
journal records `placed` with both hosts. Links resolve through the
address, so they keep working. The first release does no automatic
placement; `wpk _place` exists for an administrator.

### 11.6 Across organizations: reports and federation

The internet scale (§5.1). The unit is the **report**: a stripped
packet (§11.1, `--as report`). A bug report filed this way is not a
description of how to reproduce a problem; it is the reproduction.

**Three ways to send one**, from no infrastructure to the most:

| Way | Needs | How |
|---|---|---|
| **A file** | nothing | `wpk report <target> -o bug.wpk`, attached to an issue, a support case or an email. The maintainer runs `wpk import bug.wpk`. Works at the one-user scale, on both sides |
| **Public intake** | a hub on the receiving side, reachable over HTTPS | a project names its intake in its repository (`.wpk/intake.toml`: URL, the templates it accepts, size limits). `wpk report <target> --to <repo URL>` finds it and delivers. The intake can also open a forge issue that links to the report |
| **Hub to hub** | a hub on each side | two organizations' hubs link with the same `wpk link add`, as a peer link (§7.4) with policy on both sides: which projects, which people, which profiles. For vendor and customer, or partner organizations |

**The round trip.** A report keeps its address (`wpk:<wpid>@<origin>`)
on both sides. The reporter's board shows its state on the receiving
side (received, reproduced, did not reproduce, fixed in `<commit>`),
as far as the receiver's policy allows. A question the maintainer asks
about a report comes back to the reporter's **Needs you**, and the
answer goes back as a note. That is the back-and-forth of an issue
thread, but attached to something that runs.

**Identity on the internet.** Reports are signed with a key held by
the sender's daemon or hub (§13 D11); the receiver sees who sent it as
"verified by <hub>" or as the forge account used at the intake.
Unsigned reports (a file on an issue) are accepted and marked as such.

**Receiving is safe by default** (§12): an imported report arrives
`HELD`/`setup`; its recipe does not run until you choose to run it,
inside the receiving project's sandbox if one is configured (§13 D10);
its description is shown as the reporter's text and is never the
packet's instruction. You write the instruction ("reproduce, then find
the cause") and hand it off.

### 11.7 Coworkers: assign and consult

Two different things happen between people, and both must work over a
link, through a hub, and across organizations:

| | **Hand off** | **Assign** | **Consult** |
|---|---|---|---|
| To | the runner | one person | one or more people |
| What travels | nothing; ownership changes | the packet (a `team` bundle) | **copies** (a `team` bundle each, or `report` across organizations) |
| Yours afterwards? | yes; it comes back when it stops | **no**: it is theirs | **yes**: you keep working, or wait |
| What comes back | the packet, with the reason | nothing, unless they assign it back | **replies**: their input, and optionally their changes |

**Assign: give it away.** `wpk assign <target> <person> [-m NOTE]`
(§7.4, §11.4). After the recipient accepts, the packet is theirs and
not yours: your copy becomes `ASSIGNED`, a read-only tombstone with
the new address, and leaves your board except under **Assigned away**
(`--forget` removes the local files once they have accepted). Before it
goes:

- the packet must be yours: if the runner owns it, assign takes it
  first, at the end of the running step;
- running jobs block it (`--stop-jobs` stops them), since a job belongs
  to the packet and would be left with no owner;
- open sessions are closed, as on a hand-off;
- your uncommitted work-repo changes refuse it, as a hand-off does.

The journal keeps the chain of owners; the assignee can assign it back,
which is a new assign, not an undo.

**Consult: ask for input on copies.** `wpk consult <target> <person>…
-m "Is the RX FIFO fix right?" [--questions FILE] [--due 2d] [--wait]`

1. A `team` bundle of the packet goes to each person's inbox, marked as
   a consultation, with your message and optional structured questions
   (the same format as the agent's `ask:`, interaction.md §2).
2. Their board shows it under **Asked for your input**. Open imports a
   **copy**: a new packet with its own WPID and `origin` set to yours,
   owned by them. They can read it, open it in VS Code, run its smoke
   check, even hand the copy to their own runner. Nothing they do
   touches your packet.
3. `wpk reply <copy> -m TEXT [--answers …] [--with-changes]` sends a
   **reply** back: their text, answers to your questions, and, with
   `--with-changes`, their commits on the copy as a git bundle, like a
   pull request.
4. Replies land in your packet's inbox, each signed by its author. The
   consult card shows "2 of 3 replied". You read them on the board or in
   VS Code; **Forward to the agent** puts a reply into the packet's
   mailbox as a note attributed to its author (§13 D13); **Apply
   changes** brings a reply's commits into your work repos as a branch,
   for you to merge. Both need the packet to be yours.
5. `wpk consult close <id>` ends it; copies on the other side are marked
   closed, and their owners delete them when they like.

Your packet's ownership never changes during a consultation. By default
it carries on as before (with the runner, or with you). `--wait` puts it
to sleep until the replies are in or the due time passes, with
`resume: wait consult:<id>`, like a job (§9.3). Later, an agent could
consult people itself, as a question addressed to named coworkers
instead of to you; not in the first version.

**Format.** `status.md` gains `origin` (the address a copy was made
from); journal records `assign`, `consult` (id, recipients, message,
questions, due), `reply` (consult id, author, answers, the commits'
heads) and `forwarded`. A copy is an ordinary packet: one owner at a
time still holds, because a copy is a new packet.

## 12. Security

- **The board is a shell** (server.md §1), so wpkd listens off loopback
  only with identity checks on, records the authenticated user in every
  action, and refuses foreign Hosts and Origins. TLS is required for the
  browser IDE and recommended always.
- **Single-user daemons.** No wpkd runs another person's work. Assigned
  packets are imported and then run under the recipient's account, with
  the recipient's limits and permissions; the bundle's
  `project.toml` permissions are shown for approval at import, never
  applied silently.
- **Links are not logins.** The peer API (§7.4) reads summaries, delivers
  bundles to an inbox and files requests; nothing in it starts a step,
  opens a shell or changes a packet. Only a self link (the same login on
  both sides) forwards actions. Accepting a bundle or approving a request
  is always the owner's explicit act.
- **The hub holds summaries and bundles, never credentials or shells.**
  A hub breach exposes titles, states and whatever bundles were uploaded.
  It is a peer like any other, so it gets no more than a teammate would.
- **What leaves the machine** is what export shows you first: the core
  tier always, record and derived only by choice. Transcripts default
  out (§13 D1). Scrubbing paths is for portability; it is not a privacy
  control, and the export summary says so.
- **Agent permissions** stay per project and visible on every card;
  no push by default; jobs started by a step need an explicit
  allowed-tools entry.
- **Sessions and jobs** run as the daemon's user; their sockets live in
  0700 directories.
- **Packets from outside are untrusted.** A bundle from another
  organization (or any unsigned bundle) is imported as data: nothing
  runs, no permissions from its `project.toml` apply, and its text
  (description, notes, memento) is quoted to an agent only as the
  reporter's words, under the receiver's own instruction, never as the
  instruction. This is the defence against prompt injection by bug
  report. Running its recipe is an explicit act, in a sandbox where one
  is configured.
- **Reports are minimal by construction.** The `report` profile leaves
  history, transcripts, identity and paths out, and shows every file
  before it leaves. Policy on a hub can forbid wider profiles across an
  organization's boundary.
- **Public intake is an open door.** It takes reports from anyone, so it
  has size limits, rate limits per sender, and puts what it receives in
  a triage column, not on anyone's board directly.

## 13. Open decisions

Each has the default this design assumes.

| # | Decision | Default assumed | Options |
|---|---|---|---|
| D1 | Transcripts in a bundle | **out**; the manifest lists them by hash; `--with transcripts` includes them, path-scrubbed. Request-and-approve comes with links (R5) | (a) that; (b) out with no request path ever; (c) in by default |
| D2 | Verb for person to person | **assign** | `transfer` |
| D3 | First repo and test for "step into the bug" | **fw-uart16550**, a seeded sim test | another fw repo |
| D4 | Matching dv-flow-mgr's console text | **accept**, pinned by a test on a recorded run | wait for an events file upstream |
| D5 | What the hub shows other users | **state, title, owner, waiting since**; questions and summaries only to people the owner names in a project's `[share]` | everything, or nothing until assigned |
| D6 | Default session backend | **wpk holder** | tmux |
| D7 | Notification push channel | **ntfy** topic | webhook only; email |
| D8 | Identity for links off a tailnet | **one-time pairing code, then exchanged keys** (requests signed per link) | require a shared tailnet; reuse SSH keys; mutual TLS |
| D10 | Running an imported report's recipe | **only on request, in a container if the project names one** (`[setup] sandbox = "podman:<image>"`); without a sandbox the board warns before it runs | always require a sandbox; never run, reproduce by hand |
| D12 | Name for "send copies and ask for input" | **consult** | request review; share a copy |
| D13 | Do coworkers' replies reach the agent directly? | **no**: they wait for you, and **Forward to the agent** sends one on as a note attributed to its author | yes, as notes; per consultation (`--to-agent`) |
| D11 | Signing reports | **a key per daemon or hub** (minisign- or SSH-signature-style), with the hub vouching for its members | sigstore keyless with a forge identity; no signing |
| D9 | `wpk dash` runs the runner by default | **yes**: only packets you have handed off ever run; `--no-run` to view only, and a second `wpk dash` on the same home views only (the runner lock) | keep `--run` opt-in |

## 14. Releases

Each release is usable on its own and ends with a live check on real
work. Names `R1`–`R8`, to avoid the milestone letters already used in
other documents. Existing milestones are named where they are part of a
release.

| Scale (§5.1) | Releases |
|---|---|
| One user | R1–R4 |
| Small team | R5 |
| Organization | R6 |
| Between organizations | R4 (reports as files), R7 |
| Any scale | R8 |

### R1: Trustworthy ownership (foundation)

- `wpk dash` is the whole entry point for one user: the runner on by
  default (§13 D9), an empty board that starts with **New task**, and
  `wpk serve --install-unit` for when you want it always on.
- v0.3 states and `take` (long-running.md L1).
- Work repos atomic per step (long-running.md §2, on worktrees);
  `index.lock` retry.
- `docs/concepts.md` from §4; ide.md §2 rewritten on the built layout.
- **Exit:** a dvs-enh or fw-uart16550 batch where a step fails midway
  and the worktree is back at `base`; take during a step lands `HELD`/
  `taken` at its end.

### R2: Work from the IDE, sessions that last

- Persistent sessions, wpk holder and tmux backends (§8).
- Workspace file and **Open in VS Code** (§10.1–10.2, ide.md I1).
- Ownership-aware buttons; read-only while the runner owns it (ide.md
  I2).
- **Exit:** a shell started on the board continues in VS Code's
  terminal and survives a wpkd restart; a day of real use on one
  project with the IDE.

### R3: Jobs and the API

- Jobs, the progress protocol, `resume: wait job:` (§9.1–9.3); local
  backend; pools.
- Adapters: `dfm`, `pytest`, `ninja`.
- The REST API (§7.2): resources, scopes `owner` and `read`, tokens,
  SSE, OpenAPI, `wpk --at`; notifications (§7.3); the `wpk serve` unit
  (rest of server.md S2).
- **Exit:** a dv-flow-mgr regression on featherweight-ip started from a
  step, its graph filling in on the board, the packet woken at the end
  with the result in the prompt; a phone notification when it needs you.

### R4: Step into the bug

- Export and import, materialize, `wpk clean`, the `file://` store
  (§11.1, §11.3).
- `wpk export --from-ci`, wired into `ci/run.sh` in featherweight-ip
  (§11.2); the `from-ci-failure` template and the template mechanism
  (§7.5).
- The VS Code extension (§10.3), including Review.
- Export profiles (§11.1), including `report`; `wpk report`; import of a
  report as untrusted data (§12).
- **Exit:** a real CI failure in featherweight-ip becomes a packet on
  the board, reproduces, opens in VS Code at the revision, and the agent
  finds the cause. Then the same for a dv-solve pytest failure. And a
  bug in pyvsc or pyhdl-if filed as a report file on its issue tracker
  and reproduced by importing it on another machine.

### R5: Link up (small team)

- Links and the `peer` scope (§7.2, §7.4): `wpk link add/accept/ls/rm`, pairing on
  and off a tailnet, self and peer links.
- One board across your own hosts (self links).
- Teammates' shared packets on your board; `wpk assign` and `wpk
  consult` over a link (§11.7): copies, replies with answers and
  changes, forward and apply; inbox, outbox and retry; transcript
  requests and approvals.
- **Exit:** two people, two daemons, no server; a packet assigned from
  one to the other, opened, worked on and assigned back. Then three
  people: one packet sent as copies to the other two, both reply (one
  with changes), the owner forwards one reply to the agent and applies
  the other's changes.

### R6: The hub (organization)

- `wpk hub`: index and directory, store and relay, CI intake, team
  boards (§11.4).
- Organization sign-in (OIDC), sharing policy, export policy, retention,
  audit.
- **Exit:** the R5 team joins a hub with `wpk link add`, with no change to
  any packet; a CI failure in featherweight-ip lands on the right
  person's board through the hub.

### R7: Across organizations

- Public intake on a hub (`.wpk/intake.toml`, triage column, limits);
  `wpk report --to <repo URL>`; an issue opened on the forge that links
  to the report.
- Hub-to-hub links with policy on both sides.
- Signed reports (§13 D11); the round trip: state back to the
  reporter, questions to their Needs you.
- Sandboxed reproduction (§13 D10).
- **Exit:** an fvutils project (pyvsc or pyhdl-if) takes reports at a
  public intake; a report from a machine outside the tailnet reproduces
  on arrival, and the maintainer's question reaches the reporter's board.

### R8: Browser IDE and scale-out

- TLS (server.md S1b); web VS Code under `/ide/` with both backends
  (§10.4, ide.md I3).
- SLURM backend for jobs (and steps), licence pools (§7.6).
- Placement by an administrator (§11.5).
- **Exit:** from an iPad, open a packet in the browser IDE, start a
  SLURM job, watch it finish.

Order rationale: the order follows the scales. R1 first because
everything after it makes a half-finished step visible to more people,
and because `wpk dash` alone has to be worth installing. R2 and R3 are
the daily wins for one person. R4 is the flagship and brings export,
which links and the hub both build on. R5 makes a team possible without
anyone running a server; R6 only adds what a mesh of links cannot do
well. Reports as files come early (R4) because they need nothing on
either side; R7 adds what needs a public endpoint. R8 is the least
urgent for the current users.

## 15. Not in scope

- An IDE or editor of our own. VS Code is the IDE.
- A multi-tenant server that runs several people's work on one account.
  If wanted later, it builds on the hub (§11.4), and it needs its own
  security design.
- A hosted service that the smaller scales depend on. Every scale must
  work without anything above it (§5.1).
- Live process migration. Placement moves files; running processes are
  not moved.
- A replacement for CI or for dv-flow-mgr. work-packet starts and
  watches them.
- Changes to dv-flow-mgr. Improvements it might want for itself are
  listed in workflow-review.md §6.2.1.

## Status log

### 2026-10-25: design written

Written from `docs/workflow-review.md` and your decisions there: per-user
wpkd with a hub; tmux optional; featherweight-ip then fvutils for the CI
flow; wpk reads dv-flow-mgr unchanged; host to host is internal. The open
decisions are §13; R1 is the next thing to build.

### 2026-10-25: three scales

You set the adoption model: one user gets value from `wpk dash` alone, a
small team links up by agreement, an organization stands up a hub.
Added principle 6 and §5.1 (three scales, one protocol); §7.4 is now
links (self and peer) with a peer API that never runs actions; §11.4
makes the hub a peer with an index, store, CI intake, sign-in, policy
and audit; §12 adds "links are not logins"; D8 (identity off a tailnet)
and D9 (`wpk dash` runs by default); releases now follow the scales,
with R5 "Link up" before R6 "The hub" (browser IDE moves to R7).

### 2026-10-25: across the internet

You added that this should work between organizations as well as
inside one, and that a bug report is a stripped work packet. §5.1 is
now four scales (the fourth: between organizations) with rules 6 (the
further it goes, the less it carries) and 7 (what comes from outside is
data); §11.1 has export profiles `full`, `team` and `report`; new §11.6
covers reports as files, public intake and hub-to-hub links, with the
round trip back to the reporter; §12 treats outside packets as
untrusted (no runs, no permissions, no instructions to an agent); D10
(sandbox) and D11 (signing); R4 gains reports as files, R7 is "Across
organizations", the browser IDE moves to R8.

### 2026-10-25: one REST API

You noted that the scales motivate a REST API inside. §7.2 is now one
versioned REST API (`/api/v1/`) for every client, with design rules
(resources, one action with three faces, ownership as a resource,
idempotency keys, ETags, OpenAPI), a resource table and scopes
(`owner`, `read`, `ci`, `peer`, `public`). The separate `/peer/` API in
§7.4 is gone: a link holds the `peer` scope. `wpk --at` drives another
daemon through the API. R3 builds it; R5 adds the `peer` scope.

### 2026-10-25: assign and consult

You noted that the hand-off path must also work between coworkers, in
two ways: asking several people for input on copies, and handing a
packet to a colleague so that it is no longer yours. New §11.7 sets
them beside hand-off: **assign** (it becomes theirs; your copy a
read-only tombstone; jobs, sessions and the runner settled first) and
**consult** (copies to each person, replies with answers and optional
changes, forward to the agent, apply changes, `--wait`). Concepts,
principle 2, the states note, the REST resources, §7.4, D12 (the name)
and D13 (replies reach the agent only when forwarded), and R5's exit
check are updated. Also fixed: §11.5 Placement now comes before §11.6.
