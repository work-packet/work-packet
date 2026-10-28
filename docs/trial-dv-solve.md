# Trial: dv-solve enhancement plan as a work packet

Status: runbook (2026-10-23). Nothing has been run yet.

The goal is to run `~/projects/fvutils/dv-solve/docs/enhancement_plan_2026-10-23.md`
(items 0–5) as a work packet. On the way, the trial tries out the outline
idea from `docs/stack-experiment.md` §1a.

## The layout

The project is an empty packet with a local clone of dv-solve inside it:

```
~/work-packet-runs/dvs-enh/
  project.toml  prompt.md
  packets/<root>/
    status.md  memento.md  journal.jsonl  state/
    work/               a git clone of dv-solve, on branch wpk/dvs-enh
      packages -> ~/projects/fvutils/dv-solve/packages
    state/enhancement_plan_2026-10-23.md   the plan: packet-owned, never committed
```

Plan documents (the enhancement plan, the outline, questions, progress
notes) live in the packet's `state/` and are **never committed** to the
project repo. Providing that place is part of what a packet is for: `state/`
is versioned per step by wpk, rolled back with a failed step, and kept out
of the code's history. Files over 4 KB are listed in the step prompt by
size, not shown (`prompt.py`, `FILE_MAX`); a small `outline.md` is shown in
full every step.

Why this layout works today:

- Claude Code runs with the packet directory as its working directory
  (`executor.py`, `model.run(..., pkt.path, ...)`). So `work/` is inside
  its project root and needs no `--add-dir`.
- The executor snapshots and restores only `status.md`, `memento.md`,
  `journal.jsonl`, `state/`, `children/` and `identity/` (`_snapshot`). It
  never copies `work/`. Never put the clone under `state/`: every file
  there is read into memory at each step, and swapped at commit.
- `wpk check` warns that `work` is "not part of the packet format". That is
  only a warning; `--strict` would fail on it. Spec v0.3 (long-running.md
  §7) makes `work/` official.

What is still missing, and what stands in:

| Needed | Stand-in |
|---|---|
| Commit per step by wpk (L2) | the model commits each item in `work/`, as the plan's ground rules say |
| A runner daemon (L3) | `wpk tick` by hand, or in a loop |
| Outline and gates (stack-experiment §1a) | the model keeps `state/outline.md` and `state/questions.md` (described in the instruction) |
| `ask:` (L1) | `resume: fail` with `reason: "question: …"`, then `wpk resume` |
| `wpk new` without a prompt (L1) | a placeholder prompt and `--paused`; you write the real instruction into `memento.md` afterwards |

## 0. Once: put `wpk` on the path

`wpk` is installed in editable mode in this repo's `packages/python` venv (README, Development). The dash extras
(starlette, jinja2, uvicorn) are already there.

```bash
export PATH=$HOME/projects/work-packet/packages/python/bin:$PATH
wpk --version        # wpk 0.0.1
```

## 1. Start the dashboard

In its own terminal:

```bash
wpk dash             # http://127.0.0.1:7878 (loopback only by default)
wpk url              # from another terminal: print the board's URLs
```

The board is read-only. The project appears on it after step 2.

## 2. Create an empty packet, paused

```bash
wpk new dvs-enh --dir ~/work-packet-runs/dvs-enh --model claude-sonnet-5 \
    --paused --prompt "placeholder; replaced before the first step"
P=$(ls -d ~/work-packet-runs/dvs-enh/packets/*)    # the root packet
```

## 3. Clone dv-solve inside, and copy the plan in

```bash
git clone ~/projects/fvutils/dv-solve $P/work
cd $P/work
git switch -c wpk/dvs-enh
```

- A local clone gets your `main` as it is, including the 9 commits not on
  origin.
- The plan goes into the packet's `state/`, not into the repo.
- Share the IVPM packages (the Python environment, CaDiCaL) with your
  checkout instead of fetching them again; the packet must not change them.
- Check that the build and the soundness gate work here before you hand it
  over.

