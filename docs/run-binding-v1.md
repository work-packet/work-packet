# Run binding: the card is the packet (plan and status)

Started 2026-10-28. Design P2 "run binding" (`docs/work-data-design.md`
§5.1, §13, phase table), with changes decided by Matt (below). Follows
`docs/implementation-v1.md` (card format, history store, migration) and
`docs/dash-history-v1.md` (dashboard on history, live cards). This file is
the working plan; update it as each step finishes.

## Why

`wpk new` and the executor still use the v0.2 layout. A new packet such as
solver-research gets `project.toml`, `prompt.md`, `identity/`, `state/`,
`work/` and `packets/<id>/…`, with `solver-research.wp.md` beside them as
a view rebuilt from the journal (livecard). The goal: **the packet is a
folder holding the card and the work, and nothing else you need to look at.**

## Decisions (2026-10-28)

### The clone is the packet

90%+ of the time a packet is one repo, so **the packet folder is the clone**:

```
~/work/fw-picorv32/              a normal git clone, and the packet
  .git/
  fw-picorv32.wp.md              the card
  .work-packet/                  the packet's private data (below)
  src/  flow.yaml  ivpm.yaml
  packages/                      IVPM's dependencies: usually the "other repos"
  rundir/…/waves.fst             outputs, where you look for them
```

- **The card and `.work-packet/` are excluded from git** through
  `.git/info/exclude` (local, never pushed; `workspace.exclude` exists).
  `git status` stays clean and the card is never committed. This reverses
  the design's "card beside the repo, not inside" (§5.1).
- **Guard against `git clean -x`/`-X`,** which deletes ignored files and so
  would wipe the card and the run (plain `git clean -fd` does not). A deny
  rule in the packet's permissions, and nothing in wpk runs it (R0 checks).
- **Multi-repo work** is mostly IVPM dependencies in `packages/` inside the
  clone. A true multi-repo task (the other 10%) is a plain folder as the
  packet, with the clones in it.
- **A packet without a repo** is a folder holding the card and
  `.work-packet/`. You may put files in it (specs, logs, notes) before
  running; they are its workspace. Without git there is no reset after a
  failed step; the run's steps still record what each changed. No packet
  is ever a bare card file (the design's `~/packets/<name>.wp.md` case
  is dropped).

### Runs and the packet's data live in `.work-packet/`

Home directories are often severely limited, so nothing large goes to
`~/.work-packet/`. The design put runs in `~/.work-packet/runs/<id>/`;
**changed:**

```
<packet>/.work-packet/
  runs/<id>/                      the run: today's packet directory
    status.md  memento.md  journal.jsonl
    state/  steps/NNNN/  mailbox/  .lease  .pending/
    sub/<name>.wp.md              cards of sub-packets it made
  blobs/                          the packet's blob store (transcripts, snapshots…)
  <id>.wph                        its archive, once harvested
```

- **The rule: a packet's run is `<packet>/.work-packet/runs/<id>/`.** The
  card gives the id; the id gives the run.
- **`.work-packet/` marks a packet.** Discovery walks up from the current
  directory to the first folder holding `.work-packet/`, as git finds
  `.git` (more robust than looking for `<name>.wp.md`, as the card can be
  renamed).
- **The run is the record, not the work.** What a step produces (build
  output, logs, waveforms) is written in the clone, where the IDE shows it.
  fw-picorv32's waveforms are today at
  `<project>/packets/c2986270-…/work/fw-picorv32/rundir/…/waves.fst`; in
  the new layout, at `fw-picorv32/rundir/…/waves.fst`.
- **Moving the packet folder moves its run.** The index is refreshed by
  discovery.
- **The run never travels** (§13.3): a hand-off, bundle or copy excludes
  `.work-packet/`; the card carries the pins.
- **`~/.work-packet/` keeps only small shared things:** the registry, the
  card index, config, locks, and the shared statistics database
  (`history.db`, metrics only: 4 MB for everything so far), which lets
  `wpk stats` and the dashboard see across packets after their folders
  are gone.
- **When a packet is done** (R8), its archive is copied to the archive
  directory (`~/.work-packet/history/` by default, settable in
  `config.toml` to a big disk), with or without transcripts (a setting;
  they are ~75% of the bytes and rarely reread). Then the folder may go.
- **The `~/.work-packet/runs/<id>` links** made by the migration are retired:
  legacy projects are found through the registry, new packets through the
  index (R1).

