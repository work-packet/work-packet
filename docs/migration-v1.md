# Migrating today's packets to the new format (plan, 2026-10-28)

Status: a plan for review. M0 (securing the data) is done; nothing else
has been changed on disk. It covers what happens to the packets wpk
holds today, and the data they hold, when we move to the format in
`docs/work-data-design.md` (cards, task folders, run records, the
history store).

## 1. What there is today

From a survey of `~/.work-packet/projects/*.toml` on 2026-10-28:

| Project | State | Steps | Cost | Commits only on a local `wpk/*` branch | Uncommitted files | Size |
|---|---|---|---|---|---|---|
| dv-flow-mgr-inh-matrix | COMPLETED | 12 | $5.19 | 1 (`wpk/yaml-cloader`) | 0 | 134 MB |
| dv-solve-simbench | COMPLETED | 130 | $55.86 | 0 (pushed as `origin/wpk/dv-solve-simbench`) | 0 | 1.1 GB |
| dvs-enh | COMPLETED | 31 | $46.20 | 0 (pushed as `origin/wpk/dvs-enh`) | **5** in the packet's worktree | 1.8 GB |
| e7-1, e7-2, e7-3 | COMPLETED | 9 each | $0.49 total | none (no repos) | 0 | tiny; each has 1 child |
| fw-picorv32 | COMPLETED | 16 | $8.84 | **16** | 0 | 2.1 GB |
| fw-proto-axi-opus | COMPLETED | 16 | $18.78 | **22** | 0 | 1.9 GB |
| fw-proto-axi | COMPLETED | 15 | $1.46 | 0 | 0 | 9 MB |
| fw-proto-axi4 | registry entry only | | | | | its directory no longer exists |
| pss-registers-up-planning | **SLEEPING** (active) | 17 | $7.43 | **4** (pss-registers-up) | **1** in your clone | 2.1 GB |
| pssc | COMPLETED | 17 | $7.70 | **7** | 0 | 1.0 GB |
| task2 | PAUSED (setup) | 0 | $0 | none | 0 | empty |
| verilator-efficient-waits | COMPLETED | 54 | $23.99 | **29** (27 verilator-efficient-waits, 2 fw-uart16550) | **1** in the fw-uart16550 worktree | 7.2 GB |

Totals: about 335 steps and $176 of recorded work, 67 MB of
transcripts, and 17.4 GB on disk, nearly all of it derived (IVPM
`packages/`, builds, sim output). The disk is 92% full.

What each project holds, in today's layout:

```
<project>/
  project.toml, prompt.md       settings, setup repos, permissions; the first instruction
  identity/                     host-specific links
  state/                        the seed copied into the root packet once
  work/<repo>                   "your clone", usually on main
  packets/<uuid>/               the root packet (and children)
    status.md memento.md journal.jsonl report.md
    state/ (outline, notes, env.md, history/outline-N, report-N)
    steps/NNNN/ (meta.json, summary, state.diff, transcript, result, report)
    work/<repo>                 a git worktree on wpk/<project>: where the commits are
```

**Risk 1: about 79 commits exist only on local `wpk/*` branches.**
They are in the worktrees under each project directory, and in no
remote. Deleting a project directory, by hand or in a cleanup, loses
them. Securing them comes first (§3, M0), before any new code exists.

**Risk 2: uncommitted changes in three trees** (dvs-enh, fw-uart16550
under verilator-efficient-waits, and your pss-registers-up clone).
Migration stops on them and shows them; it never discards them.

## 2. Where each piece goes

