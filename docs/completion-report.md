# Completion report

Status: implemented 2026-10-26 (see "Status" at the end).

## Problem

When a packet reaches COMPLETED, nothing tells the owner what it produced.
The only record is the summary of the last step (`status.md` body,
`steps/NNNN/summary.md`). That summary covers only the final step, which is
often minor, such as "fixed a typo in plan.md; marking done". The decisions
and the deliverables are spread across earlier steps, `state/`, `work/` and
commit messages. `docs/packet-shapes.md:319-327` calls this out: the
deliverable "is buried in the packet's internals".

Example: a planning packet finishes. The owner wants a short account of
what was decided, plus the path to the full plan. Today they get the final
step's summary and have to search `state/` themselves.

## Where things stand

- The only way to COMPLETED is `resume: done` in the memento
  (`clock.py:108`, mapped in `executor.py` step 12).
- `_validate_pending` (`executor.py:393`) requires `.pending/summary.md`
  for every step and treats a finishing step like any other.
- The prompts (`prompts/protocol.md:22,44`, `instruct-list.md:18`,
  `instruct-outline.md:37`) never ask for a final account of the work.
- `wpk ps` and the dash Done card show the first line of the last step's
  summary. `wpk show` shows the whole of it.
- `docs/packet-ux.md:193-205` sketches a `wpk status` that lists results,
  but it has not been built.

## Proposal

### 1. The finishing step writes `.pending/report.md`

When the memento says `resume: done`, the step must also write
`.pending/report.md`. It is required, in the same way `summary.md` is
required for every step, and covers the **whole packet**, not just this
step. Front matter holds what tools need; the body is for the person.

```markdown
---
outcome: Chose a two-phase rollout; plan written, not yet reviewed.
deliverables:
  - path: work/docs/rollout-plan.md
    what: The full plan (phases, risks, owners)
  - path: state/notes/options.md
    what: The three options considered, with costs
---
## Outcome
One paragraph: what was asked, and what now exists.

## Decisions
- Two phases rather than a big-bang cutover, because …
- Option B (cache in front of the store) was rejected: …

## Deliverables
- `work/docs/rollout-plan.md`: the full plan
- …

## Open items
- Phase 2 sizing is a guess; it needs a benchmark before sign-off.
- Not done: the migration script (out of scope for this packet).
```

Rules:
- `outcome` is a single line. It replaces the last step's summary as the
  line shown by `ps` and on the dash card.
- `deliverables[].path` is relative to the packet root, or to a work repo
  as `work/<name>/…`. The executor checks that every path exists after
  the commit. A path that does not exist rejects the step, so the agent
  cannot cite files it never wrote.
- The sections in the body are fixed: **Outcome, Decisions, Deliverables,
  Open items**. Decisions may be empty only for a mechanical task, and the
  report must then say "none".
- A `fail` ending writes the same report. Outcome then says why it failed,
  and Open items says what is left.

The prompt tells the agent to build the report from `state/log.md`, the
outline (`state/outline.md`) and its own memory of the steps. It should
not rely only on this step.

### 2. The executor keeps it

In `executor.py`, at step 12 when the state is COMPLETED or FAILED:
- `_validate_pending` requires `report.md` and checks its front matter and
  deliverable paths. It does this check only on `done` and `fail`.
- The report is copied to `steps/NNNN/report.md` and to `report.md` at the
  packet root, which is the stable path for the current result.
- The `commit-begin` decision carries `outcome` and the list of
  deliverable paths, so the journal holds them as well.
- `wpk next` and `CONTINUE_FROM` move `report.md` to
  `state/history/report-NNNN.md` together with the outline. The packet
  then has a fresh round, and the earlier rounds' reports are kept.

### 3. Where the owner sees it

- **CLI:** add `wpk report <packet>`, which prints `report.md` with the
  deliverable paths made absolute so they can be clicked. When the packet
  is COMPLETED, `wpk show` prints the report instead of the last summary.
  `wpk ps` shows `outcome` in the LAST SUMMARY column.
- **Dash:** the Done card shows `outcome`. The packet page shows the
  rendered report above the "Next batch" panel, and each deliverable
  links to its file.
- **Old packets:** a packet that finished before this change has no
  `report.md`. Every view falls back to the last summary, as it does today.

## Decisions (2026-10-26)

1. **Same step.** The report is written in the step that says `done` or
   `fail`. If the quality of the reports is poor, move to a separate final
   step (for example `resume: report`) that has a clean context.
2. **Commits are recorded.** For a deliverable under `work/<repo>/` whose
   repo is a git checkout, the executor adds `commit: <sha>` (the repo's
   HEAD after the step) to the deliverable in the stored report. A plain
   folder gets nothing, because packets need not use git.
3. **Children are rolled up.** A parent's report shows its children's
   reports: outcome, decisions, deliverables and open items, recursively.
   This is done **when the report is shown, not when it is written**.
   A parent often says `done` in the same step that spawns its children
   (see the E1 scenario), so at commit time their results do not exist
   yet. A child that has not finished is listed with its state.

## Work

1. `schema.py`: `validate_report()` (front matter, sections, paths).
2. `executor.py`: require and copy the report on done/fail; journal fields;
   archive it on `next`/`CONTINUE_FROM`.
3. `prompts/protocol.md` and `instruct-*.md`: the report contract.
4. `views.py`: `wpk report`, `show` and `ps` changes; `cli.py` wiring.
5. `dash/data.py`, `dash/templates/packet.html`: card outcome, report panel.
6. Tests: a done step without a report is rejected; a bad path is
   rejected; the fallback for old packets; the archive on `next`.
7. `docs/spec.md` §4.1/§5: document `report.md`.

## Status

- [x] 1 `report.py`: validate, stamp commits, load, render with roll-up
- [x] 2 executor: require on done/fail, store, journal; archive on leaving
      COMPLETED/FAILED (next batch, resume, hand-off), not only `next`
- [x] 3 prompts: `protocol.md` "Finishing: the report", `instruct-*.md`, nudge text
- [x] 4 CLI: `wpk report`, `show` (report section), `ps` (outcome leads the
      status body)
- [x] 5 dash: report panel first on the packet page (outcome headline,
      decisions, deliverables linked through `/p/<project>/<wpid>/file`,
      open items, children rolled up); "Last summary" hidden when there
      is a report. Markdown via `markdown-it-py` (added to the `dash` extra),
      raw HTML off.
- [x] 6 tests: `tests/test_report.py`; the fake model writes a report on
      done/fail (`common.report`, behaviour `reporter`, fault `no-report`)
- [x] 7 `docs/spec.md` §4.7 and cross-references; `check.py` knows `report.md`

Next: watch the quality of real reports (decision 1) on the next live runs.
