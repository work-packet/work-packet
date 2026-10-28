# L1a: `ask:`, `wpk handoff -m`, `wpk allow` / `deny` / `set`

Status: built (2026-10-23); 352 passed, 4 skipped. Not committed. This is a slice of long-running.md L1,
built so that the dv-solve trial can continue the way it should:

```bash
wpk allow dvs-enh Bash
wpk handoff dvs-enh -m "Take the recommendations"
```

This file holds the plan and its status, so a fresh session can pick up from
it alone.

## Decisions

- **State `NEEDS_INPUT`, not `HELD` yet.** `NEEDS_INPUT` is already a
  reserved name in spec v0.2. The v0.3 migration (HELD + `held_for`
  replacing PAUSED and FAILED) stays a separate piece of work; it will read
  `NEEDS_INPUT` as `HELD`/`question`.
- **`ask:` in the memento** (a non-empty string). The step commits as
  `NEEDS_INPUT` with `reason` = the question; `resume_expr` keeps `resume`
  as a record.
  - `ask:` with `resume: done` or `fail` is an error.
  - The body must not be empty: it is the instruction for after the answer.
- **`wpk handoff <target> [-m NOTE | --note-file F]`** moves a packet from
  `NEEDS_INPUT`, `PAUSED` or `FAILED` to `RUNNABLE`. It takes the lease and
  writes a `handoff` journal record: `by`, `from`, `to`, `note`, and
  `asked` (the question, if there was one). `wpk resume` also accepts
  `NEEDS_INPUT`, with no note.
- **The step prompt** shows the hand-off records since the last
  `commit-end`, under "Hand-off": the question that was asked and your
  note. A retry of the same step sees them too.
- **`wpk allow <project> <tool>…` / `wpk deny …` / `wpk set <project>
  key=value…`** edit `project.toml`.
  - The result is validated with `schema.validate_project` before it is
    written.
  - They take the root packet's lease, so they never change settings under
    a running step. With the lease, a `config` journal record (`by`,
    `changes`) can go in the root's journal without tripping the snapshot
    check.
  - Comments in `project.toml` are lost on rewrite (tomli_w), which is
    acceptable for now.
  - `set` takes the limit keys and `model`, `harness`, `profile` and `tz`.
    Values are parsed as TOML literals, falling back to a string.
- **The board** gets a `NEEDS_INPUT` colour and a "Needs you" column, with
  the question shown on the card.
- **The protocol prompt** documents `ask:`.

## Steps

- [x] 1. schema: the state, `ask`, the `handoff` and `config` journal types
- [x] 2. executor: the decision with `ask`; `admin` op `handoff` with a note
- [x] 3. prompt: the Hand-off section; protocol.md: `ask:`
- [x] 4. cli: `handoff`, `allow`, `deny`, `set`; `resume` accepts NEEDS_INPUT
- [x] 5. check.py, views, dash: the new state
- [x] 6. spec.md, long-running.md; tests; full suite
- [x] 7. The dv-solve packet needs no conversion: `wpk handoff` takes FAILED
  too. Its step-1 memento is a holding note ("do not start until
  answered"), so this one hand-off note also carries the execution rules.
  From now on, a gate step writes the instruction for after the answer
  (protocol.md).

## Status log

### 2026-10-23
Plan written. Baseline: 331 passed, 4 skipped.
Built. New: `tests/test_ask.py` (21 tests), the fake behaviour `asker`, and
a "Needs you" case in `tests/test_dash.py`.

- schema: `NEEDS_INPUT` is a state (it needs a `reason`); `ask` is a memento
  key; `handoff` and `config` are journal types. `resume: ask` now says to
  use the key instead.
- executor: `ask` gives `NEEDS_INPUT`; `admin(..., "handoff", note=)`.
- prompt: a "Hand-off" section built from the journal since the last
  `commit-end`; protocol.md explains `ask:`.
- cli: `handoff`, `allow`, `deny`, `set`. `resume` and the project-wide
  forms take `NEEDS_INPUT`.
- project.py: `change_settings` (validates, holds the root lease, writes a
  `config` record).
- board: a "Needs you" column, its colour, and the question on the card.
- spec.md §4.1–4.3 and §5; long-running.md L1 ticked.
