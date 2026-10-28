# Run binding: the card is the packet (plan and status)

Started 2026-10-28. Design P2 "run binding" (`docs/work-data-design.md`
§5.1, §13, phase table), with one change decided by Matt (below). Follows
`docs/implementation-v1.md` (card format, history store, migration) and
`docs/dash-history-v1.md` (dashboard on history, live cards). This file is
the working plan; update it as each step finishes.

## Why

`wpk new` and the executor still use the v0.2 layout. A new packet such as
solver-research gets `project.toml`, `prompt.md`, `identity/`, `state/`,
`work/` and `packets/<id>/…`, with `solver-research.wp.md` beside them as
a view rebuilt from the journal (livecard). The goal: **a task folder holds
the card and the task's repos, and nothing else you need to look at.**

## Decision: runs live in the task folder

The design put runs in `~/.work-packet/runs/<id>/`. **Changed:** home
directories are often severely limited, and runs (transcripts, step
snapshots, worktrees) grow. Runs live with the task:

```
solver-research/                    the task folder
  solver-research.wp.md             the card: front matter, brief, thread
  <repo>/ …                         the task's repos, cloned with IVPM
  .work-packet/
    runs/<id>/                      the run: today's packet directory
      status.md  memento.md  journal.jsonl
      state/  steps/NNNN/  mailbox/  .lease  .pending/
      work/  (only for split mode; see R3)
      sub/<name>.wp.md              cards of sub-packets it made
    runs/<child-id>/                a sub-packet's run, beside its root's
```

The rule: **a packet's run is `<folder of its card>/.work-packet/runs/<id>/`.**
Nothing else is needed to find it: the card gives the id, the id gives the run.

**The run is the record, not the work.** What a step produces (build
output, logs, waveforms) is written where the work happens, in the repos
at the top of the task folder. Opening the task folder in an IDE shows it.
For example, fw-picorv32's waveforms today are at
`<project>/packets/c2986270-…/work/fw-picorv32/rundir/…/waves.fst`; in the
new layout they are at `fw-picorv32/fw-picorv32/rundir/…/waves.fst`.
`.work-packet/runs/<id>/` holds only the journal, status, steps (summaries,
diffs, transcripts, meta) and state: what the dashboard and history read,
and rarely opened by hand.

Consequences:
- **Moving the task folder moves the run with it.** The index is
  refreshed by discovery, as before.
- **`~/.work-packet/` holds only small global things:** the registry, the
  index, config, and locks. The history store and blobs are not small (R10).
- **The run still never travels** (§13.3). A hand-off, bundle or copy of a
  task folder excludes `.work-packet/runs/`, and the card carries the pins.
- **Deleting a task folder deletes its run,** so `wpk done` must harvest
  first (R8). That is already the design's order.
- **The `~/.work-packet/runs/<id>` links** made by the migration are retired.
  Legacy projects are found through the registry, new ones through the
  index (R1).

## Steps

- [ ] R0. **Survey and design update.**
  - Survey (agent): every place that builds a run path from a project
    (`os.path.join(entry["path"], "packets", wpid)`, `Packet(...)`,
    `registry.find_packets`, `views.packets`, scheduler, stats, setup/
    workspace `tg.work`/`tg.packet_work`) and what a "project" supplies
    (`project.toml` keys, `prompt.md`, project-level `state/`, `identity/`,
    `work/`).
  - Settle the workspace model in the new layout (Q5).
  - Update `docs/work-data-design.md` §5.1, §13, §13.3, §14 and the P2
    row; `docs/migration-v1.md` M2 (pss-registers-up-planning becomes a task
    folder with its run inside it).
- [ ] R1. **Locator** (`runs.py`): one function from a target (card path,
      task folder, name, id, or legacy project) to a *binding*:
      `{card, id, task_dir, run_dir, legacy}`. For a legacy project,
      `run_dir` is `<project>/packets/<wpid>`. The index gains `run_dir`.
      Tests: both layouts, moved task folders, sub-packets.
- [ ] R2. **The card carries the configuration.** `project.toml` keys
      (model, permissions, profile, harness, tz, budget, schedule) go into
      the card's front matter. Standard keys where the design has them
      (`setup`, `budget`, `due`), `x-wpk` for the rest. `prompt.md` becomes
      the brief. One loader gives the executor the same settings object
      from either a card or a `project.toml`. Test: a v0.2 project's settings
      equal its converted card's.
- [ ] R3. **`wpk new`.**
  - `wpk new <repo> "<title>"` makes `<name>/`, clones the repo into it
    with IVPM on branch `wpk/<name>` (§5.2), and writes the card and the
    run's initial `status.md`/`journal.jsonl`.
  - `wpk new "<title>"` with no repo makes a folder with only the card.
  - `wpk new --here` in an existing clone (Q2).
  - The runner works in place on the task folder's repos, so its outputs
    (e.g. `rundir/`) are in plain view. Checkouts for parallel sub-packets
    and split mode stay visible too (Q6).
