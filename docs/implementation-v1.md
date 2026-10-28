# Implementing cards and migrating today's packets (plan and status)

Started 2026-10-28. Design: `docs/work-data-design.md`; migration plan:
`docs/migration-v1.md`. This file is the working plan, kept current so
a fresh session can pick up from it alone.

**The hard requirement: every statistic is preserved.** After
migration, `wpk stats` (every rollup), and the token dashboard's
figures, must come out the same whether read from the runs or from the
history store, and must survive the run directories being removed.

## Scope of this pass

| Piece | Design | What is built |
|---|---|---|
| Card format | §6, P1 | `card.py`: parse (lenient), render (canonical, round-trips), append (locked, atomic), state, JSON form; ULIDs |
| Blob store | §7.3, P5 (directory backend only) | `blobs.py`: content-addressed files under `~/.work-packet/blobs/` |
| History store | §14, P7 | `history.py`: SQLite database, `.wph` archives, load, rebuild, read back as `stats.Step` |
| Index | §5 | `index.db`: cards by name, id, path, state |
| Migration | migration-v1 M1 + M3 steps 1–4 | `migrate.py`, `wpk migrate`: cards from journals, `runs/<id>` links, harvest of finished projects **without deleting anything**, provisional rows for the active one, and a verify that compares every statistic |
| CLI | §15.4 | `wpk migrate`, `wpk card` (show/check/list), `wpk history` (rebuild, verify), `wpk stats --history` |

Not in this pass: deleting run directories (M3 step 5, needs your go),
moving pss-registers-up-planning into a task folder (M2), the executor
writing card entries live (P2), requests, bridges, the TUI.

## Steps

- [x] 1. `card.py` and tests (round-trip vectors, lenient parse, state)
- [x] 2. `blobs.py`, `history.py` (schema, archive, load, read back) and tests
- [x] 3. `migrate.py`: card from a v0.2 project; harvest; verify; tests on fixture projects
- [x] 4. CLI commands
- [x] 5. Dry run over the real projects; read the cards
- [x] 6. Real migration; `--verify` must report every project identical
- [x] 7. `stats` falls back to the history store for a project whose runs are gone; tested
- [x] 8. Full test suite (763 passed, 4 skipped); commit and push

## What was built

| File | What |
|---|---|
| `src/work_packet/card.py` | the card format: `parse` (never raises), `render` (canonical), `append` (locked, atomic, idempotent), `merge`, `derive_state`, `check`, `find_up`, ULIDs |
| `src/work_packet/blobs.py` | directory blob store, `~/.work-packet/blobs/sha256/ab/<sha>` |
| `src/work_packet/history.py` | `history/history.db` (tables `packet`, `step`, `file`, `task`, `question`, `edge`, `tag`, `job`, `call`), `.wph` archives, `harvest`, `sync` (provisional), `rebuild`, `collect` (the same shape as `stats.collect`), `verify_project` |
| `src/work_packet/index.py` | `index.db`: cards by name (`<root>.<child>` for sub-packets), id and path |
| `src/work_packet/migrate.py` | the thread rebuilt from journals; cards; `runs/<id>` links; harvest or provisional load; verify |
| `stats.py` | `Step.tools`, `tool_attrs()`; `collect` reads the history store for a project whose `packets/` is gone |
| `cli.py` | `wpk migrate [--dry-run] [--print NAME]`, `wpk card list/show/check/fmt`, `wpk history list/verify/sync/rebuild`, `wpk stats --history` |
| tests | `test_card.py` (21), `test_migrate.py` (8) |

**How statistics are preserved.** Each step's row keeps the whole
`stats.Step` (every field `stats.packet_steps` computes, including the
ones it rebuilds from transcripts), the raw `meta.json`, and the
tool-cost attribution from the transcript, with key order kept. The
history store therefore gives back the same `Step` objects, and every
figure built from them comes out the same. Every file of each record
(3,080 files, 96 MB) is also in the blob store, so nothing depends on the
run directories surviving.

## Results on the real projects (2026-10-28)

`wpk migrate`, log in `~/.work-packet/migration/m1.log`:

- 13 projects migrated, 16 cards written (e7-* each have a `hello`
  sub-packet card under `runs/<root>/sub/`). `fw-proto-axi4` was skipped:
  its directory no longer exists.
- 14 runs harvested: archives under `~/.work-packet/history/2026/10/`, rows
  in `history.db`, blobs stored. pss-registers-up-planning (SLEEPING)
  and task2 (PAUSED) are loaded provisionally.
- Every project: "statistics identical".
- Independent checks, outputs in `~/.work-packet/migration/verify/`:
  - `wpk stats` in all 20 forms (plain, `--by` each of 6 keys, `--tools`
    each of 3 keys, each with and without `--json`) is byte-identical
    from the runs and from `--history`;
  - totals both ways: 347 step records (335 committed), $175.940676,
    13,816 input, 10,458,778 cache-write, 242,325,807 cache-read,
    3,644,572 output and 978,687 thinking tokens, 90,233.6 s;
  - a database rebuilt from the 14 archives alone is identical for every
    harvested packet; all 3,080 blobs verify.

## Not done yet

- **The executor does not write card entries** (P2). Until it does,
  re-run `wpk migrate pss-registers-up-planning`: it merges the new
  entries into the card and reloads the provisional metrics. Edits you
  make to the card's front matter or thread are kept.
- **No run directory has been deleted** (M3 step 5). Everything needed
  to delete the 14 harvested ones is in place, and `wpk stats` would
  still show the same figures. The dashboard's per-packet and per-step
  pages still read the run directories, though, so deleting them waits
  for the view model (P3) to read the history store, and for your go.
- M2 (moving pss-registers-up-planning to a task folder) and M4.

Next: `docs/dash-history-v1.md` (dashboard on the history store, then
removing the finished runs).

## Status

- 2026-10-28: plan written; steps 1–8 done.
- 2026-10-28 (close): pss-registers-up-planning resynced (32 entries,
  statistics identical); `wpk history verify` identical for every
  project (`~/.work-packet/migration/final-verify.log`). This pass is
  finished; next work is in "Not done yet" above.