| Today | New home | How |
|---|---|---|
| `packets/<uuid>/` (status, memento, journal, steps, state, report, mailbox) | the run record, `~/.work-packet/runs/<uuid>/` | unchanged: the v0.2 file contract is kept. UUIDs remain valid ids |
| `prompt.md` and each later batch's instruction | the card's brief, then `request` entries | from the journal's `handoff` records that carry `instruction` |
| questions and answers | `question` / `answer` entries | questions from each step's `result.md` (`ask:`); answers from `handoff` records (`answers`) |
| notes | `note` entries | journal `note` records |
| each completed batch | a `result` entry | `outcome` and `deliverables` from `state/history/report-<n>.md`, or `report.md` for the last batch |
| children (e7-*) | sub-packets: cards in `runs/<root>/sub/`, runs at `runs/<child>/` | names from the parent's spawn records |
| `project.toml` `[setup]` repos | the card's `work:` (remote URL and branch) | read from the repos' remotes |
| `project.toml` model, permissions, `allowed_tools`, limits, sizes | a host profile, `migrated-<name>` | so a reopened packet runs with the same permissions; never on the card |
| `identity/` | the host binding | host-specific; never on the card |
| board membership (`board =` in the registry) | a tag on the card | `featherweight-ip`, `verilator`, … |
| per-step metrics (`meta.json`) | history database rows | a backfill; the token fields map one to one |
| plan and notes as of each step | narrative blobs per step | rebuilt by applying each step's `state.diff` in reverse from the final `state/`, checked by replaying forward (§4) |
| transcripts | transcript blobs | retention counts from each step's date |
| the `wpk/*` branches | pinned commits on the card | after M0 secures them |
| `sched/` jobs, leases, session ids | dropped | control data |
| the `fw-proto-axi4` registry entry | removed | its directory is gone |

**The thread is rebuilt, not recorded.** Today's packets never kept a
conversation, so the card's entries are made from the journal and step
files. Each one carries a `Migrated-From:` trailer (for example
`journal.jsonl:41` or `steps/0007/result.md`), so nobody mistakes a
rebuilt entry for one written at the time.

## 3. The path, in stages

Each stage can be stopped after, and only the last one deletes
anything.

| Stage | Needs | Does | Reversible |
|---|---|---|---|
| **M0 Secure** | nothing new; a small script | for every repo with commits only on a local branch: a `git bundle` of the branch into `~/.work-packet/migration/bundles/`, and, with your approval per repo, a push to `refs/packets/<uuid>` on its origin. Uncommitted changes are saved as `git diff` patches next to the bundles. Writes `migration/inventory.json` (the table above, plus commit ids) | yes: it only adds |
| **M1 Adopt** | P1 (cards) and P2 (run binding) | `wpk migrate --dry-run`, then `wpk migrate`. It writes a card per project, with the rebuilt thread and pins to the commits M0 secured, and symlinks each `runs/<uuid>` to the old packet directory, then builds the index. Nothing moves; the old layout still works | yes: remove the cards, links and index |
| **M2 Bring the active one forward** | P2 | pss-registers-up-planning becomes a task folder `~/packets/pss-registers-up-planning/`. Its repos are cloned fresh with `ivpm clone <local clone> -b wpk/pss-registers-up-planning` (no `mv`: a moved venv breaks), the remotes are set to upstream, and `ivpm update` runs. The run record moves into `runs/<uuid>/` (a rename). The old worktree is retired only when the new HEAD matches and the tree is clean | yes, until the old worktree is removed |
| **M3 Harvest the finished ones** | P7 (history) | for each completed project: freeze, write the `.wph` archive, load the database, then **check that `wpk stats` and the dashboard show the same steps, tokens and cost as before migration**. Only then remove the old project directory. That frees about 15 GB | no, once directories are removed. M0's bundles and the archives remain |
| **M4 Tidy** | after M3 | remove the old registry entries; boards become saved filters over tags | yes |

M0 is worth doing now, independently of everything else, because of
Risk 1.

## 4. What is kept faithfully, and what is not

