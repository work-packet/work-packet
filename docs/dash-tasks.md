# The board as a workbench: new tasks, a shell, and the next batch of work

Status (2026-10-25): T1–T4 built; T5 (a live trial with the real model)
to do. Recommendations in §9 accepted. 466 tests pass. Not committed. A fresh session should be able to
pick up from this file and the status log at the end. Read with
setup.md (§6 the wizard, §10 the setup at the root), interaction.md (§4
actions, §5 the board) and server.md (§1 "the board is a shell", S2 one
daemon).

## 1. The problem

Today the board can answer, hand off, pause, take notes and change
settings. Everything else needs a terminal:

- **Starting a task** is `wpk new`, then `wpk setup` (a TUI) or a shell to
  clone repos, copy inputs, write `prompt.md`, set limits.
- **Continuing a task that finished** is not possible at all. `COMPLETED`
  is a dead end in the executor: `admin("handoff")` accepts only
  `NEEDS_INPUT`, `PAUSED` and `FAILED` (`executor.py:729`), although
  long-running.md §1 says a completed packet should take a new instruction
  and carry on.
- **After a hand-off** nothing runs until someone types `wpk tick`. There is
  no runner in the server yet (server.md S2).

What we want: do the whole loop from the board.

```
 New task ──► Compose ──► Hand off ──► runner works ──► stops
  (form)     settings      (checks)                  (done, question,
             prompt                                    failed, limit)
             shell                                        │
               ▲                                          │
               └──────────── Next batch ◄─────────────────┘
```

**Compose** is one page, used both for a new task and for the next batch of
an existing one. It has the settings, the instruction, the doctor checks
and a shell.

## 2. Design rules

1. **No new logic in the board.** Every form writes through the functions
   the CLI uses (`project.new`, `project.set_values`/`allow`/`deny`,
   `setup.instruct`, `setup.add_input`, `executor.admin`). New behaviour,
   such as continuing a completed packet, goes into `executor`/`actions`
   first and gets a CLI command, then a form.
2. **Ownership decides what is editable** (long-running.md §1). Compose
   and the shell are open only while you own the packet: not `RUNNABLE`,
   not `SLEEPING`, no step running. To change a running task, pause it
   first (or send a note, interaction.md §6a).
3. **The shell is your shell.** It runs as the daemon's user, which the
   board already equals (server.md §1). It is a convenience, not a
   sandbox.
4. **A hand-off ends your turn.** Shells for that project are closed, and
   the runner starts the step at once.

## 3. New task

**Board → New task** (a button in the header) opens a short form:

| Field | Default | Goes to |
|---|---|---|
| Name | — | `project.new(name, None, …)`; held for setup |
| Directory | `<projects home>/<name>` | `path=` |
| Profile | the default in `profiles.toml` | harness, model, sizing |
| Copy setup from | none | `--from-setup` (`setup.copy_setup`) |

Creating it redirects to the project's **Compose** page. Nothing else is
asked up front: the rest is in Compose, where the checks show what is
still missing.

## 4. Compose

`/p/<project>/compose` for the root packet (and `/p/<project>/<wpid>/compose`
for a held child, later). Layout, wide screen:

```
┌ dvs-enh ─ Compose ─────────────────────────────── yours: setup ─┐
│ Checks              │ Instruction                    [template ▾]│
│ ✓ Project           │ ┌──────────────────────────────────────────┐│
│ ✗ Work repos  1     │ │ Work through state/plan.md, items 0a–2.  ││
│ ✓ Inputs            │ │ ...                                      ││
│ · Smoke test        │ └──────────────────────────────────────────┘│
│ ✓ Limits            │ As the model sees it ▸   3.1 KB (shown)     │
│ ✓ Permissions       │                                             │
│ ✓ Instruction       │ Settings ▸  Inputs ▸                        │
│                     ├─ shell: dvs-enh/ ─────────────── [+ shell] ─┤
│ ✗ packages/ is      │ [wpk:dvs-enh] dvs-enh$ git clone …/dv-solve │
│   untracked         │ [wpk:dvs-enh] dvs-enh$ █                    │
│   [Do it] [Type it] │                                             │
├─────────────────────┴─────────────────────────────────────────────┤
│ Note for the model [                          ]   [Save] [Hand off]│
└───────────────────────────────────────────────────────────────────┘
```

On a phone the panels stack: Checks, Instruction, Settings, Shell.

