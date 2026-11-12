# Agent dispatch: packets created and started from a session

Status: **built, not yet tried end to end with a real model or a browser**
(2026-11-11). Decisions in §8; plan, status and what differs from the design in §9.

Two requests this design has to serve, typed into a Claude or Codex session:

- **Batch.** "Divide this list of tests up for three independent agents. Create
  three new packets on this board from this repo, and have each agent implement
  its tests on a new branch. When the tests are complete, each agent pushes its
  changes."
- **Interactive.** "Create a new VS Code packet on the Verilator board from my
  Verilator fork, on a new branch. Hand it this testcase to investigate."

Both are the same act: **a session makes packets and gives each one its first
instruction.** They differ in who works the new packet: the runner (batch) or
the user in VS Code (interactive). The two are co-designed here because they
share almost everything: where packets go, how the agent knows what "my
Verilator fork" means, the CLI call the agent makes, and the record the board
keeps of who made what.

## 1. Verdict

| Piece | Feasible? | Notes |
|---|---|---|
| Create N packets from a session, on any board, cloned on a new branch, started | **Yes, mostly exists.** | `wpk start clone … board=B objective=… --go` already works (§2). Missing: a default folder, a batch form, a skill, a wake-up of wpkd. |
| Per-board and global packet directory | **Yes, small.** | One resolver used by the CLI, `/new`, watchers and requests. |
| "When done, push" | **Yes.** | Generalise the watcher's on-completion PR delivery (`pr.py:190`) to any packet. The executor pushes, not the agent. |
| Global and board agent notes ("my Verilator fork") | **Yes, new.** | Notes files plus a small repo registry. Nothing exists at global or board level today. |
| Create a VS Code packet from a session | **Yes.** | `/new` already has `start=ide-web` / `ide-desktop`; the CLI needs the same. |
| Give the VS Code session its first instruction | **Mostly.** | wpk cannot type into a Claude session it did not start. It *can* start one: a run-once VS Code task on folder open that launches `claude` with the kickoff text (§6.2). Needs a spike. |
| Open a browser tab for it | **One click, not zero.** | The browser is usually on another machine and pop-up blockers need a gesture. The agent prints the link, and the open board tab offers it. Zero-click needs a helper on the user's machine (the future extension); out of scope. |

## 2. What exists today

From the code (details in the investigation notes; references are to `src/work_packet/`):

**Creation.** Every path goes through the starter engine:
`starters.from_values` → `check` → `preview` → `make` (`starters/__init__.py:146-477`).
A recipe has `name, dir, folder, clone{url,ref,branch,share,tool}, objective,
inputs, origin, model, harness, extra, hold, from, board`. The built-in `clone`
starter clones (ivpm or git), runs `git switch -c <branch>`, and moves the packet
to `board`. `hold=False` with an objective makes the packet RUNNABLE at once.
`preview` raises every refusal before anything is made.

**Where packets go.** No setting. The folder is `folder`, else `<dir>/<name>` with
`dir` defaulting to `"."` (`starters/__init__.py:177`). The dashboard defaults to
the parent of the last packet's folder, else `~` (`dash/app.py:1921`). Each watcher
has its own required `dir`. Requests go next to the requester.

**Config.** Global `$WPK_HOME/config.toml` over a site file. Boards are
`$WPK_HOME/boards/<name>.toml` with only `name, created, title, watch`
(`schema.py:1334`). Agent instructions exist only per project (`<project>/agent.md`,
fed to runner steps, not to interactive sessions). No repo registry; the nearest
things are `[[forge]]`, watcher `repos`, and `[[setup.repo]]`.

**From inside a session.** Any `wpk` command runs as the user, against any packet
or board; there is no token or scoping (`sched/authz.py`). So a session can
already run `wpk start clone … board=other --go`. Nothing tells it how, and
without `dir=` the packet lands inside the caller's folder. The CLI does not wake
wpkd, so the new packet waits for its next pass.

**Skills.** The `wpk-*` skills are strings in `skills.py`, installed user-wide when
the board opens VS Code for a packet (`ide.py:121`).
*Bug found on the way:* `wpk-handoff` tells the agent to run `wpk next . -m "…"`
(`skills.py:77`), but `wpk next` needs `--file`/`--draft`; `-m` is only a note, so
that branch of the skill always fails.

