# Dashboard on the history store, then removing finished runs (plan and status)

Started 2026-10-28. Follows `docs/implementation-v1.md` (cards, history
store, migration: done). Covers design P3 (the view model reads history)
and migration M3 step 5 (delete harvested run directories). This file is
the working plan; update it as each step finishes.

**Goal.** Every dashboard page for a finished packet renders the same
from the history store as from its run directory, so the 14 harvested
run directories can be deleted (about 15 GB) without losing anything
the dashboard shows. Active packets keep reading their live directories.
(The 14 harvested runs come to 12.0 GB; the 15 GB first quoted included
the active projects.)

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

## Approach (changed after D0)

D0 found the dashboard reads run directories through about 20 modules
(`dash/*`, `report`, `stats`, `questions`, `views`, `notes`, `toolcost`,
`sched/budget`, `setup`…), so a reader passed through all of them was too
invasive. Instead (the fallback named in the first version of this plan):

- **`history.restore_packet` / `restore_project`** write a packet's record
  (every file but `work/`) back from the blob store.
- **`archived.py`**: when a registered project's `packets/` is gone and
  the history store has its harvested packets, the records are written
  once to `~/.work-packet/cache/archived/<project>/packets/`, read-only,
  with the project's other top-level items (`project.toml`…) linked in,
  and the project's entry is pointed there (`archived: true`, `origin`).
  Rewritten when the set of packets changes. ~100 MB for all 14 runs.
- **The dashboard** gets projects through `archived.entries/get` instead
  of `registry.entries/get` (7 call sites); every page is unchanged.
- **Read-only**: the `ArchivedReadOnly` middleware answers 409 to any
  POST under `/p/<project>/` for an archived project (moving it between
  boards still works).
- Whole projects only: a project with a `packets/` directory is read from
  it as before. Finished projects are removed whole, so that is enough.

## Steps

- [x] D0. Survey (agent): every run-directory read and its page. Gaps:
      existence gates (404), `work/`, symlinks (`children/` links only),
      empty dirs (`mailbox/` only), mtimes (scheduler cache key only),
      live state (lease, pids; not needed once finished). Checked on the
      real runs: only `children/` links and empty `mailbox/` occur; the
      dashboard uses neither.
- [x] D1. `history.restore_packet/restore_project`, `archived.py`
      (instead of a reader; see Approach). Test: a restored record equals
      the run's, file for file.
- [x] D2. Gaps fixed:
      - **Bug found**: the harvest skipped a folder named `work` at every
        depth, so step snapshots under `steps/NNNN/deliverables/work/`
        were not archived (2 runs). Now only the top-level `work/` is
        skipped (`history.SKIP_TOP`).
      - Deliverables in `work/` that reports list (`deliverables:` front
        matter) are kept, tier `deliverables`: a listed file; a listed
        folder whole when ≤ 10 MB, otherwise the files in it the report
        links to. 831 files, 5.3 MB.
      - All 14 runs re-harvested; `history verify` identical; the 20
        `wpk stats` forms byte-identical (`~/.work-packet/migration/verify2/`).
- [x] D3. Dashboard switched (`archived.entries/get`, the middleware).
- [x] D4. Page equivalence.
      - Fixture test (`tests/test_dash_history.py`): every page of a
        finished project, crawled, is identical after `packets/` is
        removed; POSTs are refused; linked `work/` deliverables still open.
      - Real projects (`scripts/dash_history_verify.py`, on a scratch
        registry linking to the real data; nothing moved): 1,744 pages over
        11 projects; output `~/.work-packet/migration/dash-verify/`. The e7
        projects are identical. Every other difference comes from `work/`
        being gone or from the archive being read-only:
        state files show "read-only"; the "Packet worktree" IDE button
        goes; the compose page's workspace checks change; two listings of
        whole repo folders (`work/fw-uart16550`, `work/verilator-efficient-waits`,
        GBs each) are 404. Statistics, steps, tasks, cost pages: identical
        apart from the IDE button.
- [x] D5. Workspace gate (`scripts/workspace_gate.py`, report
      `~/.work-packet/migration/workspaces.md`): 14 runs, 12.0 GB.
      **11 safe (8.2 GB)**: every repo clean and on a remote or in an M0
      bundle (or no `work/`). **3 need a decision** (Q2):
      - dv-solve-simbench `bfc29450`: `work/b9-dumps`, not git, 1.5 MB;
      - dvs-enh `2454b9ba`: `work/dv-solve/out`, untracked, 2.7 KB
        (its `.scratch_*` files were saved by M0);
      - fw-picorv32 `c2986270`: `work/tools`, not git, 781 MB of
        toolchains (gcc-riscv, Verilator builds), can be rebuilt.
- [ ] D6. Deletion: **waits for Matt's go.** Per project: move the run
      directories to `~/.work-packet/trash/<id>`, re-run `history verify`,
      the stats comparison and the page check; remove
      `~/.work-packet/runs/<id>` links; empty the trash after the waiting
      period (Q1).
- [ ] D7. Docs: `docs/migration-v1.md` (M3), `docs/work-data-design.md`
      (P3) once D6 is done.

## Then: the executor writes the card (P2)

Matt does not want to re-run `wpk migrate` by hand. After D0–D5 (D6
waits for the go), the executor keeps the card current itself.

- [x] E1. Hooks: `journal.append` marks the packet (every writer: executor,
      config, requests, seeding, dispatcher); `livecard.flush` runs at the
      end of `executor.step` and `executor.admin`, after each dashboard
      POST (background thread), and at process exit. One code path with
      `wpk migrate`: `migrate.keep_project` rebuilds the thread from the
      journal and merges it, so a live card is what a migration would write.
- [x] E2. Per-project lock (`locks/keep-*`); failures are logged and never
      fail a step; the next flush catches up (it rebuilds from the whole
      journal). `WPK_NO_LIVECARD=1` turns it off.
- [x] E3. Metrics synced provisionally after each change; when every
      packet of a project is COMPLETED each is harvested (archive, load,
      verify) unless its harvest is current. A resumed finished project
      becomes provisional again (`history.sync(replace=True)`) until it
      completes again.
- [x] E4. `tests/test_livecard.py` (5): the card is written step by step;
      the live thread equals a fresh `wpk migrate`; completion harvests and
      `verify_project` is clean; `continue` after COMPLETED makes it
      provisional with a `request` entry; a failing update never fails a
      step and is caught up; unregistered/disabled projects are untouched.
      Real data: `livecard.update_project` on pss-registers-up-planning,
      task2, e7-1 in 0.2 s; `history verify` identical.
      Also: `sub/` (sub-packet cards) added to the packet format's known
      entries (`check.py`), as the validator warned about it.

## Open questions

- Q1. Trash waiting period before final delete (suggest one week).
- Q2. The three items D5 found (b9-dumps 1.5 MB, dv-solve/out 2.7 KB,
      fw-picorv32 tools 781 MB): suggest archiving the two small ones
      into the blob store and dropping `tools` (rebuildable).
- Q3. Should the dashboard mark packets shown from history (e.g. an
      "archived" badge, and hide the compose/hand-off controls that now
      answer 409), or look identical?

## Not in this plan

- Moving pss-registers-up-planning into a task folder (M2), M4.

## Status

- 2026-10-28: plan written.
- 2026-10-28: D0–D5 done; full suite 768 passed, 4 skipped. D6 waits for
  the go and Q1/Q2. Next: E1–E4.
- 2026-10-28: E1–E4 done; full suite 773 passed, 4 skipped. Cards and
  history now stay current without `wpk migrate`. Left: D6 (go, Q1, Q2),
  D7, Q3.
