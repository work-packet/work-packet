# Setup: a readiness checker and a setup wizard

Status (2026-10-24): S1–S7 and W1–W4 built (§8, §10). The setup lives at the project root; not yet used on a real project. A fresh session should be able to
pick up from this file alone. Read with long-running.md (§2 `work/`, §3
the walkthrough, §6 commands) and interaction.md §6 (the TUI).

## 1. The problem

Setting up `dvs-enh` (trial-dv-solve.md §2–§5) took eleven hand steps,
most of them about finding things and about rules you had to know:

| # | Step | What made it hard |
|---|---|---|
| 1 | `wpk new … --paused --prompt "placeholder"` | `new` needs a prompt you don't have yet |
| 2 | `P=$(ls -d …/packets/*)` | you hunt for the root's UUID directory |
| 3 | `git clone` into `$P/work`, `git switch -c wpk/dvs-enh` | branch naming is a convention; `work/` vs `work/<repo>` changed in between |
| 4 | point `origin` at the real remote | easy to forget; only matters at merge time |
| 5 | `ln -s …/packages`, add it to `.git/info/exclude` | otherwise the model's `git add` takes it |
| 6 | copy the plan into `state/` | must not go into the repo; over 4 KB it is listed, not shown |
| 7 | `identity/` links for read-only inputs | a directory name you have to know |
| 8 | build and test once in the clone, time it | "a packet that cannot build spends its steps on setup" |
| 9 | edit `project.toml`: limits and permissions | keys and values you have to know |
| 10 | write the instruction into `memento.md` | replace the placeholder; no front matter at step 0 |
| 11 | `wpk check`, `wpk resume`, `wpk step` | the warning about `work/` was expected noise |

None of it is hard once you know it. The fix is to make wpk know it:

- a **checker** (`wpk doctor`) that says what is present, what is missing
  and the exact command for each missing thing; and
- a **wizard** (`wpk setup`), a TUI that walks through the same list with
  a terminal built in, so you do the parts only you can do with your own
  shell and see each item turn green.

Both are the same list of checks. The wizard is the checker plus forms,
plus a shell.

## 2. Design rules

1. **One list of checks** (`setup.py`), used by `doctor`, the wizard and
   the board's **Setup** column. No setup knowledge lives in a front end.
2. **Every "missing" has a command.** A fix is a real `wpk …` or shell
   command with real paths, never "see the docs". You can paste it.
3. **Never ask for the UUID.** Everything takes a project name or WPID;
   `wpk path` prints the directories.
4. **Small helper commands do the work** (§5). The wizard's buttons and
   the checker's fixes call the same helpers, so anything the wizard does
   you can do in a script, and see in your shell history.
5. **Optional intent.** A `[setup]` table in `project.toml` (§4) says what
   the setup should contain (repos, inputs, links, smoke commands). With
   it, the checker can say "dv-solve is not cloned yet" instead of only
   "work/ is empty", and `wpk setup --apply` can redo a setup from the
   file. Without it, the checker still runs the generic checks.
6. **Read-only by default.** `doctor` changes nothing, except with
   `--run` (smoke commands) and `--fix` (only the fixes marked safe).

## 3. The checks

Each check has an id, a group, a level and, when it is not `ok`, a fix:

```python
@dataclass
class Check:
    id: str          # "repo.dv-solve.branch"
    group: str       # "tools" | "project" | "work" | "inputs" | "instruction" | "limits" | "go"
    level: str       # "ok" | "missing" | "warn" | "info"
    title: str       # "dv-solve is on branch wpk/dvs-enh"
    detail: str = "" # one or two lines: why it matters
    fix: list[str] = ()   # commands, in order
    safe: bool = False    # --fix and the wizard's "Do it" may run it unasked
```

`readiness(project) -> list[Check]`. `missing` blocks the hand-off;
`warn` does not.

