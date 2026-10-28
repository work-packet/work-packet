# dv-solve trial: how big is a step's unit of work? (2026-10-23)

This reviews the first 8 steps of the `dvs-enh` packet (Sonnet 5, an 80k
`step_context_tokens` limit). Step 1 planned. Steps 2–8 did outline items
0a, 0b and 0c, and started 1a.

## Numbers

| Step | Item | Calls | Peak | Cost | Limit hit | First real edit or run |
|---|---|---|---|---|---|---|
| 1 | planning | 18 | 90k | $0.71 | yes | n/a |
| 2 | 0a | 44 | 89k | $1.06 | yes | call 24, at 67k |
| 3 | 0a done, then 0b research | 40 | 98k | $0.98 | yes | call 19, at 57k |
| 4 | 0b (left uncommitted) | 36 | 85k | $0.95 | yes | call 12, at 49k |
| 5 | 0b done, then 0c research | 51 | 89k | $1.13 | yes | call 2, at 23k |
| 6 | 0c, part 1 of 2 | 32 | 55k | $0.53 | no | call 8, at 32k |
| 7 | 0c, part 2 of 2 | 36 | 70k | $0.78 | no | call 14, at 48k |
| 8 | 1a | 38 | 101k | — | yes | call 15, at 48k |

## What we learned

1. **The context limit sets the step boundary, not the outline.** The limit
   fired in 6 of 8 steps, and no step did exactly one item. The one item
   whose split into two steps was planned up front (0c) went cleanly: each
   half was committed, and neither step hit the limit.
2. **Getting oriented costs 20–45k tokens, a third to half of the budget.**
   Steps re-read files the previous step had already read: `dist_harness.py`,
   `run_rand.py` and `dvs_search.c`. Only steps 5 and 6 started fast, and
   both had a memento that gave an exact command or file.
3. **Research handed on as prose is redone.** Twice (steps 3→4 and 5→6), a
   step committed its item, started researching the next one, and was cut
   off by the limit. The next step read everything again anyway.
4. **Facts about the environment get lost or go wrong between steps.**
   - Rediscovered: the `DVS_SOLVER_PATH` value, the venv's location, the
     `DV_SOLVE_BUILD_TOOLS` reconfigure, and whether a `build/` directory
     exists.
   - Wrong: one memento gave an incorrect `DVS_SOLVER_PATH` value. Another
     stated a guessed truth formula (`k/1225`) as if it were a fact.
5. **The prompt is losing what it inlines.** Result notes are piling up in
   `outline.md` (9.8 KB), which is now over the 4 KB inline limit, so every
   step reads it to tick one box. `questions.md` was resolved in step 2 but is
   still inlined in every prompt. Context at the start of a step has grown
   from 15k to 25k, mostly because mementos got longer.
6. **Small costs.**
   - Every step spends 1–3 calls checking that `.pending/state` exists, though
     the executor always creates it.
   - Writing the outline update, summary and memento takes 4–13k tokens.
   - Step 8 ran 21k past the limit after the warning, because the hook
     doesn't warn again until 120k.

## Changes proposed (highest payoff first)

1. **Size the outline items when planning.** Make each item one step ending
   in one commit, or split it into named parts the way 0c was. Every check
   command must be one the planner has actually run (1a's check still
   contains a `<cli>` placeholder).
2. **Add a stopping rule to the protocol.**
   - After committing an item, start the next only if the context is under
     about half the limit.
   - Hand on decisions and exact next actions, never research notes.
3. **Add `state/env.md`.** It holds only facts a step has seen work: paths,
   environment variables, build and test commands. It stays small enough to
   be inlined in every prompt, and mementos point to it instead of repeating
   it.
4. **Keep the outline a lean checklist.** Results go in the commit message
   or in a `state/log.md` that isn't inlined, so the outline stays under the
   inline limit.
5. **Cap the memento at about 2 KB, with fixed parts:**
   - what is done;
   - the exact next action;
   - commands that worked;
   - which file ranges to read;
   - anything unverified, marked as a guess.
6. **Small fixes:**
   - The protocol says that `.pending/state` is already filled.
   - Questions that have been answered stop being inlined.
   - The hook warns again (or stops the step) at about 1.1× the limit.
7. **Try a larger limit.** `step_context_tokens` at about 120k would cut how
   much of each step goes on orientation. The fw-proto-chi simulation
   assumed 150k.

## Status
2026-10-23: changes 1–6 are made; 377 tests pass. Not committed. The user is
trying change 7 (the 120k limit) separately.

- `prompts/sizing-bounded.md`:
  - a step's worth is one plan item, left committed or safe to leave;
  - start the next item only if the context is under about half the limit;
  - hand on decisions, not research notes.
