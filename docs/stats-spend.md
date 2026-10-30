# Spend by board on Statistics (plan and status)

Started 2026-10-29. Status: **built** 2026-10-29 (B1–B3).

## Why

`/stats` showed the cost of each board as a number in the By board table.
That made it hard to see at a glance where the money went, or which board
drove a day's spike.

## Decision: bars, not a pie

- People compare lengths on a shared baseline far more accurately than
  angles. With 4–8 boards, slices at 18% and 23% look the same.
- A pie is only readable with about five slices. Bars still work with a
  dozen, and with a long tail of small boards.
- Each bar is labelled `$41.20 · 38%`, so the "share of the whole" that a pie
  shows is still there.
- Bars extend to spend per day stacked by board, and later to a split by
  project. A pie can't do either.

## What was built

- **`tokens.spend(by_board, dates, on)`** (`dash/tokens.py`), returned as
  `burn.spend` by `tokens.board`:
  - `bars`: one per board that spent anything, biggest first, with `cost`,
    `share` of the total, `w` (its length against the biggest) and `cls`
    (colour `sp0`..`sp7`, reused after eight boards).
  - `idle`: the boards that spent nothing in the window.
  - `chart`: spend per day stacked by board (`unit="usd"`, so the axis
    reads in dollars). Each day's tooltip splits the total by board. It is
    None for the 1-day window.
  - `spend` itself is None when nothing was spent.
- **`stats.html`, By board section** (`#spend`), shown when there is more
  than one board:
  - horizontal bars, each linking to `/b/<board>`
  - a line "$N spent …; nothing on X"
  - the stacked per-day chart
  - then the existing table
- **With a single board**, the page shows a plain "Spend per day" chart under
  "Context read per day".
- **Colours** `--sp0`..`--sp7` in `base.html`, with dark-mode variants.
- Cost counts the same steps as the rest of the page (those with token
  counts, in the window).

## Steps

| # | Step | Status |
|---|------|--------|
| B1 | `tokens.spend` + `chart(unit=)`; money axis in `_tokens.html` | done |
| B2 | Bars, idle note and stacked chart on `/stats`; colours | done |
| B3 | Test `test_boards.py::test_spend_by_board_on_stats` | done |

## Later (not built)

- A By board / By project toggle using the same bars.
- Split each board's bar by project.