- **Checks** (left): `setup.doctor` grouped by stage, as in the wizard
  (setup.md §6). Each failing check has its fix:
  - **Do it** posts the fix for a `safe` one, or one that only writes
    inside the project;
  - **Type it** puts the command into the shell *without* Enter, so you
    read it first. This is the default for anything outside the project.
  
  The checks rerun after each command in the shell (§5.3), after each
  form post, and with a Recheck button.
- **Instruction:** a text area with the template picker (`instruct-*.md`).
  Before the seed it writes `prompt.md` at the root; after it, the draft of
  the next batch (§6.2). **As the model sees it** renders the step prompt
  (`prompt.py`), so the 4 KB shown/listed rule is visible.
- **Settings** (collapsed): limits, model and profile, and permissions
  with presets ("read-only", "build and test", "unrestricted Bash") plus
  the editable `allowed_tools` list. The same POST as today's Settings
  panel (`/p/<project>/settings`); this moves it into Compose and the
  project page links here.
- **Inputs** (collapsed): the files in `state/` with sizes, an upload box
  (`setup.add_input`), and a remove button. Bigger things go through the
  shell.
- **Hand off:** enabled when no check is `missing` (with "hand off
  anyway" behind a confirm, as `--force`). It shows how many shells will
  be closed. It runs `actions.handoff` (or `actions.continue_`, §6) and
  pokes the runner, then redirects to the live view.

## 5. The shell in the browser

### 5.1 Pieces

- **Front end:** xterm.js plus its fit add-on, vendored under
  `dash/static/vendor/` (MIT). The CSP is `script-src 'self'` and the
  tailnet may have no internet, so no CDN.
- **Transport:** a WebSocket, `/p/<project>/shell/<sid>`. Binary frames
  carry terminal bytes both ways. Text frames carry JSON control messages:
  `{"resize": [cols, rows]}` from the page; `{"checks": …}`, `{"exit": code}`
  from the server.
- **Server:** `dash/shells.py`, a small session manager. Each session is
  `os.forkpty()` running `setup.shell_argv(tg, …)` (the same rc file,
  `[wpk:<name>]` prompt and history file as the wizard), read with
  `loop.add_reader`. uvicorn needs `websockets` for this; it joins the
  `dash` extra.

### 5.2 Sessions outlive the page

A reload, a dropped Wi-Fi or a closed laptop must not kill a half-done
`git clone`. So a session belongs to the server, not to the socket:

- each keeps the last 256 KB of output; a new socket to the same `sid`
  gets the replay, then live output (one socket at a time; a second one
  takes over);
- with no socket attached it lives 30 minutes, then gets `SIGHUP`;
- at most 8 sessions per server; `[+ shell]` opens another tab in the
  pane, and the project page lists open shells with a close button;
- the session ends when the shell exits, on hand-off (rule 4: `SIGHUP` to
  its process group, then `SIGKILL` after 5 s), or when the server stops.

Not kept across a server restart. tmux would give that, but it adds a
dependency and a second scrollback; a "copy to tmux" hint is enough for
now.

### 5.3 Rechecks without a FIFO

The wizard's rc snippet touches a FIFO after each command. In the browser
the pty stream is already there, so the rc's `PROMPT_COMMAND` prints a
private OSC sequence, `ESC ] 7777 ; wpk-recheck BEL`. The session manager
strips it from the stream, reruns `doctor` (debounced, in a thread), and
sends `{"checks": …}` to the page, which redraws the Checks panel.

### 5.4 Where it starts

| Packet state | Starts in | Why |
|---|---|---|
| held for setup (no seed yet) | the project root | where setup.md §10 says you set up |
| after the seed (next batch, §6) | the root packet, `packets/<UUID>/` | its `state/` and `work/` worktrees are what the next step sees |

Environment as the wizard: `WPK_PROJECT`, `WPK_WPID`, `WPK_PACKET`,
`WPK_WORK`.

### 5.5 Security

The Guard refuses every non-HTTP scope today (`guard.py:122`). It gains a
WebSocket path with the same checks as a POST:

- the Host check and the user's identity (loopback user or tailnet
  `whois`), as for HTTP;
- `Origin` must match (browsers always send it on a WebSocket);
- the CSRF token in the first text frame, `{"token": …}`; anything else,
  or nothing within 5 s, closes with 1008. Not in the URL, so it stays out
  of logs and history;
- the CSP gains `connect-src 'self'`.

