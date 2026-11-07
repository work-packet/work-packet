# Where we stand, and what's next (2026-11-07)

A hand-over note: a fresh session should be able to pick up from this file
alone. The detail is in `docs/collaboration-plan.md`, with one section per step
and a status log. How to use the features is in `docs/collaboration-guide.md`.
The design is `docs/collaboration.md`. The proposed roadmap is
`docs/roadmap-v2.md`, which is not accepted yet and not committed.

## 1. What is done

The whole of `collaboration.md` is built: phases C0-C7 and F1-F3, plus a pass
that closed the gaps they left (step G) and the documentation step (DOC). Each
step's notes in the plan say what was built and where, how it differs from the
plan, and what was left out.

| Step | What it gave | Committed in |
|---|---|---|
| C0 | Spike: project-local Claude hooks work in the CLI and the VS Code extension (`collaboration-spike.md`) | `06489da` |
| C1 | Derived view: lifecycle, driver, ball and autonomy; columns by whose move it is; Parked; Done/Drop/Reopen; real actors | `06489da` |
| C2, C2b | Presence and hooks (`hookcmd`), the runner holding off while you're there, and opening VS Code claiming a project until you hand it back (D15) | `06489da` |
| C3 | Start modes on New, Open ▾ on cards, Compose as the hand-off dialog (pre-flight, dirty tree, after I leave) | `06489da` |
| C4 | The Desk: typed Needs-you items, snooze, since you were last here, timeline, session cost | `06489da` |
| F1 | Planning fields (`plan:`), now-WIP, Backlog, quick capture, rot | `06489da` |
| C5 | SessionStart briefing, notes into interactive sessions, checkpoint during a step, continue a runner step, `/wpk-*` skills | this commit |
| F2 | The daily focus brief, built by the board each morning (`brief.py`), and the end-of-day page | this commit |
| C6 | ntfy push and browser notifications, digest, attention budget, Inbox triage, follow-ups, Settings page | this commit |
| C7 | Jobs (`wpk run`, Run a command), status line and `status.json`, rules learned from corrections, split | this commit |
| F3 | Time ledger, estimates against actuals, forecast and at risk, forge milestone dates, board milestones and burn-down, weekly review, standup and status pages, calendar fit | this commit |
| G | Edits by hand hold the runner; tokens for desktop and terminal sessions; compaction nudge; scribe drafts as proposals; watchers edited on the board; Desk odds and ends; Inbox snooze-until-moves and declining requests; split back-pointer, removal and shares; personal forecast and working days | this commit |
| DOC | Design status line, superseded-design pointers, guide, setup.md note | this commit |

Tests: the full suite gave 1420 passed and 15 skipped on 2026-11-07, before the
commit (`test-collab-g.log`, not committed; `*.log` is ignored). New test files:
`test_brief.py`, `test_collab_c6.py`, `test_collab_c7.py`, `test_collab_f3.py`,
`test_collab_g.py`.

**Dash-first rule** (user, 2026-11-06): work happens through the board, and
anything that still needs a command is listed in the plan's §2a. Every row
there is now built or "n/a", except Codex `notify` and "continue a runner step",
which is still copy-and-paste until the VS Code extension exists.

## 2. Left out of this commit, on purpose

These were already in the working tree before this work and aren't part of
it, so they are left for you to commit or drop:

