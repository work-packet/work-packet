# Dashboard on the history store, then removing finished runs (plan and status)

Started 2026-10-28. Follows `docs/implementation-v1.md` (cards, history
store, migration: done). Covers design P3 (the view model reads history)
and migration M3 step 5 (delete harvested run directories). This file is
the working plan; update it as each step finishes.

**Goal.** Every dashboard page for a finished packet renders the same
from the history store as from its run directory, so the 14 harvested
run directories can be deleted (about 15 GB) without losing anything
the dashboard shows. Active packets keep reading their live directories.

**Hard rules.**
- Nothing is deleted without an explicit go from Matt, given for this step.
- Deletion is per packet and only after its checks pass (D6).
- Statistics stay identical: `wpk history verify` and the 20-form
  `wpk stats` comparison are re-run before and after deletion.

## Where things stand

- The history store holds, for each harvested packet: its rows in
  `history.db` (packet, step, file, task, question, edge…), a `.wph`
  archive, and every file of the record in the blob store (3,080 files,
  96 MB, all verified). `wpk stats` already falls back to it.
- **`work/` is not archived** (`history.SKIP_DIRS`). It holds the
  workspaces and is most of the 15 GB (largest: 6.6 GB, 2.1 GB, 1.8 GB).
  Its git state (url, branch, head) is recorded on the card by
  `migrate.workspaces()`; M0 pushed branches and made bundles. A
  workspace may also be a plain folder (not git), and that content would
  be lost by deletion unless it is captured. Handled in D5.
- The dashboard reads run directories directly: `dash/data.py` (~95 file
  reads: `steps`, `packet`, `report`, `deliverable`, `task`,
  `state_file`, `step`, `transcript`, `activity`, `log`, `outline`…),
  `dash/app.py` (~39), `dash/plan.py` (~15), `dash/tokens.py` (~5).
  Most go through `Packet(os.path.join(entry["path"], "packets", wpid))`.

## Approach

Put one reader between the dashboard and the record, with two backends:

- **directory**: today's behaviour, for active packets and anything not
  harvested;
- **history**: `history.db` + blob store, for harvested packets. It
  answers `exists`, `listdir`, `read_bytes`/`read_text`, `stat`
  (size, mtime) for a path relative to the run directory from the
  `file` table, and `journal()`/`load_status()` from the stored copies.

The dashboard picks the backend per packet: directory if it exists,
otherwise history. Pages then don't care where the record lives, and a
deleted run looks the same as a present one. (Considered instead:
re-materializing deleted runs into a cache directory on demand. Simpler
to wire, but it re-creates files on disk and hides missing data until a
page is opened; kept as a fallback if the reader turns out to be too
invasive.)

## Steps

- [ ] D0. Survey: list every filesystem read in `dash/` (and anything
      it calls: `report`, `packet`, `journal`, `stats`) with the page
      that uses it. Note which need data the history store doesn't hold
      (e.g. anything under `work/`, mtimes, symlinks). Output: a table in
      this file.
- [ ] D1. The reader: `RunReader` with directory and history backends,
      the same answers for the same run (test: every path of a fixture
      run, compared byte for byte and listing for listing).
- [ ] D2. Fill gaps found in D0: store whatever the dashboard needs that
      the history store lacks (e.g. file mtimes, the deliverable index),
      with a re-harvest that adds it to the 14 existing packets without
      changing their statistics.
- [ ] D3. Switch `dash/data.py`, `plan.py`, `tokens.py`, `app.py` to the
      reader. Board, tree and overview read finished packets from
      `history.db` when the directory is gone.
- [ ] D4. Page-equivalence test: render every dashboard page for a
      fixture project, delete `packets/`, render again, compare. Then the
      same against the real projects, using a scratch copy of the run
      directories moved aside (not deleted); outputs kept in
      `~/.work-packet/migration/dash-verify/`.
- [ ] D5. Workspace gate, per packet: every repo in `work/` is clean
      with its head on a pushed branch or in an M0 bundle; anything that
      is not git (plain folders, untracked files) is listed for Matt to
      keep, archive, or drop. Output: a report in
      `~/.work-packet/migration/workspaces.md`.
- [ ] D6. Deletion, with Matt's go: for each harvested packet passing
      D4 and D5, move its run directory to a trash area first
      (`~/.work-packet/trash/<id>`), re-run `wpk history verify`, the
      stats comparison and D4 on the real dashboard; repoint or remove
      `~/.work-packet/runs/<id>`; then empty the trash after a waiting
      period Matt chooses.
- [ ] D7. Docs and status: `docs/migration-v1.md` (M3 done),
      `docs/work-data-design.md` (P3 status), this file.

## Open questions

- Q1. Trash waiting period before final delete (suggest one week).
- Q2. Plain-folder workspace content found in D5: archive into the blob
      store, or drop?
- Q3. Should the dashboard mark packets shown from history (e.g. an
      "archived" badge), or look identical?

## Not in this plan

- The executor writing card entries live (P2). Until it is done, re-run
  `wpk migrate pss-registers-up-planning` to refresh the active card.
- Moving pss-registers-up-planning into a task folder (M2), M4.

## Status

- 2026-10-28: plan written; nothing started.