| Group | Check | Level when not met | Fix |
|---|---|---|---|
| tools | `claude` (or `$WPK_CLAUDE`) on `PATH` and `--version` works | missing | install hint |
| project | registered, `project.toml` valid (`wpk check` errors folded in) | missing | as `check` says |
| project | root is held for setup (not runnable before it is ready) | warn | `wpk take <p>` |
| tools | `git` on `PATH`, only when `work/` holds a git repository | missing | — |
| work | the project's `work/` has something in it | warn | `git clone <path-or-url> …/work/<name>` |
| work | each repo `[setup]` lists is cloned in `work/` | missing | `git clone`, and `ln -s` for each `share` (safe) |
| work | your clone is not on the steps' branch (`wpk/<project>`): their worktree needs it | missing | `git -C … switch main` |
| work | your clone has no uncommitted changes (the steps' worktree starts from `HEAD`) | warn, before the first step | commit |
| work | untracked links in your clone (`packages/`) | info: linked into the worktree and excluded | — |
| work | `[setup]` `share` dirs are linked in your clone | missing | `ln -s …` |
| work | an entry that is not git: steps change it in place, no rollback | warn | — |
| work | (packets from before §10) clones inside the packet: on a branch, clean, untracked links excluded | missing | as before |
| work | `.envrc` present (steps do not load it until `step_env` is built) | info | — |
| inputs | each `[setup]` input is in `state/` (the project's before the first step, the packet's after) | missing | `wpk add-input <p> <file>` (safe) |
| inputs | `state/` files over 4 KB (listed, not shown in the prompt) | info, one summary line | — |
| inputs | each `identity/` link resolves; each `[setup]` link exists | missing | `rm` the dangling link / `ln -s DIR …/identity/<name>` (safe) |
| instruction | there is a first instruction: `prompt.md` before the first step, `memento.md` after | missing | `wpk instruct <p>` |
| instruction | it names `work/<repo>` paths that exist, and the `state/` files it names exist | warn | — |
| limits | `step_timeout`, `step_budget_usd`, `step_context_tokens`, `model`, with "(default)" where not set | info | `wpk set <p> key=value` |
| limits | `[setup]` has smoke commands (when there are work repos) | warn | `wpk add-smoke <p> --repo R '<cmd>'` |
| limits | `step_timeout` ≥ 1.5 × the last smoke run's time | warn | `wpk set …` with the number |
| limits | permissions: tools listed (unrestricted `Bash`, the default, noted); no `Bash` with work repos flagged | info / warn | `wpk allow <p> …` |
| limits | smoke commands passed (last `--run`, and the repo's `HEAD` then) | missing if failed, warn if never run or stale | `wpk doctor <p> --run` |
| (next) | nothing missing | — | `wpk handoff <p> -m "…"`, as the last line |


### `wpk doctor` output

```
$ wpk doctor dvs-enh          # after git clone, add-input, link, allow Bash, add-smoke;
                              # packages/ linked by hand, so not excluded
dvs-enh  ~/dvs-enh   root 57ecad2a  (PAUSED: setup)

tools
  ✓ claude 2.1.280 (Claude Code)

project
  ✓ project.toml and packets valid
  ✓ root is held for setup

work      ~/dvs-enh/packets/57ecad2a-d4e2-4f03-8fc3-1b629424afc7/work
  ✓ dv-solve on wpk/dvs-enh
  ✗ dv-solve/packages is an untracked link
      The model's `git add` would commit it. Exclude it in this clone only.
      $ echo packages >> ~/dvs-enh/packets/57ecad2a-…/work/dv-solve/.git/info/exclude

inputs
  · state/: 1 file, 1 over 4 KB (listed by size in the prompt, not shown)
  ✓ identity/research -> ~/research (read-only)

instruction
  ✗ no instruction yet
      memento.md is what the first step is told to do.
      $ wpk instruct dvs-enh --template outline

limits
  · step_timeout 20m (default), step_budget_usd 1.00 (default), step_context_tokens 80000 (default), model claude-haiku-4-5-20251001 (default)
  ! smoke commands not run yet
      $ wpk doctor dvs-enh --run
  · Bash is unrestricted
  · tools: Read, Write, Edit, Glob, Grep, Bash (acceptEdits)

2 missing, 2 warnings.  Next: echo packages >> ~/dvs-enh/packets/57ecad2a-…/work/dv-solve/.git/info/exclude
```

- Paths are printed in full (shortened with `~`), so the commands paste.
- The last line is always the single next thing to do; when nothing is
  missing it is the `wpk handoff` command.
- `--json` prints the list of checks, for the wizard, the board and tests.
- Exit codes: 0 ready, 1 something missing, 4 usage error.
- With no project, `doctor` checks tools and the home, and lists each
  project's count of missing items.

## 4. `[setup]` in `project.toml`

Optional. The wizard writes it as you go; you can write it by hand, keep
it, and reuse it for the next project of the same shape.

```toml
[setup]
smoke_timeout = "20m"

[[setup.repo]]
name = "dv-solve"                        # work/dv-solve
from = "~/projects/fvutils/dv-solve"     # local clone: no network, gets local commits
branch = "wpk/dvs-enh"                   # default: wpk/<project>
share = ["packages"]                     # symlink from `from`, add to .git/info/exclude

[[setup.input]]                          # copied into state/, never into a repo
from = "~/projects/fvutils/dv-solve/docs/enhancement_plan_2026-10-23.md"

[[setup.link]]                           # identity/<name>, read-only, passed with --add-dir
from = "~/xezim_research"

[[setup.smoke]]
repo = "dv-solve"
run = "packages/python/bin/python setup.py build_ext --inplace"
[[setup.smoke]]
repo = "dv-solve"
run = "env -u LD_LIBRARY_PATH packages/python/bin/python -m pytest -q"
```

- `wpk setup <p> --apply` does every step whose check is `missing` and has
  a helper (clone, share, input, link), then runs `doctor`. It never
  writes the instruction or changes limits.
- `wpk new <p> --from-setup other/project.toml` copies `[setup]`,
  `[permissions]` and the limits from another project: the second
  dv-solve packet is then `new`, `--apply`, `instruct`, `handoff`.
- `doctor --run` runs each smoke command in its repo, under `step_env`,
  output to `<project>/.setup/smoke-N.log`. It records pass/fail, the
  time and the repo's `HEAD` in `<project>/.setup/smoke.json`; a later `HEAD` makes the
  result stale.

`spec.md` gets the table as optional and ignored by the executor.

## 5. Helper commands

Each is small, does one setup step, prints what it did, and is idempotent
(a second run says "already done").

| Command | Does |
|---|---|
| `wpk path <p> [--work [NAME] \| --state \| --packet]` | Print the project's directory (or its `work/`, an entry, the `state/` inputs go to now, the root packet) |
| `wpk shell <p>` | A shell at the project root (in `work/<name>` if there is one entry), `WPK_*` set |
| `wpk add-input <p> FILE…` | Copy into `state/` (the project's, or the packet's after the first step); warn if over 4 KB; append to `[setup]` |
| `wpk add-smoke <p> [--repo R] CMD` | Append a `[[setup.smoke]]` command for `doctor --run` |
| `wpk instruct <p> [--file F] [--template T]` | Edit the first instruction (`prompt.md`; the packet's `memento.md` after the first step) in `$EDITOR`, starting from a template (`list`, `outline`, `plan-only`; the dvs-enh prompt is the seed of `outline`), then run the instruction checks |
| `wpk new <p>` | Creates the structure you fill in: `prompt.md` (empty without `--prompt`), `state/`, `identity/`, `work/`. Without `--prompt` the root is `PAUSED`/`setup` (L1's `HELD`/`setup` later); it prints what goes where, and "next: `wpk setup <p>` or `wpk doctor <p>`" |

## 6. The wizard: `wpk setup [<p>]`

Textual, in the `tui` extra (`work-packet[tui]` = textual + pyte). It is
the first screen of the later `wpk tui` (interaction.md §6): a project in
**Setup** opens in it.

```
┌ wpk setup ─ dvs-enh ─────────────────────────────── HELD: setup ┐
│ 1 ✓ Project        │ Work repos                                  │
│ 2 ▶ Work repos     │                                             │
│ 3 · Inputs         │ ✓ dv-solve  cloned, on wpk/dvs-enh, clean   │
│ 4 · Smoke test     │ ✗ packages/ is untracked                    │
│ 5 · Limits         │    The model's `git add` would commit it.   │
│ 6 · Permissions    │    [Do it]  [Insert in shell]               │
│ 7 · Instruction    │                                             │
│ 8 · Hand off       │                                             │
│                    │ [Add repo…]                                 │
│                    ├─ shell: …/2454b9ba/work/dv-solve ───────────┤
│                    │ [wpk:dvs-enh] dv-solve$ ls packages         │
│                    │ python  cadical  ...                        │
│                    │ [wpk:dvs-enh] dv-solve$ █                   │
├────────────────────┴─────────────────────────────────────────────┤
│ ^] shell/form  F2 full shell  F5 recheck  n next  q quit  2 missing│
└──────────────────────────────────────────────────────────────────┘
```

**Left:** the stages, which are the check groups, with a mark each.
You can jump to any stage; nothing forces the order.

**Right, top:** the selected stage.

- Its checks, each with its detail and fix.
- **Do it** runs the helper for a `safe` fix, or one that only writes
  inside the packet.
- **Insert in shell** types the fix into the terminal *without* a newline:
  you read it, edit it and press Enter yourself. This is the default for
  anything outside the packet, such as a `git remote` that reaches your
  real checkout.
- Forms where a form is easier than a command:
  - *Project*: name, directory, model.
  - *Add repo*: from, name, branch, share.
  - *Limits*: timeout, budget and context, with the smoke time shown next
    to the timeout.
  - *Permissions*: presets ("read-only", "build and test", "unrestricted
    Bash") with the `allowed_tools` list editable.
  - *Instruction*: pick a template, edit in a Markdown text area (or
    `$EDITOR` in the shell pane), checks underneath.
  - Each form writes through the helpers and `wpk set`; nothing writes
    `project.toml` directly.

**Right, bottom:** a real shell (`$SHELL` on a pty, drawn with pyte).

- It starts in the packet directory, or in `work/<repo>` on the Work and
  Smoke stages. It has `WPK_PROJECT`, `WPK_WPID`, `WPK_PACKET` and
  `WPK_WORK` set, and `[wpk:<p>]` on the prompt.
- An rc snippet sets `PROMPT_COMMAND` to write a byte to a FIFO. After
  every command you run, the wizard re-runs the checks, and the marks
  change as you work: clone by hand and **Work repos** turns green. F5
  rechecks too.
- `Ctrl+]` moves focus between the form and the shell; the shell gets
  every other key, so `vim` and `less` work.
- F2 suspends the TUI (`App.suspend()`) into a full-screen shell in the
  same directory; `exit` comes back and rechecks. This is also the
  fallback if pyte draws something badly.
- The shell's history is kept in `<project>/.setup/history`. "What did I do
  to set this up?" then has an answer, and `--apply` can learn from it
  later (§9).

**Hand off** (the last stage) shows the doctor summary, the instruction
as the model will see it (`prompt.py` rendering, so the 4 KB rule is
visible), and a note field. **Hand off** is enabled only when nothing is
`missing`. It runs `wpk handoff`.

`wpk setup` with no project starts at **Project** and runs `wpk new`
(no prompt) when you leave that stage. `wpk setup <p>` on a project that
is not held for setup opens read-only, with **Take back** offered.

## 7. Where it shows elsewhere

- **Board:** a project held for `setup` shows "2 missing · next: …" on
  its card, from `doctor --json`, with the commands copyable. This is the
  read-only side; no terminal in the browser.
- **`wpk handoff`** runs the checks first and refuses on `missing`, with
  the doctor lines (`--force` to override). This replaces "run `wpk
  check` and expect one warning".
- **`wpk check`** stays the format validator. It stops warning about
  `work/` once spec v0.3 makes `work/` official (L2).

## 8. Build plan and progress

Each stage is usable on its own. The order puts the checker first, so the
wizard is built on something already tested. Mark `[x]` when a stage's
"done when" holds and its tests pass; note anything left in the status log.

Decisions taken for the build (§9 answered with the recommendations):
`doctor` is the checker's name; smoke runs warn; `origin` stays the local
path; no history learning yet; our own pty + pyte widget.

Until L1 lands there is no `HELD` state: a project held for setup is
`PAUSED` with `reason: setup`, and its memento body is empty. `wpk check`
accepts the empty memento in that state. `wpk resume` and `wpk handoff`
on such a packet run the doctor first. Setup records (smoke logs, results,
shell history) go in `<project>/.setup/`, not in `state/` (the step prompt
would show them).

- [x] **S1 Paths and the setup hold.** `wpk path`, `wpk shell`; `wpk new`
  without `--prompt` (`PAUSED`/`setup`, empty memento, no `prompt.md`);
  `check` accepts it; `work` becomes a known packet entry (§7). Done when
  the dvs-enh runbook's step 2 is one command.
- [x] **S2 Checks and `wpk doctor`.** `setup.py` with the generic checks
  (§3), `wpk doctor [<p>] [--json] [--fix]`; `resume`/`handoff` of a
  setup-held packet refuse on `missing` (`--force`). Done when `doctor` on
  a fresh `new` lists the missing items with pasteable fixes; tests on tmp
  projects for each check.
- [x] **S3 Helpers.** `add-repo` and `link` (both removed later, see the status log), `add-input`, `instruct`
  (templates `list`, `outline`, `plan-only`). Done when a dvs-enh-shaped
  setup is done with helpers only and `doctor` is all green (test).
- [x] **S4 `[setup]`.** The table and its checks, `wpk setup <p> --apply`,
  `doctor --run`, `new --from-setup`. Done when a second project is set up
  with `new --from-setup`, `--apply`, `instruct`, `handoff` (test).
- [x] **S5 Wizard.** Textual app (`tui` extra): stages, checks, Do it /
  Insert, forms, F2 suspend shell. Done when Textual pilot tests drive a
  project end to end.
- [x] **S6 Embedded shell.** pty + pyte pane, `Ctrl+]`, PROMPT_COMMAND
  recheck, history in `.setup/history`. Done when a clone typed in the
  pane turns its mark green (test with a scripted shell).
- [x] **S7 Board.** A setup-held project's card shows the doctor summary
  and next command.

## 9. Open questions

1. **Name.** `doctor` (checker) and `setup` (wizard), or a single `wpk
   setup` with `--check`? Recommendation: `doctor` alone, so the checker
   is easy to find and easy to script.
2. **Smoke runs before hand-off.** Make them required (`missing` until
   one has passed) or only warn? Recommendation: warn, but `handoff`
   asks for confirmation if smoke never ran.
3. **The `origin` rule.** Setting `origin` to the real remote makes
   merging easy, but a model with unrestricted Bash could then push.
   Keep the local path as `origin` and add the real remote under another
   name, `upstream`? Recommendation: keep the local path as `origin`,
   since a push to a local checkout is harmless; merge with `git fetch`
   from the checkout, as dvs-enh did.
4. **Learning from the shell history.** Offer to turn commands run in the
   pane (`git clone`, `ln -s`, `cp … state/`) into `[setup]` entries?
   Nice, but heuristic; after S6, if wanted.
5. **Embedded terminal library.** Our own pty + pyte widget (about 300
   lines, no new dependency beyond pyte) or `textual-terminal` (third
   party, thinly maintained)? Recommendation: our own widget.

## 10. The setup lives at the project root (W)

You set a project up at its root, never in `packets/<UUID>/`. The root
packet is filled from the root when a step starts, and it **references**
`work/` instead of holding it.

```
dvs-enh/
  project.toml
  prompt.md          the first instruction
  state/             inputs: the plan, notes
  identity/          read-only links
  work/
    dv-solve/        your clone (git), left on its own branch
    data/            anything that is not git
  .setup/            smoke worktrees and logs, shell history
  packets/<UUID>/    the runner's; you do not go in here
    work/dv-solve/   a git worktree of ../../work/dv-solve, branch wpk/dvs-enh
    work/data ->     ../../../work/data (a link)
```

**At the start of each step of the root** (before the snapshot, inside the
lease), `workspace.prepare` does, idempotently:

1. **Seed, once.** If the journal has no `seed` record: copy the root's
   `state/` files into the packet's `state/`, and `prompt.md` into
   `memento.md` if the memento has no instruction. Then append
   `{"type": "seed", "t", "files": [...]}`. A crash before the record
   repeats the copy, which is harmless: no step has run yet.
2. **Identity, every step.** Each root `identity/<n>` that the packet
   lacks becomes a link to the same target.
3. **Work, every step.** Each root `work/<n>` that the packet lacks:
   - a git repository: `git worktree add` on branch `wpk/<project>`
     (created from the clone's `HEAD` the first time), and the clone's
     shared directories are linked into the worktree: `[setup]`'s
     `share` list, and any top-level link the clone does not track;
   - anything else: a relative link `work/<n> -> ../../../work/<n>`, and
     its real path is passed to the harness like an `identity/` link.

   Nothing is ever removed or replaced. A step that cannot prepare its
   workspace (e.g. `wpk/<project>` is checked out in your clone) is a
   failed attempt, with the reason in the journal.

**Git is used only for what is git.** Plain directories never touch git.
They are shared live: a failed step's changes to them are **not** rolled
back (long-running.md §2's reset and commit apply to work repos only, and
are not built yet). `doctor` says so for each one.

**Why a worktree and not a copy.** A clone with its build is gigabytes,
and build trees record absolute paths (dv-solve's `build-prof/CMakeCache.txt`
does), so a copied or moved build breaks. A worktree shares the git objects,
checks out in seconds, and the runner's commits are on `wpk/<project>` in
your clone already: `git log wpk/dvs-enh` there, merge when ready. Its cost:
build directories are not shared, so the first step builds from scratch.

**Before and after the seed.** The helpers write to the root until the
seed; afterwards `add-input` and `instruct` write to the packet (the root's
copies are history then). Clones and `identity/` links are always at the root;
the next step picks them up. `doctor` and the wizard look where the helper
would write, and say which.

**Smoke runs** (`doctor --run`) run in a worktree of their own,
`.setup/smoke/<repo>` (detached at the clone's `HEAD`, shares linked,
reused between runs), so they test and time what a step will see. Plain
directories run in place.

**Checks that change.** In your clone: being on `wpk/<project>` is missing
(the worktree needs that branch); uncommitted changes are a warning (the
worktree starts from `HEAD`, without them); an untracked link is still
missing (git's `info/exclude` is shared with the worktrees). A plain
directory is a warning: no rollback.

**Existing projects** (dvs-enh) are unchanged: their packets have run
already, so there is no seed, and the root has no `work/` to reference.

### Build plan (W)

- [x] **W1 `workspace.py`.** `prepare(pkt, proj, settings)`: seed, identity,
  work (worktree or link); `seed` journal record (schema); called from the
  executor's prepare for the root; failure is a failed attempt; non-git
  real paths go to `--add-dir`. Tests: seed once, crash-repeat, worktree
  created and reused, branch conflict fails the attempt, plain dir linked,
  no git installed for a plain-only project.
- [x] **W2 Helpers and `doctor` at the root.** `add-repo` clones to the
  root (no branch), `add-input`/`instruct` write to root or packet,
  `link` to the root; the checks above; `wpk path` (project by default,
  `--packet`, `--work`, `--state`); `wpk shell` starts in the root.
- [x] **W3 Smoke in a worktree.** `.setup/smoke/<repo>`.
- [x] **W4 Wizard and board.** The wizard's shell starts at the root;
  texts; spec.md §3/§4; this doc's §3–§6 brought in line.

## Status log

### 2026-10-24: design

Written from the dvs-enh setup (trial-dv-solve.md §2–§5). Not built.

### 2026-10-24: plan

Design agreed with the §9 recommendations. Building S1–S7 in order.

### 2026-10-24: S1–S4 built

`setup.py` (checks and helpers), `wpk doctor/path/shell/add-repo/add-input/
link/add-smoke/instruct`, `wpk setup --apply`, `new --from-setup`; tests in
`tests/test_setup.py`. Changes from the design:
- `add-smoke` is a new helper (a smoke command was otherwise TOML by hand).
- `origin` is not checked (decision 3): the clone's `origin` stays the local
  path.
- `state/` is one summary line (`-v` lists the files); per-file lines were
  noise on a real packet.
- No "logged in" check for claude: there is no cheap, reliable test.
- `doctor dvs-enh` on the finished trial found an untracked `build` link
  and uncommitted result files in its clone: real findings.

### 2026-10-24: S5–S7 built

`src/work_packet/tui/` (`terminal.py`: pty + pyte pane; `setup_app.py`: the
wizard), the `tui` extra (textual, pyte), and the board card. Tests:
`tests/test_setup_tui.py` drives the wizard with Textual's pilot and a real
bash in the pane (a `git clone` typed there turns **Work repos** green).
Screenshots were checked by hand. Changes from the design:
- The board shows setup on the card in the **Paused** column ("Setting up:
  N missing", the next command), not in a column of its own.
- Permissions are a comma-separated list in the Limits form, not presets.
- The Hand off stage does not yet preview the rendered step prompt.
- A project that is not held for setup opens normally, with a **Pause it**
  button if it could start; the helpers refuse while a step runs.
- History is kept per project in `.setup/history` (bash only); learning
  `[setup]` from it (§9 q4) is not built.

Next: use `wpk setup` for the next real project, and fix what gets in the
way.

### 2026-10-24: setup at the root (§10)

You do not want to populate a UUID directory. Agreed: `work/`, `state/`,
`identity/` and `prompt.md` live at the project root; the root packet is
filled on demand when a step starts and references `work/` (git worktrees
for git repositories, links for anything else; nothing depends on git
unless the entry is git). Building W1–W4.

### 2026-10-24: W1–W4 built

`workspace.py` fills the root packet when a step starts (seed once;
identity links and `work/` entries every step: a git worktree for a git
repository, a relative link for anything else), called from the executor's
prepare; a failure is a failed attempt. `setup.py`, the CLI and the wizard
work at the project root; `wpk path` prints the project directory by
default. Tests: `tests/test_workspace.py` (including a run with no git on
`PATH`), and the setup tests now run a first step and look in the packet.

Found while building:
- A link shared into a worktree showed as untracked there. Git reads
  `info/exclude` only from the clone's common directory, so `prepare` adds
  each shared name to the clone's `info/exclude` (it covers the clone and
  every worktree).
- Because of that, an untracked link in your clone is no longer "missing"
  in `doctor`: it is shared and excluded at the first step (info).
- Smoke worktrees under `.setup/smoke/<repo>` are registered in your clone
  (`git worktree list` shows them). Delete with `git worktree remove`.

### 2026-10-24: `add-repo` removed

It was `git clone` plus `ln -s` plus a `[setup]` entry. The workspace now
shares and excludes untracked links on its own, so you clone by hand (or
the wizard types `git clone … work/<name>` into its shell). `[setup]` repo
entries are not needed for that: `new --from-setup` reads them from the
source project's `work/` (each clone's `origin` and its untracked links,
`setup.repo_entries`). A `[[setup.repo]]` written by hand still works:
`doctor` shows its `git clone` and `ln -s` commands, and `--apply` runs them.

### 2026-10-24: `link` removed

It was `ln -s` into `identity/` plus a `[setup]` entry. Link by hand
(`ln -s DIR <project>/identity/<name>`; the wizard types it into its
shell). `new --from-setup` reads the links from the source project's
`identity/` (`setup.repo_entries`'s sibling `link_entries`); a
`[[setup.link]]` written by hand still works through `doctor`'s commands
and `--apply`. The helpers left are `add-input` (after the first step its
destination is the packet's `state/`), `add-smoke` and `instruct`.

### 2026-10-24: `wpk new` makes the structure

`wpk new` creates `prompt.md` (empty without `--prompt`), `state/`,
`identity/` and `work/` at the project root, and says what goes in each.
Empty ones change nothing: the first step seeds nothing and links nothing.

### 2026-10-24: `test_external_sigkill` made robust

It kills `wpk step` at seeded random moments and expects the same end state.
Each kill can cost an attempt, so whether three land on one step (packet
FAILED) depends on timing: it flipped with ~1 ms more work per step. The
test now sets `max_attempts = 30` in its runner's `config.toml` and
normalises "attempt N of M" in prompts; exhausting attempts is tested
elsewhere. The executor also stopped re-reading `project.toml` for `[setup]`
(`Settings.setup`).