- **A separate VS Code web fix**: `src/work_packet/dash/ide_forward.py`
  (drops our `nosniff` so Chrome's ORB doesn't block vscode-print's mislabelled
  scripts, and rewrites the page's own localhost origin), `tests/fake_ide.py`,
  `tests/test_ide_forward.py`, `docs/server.md`, `docs/vscode-plan.md`.
- `docs/studio-plan.md` (studio v2 status edits).
- Untracked design docs: `roadmap-v2.md`, `triggers.md`, `studio-v2.md`,
  `desktop.md`, `distributed.md`, `multi-machine-plan.md`,
  `serve-restart-plan.md`, `vscode-extension.md`, `vscode-monitor-plan.md`,
  `positioning/competitive-position.md`. The committed docs refer to several of
  them (`triggers.md`, `vscode-monitor-plan.md`, `vscode-extension.md`).
- `work-packet/`: a separate git clone inside the repo. It should never be
  committed here. Consider adding it to `.gitignore` or moving it.

## 3. Still open in what's built

- **Codex `notify`** (plan §2a): Codex reads `notify` from its own global
  config. Either the board writes it (announced, like the Claude hooks) or Codex
  sessions stay "probably waiting". It can't be measured until Codex is
  available on this host.
- **Manual checks** (plan §4.6), which only you can do:
  - web VS Code, desktop VS Code and terminal `claude` each make the card say
    *Working: you*, and the runner holds off;
  - New → Open in VS Code lands with hooks and skills;
  - a new session knows the brief;
  - the Desk at phone width;
  - ntfy on a real phone;
  - a real `wpk run` and a split from VS Code;
  - a real calendar feed;
  - a GitHub issue with a dated milestone.
- **Out of scope for G**, still open:
  - the VS Code extension (`vscode-extension.md` E1), so continuing a runner
    step in one click isn't possible;
  - narration of the brief and reviews by a model;
  - triggers and routines (§5.3 waits for them);
  - splitting a plain folder or a `work/` project, and "land after I commit";
  - backfilling a milestone's burn-down, RRULE expansion, and PR review
    requests as dates;
  - ntfy action buttons;
  - a phone view.
- **Behaviour to watch in real use**:
  - any write into a packet folder now holds the runner for up to 10 minutes
    (G1);
  - STALE rows appear on the Desk for long-parked projects (G5);
  - a compacted session is told to suggest a checkpoint (G3);
  - watchers saved from the board rewrite `boards/<board>.toml`, so comments in
    it are lost (G4).
- **Differs from roadmap-v2**: D2 says watchers should default to the Inbox
  (`propose = true`). They still default to making projects. Change it when
  the roadmap is accepted.

## 4. What's next, in order (agreed with the user 2026-11-07)

1. **Use it, and run the M2 end-to-end check.** The roadmap's M1 and M2 exits
   are about real use, which tests don't cover.
   - **M1**: a week in which the board never shows Paused or Setting up while
     you work, and a blocked Claude shows within a minute from web VS Code,
     desktop VS Code and a terminal.
   - **M2**: a real-model run (sonnet) of the whole loop with no CLI. Start by
     hand → hand off from VS Code → runner finishes → review → continue in VS
     Code. Claude can script and run this. The user does the §4.6 manual checks
     meanwhile.
2. **Phone view and ntfy buttons** (roadmap M4 "phone", design §9.6). About a
   day of work.
   - A page for a phone: today's brief, Needs you with inline answers and Reply,
     Inbox triage, capture. Either `/m` or the Desk switching layout at phone
     width. Pushes link there.
   - ntfy action buttons (Answer, Snooze 1h, Done) that post back to the board,
     so most pushes are dealt with without opening it. That needs a token-signed
     action URL that works from the phone, since a push can't carry the board's
     CSRF token.
   - Check the wide pages on a phone: board columns, sessions tables, step and
     diff views, the Watchers and Milestones forms.
3. **M3: the GitHub connector, detailed plan first.** Write it as C7 and F3 were
   written (slices, tests, docs) and get it reviewed before building. Already
   built: watchers, Inbox triage, planning fields, milestone dates. To do:
   - review requests on others' PRs become **review** items;
   - failing CI on a packet's branch becomes a **failure** item;
   - "waiting on CI" or "waiting on a reviewer" becomes ball *external*;
   - report back: a comment on hand-off and result, close or link on Done
     (opt-in per board, D7);
   - a connector interface over `forges.py` (notice, bring in, map, act);
   - minimal person-to-person hand-off: `wpk export` and `import` with a
     turnover note, and assignment through GitHub (D5, for the 2026-12-21
     outside checkpoint).
4. **M4: one agenda.** Triggers, routines, reminders, deferred hand-offs and
   at-risk alarms become one schedule that people and agents both act on. Also
   the brief as a routine packet and an ICS feed out. It needs a detailed plan
   and review, and depends on the `triggers.md` and `routines-and-outputs.md`
   designs (roadmap D3, D8).
5. Later: M5 agent ↔ agent (Q1 2027), M6 person ↔ person (Q2 2027).

Before step 3, the user should accept or change `roadmap-v2.md` (its §8,
decisions D1-D8), and decide whether to commit it.

## 5. Working conventions (from CLAUDE.md and memory)

- Never commit or push unless told to in that message. Pushing is the user's
  job.
- Plans and reports go in Markdown in the repo. Build and test output goes to
  a log file (`... > x.log 2>&1`); show the tail.
- Packets are not git-bound: a workspace may be a plain folder.
- Real-model checks use sonnet for hard checks and haiku for plumbing.
- Tests use the `fake` fixture (`WPK_HOME`, and `WPK_NOW=2026-10-21T18:00:00Z`,
  a Wednesday). The helpers `_new`, `_client` and `_flash` are in
  `tests/test_dash_tasks.py`.
