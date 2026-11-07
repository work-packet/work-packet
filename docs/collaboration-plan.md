# Working together: implementation, test and doc plan

Source design: `docs/collaboration.md` (proposal, 2026-11-06). This file is the
tracking document. Update **Status** and the step's checklist as each step
lands, so that a fresh session can pick up from this file alone.

Base: `main` at `c242bfe` (pushed 2026-11-06). That commit carries the
checkpoint, scribe and skills work this plan builds on: `checkpoint.py`,
`scribe.py`, `skills.py` and their tests, `executor.record_step(prepare=)`, and
`schema.IDE_DEFAULTS` `sessions_scribe`/`scribe_idle_s`.

## Status

| Step | What | State |
|---|---|---|
| D | Review decisions (§2) confirmed by the user | done 2026-11-06 (all as proposed) |
| C0 | Spike: project-local hooks in the VS Code extension and the CLI, `Notification` matchers, hook latency, Codex `notify`, WebSocket tab counting | done 2026-11-06 except Codex (see C0 notes) |
| C1 | Derived view (lifecycle, driver, ball), new columns and wording, Parked, Mark done, checkpoint in every state, real actors in the thread | done 2026-11-06 (see C1 notes) |
| C2 | Presence and hooks: `wpk _hook`, `settings.local.json`, interactive `end_turn` = waiting, blocked, presence gate | done 2026-11-06 (see C2 notes) |
| C2b | Opening VS Code claims the project until you hand it back (D15) | done 2026-11-06 (see C2b notes) |
| C3 | New-packet start modes, Open ▾ on every card, hand-off dialog with pre-flight and dirty-tree choice | done 2026-11-06 (see C3 notes) |
| C4 | Desk: typed inbox, In progress, Since you were last here, Timeline, split cost | done 2026-11-06, with gaps (see C4 notes) |
| F1 | Planning fields (`plan:`), now-WIP, priority → class, Backlog, quick capture, rot | done 2026-11-06, with gaps (see F1 notes) |
| C5 | SessionStart briefing, notes into interactive sessions, continue a runner step in VS Code, `/wpk-handoff` and friends | done 2026-11-06, with gaps (see C5 notes) |
| F2 | Daily focus brief (deterministic), end-of-day shutdown | done 2026-11-06, with gaps (see F2 notes) |
| C6 | Push, digest, attention budget, snooze, Inbox triage | done 2026-11-07, with gaps (see C6 notes) |
| C7 | Split / pairing, jobs as workers, learn from corrections, VS Code status bar | done 2026-11-07, with gaps (see C7 notes) |
| F3 | Forecast, at-risk, dates from forges, milestones, weekly review, standup drafts | done 2026-11-07, with gaps (see F3 notes) |
| DOC | User guide, README index, pointers in superseded designs | done 2026-11-07 (see §6 notes) |
| G | Closing the gaps left by C2-F3 (Codex excluded: not available locally) | done 2026-11-07 (G1-G8; see G) |

Notes:
- 2026-11-07: **every step is done.** Where things stand and what comes next
  (use and checks, phone view, M3 GitHub connector, M4 agenda):
  `docs/where-we-stand.md`.
- 2026-11-06: the user confirmed every decision in §2 as proposed, and set a
  rule: **work happens through the dashboard.** Any feature that still needs a
  shell command is recorded in §2a, and every step's checklist includes its dash
  surface.
- 2026-11-06: the checkpoint, scribe and skills work was committed and pushed
  as `c242bfe`. Full suite on that commit alone: 1229 passed, 13 skipped.
- 2026-11-06: plan written from the design plus a code audit (§1). Line
  numbers are as of `c242bfe`. Re-check them before
  each step.
- Order: C0 → C1 → C2 → C3 → C4 → C5, with F1 in parallel once C1 has landed.
  F2 needs C4 and F1. C6 needs C4. C7 and F3 are outlined only, and get their own
  detailed plan once C4 has been used for a while.
- The design leans on two things that **aren't built**: triggers
  (`triggers.md`, design only) and routines (`routines-and-outputs.md`, design
  only). This plan doesn't build them. §5.3 trigger handling becomes a hook for
  whoever builds triggers (the gate and the decision item type are ready). The F2
  brief is built as a plain board job with kept outputs, not as a routine packet
  (see D9).

---

## 1. What exists today (findings)

Paths are under `src/work_packet/` unless shown otherwise.

**State and derivation**
- `views.py` holds `packets`, `relative`, `ps`, `show`, `report_lines` and `log`,
  but no derivation. The column is picked in `dash/data.py:347-351` (`COLUMNS`
  and `COLUMN_OF`, `:22-25`). `actions.resumable` (`actions.py:177`) and
  `executor.stopped/unread` (`:1405/:1410`) are scattered view logic.
- `schema.py`: `STATES` (`:17`); `STATUS_FIELDS` (`:20`) and `STATUS_OPTIONAL`
  (`:29`); `validate_status` (`:317`) requires `reason` for
  PAUSED/NEEDS_INPUT/FAILED. `JOURNAL_TYPES` (`:192`) must list any new record
  type, and records are validated at `:1190`.
- PAUSED reasons are spread around: `SETUP_REASON` (`project.py:118`),
  `TAKE_REASON`/`HELD_REASON` (`executor.py:1261-1262`), `"by hand"`
  (`executor.py:1132`), `"created with --paused"` (`project.py:248`) and
  `pause_reason()` (`executor.py:1237`).
- Setup hold: `project.new` writes PAUSED/setup when there is no prompt
  (`:245-246`). Readers: `cli._setup_guard` (`:774`), `setup.py:318`,
  `check.py:224`, `actions.resumable`, `dash/data.py:380, :523`, `compose()`
  (`:1381-1433`), and `dash/app.py:1403, :1434`. Starters choose it at
  `starters/__init__.py:446-449`.

**Executor**
- `admin()` (`executor.py:1081`): 60 s lease, and pause falls back to
  `request_pause`. Handoff, resume and continue clear the reason at `:1164`. The
  handoff record (`:1171-1189`) is
  `{type, t, by, from, to, batch?, instruction?, …, note?}`, and `defer` goes here.
- Checkpoint: `record_step` refuses at `:946` (lease held → `LEASED`) and at
  `:950` (unfinished step → `NOT_RUNNABLE`).
- There is no verb registry. A new admin verb needs three things: an `actions.py`
  function, a CLI parser (`cli.py:1972-1980`, `:2046`) and a branch in `act()`
  (`dash/app.py:877-916`). The console (`dash/console.py:248-298, 482+`) is a
  fourth, optional place.

**Journal and thread**
- `journal.append/read` (`journal.py:17, :22`) do a linear scan.
- `migrate.rebuild_thread` (`:175`) credits every commit to `RUNNER` (`:260-284`)
  and never reads `decision.worker`. A checkpoint that ends PAUSED writes nothing.

**Scheduler**
- `sched/gates.py`: `fn(it, ctx) -> Reason|None`, in the `GATES` tuple (`:192`).
  `ide_first` is at `:147`. `Ctx` is at `:55` and is built in
  `sched/dispatcher.py:299`.
- **`wpk tick` (`scheduler.tick`, `:101`) bypasses the gates.** The presence check
  must also go into `scheduler.due()` (`:40`), or a cron `wpk tick` will start
  steps under your feet.
- `sched/classes.py`: urgent/high/normal/low/background, with `effective()` and
  `aged()`.

**Dashboard**
- Overview `/`: `data.overview` (`dash/data.py:511-573`) renders in
  `overview.html` (tiles 64-90, attention 97-170, boards 173-190, running 194-205,
  coming 209-221, VS Code sessions 225-229).
- Board: cards are written inline in `board.html:84-137`. Drag-and-drop exists
  only for moving a card to another board (`board.js:50-85`).
- Packet page `packet.html`: Update status is hidden in setup (`:87`). IDE form
  with "Pause and open" (`:70-79`); `ide_open` pauses at `app.py:1131-1139`.
- Tabs (Overview/Tasks/Steps/Cost/Settings/Console) are on the **project** page
  (`_tabs.html`), not the packet page.
- Compose refuses when not `OWNED` (`data.py:1340, :1373-1395`;
  `app.py:1397-1400`) and closes shells on hand-off (`:1445-1449`).
- New packet: `new.html` step 2 checkbox (`:22`); pickers on step 1 (`:58-67`);
  `made()` (`app.py:1294-1303`); `new.js` `finish()` redirects (`:200-215`).
- `data.tasks()` (`:245`) cuts tasks at handoffs that carry an `instruction`.

**IDE sessions and hooks**
- `ide_sessions.claude_feed` maps `end_turn` → `TURN_END` (`:225`), shown as
  "turn finished" (`:992`). `entrypoint` is captured (`:202`) but not used for
  turn state. `sessions/<pid>.json` has a `status` field that is kept but unused
  (`:460-477`).
- The collector covers only wpkd-launched local servers (`local_pass`, `:957`)
  and jobs (`sched/ide_job.py:51-75`). Desktop VS Code and terminal `claude` are
  not covered.
- The web proxy counts WebSockets in memory (`dash/ide.py:938, :957`). Those are
  sockets, not tabs: one tab opens several. The `SHIM` script injection
  (`rewrite_workbench`, `:847`) is the place for a visibility beacon.
- Runner Claude hooks are inline `--settings` JSON (`harness/claude.py:30-44,
  :149`), and the hook scripts are standalone files run by path (`ctxhook.py`,
  `bghook.py`, `pathhook.py`). **No code writes `.claude/settings*.json`.**
  `workspace.exclude()` (`workspace.py:146`) already appends to
  `info/exclude`.
- The packet-folder layout writes no `.code-workspace` (`ide.py:135-144`), so
  terminals there get no `WPK_WPID`.
- `skills.py` installs `/wpk-checkpoint` globally into `~/.claude/skills` and
  `$CODEX_HOME/skills`.
- Notes: `<packet>/mailbox/<id>.json`, seen per step in `steps/NNNN/notes.seen`,
  and removed only at a step commit (`executor.py:176, :905`). There is no seen
  record outside a step.
- In-process attachment: `dash/shells.py:47-56` (`attached`, `detached_at`) and
  studio `Agents.subscribe` (`dash/agent.py:198-206`).

**Not built**: triggers, routines, push or digest or snooze, phone view, a
job → wpkd push channel (S4b), `wpk brief`, hidden CLI subcommands, and dashboard
layout or screenshot tests.

**Tests**: Starlette `TestClient` with substring asserts (`tests/test_dash.py`);
the fake model behaviours are in `tests/fakemodel/behaviors/`. Session fixtures:
`tests/data/ide_sessions/*.jsonl`, and `test_ide_sessions_bind.py` `World`. The
`live` marker is set with `WPK_LIVE=1`. Full suite: `packages/python/bin/pytest
-q`, about 1174 tests in about 7 min.

---

## 2. Decisions (step D, confirmed 2026-11-06)

The design's §15 recommendations, plus decisions this plan needs that the design
leaves open. The user confirmed all of them as proposed.

| # | Decision | Proposed | First needed |
|---|---|---|---|
| D1 (Q1) | Presence defers the runner by default | Yes | C2 |
| D2 (Q2) | Install packet-local hooks by default, `[ide] hooks = false` to turn them off | Yes, announced once per board | C2 |
| D3 (Q3) | Runner COMPLETED on a non-*runner* packet = review, not done | Yes | C1 |
| D4 (Q4) | Presence TTL 10 min; web attachment alone counts for at most 2 h | Yes | C2 |
| D5 (Q5) | "your turn" never pushes | Yes | C6 |
| D6 (Q6) | Write `owner = $USER` now | Yes, on create and on first touch | C1 |
| D7 (Q7-Q12) | Inbox as a column plus a Desk strip; "Hand off…" instead of "Next batch"; own presence kinds; buckets plus rank; brief on Desk, push opt-in; focus score reorders only through class mapping | Yes to all | C4 / F1 / F2 |
| D8 | Where do lifecycle, autonomy and owner live? | `status.md` optional fields (executor-owned, validated). `plan:` goes in the card (person-owned). | C1 |
| D9 | The F2 brief without routines | A deterministic `wpk brief` command, run by the board at the set time, with output kept under `$WPK_HOME/briefs/YYYY-MM-DD.md`. Move it to a routine packet when routines exist. | F2 |
| D10 | `wpk _hook` entry point | A standalone `hookcmd.py` run as `<sys.executable> -m work_packet.hookcmd <event>`, importing only stdlib, `fsutil` and `presence`. Not through `cli.py`, for start-up time and to match the existing hook scripts. `wpk _hook` stays as an alias for manual testing. | C2 |
| D11 | Interactive delivery of a note: does it consume the note? | No. Record `<id> session:<sid> <t>` in a per-packet `mailbox/.seen` file. The runner still gets the note unless a person checkpoint with `--next` follows it. Each consumer sees a note at most once. | C5 |
| D12 | Push channel for C6 | ntfy (URL in config), plus browser notifications from the board tab. Both are opt-in. | C6 |
| D13 | Does the board need column drag (§8.2)? | Yes in C4, as actions with a confirm. C1 ships only the columns. | C4 |
| D15 | Opening VS Code on a packet the runner has | **Claims it** (user, 2026-11-06): the project is paused with reason `claimed` until you explicitly hand it back. Presence stays as the safety net for work the board didn't open. Supersedes C2's "open changes no state". Confirmed (user, 2026-11-06): a claim always comes from a dashboard-linked action; detected work (a terminal `claude`, desktop VS Code opened by hand) never claims on its own. | C2b |
| D14 | Rename "Paused" in the CLI too? | `wpk ps` gets BALL and DRIVER columns; `--raw` shows executor state | C1 |

## 2a. Dash-first: what still needs a command

Work happens through the dashboard. A CLI verb is fine as a second way in, but
nothing a person does day to day may be CLI-only. This table tracks every place
the plan adds or keeps a command, with its dash surface. Keep it current: a step
isn't done while a row it touches says "gap".