```bash
cp ~/projects/fvutils/dv-solve/docs/enhancement_plan_2026-10-23.md $P/state/
ln -s ~/projects/fvutils/dv-solve/packages packages
packages/python/bin/python setup.py build_ext --inplace > build.log 2>&1; tail -3 build.log
env -u LD_LIBRARY_PATH packages/python/bin/python -m pytest -q > test.log 2>&1; tail -3 test.log
```

- If the build or the tests fail in the clone, fix that by hand first. A
  packet that cannot build spends its steps on setup.
- Note how long `pytest -q` takes; it sets `step_timeout` below.
- If `packages/` shows as untracked in `git status`, add it to
  `.git/info/exclude`, so the model's `git add` cannot pick it up.

The plan's other inputs are in `~/xezim_research/`, outside the packet.
Either copy what the items need into `$P/work/` (or `$P/state/`, if small),
or link it read-only:

```bash
mkdir -p $P/identity && ln -s ~/xezim_research $P/identity/xezim_research
```

wpk passes each `identity/` link to Claude Code with `--add-dir`.

## 4. Limits and permissions

Edit `~/work-packet-runs/dvs-enh/project.toml`. Add the limits above
`[permissions]`, and replace that table:

```toml
step_timeout = "60m"        # a build plus the full pytest; raise it if step 3 showed longer
step_budget_usd = 4.00
step_context_tokens = 120000
carry_session = true        # carry the session within an item (context.md C4)

[permissions]
allowed_tools = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
permission_mode = "acceptEdits"
```

**Bash** is needed for builds, tests, timing and commits.

