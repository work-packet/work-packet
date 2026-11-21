# Assessment: the outline on the packet's main page

Status (2026-11-21): proposal steps 1-5 built, plus the open-items flag (6).
Board cards are not started.

Built: `templates/_outline.html` (style, panel, Snapshot line), used by `live.html`,
`packet.html` and `project.html`/`_snapshot.html`; `data.outline()` now also returns
`mtime`, `open` and `segments` (`_outline_segments`). Folding is by runs, not by
top-level group: real outlines are mostly flat (`0a`, `0b`, `1a`…), so a run of
3+ done items folds to one line once the outline is over 12 items. Tests:
`tests/test_dash.py` `test_outline_*`.

## What is there today

- **One reader, one page.** `data.outline(pkt)` (`dash/data.py:1752`) parses
  `state/outline.md` (or, failing that, the first `state/*.md` with two or more
  `- [ ]` lines) into entries with depth, state, a plain title and the
  current item. Only `data.live()` calls it (`data.py:1807`), so only the Live
  view shows it (`templates/live.html:108-116`: done/total, a bar, the
  indented checklist, a link to the Plan tree).
- **The project page** (`/p/<name>`, `project.html` + `_snapshot.html`) has
  no plan at all: directory, task counts, spend, board, last step and the
  step timeline.
- **The task page** (`/p/<name>/<wpid>`, `packet.html`) mentions the outline
  only as a link (`packet.html:166`, "Live view: … the outline …"). The file
  itself is in *State files* as raw Markdown in a `<pre>`, and that block is
  closed when there are more than 5 files or the file is over 2000 bytes,
  which is the usual case for a real outline (pssc-debug's is ~7.7 KB).
- **The Plan page** (`/plan`) shows the tree and how it changed step by
  step. It is good for history, but it is a separate click, and it doesn't
  answer "where does it stand" at a glance.

## Assessment

You're right, and it's a gap more than a design choice:

1. **The outline is current when nothing is running.** It isn't live data.
   `checkpoint.tick` marks items done during work by hand, the scribe reads
   it, and runner steps commit it. At rest it is the best single answer to
   "where does this packet stand". The Live view is the wrong place to keep
   it, because that page is about the running step (feed, processes, the
   step's own todos).
2. **The design already planned it.** `docs/packet-page.md` §3 says to put
   "Snapshot first: state, step, outline done/total…". Nobody built that
   part.
3. **The raw file in State files doesn't do the job.** It is closed by
   default, shows dates and detail bullets instead of the plain titles from
   `_plan_title`, and has no current-item marker and no progress figure.
4. **It costs almost nothing.** `outline()` lists `state/` and reads a few
   small files, a negligible cost next to what both pages already load.

## Proposal

1. **`_outline.html` macro.** Move the block in `live.html:108-116` into a
   macro, `panel(e, wpid, ol, fold=False)`, and have the Live view call it
   unchanged.
2. **Project page.** In `project_overview` (`app.py:~1043`), compute
   `outline` for the root packet and render it straight after the Snapshot.
   Also add a `Plan  7 of 12 · ▶ 3b Parser` row to the Snapshot's `kv2` grid,
   so the headline is there even with the panel folded.
3. **Task page.** In `data.packet()`, add `"outline": outline(pkt)` and render
   the panel above the Status/State-files grid, in place of the line-166
   links (keep the Plan link in the panel header, as Live does).
4. **Folding for long outlines** (`fold=True` on the two main pages). With
   up to ~15 items, show them all. Above that, show top-level items. A top-level group that is all
   done collapses to one `<details>` line ("✓ 1 Setup (4/4)"), and the group
   that holds the current item is open. The Live view keeps the full list.
5. **"As of".** On the main pages, put the outline file's mtime (or "updated
   by step N") in the header. That matters at rest, when the file may be days
   old.
6. **Flag a mismatch.** If the packet is COMPLETED or closing and items are
   still open, say so in the panel header ("3 items still open"). This fits
   the close check in `docs/close-remove-plan.md`.

### Open choices (my recommendation first)

- **Which outline on the project page:** the root packet's only. Children
  each have a task page, and the Tasks table already gives their state.
  Merging child outlines into the project view is the Plan tree's job.
- **Fallback heuristic** ("first `.md` with a checklist"): keep it, since the
  panel names the file it read. If it misfires on the main page, drop the
  fallback there and show only `outline.md`.
- **Board cards:** leave them out for now. A `7/12` chip would be nice, but
  the board renders many cards and was just made quiet (`49addb8`). Cards
  would need a cached count (mtime-keyed) first. That would be a separate
  step.

## Tests

`tests/test_dash.py` already builds packets with outlines. Add:

- The project page and the task page show "N of M done" and the current
  item for a packet that has `state/outline.md` and nothing running.
- A long outline folds its done groups on the main page but not on Live.
- With no outline, the main pages show nothing, rather than Live's "No
  checklist" hint.
