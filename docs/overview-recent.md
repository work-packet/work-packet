# Overview: finished work in Needs attention, and token use on its own page (plan and status)

Started 2026-10-28. Changes the Overview (`docs/overview.md`). Status:
**proposed**, waiting for decisions on Q1–Q5 before building.

## Why

The Overview shows well what is running and what is waiting on you. It
does not show what has *finished* since you last looked. A packet that
completes leaves "Running now" and does not appear anywhere else on the
page: you have to remember it and go and find it. Below that, the token
section (summary, chart, top-10 project table) fills the bottom half of the
page. You look at it now and then, not every time you open the Overview.

## What changes

### 1. Finished work joins "Needs attention"

There is no new section. Finished work you have not looked at becomes one
more kind of row in the existing **Needs attention** list. That list is
already "what waits on you", and finished work waits on you to read it.

- **What is listed:** each project whose root packet is COMPLETED, and
  which you have not opened since it completed.
  - A completion is identified by the project and the root's `updated`
    time.
  - A project that gets a next task and completes again shows up again.
- **A row** (kind `done`, after asks, failures and setup):
  - a `DONE` badge, the project and its board;
  - the report's outcome, cut to one line;
  - when it completed (for example, "2 h ago");
  - what the task cost;
  - the PR link, if `[pr]` is set;
  - Open, and a `×` to dismiss.
- **Only `done` rows can be dismissed.** Asks, failures and setup leave the
  list when they are dealt with (answered, handed off, removed), as now.
  Dismissing a failure would hide a packet that is still broken.
- **Removing a row:**
  - **By opening it.** A visit to `/p/<project>` or any page under it
    marks the project's current completion as seen. Opening the project
    while it is still running does not mark a completion that happens
    afterwards.
  - **By dismissing it.** The `×` on a row removes it without opening it.
  - **By selecting.** A checkbox on each `done` row, and a bar above the
    list: "Select all done", "Mark seen", "Clear all done".
  - Each of these sends one POST, `POST /seen`, with a `project=` value
    per row and the CSRF token. The flash says "marked N seen".
- **Where it is stored:** `$WPK_HOME/dash/seen.json`, as
  `{project: "<root updated ISO time>"}`.
  - The file is written atomically under a lock.
  - Nothing in the project changes.
- **Tiles:** a **Done** tile (count of unread completions, links to
  `#attention`) next to "Needs you". It is not coloured: done is good news.
- **Many at once:** the list shows up to 20 `done` rows, newest first, then
  "and N more" (expands).
- **Live refresh:** ticked boxes survive it. The bar's form is marked
  `data-filter`, and the ticks are kept in session storage, as on All
  packets.
- **Empty list:** "Nothing needs you." stays the wording when there are no
  rows of any kind.

### 2. Token use moves to a new page: Statistics (`/stats`)

- The whole "Tokens, last N days" section moves to `/stats`, unchanged:
  the quota line, the summary, the chart, the per-project table with its
  1/7/30-day switch, and "more projects".
- The page also gets the per-board token figures, which today sit in the
  Overview's Boards table: Cost, Context and Per day.
- **The Overview keeps:**
  - the Spend today and Weekly quota tiles, which now link to `/stats`;
  - the Boards table, with only state counts, Projects, Packets and Last
    step. Its Cost/Context/Per-day columns move to `/stats`, so the
    Overview no longer runs the full `tokens.board()`.
  - The Spend tile needs only its "today" figure, which comes from the
    cards.
  - The quota tile still needs the newest quota seen across the steps.
    `tokens.quota` reads only that, which is a lighter read.
- **Side tab:** "Statistics" goes below Overview, alongside All packets.
- Links that pointed at `/?days=` and `#tokens` now point to
  `/stats?days=` (the tiles, and any links in the docs).

## Steps

- [ ] O1. `dash/seen.py`:
  - `load(h)`, `mark(projects, h, at=None)` (stores each project's
    current root `updated`) and `unread(cards, h)`;
  - the lock and the atomic write;
  - tests.
- [ ] O2. `data.overview` adds attention rows of kind `done` (the outcome
  from `report.of_packet`, the task's cost, `[pr]`), after setup; the `done`
  tile.
- [ ] O3. Routes:
  - `POST /seen` (ids or `all`, with CSRF);
  - the project pages mark a project seen on GET, in `project_page`,
    `packet`, `step` and `live_view`;
  - tests: open → gone, dismiss, select, all, re-complete → back.
- [ ] O4. `overview.html`: `done` rows in Needs attention, the selection
  bar (shown only when there are `done` rows), the tile; `overview.js` (or reuse `packets.js`) for select-all and ticks
  that survive refresh.
- [ ] O5. `/stats`:
  - a new `stats.html`, with the token section moved from `overview.html`
    plus the per-board table;
  - the Overview drops `tokens.board()`;
  - a side-tab entry, and the tile links updated;
  - update tests `test_dash.py::test_pages` and `test_token_panels`.
- [ ] O6. Docs: `docs/overview.md` (§2 Attention gains `done` rows, §6 moved
  to Statistics), `docs/boards.md` (Dash list); check the page in a browser
  at 1400 and 1100 wide.

## Questions (proposed answers in bold)

- **Q1. What counts as "completed"?**
  - Root COMPLETED, as `DONE`. FAILED and asks are already in the list.
  - **Also a root PAUSED by a budget or step limit, as `STOPPED`**: it
    ended a run without you, so it is "finished, go look". Dismissable like
    `DONE`; handing it off again also clears it.
- **Q2. Per project or per packet?** **Per project.** Boards hold projects,
  and a project's children finishing is part of its run, not an event of
  its own. A child that fails already shows as "trouble".
- **Q3. Page name: Statistics or History?** **Statistics** (`/stats`), to
  match `wpk stats`.
  - "History" is already the name of the history store (`wpk history`,
    `history.db`).
  - A History page could later list *all* past completions, including
    those marked seen.
- **Q4. Whose "seen"?** With unix login several people can sign in to one
  board. **One shared seen-list per home for now**, since the board is the
  owner's.
  - If colleagues use it, key the file by signed-in user later
    (`seen.<user>.json`).
- **Q5. First run.** Without a seed, every project that ever completed
  would appear at once. **Seed on first load:**
  - completions older than 24 h are marked seen;
  - newer ones are listed.

## Status

- 2026-10-28: plan written; nothing built.
- 2026-10-28: changed: no separate section; unread completions are `done`
  rows in Needs attention, and only those rows can be dismissed.