- Unrestricted `Bash` is simple, and the clone is disposable. But it can
  reach anything your user can, including the shared `packages/` and your
  real checkout (the clone's `origin`).
- The narrow choice is a list of patterns, such as `Bash(git commit *)` and
  `Bash(env -u LD_LIBRARY_PATH *)`. It is fiddly; expect some denied calls.
- Either way, the instruction forbids `git push`, `ivpm` and network use.

## 5. Tell it what to do

Write the instruction in §6 into `$P/memento.md`, replacing the placeholder.
The whole file is the body; there is no front matter at step 0. Then:

```bash
wpk check ~/work-packet-runs/dvs-enh      # expect one warning: work/
```

## 6. The seed prompt

This uses the `list` template: the plan already has the items, and gates
are needed only for real questions. The soundness and uniformity gates in
the plan's ground rules become each item's checks.

```markdown
You are working on dv-solve in work/ (a git clone on branch wpk/dvs-enh).
The task is the plan in state/enhancement_plan_2026-10-23.md, items 0–5. Item 6 goes
to the backlog. Follow its ground rules exactly: one commit per item with
before/after numbers (in the commit message; plan and outline updates stay
in state/, never in the repo); the soundness gate; the uniformity gate; timing from
the C-API arm (item 0); all build, timing and test output to log files,
never the terminal. The comparison material in identity/xezim_research/ is
read only.

Never: git push, ivpm, network access, changes outside this packet, or
changes under work/packages/.

Keep the work as an outline in state/outline.md:
- One line per item: [ ] pending, [>] active, [x] done, [-] deferred
  (with a reason), [+] added during the run. Each item has a goal, refs
  (plan sections and files) and checks (commands).
- Work only on the active item. When you split an item, add its sub-items
  under it.
- Work you discover that is not this item: add it as a [+] item; do not do it.
- When an item closes, add its checks to a "Regression" list at the end of
  outline.md. Run that list (or the quick part of it) before you close each
  later item.

Keep questions for me in state/questions.md. Each has: the question, your
recommended answer, the items that depend on it, and whether you can go on
provisionally.
- If you can go on, do so, on your recommendation.
- Stop to ask (resume: fail, with reason "question: <one line>") only when
  no item can continue without an answer.

The first step: read the plan, write state/outline.md, set up item 0, and
stop with resume: now.

Every step:
- Do a bounded piece of the active item.
- Update the item's notes and the plan's Status table and Log line.
- Write the memento body as the instruction for the next step: the active
  item only, with its refs and checks. Not the whole plan.
- Continue with resume: now. Use resume: done when items 0–5 are done or
  deferred.
```

## 7. Go

```bash
wpk resume dvs-enh                 # PAUSED -> RUNNABLE
wpk step dvs-enh                   # one step; watch it on the board
wpk show dvs-enh                   # status, memento (the next instruction), children
cat ~/work-packet-runs/dvs-enh/packets/*/state/outline.md
```

When the first steps look right, let it run:

```bash
wpk tick --project dvs-enh --until-idle --max-steps 10
```

Raise `--max-steps` as you gain trust. There is no daemon yet, so a
sleeping packet needs another `tick`. Cron or a loop works for that.

## 8. When it asks, and when you take it back

- **A question.** The packet is `FAILED` with `reason: question: …`
  (`wpk show`, and on the board).
  1. Answer in `state/questions.md`, or add the answer to the top of
     `memento.md`.
  2. Run `wpk resume dvs-enh`, then `wpk tick` again.
- **Review.**
  - `wpk log dvs-enh` and `wpk log dvs-enh --step N` show each step's
    summary, diff and meta.
  - `git -C $P/work log --stat main..wpk/dvs-enh` shows the commits.
  - `wpk stats dvs-enh` shows cost and context per step.
- **Merge.** When you're happy, fetch the branch into your checkout and
  merge it yourself: `git -C ~/projects/fvutils/dv-solve fetch $P/work
  wpk/dvs-enh`.

## 9. What to record (for stack-experiment.md)

- Steps per item, cost per item (`wpk stats`), and mean and peak context.
- How many steps the outline and questions files cost to keep up, and
  whether the memento stayed focused on one item.
- Every question raised: blocking or provisional, and whether your answer
  differed from the recommendation.
- Departures from the plan, items added during the run, and regressions.

## 10. Next: the new step rules and a 120k limit (2026-10-23)

After 8 steps, a review (`docs/experiments/dvs-enh-steps.md`) changed the
protocol and step-sizing text. The packet picks those up at its next step,
but its `state/` still has the old shape. To bring it over, and to try a
larger context limit, run these in order. `wpk set` waits for the root
packet's lease too, so pause first.

1. **Pause between steps.** `wpk pause` takes the packet's lease, so it is
   refused while a step is running. If it says the packet is leased, wait
   for the step to end (the board's live view shows when it does), then try
   again:

   ```bash
   wpk pause dvs-enh
   wpk ps | grep dvs-enh          # shows PAUSED
   ```

2. **Raise the context limit to 120k.** The "start the next item only below
   half the limit" rule then falls at about 60k, and "stop now" at 144k:

   ```bash
   wpk set dvs-enh step_context_tokens=120000
   ```

3. **Hand it back with a note** to restructure `state/` first:

   ```bash
   wpk handoff dvs-enh -m "Before the next outline item: restructure state per the protocol's 'Working through a plan'. Move result notes from outline.md to state/log.md (keep outline under 4 KB), write state/env.md with the verified facts (DVS_SOLVER_PATH=\$PWD/build-prof, the venv, the build/configure commands), move questions.md to state/archive/, and fix 1a's placeholder check command. Then continue."
   ```

4. **Check the next step** (on the board's live view, or `wpk show
   dvs-enh`):
   - `state/outline.md` is under 4 KB;
   - `state/env.md` exists;
   - `questions.md` is in `state/archive/`.

5. **Compare.** After a few more items, run `wpk stats dvs-enh` and set the
   steps per item, orientation cost and peak context against the table in
   `docs/experiments/dvs-enh-steps.md`.

## Status log

### 2026-10-23: runbook
Plan documents moved to the packet's `state/`; they are never committed to
the project repo.
Written. Not run. Revised the same day: an empty packet with a clone of
dv-solve in `work/`, instead of a worktree linked through `identity/`.

### 2026-10-23: next steps
Added §10: pause, raise `step_context_tokens` to 120k, hand off with a note
to restructure `state/`, then compare against the 8-step review.
