# Plans on the board, as a tree

Status: built (2026-10-26); see Status at the end.

## What a plan is today

- **The outline (`state/outline.md`).** The model writes and edits this nested
  Markdown checklist each step, following `instruct-outline.md` / `protocol.md`
  ("Working through a plan").
  - Markers: `[ ]` pending, `[>]` active, `[x]` done, `[-]` deferred, `[+]` added, `[~]` partial.
  - Each item has an id such as `4` or `4a`.
- **Sub-items come in two forms:**
  - indented lines (`  - [x] 4a ...`), as in fw-picorv32;
  - inline inside the parent's text (`[x] 3a ...; [x] 3b ...`), as in fw-proto-axi-opus.
- **Where the dash shows it:** only on the live page, as a flat-ish list (`data.outline()`). Inline sub-items are not split out.

## Where the sequence comes from

There is no explicit plan history, but every version can be recovered.

1. **Batches.** `wpk next` / `continue` archives the outline to `state/history/outline-<batch>.md`, and the journal's `handoff` record names it.
2. **Steps within a batch.** Each `steps/NNNN/prompt.md` holds the outline as it stood when that step started (under "State files"). The current `state/outline.md` is the last version.
   - The fallback is `steps/NNNN/state.diff`, applied in reverse from the current outline, for when the prompt copy was truncated (8 KB cap).
3. **Linking steps to items.** A step's memento `item:` names the plan item it worked on. This already drives the "By plan item" cost table.

## Proposal

**Parser: `dash/plan.py`, `parse(text) -> [Item]`.** Each `Item` holds `id`, `state`, `text`, `children` and `line`.
- Continuation lines join their item.
- Inline `[x] 3a ...` markers split into child items.
- The title, legend and a trailing non-checkbox section (such as "Regression") are kept as notes.

**Versions: `plan.versions(packet)`.**
- Ordered: batch 1 steps…, the batch-1 archive, batch 2 steps…, current.
- Consecutive identical versions are dropped.
- Each version is tagged with its step number and memento `item`.

**Page: `/p/<project>/<wpid>/plan`.**
- **Tree.** Nested `<details>`/`<summary>`: collapsible with no JS, and fine under the CSP.
  - Open by default: the active item and the path to it. Done subtrees start closed.
  - Each node shows a state icon, its id, its text as inline Markdown, and a rolled-up count (`3/5`).
  - Each node also shows the steps that worked on it (with links) and the item's cost.
  - Links: `state/notes/<id>.md` when it exists, through the markup view.
  - Buttons: Expand all / Collapse all.
- **Sequence.**
  - A strip of versions down the side, grouped by batch, with each batch's hand-off instruction as its header.
  - Picking a version shows that tree, marked against the one before it: new items, state changes (`[ ]→[x]`), items deferred, items dropped.
  - "Changes only" filters the tree to those items.
- **Children.** Spawned packets' outlines nest under a "Children" node.
  - Nothing links a parent item to the child it spawned, so they are not placed under items.
  - Recording an `item:` on `spawn` would fix that later.

**Later:** the live page could use the same tree instead of its flat list (not done; it links to the plan page).

## Status

Built (2026-10-26):

- `dash/plan.py`: `parse`, `versions`, `undo`, `from_prompt`, `compare`, `page`.
- `templates/plan.html`, route `GET /p/<project>/<wpid>/plan`:
  - `?v=<key>`: the version to show (`s<n>` is after step n; `b<n>` is the start of batch n).
  - `?changes=1`: only what changed.
  - `?open=all|none`: expand or collapse everything (no JS).
- Links to the plan from the packet page and the live page's Outline heading.
- `state/` files open in the file view: `/p/<project>/<wpid>/file?path=state/...`.
  - The plan links each item's `state/notes/<id>.md` there, and the latest `outline.md`.
  - These files can be marked up (docs/doc-markup.md) only while the runner leaves the packet alone (COMPLETED, NEEDS_INPUT, PAUSED, FAILED, with no step in flight). A step replaces `state/` when it commits, so an edit made while one runs would be lost.

Parsing details:
- A `+ ...` line right after an item's text is taken as a wrapped line, not a bullet.
- Sub-items written inline are split out only when the marker is followed by an id (`[x] 3b ...`).
- The current item is the deepest active one, else the first leaf still to do.
- A step's cost is split evenly over the items its memento names, and each item shows its share.

Tests: `tests/test_plan.py`, using the fake model's `planner` behaviour. It runs once with the outline shown in each prompt, and once padded past the prompt's 8 KB cap so that versions have to undo diffs.

Checked on real packets: fw-proto-axi-opus (16 versions, inline sub-items), fw-picorv32 (batch 1 archived to history), dvs-enh (outline too big for the prompt, rebuilt from diffs).

Not done:
- Child packets are listed under "Children" with their current outline, not placed under the item that spawned them; the spawn record names no item.
- The live page still shows the flat list; it links to the tree.
