# Context size and session length

Status: C1–C4 built and measured live (2026-10-22); C5 waits for L2 (`work/`). This file holds the
plan and a status log, so a fresh session can pick up from it alone.

## 1. The cost model

Every API call in a Claude Code session re-reads the whole context. Cache
reads cost about 0.1× the input price; cache writes 1.25× (5-minute TTL) or
2× (1-hour TTL). Claude Code `-p` steps already write with the 1-hour TTL
(`usage.cache_creation.ephemeral_1h_input_tokens` in E7 transcripts), so a
write costs 2× and the cache stays warm for an hour. With context C a turn costs about 0.1·C in reads, so a
session's cost grows roughly with the square of its length.

A fresh session avoids that, but rebuilds the orientation context O: the
system prompt, tools, the step prompt, and what the model reads to find its
bearings. Continuing is cheaper while

    (C − O) × turns in the next piece of work × 0.1  <  2·O + orientation turns

With 3–6 tool calls per piece of work this tips over at C ≈ 4–7·O. So the
numbers to measure are O (the first call's context) and how fast C grows.

For Stage 1 steps O is about 8–10k tokens and a step stays small. For `work/`
projects (long-running.md) O will be several times larger, and one step may
do a lot of reading. That is where these controls matter.

## 2. The controls

| # | Control | What it does |
|---|---|---|
| C1 | Measure | `meta.json` records context per API call: first (≈ O), peak, last, calls |
| C2 | Protocol in the system prompt | The fixed protocol text (`prompts/protocol.md`) moves from the step prompt into `--append-system-prompt-file`, so it is cached with the system prompt. Rules on tool output are added to it |
| C3 | Context budget hook | A `PostToolUse` hook, passed with `--settings`, reads the session's last usage. Over `step_context_tokens` it tells the model to finish the current item, write the hand-off files and stop with `resume: now`; over 1.2× it says stop now. `--max-budget-usd` stays the hard limit |
| C4 | Session carry-over | When a step follows a `resume: now` step within the cache TTL, it resumes that session (`--resume <prev> --fork-session`) instead of starting cold |
| C5 | `work/` digest | wpk puts `git log`, `git diff --stat` and the last build/test result in the prompt so the model does not explore. Needs L2 |

### C3 details

- Context of a call = `input_tokens + cache_creation_input_tokens +
  cache_read_input_tokens` of the last main-thread assistant message in the
  hook's `transcript_path`.
- The hook fires at most once per level (soft at the limit, hard at 1.2×);
  a marker file in the step folder records which levels fired, so it adds
  only two short messages per step.
- `step_context_tokens = 0` turns it off.

### C4 rules

A step resumes the previous session only if all hold; otherwise it starts
fresh, as today:

- `carry_session = true` for the project;
- attempt 1 (a retry always starts fresh);
- the previous committed step ended `RUNNABLE` (`resume: now`);
- it ended less than `carry_ttl` ago (default `55m`, inside the 1-hour cache);
- same model;
- its peak context was under `carry_factor` × the chain's `base` (the first
  call of the fresh session that started the chain, about O), and under
  `step_context_tokens` (a step the hook stopped is full).

The packet files stay the source of truth: the memento must still be enough
for a fresh start, and carry-over is only a cache optimisation. If the
resume fails (session file gone), the attempt fails and attempt 2 starts
fresh. `meta.json` and `step-start` record `carried_from`.

The step is forked under its own deterministic ID: `--resume <prev>
--fork-session --session-id <this step's>` works (probed 2026-10-22).

Two things Claude Code does with a resumed session:

- `total_cost_usd` is the cost of the **whole chain**, not this run. wpk
  stores it as `session_cost_usd` and records `cost_usd` as the difference
  from the previous step's, so budgets and the board stay right.
- `--max-budget-usd` is not applied to the chain total (a resumed run with a
  $0.01 cap and a $0.030 chain total finished four turns). It seems to count
  this run only, so it is passed unchanged.

wpk sets `CLAUDE_CODE_PROMPT_CACHE_TTL=1h` in the step's environment (unless
already set), since carry-over depends on the 1-hour cache.

## 3. Configuration (spec v0.2 additions)

In `config.toml` and `project.toml`, overriding as the other limits do:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `step_context_tokens` | int ≥ 0 | 80000 | C3 soft limit; 0 = off |
| `carry_session` | bool | false | C4 on or off |
| `carry_ttl` | duration | `55m` | C4: longest gap to carry a session over |
| `carry_factor` | number > 1 | 4 | C4: start fresh once the context reaches this multiple of `base` |

`carry_session` is off by default until L5 measurements on a `work/`
project say it pays there too; E7 says it does for short steps (below).

## 4. Build plan

- [x] C1: per-call usage in `meta.json` (`context`), parsed from the
  stream-json transcript, deduplicated by message id, subagent calls left out.
- [x] C2: split `prompts/step.md` into `protocol.md` (system) and `step.md`
  (user); output-hygiene rules; pass `--append-system-prompt-file`.
- [x] C3: `ctxhook.py` (standalone file); `--settings` JSON; config key;
  tests run the hook on synthetic session files.
- [x] C4: carry-over rules, `--resume/--fork-session`, `carried_from`,
  per-step cost from the chain total, `base` and `carry_factor`; tests.
- [x] Live: E7 with carry-over off and on (`tests/test_live.py`, run `carry`
  prints the per-step table).
- [ ] C2: find out why the protocol is not read from cache across steps.
- [ ] Live: a step that crosses `step_context_tokens`, to see the model
  wrap up on the hook's message (only the injection itself is probed).
- [ ] C5 (after L2): `work/` digest in the prompt.
- [ ] L5: pick `step_context_tokens` per project from measured O and growth.

## Status log

### 2026-10-22: design
Options reviewed; C1–C4 started.

### 2026-10-22: C1–C4 built; E7 live
267 tests pass. Probes (Haiku, a few cents): a `--settings` hook runs under
`--setting-sources ""` and its `additionalContext` reaches the model; fork
with a chosen session ID works; the budget cap ignores the chain total.

Claude Code already caches with the 1-hour TTL (`ephemeral_1h_input_tokens`),
so writes cost 2× and the cost model in §1 uses that.

E7 (`prototype/sub`, Haiku, 8 root steps + 1 child):

| Run | Total | Root step cost | Calls/step | First call | Cache write/step |
|---|---|---|---|---|---|
| fresh each step | $0.191 | $0.016–0.027 | 4–7 | 11.0k | 2.8–3.6k |
| carried | $0.131 | $0.012–0.015 | 3 | 13.2k → 22.7k | 1.6k |

A carried step re-reads ~1.6k more context each step, so its cost creeps up
(about $0.0005/step). Priced from tokens, it would match a fresh step
($0.021) at about 47k context, ≈ 4·O; hence `carry_factor = 4`. Carried
steps also need fewer calls (the model remembers what it already knows)
and write half the output tokens. The E7 run took 75 s instead of ~110 s.

C2 shows no saving yet. Warm fresh steps still write 2.8–3.6k tokens to the
cache, as on 2026-10-21 (~3.2k), when the protocol should now be read from
cache. Possibly Claude Code's cache breakpoints don't fall after the
appended system prompt, or something earlier in the system prompt changes
per step. The fresh run cost more than 2026-10-21's ($0.191 against
$0.157–0.166) because of more calls (4–7) and more output tokens, not
cache writes; that looks like run-to-run variance. Open: look at the first
call's read/write split on two back-to-back fresh steps.
