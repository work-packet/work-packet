# Overview: finished work in Needs attention, and token use on its own page (plan and status)

Started 2026-10-28. Changes the Overview (`docs/overview.md`). Status:
**agreed** (Q1–Q5 below); not built yet.

## Why

The Overview makes it easy to see what is running and what waits on you.
It does not show what has *finished* since you last looked. A project that
stops leaves "Running now" and does not appear anywhere else on the page.
The token section (summary, chart, project table) fills the bottom half of
the page. You look at it now and then, not on every visit.

## What changes

### 1. Finished work joins "Needs attention"

There is no new section. A project that has stopped and that you have not
looked at since is one more kind of row in the **Needs attention** list.

- **What is listed:** each project whose run has *stopped*, which means
  all of these hold:
  - its root packet is COMPLETED (`DONE`), or PAUSED by the system for a
    budget or limit (`STOPPED`, Q1);
  - no packet in its tree is running, RUNNABLE or SLEEPING (Q2: only once
    the whole project stops, not when one packet does);
  - its root has not been marked seen since it stopped (§2).
- **Not listed:**
  - a root PAUSED by hand (you did that yourself);
  - a root PAUSED for setup (it already has its own SETUP row);
  - FAILED and asks (they already have rows).
- **A row** (after asks, failures and setup; newest first):
  - a `DONE` or `STOPPED` badge, the project and its board;
  - the report's outcome, cut to one line, or for `STOPPED`, the reason;
  - when it stopped;
  - what the run cost;
  - the PR link, if `[pr]` is set;
  - Open, and a `×` to dismiss.
- **Only these rows can be dismissed.** Asks, failures and setup leave the
  list when they are dealt with, as now. Dismissing a failure would hide a
  packet that is still broken.
- **Removing a row:**
  - **By opening it:** a visit to `/p/<project>`, or any page under it,
    marks it seen.
  - **By dismissing it:** the `×` on a row removes it without opening it.
  - **By selecting:** a checkbox on each of these rows, and a bar above
    the list with "Select all", "Mark seen" and "Clear all finished".
  - Each of these is one `POST /seen` (a `project=` per row, with the CSRF
    token); the flash says "marked N seen".
  - Handing the project off again, or giving it a next task, also removes
    the row, because its run is no longer stopped.
- **Tile:** a **Done** tile, with the count of unread rows, next to
  "Needs you"; it links to `#attention` and is not coloured.
- **Many at once:** up to 20 of these rows, then "and N more" (expands).
- **Live refresh:** ticked boxes survive it. The bar's form is
  `data-filter`, and the ticks are kept in session storage, as on All
  packets.

### 2. "Stopped" and "seen" are kept with the packet (Q5)

They are not kept in a dashboard file, and they are not guessed from
times. Both are recorded on the **root packet's** runtime metadata, so they
travel with the packet, reach the history store, and mean the same to
`wpk` and to the dashboard.

- **`status.md` gains two optional fields** (`schema.STATUS_FIELDS`, spec
  §status):
  - `stopped`: the UTC time the packet's run stopped, set by the executor
    when the root goes to COMPLETED (step commit), or to PAUSED by the
    system (the scheduler's caps, via `admin(..., by=SYSTEM)`). It is
    cleared when the packet becomes RUNNABLE again (handoff, continue,
    resume).
  - `seen`: the UTC time someone last looked, set by a new
    `executor.mark_seen(pkt, by)`. Like `admin`, it takes the lease, so it
    never races a step. It also appends a `seen` journal record
    (`{type: seen, t, by}`), so the history keeps who looked and when.
- **Unread** is `stopped` set and (`seen` missing or `seen < stopped`),
  together with the tree check in §1.
- **The tree check:** the root's `stopped` is set when the root stops,
  but its children may still be running. The row waits until the tree is
  at rest; then "when it stopped" is the later of the root's `stopped` and
  the newest step end in the tree.
- **Existing packets:** they have no `stopped` field, so they are not
  listed. Nothing floods the list on the first run, and no cut-off is
  needed. From now on every stop is recorded.
- **CLI:** `wpk seen <project>…` (and `--all`) does the same as the
  dashboard. `wpk ls` or `wpk status` can show "unread", if that turns out
  to be useful.
- **Who:** one shared mark per packet (Q4). The journal records `by` (the
  signed-in user, else `user@host`), so per-user marks can be added later
  if colleagues use the board.

### 3. Token use moves to a new page: Statistics (`/stats`, Q3)

- The "Tokens, last N days" section moves to `/stats` unchanged: the quota
  line, the summary, the chart, and the per-project table with its 1/7/30
  switch and "more projects".
- **The Boards table on the Overview does not change**: the same columns,
  including Cost, Context and Per day, with its own 1/7/30 switch (the
  `days` the table uses).
  - The switch moves from the old token heading to the Boards heading.
- The Spend and Weekly quota tiles link to `/stats`.
- The side tab gets "Statistics" below Overview, next to All packets.
- Links to `/?days=…#tokens` become `/stats?days=…`.

## Steps

- [ ] O1. Packet metadata:
  - `stopped`, `seen` in `schema.STATUS_FIELDS`, `STATUS_OPTIONAL` and the
    validator; spec (`docs/spec.md`) and `docs/packet-format.md`;
  - the executor sets `stopped` on a commit to COMPLETED and on a system
    pause, and clears it on RUNNABLE;
  - `executor.mark_seen` with the `seen` journal record;
  - the history store keeps both fields and the record (check `history.py`
    harvest);
  - tests.
- [ ] O2. `data.overview`: rows of kind `done` and `stopped` (the tree
  check, outcome from `report.of_packet`, the run's cost, `[pr]`); the Done
  tile.
- [ ] O3. Routes and CLI:
  - `POST /seen` (projects, or all, with CSRF);
  - the project pages mark seen on GET when the project is unread
    (`project_page`, `packet`, `step`, `live_view`; a lease that is held
    means skip, not fail);
  - `wpk seen`;
  - tests: open → gone; dismiss, select, all; next task → gone; stops
    again → back; a child still running → not yet listed; an old packet
    without `stopped` → not listed.
- [ ] O4. `overview.html`: the rows, the selection bar (only when there
  are such rows), the tile; select-all and ticks that survive refresh
  (`overview.js`, or shared with `packets.js`).
- [ ] O5. `/stats`:
  - `stats.html` holds the token section moved from `overview.html`;
  - the Boards table and its window switch stay on the Overview;
  - side-tab entry, tile links;
  - update tests `test_dash.py::test_pages` and `test_token_panels`.
- [ ] O6. Docs (`docs/overview.md` §2 and §6, `docs/boards.md` Dash);
  check the page in a browser at 1400 and 1100 wide.

## Decisions (2026-10-28)

- Q1. STOPPED (a root paused by the system for a budget or limit) counts,
  as well as COMPLETED.
- Q2. Per project, and only once the whole project has stopped.
- Q3. The new page is **Statistics** (`/stats`).
- Q4. One shared "seen" for now.
- Q5. "Stopped" and "seen" are stored with the packet's runtime metadata,
  not in a dashboard file and not guessed from times.
- The Boards table on the Overview stays as it is.

## Status

- 2026-10-28: plan written.
- 2026-10-28: finished work goes in Needs attention, not a new section.
- 2026-10-28: decisions Q1–Q5 taken; the seen and stopped marks moved to
  packet metadata; the Boards table kept as it is.
