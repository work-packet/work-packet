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
| F2 | Daily focus brief (deterministic), end-of-day shutdown | todo |
| C6 | Push, digest, attention budget, snooze, Inbox triage | todo |
| C7 | Split / pairing, jobs as workers, learn from corrections, VS Code status bar | todo (outline only) |
| F3 | Forecast, at-risk, dates from forges, milestones, weekly review, standup drafts | todo (outline only) |
| DOC | User guide, README index, pointers in superseded designs | todo (done per phase; see §6) |

Notes:
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
| `[ide] hooks`, `presence_ttl`, `idle_escalate` | `hooks`: board switch (built). `presence_ttl`, `idle_escalate`: **still config-only.** A board Settings page for the remaining keys (TTL, idle escalation, focus time, WIP limits, ntfy) is to be built in C4, when there are enough of them to justify it. | C2/C4 | hooks built; rest open |
| `python -m work_packet.hookcmd <event>` | None needed: run by Claude Code, never by a person | C2 | n/a |
| Codex `notify` set-up | **Gap: Codex reads `notify` from its own global config.** Either the board writes it (announced, like the Claude hooks) or Codex sessions stay "probably waiting". Decide after C0. | C2 | open |
| `wpk new --start …` | The New page's start buttons (no CLI flag: the start modes belong to the board) | C3 | built |
| `wpk handoff --after-me` | "After I leave" in Compose and on the packet page's Hand off form | C3 | built |
| `wpk checkpoint` | Already on the packet page (Update status, becoming Checkpoint), plus Draft from session | C1/C5 | exists |
| Continue a runner step (`claude --resume … --fork-session`) | Step page: **Continue this conversation yourself**, with the commands to paste. **Still a copy-and-paste**: one click would need a VS Code extension or terminal API (C7's status-bar extension could do it). | C5 | gap |
| `/wpk-handoff`, `/wpk-note`, `/wpk-done`, `/wpk-todo` skills | Typed inside a Claude session you are already in. Each has a dash equivalent (Compose, note box, Done, capture in F1). | C5 | built (todo waits for F1) |
| `wpk plan --priority … --due …` | Plan ▾ on cards, the packet page and the Backlog (every field); rank typed on the Backlog | F1 | built |
| `wpk todo "…"` | Capture boxes on the Desk, the Backlog and each board's Inbox column | F1 | built |
| `wpk brief` | The board runs it at `[focus] time` and shows it on Desk. Add a **Rebuild now** button and the list of past briefs. The time is set on the board Settings page. | F2 | planned |
| `wpk shutdown` | A Desk button, offered after 17:00 when the last presence lapses | F2 | planned |
| `[focus] time`, `focus_wip`, `review_wip`, `[notify] ntfy_url` | Board Settings page (above), with a "send a test push" button for ntfy | F1/F2/C6 | planned |
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

- [ ] `brief.py`: `build(user, now) -> Brief(overnight, needs_you, focus,
  handoff_candidates, housekeeping)`, built from the journal since the last
  brief, attention items, plan fields and rot. The focus score is documented in
  code and in the guide: priority, deadline pressure (due-based only until F3
  adds the forecast), unblocks others (questions gating runner work, weighted by
  queued tasks), then age. Each line carries a `why`.
- [ ] Hand-off candidates: packets with a brief, a next action and
  `autonomy != manual`, or ones marked runner-safe. Budget left from
  `sched/budget`.
- [ ] `wpk brief [--date] [--md]`. The board runs it at `[focus] time` (default
  08:30 weekdays) and writes `$WPK_HOME/briefs/YYYY-MM-DD.md` (D9). Past briefs
  are listed on Desk (history, memory `dashboard-is-central`).
- [ ] Desk "Today" strip; the first SessionStart briefing of the day gets one line.
- [ ] Feedback: "not today" and "done already" are stored in
  `$WPK_HOME/briefs/feedback.json`. Three ignores raise a stale item, then
  silence.
- [ ] Optional narration through the scribe model (opt-in): it rephrases only,
  and the order is fixed by the score.
- [ ] Shutdown: `wpk shutdown`, and a Desk button that appears after 17:00 when
  the last presence lapses. It lists open sessions to checkpoint, the night-shift
  candidates (sized to budget and quota) with "hand off all" (`defer: true`), and
  "pick tomorrow's first item" (sets rank 1 in *now*).

**F2 tests**
- `tests/test_brief.py`: golden-file briefs from a synthetic board (fixed
  `WPK_NOW`). Score ordering with reasons; the feedback suppression; no model
  call when narration is off (assert the fake model isn't invoked).
- `tests/test_dash.py`: the Today strip and the brief history list.

### C6. Attention delivery (needs C4)

- [ ] Push (D12): `notify.py` with ntfy (`[notify] ntfy_url`, topic) and
  browser `Notification` from an open board tab via the existing live
  WebSocket. Only *blocked* and *question* push, past their threshold and when
  not visible. A daily brief push is opt-in.
- [ ] Rate limit: one push per item, then a digest.
- [ ] Digest: the notify-type items batched hourly or daily.
- [ ] Attention budget (§7.6): the review WIP tile; a hand-off dialog warning
  above `review_wip`.
- [ ] Inbox triage: the Inbox column and Desk strip read watcher packets that
  aren't accepted yet (`watch.py` gains a "propose" mode that writes Inbox items
  instead of packets), requests (`requests.py`), captures (F1) and
  agent-proposed follow-ups (a memento field `follow_ups:` that the runner may
  write and that the board turns into Inbox items). Actions: accept (→ W1/W4),
  decline, merge into a packet, snooze.
- [ ] Duplicate hint on accept: title and brief token overlap with open packets.

**C6 tests**: `tests/test_notify.py` (thresholds, visibility suppression, rate
limit; ntfy with a fake HTTP server); `tests/test_inbox.py` (sources → items,
the triage actions); dash tests for the tile and warning.

### C7. Concurrency and jobs (outline; detail later)

- Split (`packet-ux.md` U3): runner in a worktree, result as a branch, a review
  item with a diff and merge or cherry-pick. Plain folders get copy-in and
  copy-out with a diff. Needs its own design pass on merge UX.
- Jobs as workers: `work-sessions.md` stages 1-4 (`wpk run -- cmd`, OSC marks),
  journal `job-start`/`job-end`, ball *external*.
- Learn from corrections: recurring notes and answers → a proposal to promote
  them into `skills.py` or the starter. Needs the scribe.
- VS Code status bar: a thin extension or status-line reading presence and
  attention (`vscode-extension.md`).
- §12 distributed: presence over the S4b push channel. **Action now**: add
  "presence records" to the S4b design in `vscode-monitor-plan.md` so it isn't
  retrofitted.

### F3. Deadlines and reporting (outline; detail later)

- Forecast from step durations, queue waits and presence pace; a range; at-risk
  decision items.
- Dates from forges (milestones, review requests) as proposals; board milestones
  with a burn-down.
- Weekly review, standup and status drafts as kept outputs (routines if built
  by then); estimates against actuals; an ICS calendar fit.

---

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

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| The VS Code extension ignores project hooks, or `Notification` doesn't fire there | C0 first; fall back to `sessions/<pid>.json` `status` and the transcript tail; label the card "probably waiting" |
| Hook start-up is slow on the shared FS and adds latency to every prompt | D10 stdlib-only module; measure in C0; plan B is an event-file drop |
| Editing by hand in desktop VS Code with no Claude session isn't seen after the open's 10 minutes, so the runner may start under you (found in C2) | Hand off with `--after-me` (or don't hand off) while you edit; build the file-mtime activity scan (design §4.2 fallback) if it bites; the legacy layout still opens read-only |
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