| Command | Dash surface | Phase | State |
|---|---|---|---|
| `wpk done` / `reopen` / `drop` | Done/Reopen on the card; Mark done, Drop and Reopen on the packet page's Now line; Done on Overview REVIEW rows; console `/done`, `/drop`, `/reopen` | C1 | built |
| `wpk autonomy …` | Autonomy select on the packet page's Now line (the card shows a chip when not the default) | C1 | built |
| `wpk ps` (BALL, DRIVER) | The board and Desk themselves; CLI-only by nature | C1 | n/a |
| `wpk doctor` hooks report, `wpk hooks install` | Packet page: hooks line with Install/Repair when not installed; board switch under the Overview's Recent VS Code sessions (and on the packet page when hooks are missing) | C2 | built |
| `[ide] hooks`, `presence_ttl`, `idle_escalate` | Board Settings page (C6), and the hooks switch there too | C2/C6 | built |
| `python -m work_packet.hookcmd <event>` | None needed: run by Claude Code, never by a person | C2 | n/a |
| Codex `notify` set-up | **Gap: Codex reads `notify` from its own global config.** Either the board writes it (announced, like the Claude hooks) or Codex sessions stay "probably waiting". Decide after C0. | C2 | open |
| `wpk new --start …` | The New page's start buttons (no CLI flag: the start modes belong to the board) | C3 | built |
| `wpk handoff --after-me` | "After I leave" in Compose and on the packet page's Hand off form | C3 | built |
| `wpk checkpoint` | Already on the packet page (Update status, becoming Checkpoint), plus Draft from session | C1/C5 | exists |
| Continue a runner step (`claude --resume … --fork-session`) | Step page: **Continue this conversation yourself**, with the commands to paste. **Still a copy-and-paste**: one click needs a VS Code extension or terminal API. C7 built the status line and `status.json`, not the extension. | C5 | gap |
| `/wpk-handoff`, `/wpk-note`, `/wpk-done`, `/wpk-todo` skills | Typed inside a Claude session you are already in. Each has a dash equivalent (Compose, note box, Done, capture in F1). | C5 | built (todo waits for F1) |
| `wpk plan --priority … --due …` | Plan ▾ on cards, the packet page and the Backlog (every field); rank typed on the Backlog | F1 | built |
| `wpk todo "…"` | Capture boxes on the Desk, the Backlog and each board's Inbox column | F1 | built |
| `wpk brief` | Built by the board each morning; Desk Today panel; Brief page with Rebuild and earlier days. `[focus] time` is still `config.toml` (Settings page open, §2a) | F2 | built |
| `wpk shutdown` | End of the day page, linked from the Desk after 17:00 | F2 | built |
| `[focus] time`, `focus_wip`, `review_wip`, `[notify] …` | Board Settings page, with **Send a test push** and the browser-notification switch | F1/F2/C6 | built |
| `[[watch]] propose` and the rest of a watcher | **Watchers** on the board's page: Add, Edit (name, repos, labels, dir, every, pr, to the Inbox, held, on), Remove, Poll now (G4) | C6/G4 | built |
| `follow_ups:` (memento) | Written by the runner, never by a person | C6 | n/a |
| `wpk run -- cmd` (jobs) | **Run a command** under Jobs on the project page; the job page. `wpk run` stays for jobs started in your own terminal. | C7a | built |
| `wpk statusline` | Never typed: Claude Code runs it, set by the hooks switch | C7b | n/a |
| `wpk plan --milestone` | Plan ▾ (board cards and the packet page); milestones are added and removed on the board's page | F3d | built |
| Weekly review, standup, status | `/review` (Rebuild, Tidy the backlog), `/standup`, `/status/<board>[/<milestone>]`, Keep a copy; no CLI verb | F3e | built |
| `[focus] review_*`, `[calendar] ics` | Settings page | F3e/F3f | built |
| Live tests and C0 spike scripts | Developer-only; not a user workflow | — | n/a |

---

## 3. Implementation steps

Each step lists its tasks, then its tests (§4 has the shared test plan), then its
docs (§6). Mark each `[x]` when it lands, and add a dated `Notes:` line.

### C0. Spike (de-risks C2)

Goal: confirm the facts in design §4.3, which come only from secondary sources.
Record the results in `docs/collaboration-spike.md` and save sanitized hook
payloads as fixtures in `tests/data/hooks/`.

- [x] Claude CLI in a folder with `.claude/settings.local.json` hooks: check that
  `SessionStart`, `UserPromptSubmit`, `Stop`, `Notification`, `PreCompact` and
  `SessionEnd` fire. Capture each event's stdin JSON (`session_id`,
  `transcript_path`, `cwd`, `hook_event_name`, the `notification_type` or message
  text).
- [x] The same in the **VS Code extension**, both desktop and web (`serve-web`
  through the board). Does it honour project `settings.local.json`? Does
  `Notification` fire for permission prompts in the extension UI?
- [x] `Notification` matcher values: is it `permission_prompt`/`idle_prompt` as a
  matcher, or must we parse the message? What is the idle delay?
- [x] `SessionStart` `additionalContext`: is it accepted from a command hook's
  JSON stdout, and is there a size limit? Does `source` (startup, resume, clear,
  compact) arrive?
- [x] `UserPromptSubmit` `additionalContext` (for note delivery).
- [x] Hook latency (local disk only) budget: measure `python -m work_packet.hookcmd` cold start on
  the shared FS. Target < 150 ms. If slower, plan B is a tiny shell script that
  writes an event file, with the board folding it in.
- [x] Does `sessions/<pid>.json` `status` show `waiting`/`busy`? If it does, it is
  a hook-free fallback for blocked/waiting.
- [ ] **open** Codex: does `notify` fire on turn end in the VS Code extension? Is there any
  approval signal?
- [x] (decided, not measured) Web proxy: one browser tab = how many WebSockets, and with what paths? Can
  we tell a workbench tab apart (management socket path) so we count tabs?
- [x] (decided) Does `document.visibilityState` from the shim survive inside the workbench
  iframe?
- [x] Write the findings, then update design §4.3 if anything differs. Stop and
  ask the user if extension hooks don't work: C2's scope changes.

C0 notes (2026-11-06): results in `docs/collaboration-spike.md`; fixtures in
`tests/data/hooks/`. Hooks work in the CLI and in the extension's SDK mode.
Changes to C2:
- Also hook **PermissionRequest** (fires immediately with `tool_name`; this is
  the blocked signal) and **PostToolUse** (clears blocked after an approval).
  Notification `permission_prompt` follows about 6 s later as a backstop, and
  `idle_prompt` comes 60 s after Stop.
- **Payloads carry prompt, reply and tool text.** `hookcmd` allowlists fields.
- The interactive CLI needs a one-time folder-trust click before project hooks
  run.
- Runner and studio use `--setting-sources ""`, so they don't fire our hooks.
  `hookcmd` also ignores `WPK_STEP`.