- `prompts/protocol.md`:
  - `.pending/state` is already made;
  - the memento is under about 2 KB, has fixed parts and marks guesses;
  - a new section, "Working through a plan", covers `outline.md` (sized
    items, checks that have been run, no results), `env.md` and
    `state/archive/`;
  - search first, then read only the part of a file needed.
- `prompt.py`: `env.md` and `outline.md` are shown first under "State files".
  `state/archive/` is counted but never shown.
- `ctxhook.py`: the second warning, "stop now", comes at 1.2× the limit, not
  1.5×. The first warning adds "without starting another".
  `docs/context.md` is updated to match.
- The packet already running picks up the new protocol at its next step.
  It will not restructure its 9.8 KB outline unless it is told to (a
  hand-off note).

## Follow-up: steps 9–16 after the changes (2026-10-23)

The new protocol (changes 1–6) took effect at step 10 (step 9's system
prompt doesn't have it yet). The 120k limit took effect at step 14. Step 13
did the hand-off's state restructure. Step 16 attempt 2 was still running
during this review.

| Step | Item | Limit | Calls | Start | Peak | Cost | Hook fired | First real edit or run |
|---|---|---|---|---|---|---|---|---|
| 9 | 1b, part 1 of 2 (committed) | 80k | 56 | 22k | 105k | $1.42 | soft, then hard | call 25, at 73k |
| 10 | 1b, part 2: code | 80k | 46 | 23k | 99k | $1.24 | soft | call 33, at 84k |
| 11 | 1b, part 2: evidence | 80k | 53 | 24k | 90k | $1.07 | soft | call 13, at 36k |
| 12 | 1b, part 2: regression gate | 80k | 71 | 25k | 86k | $1.34 | soft | call 13, at 36k |
| 13.1 | 1b commit | 80k | 17 | 23k | 38k | $0.24 | — | failed: wrote `state/outline.md` directly |
| 13.2 | — | 80k | 27 | 23k | 44k | — | — | failed: did not finish |
| 13 | restructure `state/` | 80k | 39 | 23k | 81k | $0.95 | — | call 12, at 43k |
| 14 | 2a: change fails `perm16` | 120k | 51 | 21k | 127k | $1.51 | soft | call 37, at 94k |
| 15 | 2a: root cause and fix | 120k | 67 | 22k | 129k | $2.05 | soft | call 9, at 40k |
| 16.1 | 2a: rest of the gate | 120k | 24 | 21k | 44k | $0.34 | — | failed: ended its turn to wait for a background task |

### What changed for the better

- **Orientation is cheaper when the memento is good.** Steps 11, 12, 15
  and 16 started real work at call 5–13 (28–40k). Before the changes, 20–70k
  was normal. Steps 10 and 14 were still slow (84k and 94k), because each
  one started new code: step 10 started 1b part 2, and step 14 started
  item 2a.
- **Facts now survive between steps.** `env.md` holds traps that later steps
  would otherwise hit again:
  - a `git stash` doesn't force a rebuild;
  - the fuzz test skips every case when there's no `build/`, and the skips
    look like a pass;
  - `PYTHONPATH` is needed.

  Since step 13 no step has rediscovered the solver path or the venv.
- **Summaries hand on decisions and exact next actions.** They no longer
  carry research notes. Step 15 found the root cause of step 14's failed
  change and fixed it with no re-investigation.
- **The state restructure was done.** `outline.md` went from 12.3 to 6.4 KB,
  results moved to `log.md`, and `questions.md` was archived.

### What didn't

1. **`env.md` and `outline.md` are both still over the 4 KB inline limit.**
   They are 4.6 KB and 6.4 KB, so neither is shown in the prompt. Every step
   spends its first two calls reading them. Change 3 (an `env.md` small
   enough to inline) isn't working yet.
2. **The context limit still ends steps, not the outline.** The soft warning
   fired in every finished step except 13. Item 1b took five steps (9–13).
   Item 2a has taken three so far and isn't committed. Most of the cost is
   the regression gate, which is heavy:
   - `rand-core`;
   - svcorpus;
   - full `pytest`;
   - the fuzz test;
   - `ctest`.

   This gate, more than sizing the items, is what spreads one item over
   several steps.
3. **The 120k limit hasn't paid off yet.** Steps 14–15 ran to 127–129k and
   cost $1.51 and $2.05, against about $1.0–1.4 at 80k. They didn't finish
   an item faster. Step 15 re-read files 11 times, the most of any step.
   Two steps is too few to judge, and item 2a turned out to need debugging.
4. **Three attempts failed in two new ways:**
   - **Step 13.1 edited `state/outline.md` directly** instead of through
     `.pending/`. The executor rejected it. The work survived anyway: the
     dv-solve commit landed, and attempt 3 found it.
   - **Step 16.1 started a long check as a background Bash task** and ended
     its turn to "wait for the notification". In `-p` mode that ends the
     session, so no memento was written. Step 16 attempt 2 is also using
     background tasks, so it may fail the same way.

   Together the failed attempts cost about $0.6 (13.2 didn't report its
   cost).
5. **Small things haven't gone away:**
   - Steps 12 and 13 still check that `.pending/state` exists.
   - The memento is 2.8 KB, against the 2 KB cap.

### Verdict

The changes have helped where they were aimed: handing on facts and
decisions, and starting fast when there's an exact next action. They haven't
changed the step boundary, though, because item 1b's and 2a's cost is
verification, not orientation.

Cost per item looks worse. Steps 1–8 cost about $7.4 for roughly 3.5
items. Steps 9–15 cost about $9.8 for about 1.5 items. The comparison is
confounded, though: 1b and 2a are solver changes that need statistical
validation, and 0a–0c weren't.

### Suggested next changes

1. **Get `env.md` under 4 KB, or inline it at any size up to about 8 KB.**
   The second is one line in `prompt.py`. Either way `env.md` gets shown.
   `outline.md` could show only its unchecked items.
2. **Split each item's check into a fast check and the full gate.** The
   outline gives each item a fast check, such as the bench it targets. The
   full regression gate becomes its own step every few items, or runs once
   before the branch is handed back.
3. **The protocol forbids background Bash and ending a turn to wait.** The
   rule says to run long checks in the foreground with a timeout, or with
   output to a log that the step polls. The executor could also spot a
   final message that waits on a background task and give a clearer failure
   reason.
4. **Remind steps not to edit `state/` directly.** Repeat the `.pending/`
   rule near the "Working through a plan" section, because that's the
   section that tells the model to edit `outline.md`.
5. **Keep 120k for two or three more items**, then compare the cost per
   committed item, not per step.

### Status
2026-10-23: suggestions 1 (the inline part), 3 and 4 are made; 385 tests
pass. Not committed.

- `prompt.py`: a new `FIRST_MAX` (8 KB) applies to `env.md` and
  `outline.md`. Other state files stay at 4 KB.
- `protocol.md`:
  - "Working through a plan" now gives 8 KB as the limit for those two
    files, and repeats that `state/` is changed only through
    `.pending/state/`;
  - "Keeping the context small" now says: no background tasks, and never
    end the turn to wait for one.
- Suggestions 2 (a fast check plus the full gate) and 5 (more items at 120k)
  are still open.

2026-10-23, later: three ways to stop losing whole attempts (390 tests
pass, not committed):

- **The nudge:** when a turn ends with `.pending/` incomplete, the executor
  resumes the same session once and asks for the two files (`docs/spec.md`
  §7). Steps 16.1 and 17.1 would both have been saved this way.
- **A "Last attempt" section** in a retry's prompt shows the failed
  attempt's reason, its tool calls, its last message and any `.pending/`
  files it left.
- **`bghook.py`:** a PreToolUse hook, always installed, that refuses Bash
  calls with `run_in_background`.

## Follow-up: failures through step 28 (2026-10-24)

Seven failed attempts in 28 steps:

| Attempt | Why | Cause | Fixed by |
|---|---|---|---|
| 13.1, 22.1, 28.1 | wrote committed files | Read `state/X`, then Edited that path; 28.1 wrote a *new* file to `state/notes/5a.md` | `pathhook.py` (below) |
| 16.1, 17.1 | no memento | background task, then ended the turn to wait | `bghook.py` and the nudge (above); none since |
| 27.1 | timeout (30m) | ran the full pytest suite four times plus rebuilds; no warning before the kill | time warning (below) |
| 13.2 | did not finish | the owner paused the packet and changed its config mid-attempt | not a model failure |

22.1 and 28.1 came *after* the protocol said twice that writing `state/`
directly fails, so more prompt text was not enough. Changes (416 tests
pass, not committed):

- **`pathhook.py`:** a PreToolUse hook on Edit, Write, MultiEdit and
  NotebookEdit that refuses a file the executor owns (`state/`,
  `memento.md`, `status.md`, `journal.jsonl`, `children/`, `identity/`)
  and names the `.pending/` path to use instead. The step goes on, where it
  used to be thrown away. Bash writes (`sed -i`, `>`) are not checked; none
  of the failures used them, and `_check` still catches them.
- **Time warning:** the executor sets `WPK_STARTED_AT`, `WPK_WARN_AT` (at
  70% of `step_timeout`) and `WPK_DEADLINE`; `ctxhook.py` warns once after
  `WPK_WARN_AT` with the minutes left, and tells the step to finish the
  item and write the memento. It shares the `ctxhook.fired` marker with the
  context warning.
- **`protocol.md`:** "New files can be written straight away" read as
  "straight into `state/`". It now says a new file goes in
  `.pending/state/` too, with `state/notes/5a.md` as the wrong example.

Still open: 27.1 also re-ran the full suite to get a baseline that an
earlier step had already run. Recording the baseline failure list in
`state/env.md` (or a file it names) would save most of that time.
