# Console: ask and act from the board (plan and status)

Started 2026-10-29. Status: **C1, C2 and C3 built** 2026-10-29. C-Q1 to C-Q3 answered.

## Why

Most of the questions I ask in the terminal are about what the board shows:
"why is this packet stuck?", "what did that run do?", "pause this project",
"what is the server doing?". To ask them I leave the board, open a terminal,
and tell the model what I was looking at. The board already knows that.

## What exists today

- **One set of actions** (`actions.py`, docs/interaction.md §4). The CLI,
  the board and the TUI call it and add no logic of their own. Slash
  commands should do the same.
- **Shells in the browser** (`dash/shells.py`). These are pty sessions the
  server owns, reached over a WebSocket (`/p/{project}/shell/{sid}`). They
  outlive the socket and reattach with recent output. The agent's stream can
  reuse this pattern.
- **The Claude harness** (`harness/claude.py`). It runs
  `claude -p --output-format stream-json`, sets `--model` and `--session-id`,
  continues a conversation with `--resume`, and parses the transcript.
- **The guard** (`dash/guard.py`). It tells the board who the caller is and
  what rights they have (e.g. `cancel`). Commands that change state check
  those rights, as the matching board buttons do.

## Proposal

### 1. A console drawer on every page, scoped to the page

A drawer at the bottom of `base.html`, opened with a key (`` ` ``) or a
button. The page you are on sets its **scope**:

| Page | Scope | Agent's cwd | Default target of `/cmd` |
|---|---|---|---|
| `/`, `/stats`, `/sched`, `/runs`, `/boards`, `/packets` | server | wpk source repo (C-Q1) | none: name one |
| `/runs/{sid}` | server, with the run | wpk source repo | the run |
| `/p/{project}` and its tabs | project | project dir | the project |
| `/p/{project}/{wpid}` | packet | project dir | the packet |
| `/p/{project}/{wpid}/{step}` | packet, with the step | project dir | the packet |

A line can still name another target (`/pause other-project`). The page
sends its scope with each line, so neither you nor the agent has to say what
you are looking at.

### 2. Slash commands: run directly, no model

A line that starts with `/` is parsed and passed to `actions.py`, or to a
read-only query. The model is not involved: these are instant and always do
the same thing.

- **Change state:** `/pause`, `/resume`, `/stop`, `/note`, `/handoff`,
  `/answer`, `/continue`, `/allow`, `/deny`, `/set`.
- **Read only:** `/show`, `/questions`, `/runs`, `/log`, `/sched`,
  `/help`.
- **Console:** `/model <alias>`, `/new` (start a fresh conversation),
  `/sessions`, `/packet` (§5).

The command table is built from the CLI's argparse, or from one table both
use, so the console and `wpk` cannot drift apart. That table also gives
`/help` and tab completion. Results come back as rendered cards with links,
like the board's own panels, not as plain text. Rights are checked as the
board checks them.

### 3. Everything else goes to an agent

A line without a leading `/` goes to a Claude session that the server runs
through the harness: headless `claude -p --output-format stream-json`,
continued with `--resume`. The server streams its events to the drawer
over a WebSocket. The agent:

- starts in the cwd the scope gives (§1) and gets a primer: the scope (the
  project, packet, step or run, and their state), a short guide to `wpk`
  and the board, and the slash-command table;
- has **read-only tools** by default: `Read`, `Grep`, `Glob`, and a Bash
  allowlist limited to read-only `wpk` subcommands and reading logs;
- uses a cheap model by default (C-Q3). `/model` switches models for the
  rest of the conversation.

### 4. The agent acts by proposing slash commands

The agent does not change state itself. When it wants to, it writes a
slash command on a line of its own (`/pause wp-123`). The drawer renders
that line as a button:

- a **read-only** command runs at once and its card is shown inline;
- a command that **changes state** waits for a click and is checked against
  the caller's rights, as if typed.

So both modes act in one way, approval comes with it, and every change
appears in the transcript as the command that made it.

### 5. Sessions: global, per project, per packet (C-Q2)

A conversation belongs to the scope it started in: the server, a project or
a packet. Opening the drawer on a page resumes the latest conversation for
that scope. `/new` starts another, and `/sessions` lists the earlier ones.

Transcripts are kept: the slash commands, their cards, the agent's
replies, and any commands proposed, run or declined. They are stored under
the server's home (`<home>/console/<id>/`: `meta.json` and
`transcript.jsonl`), not in the project tree. Packets are not tied to git,
and this keeps the console from writing into a workspace. A project's
**Console** tab and a packet's page list the conversations about them.

`/packet` makes a packet from the conversation: the instruction is drafted
from the transcript and opened in Compose for you to edit before handing
it off.

### C-Q1: what is the agent's cwd? (answered)

**Both, chosen by the page.** Project and packet pages use the project dir.
Server-level pages use the wpk source repo when wpk is installed editable
(found from `work_packet.__file__`), and the server's home otherwise.

### C-Q2: one console or one per scope? (answered)

**All of them**: server, project and packet conversations, as in §5.

### C-Q3: model (answered)

**A cheap model by default** (`haiku`), switched per conversation with
`/model`. The default is a `[console] model` key in the server config.

## Steps

- **C1: the drawer and slash commands, no model.**
  - `dash/console.py`: a parser for the command table, scope resolution from
    the page path, dispatch to `actions.py` and the read-only queries.
  - `POST /console/cmd` returns a rendered card.
  - `_console.html` and `console.js`: the drawer, its key, history (↑/↓),
    tab completion and `/help`.
  - Tests: parsing, scope defaults, rights, and one command per action.
- **C2: the agent, read-only, streaming.**
  - Agent sessions on the server, like `shells.py` (a cap on how many,
    an idle timeout, reattach), built on `harness/claude.py`.
  - `WebSocketRoute /console/ws/{id}`; the primer; the tool allowlist;
    `/model`.
  - The session store (§5), `/new`, `/sessions`.
  - Tests with `tests/fakemodel`.
- **C3: commands the agent proposes, history, making packets.**
  - Spot a proposed command in the agent's output; render it as a button;
    run read-only commands at once; record each command as run or declined.
  - The Console tab on the project page; the list on the packet page.
  - `/packet` → a Compose draft.

## Status

- 2026-10-29: plan written; C-Q1 to C-Q3 answered.
- 2026-10-29: **C1 built.**
  - `dash/console.py`: `scope_of(path)`; target resolution (the page's
    scope, a project name, a packet id or unique prefix from anywhere,
    `project/wpid`; `@target` for the commands that take text); the
    commands `/help /show /questions /open /pause /resume /keep /stop /note
    /handoff /answer`. They call `actions` and `executor` as the board's
    buttons do. Archived projects are refused. `/stop` needs the `cancel`
    right. Results are JSON cards (`text`, `lines`, `href`).
  - `POST /console/cmd` (`{line, path}`, the CSRF token in a header) and
    `GET /console/commands` (for completion), in `app.py`.
  - `base.html`: a **console** button in the header and a drawer outside
    `<main>`, so live refresh leaves it alone. `console.js`: `` ` `` opens it,
    Esc closes it, ↑/↓ for history and Tab to complete. History, the last
    40 cards and whether the drawer is open are kept in localStorage. After a
    command that changes state, the page reloads.
  - The command table is the console's own (`console.COMMANDS`), not
    generated from the CLI's argparse as §2 proposes: the CLI's argument
    shapes don't fit a scoped console well. Revisit if they drift.
  - Tests: `tests/test_console.py` (8); the full suite passes (851).
  - Not tried in a browser yet: needs the dashboard restarted.
- 2026-10-29: **C2 built.**
  - `dash/agent.py`: `Agents`, the conversation store and the replies
    running. One `claude -p` process per reply, on a thread: the first with
    `--session-id`, later ones with `--resume` (no fork), so a conversation
    is one Claude session. `--permission-mode dontAsk`, `--tools
    Read,Grep,Glob,Bash`, and `--allowedTools` limited to Read/Grep/Glob, `ls`
    and read-only `wpk` subcommands (`agent.WPK_RO`). Everything else is
    refused without asking. The user's settings, MCP servers and slash
    commands are left out, as for steps. `wpk` is put on the agent's PATH and
    `WPK_HOME` is set to the board's. The server's home (and the project dir)
    are added with `--add-dir`.
  - The primer (`prompts/console.md` and the scope, its `/show` card or the
    project list, and the slash-command table) is written to
    `<home>/console/<id>/primer.md` before each reply and passed with
    `--append-system-prompt-file`, so it always has the current state.
  - Store: `<home>/console/<id>/meta.json` (scope key `server`, `p/<project>`
    or `p/<project>/<wpid>`; cwd; model; Claude session id; turns; cost;
    title = the first question), `transcript.jsonl` (`cmd`, `ask`, `say`,
    `tool`, `end`), `stream.jsonl` (raw), `stderr.log`. A scope's
    **current conversation is the one updated last**: `/new` makes one, and
    `/sessions <id>` touches an older one, so the browser keeps no state.
    Slash commands are recorded too, so the conversation is the drawer's
    history (made on the first line typed in a scope).
  - Commands: `/model [name]`, `/new`, `/sessions [id]`, `/cancel` (also a
    **stop** button while a reply runs). `[console]` in config.toml: `model`
    (haiku), `budget_usd` per reply (0.5), `max_running` (4), `timeout_s`
    (600); validated in `schema.py`.
  - Routes: `POST /console/cmd` now goes through `console.line` (slash or
    question); `GET /console/conv?path=` gives the page's conversation and
    transcript; `WS /console/ws/{id}` (CSRF token in the first message, as
    for the shell; `?since=` replays later events, then streams). Without an
    `Agents` (tests, `create_app` alone) the console is slash-only, as in C1.
    `wpk serve`/`dash` server makes one and stops running replies on shutdown.
  - `console.js`: loads the transcript from the server (the C1 localStorage
    cards are dropped), streams replies, shows the model and "thinking…".
    Replies are whole messages (stream-json without partial messages), not
    token by token.
  - Tests: `tests/test_console.py` (14, with a `console` fake behaviour):
    cwd per scope, the primer, session-id then resume, the flags, per-scope
    conversations, `/new` `/sessions` `/model`, busy and `/cancel`, the
    socket behind the guard. Full suite: 856 passed. One flake,
    `test_dash_pages_match_the_legacy_layout`, which compares real step
    durations and failed under load average 19, passes when re-run.
  - Tried against the real CLI (haiku, a scratch home): `wpk ps` ran,
    `touch /tmp/…` was refused by dontAsk, $0.033 for the reply.
  - Not tried in a browser yet: needs the dashboard restarted.
- 2026-10-29: **C3 built.**
  - Proposals: `console.proposed(text)` finds the lines of a reply that are
    a known slash command on their own (indented, in backticks or after `$ `
    too; not `/model /new /sessions /cancel`). They are kept with the `say`
    event as `props`. `/show`, `/questions` and `/help` (`console.AUTO`) run
    at once on the server, and their cards go in the transcript with `ref`
    and `auto`. In the drawer they are folded to their head line. The rest
    show **Run** and **Dismiss**. Run posts the line with `ref`, so it goes
    through the same checks as a typed command. Dismiss records a `decline`.
    `/open` is a button too (it navigates).
  - History: `/console` (in the side nav) lists every conversation;
    `/console/c/{id}` shows one, read-only, with what became of each
    proposal; the project's **Console** tab (`/p/{project}/console`) lists
    those about the project and its packets; a packet page lists its own.
  - `/packet [instruction]`: the instruction (or the first question), then
    the last three exchanges quoted, and the transcript's path. It opens
    Compose (`?instruction=`) on project and packet pages and New packet
    (`?objective=`) on server pages, for editing before anything is made.
  - Found in the browser (headless Chromium over CDP; there is no
    puppeteer): the packet page's new `<h2 id="console">` hid the drawer
    from `getElementById`, so console.js threw. It is renamed, and a test
    checks for a single `id="console"` per page. The browser run covered
    the drawer, a click on Run (packet PAUSED), reopening after the reload,
    the list, the transcript page and a 390px-wide phone screen.
  - Tests: `tests/test_console.py` (19). Full suite: 862 passed.
  - Not done: the agent is not told what a proposal it made returned (a card
    from a command that ran at once is for the person). Feeding results back
    is a possible C4, along with token-by-token replies
    (`--include-partial-messages`).