### Workspaces

- **One packet: the runner works in the clone,** on the packet's branch
  (`wpk/<name>`, or the current branch with `--here`). No separate
  worktrees; outputs appear where you look.
- **Sub-packets working in parallel** each get a git worktree as a
  **sibling** folder, `../<name>@<child>/`, and that worktree is a packet
  like any other (its own card and `.work-packet/`). `wpk ide` opens the
  packet with them as extra roots.
- **A failed step** resets the clone to the last committed step's head, as
  today. Only tracked files are touched; ignored outputs (`rundir/`) survive.
- **You and the runner share the clone:** opening the IDE (`wpk ide`, the
  dashboard button) pauses the packet first.
- **`wpk done` lists ignored outputs** (`rundir/`, `build/`…) with sizes and
  asks what to keep: listed deliverables are archived (≤ 10 MB, as now);
  larger ones become attachments (P5).

## Steps

- [ ] R0. **Survey and design update.**
  - Survey (agent): every place that builds a run path from a project
    (`os.path.join(entry["path"], "packets", wpid)`, `Packet(...)`,
    `registry.find_packets`, `views.packets`, scheduler, stats, setup/
    workspace `tg.work`/`tg.packet_work`); what a "project" supplies
    (`project.toml` keys, `prompt.md`, project-level `state/`, `identity/`,
    `work/`); how a failed step resets the repo today, and whether anything
    runs `git clean -x`.
  - Update `docs/work-data-design.md` (§5.1 clone is the packet, §7.3 blobs
    per packet, §13 runs in `.work-packet/`, §13.3, §14 archive directory,
    the P2 row) and `docs/migration-v1.md` M2.
- [ ] R1. **Locator** (`runs.py`): one function from a target (packet
      folder or anything inside it, card path, name, id, or legacy
      project) to a *binding*: `{card, id, packet_dir, run_dir, legacy}`.
      Discovery by `.work-packet/`. For a legacy project, `run_dir` is
      `<project>/packets/<wpid>`. The index gains `run_dir`. Tests: both
      layouts, a moved packet folder, sub-packets.
- [ ] R2. **The card carries the configuration.** `project.toml` keys
      (model, permissions, profile, harness, tz, budget, schedule) go into
      the card's front matter. Standard keys where the design has them
      (`setup`, `budget`, `due`), `x-wpk` for the rest. `prompt.md` becomes
      the brief. One loader gives the executor the same settings object
      from either a card or a `project.toml`. The default permissions deny
      `git clean -x`/`-X`. Test: a v0.2 project's settings equal its
      converted card's.
- [ ] R3. **`wpk new`.**
  - `wpk new --here` in a clone writes `<here>/<name>.wp.md` and
    `<here>/.work-packet/`, adds both to `info/exclude`, and starts the run
    on the current branch (or `-b wpk/<name>`).
  - `wpk new <repo-url> "<title>"` clones with IVPM into `<name>/` on
    `wpk/<name>`, then does the same.
  - `wpk new "<title>"` with no repo makes `<name>/` holding the card and
    `.work-packet/`; files can be added before `wpk run`.
  - `wpk new <repo> <repo> …` (multi-repo) makes a plain folder with the
    clones inside.
- [ ] R4. **The executor runs from a binding.**
  - `executor.step/admin` take any target R1 resolves.
  - The runner works in the clone; a failed step resets tracked files only.
  - At its event points the executor appends the card entries itself
    (`accepted`, `question`, `note`, `result`, `request` on hand-off)
    through `card.append`, keyed so a rebuild adds nothing.
  - The journal stays the executor's own record. For new packets livecard
    only checks that a rebuild from the journal adds nothing (a test
    assertion, and `wpk card check --against-journal`). For legacy projects
    it keeps mirroring as now.
