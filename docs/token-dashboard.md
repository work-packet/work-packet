# Token use: recording now, trend views later (2026-10-23)

Goal: see how tokens are used and which projects, packets and tasks burn
them, so the step approach can be tuned on evidence.

## What is recorded (done)

Each step's `meta.json` (docs/spec.md §7) now has:

- `tokens`, summed over the step's runs (a nudged step has two):
  - `input_tokens` (not from the cache);
  - `cache_creation_input_tokens`, split by TTL into `cache_write_1h` and
    `cache_write_5m`, which are priced differently;
  - `cache_read_input_tokens`;
  - `output_tokens`, and `thinking_tokens`, which are part of it.
- `context`: as before, plus `cache_breaks` (main-thread calls that read
  less than half the previous call's context from the cache) and
  `cache_rewrite` (the tokens those calls wrote again).
- `api_s`: time in API calls, beside `duration_s`.

Claude Code's per-run `usage` is right even on a resumed session. Its
`total_cost_usd` and `modelUsage` cover the whole chain (probed with two
Haiku runs). So tokens need no chain correction, and cost keeps the one it
has. A per-model split would need that correction too, so it isn't stored.

Older steps are filled in from their transcripts when `wpk stats` reads
them.

## What you can see now

- `wpk stats [project...]`: one tokens line per harness/model/profile
  group.
- `wpk stats --by project|packet|item|model|day|step [--since 7d] [--json]`: a
  table of token use and cost per row.
- `wpk stats --tools [tool|kind|target] [--json]`: what used up context
  inside steps (view 5), with the lines read twice and the biggest single
  results.

On dvs-enh's 19 attempts so far:

- 51.8M context tokens, 97% from the cache, and no cache breaks;
- 509k output tokens, 47% of them thinking;
- 13% of all tokens went on failed attempts;
- $20.70.

Input is about 100× output. So most of the cost is re-reading the context
on every call: calls per step × context size. Cutting calls, or keeping
context small, pays more than cutting output.

## Trend views

These are built on `stats.rollup()`, so the board and the CLI show the same
numbers. The board's data is in `dash/tokens.py`, its macros in
`templates/_tokens.html`, and every bar has a hover title with the
breakdown. All five views are built (2026-10-24).

1. **Project page, "Tokens" panel:**
   - a stacked bar per day of cache read, cache write, uncached input and
     output, with cost as a line;
   - beneath it, the `--by packet` table.
2. **Board, "Who burns tokens":**
   - the projects ranked by tokens and cost over the last 7 or 30 days;
   - each row has a sparkline, and its share spent on failed attempts.
3. **Packet page, per-step chart:**
   - the context tokens read by each step, with peak context and calls
     beside it;
   - failed attempts in red and nudged steps marked;
   - the same SVG style as the project timeline.
4. **Step page:** the token breakdown, and a per-call context curve from
   the transcript, with cache breaks marked.
5. **What burns context inside a step:** attribution by tool.
   - Each tool result's size counts against every later call, so its cost
     is roughly size × the calls that remain.
   - Group by tool and by file or command.
   - This shows big `Read`s, noisy `Bash` output and repeated reads, which
     are the levers the protocol tunes.

### How view 5 measures (`toolcost.py`)

- A step's context tokens split exactly: each piece of context costs its
  size × the calls that read it ("carried"). The rows add up to the
  context read.
- Sizes are measured. The growth in context between two calls is shared
  among the tool results that arrived in between, by length, at no more
  than 2.35 characters a token (a fit over 1160 call pairs on dvs-enh).
  What's left of the growth is the model's own turn: thinking, text, tool
  calls and hook messages. The first call is the prompt.
- "Lines read again" counts only `Read`s that overlap lines already read in
  the same step. A re-read after an edit is legitimate, so it's a lead, not
  a verdict.
- Shown on the step, packet and project pages ("Where the context went").
  Only Claude Code transcripts are attributed. Parsing all 24 dvs-enh
  transcripts takes about 0.1 s.

### What view 5 shows on dvs-enh (24 attempts, 2026-10-24)

| Source | Carried | Share |
|---|---|---|
| The prompt (system prompt, tools, step prompt) | 27.2M | 36% |
| Model turns (thinking kept in context, tool calls) | 24.9M | 33% |
| Bash results | 14.1M | 18% |
| Read results | 9.6M | 13% |
| Edit, Write, Glob, Grep | 0.4M | 1% |

- The biggest levers are the ones the tools can't see: the prompt (about
  23k tokens, read on every call) and the model's retained thinking. Fewer
  calls per step cuts both.