- Web tabs are counted by a shim beacon with tab ids, not by sockets.
- Open: Codex project-local hooks (Codex isn't signed in on this host); hook
  latency on an NFS home; a click-through in a real VS Code window (§4.6).

### C1. Derived view, columns, Parked, done (no new data sources)

**C1.1 Model fields**
- [x] `schema.py`: add `lifecycle` (open|done|dropped), `autonomy`
  (manual|handoff|runner), `review` (each|failure|never) and `owner` to
  `STATUS_OPTIONAL` and to `STATUS_FIELDS` order. Validate the values. Add
  `done`, `reopen`, `drop` and `autonomy` to `JOURNAL_TYPES` (or use `admin` with
  `op`, which is preferred because it needs fewer schema changes; decide while
  implementing and note it here).
- [x] Move the PAUSED reason constants into `schema.py` (`REASON_SETUP`,
  `REASON_BY_HAND`, `REASON_STUDIO`, `REASON_HELD`). Leave the old names as
  aliases.
- [x] `owner` defaults to `getpass.getuser()` when it is missing (read side). It
  is written on create.

**C1.2 Derivation in `views.py`**
- [x] `lifecycle(pkt) -> str`: the `lifecycle` field; else `done` if the root is
  COMPLETED and autonomy is `runner` with review `never`; else `open`.
- [x] `driver(pkt, presence=None) -> {who, sessions}`: a live lease → runner. In
  C1, `presence` is always None, so driver is runner|nobody, plus "you" when
  PAUSED studio/by-hand with `taken_by`.
- [x] `ball(pkt) -> Ball(who, kind, reason, since)` per the mapping table in
  design §4.1. Setup becomes `you / not started`; by hand becomes `you / parked`;
  COMPLETED on a non-runner packet becomes `you / review`.
- [x] `column(pkt)`: Inbox, Needs you, Working: you, Working: agent, Waiting,
  Parked, Done. Inbox stays empty until C6, but the column exists.
- [x] (always `handoff` when unset) `autonomy(pkt)` with migration defaults: `handoff`, or `runner` if
  scheduled/sleeping with `wake_at`. Triggers don't exist yet.
- [x] Pure functions over `(status, journal tail, lease, presence)`, so they can
  be unit tested without a run.

**C1.3 Verbs**
- [x] (as `executor.mark`; see notes) `actions.done(pkt, by, note=None)`, `reopen`, `drop`,
  `set_autonomy(pkt, value, review=None)`. Each one writes status plus a journal
  record. `done` on a RUNNABLE packet first pauses the runner (`executor.admin
  pause`) and refuses if a step is live unless `--force`.
- [x] CLI: `wpk done [target] [-m note]`, `wpk reopen`, `wpk drop`,
  `wpk autonomy manual|handoff|runner [--review each|failure|never]`.
- [x] Dash: `act()` branches for `done`, `reopen`, `drop` and `autonomy`. Console
  slash commands for the same.
- [x] (by parking: closing a queued packet pauses it; see notes) Executor: the runner never starts a step on `lifecycle != open`
  (`scheduler.due`, gates `project_hold`, `tick`).

**C1.4 Setup is no longer a state**
- [x] `project.new` without a prompt: `state=PAUSED`, `reason=REASON_SETUP` stays
  **for now** (the executor still needs "don't start"), but views treat it as
  Parked / not started. Only C3 changes creation, together with the start modes.
- [x] Checkpoint is visible in every state: drop the `reason != "setup"`
  condition at `packet.html:87`. In `executor.record_step`, a checkpoint on
  PAUSED/setup keeps the reason (as today).
- [x] An empty `prompt.md` stays a readiness "missing", but readiness shows only
  in the Compose and hand-off pre-flight, not on cards or the Overview attention
  list (`data.py:380, :523`; `board.html:94, 109-114`; `overview.html:145`).

**C1.5 Board, overview and CLI**
- [x] `data.COLUMNS`/`COLUMN_OF` are replaced by `views.column`. `data.card` gains
  `ball`, `driver`, `lifecycle` and `autonomy`.
- [x] `board.html`: new columns; an autonomy chip and a driver dot on the card; a
  Done button on the card; wording per design §8.5 (Parked, Checkpoint, Last
  activity, In progress).
- [x] `overview.html`: attention kinds come from `ball`. "setup" is gone, and
  "review" is added for COMPLETED non-runner packets. The Running tile becomes
  "In progress".
- [x] (no separate filter: the Done column) Done packets leave the active views. Add a "Done" filter, plus a reopen
  link on the packet page.
- [x] (BALL only; no DRIVER column) `wpk ps`: BALL and DRIVER columns; `--raw` shows today's STATE (D14).
- [x] `packet.html`: a small **Now** line (driver, ball, autonomy) above the
  state chips. The full Now panel is C4.

**C1.6 Thread actors**
- [x] `migrate.rebuild_thread`: read `step-start.worker` /
  `decision.worker`. Credit `session` as *you (VS Code)*, `studio` as *you
  (studio)*, `scribe` as *scribe (draft)*, and `agent` as *runner*. A commit that
  ends PAUSED with a by-hand worker writes a `note` entry carrying the summary
  line.
- [x] Credit `done`, `reopen` and `drop` records to `by`.

**C1 tests**
- `tests/test_views_derive.py` (new): a table-driven test over every row of the
  design §4.1 mapping (executor state × reason × lease × autonomy) for
  `lifecycle`, `driver`, `ball` and `column`. Pure; build status dicts directly.
- `tests/test_actions_done.py` (new): done, reopen and drop round trip on a fake
  run. Done on RUNNABLE pauses first. Done with a live lease refuses. Journal
  records validate. The runner skips done packets in `due()` and `tick`.
- `tests/test_schema.py`: the new fields validate, and bad values are rejected.
- `tests/test_migrate.py`: thread actors for session, studio and scribe
  checkpoints; a PAUSED checkpoint makes a note entry.
- `tests/test_dash.py` (extend the `tree` fixture): board columns render with the
  new names. A setup packet shows in Parked, not with "Setting up". The Done
  button POST → 303 ok, and the packet leaves the board. Update status (now
  Checkpoint) is present on a setup packet.
- `tests/test_cli.py`: the `ps` columns, plus `--raw`.
- Regression: the full suite. Expect churn in `test_dash.py` and `test_setup.py`
  from the wording changes; update the assertions instead of keeping the old
  strings.

C1 notes (2026-11-06), what was built and where it differs from the plan above:
- **Fields**: `lifecycle`, `autonomy`, `review` and `owner` are optional in
  `status.md` (`schema.STATUS_FIELDS`, validated). `schema.REASON_*` hold the
  PAUSED reasons; `project.SETUP_REASON` and `executor.TAKE_REASON`/`HELD_REASON`
  alias them. `project.new` writes `lifecycle: open`, `owner` (`packet.user()`)
  and `autonomy` (`handoff` with an instruction, `manual` without). Documented
  in `docs/spec.md`.
- **Journal**: no new record types. Done, drop, reopen and autonomy are `admin`
  records with that `op` (plus `note`, `autonomy`, `review`). A hand-off of a
  closed packet records `reopened`.
- **Verbs**: in `executor.mark()`, not `actions.py`, next to `admin()`. It takes
  the lease. Closing a RUNNABLE or SLEEPING packet parks it (PAUSED, reason
  `done`), so `due()`, `tick` and the dispatcher need no new check. While a step
  runs, it refuses with `LEASED` and changes nothing; this applies to autonomy too.
  Every hand-off, resume or continue writes `lifecycle: open`.
- **Surfaces**: CLI `wpk done|drop|reopen [target] [-m]`, `wpk autonomy MODE
  [target] [--review]`, `wpk ps --raw`. Dash `act()` actions done, drop,
  reopen and autonomy (`back=/…` returns to a board). Console `/done`, `/drop`,
  `/reopen`. The card has Done/Reopen (`_pause.html` `mark`). The packet page's
  **Now** line has driver, ball, autonomy select, Mark done, Drop and Reopen.
- **Decision taken while building (review vs. seen)**: a COMPLETED, open packet
  is a **review** (Needs you) only until someone looks at it (the existing
  `seen` marker, `overview-recent.md`). After that it is **Parked**, "finished;
  mark it done or hand it more". This keeps the Overview's seen and clear-all
  flow, and a person still decides done. Overview rows say **REVIEW** (with a
  Done button) for open packets, and **DONE** only for legacy ones.
- **Legacy**: COMPLETED with no `lifecycle` derives as done, as the old Done
  column showed it. Other states derive from today's fields, and nothing is
  rewritten until touched.
- **Setup**: creation without an instruction is still PAUSED/setup internally
  (C3 changes creation). The card says "not started" in Parked and opens
  Compose. Readiness counts left the card and the attention list, but Compose
  still shows them.
- **Not done in C1**: "Pause and open" stays until the presence gate (C2).
  There is no separate Done filter: the board's Done column and the packet page's
  Reopen cover it.
- **Tests**: new `tests/test_views_derive.py` (table over §4.1, schema fields)
  and `tests/test_mark.py` (verbs, runner leaves closed packets, hand-off
  reopens, lease refusal, CLI, thread actors), plus a console test. Updated
  `test_dash.py` (columns, ball kinds, done/reopen round trip), `test_setup.py`,
  `test_seen.py` (REVIEW), `test_projects.py` (`ps`), `test_report.py` and
  `test_dash_tasks.py` (wording).
- **Docs**: `docs/collaboration-guide.md` (C1 part), README index,
  `product.md` principle 2, superseded pointers in seven designs,
  `session-checkpoint.md` status, `spec.md` fields and admin ops.

### C2. Presence and hooks

**C2.1 `presence.py` (new)**
- [x] Record path `<packet>/.work-packet/presence/<source-id>.json`, using
  `layout.DOT` and the packet's run dir from `packet.py`. Write it atomically
  (`fsutil`). Fields as in design §4.2, with no content.
- [x] `beat(pkt_dir, source, **fields)`, `end(...)`, and
  `read(pkt_dir, now) -> [Presence]`, which drops expired records (TTL from
  `[ide] presence_ttl`, default 600 s) and deletes ended ones older than a day.
- [x] (`attended`, `live`, `records`; no `turns`) `attended(pkt) -> bool`; `turns(pkt) -> [(source, turn, since)]`.
- [x] The web-attachment-only cap (D4): attached with no hook beat or edit for
  2 h → not attended, and the ball becomes `stale`.

**C2.2 Hook installation**
- [x] `hooks_install.py` (or a section in `presence.py`):
  `install(folder, *, git)` merges into `<folder>/.claude/settings.local.json`.
  - Parse the existing JSON. Add our entries under `hooks.<Event>`, tagged with a
    marker (`"wpk": 1` in the hook object, or a command path containing
    `work_packet.hookcmd`). Replace only our own entries and never touch others.
    Write it atomically.
  - Command: `<sys.executable> -m work_packet.hookcmd <event>`. Use the absolute
    interpreter, as `harness/claude.py` does.
  - In a git clone, `workspace.exclude(folder, [".claude/settings.local.json"])`.
- [x] Call it from `ide.resolve` next to `skills.install()` (`ide.py:104`), from
  `project.new` when `[ide] hooks` is on, and from `wpk doctor --fix`.
- [x] `uninstall(folder)` removes only our entries (for `[ide] hooks = false`).
- [x] `wpk doctor` reports "hooks: installed / modified / off" and lists what we
  added.
- [ ] **changed**: the switch's own text is the announcement, no banner. Announce once per board: a dismissible banner on the first install, with
  the dismissal recorded in the board config.
- [ ] **not needed**: the hook finds the packet from its cwd. Packet-folder layout: also write `.vscode/packet.code-workspace` (or a
  `.vscode/settings.json` merge with `terminal.integrated.env.linux`), so that
  terminals there get `WPK_WPID`. Fixes the gap at `ide.py:135-144`.

**C2.3 `hookcmd.py` (new, fast path)**
- [x] Read the hook JSON on stdin. Find the packet from `WPK_WPID`/`WPK_PACKET`,
  or else walk up from `cwd` to the packet dir (this must work in desktop VS Code
  with no env).
- [x] Events → presence and journal:
  - `SessionStart`: presence `working`; journal `session-start` with actor
    `{kind, via, session}`, where `via` comes from `CLAUDE_CODE_ENTRYPOINT` and
    `WPK_IDE_LAUNCH`. Returns no `additionalContext` until C5.
  - `UserPromptSubmit`: turn `working`.
  - `Notification`: `permission_prompt` → `blocked` (with the tool name if the
    payload has it); `idle_prompt` → `waiting` (confirmed).
  - `Stop`: `waiting`, and `turn_since=now`.
  - `SessionEnd`: `ended`, and journal `session-end`.
  - `PreCompact`: beat only; C5 adds the checkpoint prompt.
- [x] Never fail the session: catch everything, always exit 0, write errors to
  `$WPK_HOME/logs/hook.log` (rate-limited).
- [x] `journal.append` from a hook: journal writes are not under the step lease
  today. Confirm that appending a small record concurrently with a running step
  is safe (`O_APPEND`, a single `write` under PIPE_BUF). Add a test.
- [ ] **not done** `turn-waiting` journal record only once waiting has lasted
  `idle_escalate`. This is written by the board's pass (C2.6), not by the hook.
- [x] (`session-start`, `session-end` only) Add `session-start`, `session-end` and `turn-waiting` to `JOURNAL_TYPES`.
- [ ] **open** (C0 couldn't verify Codex) Codex (if C0 confirms): `notify` program → `hookcmd codex-notify`, which
  marks `waiting` and is labelled "probably waiting" on the card.

**C2.4 `ide_sessions.py`**
- [x] A session is interactive if `entrypoint` is in
  (`claude-vscode`, `cli`, …), or a presence record names its session id. For
  those, `end_turn` → `WAITING` (label "waiting for you"). Runner steps keep
  FINISHED.
- [x] If a presence record exists for the session, its turn state wins over the
  transcript.
- [ ] **not done** (turn states yes; tokens no) Desktop and terminal sessions: once hooks write presence plus
  `session-start` with `transcript_path`, the collector can read usage from that
  transcript (attribution level `hook`). Add a `hook` attribution level next to
  confirmed/workspace.

**C2.5 Web proxy attachment and visibility**
- [x] (by the beacon's tab ids, not `proxy_ws`) `dash/ide.py proxy_ws`: count tabs, not sockets (using C0's rule), and keep
  a per-server set of attached tabs. Write a presence record with `kind=ide-web`
  and `attached=true` for each packet opened in that server (`opens.jsonl`).
  Beat it every minute while attached, and end it on the last detach.
- [x] Beacon: extend `ide_forward.js`, or add a second shim, to POST
  `/ide/<key>/__wpk/vis` on `visibilitychange` (a tab id plus the visible flag).
  Store it in the same presence record (`visible`).

**C2.6 Board pass**
- [x] (dead pids reaped; no turn-waiting records) In `dash/runner.py`, a presence pass every `sessions_poll_s`. Expire
  records, check that hook-recorded pids are alive, and write `turn-waiting`
  journal records past `idle_escalate`. Shells and studio write presence on
  attach and detach (`kind=shell`/`studio`).

**C2.7 Scheduler gate**
- [x] `sched/gates.py`: a `presence_defers` gate after `project_hold`. It returns
  `Reason("present", "you're working on it", clears_at=None)` when
  `presence.attended(pkt)` and the newest handoff has no `defer: false`.
- [ ] **not needed**: the gate reads it per item. Put `attended` on `Ctx` (computed once per pass).
- [ ] **not needed**: `tick` goes through the gates. Do the same check in `scheduler.due()` so `wpk tick` respects it.
- [x] (default False: a go-ahead made now; `--after-me` is True) `executor.admin handoff` takes a `defer` argument (default True) and writes
  it in the handoff record. `defer: false` is used by "hand off while present"
  (C3/C5).
- [x] `ide_open` (`app.py:1131-1139`): stop pausing. "Pause and open" becomes
  "Open". Keep `pause=1` working for old links, but drop the checkbox.

**C2 tests**
- `tests/test_presence.py`: beat, read and expire; the TTL; the attachment-only
  2 h cap (with `WPK_NOW`); ended cleanup; atomic writes under concurrency.
- `tests/test_hooks_install.py`: merge into an empty file, into a file with the
  user's hooks (preserved byte-for-byte in meaning), and re-install
  (idempotent). Uninstall leaves the user's hooks. `info/exclude` is updated in a
  clone, and nothing happens in a plain folder (memory: packets are not
  git-bound). A malformed user JSON is left untouched with a warning.
- `tests/test_hookcmd.py`: replay each fixture in `tests/data/hooks/*.json`
  (from C0) through `hookcmd.main(stdin)`, and assert on presence and journal.
  Locate the packet from cwd with no env. Garbage stdin → exit 0 plus a log
  line. **No prompt text in any file written**: reuse the `SENTINEL-*` pattern
  from the session fixtures.
- `tests/test_ide_sessions.py`: interactive `end_turn` → waiting; a runner step
  `end_turn` → finished; a presence turn state overrides.
- `tests/test_sched_dispatch.py` and `tests/test_tick.py`: an attended packet is
  not started by the dispatcher or by `tick`; `defer:false` starts it; a running
  step is not stopped by presence.
- `tests/test_ide.py`: tab counting with `fake_ide.py`, and the beacon route.
  `ide_open` no longer pauses.
- Live (`WPK_LIVE=1`, sonnet per memory `real-model-tests-sonnet`; haiku is
  fine for plumbing): `tests/test_hooks_live.py` runs a real `claude -p` in a
  packet folder with installed hooks. Assert that `SessionStart`, `Stop` and
  `SessionEnd` reach presence and the journal. Permission-prompt coverage is a
  manual check (§4.6).

C2 notes (2026-11-06), what was built and where it differs from the plan above:
- **`presence.py`** (stdlib + fsutil): records in `<project dir>/presence/` (the
  project dir, not per packet; each record names its `wpid`). `beat`, `end`,
  `records(ttl=None for stale-but-open)`, `live`, `attended`, `holds` (the gate's
  rule), `reap` (dead pids on this host), `where` (the card's "you · …" text) and
  `find_project` (walks up from a cwd).
- **Wall-clock time** for presence, the gate and the card, as for leases; not
  `WPK_NOW`. Tests that need a hand-off after presence drop `WPK_NOW`.
- **`hookcmd.py`** is run as `python -m work_packet.hookcmd <event>`. `wpk _hook`
  was not added: it isn't needed, and the module runs directly. Following C0, it
  also handles **PermissionRequest** (blocked + tool) and **PostToolUse** (working
  again). It reads only the allowlisted fields (`KEEP`) and ignores `WPK_STEP`.
  It finds the project from `WPK_PROJECT_DIR`, else by walking up from `cwd`, and
  the packet from `WPK_WPID`, else the root.
- **`sessionhooks.py`** installs, uninstalls, reports status, has a board switch
  (`$WPK_HOME/ide/hooks.json` over `[ide] hooks`, as the scribe's switch works) and
  `apply_all`. Installed by `project.new` (packet folders), `ide.resolve` (code
  folders only: not `state/`, the packet or the project directory), and
  `convert`.
- **No `.vscode` workspace file for the packet layout.** The hook finds the
  packet from its cwd, so writing a workspace file into the user's folder wasn't
  needed.
- **Gate** `presence` sits after `project_hold`. The plan worried that `wpk tick`
  skipped the gates: it doesn't (it runs through the dispatcher), so no `due()`
  change was needed. Go-aheads now carry `defer` (`handoff`, `admin`
  resume/wake). Rule: hold while attended, unless the newest go-ahead is
  `defer: false` and came after presence began. `wpk handoff --after-me` sets
  `defer: true`. The TTL is passed in the sched config as `presence_ttl`.
- **Views**: `driver`, `ball` and `column` take `present`. A person present gives
  driver `you`, column **Working: you**, and ball text "you · VS Code (web) ·
  Claude ×2 (1 blocked)". Present while a step runs gives `you + runner` and a
  risk line on the card. A question or failure stays yours with its own kind.
- **Web tabs**: `dash/ide_presence.js` is injected beside the forward shim (when
  hooks are on). It beats `/ide/<key>/__wpk/vis` with a tab id and visibility, and
  the proxy writes `ide-web-<key>-<tab>` records for the project the server was
  opened for (`ide_launch.packet_of`). WebSocket counting wasn't changed.
- **Desktop**: an open from the board writes an `ide-desktop` record (10 min).
  After that, desktop presence comes only from Claude's hooks. The file-mtime
  activity scan (design §4.2 fallback) is **not built**: by-hand editing in desktop
  VS Code with no Claude session doesn't hold the runner after 10 minutes. It is
  noted as a risk (§5).
- **Shells**: attach beats, typing beats at most once a minute, and detach ends.
  Studio needs nothing new: `taken_by` already makes the driver `you`.
- **`ide_open`**: no pause by default. "Pause and open" remains only for the
  legacy layout, where files open read-only while the runner has them. `pause=1`
  still works.
- **Sessions tables**: an interactive turn's end reads **waiting for you**
  (`ide_sessions.interactive`). Hook-reported turns override the label, including
  "waiting for your permission (Bash)". The hook attribution level for
  desktop/terminal session *tokens* was **deferred to C4** (cost split).
- **Doctor**: a `work.hooks` check (warn when missing or modified, never
  blocking) with fix `wpk hooks install <name>`. New CLI: `wpk hooks
  install|remove|status`.
- **Dash-first**: the hooks switch is under the Overview's Recent VS Code sessions,
  and on a packet page whenever its hooks are not installed, beside
  **Install/Repair**. The once-per-board announcement is the switch's text, not a
  separate banner. `presence_ttl` stays a `config.toml` key (§2a).
- **Not done**: the board pass's `turn-waiting` journal records (they belong with
  attention items in C4). The reaper runs only in the web-sessions loop
  (`[ide] web` on).
- **Tests**: new `test_presence.py`, `test_hooks_install.py`, `test_hookcmd.py`
  (replays `tests/data/hooks`, with a SENTINEL sweep of every file),
  `test_collab_c2.py` (gate, after-me, board card, hooks page, switch, desktop,
  web beacon, doctor, CLI) and live `test_hooks_live.py` (real `claude -p`,
  passed). Updated `test_ide_sessions*.py`, `test_ide.py`, `test_packet_layout.py`
  and `test_studio_tree.py` (`.claude/` in listings).
- **Docs**: guide sections (runner waits, is Claude waiting, the hooks, settings),
  `spec.md` (session records, `defer`), and the `vscode-monitor-plan.md` status
  note.

### C2b. Opening claims it (D15, added 2026-11-06)

The user's rule: "opening a VS Code session on a packet that was runnable is one
path to explicitly claim that packet. The user must explicitly hand it back to the
agent. I don't want agents trying to work under me."

- [x] `schema.REASON_CLAIMED`; `actions.claim(entry, by)` = `pause_project` with
  that reason (a running step finishes first, queued jobs withdrawn). If the runner
  has nothing, it is a no-op that says so.
- [x] Every board VS Code open (`ide_open`: packet page, Open ▾, New's auto-open)
  claims. `wpk ide` claims unless `--look`.
- [x] Hand-back: `admin` resume/handoff/continue on the root also resumes the
  project's other `claimed` packets (`executor._release_claim`). Resume on the
  project gives back claimed packets too (`resumable`). `resume_project` now
  re-reads each packet, since a root's hand-back may already have released it.
- [x] View: PAUSED/claimed gives driver `you`, ball `claimed` ("yours: hand it back
  when you're done"), column **Working: you**.
- [x] "Pause and open" is gone everywhere; the hints say opening takes it.

C2b notes: with a claim, the legacy layout's read-only workspace no longer
applies (the claim makes the owner `you` before the workspace is written).
Reopening a web tab from a bookmark, or desktop VS Code or a terminal opened
outside the board, doesn't claim; presence still holds the runner then. Tests:
new `tests/test_claim.py` (it lasts with no presence, hand-off releases it, a
running step finishes first, the root's hand-back releases children, project
Resume, `wpk ide` claims unless `--look`). `test_ide.py` (`test_board_open_claims_it`,
packet folder). Docs: design §5.1 revision note, the guide's "Opening a packet
makes it yours".

### C3. Start modes, Open ▾, hand-off dialog

**C3.1 New packet**
- [x] (collapsed on step 1 instead) `new.html`: move the harness and model pickers out of step 1 into a
  "Hand to runner → Advanced" section. Step 2 gets three equal buttons: **Open in
  VS Code** (web/desktop, remembered per board in a cookie or board config),
  **Open studio** and **Hand to runner**. Brief stays optional.
- [x] `new_create` takes `start=ide-web|ide-desktop|studio|handoff|none`.
  `starters/__init__.py`: `handoff` → today's `go`. Otherwise create
  open/manual, using `REASON_SETUP` internally (the executor still needs "don't
  start"). Write `autonomy=manual` and `owner`.
- [x] `made()` / `new.js finish()`: per start mode, redirect to the IDE
  (web: `/ide/<key>/`) or show a desktop `vscode://` button panel on the
  progress page (CSP: a click, not a redirect), or go to studio or the packet.
- [x] Hooks and skills are installed before the IDE launches (C2.2).
- [ ] **not done** (dash-first) CLI: `wpk new … --start ide|studio|handoff|none` (default `none`), so it
  matches.

**C3.2 Open ▾**
- [x] A shared partial `_open_menu.html`: web VS Code, desktop VS Code, studio,
  shell. Used on board cards, overview rows, the packet page and the project
  top bar. It posts to the existing `ide_open` and studio routes, without pause.

**C3.3 Hand-off dialog**
- [x] (as Compose, extended) A modal or page `/p/{p}/{wpid}/handoff` with: an instruction (required); a
  "context so far" draft from `checkpoint.last()` or the latest scribe draft,
  editable; harness and model under Advanced; the pre-flight from
  `setup.readiness` (missing items are listed, and "hand off anyway" is
  allowed); and a dirty-tree choice: *commit as WIP* / *include as-is* /
  *split* (disabled until C7, plain folders show only include-as-is); and
  *start now* vs *after I leave* (`defer`).
- [x] The backend calls `executor.admin("handoff", instruction=…, note=context,
  defer=…)`. Commit-as-WIP uses `workspace` helpers and is git-only.
- [ ] **changed**: Compose *is* the hand-off dialog. Compose stays for editing the brief and inputs, but drops the hand-off
  button and links to the dialog. It no longer closes shells on hand-off.
- [ ] **not done** Compose refusal on RUNNABLE: allow editing `prompt.md` and the brief (they
  are not read mid-step). Keep refusing state-file edits.
- [x] (pre-flight uses kept) A one-step `REASON_SETUP` migration: now that start modes exist, a new
  packet with no prompt is still PAUSED internally, but nothing user-visible
  says setup. Remove the remaining `held_for_setup` UI uses; keep the CLI guard
  as the pre-flight.

**C3 tests**
- `tests/test_dash.py`: `/new` POST with each `start` (JSON job flow) → status
  `autonomy=manual`, and the redirect target. The desktop panel has a
  `vscode://` link. The harness picker appears only under hand-off.
- `tests/test_dash_tasks.py`: hand-off dialog with each dirty choice on a git
  packet and a plain packet; `defer` is recorded; pre-flight missing items are
  listed but don't block "anyway".
- `tests/test_starters.py`: start modes produce the right status.
- `tests/test_cli.py`: `wpk new --start`.
- Manual (§4.6): a desktop `vscode://` link opens with hooks active.

C3 notes (2026-11-06), what was built and where it differs from the plan above:
- **New**: step 2's checkbox became **How do you want to start?**: Open in VS
  Code (with a browser/desktop select remembered in `localStorage`), Open studio,
  Hand to runner, Just make it (`start=ide|studio|handoff|none`, `ide=web|desktop`;
  the old `go=1` still means handoff). Hand to runner refuses an empty objective.
  The harness and model stayed on step 1, inside a collapsed **For the runner**
  section: moving them into step 2 would have meant changing how the recipe is
  previewed, for little gain.
- **Landing**: `made(plan, start)` sends you to the packet page. For VS Code or the
  studio it adds `?open=…`, and the packet page then submits the IDE or studio
  form by itself (`#autoopen`, once: the URL is cleaned first, and there is a
  visible fallback button). Desktop lands on the existing `vscode://` page (a
  click, per the CSP). "Just make it" goes to the packet page, not Compose.
- **Not started = manual**: creation without a hand-off is still PAUSED/setup
  internally, with `autonomy: manual`. The **remaining `held_for_setup` uses were
  kept** where they are a pre-flight (CLI guard, Compose's setup mode, the card's
  link to Compose); nothing user-visible says "setup".
- **`wpk new --start`**: not added. `wpk new` makes a packet that has not started;
  the start modes belong to the board (dash-first).
- **Open ▾** (`_open.html`) on every board card: VS Code (browser/desktop), Studio
  (when no step runs), Shell and files. The old card **Open** is now **Page**.
  Not yet on Overview rows (C4's Desk rows will carry it).
- **Hand-off dialog = Compose**, extended rather than replaced (it already had
  the instruction, note, checks and hand-off-anyway): "hand to runner" / "hand
  off" wording; the note is drafted from the status when the last step was a
  person's (`data._by_hand_last`); **Start now / After I leave** (`after=1`, which
  becomes `defer: true`, also via `actions.continue_(defer=)`); uncommitted changes
  get a safe **Commit as WIP** fix (`git add -A && git commit -m 'WIP before
  hand-off'`). Hand-off anyway is the include-as-is choice. Split stays for C7.
- **Shells are no longer closed** on hand-off; the shell's note says the runner
  waits while it is open.
- **Not done**: Compose still refuses edits while RUNNABLE (C3.3's "allow
  editing prompt.md while queued"). It is low value now that presence holds the
  runner, so it is left for later.
- **Tests**: new `tests/test_collab_c3.py` (start buttons, each start mode and its
  landing, hand-off needs an objective, old form, Open ▾ on cards, context draft
  plus after-me through Compose, after-me on the packet page, Commit as WIP).
  Updated `test_dash_tasks.py` (held project lands on its page; hand-off keeps
  shells) and `test_starters.py`.
- **Docs**: guide sections (Starting a packet, Open ▾, Handing off).

### C4. Desk and Timeline

**C4.1 Attention items**
- [x] `views.attention_items(packets, presence, now) -> [Item(type, packet,
  urgency, since, text, actions, source_id)]` for the types question, blocked,
  your turn, review, failure, decision, stale and notify. Rules from design §4.3:
  - blocked escalates after 2 min unless the tab is visible;
  - your turn escalates after `idle_escalate`;
  - items close when their cause clears (they are derived, not stored).
- [x] The only stored item state is snooze/dismiss:
  `$WPK_HOME/attention/<user>.json` `{item_key: {until, until_activity}}`. Keys
  are stable, built from (packet, type, source_id, since).
- [x] (partly: reviews are the unread finished rows; no files-changed or checks payload yet) `review` items: from COMPLETED non-runner packets and task boundaries. The
  payload is files changed (from the handoff `heads` and git diff, or a step
  `changes` list in a plain folder), checks run (from step meta), cost and time.

**C4.2 Desk page (`/`)**
- [x] `data.desk()` replaces `data.overview()`, keeping the old function
  until the template is switched. Sections: Needs you (filter chips),
  In progress (people, agents, jobs), Waiting/scheduled, Since you were last
  here, tiles (Needs you, In progress, Reviews (oldest), Today $ split, Pool),
  and an Inbox strip (empty until C6).
- [x] Inline answer for questions (reuse the existing answer form) and inline
  accept for reviews (`actions.done`).
- [x] Boards become `?board=` filters, and the boards table becomes a filter
  row.

**C4.3 Since you were last here**
- [x] A per-viewer seen marker: `$WPK_HOME/seen/<user>.json` `{packet: t}` plus a
  global `last_visit`. Update it on Desk and packet-page views. This is distinct
  from the existing run-finished `seen` field, which stays as it is.
- [x] `views.timeline(pkt, since=None, kinds=None)`: merge journal records
  (steps, checkpoints, sessions, notes, handoffs, answers, done) into
  `[Event(t, actor, kind, text, link)]`. Desk collapses it per packet.

**C4.4 Packet page**
- [x] A **Now** panel: driver, live sessions with turn states (from presence,
  owner-only per §10), open attention items, autonomy select, Open ▾, Hand off,
  Checkpoint and Done.
- [x] A Timeline section as the default history, with actor and kind filters.
  Steps keeps the runner's detail. On the project page, add a Timeline tab next
  to Steps in `_tabs.html`.
- [ ] **not done** Tasks are also cut at checkpoints with `--next` (`data.tasks()`).

**C4.5 Board columns, drag (D13)**
- [x] Drag between columns: to *Working: agent* opens the hand-off dialog; to
  *Done* marks done (confirm); to *Parked* pauses the runner. Other drops are
  refused. Reuse `board.js` drag code.

**C4.6 Cost split**
- [x] `stats.py`: a session worker class from `ide_sessions` records
  (`total()`/`row()`), keyed by packet. `dash/tokens` and the Cost tab show
  runner / sessions / studio. `sched/budget.ledger()` is unchanged (runner only),
  with a comment saying so.

**C4 tests**
- `tests/test_attention.py`: item derivation per type; the escalation timing
  (`WPK_NOW`); visibility suppression; snooze until a time and until activity;
  auto-close on cause clear.
- `tests/test_timeline.py`: a merged order across actors, `since` filtering, and
  a per-packet collapse.
- `tests/test_dash.py`: the Desk sections render with the fake tree plus
  synthetic presence records; inline answer and accept; the `?board=` filter; the
  Now panel is owner-gated; Timeline is present.
- `tests/test_stats.py`: session tokens appear as their own class; budget totals
  are unchanged.
- `tests/test_dash_tasks.py`: a task cut at a `--next` checkpoint.
- Layout check (new): a fakechrome or simple HTML structure test that Desk has
  no section with a missing anchor. Optional; decide in C4.

C4 notes (2026-11-06), what was built and where it differs from the plan above:
- **Attention**: `attention.py` adds the presence-only items (blocked after 2 min,
  your turn after `[ide] idle_escalate` (900 s), stale after an hour of silence
  while "working"). None is raised while a web tab on the project is visible. The
  board's own items (question, failure, review, stopped, trouble, stalled, stuck)
  stay in `data.overview`, which now orders them by urgency and gives each a
  snooze `key`. **No separate `views.attention_items`**: the board's kinds already
  existed in `data.overview`, so only the new kinds were added, rather than moving
  everything.
- **Snooze**: per person, `$WPK_HOME/attention/<user>.json` `{key: until}`. The
  key includes when the cause began, so anything new un-snoozes it. The choices
  are 1 h, tomorrow 08:00, or until it changes. `POST /attention/snooze`.
- **Desk = the Overview**, reworked in place (no new `data.desk()`): Reviews tile;
  the heading **Needs you** with a snoozed count; board filter tabs (`?board=`);
  **Since you were last here** (`data.since_last`, three events per project, the
  most recently active first); session tokens under Spend today
  (`data.session_spend`, priced when a profile has a price).
- **Visits**: `attention.since` (read-only) and `attention.visit`. The visit is
  recorded by a **POST beacon** from the page (`/attention/visit`), because GET
  routes must change nothing (`test_server.test_get_routes_change_nothing`). A
  visit is a 30-minute sitting.
- **CSP finding**: the board's CSP is `script-src 'self'`, so **inline scripts
  never run**. C3's auto-open, C4's beacon, and the **"Draft from session" button
  from the committed checkpoint work (`c242bfe`)** were all inline. All three now
  live in `dash/page.js`, loaded from `base.html`. `project.html` still has an
  older inline anchor-redirect script (not from this work); it never ran either.
  It is left for a separate fix.
- **Timeline**: `views.timeline(pkt, since, limit)` merges steps (runner),
  checkpoints (person, scribe), failures, hand-offs, done/drop/reopen/autonomy,
  pause/resume/wake, sessions and settings. It is shown on the packet page
  (`#timeline`, 25 then "older") and feeds Since you were last here. **No actor
  filters yet.** No Timeline tab on the project page yet: the packet page has it.
- **Drag between columns** (`board.js`): Done (confirm, then `act done`), Parked
  (`/p/<name>/run op=pause`), Working: agent (goes to Compose). Other drops do
  nothing.
- **Not done in C4** (each is small; carry into C5 or later):
  - tasks cut at checkpoints with `--next` (`data.tasks`);
  - Open ▾ on the Desk's In progress rows;
  - a fuller Now panel listing live sessions (the sessions table is on the page);
  - inline accept on review rows (they have a Done button; the page has answer
    forms);
  - a board Settings page for `presence_ttl` and `idle_escalate` (still
    `config.toml`, §2a);
  - session *tokens* for desktop and terminal sessions (the collector sees only
    web VS Code; the hooks know the transcript path, so a hook-attributed collector
    pass is the next step).
- **Tests**: new `tests/test_collab_c4.py` (session item thresholds, a visible tab
  suppresses them, snooze, visits, timeline actors and order, the Desk with
  blocked, snooze and since-last, board filter, packet timeline, session spend,
  drop targets). `test_collab_c3.py` asserts no inline script. `test_dash.py`
  heading wording.
- **Docs**: guide sections (The Desk, timeline, dragging cards; `idle_escalate`).

### F1. Planning fields (can start after C1)

- [x] (in `planning.py`, through `card.load/save` under the project's lock) `card.py`: read and write the `plan:` front-matter block (priority, rank,
  due, due_kind, estimate, blocked_by, area). Validate it, and preserve unknown
  keys.
- [x] Verbs: `wpk plan <target> --priority now|next|later|someday --due DATE
  --estimate 2d --blocked-by X --area dv`. Dash: one-click priority and due on
  the card (small menus, which work on a phone width).
- [x] The now-WIP (`focus_wip`, default 3): setting a fourth packet to `now`
  returns a "demote which?" prompt (dash) or refuses with a list (CLI) unless
  `--force`.
- [x] `sched/classes.effective()`: when there is no explicit class, map the
  personal priority (now → high, next → normal, later/someday → low). Add a
  `due` boost through `aged()`-style ageing when due is within N days.
- [x] (rank by typing, not drag) Backlog view: `/backlog`, with Parked plus later/someday plus Inbox, sorted
  by priority then rank. Drag sets the rank.
- [x] Quick capture: a one-line form on Desk and `wpk todo "text" [--board]`.
  Creates an Inbox item under `$WPK_HOME/inbox/<id>.json` (not a packet yet), with
  source and link. Accept → New with the text prefilled.
- [x] (`planning.rotting`; on the Backlog's Housekeeping, not yet as Desk stale items) Rot: `views.rot(packets, now)`, using the thresholds from design §9.6. It
  feeds *stale* attention items (low urgency) and the brief's Housekeeping
  section.
- [ ] **not done** Agents never write `plan:`: `pathhook` already protects executor files.
  Add the card's plan block to the guarded set if the card is inside the work
  tree.

**F1 tests**
- `tests/test_card.py`: `plan:` round trip, and unknown keys preserved.
- `tests/test_sched_classes.py`: the mapping, an explicit class wins, the due
  boost.
- `tests/test_plan_fields.py`: the WIP limit and `wpk todo`/Inbox.
- `tests/test_dash.py`: the backlog page, the card priority POST, quick capture.

F1 notes (2026-11-06), what was built and where it differs from the plan above:
- **`planning.py`**: `get`, `validate`, `set_` (card under `livecard._lock`, plus
  an `admin` `op: plan` journal record with the changes), `in_focus` (the
  now-WIP), `sched_class`, `due_text` and `rotting`. The card's own front matter
  wins on rebuild (`migrate.merge_into`), so `plan:` survives. A project without
  a card gets one with just `plan:`, which the rebuild fills in.
- **Scheduler**: `classes.effective` gives the packet override, then the
  project's class, then the plan's class (`"plan"`), then normal. The due boost is
  a fixed 2 days.
- **CLI**: `wpk plan [target] --priority/--rank/--due/--due-kind/--estimate/
  --blocked-by/--area [--force]` (no flags prints the plan). `wpk todo "…" |
  --list | --drop ID`. `[plan] focus_wip` is validated in `config.toml`.
- **Board**: priority chip (when not *next*) and due text on cards; **Plan ▾**
  on cards, the packet page's Now line and Backlog rows (priority buttons, due
  date, hard or soft, into now anyway); the Inbox column lists captures for that
  board, with a capture box, Make packet and Drop.
- **Backlog page** (`/backlog`, side tab): Inbox, then Now/Next/Later/Someday
  (rank, name, chips, blocked by, ball text, Next, column, Plan ▾), then
  Housekeeping (rotting).
- **Desk**: a Focus line (projects in *now*, with due dates) and a capture box
  with the Inbox count.
- **Inbox** (`inbox.py`, `$WPK_HOME/inbox/<id>.json`): `add`/`items`/`get`/
  `drop`. Make packet drops the item and opens New with the text as its objective
  (abandoning New loses it from the Inbox; the text was in the form). Watcher
  issues, requests and agent-proposed follow-ups don't feed it yet (C6).
- **`/wpk-todo`** skill.
- **Not done**: the pathhook guard against agents editing `plan:` (an agent would
  need to edit the card's front matter; low risk); rot as Desk stale items;
  dragging to rank; estimates against actuals (F3); duplicate hints (C6).
- **Tests**: new `tests/test_planning.py` (validation, card round trip through a
  rebuild, the now limit, the class mapping and due boost, texts and rot, CLI,
  board, Backlog, capture, accept). `test_skills.py` covers five skills.
- **Docs**: guide sections (priorities and Backlog, quick capture,
  `focus_wip`).

### C5. Turnover in both directions

- [x] **SessionStart briefing** (`hookcmd` SessionStart): build the briefing with
  `views.briefing(pkt)`: brief, latest checkpoint and next action, open
  questions, runner state, waiting notes, and the card path. Cap it at about
  1.5 KB. Return it as `additionalContext`. Skip it on `source=compact` if C0
  shows it is redundant there. From F2 onwards, add today's focus line.
- [x] **Notes to interactive sessions** (`UserPromptSubmit`): deliver notes not
  yet seen by this session (D11). Record them in `mailbox/.seen`. The card says
  "delivered to Claude in VS Code 14:07".
- [x] **Queued reply as a note** (design §7.8): on Desk, *your turn* / *blocked*
  items get "reply on next prompt", which writes a note addressed to that
  session. Board-hosted shells and studio type it directly.
- [x] (commands to paste; not one click) **Continue a runner step** (§7.3): the review item and the step row get
  "Continue in VS Code", which opens the IDE and runs
  `claude --resume <meta.session> --fork-session` in a new terminal. Use the
  `ide_forward` open link, or show the command line to copy if no terminal API
  is available. "Ask the runner why" is the same with `--permission-mode plan`.
- [x] **Skills**: `skills.py` adds `/wpk-handoff "<instruction>" [--after-me]`,
  `/wpk-note`, `/wpk-done` and `/wpk-todo` next to `/wpk-checkpoint`. Each calls
  the CLI verb with `$WPK_WPID`.
- [x] **Checkpoint during a step** (design §5.5): `executor.record_step` /
  `checkpoint.record` while a step holds the lease writes a `note` journal entry
  (worker session) instead of refusing. It takes no lease and doesn't touch
  status or the memento. `--next` is kept in the note and applied at the next
  step boundary only if no newer checkpoint exists. Update `session-checkpoint.md`.
- [ ] **not done** **PreCompact / SessionEnd**: if no checkpoint since `session-start`, the hook
  returns a short "consider /wpk-checkpoint" context (PreCompact) or, with the
  scribe on, queues a scribe draft (SessionEnd).
- [ ] **not done** **Scribe drafts as proposals**: the card shows "draft checkpoint · accept /
  edit" (accept → a `worker: session` checkpoint from the draft). This already
  mostly exists in `checkpoint.record`; add the UI.

**C5 tests**
- `tests/test_hookcmd.py`: the SessionStart output JSON shape and size cap; the
  briefing content from a fake packet; notes delivered once per session and
  still delivered to the runner.
- `tests/test_checkpoint.py`: a checkpoint during a running step (hold a lease in
  the test) → a note entry, status unchanged; `--next` applied at the boundary.
- `tests/test_skills.py`: the new skills are installed, and an edited skill is
  not overwritten.
- `tests/test_dash.py`: the "Continue in VS Code" command for a step with a
  session id; reply-as-note creation.
- Live: a real `claude -p` in a packet sees the briefing (ask it to repeat the
  packet name) and a queued note (`WPK_LIVE=1`, sonnet).

C5 notes (2026-11-06), what was built and where it differs from the plan above:
- **`briefing.py`**: `briefing(proj, wpid)` (at most 1500 characters: name and id,
  brief from `prompt.md` or the memento, where it stands and as of when, Next,
  the runner's state, notes waiting, the skills). It is skipped on
  `source=compact`. `new_notes(proj, wpid, session)` gives each session the notes
  it hasn't seen, recording `<id> session:<sid> <epoch>` in `mailbox/.seen`. The
  runner still consumes notes at its commit (D11).
- **`hookcmd`** prints `hookSpecificOutput.additionalContext` for SessionStart
  and UserPromptSubmit. The project lookup is factored into `_project`.
- **Live check passed**: a real `claude -p` (haiku) in a packet folder named the
  packet and repeated a note's magic word (`test_hooks_live.py`).
- **Checkpoint during a step**: `checkpoint.during_step` writes a note
  (`notes.add`, which the step's PostToolUse hook delivers) and a `note` journal
  record with `by`; it takes no lease and changes no status. The scribe is still
  refused during a step. Next actions travel in the note text, not through the
  memento (simpler than "applied at the boundary", and the runner reads notes
  anyway). The packet page's Checkpoint form now shows while a step runs, and says
  what will happen.
- **CLI from the folder**: `cli._packet(None | ".")` uses `$WPK_WPID`, else walks
  up from the cwd (`presence.find_project`). This applies to `wpk checkpoint`,
  `done`, `reopen`, `drop`, `autonomy`, and `note .`/`handoff .`. The checkpoint
  skill no longer stops when `WPK_WPID` is unset (desktop VS Code doesn't set it).
- **First hand-off sets the instruction**: `wpk handoff X -m TEXT` on a root held
  for setup with no instruction writes TEXT as the instruction
  (`cli._first_instruction`). This is what `/wpk-handoff` relies on.
- **Skills**: `skills.MORE` adds `wpk-handoff` (`handoff . -m` or `next . -m`,
  plus `--after-me`), `wpk-note` and `wpk-done`. `install()` writes them all, and
  `texts()` lists them. `wpk-todo` waits for F1's Inbox.
- **Continue a runner step**: the step page shows `cd <folder> && claude --resume
  <sid> --fork-session`, and the same with `--permission-mode plan`, for Claude
  steps by the runner. **Not one click**: the board can't open a terminal inside
  VS Code. This is noted in §2a.
- **Reply** on Desk "YOUR TURN" rows posts a note (`act note`), which reaches the
  session with its next prompt.
- **Timeline** shows person `note` records (checkpoints during a step).
- **Not done**: the PreCompact/SessionEnd checkpoint nudge, the scribe-draft
  accept/edit UI on cards.
- **Tests**: new `tests/test_collab_c5.py` (briefing content, notes once per
  session and still for the runner, no briefing after compaction, CLI from a
  subfolder, first hand-off's instruction, step resume commands, Desk reply) and
  a live briefing+note check. Updated `test_checkpoint.py` (during a step it's a
  note) and `test_skills.py` (four skills).
- **Docs**: guide sections (sessions start oriented, skills, picking up a step).

### F2. Focus brief and shutdown (needs C4 and F1)

- [x] `brief.py`: `build(user, now) -> Brief(overnight, needs_you, focus,
  handoff_candidates, housekeeping)`, built from the journal since the last
  brief, attention items, plan fields and rot. The focus score is documented in
  code and in the guide: priority, deadline pressure (due-based only until F3
  adds the forecast), unblocks others (questions gating runner work, weighted by
  queued tasks), then age. Each line carries a `why`.
- [x] (no budget figure yet) Hand-off candidates: packets with a brief, a next action and
  `autonomy != manual`, or ones marked runner-safe. Budget left from
  `sched/budget`.
- [x] (`--day`, `--rebuild`; Markdown always) `wpk brief [--date] [--md]`. The board runs it at `[focus] time` (default
  08:30 weekdays) and writes `$WPK_HOME/briefs/YYYY-MM-DD.md` (D9). Past briefs
  are listed on Desk (history, memory `dashboard-is-central`).
- [x] Desk "Today" strip; the first SessionStart briefing of the day gets one line.
- [x] Feedback: "not today" and "done already" are stored in
  `$WPK_HOME/briefs/feedback.json`. Three ignores raise a stale item, then
  silence.
- [ ] **not done** Optional narration through the scribe model (opt-in): it rephrases only,
  and the order is fixed by the score.
- [x] (offered after 17:00 by clock, not by presence lapsing) Shutdown: `wpk shutdown`, and a Desk button that appears after 17:00 when
  the last presence lapses. It lists open sessions to checkpoint, the night-shift
  candidates (sized to budget and quota) with "hand off all" (`defer: true`), and
  "pick tomorrow's first item" (sets rank 1 in *now*).

**F2 tests**
- `tests/test_brief.py`: golden-file briefs from a synthetic board (fixed
  `WPK_NOW`). Score ordering with reasons; the feedback suppression; no model
  call when narration is off (assert the fake model isn't invoked).
- `tests/test_dash.py`: the Today strip and the brief history list.

F2 notes (2026-11-06):
- **`brief.py`**: `build` (overnight since the previous brief, else 16 h; needs-you
  counts; focus top 3 by `score` with reasons; hand-off candidates are parked
  projects with a Next; housekeeping is rotting projects plus anything suggested
  3 briefs running and untouched), `render` (Markdown), `due`/`maybe_build`
  (weekday, after `[focus] time`, not built today), `say` (not today / done
  already, per day, kept a month), `focus_line`, `shutdown`, `shutdown_hint`.
  Briefs are kept as `$WPK_HOME/briefs/YYYY-MM-DD.json` and `.md`.
- **The board builds it** in the watch loop (`dash/runner.py`), which runs with
  the board's runner. `[focus] time|weekends|off` are validated in config.
- **Desk**: a **Today** panel (focus with reasons, not today / done already, hand
  off before you start) and an End of the day link after 17:00. Pages: `/brief`
  (today's, earlier days, Rebuild), `/brief/<day>`, `/shutdown` (checkpoint
  links, night shift: one form handing ticked projects off with `defer: true`,
  "First tomorrow" = now + rank 1).
- **Sessions**: the SessionStart briefing adds "Today's focus on the board: …".
- **CLI**: `wpk brief [--rebuild] [--day D]`, `wpk shutdown`.
- **Not done**: narration by a model; push/email of the brief (C6); runner budget
  left in the hand-off line; estimates against actuals (F3); feedback shaping the
  score beyond the day.
- **Tests**: new `tests/test_brief.py` (score order and reasons, needs counts, the
  file, not today, the repeat rule, when it is due, CLI, Desk panel, feedback,
  shutdown page and night-shift hand-off with defer, the session's focus line,
  config validation).
- **Docs**: guide sections (the daily focus brief, the end of the day, `[focus]`
  keys).

### C6. Attention delivery (needs C4)

- [x] Push (D12): `notify.py` with ntfy (`[notify] ntfy_url`, `ntfy_token`,
  `link`). Only *blocked* and *question* push, past their threshold
  (`question_after_s`, 300 s; blocked after `attention.BLOCKED_AFTER_S`), not
  snoozed, and not while a web VS Code tab on the project is visible. A daily
  brief push is opt-in (`brief`). The board's watch loop runs `notify.run` each
  minute; it reads nothing without `ntfy_url`. **Changed**: browser
  notifications don't use a WebSocket (the board has none; `live.js` polls the
  page). `dash/notify.js` polls `GET /attention.json` every 30 s, only when you
  turned it on in Settings (per browser), and shows a notification only while
  the tab is hidden, tagged by the item's key so several tabs show it once.
- [x] Rate limit: one push per item (`$WPK_HOME/notify/state.json`), at most
  `max_per_hour` (6); the rest go to the digest.
- [x] Digest: `digest = off | hourly | daily` (`digest_at`). It holds the
  non-push types (review, failure, your turn, decision) and pushes held back by
  the rate limit. Lines whose item closed are dropped.
- [x] Attention budget (§7.6): the Desk's Reviews tile says when it is at or
  over `[plan] review_wip` (default 5); Compose and the packet page's Hand off
  form warn at that point (`data.review_load`, one status read per project).
- [x] Inbox triage:
  - watchers gain `propose = true` (an Inbox item per new issue; accept makes it
    with the watcher's recipe and records it as seen);
  - `follow_ups:` is a memento key (≤ 5 strings, spec §4.2, protocol prompt).
    **Changed**: the executor writes the items as the step commits
    (`executor._follow_ups`), not the board. Ids come from the packet and step,
    so a redone commit is idempotent;
  - requests whose delegate is PAUSED (not started) show with an Open link,
    derived and never stored;
  - captures (F1).
  Actions: accept, drop (decline), **merge** into an open project (a note to its
  root), snooze (Tomorrow).
- [x] Duplicate hint: word overlap (≥ 2 words, ≥ 34% of the smaller set) between
  an item and each open project's name, intent and root instruction. Shown as
  "looks like X: merge instead?", and Merge ▾ preselects X.
- [x] **Added**: the board Settings page (§2a). `settings.py` edits
  `config.toml` line by line (comments kept; a default removes the key; the
  result must parse to what was asked and pass the config checks). It covers
  `[ide] presence_ttl/idle_escalate`, `[focus]`, `[plan] focus_wip/review_wip`
  and `[notify]`, plus a test push, the browser switch and the hooks switch.

**C6 tests**: `tests/test_collab_c6.py` (14): a question pushes once, with its
link; no topic, snoozed, threshold and visible tab hold it; rate limit, then the
hourly digest; a review goes to the daily digest only; `post` against a fake ntfy
HTTP server (headers, token, error); Settings line edit keeps comments, save
validates and removes defaults, the page saves and refuses; `/attention.json`;
the review budget on Compose and the Desk; follow-ups from a memento (fake
`proposer` behaviour) and idempotent ids; bad `follow_ups` refused; snooze,
merge (the note is queued) and the duplicate hint; a proposing watcher (fake
forge) and the board's Inbox column.

**C6 notes** (2026-11-07):

- Not done: "snooze until new activity" for Inbox items (only Tomorrow);
  declining a *request* from the Inbox (Open the project and Drop it there);
  an attention budget for the runner's own work (only reviews are counted);
  ntfy action buttons (answer from the phone) — §7.8 one-line replies stay
  for C7.
- The ntfy token is stored in `config.toml` in plain text, like the forge
  tokens. The Settings page never shows it back.
- A push's link needs `[notify] link`: the board doesn't know its own public
  address.
- Manual check still to do: a real ntfy topic on a phone (§4.6).

### C7. Concurrency and jobs (detailed 2026-11-07)

Designs: `collaboration.md` W4, W6, W7, §5.2, §5.4, §7.7, §7.10, §12;
`work-sessions.md` stages 1-4; `packet-ux.md` U3; `vscode-extension.md`. Found
in code (2026-11-07): none of it exists. There is no `job-*` record, no
`wpk run`, no *external* ball, no split and no diff of `work/` repos.
`skills.py` only installs the fixed `wpk-*` skills, and the extension has no
code. What there is: `workspace.add_worktree`, `dirty`, `git_trees`,
`/attention.json`, presence records, and `agent.md` (project notes that go
into every step's prompt).

C7 is built in five slices, each usable on its own:

**C7a. Jobs as workers** (W7; `work-sessions.md` stage 2's record, minus the
OSC marks).
- [x] `jobs.py`: `start(proj, cmd, cwd)` and `end(...)`. A job is
  `<project>/jobs/<id>/job.json` (`id, cmd, cwd, host, pid, by, start, end,
  exit`) plus `log` (the output, teed). The root packet's journal gets
  `job-start` and `job-end`. `live(proj)` returns running jobs; a job whose pid
  is gone on this host with no end counts as **lost**. `recent(proj)` returns
  finished ones.
- [x] `wpk run [--name N] -- cmd…`: finds the project from the cwd (as the
  hooks do), runs the command with its output teed to the log, records the job
  and exits with the command's status. Outside a packet it just runs the
  command.
- [x] `views.ball(..., jobs=)`: a running job and nobody on it gives
  `who: external`, kind `external`, text "waiting on make sim, 1h12m". The card
  sits in **Waiting**. A job never hides a question or a failure.
- [x] Attention: a failed or lost job that you haven't seen is a `failed`
  item ("make sim failed (exit 2)"). A finished job you haven't seen is a
  `done` item, which goes to the digest and never pushes. Opening the job page
  marks it seen.
- [x] Dash: a **Jobs** panel on the project page (running and recent) and
  `GET /p/<name>/jobs/<id>` (the command, times, exit, the log tail, polled
  while it runs). **Run a command** (`POST /p/<name>/jobs`, owner only)
  starts `wpk run` detached in the packet folder. A job started in a terminal
  shows up the same way.
- [x] Tests: start and end records, exit status passthrough, the lost
  detector, ball and column, attention items, the run form, seen.
- Out of scope (gap): OSC marks from the rc hook (stage 2 proper), never reap a
  session with a foreground job (stage 1), `WPK_PROGRESS` (stage 3).

**C7b. Status at a glance** (§7.10).
- [x] `GET /p/<name>/status.json`: `{name, ball, driver, column, needs: n,
  jobs: n, url}`. A read only; an extension or a status line polls it.
- [x] `wpk statusline`: Claude Code's `statusLine` command. It reads the event
  JSON (`cwd`), finds the packet from local files and prints one line, e.g.
  `wpk uart-fix · yours · 2 need you`. It must be fast and never fail.
- [x] The hooks switch also sets `statusLine` in the folder's
  `.claude/settings.local.json`, and only if the folder has none of its own.
  Turning hooks off removes ours.
- [x] Tests: the JSON, the line for each ball, never replacing your own
  status line.
- Out of scope (gap): the VS Code extension itself (`vscode-extension.md` E1).
- Notes (2026-11-07, C7a and C7b done):
  - Files: `jobs.py`, `statusline.py`, `views.ball(jobs=)` and the *external*
    kind, `views.span`, `data.job_state` and `glance`, the Desk's JOB rows,
    `notify.items` (a job is a failure or a review: never pushed),
    `templates/job.html`, the Jobs panel on the project page,
    `cli.py run`/`statusline`, and `sessionhooks` `statusLine`.
  - Tests: `tests/test_collab_c7.py`.
  - A job is timed by the wall clock, like presence. `WPK_NOW` doesn't move it.
  - `wpk run` pipes the command's output, so the command doesn't see a
    terminal: programs that colour only on a tty lose their colour (gap).
  - Opening an ended job's page marks it seen (owner only), as opening a
    finished project reviews it.
  - The status line's command is `python -m work_packet.statusline`, not `wpk
    statusline`, so it doesn't load the whole CLI after every turn.
  - "Yours" means a status line in `~/.claude/settings.json` or the folder's
    `.claude/settings.json`. Ours goes in `settings.local.json`, which would
    hide either of those.

**C7c. Learn from corrections** (§7.7).
- [x] `learn.py`: collects your notes (`mailbox/`, consumed and queued) and
  your answers (journal `admin` answers) across the board's projects.
  - It groups near-duplicates (the word overlap of `inbox.similar`, stricter).
  - A group seen 3+ times, or in 2+ projects, and not yet promoted or
    dismissed, is a **proposal**: "You have said this 3 times: …".
- [x] Proposals reach the Inbox with source `learn`, via the board loop once
  an hour.
  - **Keep it** shows a form with the rule's text, which you can edit, and
    writes it under `## Learned` in each project's `agent.md`, so every later
    step gets it.
  - **Drop** remembers the group's key, so it won't propose it again.
- [x] Tests: the grouping, the thresholds, the agent.md append (comments and
  text above it kept), the step prompt carries it, and a dropped group stays
  dropped.
- Change from the outline: it goes to `agent.md`, not `skills.py`. A step
  always reads `agent.md`, whereas a skill is only loaded when the model picks
  it. Skills for interactive sessions are a gap.
- Notes (2026-11-07, C7c done):
  - Files: `learn.py`, the board loop's learn pass (`dash/runner.py`), the
    Inbox row's **Keep it…** (`_inbox.html`), `templates/learn.html`, and
    `GET`/`POST /learn/<id>`.
  - What counts: queued and committed notes, plus the `note` and `answers` on
    `admin` and `handoff` records. Anything with fewer than 3 content words
    is left out, so "yes" and "B" never count.
  - Grouping: at least 3 shared words, covering 60% of the shorter text. A
    group's key is the hash of its oldest member's id, and the Inbox item's id
    is that key, so a proposal is made once.
  - Drop is the Inbox's own: proposed means it's never proposed again.
  - A cross-project rule is checked for every project it came up in, and you
    can tick others.

**C7d. Split** (W4, W6, §5.4; `packet-ux.md` U3). Only for a packet-layout
project whose folder is a git checkout.
- [x] `split.py`:
  - `make(entry, text)` creates a worktree of your folder at
    `$WPK_HOME/splits/<name>-split`, on branch `wpk/<name>-split` from your
    `HEAD`. Uncommitted edits stay with you.
  - It makes a packet-layout project there (`project.new(packet=True)`) with
    the hand-off text as its prompt, `autonomy: handoff`, and `split.json`
    (`of, base, branch`).
  - So the runner works beside you, never in your folder (D15).
- [x] `diff(split)`: the split's commits since `base`, plus what it changed
  and hasn't committed (untracked files listed). It's a read only.
- [x] `land(split)`:
  - it commits what the split left uncommitted (in the split's worktree);
  - then merges the branch into your folder (`--ff-only` when your `HEAD` is
    still `base`, else a merge commit);
  - git refuses when your own edits would be overwritten, and the board says
    so;
  - then the split is marked done.
- [x] Dash:
  - the hand-off page has **Split: the runner works in a copy** next to Hand
    off, when allowed (git, packet layout);
  - a Split panel on both projects (base, branch, state, files changed, the
    diff) with **Bring it in** and **Drop the split**;
  - the dirty-tree check offers split as its third choice (W4).
- [x] Tests: make (your edits stay put), diff, land with fast-forward and with
  a merge, land refused over your edits, drop, the page.
- Out of scope (gap): plain folders (copy in, copy out); legacy `work/`
  clones; "land after I commit" waiting; removing the split's folder.
- Notes (2026-11-07, C7d done):
  - Files: `split.py`, Compose's **Split** button (also offered beside the
    dirty-tree check), the Split panel on the project page, and `POST
    /p/<name>/split` (`op=land|drop`).
  - The split is a project of its own (`<name>-split`, packet layout in the
    worktree), so the board, review, attention, jobs and VS Code all work
    on it unchanged. The original's journal gets a `split` record.
  - Change from the plan: to bring a split in, it has to be stopped (not
    RUNNABLE or SLEEPING) and still open. A second landing is refused.
  - The worktree starts from `HEAD`: untracked tools (`packages/`, a venv)
    are not in it (gap; `workspace.link_shares` could link them, as it does
    for `work/` clones).
  - A split's card doesn't point back to the original on the board, only on
    the project pages (gap).

**C7e. Distributed presence (doc only, the "action now").**
- [x] `vscode-monitor-plan.md` S4b: presence records travel over the push
  channel too (`POST /ide/sessions/push` with `kind: presence`, the same token
  and size cap). This is so S4b isn't retrofitted.

Order: C7e, C7a, C7b, C7c, C7d.

### F3. Deadlines and reporting (detailed 2026-11-07)

Designs: `collaboration.md` §9.1 (Time, Deadlines), §9.3, §9.4 (the forecast in
the brief), §9.5 (weekly review, standup, calendar), §9.6 (estimates against
actuals). Found in code (2026-11-07):
- Step durations exist per step (`stats.packet_steps`, `meta.json`
  `duration_s`). Tasks with start and end come from the journal
  (`history._tasks_and_questions`), and so do questions with asked and
  answered times.
- The remaining plan is `state/outline.md` (`dash/plan.count`).
- **Not there:**
  - Presence keeps only live heartbeats, so there is no record of your time.
  - Nothing reads the `estimate` field ("2d"), and nothing produces a forecast
    or an at-risk item.
  - Forges read no milestones, due dates or review requests.
  - Boards have no milestones. `boards/<name>.toml` allows only name, created,
    title and watch, and `main` has no file.
  - There are no reports and no calendar.

F3 is built in six slices, each usable on its own. **Everything is
deterministic: no model call** (narration stays a gap, as in F2).

**F3a. Your time, and estimates against actuals** (§9.1 Time, §9.6)
- [x] `timelog.py`: a per-project ledger, `<project>/time/<YYYY-MM-DD>.json`
  `{"by": {user: seconds}, "last": {user: t}}`.
  - `presence.beat` adds the time since that user's last beat on the project,
    when that beat is within `GAP_S` (300). This is counted per user, not per
    source, so two sessions open at once count once.
  - Beats that only say a tab is attached (`idle_since` set, or
    `active: false`) and `ended` beats don't count.
  - It is stdlib only, because it runs in the hook.
  - Readers: `spent(proj, since, until)` gives `{user: s}`, and `days(proj)`
    gives the days with time.
- [x] `planning.estimate_hours("2d")` gives 16. The scale is 1d = 8h and
  1w = 5d; it is documented in the guide.
- [x] `actuals(entry)`:
  - your time (ledger) and the runner's time (step `duration_s`);
  - the working days since the first activity, for "3.5d so far";
  - `over`, true when the elapsed working days pass the estimate.
- [x] Dash:
  - the project page's plan line: "estimate 2d · so far 3.5 working days: you
    5h, the runner 2h";
  - the brief's Housekeeping: "You estimated spi-boot at 2d; 3.5d so far",
    for open projects whose actuals pass the estimate.

**F3b. Forecast and at risk** (§9.3)
- [x] `forecast.py`, `forecast(entry, card, now)`. It returns `{"low", "high"}`
  as epoch times, plus `runner` and `yours` (seconds), and `why` (the parts in
  words), or None when nothing is known.
  - **The runner's share**: the fraction of the current outline still to do,
    times this project's task wall time (the 25th to 75th percentile of its
    `_tasks_and_questions` tasks). With no history, the board's tasks are used.
  - **Your share**: each item that needs you (question, review, failure, or
    "yours" when you are working on it) times your answer time (the 25th to
    75th percentile of questions, asked to answered, across the board). When
    you have set an estimate and history shows your pace (ledger hours per
    working day on the project, last 14 days), the hours left on the estimate
    divided by that pace are used instead.
  - With neither, there is no forecast. A range, never one date.
  - Computed only for cards with a due date (their own, or a milestone's), so
    the board doesn't read every journal. The board-wide distributions are
    cached for 10 minutes.
- [x] `at_risk(plan, fc, card, today)` gives a reason or None:
  - the forecast's high passes `due`;
  - `due` is within 2 days and the ball has been yours for more than a day;
  - `due` is within 7 days and `blocked_by` names something that isn't done.
- [x] The card:
  - `forecast`, `at_risk` and `due_eff` (its own due, else the milestone's,
    soft);
  - an **at risk** chip on the card and the project page, giving the reason
    and the range.
- [x] Attention:
  - an `atrisk` item on the Desk (a decision: never pushed, in the digest),
    keyed by due and reason;
  - its text, e.g. "fifo-cov due Fri: 2 runner tasks and your review remain;
    forecast Thu-Mon";
  - the buttons **Hand it off now** (Compose), **Move the due date** (Plan ▾)
    and **Open**.
- [x] `brief.score`: an at-risk project gets +100 and the reason "at risk:
  forecast Fri-Mon".

**F3c. Dates from forges** (§9.3)
- [x] `forges._brief` gains `milestone` `{"title", "due"}` for GitHub
  (`milestone.due_on`) and Forgejo (`milestone.due_on`), or None.
- [x] `watch.poll`: for an issue already made into a project (`known` or
  `seen`) whose milestone has a due date, an Inbox item (source `date`):
  - the project has no due date, or a different one;
  - the item is "x: issue milestone *v1.2* is due 2026-12-01", with ref
    `{"date", "project", "due", "from"}`;
  - it is proposed once per project and date (watch state `dates`).
- [x] Inbox: **Use this date** sets `due` (soft) with `planning.set_`, and drops
  the item. Drop is the Inbox's own.
- [ ] **Gap**: PR review requests ("reviews asked of you") need a per-user
  search API. Not built.

**F3d. Board milestones and a burn-down** (§9.3)
- [x] `milestones.py`:
  - `$WPK_HOME/milestones/<board>.json`, a list of `{"name", "title", "date",
    "made"}`. It is kept apart from `boards/<name>.toml` so that `main` can have
    milestones too;
  - `add`, `remove`, `of_board`, `get`.
- [x] A plan field `milestone: <name>`. A project on a milestone inherits its
  date as a soft due, unless it has its own (`planning.effective_due`).
- [x] Snapshots, `$WPK_HOME/milestones/<board>/<name>.jsonl`, one a day, taken
  by the board's loop:
  - `{"day", "runner", "yours", "done", "projects"}`;
  - runner: outline items still to do;
  - yours: items that need you plus projects that are yours;
  - done: projects done.
  - History starts when the milestone is made: there is no backfill.
- [x] The board page, a Milestones panel:
  - each milestone shows its date, its projects (with at-risk chips), the
    latest forecast (the latest high among its projects) against the date, and
    an inline-SVG burn-down of runner and your work, with the ideal line to the
    date;
  - forms: Add (name, date, title) and Remove.
- [x] Plan ▾ gets a milestone choice from the project's board.

**F3e. Weekly review, standup and status drafts** (§9.5)
- [x] `report.py`, `weekly(h, now)`, Monday to now:
  - done by you and by the runner: projects marked done, tasks finished, your
    hours (ledger) and the runner's hours;
  - cost (`stats`);
  - waiting for you for more than a week (Inbox items, items that need you);
  - backlog older than 4 weeks (later and someday, rotting);
  - estimates against actuals;
  - next week's deadlines and milestones, with at-risk flags.
  - It is stored as `$WPK_HOME/reviews/<YYYY-Www>.json` and `.md`, and the
    board's loop builds it on `[focus] review_day` (default fri) after
    `review_time` (default 16:00).
- [x] `standup(h, now)`, for one person:
  - **Yesterday**, your last working day: hand-offs, notes, marked done, your
    time per project, the runner's finished tasks on your projects;
  - **Today**: the brief's focus;
  - **Blocked**: `blocked_by`, and projects waiting on someone else.
- [x] `status(h, board or milestone)`: a row per project (column, whose move,
  done this week, due, forecast, at risk).
- [x] Every report renders as Markdown, kept in `$WPK_HOME/reports/` by day.
  Pages: `/review` (latest; earlier weeks; Rebuild; **Tidy the backlog**, a
  form of checkboxes with keep / someday / drop), `/standup`, `/status/<board>`
  and `/status/<board>/<milestone>`.
  - Each page has a copy box (the Markdown) to paste into chat or mail.
  - Linked from the Desk (Brief panel) and the board page.

**F3f. Calendar fit** (§9.5, later in the design)
- [x] `icsfeed.py`, under `[calendar] ics = "<url or path>"`:
  - the board's loop fetches the feed at most hourly into
    `$WPK_HOME/calendar/feed.ics`;
  - a small parser (VEVENT: DTSTART, DTEND, SUMMARY; UTC `Z`, `TZID` with
    zoneinfo, floating as local; all-day events ignored; no RRULE expansion,
    which is a gap);
  - `today(now)`, `busy(now)`, `next_free(now)`.
- [x] The brief: "Meetings today: 11:00-12:00 Sync" and, before the next one,
  "45 min before 11:00: 2 reviews fit", at 15 min per review or answer.
- [x] Pushes wait while you are in a meeting: `notify` holds the push and
  sends it after the meeting ends. Settings page: the ICS field.

**F3 tests** (`tests/test_collab_f3.py`)
- The ledger: one user, two sources, counted once; gaps; idle beats don't
  count. Estimates; actuals.
- The forecast from a synthetic journal (tasks, questions); a range; none with
  no history; at risk (each of the three reasons); the Desk item; the brief
  score.
- Forge milestone parsing (a fake GitHub JSON); a watch poll proposes a date
  once; Use this date sets the due date.
- Milestones: add and remove; the inherited due date; a snapshot a day; the
  board panel and the SVG; the Plan ▾ milestone.
- Weekly review content, file and page; Tidy the backlog; standup; status per
  board and milestone; the loop builds on the day.
- ICS: parsing (UTC, TZID, all day); busy; the brief lines; a push held during
  a meeting; config validation.

F3 notes (2026-11-07), what was built and where it differs from the plan above:
- **F3a**: `timelog.py`, called from `presence.beat`.
  - A beat that doesn't count (idle, hidden tab, ended) breaks the chain, so the
    next beat starts afresh instead of counting the gap.
  - `planning.estimate_hours`, `working_days`, `actuals` and `actuals_text`.
  - The line is on the packet page's Now line (`id="actuals"`); the project page
    has no plan line. The brief's Housekeeping gets the estimate lines.
- **F3b**: `forecast.py` (`forecast`, `at_risk`, `range_text`,
  `decision_text`), and `data.deadlines` after `data.board`:
  - cards get `due_eff`, `due_kind`, `milestone`, `forecast` and `at_risk`;
  - the Desk gets an `atrisk` row (`data.risk_item`, type decision in
    `notify`), plus a chip on the board and the Backlog, and brief score +100.
  - Parked projects count no item of yours; only questions, reviews,
    failures, blocked sessions and "working: you" do.
  - The card's "due Fri" text still uses the real date (as before F3), while the
    forecast uses the board clock (`WPK_NOW` in tests).
- **F3c**:
  - `forges._milestone`, and `watch.propose_date` called from `poll` for
    issues already made into projects (state `dates`);
  - **Use this date** on the Inbox item. Review requests are not built (gap).
- **F3d**: `milestones.py`, with the plan field `milestone` (`wpk plan
  --milestone`).
  - The board page has a Milestones panel (Add, Remove, Status link, inline-SVG
    burn-down), and Plan ▾ offers the board's milestones on the board and the
    packet page.
  - The daily snapshot is taken by `reviews.tick` in the board's loop.
- **F3e**: `reviews.py` (`weekly`, `standup`, `status`, `tidy`, `keep`,
  `tick`), which uses the board clock.
  - Pages `/review[/<week>]`, `/standup`, `/status/<board>[/<milestone>]`,
    POST `/review/build`, `/review/tidy` (owner only) and `/reports/keep`,
    on the template `rhythm.html`.
  - Linked from the Desk's Today panel, the Brief page and the board's
    Milestones.
  - `[focus] review`, `review_day` and `review_time` are validated, and on the
    Settings page.
- **F3f**: `icsfeed.py` (`[calendar] ics`, validated, on the Settings page).
  - Fetched hourly by `reviews.tick`.
  - Brief section "Today's calendar".
  - `notify.tick(busy=)` holds pushes, the digest and the brief push during a
    meeting.
- **Not done**:
  - PR review requests as dates;
  - RRULE expansion (only the first instance of a repeating event counts);
  - narration by a model;
  - backfilling a milestone's burn-down from before it was made;
  - per-person calibration of the forecast (it pools the board's questions):
    **done in G8**;
  - your share counted in working days (it is wall-clock): **done in G8**.
- **Tests**: new `tests/test_collab_f3.py`, 13 tests:
  - the ledger, estimates against actuals;
  - the forecast and at-risk reasons, at risk on the board, Desk and brief;
  - a forge date to the Inbox and Use this date;
  - milestones and the burn-down;
  - the weekly review and when it's due, standup and status;
  - ICS parsing, the brief and held pushes, config keys.
- **Docs**: guide sections "Deadlines: forecast, at risk and milestones", "The
  weekly review, standup and status" and "Your calendar", plus config rows and
  the time ledger under "What the board writes".

---

### G. Closing the gaps (added 2026-11-07)

The user asked to close the gaps each step left, except Codex (not available
on this host; its §2a row stays open). Ordered by what matters day to day.
Each slice keeps the dash-first rule and adds tests. Out of scope here: the
VS Code extension (`vscode-extension.md` E1), so one-click continue stays a
copy-and-paste; model narration; triggers and routines; split for plain folders.

- [x] **G1. Edits by hand hold the runner** (C2 gap, §5 risk). `presence.edited`
  scans the packet folder's file times. It skips VCS, tool and cache folders,
  `.work-packet`, `.vscode`, `.claude` and the cards, caps at 20,000 entries and
  caches for 60 s. `presence.edits_hold` counts a change only if it is newer
  than the packet's journals, so the runner's own writes and edits made before a
  hand-off don't count, and only within `presence_ttl`. `holds` uses it when no
  presence record is live: "files in it were edited by hand 2 min ago; it starts
  once they are quiet for 10 min, or when you hand it off". It applies only to the
  packet layout (a legacy project opens read-only) and runs only in the
  scheduler's gate, so cards don't scan. Tests: `test_presence.py` (hold,
  quiet, a hand-off since, skipped files, cache, legacy).
- [x] **G2. Tokens for desktop and terminal sessions** (C4 gap). The hook keeps
  the transcript path in the presence record (`transcript`; absolute `.jsonl`
  only, no text). `ide_sessions.hook_pass` runs in the board's sessions loop
  whenever `[ide] sessions` is on, even with web VS Code off. For each Claude
  presence record that isn't `ide-web`, it reads what is new in the transcript
  with the same `scan`, and keeps a session record with attribution `hook`
  (project, wpid, host, client from `via`). A session a launch collector already
  has (confirmed or workspace) is left to it. An ended session gets one last
  read. The record is shown in the sessions tables, with process running/ended
  like a confirmed one, and is counted in Spend today. Tests: `test_collab_g.py`
  (path kept, read and counted once, last read after the end, web sessions
  left alone).
- [x] **G3. Checkpoints from sessions** (C5 gaps).
  - **Nudge**: Claude Code's PreCompact hook can't give the model context, but
    the SessionStart (`source: compact`) that follows can. So
    `hookcmd.compact_nudge` asks the session to suggest `/wpk-checkpoint` when
    the packet has no step since the session's presence `since`. The briefing
    is still not repeated.
  - **SessionEnd**: no new queue. The scribe's `due` now treats an ended `hook`
    session (G2) like an ended confirmed one, so desktop and terminal sessions
    get a draft when they end, with the scribe on.
  - **Proposals**: `checkpoint.draft_of` returns the scribe's draft while it is
    the last checkpoint. `accept_draft` records it again as a `session`
    checkpoint (status, body, next), so the memento moves.
  - **Dash**: action `accept-draft`. The card shows `draft checkpoint · Accept ·
    Edit` (`_pause.html` `draft`). The packet page has a Draft checkpoint panel
    and the Checkpoint form open, with the draft's body filled in.
  - Tests: `test_collab_g.py` (offered on the board and the page, accepted,
    nothing left to accept; the nudge and none after a checkpoint; an ended hook
    session). `test_collab_c5.py`: compaction now gives only the nudge.
- [x] **G4. Watchers on the board** (C6 §2a gap). `watch.save` (add, or
  replace by its old name, keeping keys the form doesn't show) and
  `watch.remove`. Both are checked with `schema.validate_watches` before
  writing, and nothing is written on an error. `boards/main.toml` is made for
  main's first watcher. The board file is rewritten with `save_toml`, so comments
  are lost; it is machine-written already (`new_board`). A file that doesn't
  validate is never rewritten; the page says to fix it by hand. Dash: POST
  `/b/<board>/watch` (`op` save/remove, `was`), and the Watchers section is always
  shown, with Edit per watcher and Add a watcher. Tests: `test_collab_g.py` (add,
  edit with a hidden key kept, rename, bad repos refused, duplicate, remove,
  main's first watcher, unknown board).
- [x] **G5. Desk and board odds and ends** (C2-C4, F1).
  - **Tasks cut at checkpoints**: `data.tasks` starts a task after a by-hand
    checkpoint whose summary has a `Next:` line. A hand-off with an instruction
    straight after it (no step between) renames that task instead of adding an
    empty one.
  - **Open ▾ on the Desk**: on In progress rows (you and running) and on REVIEW
    rows. The `.openmenu` CSS moved from `board.html` to `base.html`.
  - **Review rows**: Done was already there (accept). Added **Next…** (Compose)
    and Open ▾ (take & open), so all of the design §4.3 review buttons are there.
  - **Rot on the Desk**: kind `rot` ("STALE"), only for parked open projects,
    ordered last, keyed by priority and limit. Plan ▾, Hand off…, Open. Not in
    `notify.items`, so never pushed or in the digest.
  - **Compose while queued**: `executor.requeue` changes the memento of a
    RUNNABLE or SLEEPING packet under the lease (refused while a step holds it),
    and writes an `admin` `requeue` record. Compose shows **Save the
    instruction** when the runner has it but nothing is running. State files are
    never edited this way.
  - **`turn-waiting`**: `attention.log_waits`, run by the board's sessions loop.
    One record per wait (presence `waited` = that `turn_since`), stamped
    `turn_since + idle_escalate`. The timeline shows "Claude (VS Code) waited for
    you since 10:02". New fields: presence `waited`, `presence.mark` (no beat).
  - Tests: `test_collab_g.py` (tasks, Desk rows and rot, requeue, waits).
- [x] **G6. Inbox** (C6).
  - **Until it changes**: for an item with a `project`, `inbox.snooze(...,
    change=True)` keeps `change_at`, and `items` shows it again once that
    project's root journal is newer, capped at `CHANGE_MAX_S` (a week). An item
    with no project has nothing to watch, so it gets the time only and no
    button.
  - **Decline a request**: `inbox.decline_request` delivers "Request `x` (…) was
    declined by …: <reason>" to the requester through `requests.deliver`
    (outcome `declined`, so it wakes a waiter), then drops the delegate project
    if it never ran a step. POST `/inbox/request/decline`; Decline ▾ with a
    reason on request rows (board Inbox column and Backlog).
  - Tests: `test_collab_g.py` (change snooze, no-project snooze, decline end to
    end and twice).
- [x] **G7. Split** (C7d).
  - **Back-pointer**: the card has `split_of` (from `split.json`), shown as
    "split of <name>".
  - **Remove its folder**: `split.remove`, only once the split is done or
    dropped. It keeps the journal at `splits/removed/<name>.journal.jsonl`, runs
    `git worktree remove --force` and prune, then `git branch -d` only when
    done (merged). A dropped split keeps its branch. It unregisters the split
    and writes a `split` `op: removed` record on the original, which the
    timeline shows. Dash: `op=remove` on `/p/<split>/split` (owner only), with a
    confirm.
  - **Shares**: `make` links untracked `SHARES` (`packages`, `.venv`, `venv`,
    `node_modules`) and untracked top-level links into the worktree, through
    `workspace.link_shares`, which also excludes them.
  - Still out of scope: plain folders, legacy `work/` clones, "land after I
    commit".
  - Tests: `test_collab_g.py` (links, back-pointer, remove refused while open,
    removed after landing with the branch deleted, dropped keeps its branch).
- [x] **G8. Forecast** (F3).
  - `history._tasks_and_questions` now keeps who answered (`by` of the
    hand-off).
  - `forecast._history` returns `(seconds, who)`. The forecast uses the
    owner's own answer times (the card's root `owner`, without `@host`) when
    there are `OWN_MIN` (5) of them, on the project and then on the board;
    otherwise everyone's, as before. `history()` keeps its old shape.
  - The estimate path lays the days left on working days (`add_working`:
    weekends skipped) instead of scaling by 7/5. Answer times stay wall-clock,
    since they are measured that way.
  - Tests: `test_collab_g.py` (working days across a weekend, own answers
    used at 5 and not for someone with none, the board pool).

## 4. Test plan (shared)

### 4.1 Principles
- Derivation is pure (`views.py`, `attention`, `brief`, `presence.read`) and is
  tested with table-driven unit tests that build status, journal and presence
  dicts directly. That keeps most coverage fast and independent of the fake model.
- Every time-based rule takes `now` and is tested with `WPK_NOW`.
- Privacy: every test that feeds transcripts or hook payloads uses `SENTINEL-*`
  text and asserts that it never appears under `$WPK_HOME` or the packet's
  `.work-packet/` (extend the existing check in `test_ide_sessions.py`).
- No git assumption: every packet-touching test runs on both a git clone and a
  plain folder (parametrize), per memory `packets-not-git-bound`.

### 4.2 New fixtures
- `tests/data/hooks/*.json`: sanitized real hook payloads from C0 (SessionStart
  for each source, UserPromptSubmit, Stop, Notification permission and idle,
  PreCompact, SessionEnd, Codex notify).
- `tests/conftest.py`: a `presence` fixture to write synthetic records; a
  `hooked_packet` fixture (a packet folder with hooks installed and
  `WPK_SKILLS_DIRS` isolated); a `viewer` fixture setting the dash user for
  owner gating and seen markers.
- `tests/fakemodel/behaviors/`: a `waits` behaviour that ends a turn
  (`end_turn`) without finishing the packet, for interactive-session tests if
  needed.

### 4.3 New test files (summary)
`test_views_derive.py`, `test_actions_done.py`, `test_presence.py`,
`test_hooks_install.py`, `test_hookcmd.py`, `test_attention.py`,
`test_timeline.py`, `test_plan_fields.py`, `test_brief.py`, `test_notify.py`,
`test_inbox.py`, and live `test_hooks_live.py`.

### 4.4 Extended test files
`test_schema.py`, `test_migrate.py`, `test_dash.py`, `test_dash_tasks.py`,
`test_cli.py`, `test_ide_sessions.py`, `test_ide.py`, `test_sched_dispatch.py`,
`test_tick.py`, `test_checkpoint.py`, `test_skills.py`, `test_starters.py`,
`test_stats.py`, `test_card.py`, `test_sched_classes.py`, `test_setup.py`.

### 4.5 Running
- Per step: the touched test files, then the full suite. Output goes to a log:
  `packages/python/bin/pytest -q > test-collab-<step>.log 2>&1; tail -5
  test-collab-<step>.log`.
- Live: `WPK_LIVE=1 packages/python/bin/pytest -m live -s tests/test_hooks_live.py
  > test-collab-live.log 2>&1`.

### 4.6 Manual acceptance checklist (record results in the step notes)
- [ ] (C2) Web VS Code through the board: the card shows *Working: you*. Claude
  in the extension asks permission → after 2 min with the tab hidden, a
  *blocked* item; with the tab visible, no escalation. Claude ends its turn →
  "Claude waiting" muted, then *your turn* after 15 min.
- [ ] (C2) Desktop VS Code on the same packet: the same signals arrive through
  hooks alone.
- [ ] (C2) Terminal `claude` in the packet folder: a session appears and its
  tokens are counted.
- [ ] (C2) With a hand-off pending and the IDE open, the runner doesn't start.
  Close the tab; after the TTL it starts.
- [ ] (C3) New → Open in VS Code: lands in the IDE with hooks and skills present,
  and the card is *Working: you*, not Paused.
- [ ] (C5) A new Claude session in the packet knows the brief and next action
  without being told; a note sent from the phone shows up on the next prompt.
- [ ] (C4) Desk at phone width: Needs you, inline answer and capture are usable.
- [ ] (F3) A real calendar feed (Google or Outlook ICS URL) in Settings: today's
  meetings in the brief at the right local times; a push held during a meeting.
- [ ] (F3) A watched GitHub issue with a dated milestone: the date is proposed in
  the Inbox.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| The VS Code extension ignores project hooks, or `Notification` doesn't fire there | C0 first; fall back to `sessions/<pid>.json` `status` and the transcript tail; label the card "probably waiting" |
| Hook start-up is slow on the shared FS and adds latency to every prompt | D10 stdlib-only module; measure in C0; plan B is an event-file drop |
| Editing by hand in desktop VS Code with no Claude session isn't seen after the open's 10 minutes, so the runner may start under you (found in C2; **fixed in G1** by the file-time scan) | Hand off with `--after-me` (or don't hand off) while you edit; build the file-mtime activity scan (design §4.2 fallback) if it bites; the legacy layout still opens read-only |
| Writing `settings.local.json` clobbers user config | Merge with tagged entries, never rewrite foreign ones, test with real-world files, `doctor` shows the diff, off switch |
| Concurrent journal appends from hooks and the runner | Small `O_APPEND` writes; a test; if not safe, hooks write presence only and the board pass journals |
| Presence false positives (a tab left open overnight) keep the runner idle | The 2 h attachment-only cap (D4) and a stale item; "start anyway" on the card |
| The wording and column change breaks many dash test assertions | Do it in one C1 commit, update assertions, and don't keep old strings |
| Scope: the design is very wide | Each phase is usable on its own; C7/F3 are outline only; re-plan after C4 |
| Uncommitted checkpoint/scribe/skills work drifts | Resolved: committed as `c242bfe` |

## 6. Doc plan

| Doc | Kind | Written in |
|---|---|---|
| `docs/collaboration.md` | design | exists. Update the status line per phase. Fix §4.3 after C0. Mark §5.3 "awaits triggers". Mark F2 "built without routines (D9)". |
| `docs/collaboration-plan.md` | tracker | this file, updated per step |
| `docs/collaboration-spike.md` | spike results | C0 |
| `docs/collaboration-guide.md` | **user guide** (like `studio-guide.md`) | Grown per phase. C1: what the columns and the ball mean, done/reopen/drop, autonomy. C2: presence, hooks (what is written, where, how to turn it off, privacy), how the runner holds off. C3: start modes, Open ▾, the hand-off dialog. C4: Desk, attention types, snooze, Timeline, cost split. F1: plan fields, `wpk plan`, `wpk todo`. C5: the briefing, notes to sessions, continue a step, `/wpk-*` skills. F2: the brief and its score, shutdown. C6: push setup (ntfy). Each phase adds a **config keys** table (`[ide] hooks`, `presence_ttl`, `idle_escalate`, `[focus] time`, `focus_wip`, `review_wip`, `[notify] …`), because there is no central config reference today. |
| `README.md` "Documents" | index | C1: add the design + plan + guide triple; C0: the spike |
| `docs/product.md` §1 | design | C1: replace principle 2 with P2/P3 and link here |
| Superseded-design pointers | design | C1: a one-line "superseded in part by `collaboration.md` §x" at the top of `long-running.md` (HELD), `interaction.md` §6b, `dash-tasks.md` §2 rule 4 and §6.6, `ergonomics.md` (`wpk work`), `orientation.md`, `work-sessions.md` (`worker: person`), `triggers.md` §3.1 |
| `docs/session-checkpoint.md` | design | C5: answered questions (lease, scribe as proposal), checkpoint during a step |
| `docs/vscode-monitor-plan.md` | tracker | C2: interactive `end_turn`, hook attribution level; C7 action: presence over S4b |
| `docs/server.md` / `docs/setup.md` | user-ish | C2: hooks in `wpk doctor`; C3: setup is a hand-off pre-flight, not a state |
| CLI help strings | reference | with each verb (`done`, `reopen`, `drop`, `autonomy`, `plan`, `todo`, `brief`, `shutdown`, `new --start`, `handoff --after-me`) |

DOC notes (2026-11-07): every row is done. The guide, README, `product.md`,
spike doc and superseded-design pointers were written phase by phase. The
final pass:
- `collaboration.md` status line says it is built, with the two parts not built:
  §5.3, marked "awaits triggers"; and §9.4 and the F2 row in §13, marked "built
  without routines (D9)". §4.3's Codex line is marked "not measured yet". §4.3's
  PermissionRequest fix was made after C0.
- `server.md` (wpkd) has no `doctor` section, so the doctor and hooks note and
  "setup is a hand-off pre-flight, not a state" went into `setup.md`, which
  documents `wpk doctor`.
- CLI help: `done`/`drop`/`reopen`, `autonomy`, `plan` (incl. `--milestone`),
  `todo`, `brief`, `shutdown` and `handoff --after-me` all have help. `new
  --start` was not added (C3 notes).

## 7. Status log

- 2026-11-06: plan written. Decisions confirmed; §2a dash-first table added. Prerequisite commit done.
- 2026-11-06: C0 done (Codex open).
- 2026-11-06: C1 done; full suite 1267 passed, 13 skipped. Not committed.
- 2026-11-06: C2 done; full suite 1301 passed, 13 skipped; live hooks check passed. Not committed.
- 2026-11-06: C3 done; full suite 1311 passed, 14 skipped. Not committed.
- 2026-11-06: C4 done with gaps; full suite 1326 passed, 14 skipped. Not committed.
- 2026-11-06: C5 done with gaps; full suite 1333 passed, 15 skipped (after fixing the layout-parity test for the step page's resume panel); live hooks checks (2) passed. Not committed.
- 2026-11-06: C2b (opening VS Code claims the project, D15) done; full suite 1338 passed, 15 skipped. Not committed.
- 2026-11-06: F1 done with gaps; full suite 1346 passed, 15 skipped (plus a rerun of the touched files after the last template and config changes). Not committed. Next: F2 (focus brief, shutdown), then C6.
- 2026-11-06: F2 done with gaps; full suite 1353 passed, 15 skipped. Not committed. Next: C6.
- 2026-11-07: C6 done with gaps; full suite 1367 passed, 15 skipped. Not committed. Next: C7 and F3 need detailed plans (outline only so far); the manual checks in §4.6 (a real ntfy topic on a phone) are open.
- 2026-11-07: C7 detailed (slices C7a-e) and done with gaps: jobs, status line and `status.json`, rules from corrections, split, and presence in the S4b design. Full suite 1386 passed, 15 skipped (`test-collab-c7.log`). Not committed. Next: F3 needs a detailed plan (outline only); the manual checks in §4.6 are open, plus one for C7: a real `wpk run` and a split from VS Code.
- 2026-11-07: F3 detailed (slices F3a-f) and done with gaps: your time and estimates against actuals, forecast and at risk, dates from forge milestones, board milestones with a burn-down, weekly review / standup / status, calendar fit. Full suite 1399 passed, 15 skipped (`test-collab-f3.log`). Not committed. Every phase of the plan is now built; open: the gaps in each step's notes, the Codex `notify` row in §2a, and the manual checks in §4.6 (including two new F3 ones).
- 2026-11-07: DOC done: the final pass on `collaboration.md` (status line, §4.3
  Codex, §5.3, §9.4, §13) and a doctor and pre-flight note in `setup.md`. Docs
  only, no code changed. Every step in the Status table is done. Open: the gaps
  in each step's notes, the Codex `notify` row in §2a, and the §4.6 manual
  checks. Not committed.
- 2026-11-07: G done (G1-G8): edits by hand hold the runner, tokens for desktop
  and terminal sessions, the compaction nudge and scribe drafts as proposals,
  watchers edited on the board, Desk and task odds and ends, Inbox snooze until
  the project moves and declining requests, split back-pointer, removal and
  shares, and the forecast's own answer times and working days. 18 new tests in
  `tests/test_collab_g.py`; `test_collab_c5.py` updated for the nudge. Full suite
  1420 passed, 15 skipped (`test-collab-g.log`). Not committed. Still open: the
  Codex `notify` row (§2a, no Codex here), the §4.6 manual checks, and the
  out-of-scope items in G's preamble.