- [ ] R5. **Scheduler, registry, stats.**
  - The scheduler's due list, `budget.ledger`, `stats.collect`, `wpk
    stats`, `history` sync and harvest all enumerate both legacy projects
    (registry) and packets (index).
  - Board membership is the card's `board` tag.
  - Statistics guarantee: the stats of a converted project are
    byte-identical before and after (same check as the migration).
- [ ] R6. **Dashboard.** Replace the run-path constructions found in R0
      with the R1 locator, so pages take a binding instead of
      `entry["path"] + "/packets/" + wpid`. New packets show on the board
      from the index. The page-equivalence crawl (`dash/crawl.py`) must
      give identical pages for a converted project.
- [ ] R7. **Sub-packets.**
  - A child that works in parallel gets a sibling worktree
    `../<name>@<child>/`, which is a packet (card, `.work-packet/`, run).
  - A child that only needs a run (no checkout of its own) runs in
    `<packet>/.work-packet/runs/<child-id>/`.
  - In both cases its card is listed in the root run's `sub/`, and its
    address is `<root>.<child>` (already in the index).
  - `wpk ide` opens the packet with the sibling worktrees as extra roots
    and pauses the packet first.
- [ ] R8. **Done.** `wpk done`:
  - list ignored outputs (`rundir/`, `build/`…) with sizes and ask what to
    keep;
  - harvest (archive, load, verify) into `.work-packet/`;
  - copy the archive to the archive directory (transcripts per setting);
  - pin and freeze the card, and keep a copy of it with the archive;
  - check that the branches are pushed (the D5 workspace gate, reused);
  - delete the packet folder, with its own confirmation.
- [ ] R9. **Convert: solver-research first.** `wpk convert <project>`
      rebuilds a v0.2 project in the new shape, renaming on one file
      system and copying nothing:
  - the root packet's clone (`packets/<id>/work/<repo>`, or the project's
    `work/<repo>`) becomes the packet folder;
  - `packets/<id>/` (without `work/`) → `<packet>/.work-packet/runs/<id>/`;
  - `project.toml` and `prompt.md` → the card (R2);
  - the empty template folders (`identity/`, `state/`) are removed;
  - a project with no repo becomes a plain packet folder.

  It records what it did in the card (`note`, `Migrated-From`), registers
  the packet in the index, and verifies: stats identical, pages identical,
  `wpk check` clean. Dry run first. solver-research is new and small, so it
  is the first case.
- [ ] R10. **Home-directory space.**
  - Blobs move to the packet's `.work-packet/blobs/` for new packets.
  - The archive directory and the archived-project cache are configurable
    (`config.toml`), defaulting to `~/.work-packet/`.
  - `wpk history list` reports sizes. The existing shared blob store (101
    MB) and cache (~100 MB) stay until their projects are converted or
    archived.
- [ ] R11. **M2: pss-registers-up-planning**, only after R9 has run
      cleanly on solver-research and with Matt's go (it is the long-running
      live packet; G6 in `docs/migration-v1.md`).
- [ ] R12. Docs and status: this file, design doc, `README.md` usage.

## Questions (all decided 2026-10-28)

- Q1. The hidden folder is **`.work-packet/`** (it sits at a repo root
      beside `.git`, `.github`, `.vscode`, so it should explain itself;
      matches `~/.work-packet/`). It also marks the packet for discovery.
- Q2. `wpk new --here` puts the card and `.work-packet/` in `<here>`,
      excluded in `.git/info/exclude`. With the clone as the packet, this
      is the main way to make one, not the exception.
- Q3. A packet without a repo is a folder (card and `.work-packet/`) that
      may be filled with files before running.
- Q4. The packet's data, blobs included, lives in its `.work-packet/`. The
      shared statistics database stays in `~/.work-packet/` (small). At
      `wpk done`, the archive is copied to a configurable archive directory.
- Q5. The clone is the packet; the runner works in it; parallel children
      get sibling worktrees that are packets themselves.
- Q6. Checkouts of parallel sub-packets stay visible: siblings
      `../<name>@<child>/`, opened as extra roots by `wpk ide`.
- Q7. Opening the IDE pauses the packet first, in `wpk ide` too.
- Q8. `wpk done` lists ignored outputs with sizes and asks; small
      deliverables are archived, larger ones become attachments (P5).

## Not in this plan

Requests between packets (P4), S3 blobs (P5), hand-off bundles (P6), the
TUI (P8), bridges (P9, P10). D6 (deleting the harvested v0.2 runs) is
tracked in `docs/dash-history-v1.md`.

## Status

- 2026-10-28: plan written; runs-in-task-folder decided; nothing started.
- 2026-10-28: added: the run is the record, outputs stay in the visible
  checkouts (fw-picorv32 waveforms as the example); Q6–Q8 decided.
- 2026-10-28: Q1–Q5 decided: the clone is the packet; `.work-packet/` holds
  runs, blobs and the archive; `--here` is the main form; packets without
  a repo are folders; children get sibling worktrees; `git clean -x`
  guarded. Plan rewritten to match. Next: R0.
