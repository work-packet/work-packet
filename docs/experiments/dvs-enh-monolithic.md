# dvs-enh: steps vs. one monolithic session (2026-10-24)

Question: would dvs-enh have cost less, in tokens and quota, as one long Claude
Code session instead of 31 work-packet steps?

## Data

- 38 transcripts: 31 steps that passed, plus 7 failed attempts. 1,857 main-thread calls.
- Reported cost $46.20. Context read 125.9M tokens, 98% of it from the cache.
- Each step starts at a median of 24k tokens of context (14.8k–28.5k) and grows a median of 75k.
  The 31 passing steps grew 2.37M tokens in all.

## Method

The simulation is in `dvs-enh-monolithic.py`. It replays every call of the 31 passing steps in one conversation.
- The context at each call = the base prompt + everything carried from earlier steps + this step's own growth so far + 2k for the user turn that starts the step.
- When the context reaches the auto-compact threshold, one call reads all of it and writes a 20k summary. That summary is what gets carried forward.
- New tokens in a call are priced as cache writes, the rest as cache reads, at Sonnet-class ratios
  (read 0.30, write 3.75, output 15 per Mtok). Output is the same in both cases, so the figures below compare context cost.

## Result

| Run as | Context read | Est. cost | vs. steps |
|---|---|---|---|
| work-packet, 31 steps | 111M | $42 | 1.0× |
| monolithic, compact at 160k (200k window) | 158M | $64 | 1.5× |
| monolithic, compact at 400k | 341M | $114 | 2.7× |
| monolithic, compact at 900k (1M window) | 727M | $228 | 5.4× |
| monolithic, never compacts | 2,019M | $614 | 14.5× |

The cost of the 7 failed attempts is on the work-packet side and not in the table: about 15M tokens of context, 12% of the total.

## Re-reading

Steps start fresh, so they re-read files. Of the 282k tokens of `Read` results, 141k were files an earlier step had already read.
That is 6% of the 2.37M grown. Even counting the calls that carry those tokens afterwards, it adds about $1. A monolithic session would avoid only part of it, since it also re-reads after each compaction.

## Reading

- Cost per call is set by the size of the context, and a step resets it to about 24k.
  A monolith only resets when it compacts, so its calls average a much larger context.
  The closest monolithic setup (compact at 160k) is still 1.5× the cost. A longer window makes it worse, not better.
- So splitting is the efficient option here, by about 1.5× against a well-tuned monolith and far more against a 1M-context one.
  Quota tracks cost, so the same ratios apply to the weekly quota.
- What the model does not capture: 
  - A monolith's 20k summary is lossy, while the step state is curated.
  - The monolith might have done the work in fewer calls, which cannot be measured from this data.
  - The timeouts behind the failed attempts are a work-packet cost a monolith would not pay in the same form.

## When to compact (2026-10-24)

`dvs-enh-compaction.py` runs the same model with other compaction policies. It maps each step to its plan item. Steps 17–31 record the item in their memento; for steps 1–16 the mapping comes from the step summaries. The plan has 14 sub-items (planning, 0a, 0b … 5b) under 7 top-level items (planning, then 0–5).

| Policy | Compactions | Peak context | Context read | Est. cost | vs. steps |
|---|---|---|---|---|---|
| work-packet, 31 steps | none (31 fresh starts) | 145k | 111M | $42 | 1.0× |
| Auto-compact at 200k | 14 | 199k | 190M | $71 | 1.7× |
| At each sub-item, no auto | 13 | 389k | 259M | $92 | 2.2× |
| At each sub-item, plus auto at 200k | 20 | 199k | 169M | $68 | 1.6× |
| At each top-level item, no auto | 6 | 580k | 411M | $135 | 3.2× |
| At each top-level item, plus auto at 200k | 17 | 199k | 180M | $70 | 1.6× |
| Ideal: at each natural break near 80k (where steps ended), plus auto at 200k | 30 | 158k | 135M | $62 | 1.4× |

- Compacting only at plan boundaries needs a window over 200k. Item 1b alone ran five steps and grew to 389k.
  So "compact at the end of each item" either needs a 1M window, and pays for it, or still relies on auto-compaction partway through an item.
- Even ideal timing costs 1.4×: compacting where each step ended (about 80k, at a clean point), which a user could only approach by watching the context counter. The 20k summary rides along in every call (about $10). Each compaction is also an extra call that writes the summary (about $9).
  A step pays for neither: it writes its memento and state as part of its own work, and the next step starts at about 24k.