Each session records who opened it and when, in the project's
`.setup/shells.log`, and its keystrokes go to the same bash history file
as the wizard's.

## 6. The next batch of work

### 6.1 What it is

A packet that has stopped can be given a **new instruction** and handed
back. This differs from today's hand-off, which adds a note to the
existing instruction:

| | Hand off (today) | Next batch (new) |
|---|---|---|
| From | `NEEDS_INPUT`, `PAUSED`, `FAILED` | those, and **`COMPLETED`** |
| Instruction | unchanged; the note is added | replaced by the one you wrote |
| `state/` | kept | kept; the outline can be archived |
| Record | `handoff` | `handoff` with `instruction` and `batch` |

The board offers **Next batch** on a stopped packet's page (the main button
on a `COMPLETED` one), which opens Compose for that packet.

### 6.2 Drafts

Until the hand-off, `memento.md` still holds the model's last memento,
which the packet page shows. So Compose does not write it. The draft goes
to `<project>/.setup/next/<wpid>.md` (instruction) and `.json` (note,
options), saved on **Save** and every few seconds while typing. Nothing in
the packet changes until the hand-off, so you can leave a draft for days.

### 6.3 The hand-off

`actions.continue_(pkt, instruction, note=None, archive_outline=True,
carry_session=False)` and `wpk next <target> [--file F] [-m NOTE]
[--keep-outline] [--carry-session]`. Inside `executor.admin`, under the
lease:

1. check the state (stopped, as the table above) and the instruction (not
   empty; `schema` validates it as a memento body with no front matter);
2. if `archive_outline`: move `state/outline.md` to
   `state/history/outline-<batch>.md`, so the model starts a new outline
   instead of seeing a finished one;
3. write the instruction as `memento.md`; reset `attempts`, `reason`,
   `wake_at`; set `RUNNABLE`;
4. append `{"type": "handoff", "from": "COMPLETED", "to": "RUNNABLE",
   "batch": 2, "instruction": "…", "note": "…", "by": …}`. `batch` counts
   these records, starting at 1 for the first run;
5. delete the draft.

The model's last memento of batch 1 is not lost: each step's committed
`steps/NNNN/result.md` holds the memento it wrote (`executor.py:665`).

### 6.4 What the model sees

The step prompt's Hand-off section gets a variant for a new batch:

> **New work (batch 2).** The previous instruction is finished. Its last
> memento said: «summary». Your instruction is below. `state/` still holds
> what earlier steps wrote; the old outline is in
> `state/history/outline-1.md`.

`protocol.md` gets two sentences on this. Notes still in the inbox show as
usual.

### 6.5 Carrying the session

Optionally the first step of the new batch resumes the model's last session
(`--resume <id> --fork-session`, harness.md C4), so it starts with its own
memory of the work. That is often worth it right after a batch, but the
cache will usually have expired: the first call rereads the whole context
at the cache-write price. Compose shows the estimate (the last step's
context tokens × the write price) next to the checkbox. Off by default.
Uses the existing carry-over code path; `continue_` just records the
choice for the next step.

### 6.6 Changes you made by hand

After the seed, the shell starts in the packet, so you may edit its
`state/` or commit in its `work/` worktrees. The hand-off records each work
repo's `HEAD` (`"heads": {repo: sha}`), and the Hand-off section lists the
commits since the last step's heads ("you committed 2 changes in dv-solve:
…"). Uncommitted changes in a work repo block the hand-off with a check
("commit or stash in work/dv-solve"), rather than being committed for you
(long-running.md §1 proposed auto-committing them; it is not built, and a
refusal is easier to reason about).

## 7. Handing off means it runs

A hand-off today only makes the packet `RUNNABLE`. For the board to be
enough, the server must run steps. That is server.md S2 ("one daemon"),
not built. This plan needs the smallest part of it:

- `wpk dash --run`: a scheduler loop in the server process, calling
  `scheduler.tick(entries, until_idle=True)` in a worker thread, woken by
  a timer (next `wake_at`) and by an in-process poke from every hand-off,
  answer and wake;
- one runner per home, by a lock file, so a `wpk tick` beside it does not
  double-run (the lease already prevents double steps; the lock avoids
  the noise);
- SIGTERM: stop listening, let a running step finish, exit.

`--install-unit`, `wpk serve` as a name and the rest of S2 stay in
server.md.

## 8. Build plan