- [ ] R4. **The executor runs from a binding.**
  - `executor.step/admin` take any target R1 resolves.
  - At its event points the executor appends the card entries itself:
    `accepted`, `question`, `note`, `result`, `request` on hand-off.
    It writes through `card.append`, keyed so a rebuild adds nothing.
  - The journal stays the executor's own record. For new packets livecard
    only checks that a rebuild from the journal adds nothing (a test
    assertion, and `wpk card check --against-journal`). For legacy projects
    it keeps mirroring as now.
- [ ] R5. **Scheduler, registry, stats.**
  - The scheduler's due list, `budget.ledger`, `stats.collect`, `wpk
    stats`, `history` sync and harvest all enumerate both legacy projects
    (registry) and cards (index).
  - Board membership is the card's `board` tag.
  - Statistics guarantee: the stats of a converted project are
    byte-identical before and after (same check as the migration).
- [ ] R6. **Dashboard.** Replace the run-path constructions found in R0
      with the R1 locator, so pages take a binding instead of
      `entry["path"] + "/packets/" + wpid`. New packets show on the board
      from the index. The page-equivalence crawl (`dash/crawl.py`) must
      give identical pages for a converted project.
- [ ] R7. **Sub-packets.**
  - A child's run goes in `<task>/.work-packet/runs/<child-id>/`.
  - Its card goes in `runs/<root>/sub/<name>.wp.md`.
  - Its address is `<root>.<child>` (already in the index).
- [ ] R8. **Done.** `wpk done`:
  - harvest (archive, load, verify);
  - pin and freeze the card;
  - check that the repos are pushed (the D5 workspace gate, reused);
  - move the card to the archive;
  - delete the task folder, run included, with its own confirmation.
- [ ] R9. **Convert: solver-research first.** `wpk convert <project>`
      rewrites a v0.2 project in place, renaming on one file system and
      copying nothing:
  - `packets/<id>/` → `.work-packet/runs/<id>/`;
  - `project.toml` and `prompt.md` → the card (R2);
  - project `work/<repo>` → `<repo>/` at the top (Q5);
  - the empty template folders (`identity/`, `state/`) removed.

  It records what it did in the card (`note`, `Migrated-From`), re-registers
  the project in the index, and verifies: stats identical, pages identical,
  `wpk check` clean. Dry run first. solver-research is new and small, so it
  is the first case.
- [ ] R10. **Home-directory space.** Make the roots of the history store,
      the blob store and the archived-project cache configurable
      (`config.toml`), defaulting to `~/.work-packet/`. Report their sizes
      in `wpk history list`. Today: blobs 101 MB, history 4 MB, cache ~100
      MB, migration bundles and the records tarball (Q4).
- [ ] R11. **M2: pss-registers-up-planning**, only after R9 has run
      cleanly on solver-research and with Matt's go (it is the long-running
      live packet; G6 in `docs/migration-v1.md`).
- [ ] R12. Docs and status: this file, design doc, `README.md` usage.

## Open questions

- Q1. Name of the hidden folder: `.work-packet/` (proposed; matches
      `~/.work-packet/`), or `.wpk/`.
- Q2. `wpk new --here` in an existing clone. Proposed:
      `<clone>/.work-packet/` with an entry in `.git/info/exclude` (never
      `.gitignore`, which is shared), and the card beside it.
- Q3. A workspace-less card (`~/packets/<name>.wp.md`) has nowhere to put
      a run. Proposed: it gets its own folder (`~/packets/<name>/`) the first
      time it runs, as §5.1 already says for workspaces. The rule "the run
      is next to the card" then always holds.
- Q4. Where the history store and blobs live by default, given home-space
      limits. Proposed: stay in `~/.work-packet/` but configurable (R10).
      Or a per-machine data directory set at first run.
- Q6. Checkouts of sub-packets that work in parallel must stay visible
      for human inspection (their build output and waveforms). Proposed:
      `<task>/<repo>@<child>/` beside the main checkout, not under
      `.work-packet/`; `wpk ide` opens the task folder with them as extra
      roots. Same for split mode's scratch worktrees.
- Q7. Human and runner sharing a checkout: the IDE action pauses the
      packet first (as the dashboard's IDE button does today); a step that
      fails resets the repo, so nothing is changed by hand while a step
      runs. Keep this rule, and make `wpk ide` apply it too.
- Q8. Ignored outputs (`rundir/`, `build/`) are not in the record and
      vanish when `wpk done` deletes the task folder. Proposed: `wpk done`
      lists ignored outputs and their sizes and asks; listed deliverables
      are archived (≤ 10 MB, as now); larger ones become attachments in
      the blob store (P5).
- Q5. Workspace model. v0.2 has the user's clones in the project's
      `work/` and the packet's clones or worktrees in `packets/<id>/work/`.
      The design says the runner works in place in the task folder's repos.
      R0 settles how steps' worktrees, resets on failure and `heads` map
      onto that. The answer decides R3 and R9.

## Not in this plan

Requests between packets (P4), S3 blobs (P5), hand-off bundles (P6), the
TUI (P8), bridges (P9, P10). D6 (deleting the harvested v0.2 runs) is
tracked in `docs/dash-history-v1.md`.

## Status

- 2026-10-28: plan written; runs-in-task-folder decided; nothing started.
- 2026-10-28: added: the run is the record, outputs stay in the visible
  checkouts (fw-picorv32 waveforms as the example); Q6–Q8.
