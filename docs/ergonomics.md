# Working with packets: making it easy (proposal, 2026-10-26)

Status: a proposal for review. Nothing here is built. It follows
`docs/positioning-survey.md` §7 (cheap ways in) and `docs/packet-format.md`
(levels, packets that work without a daemon).

## 1. What is hard today

The CLI was built from the executor outwards, so it exposes the
executor's model:

1. **Two nouns where people think of one.** You `wpk new` a *project*,
   but the work happens in its *root packet*, and children are packets
   too. People think "a task".
2. **UUID paths.** Real work lands in
   `~/dvs-enh/packets/57ecad2a-d4e2-4f03-8fc3-1b629424afc7/work/dv-solve`
   (`docs/setup.md`). You can't type it, tab-complete it or remember it.
   Commands take a WPID or a project name, never "here".
3. **Ceremony up front.** Getting to the point where an agent works
   takes several commands: `new` → `setup`/`doctor` → `add-input` →
   `add-smoke` → `instruct` → hand off. The repo you were standing in
   when you decided to start is not used automatically.
4. **Two copies of the code.** The project's `work/<repo>` is "your
   clone" and the packet's `work/<repo>` is "the packet's worktree"
   (`ide.resolve`). Which one to edit is a question the user should never
   have to ask.
5. **No interactive verb.** You can run steps unattended, inspect them
   and open VS Code. But "sit down with an agent in this packet" has no
   command. That is the most common thing people will want, and what
   people new to packets would try first (`docs/packet-format.md` §3,
   Level 0).
6. **Ownership is a chore.** You must remember to hand off and take
   back. A wrong guess gives a read-only window or a refused command.
7. **About 30 commands, with executor jargon** (`tick`, `step`,
   `recover`, `memento`, `instruct`, `next`).

## 2. Targets

- **Start:** from "I have a task" to an agent working in the right place
  in **one command, under 30 seconds**, with no setup questions when
  you're standing in a repo.
- **Resume:** **one command** from anywhere, and the agent knows where it
  was.
- **Look:** **one command or one click** to VS Code on the right view.
- **Hand over:** to the runner, to a colleague or to a vendor in **one
  verb**, with no state machine to understand.
- **Same verbs everywhere:** the CLI, the board and the VS Code extension
  offer the same actions under the same names. The board adds reach, not
  new concepts.

## 3. The model people see

**One noun: a packet is a task.**
- A project becomes an optional grouping; the root packet *is* the
  task.
- Children appear as sub-tasks under it.
- "Project" survives in the format as a thin container
  (`docs/packet-format.md` §2), but no everyday command needs it.

**Names, not ids.**
- Packets get a slug (`uart-overrun`). A packet made from a directory
  lives in it, at `<dir>/.packet/` (§10). Others live at a readable path,
  `~/packets/uart-overrun/`.
- The WPID stays the identity and goes in `PACKET.md` and the address.
- Children are `uart-overrun/sub/<name>`.

**"Here" is the default target, as in git.** Every command resolves its
target in this order:
1. an explicit name, or an id prefix;
2. the packet containing `cwd`: walk up for `.packet/` (in place), or
   for `PACKET.md` (standalone).

So inside a packet, `wpk status` needs no argument.

**One copy of the code you edit.**
- In place (the default): your directory *is* the packet's work, and you
  and the agent take turns in it (§10).
- Split off or standalone: the packet's worktree, outside your checkout,
  is the only copy anyone edits for that task.
- The project-level `work/` disappears from what users see.

**Ownership follows what you do.**
- Running a packet hands it to the runner.
- Opening it, or starting an agent in it, takes it back, waiting for the
  end of the current step if one is running and saying so.
- The states stay in the format; users never type `take` or `handoff`
  unless they want to.

## 4. The verbs

Ten everyday commands. Everything else moves under `wpk admin …` or
stays for scripts.

| Verb | Does | Replaces today |
|---|---|---|
| `wpk new [name] [-m "task"] [--from <src>]` | Create a packet and print its path. In the current directory by default: `.packet/` in place, recipe recorded from the repos found (§10). `--from` takes a repo URL, a branch, an issue URL or a CI bundle. No `-m`: opens `$EDITOR` on the brief | `new`, `setup`, `add-input`, `instruct`, most of `doctor` |
| `wpk work [name]` | **New.** An interactive agent in the packet, with the hooks installed (§5). Resumes where the last shift ended | none |
| `wpk open [name] [repo] [--shell \| --web]` | VS Code on the packet's view (today's `wpk ide`), rebuilding the workspace first if needed. `--shell` for a shell in the packet | `ide`, `shell`, `path` |
| `wpk run [name] [-m "next"]` | Give it to the runner, with an optional instruction or note. Checks run here, not at creation: instruction present, repos on a branch, smoke check passes if there is one | `handoff`, `next`, `resume` |
| `wpk status [name]` | Like `git status`: state, owner, last shift summary, what's next, open questions, jobs, cost so far. No argument outside a packet: every active packet (today's `ps`) | `show`, `ps` |
| `wpk ask` / `wpk answer [name]` | See and answer open questions; answering runs it again | `answer` |
| `wpk note [name] "…"` | A note to the packet, running or not | `note` |
| `wpk done [name]` | Mark finished: clean the derived tier (with a prompt for what is kept), commit the worktrees, ask whether to archive | none (`clean` was designed) |
| `wpk send [name] <person \| file \| repo>` | Assign to a person, export to a file, or file a report against a repo's intake, choosing the export profile by destination | `export`, `assign`, `report` (designed) |
| `wpk get <file \| address \| url>` | Import and rebuild; arrives held and safe (§6 of the format) | `import` (designed) |