**Pushing.** `pr.py` is the guarded push path (refuses base branch, detached HEAD,
dirty tree, nothing ahead; never forces). `pr.sync` (`pr.py:190`) opens a PR when a
watcher-made packet completes, if the watcher has `pr = draft|ready`. Steps can
also `git push` themselves (Bash is unrestricted); only prompt text discourages it.

**VS Code.** `POST /p/<project>/ide` claims the packet and either serves web VS Code
under `/ide/<key>/` (lazy `code serve-web` behind wpkd's Guard) or renders a
`vscode://` link. After `/new` with `start=ide-*` the board redirects to
`/p/<project>?open=<mode>` and the page auto-submits. Nothing starts `claude` in
VS Code; the SessionStart hook only adds a briefing once the user starts it.
There is no push channel to a browser beyond the open board tab's 30 s
`/attention.json` poll and ntfy.

## 3. Packet directories

### 3.1 Settings

```toml
# $WPK_HOME/config.toml
[packets]
root = "~/packets"          # packets go in <root>/<board>/<name>
layout = "board"            # "board": <root>/<board>/<name>;  "flat": <root>/<name>

# $WPK_HOME/boards/verilator.toml
dir = "~/work/verilator"    # this board's packets go in <dir>/<name>
```

A site config may lock `packets.root` like any other key.

### 3.2 One resolver

`registry.packet_dir(board, name, h)` returns the folder for a new packet. Order:

1. An explicit `folder=` / `dir=` (CLI, recipe, form) wins.
2. The board's `dir`.
3. `[packets] root` with the layout (`<root>/<board>/<name>`; `main` is a board like
   any other, so `~/packets/main/<name>`).
4. Nothing set: today's behaviour (CLI: `.`; dashboard: last packet's parent), so
   nobody's setup changes until they opt in.

Every creator calls it: `starters.folder_of`, `/new` (the field is prefilled with
the resolved path and stays editable), watchers (their `dir` becomes optional and
falls back to the resolver), `requests.send`, and the setup TUI. `wpk new` keeps
`--dir`/`--here` and gains `--board`.

**One change of default for agents:** when `WPK_WPID` is set (we are inside a
packet) and steps 1–3 give nothing, `wpk start` refuses rather than create a
packet inside the caller's folder: "set `[packets] root` or pass dir=". Nesting a
packet inside another's tree by accident is never what was meant.

Editing: `wpk board set <name> dir=<path>`, `wpk config set packets.root <path>`,
and fields on the board's Settings and the global Settings page.

## 4. Agent notes: what "my Verilator fork" means

### 4.1 Two kinds of data

**Free text notes** — conventions, preferences, how this group of work is done:

- Global: `$WPK_HOME/agent.md`
- Board: `$WPK_HOME/boards/<name>.md` (beside the board's `.toml`)
- Project: `<project>/agent.md` (exists)

Markdown files, not TOML strings: they are prose, the user edits them in an
editor, and they diff well. The dashboard edits them in place (board Settings,
global Settings).

**A repo registry** — the structured part, because the agent must turn a phrase
into an exact URL, ref and branch, and a wrong guess clones the wrong thing:

```toml
# config.toml (global) or boards/<name>.toml (board; board entries shadow global by name)
[[repo]]
name = "verilator"                       # what wpk and the agent call it
url = "git@github.com:mballance/verilator.git"
aliases = ["my verilator fork", "verilator fork"]
upstream = "https://github.com/verilator/verilator"   # optional, for PR base / rebase notes
ref = "master"                           # default base
branch_prefix = "mb/"                    # new branches: <prefix><packet-name>
tool = "git"                             # or "ivpm"
share = true                             # reuse a reference clone (clone.share)
notes = "Build with ./ci/build.sh; tests in test_regress/."
```

The clone starter learns `clone=@verilator` (or `repo=verilator`) to mean "this
registry entry", filling `url`, `ref`, `tool`, `share` and a default branch of
`<branch_prefix><name>`. `wpk repos [--board B] [--json]` lists what the agent may
pick from, with aliases. Matching an alias to the user's words is the agent's job;
the registry only makes the answer exact and checkable.

### 4.2 How the agent sees them

Notes are context, not always-on prompt: a big global note in every step prompt
is a cost on every step.

- **`wpk context [--board B] [--json]`** prints global notes, the board's notes
  and the repo registry, resolved. The dispatch skill (§5.3) runs it first.
- **Interactive sessions:** the SessionStart briefing adds one line per non-empty
  notes file ("Board notes: 14 lines — `wpk context`") rather than the text, plus
  the board's notes in full if they are short (≤ 40 lines, a setting).
- **Runner steps:** `prompt/step.md` gets "## Board notes" and "## Your notes"
  sections above the existing "## Project notes (agent.md)", in that order (general
  to specific). Each is capped (default 4 KB); past the cap the step sees the
  first part and a pointer to `wpk context`.

## 5. Batch dispatch

### 5.1 The call

`wpk start` already does one packet. Add a batch form, all-or-nothing on
refusals:

```sh
wpk start --recipes - --go --json <<'EOF'
[
  {"starter": "clone", "name": "uvm-tests-a", "board": "dv", "clone": "@ibex",
   "objective": "Implement tests 1-4 ...", "inputs": ["tests-a.md"]},
  {"starter": "clone", "name": "uvm-tests-b", ...},
  {"starter": "clone", "name": "uvm-tests-c", ...}
]
EOF
```

- Every recipe is `preview`ed first; one refusal (name taken, board unknown,
  folder not empty) refuses the whole batch and names each problem. Then `make`
  runs each in turn; a failure after some are made reports what was made and
  leaves it (each `make` already cleans up its own failure).
- `--dry-run` prints the previews: the folders, branches and boards, so the agent
  can show the user exactly what will happen.
- `--go` makes them RUNNABLE and **wakes wpkd** (the same `poke()` `/new` uses;
  the CLI gains it for single `wpk start --go` too).
- `--json` returns `[{name, wpid, folder, branch, board, url}]`; `url` is the
  packet's board page.

Inputs: `inputs` already takes files. The batch form also takes
`"inputs": [{"name": "tests.md", "text": "..."}]`, so the agent can hand each packet
its slice of the list without writing temp files.

### 5.2 Lineage and the board

Each made packet records where it came from:

```toml
# project.toml of the new packet
[origin]
by = "packet:3f9a12cd"          # the dispatching packet's wpid ("user" from /new)
batch = "b-20261111-1432-uvm"   # shared by the packets made in one call
```

and the dispatching packet's journal gets a `dispatched` record listing them.
The dashboard shows it both ways (this keeps history navigable, the dashboard
being where results are read): the new packet's card says "from <packet>", the
dispatcher's page lists "Dispatched: a, b, c" with their states, and a batch
filter groups siblings. `wpk show . --dispatched` gives the same to the agent, so
the dispatching session can report "two done, one blocked" when asked.

### 5.3 The `wpk-dispatch` skill

A sixth skill in `skills.py`. Its steps:

1. Run `wpk context --board <board>` and `wpk repos --board <board>`. Resolve "this
   repo" (the caller's own origin), "my X fork" (registry alias), "this board"
   (`WPK_WPID`'s board). If any is ambiguous, ask.
2. Split the work and write one objective per packet, each self-contained for an
   agent that has not seen this session: goal, its slice, how to check it, what
   "done" means, and the branch it is on.
3. Run the batch with `--dry-run` and **show the user the plan** (names, boards,
   folders, branches, delivery) and get a yes. This is the guard: dispatch spends
   money and, with delivery on, pushes to a remote.
4. Run it with `--go --json`. Tell the user what was made, with the links.

### 5.4 "When complete, push"

The agent in the new packet should not be the one who pushes. Instead, the recipe
carries a delivery policy and the executor carries it out on COMPLETED, through
the existing guarded path:

```toml
# project.toml
[deliver]
on = "complete"      # when
do = "push"          # "push" | "draft-pr" | "pr" | "none"
```

- `pr.sync` (`pr.py:190`) generalises from "packets made by a watcher with `pr` on"
  to "any packet with `[deliver]`", and gains a `push`-only mode (push the branch,
  open nothing). Watchers then just write `[deliver]` into the packets they make.
- The existing refusals hold: own branch, not base, committed, commits ahead, no
  force. A failure shows on the packet ("Push failed: …") and is not retried by
  itself, as today for watchers.
- The step protocol gets a line: "Do not push; on completion wpk delivers the
  branch per `[deliver]`." Steps can still run `git push` (Bash is open); this
  is guidance plus a deterministic path, not enforcement. Enforcement — a
  PreToolUse hook refusing `git push` in steps — is cheap to add and worth having
  once `[deliver]` exists; it is listed as a follow-on (§9, D5).

Batch recipe key: `"deliver": "push"`. The skill sets it when the user says
"push" / "open a PR".

**When delivery happens — exactly, and visibly.** Delivery must never surprise
the user, so the rule is narrow and shown everywhere:

- **Trigger:** only the packet's transition to COMPLETED (the runner finished its
  last step and reported done). NEEDS_INPUT, FAILED, PAUSED, a stopped runner or a
  user-claimed packet never deliver. Reopening a completed packet and completing
  it again delivers again (pushing the new commits; a PR already open is updated
  by the push, not reopened).
- **Gate (optional):** `[deliver] gate = "make test"` runs in the packet's folder
  before the push; non-zero exit means no push, and the packet shows "Delivery
  held: gate failed" with the output's tail. The skill sets a gate when the user's
  words imply one ("once the tests pass, push").
- **Set only by name.** `[deliver]` is written only when the recipe asks for it
  (the user said push / PR) or a watcher has `pr` on. No global default turns it on.
- **Shown before and after.** The dry run lists "push `mb/uvm-tests-a` to
  `origin` on completion" per packet; the card and packet page carry a "Will push
  on completion" badge with **Push now** and **Cancel delivery** buttons
  (`wpk deliver <pkt> --now|--off`); the result ("Pushed 4 commits to … at
  14:32" or the refusal) goes in the journal and on the page.

### 5.5 Guards

- **Confirmation** (skill step 3). The skill always shows the dry run and waits.
- **Caps.** `[dispatch] max_batch = 8` (refuse bigger batches) and each made packet
  gets the normal budgets; the dry run shows the per-packet budget so the user
  sees what three runners may spend.
- **Who may dispatch.** Interactive sessions: yes. Runner steps: no by default —
  the protocol already forbids steps from creating packets, and a runaway step
  making packets is the failure to avoid. A project can allow it
  (`[permissions] dispatch = true`); then a step dispatch becomes a question to the
  owner (as requests do, `docs/delegation.md`) unless `dispatch = "auto"`.

## 6. Interactive dispatch: a VS Code packet

"Create a new VS Code packet on the Verilator board from my Verilator fork on a
new branch. Hand it this testcase to investigate."

### 6.1 Create

Same call, with a start mode instead of `--go`:

```sh
wpk start clone name=vl-issue-5123 board=verilator clone=@verilator \
     objective="Investigate ..." inputs=t_issue_5123.v \
     --open=ide-web --json
```

`--open=ide-web|ide-desktop` does what `/new start=ide-*` does today: the packet is
made held and claimed by the user (`actions.claim`), and the objective becomes
`prompt.md`. Web: the IDE server is registered (and may be pre-warmed with
`Backend.ensure` so the first load is quick). The JSON result carries `open_url`:
`https://<board>/ide/<key>/?folder=…` for web, or the `vscode://…` link for desktop
(`ide.py:446`).

### 6.2 The first instruction reaches Claude

wpk cannot type into a Claude session it did not start (`collaboration.md:514`).
So it starts one:

- `make` writes `.wpk/kickoff.md` (the objective plus inputs) in the packet.
- The packet's generated `.vscode/tasks.json` (it already has `wpk show/log/check`
  tasks, `ide.py:181`) gains a task with `"runOptions": {"runOn": "folderOpen"}`
  that runs `wpk kickoff`.
- `wpk kickoff` atomically takes `.wpk/kickoff.md` (rename to
  `.wpk/kickoff.done.md`) and, if it got it, `exec`s
  `claude "<kickoff text>"` (or `codex`, per the packet's harness) in that terminal.
  If the file is already gone it prints the packet summary and exits, so reopening
  the folder never starts a second session.
- VS Code runs folder-open tasks only with `task.allowAutomaticTasks = "on"` in a
  trusted workspace. For **web** VS Code wpk owns the server's data dir
  (`--server-data-dir $WPK_HOME/ide/data`), so it sets this in that profile's
  settings and marks packet folders trusted. For **desktop** VS Code it is the
  user's own setting: the first time, VS Code asks; the packet page says what to
  allow. Without it, the kickoff is still there: the SessionStart briefing says
  "There is a kickoff waiting: run `wpk kickoff`" and the first prompt the user
  types gets it as context.

Spike first (§9, I1): confirm `runOn: folderOpen` fires under `code serve-web`
with machine-level settings, that `claude` launched from a task terminal is
picked up by `ide_sessions` like a hand-started one, and what the Claude Code VS
Code extension offers instead (if it can be opened with a prompt, that is a nicer
target than a terminal).

### 6.3 Opening the tab

The browser usually runs on another machine than wpkd (laptop/iPad over the
tailnet), and browsers block tabs not opened by a click. So "open a tab" becomes
"put a one-click link where the user already is":

1. **In the calling session.** The skill prints `open_url` as a link. In VS Code's
   terminal or the Claude panel that is one click, and that is the main path.
2. **On the board.** The dispatch adds an attention item "vl-issue-5123 is ready —
   Open in VS Code" for its owner. An open board tab's existing poll
   (`notify.js`) shows it as a browser notification whose click opens the URL —
   a click, so no pop-up blocker.
3. **Phone.** If ntfy is set up, the same item goes there with the URL as its click
   action (off by default for this kind; on with `[notify] ready = true`).
4. **Desktop VS Code, same machine.** If the calling session has
   `VSCODE_IPC_HOOK_CLI` (it runs in a VS Code terminal), `wpk start --open=ide-desktop`
   can run `code --new-window <path>` (what `wpk ide --open` does today,
   `ide.py:460`), which opens a real window with no click. Over Remote-SSH that
   window opens on the user's machine. Worth confirming in the spike.

Zero-click opening of a *browser* tab needs something on the user's machine that
listens to wpkd: the VS Code extension (`docs/vscode-extension.md`, not built) or
the desktop app. Not in this plan.

### 6.4 A skill for it

The same `wpk-dispatch` skill, with a branch: if the user says "VS Code packet",
"open it", "I want to look at it", use `--open=ide-web` (or `ide-desktop` if
`[ide] desktop` is on and `web` is off), no `--go`, and finish by printing the
link. The dry run + yes still applies, but for a single interactive packet the
skill may fold it into one line ("Making vl-issue-5123 on verilator from
mballance/verilator@master, branch mb/vl-issue-5123 — go?").

## 7. Fit with what exists

- **Starters** stay the one engine; this adds a registry lookup (`clone=@name`), a
  batch entry, a folder resolver and three recipe keys (`deliver`, `open`,
  inline `inputs`). `/new` gets the resolver and the registry in its clone
  search for free.
- **Requests** (`delegation.md`) are packet-to-*project* work with owner approval
  and an answer coming back. Dispatch is session-to-*new packets*, approved in the
  session. They can share the lineage record (`origin.by`).
- **Watchers** become a dispatcher that runs on a timer; they pick up `[deliver]`
  and the folder resolver.
- **Packets not bound to git.** The `folder` starter works in batch too; `deliver`
  is refused at preview for a packet with no git origin.
- **Codex.** Skills are installed for Codex too; `wpk kickoff` runs `codex "<text>"`
  for a Codex packet.

## 8. Decisions (2026-11-11)

1. **Notes are Markdown files** (§4.1); the repo registry stays TOML.
2. **wpk delivers, not the agent** (§5.4), on the condition that *when* is
   unambiguous: only on COMPLETED, only if `[deliver]` was asked for by name,
   optionally gated by a command, and announced in the dry run and on the packet
   with Push now / Cancel.
3. **Skills are installed on packet creation by default** (`starters.make` and
   `project.new`, i.e. every creation path), as well as when the board opens VS
   Code. User-edited copies are still left alone. `[skills] install = false`
   turns it off.
4. **Folders stay where they are** when a packet moves to another board; the
   layout applies to new packets only.

## 9. Plan and status

Status as of 2026-11-11. `[x]` built and tested (`tests/test_agent_dispatch.py`
plus the existing suites), `[~]` partly built, `[ ]` not started.

**P0 — fixes found while investigating**
- [x] P0.1 `wpk-handoff` uses `wpk next . -f -` / `wpk handoff . --note-file -`
      (stdin heredocs). Test: every `wpk ...` command in every skill parses.
- [x] P0.2 `wpk start --go`, `wpk handoff`, `wpk resume`, `wpk next` wake wpkd:
      SIGUSR1 (`sched/home_lease.poke`). The server takes SIGUSR1 and says so in
      `server.json` (`"poke": "SIGUSR1"`); the CLI signals only a server that says
      so, on this host, whose pid runs wpk — an older wpkd, for which SIGUSR1 is
      fatal, is never sent it. After its loop the server ignores SIGUSR1, so an
      exec to restart is safe too. **Restart wpkd once** (`wpk serve --restart`)
      for the CLI to start waking it.
- [x] P0.3 Skills installed on packet creation (`project.install_skills`, from
      `project.new` and the IDE open), off with `[skills] install = false`.

**D — directories and notes**
- [x] D1 `[packets] root/layout`, board `dir`, `registry.packet_dir`; starters
      (`folder_of`), `/new` (an empty dir means the board's, when a directory is
      set), watchers (`dir` optional, on the form too), `requests.send` (the
      requester's board's directory, else beside it as before), the setup TUI;
      refusal to nest under `WPK_WPID`; `wpk board set <b> dir=…`, `wpk board
      show`; global Settings fields (`packets.root`, `packets.layout`,
      `skills.install`); "Packets and agent notes" on each board's page.
- [x] D2 `$WPK_HOME/agent.md`, `$WPK_HOME/boards/<b>.md`, `wpk context [--board]
      [--json]`; edited on Settings ("Notes for agents") and on the board's page.
- [x] D3 `[[repo]]` (global + board, board wins by name; aliases), `wpk repos`,
      `clone=@name` (url, ref, tool, share, `branch_prefix` + name), `/new` clone
      search lists them first.
- [x] D4 Board notes in full (≤ 40 lines) or a pointer, and a line for your
      notes, at SessionStart; "Your notes" / "Board notes" sections (4 KB cap
      each) above the project notes in the step prompt, plus a "Delivery" section
      telling the step not to push.
- [x] D5 A step of a packet with `[deliver]` gets `WPK_DELIVER`; the Bash
      PreToolUse hook (`bghook.py`) then refuses `git push` (also `git -C d push`,
      with env assignments or options before it) and says why. Claude only: Codex
      steps have no hooks; they get the prompt's "Delivery" section.

**B — batch dispatch**
- [x] B1 `wpk start --recipes FILE|-`: items are `{"starter", field values}` or
      recipes; inputs as files or `{name, text}` (also `inputs=a,b` on the
      command line); every recipe previewed first, duplicate names/folders
      refused, one refusal makes none; `--dry-run --json` gives recipes and
      previews; `--json` gives `[{name, wpid, folder, branch, board, url, state,
      deliver}]`.
- [x] B2 `[origin] by` (`packet:<wpid>` from a session; `user` in a batch) and
      `batch`; a `dispatched` journal record on the dispatching packet; the
      packet page says "made by <packet> (<batch>)"; the dispatcher's page lists
      "Dispatched: a, b (states, delivery)" with a link to the batch on its board
      (`/b/<board>?batch=…`, a filter); `wpk show <p> --dispatched`.
- [x] B3 `[deliver] do/gate/base`, `deliver.py`: due when the root is COMPLETED
      and HEAD has not been tried; the gate runs first; push refusals as `pr.py`'s
      (never the base, nothing uncommitted, commits ahead, no force); result in
      `[delivered]` and a `deliver` journal record; a failure is not retried until
      HEAD moves or Push now. A `wpk-deliver` thread in wpkd runs it (a gate may
      be a test suite). `wpk deliver <p> [--now|--off|--set MODE --gate CMD]`;
      the packet page shows "Will push on completion" / the last result, with
      **Push now** and **Cancel delivery**. `deliver=push gate=…` on the command
      line and in recipes; the dry run says "on completion: push <branch> to
      origin". A `draft-pr`/`pr` delivery needs a forge origin (refused at preview
      otherwise); a delivery needs a branch of its own (refused at preview).
- [x] B4 `wpk-dispatch` skill (both branches); `[dispatch] max_batch` (8);
      runner steps refused unless their project allows it (`wpk set <p>
      dispatch=true`, `[permissions] dispatch`; their prompt then says so) or
      `[dispatch] steps = true` for all.
- [x] B5 Real-model check (sonnet, `claude -p` with the skill as system prompt,
      a scratch home with `[[repo]] calc` and board `dv`): "split these 4 tests
      across two packets on the dv board from my calc fork… push when done" made
      two packets on `dv`, cloned from `@calc` on `mb/…` branches, `[deliver]
      push`, one batch. It also wrote "commit and push" into the objectives; the
      skill now says objectives say "commit on your branch", never "push". Not
      run: the packets themselves through the runner to a push.

**I — interactive dispatch**
- [ ] I1 Spike: does `runOn: folderOpen` fire under `code serve-web` with the
      machine setting? Not verified: needs a browser. Until it is, the
      SessionStart path below is what is known to work.
- [x] I2 `wpk start --open ide-web|ide-desktop`: claimed for you, held; web:
      registered with the board's VS Code (`/ide/<key>/?workspace=…`), desktop:
      `vscode://` (remote over SSH when the board knows the host), and `code
      --new-window` when the session runs in a VS Code terminal. `open_url` in
      `--json`.
- [x] I3 The objective (and a list of the inputs) is written to
      `<packet>/.work-packet/kickoff.md`. Two ways it reaches Claude, whichever
      comes first takes it (an atomic rename to `kickoff.done.md`):
      the **kickoff workspace** (`.work-packet/kickoff.code-workspace`, which the
      open link opens) has a folder-open task running `wpk kickoff <wpid>`, which
      execs `claude "<kickoff>"` (or `codex`); and the **SessionStart hook** gives
      the first Claude session in the packet the kickoff as "Your task in this
      packet". wpk sets `task.allowAutomaticTasks = "on"` in its web VS Code's
      machine settings unless you set it.
- [x] I4 A packet whose kickoff waits is a "ready for you: open it in VS Code"
      attention item (`/p/<p>?open=ide-web|ide-desktop`, which opens it); a
      browser notification always, an ntfy push with `[notify] ready = true`
      (Settings). It goes when a session takes the kickoff.
- [x] I5 Real-model check (sonnet): "a new VS Code packet on the dv board from my
      calc fork on a new branch; hand it this testcase" made the packet with the
      testcase as an input, the kickoff, and gave the `vscode://` link. Not
      tried: clicking it.

**Where the build differs from §1–§7**
- Skills are installed user-wide (`~/.claude/skills`, `~/.codex/skills`) by
  any `wpk start`/`wpk new`, as decision 3 says; the tests point them at a
  temporary folder (`WPK_SKILLS_DIRS`).
- The kickoff lives in the packet's `.work-packet/` (not `.wpk/`), and its task
  is in a workspace file there, not in the packet's `.vscode/tasks.json`: a
  clone's own `.vscode/` is left alone, and only the dispatch's first open runs
  the task (the board opens the plain folder after that).
- A project's `[permissions] dispatch` is true or false: there is no "ask the
  owner first" mode (§5.5).
- Watchers with `pr = draft|ready` write `[deliver] do = "draft-pr"|"pr"` into
  what they make, so delivery makes their PRs (retried when HEAD moves);
  `pr.sync` still serves packets they made before.
- `[origin] by/batch` is written for packets a session or a batch makes, not for
  each packet you make by hand.

**Found on the way, fixed:** `wpk ide` printed a web link without the server key
(`/ide/?folder=…`), which the board answered 404; it now registers the target
and prints `/ide/<key>/?…`.

**Next (needs the user):** I1 (open a kickoff link in serve-web and desktop VS
Code: does the task run, is the session seen by the board), and a batch run
through the runner to the push.
