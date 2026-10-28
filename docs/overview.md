# The Overview page

Status: built (2026-10-25). Decisions: counts are projects (packets in a
tooltip); the combined all-cards board is gone; tokens over 1, 7 or 30 days
(`/?days=`).

## Problem

`/` today is the `main` board's layout with every board's cards in it, plus the
7-day token table underneath (boards.md, "Dash"). It answers "show me every
card", which `/b/<board>` and All packets already answer better. It does not
answer the questions you open the dash with:

1. Does anything need me right now?
2. What is running, and is anything stuck or failing?
3. How is each board doing?
4. What am I spending, and how much quota is left?
5. What happens next (who wakes up when)?

The Overview should answer those at a glance, with no cards. Each item links to
the board, project or packet where you act on it.

## Layout

Top to bottom, the most urgent first. Everything comes from what `data.board()`
and `tokens.board()` already read; no new files.

### 1. Headline tiles

One row of stat tiles:

| Tile | Figure | Sub-line |
|---|---|---|
| Needs you | projects in *Needs you* | oldest waiting for |
| Running | projects with a live step | next wake-up |
| Failed | projects in *Failed* + failed child packets | newest failure, when |
| Spend | today | the token window (7 or 30 days) |
| Quota | weekly quota used | resets in |
| Pool | the scheduler's mode (red unless running) | packets waiting, starting |
| Cores in use | cores the pool's jobs hold / its limit | jobs / limit |
| Budget | spent of `[sched.budget] amount` (only with a budget) | pace; amber when ahead of it |

The three scheduler tiles link to `/sched` (docs/scheduler.md §9). Every
page also shows a red banner while the pool is halted or stopped.

A tile is red/amber only when it calls for action (Needs you > 0, Failed > 0,
quota ≥ 80%). The quota tile is hidden for API-key accounts (no quota data).

### 2. Attention

One list, across all boards, of what waits on you: *Needs you* items first
(the question, project, board, "Answer" link to `/p/<project>/<wpid>#answer`),
then failures (root failed, or `trouble` children; the reason), then projects
held for setup (`setup.next`). Empty: one muted line "Nothing needs you."

### 3. Boards

A table, one row per board, `main` first:

| Board | Needs you | Running | Ready | Sleeping | Paused | Failed | Done | Projects | Packets | Cost | Context | Per day | Last step |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

- The status cells are project counts, the same columns as the board, with the
  board's colour dot; a zero is muted. A cell links to `/b/<board>`.
- A thin stacked bar under the board name shows the same split at a glance.
- A status cell's title names its projects. Packets counts every packet, its
  title the count per state.
- Cost, Context and Per day cover the token window (§6).
- Projects that could not be read show as "+N?" after the project count.

### 4. Running now

Each live step: project, packet, step, for how long, its last activity line
(`card.running.now`), linked to the live view. This is what the Running column
showed on the old Overview, without the rest of the board.

### 5. Coming up

What runs next, ~8 across all boards: first the Ready packets (due now; a
note when the runner is off), then the wake-ups, soonest first: project,
packet, wakes at, board. (Sleepers are already sorted by `wake_at` in
`data.board()`.)

### 6. Tokens, last N days

- The quota line (`tkm.quota`), as now.
- The totals over the window (`tkm.summary`) and a full context-per-day chart.
  The per-board figures sit in the Boards table (§3).
- A 1 / 7 / 30 day switch (`/?days=`, default 7); "Per day" columns hide
  for one day.
- The per-project table as now, cut to the top 10 by context with "show all"
  (a `<details>`), since the board summary carries the totals.

### 7. Projects that could not be read

As now.

## Where the all-cards board went

The combined board left `/` and was dropped. Each board has its own page,
and All packets covers "everything at once" with sort and filter. The
"Show all cards / Fit board to screen" toggle and the scrolling-column CSS go
with it, since only the Overview needed them.

## Build notes

- `data.overview(cols, broken, side, burn)` builds the tiles, attention list,
  board rows, running list and wake-ups from the results `board()` already has;
  `tokens.board(entries, days, on)` gives each row its `board`, plus `boards`
  (per-board figures and spark) and `total` (figures and chart).
- New template `overview.html`; `board.html` loses its `not here` branches.
- Live refresh as now (`live=True`).
- Tests: `test_dash.py::test_pages` and `test_token_panels`,
  `test_boards.py::test_dash_side_tab_and_board_pages`,
  `test_setup.py::test_board_card_shows_setup`.