Shell niceties that cost little and matter a lot:
- tab completion of packet names;
- `wpk cd <name>`, via a shell function, as `zoxide` and `nvm` do;
- `wpk prompt`, a short `[uart-overrun · yours · step 12]` for `PS1`,
  as git's prompt does.

## 5. Without a front-end: `wpk work` is the product

For most people their first, and often only, experience will be a
terminal and VS Code. `wpk work` must make the method invisible:

1. **Start or resume.** Launch the harness (Claude Code first) in the
   packet with three hooks (`docs/packet-format.md`, "shift-end"):
   - **SessionStart:** put the brief, the memento, the last shift's
     summary and any notes into context. You never type "read the plan
     first".
   - **PostToolUse:** today's `ctxhook.py`. At the context limit it says
     "good point to end the shift". This is how interactive work gets the
     fresh-context savings without a runner.
   - **PreCompact / SessionEnd:** write the shift-end through the CLI:
     memento, summary, a journal record with each repo's HEAD, and the
     cost of the session. The model never writes JSONL.
2. **End of a shift is implicit.** Quit, `/clear` or hit the nudge, and
   the turnover is written. `wpk work` again picks it up in fresh
   context. The step boundary becomes something users *feel* as "the
   agent remembers where it was", not something they manage.
3. **Hand to the runner from inside.** A `/run` command (or `wpk run` in
   another terminal) ends the shift and hands off in one move. The same
   packet carries on unattended if a daemon is running, or at the next
   `wpk work` if not.
4. **It works for other harnesses later.** The hooks are the adapter.
   Harnesses without hooks get the brief through the prompt and a
   wrapper that writes the shift-end when the process exits.

`wpk work` replaces the hand-kept "plan and status file so a fresh
session can pick up" habit (the user's own CLAUDE.md does exactly this)
with something the tool keeps.

## 6. With a front-end: the same verbs, more reach

**The board.**
- **New from…** takes whatever you paste: a repo URL, a branch, an issue
  URL, a CI bundle or run link, or plain text. It runs `wpk new --from`.
- Each card offers the same verbs: **Work** (a web shell running
  `wpk work`), **Open** (VS Code: desktop over Remote-SSH, or the browser
  IDE), **Run**, **Answer**, **Done**, **Send**.
- The ownership states disappear from the buttons: "Open" on a running
  packet says "taking it at the end of step 13" and does it.
- On a phone, the useful verbs are **Answer**, **Note** and **Run**. The
  rest can wait for a laptop.

**The VS Code extension** reads the packet files, with the daemon
optional (see the discussion of using packets without the daemon):
- **Packets: New from this branch.** Creates a packet from the open repo
  and reopens the window on the packet's view. This is the IDE's front
  door.
- A **status bar** item: `uart-overrun · yours · step 12 · $1.84`.
- Commands for the same verbs: **Work** (a terminal running
  `wpk work`), **Run**, **Note**, **Review since hand-off**,
  **Open at step N**.
- A **Packets view** from the local index. With a daemon it adds live
  jobs, Needs you, and packets on other hosts.

## 7. What changes underneath

| Change | Where | Size |
|---|---|---|
| Slugs and readable packet paths; WPID kept in `PACKET.md` | format, `packet.py`, `registry.py` | medium; needs a migration for existing projects |
| Target resolution: name, id prefix, `cwd`, `.packet` pointer | new `resolve.py`, used by every command | small |
| Project optional; a single packet is valid; the recipe lives in the packet | format Q1; `project.py`, `setup.py` | medium |
| Packet worktree is the only one users edit; the project-level `work/` becomes internal (a cache of clones) | `workspace.py`, `ide.py` | medium |
| Ownership moves implied by verbs | `actions.py` (take on open or work; hand off on run) | small; the states exist |
| `wpk work` and the hook set; shift-end through the CLI | new; reuses `ctxhook.py`, the harness adapter | medium |
| Verb set; the old commands become aliases under `wpk admin` | `cli.py` | small but wide |
| `.packet` pointer and `~/packets/index` | new | small |
| Extension reads files first | `docs/product.md` §10.3 | design change; not built yet |