Each stage is usable alone. Mark `[x]` when its tests pass and note
anything left over in the status log.

- [x] **T1 Runner in the server (§7).** `--run`, poke, lock, SIGTERM.
  Tests: hand-off through the app runs a fake step without `wpk tick`;
  a second runner exits on the lock.
- [x] **T2 Next batch in the core (§6).** `executor.admin("continue")`,
  `actions.continue_`, `wpk next`, outline archive, `batch` and `heads`
  in the record, the prompt variant, protocol text, carry-session option.
  Tests: `COMPLETED` → `RUNNABLE` with a new memento; refused while
  running; the prompt shows batch 2 and the commits; outline archived and
  kept with `--keep-outline`; a dirty work repo refuses.
- [x] **T3 Compose page (§4) without the shell.** New task form; Compose
  with Checks, Instruction (template, preview), Settings, Inputs (upload
  needs `python-multipart` in `dash`), drafts, Hand off and Next batch.
  Tests: each form equals its CLI command; Compose read-only while the
  runner owns the packet; a draft survives and is deleted on hand-off.
- [x] **T4 Web shell (§5).** Vendored xterm.js, `shells.py`, the
  WebSocket route, Guard for WebSockets, replay on reconnect, idle
  timeout, OSC recheck, close on hand-off, Type it. Tests: a WebSocket
  without the token or with a foreign Origin is closed; echo through a
  pty; reconnect replays; the OSC sequence triggers a `checks` message and
  is not shown; hand-off kills the session.
- [ ] **T5 Live trial.** Create a small project from the board on a
  second device, clone a repo in the browser shell, hand off, let it
  finish, then give it a second batch from the board with and without the
  session carried; note the costs.

Order: T1 and T2 first (they make the loop work from the CLI), then T3,
then T4. T3 is useful without T4: the shell can still be `wpk shell`.

## 9. Open questions

Recommendations in **bold**; take them unless told otherwise.

1. **Shell lifetime.** Server-owned sessions with replay and a 30-minute
   idle timeout (§5.2), or a shell that dies with its socket? **Server-owned.**
MSB: Fine
2. **Dirty work repos at hand-off.** Refuse (§6.6) or commit them as
   "handoff: …" (long-running.md §1)? **Refuse**, with Type it offering the
   commit command.
MSB: Fine
3. **Archive the outline by default** on a next batch? **Yes** for
   `COMPLETED`, **no** for the other states (there the batch usually
   continues the same plan).
MSB: Fine
4. **Next batch on children.** Root only for now; a held child gets
   Compose later if it turns out to be needed. **Root only.**
MSB: Fine
5. **Second batch's budget.** Do limits count per batch or for the
   project's life? **Per step as today**; a per-batch budget is a later
   setting.
MSB: Fine

## Status log

### 2026-10-25: design

Written after the user asked to fill in a task from the board (settings,
prompt, a shell hosted by the server to set up files) and to continue a
task that has stopped by setting up the next batch of work and handing it
off. Found while surveying: `COMPLETED` cannot be handed off
(`executor.py:729`); the Guard refuses WebSockets (`guard.py:122`); no
runner runs in the server (server.md S2 open); work-repo heads are not yet
recorded at hand-off. Not built.

### 2026-10-25: T1–T3 built

- **T1.** `dash/runner.py`: a thread running `scheduler.tick(until_idle)`,
  woken by `poke()` (every successful board action) or the next `wake_at`
  (at most 60 s). `runner.lock` (flock) allows one per home. `wpk dash
  --run [-j N]`, or `[server] run = true`. SIGTERM: no new step starts,
  running ones finish. `scheduler.tick`/`run_pass` take a `stop` callable;
  `scheduler.next_wake`. The header says "runner on/off".
- **T2.** `executor.admin(…, "continue", instruction=…)`, `actions.continue_`,
  drafts (`actions.save_draft/load_draft/drop_draft`, `.setup/next/`),
  `wpk next <target> [-f F | --draft] [-m] [--archive-outline] [--carry-session]
  [--force]`. Every step's `decision` records `heads`; every hand-off
  records `heads` and `commits` since. Prompt: "New work (batch N)" and the
  commits; protocol.md "A new batch of work"; spec.md §4.3 rows. Carry:
  `_carry_from(asked=True)` skips the setting, state, TTL and factor checks.