- Within Bash, `sed -n` (6%) and `grep` (5%) lead; test and build output is
  small, because the log-file rule works.
- Overlapping re-reads cost about 0.8M (1%), mostly `dvs_compile.c` and
  `dvs_search.c`.

### Open questions

- **"Tasks" below packets: decided.** A memento may carry `item:`, the plan
  item the step worked on (docs/spec.md, memento fields). It is optional,
  and a missing or malformed `item` is never an error. A failed attempt is
  charged to the item in its own pending memento, or else to the one its
  step committed. `wpk stats --by item` and the packet page's "Item"
  column use it. Steps from before the field existed show as
  "(no item)".
- **Caching.** `wpk stats` re-parses old transcripts, about 0.1 s for
  dvs-enh. The board needs a per-step cache once there are hundreds of
  steps. It could write the backfilled fields into `meta.json`, or keep an
  index file.
- **Prices for harnesses that don't report cost.** Profiles already have a
  `price` table, so a cost-by-token-type split could use it for every
  harness.

## Build plan

- [x] Record the full token detail per step; backfill it from transcripts.
- [x] `wpk stats` token figures and `--by` rollups; tests (393 pass).
- [x] Project "Tokens" panel (view 1): totals, context and output per day (last 14 days), tables by packet and by plan item.
- [x] Board ranking (view 2): "Tokens, last N days" on the Overview (1, 7 or 30;
  overview.md), per board and per project, with a bar per day.
- [x] Packet per-step chart (view 3): a bar per attempt, linked to it, with failed attempts marked red; context and output columns in the Steps table; the by-item table.
- [x] Step page breakdown and call curve (view 4): a bar per API call. Steps recorded before the new fields are filled in from the transcript. (405 tests pass.)
- [x] Tool attribution (view 5): `wpk stats --tools`, and "Where the context went" on the step, packet and project pages (410 tests pass).
- [x] The memento `item:` field, `--by item`, the packet page's "Item" column (395 tests pass).

## Subscription quota (2026-10-24)

On a Pro or Max plan the measure that matters is the share of the weekly
quota, not dollars. Claude Code's stream-json carries it in an undocumented
`rate_limit_event` (seen in 2.1.280; the docs list only the status line's
`rate_limits` and the interactive `/usage`):
`rate_limit_info.unifiedWindows.{five_hour,seven_day}.{utilization,resetsAt}`,
utilization a fraction in whole percents. API-key accounts get no such event,
and then nothing below is shown.

- The parser (`harness/claude.py` `_add_quota`) keeps the first and last
  reading of each window per step; `meta.json` saves them as `quota`. Older
  steps get theirs from the transcript.
- A step's use (`Step.quota_used`) is last minus first, or last if the window
  reset in between. It is rough: the first reading comes after the first call,
  steps often move it by 0 or 1 point, and any other use of the account
  meanwhile counts too. Summed over many steps it is a fair share.
- Shown: the board and the project page give the weekly and 5-hour use as of
  the newest step, with reset times (red at 80% or more). The tables and
  summaries have a "Week quota" column, the step page gives first → last for
  each window, and `wpk stats --by` has a `week` column.
- On dvs-enh, the 36 attempts of the past week came to about 11% of the weekly
  quota, while the account as a whole was at 39%.
- The scheduler's `quota` budget (docs/scheduler.md §4.1) reads the same
  readings: the newest `seven_day` and `five_hour` utilization against
  `[sched.budget] amount`, with each step's `quota_used` as its estimate.