| Data | Fidelity |
|---|---|
| steps, summaries, reports, deliverables, diffs, transcripts, per-step cost and tokens | **exact**: copied as they are |
| commits | exact, once M0 has secured them |
| the plan and notes as of each step | **rebuilt** from `state.diff`. Where the reverse replay doesn't match the forward check, that step's plan is marked "not recoverable" rather than guessed |
| the conversation (card entries) | **rebuilt** from the journal and step files, and marked `Migrated-From:`. Questions asked before `ask:` was structured (interaction.md I1) may come through as plain notes |
| sub-packet names (e7-*) | from spawn records; where a name is missing, `child-<n>` |
| links between packets (for example pss-registers-up-planning → pssc) | not recorded today (the journals have no `request` records). Added by hand if you want them: `wpk link pss-registers-up-planning pssc` writes a `note` with `Related: pkt:pssc` |
| permissions, model, limits | kept as the `migrated-<name>` host profiles |
| session ids, leases, scheduler state | dropped |

## 5. Decisions for you

| # | Decision | Recommendation |
|---|---|---|
| G1 | Where to keep the 79 local-only commits: pushed to `refs/packets/<uuid>` on each origin (outward-facing, so your approval per repo), or only as local bundles | push where the origin is yours (the fw-* and fvutils repos); bundles for the rest. Bundles in every case |
| G2 | Which finished packets to keep history for | all of them. History is cheap once harvested, and dv-solve-simbench (130 steps) is the best test of harvest fidelity |
| G3 | The e7-* experiments | keep: they are the only packets with children, so they test sub-packet migration |
| G4 | task2 (empty, PAUSED at setup) | discard |
| G5 | The three trees with uncommitted changes | review each; M0 saves them as patches either way |
| G6 | pss-registers-up-planning: move to a task folder now (M2), or keep it attached where it is until it finishes | move it: it is the one live packet, and the first real test of task folders with IVPM |
| G7 | Were any of the `wpk/*` branches' changes already merged upstream by other means (cherry-picks, re-done by hand)? | you know; the survey counts commits only by reachability. The ones that were merged can still be pinned, but don't need pushing |

## 6. Status

- [x] M0 secure, done 2026-10-28 (by hand, not yet a script):
  - the 7 local-only `wpk/*` branches (79 commits) are pushed to their
    origins under the same branch names, and bundled to
    `~/.work-packet/migration/bundles/`. Every bundle verifies, and none
    of the repos now has commits only on a local branch.
    `~/.work-packet/migration/branches.txt` lists each one with its head;
  - every packet record (journals, steps, transcripts, state, with
    `work/` excluded), plus the registry and boards, is archived to
    `~/.work-packet/migration/packet-records-2026-10-28.tgz` (31 MB,
    347 step `meta.json` files);
  - uncommitted changes:
    - dvs-enh's three `.scratch_*.py` files were copied to
      `migration/patches/dvs-enh/` and not committed. Its `build/` and
      `out/` are derived and empty or nearly so;
    - fw-uart16550's untracked `packages/` is IVPM output, so nothing
      was saved;
    - your pss-registers-up clone on `main` adds `default-dep-set: dev`
      to `ivpm.yaml`. It was saved as
      `migration/patches/pss-registers-up--main--ivpm.yaml.patch` and
      **not committed**, because it changes what lab attendees fetch.
      Your call (G5).
- [x] M1 adopt, done 2026-10-28 with `wpk migrate` (see
  `docs/implementation-v1.md`): 16 cards, `runs/<id>` links, `index.db`.
  The executor does not yet write card entries (P2), so re-running
  `wpk migrate` is how the active card catches up
- [ ] M2 pss-registers-up-planning to a task folder
- [~] M3 harvest and verify: steps 1–4 done 2026-10-28 for all 14
  finished runs (archives, database, blobs), and every statistic checked
  identical. Step 5 (removing the old directories) is not done: it waits
  for the dashboard's packet pages to read the history store (P3), and
  for your go
- [ ] M4 tidy

- 2026-10-28: plan written from the survey. Nothing changed on disk.