## 8. Open questions

| # | Question | Default assumed |
|---|---|---|
| E1 | Default home for packets | In place, `<dir>/.packet/` (§10); `~/packets/<slug>/` for packets not made from a directory |
| E2 | Is the packet directory itself a git repo? | Yes (§10): it survives `git clean -fdx` and serves as the journal without a runner |
| E3 | Should `wpk work` launch in the terminal you're in, or always in a persistent session (tmux or wpkd's session holder) so it survives closing the terminal? | Your terminal without a daemon; a persistent session with one |
| E4 | One CLI name (`wpk`) for both the daemonless format tool and the full product? | Yes. One package, with the daemon in an extra (`work-packet[dash]`) |
| E5 | Keep the old commands working? | As aliases for one minor release, then under `wpk admin` |

## 9. A first slice to test the idea

Build the smallest thing that lets us feel the difference, and use it on
the next real interactive task before building more:

1. `wpk new` from `cwd` with a slug path, and target resolution from
   `cwd`.
2. `wpk work`: launch Claude Code with SessionStart, `ctxhook` and
   SessionEnd hooks, with the shift-end written by the CLI.
3. `wpk status` like `git status`.
4. `wpk open` as an alias for today's `wpk ide`, with the target taken
   from `cwd`.

If after a week the packet feels like *less* work than keeping a plan
file by hand, carry on with `run`, `done`, `send` and the board and
extension verbs. If it doesn't, the friction is in the model, not the
commands, and §3 needs another look.

## 10. Packets made in place (2026-10-26)

**Goal:** make a packet from any directory you're already working in,
for example a clone you've been hacking on for an hour, with the packet
structure inside it. Measured with git 2.43 in a scratch repo.

### Layout

```
~/work/dv-solve/              your directory: the packet's work, in place
  .packet/                    the packet (a git repo of its own, see below)
    PACKET.md  memento.md  state/  journal.jsonl  steps/  recipe.toml
  src/ …                      your files, untouched
```

- `wpk new` here creates `.packet/` and adds it to `.git/info/exclude`.
  The repo's tracked files, including `.gitignore`, don't change.
- `work/` is implicit: the directory that contains `.packet/`. The
  recipe records each repo found there: remote, HEAD, unpushed commits,
  and uncommitted changes at export.
- Discovery is git's: walk up from `cwd` for `.packet/`.
- The standalone layout (`<packet>/work/<repo>`) stays as the second
  form of the same format, for packets made from a URL, an issue or an
  import.

### Measured: why worktrees must not go inside the checkout

- `git worktree add .packet/work/x` works, and once `.packet/` is
  excluded, `git status` is clean. But:
  - `grep -r` and build or test globs see a second copy of every file;
  - `rg` does not, because it honours the exclude.
- A worktree inside `.git/` (`.git/wpk/<slug>`) also works: status and
  `rev-parse` are correct, and almost every tool skips `.git`. It is
  unconventional, and IDE behaviour there is not checked.
- **`git clean -fdx`**, the usual "clean build", **deletes `.packet/`'s
  files**. It skips only nested repositories, so a worktree under it
  survives but the state does not.
- **If `.packet/` is itself a git repo, `git clean -fdx` skips it.**
  Only `-ffdx` removes it.
- A symlink `.packet -> ~/packets/<slug>` survives even `-ffdx`: clean
  removes the link, not the target.

### Proposal

1. **The first packet on a directory needs no worktree.** You and the
   agent take turns in the same tree. That is what people expect.
2. **`.packet/` is a git repo by default.** That protects it from
   `clean -fdx` and gives a journal without a runner (E2, now
   answered yes). Shift-ends and steps are commits.
3. **Recovery.** The index (`~/packets/index`) records where each
   packet is. `wpk status` warns when one has gone. `--home` stores the
   packet in `~/packets/<slug>/` with a `.packet` symlink, for people who
   run `-ffdx` or re-clone often.
4. **A second packet on the same clone, or "keep working while the
   runner runs", splits off a worktree *outside* the checkout**, as a
   sibling (`../dv-solve.wpk/<slug>/`) or under `~/packets/<slug>/work/`.
   Never under the checkout. A worktree in `.git/` is the fallback if
   siblings turn out to be unwelcome.
5. **Rollback in place must not `git clean -fd`.** Your directory holds
   your own untracked files. Record the untracked set before a step and
   remove only what the step created. Reset tracked files as now.
6. **Branch.** In-place packets stay on your current branch and record
   the base commit; `wpk done` offers to squash. On the default branch,
   `wpk new` offers `wpk/<slug>` first.
7. **While the runner owns an in-place packet, the directory is the
   runner's.** The guard makes VS Code read-only, as it does now. That
   is the cost of in place; `wpk run --split` avoids it by moving the
   work to a worktree first.
