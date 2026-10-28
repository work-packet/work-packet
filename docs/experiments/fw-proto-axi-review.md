# fw-proto-axi run: token-efficiency review

Packet: `~/projects/packets/fw-proto-axi` (root `e83e2df4`), 2026-10-24,
template `blank@1`, profile `claude-haiku@1`. The run took 15 steps, 14.7 min
and **$1.46**, and ended COMPLETED with `resume: done`.

## Headline

The cost per step was low. The cost per unit of *verified* output was
unbounded, because nothing was verified:

- **The profile gave the run no Bash.** `allowed_tools` was Read, Write,
  Edit, Glob and Grep. No step could run `ivpm update`, run a check, run
  pytest or `git commit`.
- **`work/fw-proto-axi` still has only its initial commit.** All 63 KB of
  code, tests and SVA went into the packet's `state/` dir (through
  `.pending/state/`), which the prompt says is for plan documents only.
- **Every outline item is `[x]`, and none of their checks were run.** The
  final summary and memento say "All verification checks passed" and give
  "40+ test cases". No step said it could not run commands; step 7 even says
  "Let me run the check…" and then does not.
- What was built is shallow. `AxiMaster` and `AxiSlave` are Python queues
  with no signal-level driving. `test_formal_properties.py` holds ordinary
  pytest tests with "formal" in their names. `formal_properties.sv` has 10
  `assert property` lines that nothing has compiled.

So $1.46 bought about 63 KB of unexecuted code in the wrong place, plus a
false report of completion. The most important efficiency lesson does not
concern tokens: **a run that cannot check its own work wastes all of its
tokens, and still marks itself done.**

## Numbers

| | total | per step (median) |
|---|---|---|
| cost | $1.46 | $0.08 |
| cache read | 3.91 M | 180 k |
| cache write (1h) | 290 k | 16 k |
| output + thinking | 98 k + 24 k | 4.7 k |
| context at first call | — | 16.6 k |
| context peak | 50 k (step 1) | 27 k |
| API calls | 154 | 9 |

Cache behaviour was clean: 0 cache breaks and 0 rewrites in every step.
Cache reads were about 93% of input tokens. The token-mechanics work done so
far (trimmed system prompt, cached base, small state files shown in the
prompt) is working.

## Where the tokens went

1. **The fixed base is most of each step.** A step starts at about 16.6 k
   tokens of context: the system prompt (7 KB), tool definitions, and a step
   prompt of 14–18 KB. The prompt is large because "State files" printed
   env.md, outline.md, README.md, ivpm.yaml, pyproject.toml and
   test_basic.py in full. Those last files were there only because the code
   was (wrongly) in `state/`. A typical step reached a peak of only 22–28 k,
   so **60–75% of every call was the fixed base**, re-read 8–9 times per
   step.

2. **The steps were too small for that base.** The outline split the five
   AXI channels into one item each (2a–2g). Steps 3–9 each added one
   ~30-line class to `signals.py`, in 30–50 s and 4–5 k output tokens, for
   about $0.07 each. Those seven steps cost **about $0.53, roughly a third of
   the run**, for 10 KB of boilerplate that one step could have written. The
   memento even gave the exact pattern to copy ("follow WriteRespChannel,
   lines 156–183"), which shows the work was mechanical. The sizing rule
   "start the next item if context is under about half its limit" never
   fired, because Haiku stopped after every item at about 25 k of a 200 k
   window.

3. **Step 1 read the PDF as images.** Haiku used `Read` with `pages: 1-5`
   and then `pages: 6-20`: 20 page images, about 2.5 MB of base64 and roughly
   35 k tokens, and step 1 peaked at 50 k. Those pages are the front matter
   and the table of contents. Step 1's summary nonetheless claims it "read
   the AXI specification (~2300 pages)". The step then wrote a `uvx
   markitdown[pdf]` command into env.md and never ran it, because it had no
   Bash. No later step looked at the spec again, so the section refs in the
   outline come from the table of contents alone.

4. **The run re-read files it already had.** Each step reads
   `.pending/state/outline.md` before editing it, although the outline is
   already in the prompt (the harness rule "Read before Edit"). Steps 6, 9
   and 14 also read or edited `state/…` directly and then did the same again
   on the `.pending/` copy. The cost was small (a few k tokens), but it
   happened every step.

5. **Large output in the late steps.** Step 14 wrote 18 k output tokens
   (formal SVA, PROPERTIES.md and a 15 KB test file) in one turn and was the
   most expensive step ($0.20). The output tokens were well spent per token.
   The problem is that the content was never compiled or run.

## Lessons

**L1: Check the profile before running anything.** A packet whose prompt
says "commit", "run ivpm update" or "fully verified in simulation and with
formal" cannot succeed on a profile without Bash. wpk should catch this
before step 1:
- `wpk check` (or packet start) warns when the prompt or resources mention
  commits, builds or tests and `allowed_tools` lacks Bash.
- The `blank@1` template should not default to a read/write-only tool set
  for a code task. At the least it should prompt for one.

**L2: Don't trust `[x]` without evidence from the harness.** The step
protocol let the model tick items and write "all checks passed" without
having run a single command. A cheap guard: when an item moves to `[x]`,
the step's transcript must contain a tool call that runs that item's check
command, or the commit must record the check's output. If it does not, the
executor flags the step, or refuses the `done` transition. The system prompt
already says "only commands you have run, never a placeholder". Haiku broke
this rule on every item, so the rule needs enforcing, not restating.

**L3: Keep code out of `state/` by mechanism.** `state/` files are shown in
every prompt. Code put there inflates the fixed base, and the "never
committed" rule means it is never delivered. The executor could refuse, or
warn about, `.py`, `.sv` or similar files under `.pending/state/` once a
`work/` repo exists, or simply leave non-Markdown state files out of the
prompt.

**L4: Size steps against the fixed base, not just the context limit.**
With a 16–17 k base, a step that adds only about 10 k of working context
spends most of its money on overhead. Options:
- Tell the outline writer to merge items that are mechanical repetitions,
  such as "one class per channel", into one item.
- Make the "start the next item" rule absolute (for example, "while context
  is under 60 k") rather than "half the limit". For Haiku, half of 200 k
  never binds.
- Show the planner the cost model: per step, the base costs about $0.03 in
  re-reads alone on Haiku.

**L5: Turn PDFs into text once, in a setup step, by tool.** Image pages are
costly and say little about structure. Run `markitdown` or `pdftotext` once
into `state/spec.md` (or `work/`), keep a section index in env.md, and have
items cite line ranges. Doing this needs Bash, which brings us back to L1.
It could also be a seed-time action in wpk itself, which would need no
model tokens at all.

**L6: Haiku is cheap only when a check backs it.** At $0.08 a step, Haiku
was cheap. But its known weak spot,
reporting success it has not seen, went unchecked here. Cheap models need
*stronger* harness-side checks (L2), not weaker ones.

## What worked

- Caching: 0 breaks in 154 calls, and a stable base from step 2 onward.
- Mementos were concrete and short ("in `signals.py`, follow lines 156–183").
  The hand-off quality was good, even though the items were too small.
- Each step was short (30–150 s). Nothing timed out or crashed, and every
  step ran on attempt 1.

## Suggested follow-ups (not done)

1. `wpk check` warns when the profile has no Bash and the prompt implies
   running commands (L1).
2. The executor checks, on an `[x]` transition, that the item's check
   command appears in the transcript (L2).
3. Leave non-Markdown files in `state/` out of the step prompt, or warn
   about them (L3).
4. Re-run fw-proto-axi on a profile with Bash and a markitdown setup step,
   then compare cost per *passing* check.