- **T3.** `/new` (name, directory, model, copy setup from), `/p/<p>/compose`
  (checks, instruction with templates or "the last instruction", draft,
  archive/carry options with the context size to reread, note, Save, Hand
  off / anyway, Do it for safe fixes, inputs upload/remove, Settings panel
  as a macro shared with the project page). Links: board setup cards, the
  packet page ("Set it up" / "Next batch"), the project page. `compose.js`
  (enable on "anyway", Ctrl+S, unsaved warning). The Guard takes the CSRF
  token from the URL for multipart uploads. `dash` extra gains `websockets`
  and `python-multipart`.
- Left out of T3: permission presets (none exist yet; the tool list is
  editable) and a full "as the model sees it" prompt render (the page
  shows size and shown/listed per input instead).
- Tests: `tests/test_dash_tasks.py` (12). Full suite after T2: 458 passed.

### 2026-10-25: T4 built, and the loop checked on a real server

- `dash/shells.py`: `pty.fork` sessions on the server's loop, 256 KB replay,
  one socket at a time (a second takes over), 30 min idle with none
  attached, at most 8, SIGHUP then SIGKILL after 5 s, opens logged to
  `<project>/.setup/shells.log`. The rc's `PROMPT_COMMAND` prints
  `ESC]7777;wpk-recheck BEL`; the session strips it (also when split
  across reads) and sends `{"recheck": true}`; `shell.js` refetches the
  page and swaps the Checks panel.
- WebSocket `/p/<p>/shell/<sid|new>`: the Guard checks host, identity and
  `Origin` (ws/wss map to http/https); the app wants `{"token"}` first
  (1008 otherwise, 5 s). Binary frames are terminal bytes; text frames are
  `resize`, `input` (Type it), `close`. A new shell needs the task to be
  yours. Compose's hand-off closes the project's shells.
- `shell.js` + vendored xterm.js 6.0.0 and addon-fit 0.11.0
  (`dash/vendor/`, MIT): tabs, + shell, close, reconnect with backoff,
  reattach on reload (sessionStorage), Type it opens a shell if none.
- Checked against a real `wpk dash --run` (scratch script, fake model):
  New task → shell writes `prompt.md` → recheck → hand off (1 shell closed)
  → runner to `COMPLETED` → Next batch → step 9 → SIGTERM waits for the
  running step, exit 0, no tracebacks. Headless Chrome: xterm renders,
  typing works, no CSP errors, the Checks panel updates after `git init`,
  a reload replays the output.
- Tests: 4 more in `tests/test_dash_tasks.py` (16). The WebSocket tests
  hold one TestClient portal open, since sessions live on one event loop
  (as under uvicorn). Full suite: 466 passed, 4 skipped.
- Not done: mobile layout of the terminal beyond the panels stacking; no
  shell for a held child (decision 4).

### 2026-10-25: harness and model choices in New task

New task has a harness `<select>` and a model combo box (an `<input>` with
a `<datalist>` per harness; `new.js` switches the list with the harness).
Choices: `Harness.models()` (Claude: the `--model` aliases, then full
names, in `harness/claude.py` `MODELS`), then models that registered
projects use, and the configured default. Any other model can be typed.
Claude Code cannot list the models an account may use: there is no CLI
command, `/v1/models` needs an API key (a claude.ai login has none), and
`~/.claude/stats-cache.json` is internal and lists other gateways' models
too. So the list is fixed and must be updated when models change; a
one-call probe (`claude -p --model X`) could check a choice later.

### 2026-10-25: the shell starts by itself, and says why when it cannot

Reported: the shell pane showed only a cursor. The server was fine (a
WebSocket to the running board got the prompt); the page started no shell
until "+ shell", and a failed connection was silent. Now: the pane opens
a shell when none is open (without taking the keyboard), writes
"Starting a shell…" and any failure (with the close code) into the
terminal, and the board logs refused WebSockets (host, Origin, token).
The CSP names `ws://<host> wss://<host>` in `connect-src` (older Safari
does not count them as 'self'), and script URLs carry `?v=<version-mtime>`
so a browser does not keep an old `shell.js` for the 5-minute cache.

### 2026-10-25: the shell is opt-in again

A shell opened by itself on every Compose visit, so each look at the page
left a pty running for 30 minutes. Now the pane shows "Open shell" and a
line saying no shell is running; the terminal is made and a shell started
only on "Open shell", "+ shell" or "Type it". Shells already open still
reattach on load. Failures are still written into the terminal.
