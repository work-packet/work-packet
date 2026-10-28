# Boards and the side tab

The dash grows a side tab on its main screen, the first step toward a
collaborative model (product.md §11): **Overview, Inbox, Outbox, Boards
(each local board beneath it), Connections**. This round builds Overview and
local boards: create a board, delete one, move projects between boards.
Inbox, Outbox and Connections show in the tab as "later" and do nothing yet.

## Model

- A card on the board is a registered project (its root packet and the tree
  under it), so a board holds projects and "moving a packet" moves its project.
- A board is `$WPK_HOME/boards/<name>.toml`: `name`, `created`, optional `title`.
  Board names follow the project-name rule `[a-z0-9][a-z0-9_-]*`.
- `main` is the default board. It always exists, needs no file and cannot be
  deleted.
- A project's board is an optional `board` field in its registry entry
  (`projects/<name>.toml`). An absent field, or the name of a board that no
  longer exists, means `main`. So a project is on exactly one board, and one
  rewrite of one small file moves it.
- Deleting a board moves its projects to `main` and removes the board file.
  Nothing about a project is lost.

## Dash

- `/` is the **Overview** (overview.md): no cards, but headline tiles, what
  needs you, a row per board with its project count in each column, what runs
  and wakes next, and token use over 1, 7 or 30 days.
- `/b/<board>`: one board's cards; its columns just grow.
- `/packets`, **All packets**: one row per packet on every board (board,
  project, packet, state, step, last step, cost, reason or summary). Click a
  heading to sort (a third click goes back to tree order); search matches
  every word in a row; state and board filters. The choices survive a live
  refresh (`packets.js`, session storage); its form is `data-filter`, so typing
  in it does not stop live refresh for good, as a dirty form does.
- The side tab is on all three: entries with counts (cards; a "needs you" count
  when nonzero), a `+` to make a board, and later-items greyed out. It folds
  to a strip across the top on a narrow screen.
- Moving: drag a card onto a board in the side tab; the "Board" select on
  the project page (works with no mouse, and on a phone); or, on All packets,
  tick rows, pick a board and press "Move to board". A board holds projects,
  so that moves each ticked packet's whole project, once however many of its
  packets are ticked, and the flash says "moved project …".
- POST `/boards` (create), POST `/b/<board>/delete`, POST `/p/<project>/board`
  (move). The CSRF token rides in the form, or in `X-CSRF-Token` for a drop.
- Deleting asks first (`data-confirm`), saying how many projects go to `main`.

## CLI

`wpk board [list]`, `wpk board new <name>`, `wpk board rm <name>`,
`wpk board move <project> <board>`.

## Next: operations on selected packets

All packets gets a checkbox per row and a bar of operations on the selection:
move to a board, remove, change state (pause, resume, hand off), and more.
To settle first:

- Settled 2026-10-26: boards hold whole projects only. "Move" on a child
  packet moves its project (each project once), and the bar says so. Boards
  will not hold single packets; a child always sits on its root's board.
- "Remove": unregister the project (`wpk rm`, files kept), or delete a packet
  subtree? Only the first exists today.
- Change state maps onto `executor.admin` (pause, resume, handoff); one POST
  with a list of `project/wpid`, one outcome line per packet in the flash.

## Steps

- [x] B1 registry: boards, `board` field, create/delete/move; schema (spec §2.3); tests
- [x] B2 data/tokens: filter by board, board summaries for the side tab
- [x] B3 dash: side tab, `/b/<board>`, POST routes, project-page select; tests
- [x] B4 board.js: drag a card onto a board; confirm on delete
- [x] B5 CLI `wpk board`; tests
- [x] B6 All packets table: sort, search, filters (`/packets`, packets.js)
- [x] B7 render check in Chrome (1400 and 1100 wide); the drop's POST with
  `X-CSRF-Token` against a real `wpk dash`
- [x] B8 operations on selected packets (above): built with the scheduler
  (docs/scheduler-plan.md Q3.6): a checkbox per row on All packets and a bar
  for pause, resume, hold project, set class and set size; one POST, one
  outcome line per packet in the flash
- [x] B9 All packets: "Move to board" in the bar (2026-10-26; `op=board`,
  moves projects, no runner poke); test in `tests/test_boards.py`

## Status

2026-10-25: B1-B7 done; full suite passes (523). Not committed. Drag and drop
and the sort/search were checked for syntax and by request, not by hand in a
browser: worth a try before relying on them.
