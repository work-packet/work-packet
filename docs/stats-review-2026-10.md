# Stats review: ~/projects/packets (Oct 23–27, 2026)

Source: 205 `steps/*/meta.json` records and their `transcript.jsonl` files, plus
the packet journals, across 9 projects (`task2` never ran). The scripts are in
`docs/experiments/stats-2026-10/` (`agg.py` for per-step metrics, `tx.py` for
tool use). Run them again as more steps accumulate.

Caveat: `apiKeySource: none` means these runs used the subscription, so
`cost_usd` is the list-price equivalent. The real limit is the 5-hour and
7-day quota, but the quota and the dollar figure move together.

## Headline numbers

| model | steps | $ | $/step | calls/step (med) | peak ctx (med / max) | min/step |
|---|---|---|---|---|---|---|
| opus-5-5 | 153 | 78.77 | 0.51 | 15 | 35k / 97k | 3.8 |
| sonnet-5 (dvs-enh only) | 37 | 46.20 | 1.25 | 50 | 90k / 145k | 10.6 |
| haiku-4-5 (fw-proto-axi only) | 15 | 1.46 | 0.10 | 9 | 27k / 50k | 1.0 |
| **total** | 205 | **126.44** | | | | |

- **Opus steps cost almost the same everywhere.** Six of the seven Opus
  projects came in at **$0.41–0.47 per step**, with about 15 calls and a 32–37k
  peak. The exception is `fw-proto-axi-opus` at $1.10, the earliest Opus run,
  with a $5 budget and large reads of a spec and a reference repo.
- **Context size drives cost.** Cost per step correlates 0.93 with peak context
  and 0.88 with call count. Each call re-reads the whole context, so cost grows
  roughly as calls × average context.
- **Spend is concentrated.** The top 10% of steps account for 29% of all spend,
  and 10 of the 12 most expensive steps are `dvs-enh` (Sonnet).

## Model selection: what the data can and cannot say

- **Sonnet vs Opus is not a fair comparison.** `dvs-enh` is the only Sonnet
  project. It was also the first project, so it ran an older protocol, and it
  was configured with `step_context_tokens = 120000` and `step_budget_usd = 3`.
  Its steps were about three times larger (50 calls, 90k peak), and that, not
  the model, is why it cost 2.5 times more per step. We can't separate the
  model from the step size or the protocol version.
- **Haiku vs Opus on the AXI task is not a fair comparison either.**
  `fw-proto-axi` (Haiku) had no `Bash` tool, so it could not build or run
  anything. Its "done" is a README. The Opus run ended with `ci/run.sh` passing
  5/5 and tests passing 8/8. On top of that, Haiku read the AXI PDF raw twice
  (2.5M characters), which alone is **28% of all tool-result text in the whole
  corpus**.
- What we can say: on the current protocol, Opus does steady work at about
  $0.45 per step, and nothing yet shows a cheaper model doing the same work.

## Where the money goes (fitted from per-step token counts)

| | cache write | output | cache read |
|---|---|---|---|
| Opus | 45% | 38% | 17% |
| Sonnet | 25% | 25% | 51% (long contexts) |

- **Prefix caching across steps works.** The first call of each step reads
  about 9.5k tokens (Opus) or 18.5k (Sonnet) from cache and writes only about
  5.5k new. The new part is `system.md` and `prompt.md`.
- **Every cache write uses the 1-hour TTL** (`cache_write_5m` is 0 everywhere).
  Only 26 of 8,591 gaps between calls exceeded 5 minutes, and they fell in 20 of
  207 steps (long sims or builds). A 5-minute TTL would make writes cheaper
  (about 1.25× instead of 2× input price). However, it would bring back the
  rewrites after those long gaps, and the prefix would no longer be reused
  across steps spaced more than 5 minutes apart. The rough net saving is
  **5–10%**, so this is low priority and worth only an experiment.

### Output tokens (visible characters, all models)

| what | share |
|---|---|
| Bash command text (59% of it is heredocs: scripts and files written via shell) | 44% |
| **Writes and edits to packet state** (state/, memento, notes, log) | **26%** |
| Writes and edits to work files | 14% |
| Prose | 12% |

The model writes nearly twice as much packet bookkeeping as real work-file
content. Output is 38% of Opus cost, so cutting the duplicated bookkeeping (the
same facts in memento, status, log and notes) is worth roughly a 5% saving.

### Context input (tool results)

- 8.9M characters of tool results in total: Read 49%, Bash 47%. Seven results
  over 20k characters make up 29% of that.
- 248 of 661 `Read` calls had no `limit`. Outside the PDF case this is mostly
  fine, since the average Read returns 6.6k characters.

## Failures and waste

- **`fw-picorv32` startup: 12 failed attempts and 4 manual hand-offs.** The
  first 9 failed in about 1 second each on the invalid model id
  `claude-opus-5.5`. The next 3 failed with the correct id for a reason the
  journal doesn't record. The retry loop spent all 3 attempts within a second
  each time, and nothing told the owner why.
- **`dvs-enh`: 7 failed attempts.** Three were protocol violations (the model
  wrote committed files), two were a missing `.pending/memento.md`, one timed
  out and one did not finish. At about $1.25 or more per Sonnet step, that is
  real money, but **failed attempts are not recorded in `meta.json`**: there are
  205 metas against 216 `step-start` events. So the true waste is unmeasured.
- **Polling at Opus prices.** `pss-registers-up-planning` wakes every day to
  check whether a pssc fix has landed, which costs a full Opus step (about
  $0.45) to find "still blocked".

## Recommended steps (in priority order)

1. **Cap step size by default.** Set the default `step_context_tokens` to about
   60k (the Opus median peak is 35k). Steps should end and hand off rather than
   grow. This is the biggest lever on cost.
2. **Run one controlled model A/B.** Use the same seed, the current protocol,
   the same tools (including Bash) and the same caps: Opus vs Sonnet, and
   Haiku if wanted. Compare $ per *completed outline item*, not per step. The
   existing data can't answer the model question.
3. **Add a preflight and fail fast on startup errors.** Check the model id and
   the harness launch once (as `wpk check` or at hand-off). Don't spend 3
   retries on an immediate exit 1 with an unchanged config. Put the tail of
   `stderr` into the `step-failed` journal event.
4. **Record failed attempts.** Write a `meta.json` (cost, tokens, why) for
   every attempt, so `wpk stats` can report waste.
5. **Guard against large inputs.** In `[setup]`, convert PDFs to text
   (`pdftotext`) or split them by section. Have the protocol tell the model to
   Read large files with `limit`/`offset`.
6. **Use cheap wake checks.** For blocked or polling packets, prefer a shell
   predicate in the wake condition (for example "origin/main moved"), or a
   Haiku-tier check, over a full step.
7. **Trim the bookkeeping.** Audit what the protocol makes the model write
   each step (memento, status, summary, result, log, notes), and drop the
   duplicates.
8. **Extend `wpk stats`** with cost share by token class, cost of failed
   attempts, tool-result bytes per tool, and steps over a context threshold,
   so this review becomes a single command.
9. *(Low priority)* Try the 5-minute cache TTL on one project and compare.
