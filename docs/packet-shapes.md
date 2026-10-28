# Packet shapes: the record, the workspace and the runtime (brainstorm, 2026-10-26)

Status: a review of the current packet definition and a proposal for
discussion. Nothing here is built. It builds on `docs/packet-format.md`
(draft 0), `docs/ergonomics.md` and `docs/long-running.md`, and suggests
changes to all three.

Revised the same day. **Git is not required.** A packet may be a
research or scratch task whose files never go into a git repo unless
the user decides to put them there. Git is one kind of workspace, not
the base the format is built on.

Revised again: git is fine as **internal plumbing** (Q8, decided), and
**committed steps land their results in the source**, not in the packet's
step folders (§5.2). For a git repo, your checkout, not the step
worktree, always holds the last committed step. Remote runners reach a
packet through a shared filesystem, or later by download and upload, and
parallel children land in their own result refs, which the parent
integrates (§5.3, §5.4).

The question: a packet can start in several ways:
- as my existing working directory (often, but not always, a clone);
- as a task made on the board or in a terminal, from a repo or from
  nothing (for example "research topic X");
- as a failing test that needs only a summary and a way to reproduce it.

Can one set of metadata cover all of these, while asking the user to
learn and do almost nothing?

## 1. Review: what the current designs get wrong

**Containment.** Each design so far answers "where is the packet?" by
putting one thing inside another, and each picks a different direction:

| Document | Relationship | Consequence |
|---|---|---|
| `long-running.md` §2 | the repo is cloned **inside** the packet (`packets/<WPID>/work/<repo>`) | your existing directory can't be the packet; UUID paths; a second copy of the code |
| `setup.md` §10 | the setup lives at the **project** root, packets under it | two nouns (project, packet); the recipe isn't in the packet |
| `ergonomics.md` §10, `packet-format.md` §2.1 | the packet is **inside** the repo (`<dir>/.packet/`), or standalone with `work/` | two forms, a split operation between them, `git clean` hazards, exclude-file edits |

This makes the packet's identity depend on where its files are. Each new
way to start then needs its own layout, plus conversions between layouts
(split, materialize, tombstones). The user has to learn which layout
they are in.

**Git assumed throughout.**
- `work/` is defined as "a folder of repositories", and anything else in
  it is a warning (`long-running.md` §2).
- Steps are made atomic with `git reset --hard` and `git clean`.
- Hand-off requires every work repo to be on a branch with a clean
  tree.
- The in-place recipe is "each git repository found".
- `packet-format.md` §2.4 makes the packet directory itself a git repo
  "at every level".

A research packet that is a folder of notes, downloaded papers and
scripts has no place in any of this.

**Too many concepts reach the user.** Counting the current documents:
- levels (0–3), forms (in place, standalone), tiers (core, record,
  derived);
- states (6), `held_for` reasons (5), export profiles (3);
- project vs packet, `work/` rules, and ownership.

Each one is reasonable on its own, but together they are a lot for
someone who wants to "keep track of this task".

**Runtime configuration is stored as packet data.** `project.toml` holds
`step_env`, budgets, permission profiles and limits next to the recipe.
These are facts about **where and how** the work runs on one host, not
about **what** the work is. They should not travel in a bundle or go to
a colleague.

## 2. The reframe: three things, not one

Separate them the way OCI separates the image spec from the runtime
spec:

| | **Packet** (the record) | **Workspace** | **Runtime** (binding) |
|---|---|---|---|
| What | what the work is, where it stands, how to get its workspace back | the files the work is done in: a plain folder, one or more repos, a mix, or nothing | who or what is working on it right now, on which host, with which environment and limits |
| Size | kilobytes | anything | a few lines |
| Travels? | **always** | **what can't be rebuilt** (§3 rule 1) | never; each host makes its own |
| Examples | brief, memento, history, sources (repos at commits, archives, shared paths), repro command, artifact links | `~/notes/rv-cache-research/`, `~/work/fw-uart16550`, a dir the runner cloned into | "you, interactively, in `~/work/fw-uart16550`"; "the runner on `build3`, `direnv exec`, $5/day"; "nobody: dehydrated" |

The packet **refers to** a workspace. It does not contain it, and it is
not contained by it. The runtime **binds** a packet to a workspace on a
host, for an owner.

### Workspace kinds

| Kind | Example | How it is captured to travel | How a step is undone |
|---|---|---|---|
| **None** | a failing test not yet looked at; a question to answer | nothing to capture | nothing to undo |
| **Plain folder** | research notes, a design sketch, downloaded papers | its files travel (minus an ignore list for bulky derived files) | a shadow repo in the store (§5.1) |
| **Git repos** | your clone of fw-uart16550 | repo URL + commit; unpushed work as a patch | `git reset` as now |
| **Mixed** | a folder with a clone in it and notes beside it | per part, as above | per part, as above |
| **Shared path** | a sim run directory on a project file server | the path, valid only on hosts that see it | not undone; steps there are marked unsafe to retry |

The kind is **detected**, not declared: the tools look at what is there.
A plain folder becomes a git workspace the moment you `git init` it, or
clone into it, and nothing else changes.

### Shapes

With this split, the user's starting points are not different formats.
They are one record with different workspace bindings:

| Shape | Workspace | Runtime | Started by |
|---|---|---|---|
| **Attached**: my directory is the packet | a directory you already have, git or not | you | `wpk work` in it |
| **Hosted**: made on the board from a repo | a directory the runner cloned into, which it manages | the runner, or you through Open | board **New from repo** |
| **Scratch**: made from nothing, on the board or in a terminal | a plain empty folder, in the store (§4) | either | board **New**, or `wpk new "research X"` |
| **Dehydrated**: a failing test | none; the record says how to build one | nobody yet | CI, or `wpk send` of any packet |

Moving between shapes is a change of binding. The record stays the same.

```
                 hydrate (fetch sources, unpack files, run setup)
   Dehydrated ───────────────────────────────────────────► Attached / Hosted / Scratch
       ▲                                                        │
       └───── dehydrate (capture sources, keep files that ◄─────┘
                         can't be rebuilt, drop the rest)

   Attached ◄──── hand over / take back (rebind the runtime) ────► Hosted
```

Today's split, materialize, clean, export and import operations all
become one of these two moves.

## 3. One record

One file is required: `PACKET.md`. Everything else is created by the
tools when it is first needed. Front matter holds the facts that travel,
and the body is the brief.

A scratch research packet:

```markdown
---
packet: 1
id: 9a3e…                       # generated; users never type it
title: Survey of RISC-V cache coherence verification approaches
---
Find what's published on formal vs simulation approaches for RISC-V
coherence, 2022 onwards. Output: a short comparison table and reading list.
```

A failing test:

```markdown
---
packet: 1
id: 6f1c…
title: UART overrun flag not cleared
sources:                        # how to get the workspace back; captured, rarely typed
  - repo: https://github.com/featherweight-ip/fw-uart16550
    commit: 3f0c9a2
  - archive: https://ci.example/run/8812/inputs.tar.gz
setup: ivpm update              # optional: delegate to the project's own tooling
repro: dfm run uart.test_overrun  # optional: the one command that shows the problem
artifacts:                      # optional: links, not copies
  - https://ci.example/run/8812/waves.fst
---
test_overrun fails at 41/67: the RX overrun flag stays set after LSR is read.
Seen on main at 3f0c9a2. Expected: the flag clears on the LSR read (spec §8.4).
```

Rules that keep this cheap:

1. **Travel what can't be rebuilt.**
   - A repo at a pushed commit travels as a reference.
   - A plain folder's files travel as files: they *are* the work.
   - Bulky derived files (build output, waves, caches) are dropped,
     using a default ignore list the user can extend.
   - Anything over a size threshold is shown before it is sent.
2. **Sources are captured, not written.** `sources:` is filled in from
   what is in the workspace when the record has to travel or be rebuilt:
   at hand-over to another host, `send` and dehydrate. It is not filled
   in at creation. A packet that never leaves your machine never needs
   an accurate `sources:`. A plain folder needs no `sources:` entry; its
   files go with the record.
3. **Setup delegates.** `setup:` and `repro:` are one command each, in
   the project's own tooling (ivpm, dfm, make). We don't invent a setup
   language.
4. **Absent means default.**
   - No `sources:` means a scratch workspace, or none.
   - No `repro:` means none.
   - No memento means "read the brief".
   - A packet with only a title is valid.
5. **The user never keeps the books.** Shift-end hooks write the memento
   and the history. How the history is stored is the tools' business
   (§4.1). The format must not need git to read it.
6. **Runtime data stays local.** These go in a **binding** file on the
   host (§5) and never in `PACKET.md`:
   - paths, owner, leases;
   - budgets, the permission profile, `step_env`;
   - session ids, costs in progress.

The levels in `packet-format.md` §3 still apply, but as a guide for
implementers. A user never needs to know them.

## 4. Where the record lives

The user wants "my directory is my packet". That is a statement about
the **workspace**, not about where the record's files are stored.

**Recommendation: a store, plus a pointer where needed.**

- **Record:** a store, by default `~/packets/<slug>/`, holding
  `PACKET.md`, the memento, notes and history.
- **Scratch workspace:** `~/packets/<slug>/files/`, a plain folder. A
  scratch packet is entirely in the store, so it needs no pointer.
  Discovery walks up from `cwd` and finds `PACKET.md`.
- **Attached workspace:** a pointer to the record in the directory you
  work in. Pick the least visible place that works:
  - a **plain directory** gets a one-line `.packet` file (the id), the
    only trace in your files;
  - a **git repo** gets the pointer in its git dir (`$GIT_DIR/packet`)
    instead. No tool sees it, `git clean` can't remove it, and nothing
    goes in `.git/info/exclude`. Each git worktree has its own git dir,
    so each can point at a different packet.
- **Hosted workspace:** the runner keeps it wherever it likes (today
  `work/` under its home). The binding records the path, so no pointer
  is needed.

Why a store and not `<dir>/.packet/`:
- your directory gains one small file at most, or nothing in a repo;
- the board finds every packet in one place;
- deleting or re-cloning the directory loses nothing that matters:
  the record has the brief, the history and the sources;
- scratch packets need no directory of your own at all.

Options considered and set aside:
- the record in `<dir>/.packet/` (the current proposal), which is
  exposed to `git clean`, grep and globs;
- the record in `.git/packet/`, which works only for git;
- the record as git refs (`refs/packets/<slug>`), which works only for
  git. It is worth keeping as a *transport* later: a way to hand a
  packet over through a project's own remote with no server.

### 4.1 History without making the user's work a repo

`packet-format.md` §2.4 decided the packet directory is a git repo, with
a commit per shift-end. Three ways to square that with "my content is
not in git":

| | History kept as | User-visible git? | Plain-folder workspace versioned? |
|---|---|---|---|
| A | `journal.jsonl` plus a snapshot of the record files per shift-end, under `history/` | none | yes, if the snapshot includes `files/` (small folders only) |
| B | a git repo in the store, private to the tools, tracking the record files only; never in the workspace | none in your workspace; one hidden repo in the store | no |
| C | as B, and also tracking `files/` for scratch packets | as B | yes, at no cost to the user |

**Suggested default: C.**
- The store's repo is plumbing, like the runner's index. You never run
  git against it, and it never appears in your directories.
- A scratch research packet gets undo and history of its files without
  being "in a repo" in any sense you have to manage.
- The **format** stays git-free: a reader needs only `PACKET.md`, the
  memento and the journal, so another tool can implement A instead.

**Decided (Q8): C.** Git as internal plumbing is fine. The same idea
gives plain-folder workspaces their rollback and history (§5.1).

## 5. The runtime binding

A **binding** is a small local file, `~/packets/<slug>/.bind.toml`. It
is in the store but never exported.

```toml
host = "laptop"
workspace = "/home/matt/work/fw-uart16550"   # or "files" for scratch, "managed" for runner-cloned
owner = "me"                                  # or "runner"
env = "direnv"                                # how to enter the environment; "none" by default
profile = "default"                           # permissions, budgets: names, defined per host
```

Some consequences:
- **Handing to the board is registering a binding, not moving files.**
  On the same host, the runner can work in your directory in place:
  the directory is locked while it owns it, as now. With `--split` (git
  only) it steps in a scratch worktree so you can keep editing, and
  still lands every committed step in your checkout (§5.2).
- **On another host**, the runner reaches the packet over a shared
  filesystem, or (later) downloads it and uploads the result (§5.3).
  Either way it gets its own binding. Same packet, several bindings over
  its life, one owner at a time.
- **Budgets, profiles and environment** are host settings selected by
  name. A received packet never brings its own permissions, which
  enforces the "data, not instructions" rule by construction.
- **Sessions** (the idle-shell idea in `bigger_picture.md`) attach to
  the binding, not the packet.

### 5.1 Steps in workspaces without git

The runner's step protocol rolls a failed step back. For git repos it
does that with `git reset`, as now. Now that git is accepted as internal
plumbing (Q8), plain folders can use the same mechanism, without becoming
repos:

- **Plain folder under a size limit** (say 100 MB, not counting ignored
  derived files): a **shadow repo** in the store,
  `git --git-dir=~/packets/<slug>/shadow.git --work-tree=<workspace>`.
  - It snapshots the workspace before each step and commits it after.
  - It resets on failure, removing only the files the step created
    (`packet-format.md` §4).
  - The folder gets no `.git` and never looks like a repo, to you or to
    any tool.
  - It also gives the plain folder a per-step history and diffs for
    free.
- **Larger plain folder, or a shared path:** no rollback. The step is
  marked non-atomic, a failure goes to **Needs you** rather than being
  retried, and the summary lists the files the step changed.
- **Interactive shifts** (`wpk work`) are never rolled back, in any kind
  of workspace, as `packet-format.md` §4 already says. The shadow repo
  still records a commit at each shift-end.

### 5.2 Where results land

**Today.** A step's outputs end up in three places:

| Output | Lands in | Problem |
|---|---|---|
| code and tests | `work/<repo>`, committed per step | fine: this is already the source |
| documents, reports, notes, tables | `state/` through `.pending/state/` (the packet's own files) | a research packet's deliverable is buried in the packet's internals, mixed with its plan and notes |
| what was done, in prose | `steps/NNNN/summary.md` of the step that did it | the answer to "what did it find?" sits in whichever step happened to finish |

**Proposal: a committed step lands its results in the source.** The
**source** is the workspace the packet is bound to, whatever its kind:
your directory, the scratch `files/` folder, or the managed clone. The
packet keeps the *record* of the work. The source gets the *work*.

| What | Where | Rule of thumb for the agent |
|---|---|---|
| **Results**: code, tests, reports, tables, figures, the answer | the source | would the owner want it after the packet is gone? |
| **Process**: the outline, `env.md`, working notes, questions | the record, `state/` | it is about doing the work, not the work |
| **Provenance**: summary, transcript, cost, and a diff of what landed | `steps/NNNN/` | written by the executor, never by the model |

So a research packet ends with `files/report.md` (or `report.md` in your
own directory), not with the answer inside `steps/0007/summary.md`.
`wpk status` and the board link to the results in the source, not to
the step folder.

**The invariant: the source always holds the last committed step.**
When the source is a git repo, *your repo*, meaning your checked-out
branch and your working tree, has every committed step as soon as that
step commits.
- Any worktree or clone the runner steps in is scratch. It never holds
  the only copy of committed work, and you never have to go and look in
  it.
- A step is not committed until it has landed in the source.

This replaces today's arrangement:
- `work/<repo>` is a worktree of your clone on `wpk/<project>`;
- its commits sit in your repo's object store, but your checkout never
  shows them.

**How a step lands, by where it ran.**

| Where the step ran | Landing (the last action of the step commit) | Your repo afterwards |
|---|---|---|
| **In your repo** (in place, the default; the runner owns the directory while it runs) | the step's commit is made on your checked-out branch | branch and tree at the step's commit, at once |
| **In a step worktree** (`--split`, so you can keep editing) | the worktree starts **detached** at your `HEAD`, and its step commit is a child of it. Landing is `git merge --ff-only` of that commit in your checkout. If you have committed in the meantime, the step commit is first rebased onto your new `HEAD` in the worktree. Your uncommitted edits stay as they are; git refuses only if the step touches the same files | branch and tree at the step's commit. On a conflict the step is not committed: the packet waits with a question ("step 12 touches `uart.sv`, which you are editing"), and the step is retried or rebased when you answer |
| **On another host** | through a shared filesystem, as on your own host; or, later, by upload, where your host's wpk does the landing (§5.3) | as above. The packet never runs ahead of your repo |
| **Scratch** | committed in `files/` (shadow repo) | n/a |
| **Plain folder of your own** | in place only: the step's changes are made in your folder and committed to the shadow repo. There is no split for plain folders in the first version | the folder holds the step's result at once |
| **Hosted from a repo** (the runner cloned it from a URL) | the managed clone *is* the source; steps commit on its checked-out branch | pushed upstream only when you say so: **Done** offers to push the branch or open a PR. Steps never push (`long-running.md` §8) |

Consequences:
- **The packet needs no `wpk/<slug>` branch of its own.** It works on
  whatever branch your checkout is on when it starts, and records that
  branch in the binding.
  - On the default branch, `wpk new` offers to make a branch first
    (`packet-format.md` Q11).
  - If you switch branches while the runner holds the packet, the next
    landing stops and asks.
- **Two packets on one repo** each need their own checkout (a worktree
  you make and own, with its own pointer, §4). Each lands in its own
  checkout. The step worktree is never somewhere you work.
- **Taking the packet back is instant.** There is nothing to merge,
  because your repo is already current.

**What changes in the protocol.**
- **The model writes results to the source and process to `state/`.**
  For a git repo this is today's rule. For a plain folder it replaces
  "everything goes through `.pending/state/`".
- **The record keeps its staging.** `.pending/state/` stays as it is,
  for the packet's own files, because those are small.
- **The step commit gains one action:** commit the source (the git
  repos, or the shadow repo), and write `steps/NNNN/work.diff` from that
  commit. Rollback is the reverse.
- **`steps/NNNN/` holds no deliverables.** It holds the record of what
  landed.

### 5.3 Remote runners

Two ways for a runner on another host to reach a packet. Both keep the
source on the owner's side as the authoritative state.

**Shared filesystem (first).** The packet store and the source are on a
filesystem that both hosts mount, such as NFS on a compute farm. The
remote runner works exactly as a local one: in place, or in a scratch
worktree beside the source, landing with the same fast-forward. What
has to hold:
- **Relative paths everywhere (decided, Q13).** Every path wpk writes
  is relative to the store or to the source, so the share can be
  mounted at different points on different hosts:
  - the binding;
  - the pointers (§4);
  - worktree links, using `worktree.useRelativePaths`.
  Relative worktree links need git 2.48 or later; we measured 2.43, so
  `wpk doctor` checks the version on each host. An older git falls back
  to the same mount path everywhere, with a warning.
- **Leases that work across hosts.** Don't rely on `flock` over NFS.
  The lease is a file holding the host, pid and an expiry that is
  renewed by heartbeat. It is taken with an exclusive create. A lease
  whose heartbeat has stopped can be broken after a grace period, and
  breaking one is journaled.
- **Git's own locks are enough** for the rest (`index.lock`, ref
  locks), because ownership already ensures that only one party writes
  to a checkout at a time.
- **Scratch on local disk where it is big.** Build and simulation
  output goes to the runner's local scratch through the ignore list and
  `setup:`, not onto the share.

**Download and upload (future).** The runner has no shared filesystem.
1. **Download:** the record, plus the source as a git bundle of the
   commits it needs. A plain folder comes as a tar of its shadow-repo
   commit.
2. **Work:** steps commit locally, in a clone that is scratch.
3. **Upload:** for each committed step, the record changes plus a git
   bundle of the step commit go to the owner side (the owner's host, or
   the server).
4. **Land:** the owner side imports the bundle into the source repo and
   fast-forwards the checkout, as for `--split`.

The step counts as committed only when the upload has landed. Until
then it sits in commit-begin, and is rolled forward when the connection
comes back. A runner that has lost its link may carry on in the
meantime only if `max_unlanded` (default 0) allows it. Otherwise it
waits, so the source is never more than that many steps behind.

### 5.4 Parallel sub-tasks: the parent integrates

Later, a packet will spawn several children that run at the same time.
They can't all land in your checkout. Instead, each packet has an
**authoritative state**, and the invariant applies per packet:

| Packet | Its authoritative state | Its committed steps land in |
|---|---|---|
| Root | the source: your checkout, `files/`, or the managed clone | the source, as in §5.2 |
| Child | its own **result ref**, `refs/packets/<root>/<child>`, in the root's repo (a shadow repo for a plain folder) | that ref, by the same commit-and-land; its scratch checkout is a worktree, detached at the ref |

Rules:
- **A child starts from its parent's authoritative state** at the commit
  where it was spawned. That commit is recorded in its `created` record.
- **Only the parent lands work in the parent's state.** A child never
  writes to its parent's source. Integration is the parent's act.
- **Integration is a parent step.**
  - **When the parent finishes (decided, Q15).** Integration happens
    when the parent reaches the end of the work it spawned children for.
    That is when its memento says `resume: done`, or when its
    `wait children` ends. It does not happen as each child completes.
    Until then each child's work stays in its result ref, where you can
    look at it but it doesn't touch the parent's state.
  - The executor then merges each completed child's result ref into the
    parent's state, one at a time.
  - A clean merge is a **mechanical step**: no model run. It is journaled
    as `integrate` with the child, its ref and the merge commit.
  - It is then subject to the same landing as any other step, so a root's
    integration lands in your checkout.
- **Conflicts are the parent's work, not the user's.**
  - A conflicting merge becomes a model step of the parent, with the
    conflict and both children's summaries in its prompt.
  - The parent may resolve the conflict, re-run a child with a new
    instruction, or drop one child's work.
  - Only if it can't resolve it does it ask you.
- **Order.** By default, children are integrated in the order they
  were spawned, so the result doesn't depend on timing. The parent can name an order (`integrate: [b, a]`) when one
  child builds on another.
- **A check after each integration.** The parent's `repro:` or smoke
  check runs on the merged state. A merge that is clean as text but
  fails the check counts as a conflict.
- **Refs, not branches.** Result refs live under `refs/packets/`, so
  they don't clutter `git branch`. They are kept until the parent
  completes, then pruned, with the journal keeping their commit ids.
  Because a worktree shares its repo's object store, a child's commits
  are already in your repo, and only the ref is new.
- **Plain folders work the same way** through the shadow repo: a child's
  scratch is a worktree of the shadow repo, and integration is a git
  merge there, applied to the folder.
- **Remote children** reach the root's repo through a shared
  filesystem, or upload their step bundles to the root's side, where
  they land in the child's result ref (§5.3).

Nested children follow the same pattern: each parent integrates its own
children into its own result ref, and the root integrates into the
source.

## 6. The starts, as the user sees them

A fuller walk-through of every use case, with screens, is in
`docs/packet-ux.md`.

**My directory (git or not).**
```
$ cd ~/work/fw-uart16550
$ wpk work
No packet here. What are you working on? > UART overrun flag not cleared
packet uart-overrun · yours · agent starting…
```
That is the whole setup:
- the slug comes from the answer, or from the directory or branch name;
- the pointer is written (`$GIT_DIR/packet` here, `.packet` in a plain
  folder);
- hooks write the shift-ends.

Hand-off is `wpk run` (or **Run** on the board). That writes the binding
with `owner = "runner"`, and the packet appears on the board. Sources
are captured only if the runner is on another host.

**Scratch, from the terminal or the board.**
```
$ wpk new "Survey of RISC-V cache coherence verification approaches"
packet riscv-coherence-survey · ~/packets/riscv-coherence-survey/files/
$ wpk work riscv-coherence-survey
```
On the board: **New**, then a one-line brief, then **Work**.
- No repo, no directory to choose, no setup.
- Notes, downloads and scripts accumulate in `files/`.
- If you later decide to keep the result in a repo, copy it there, or
  `git init` in `files/`. The packet notices the workspace kind changed
  and needs no other change.

**Board, from a repo.** Paste a URL or a URL@ref, then type one line of
brief. The runner clones into a managed workspace, runs `setup:` if
there is one, and the card offers **Work**, **Open** and **Run**. The
user never sees a path.

**Failing test.** A CI step (a few lines of shell or an action) writes
`PACKET.md` and nothing else:
- brief: the test name and a failure excerpt;
- `sources:`: repo@sha, or an archive of the inputs;
- `repro:`: the command;
- `artifacts:`: links to logs and waves.

It stays **dehydrated** until someone runs `wpk get <url>` or clicks
**Open** on the board. Hydrating fetches the sources, runs setup, and can
run `repro:` once to confirm. Most failures are triaged, and many are
closed, without ever being hydrated.

## 7. What the user must learn

| To | They learn | They don't need |
|---|---|---|
| Start something | `wpk work` in a directory, or `wpk new "…"` | layouts, workspace kinds, git |
| Keep an agent's place across sessions | `wpk work` | memento, journal, steps, levels |
| Let the runner carry on | `wpk run`, `wpk status` | ownership states, lease, binding |
| Take it back | `wpk work` or **Open** (both take it back) | `take`, `handoff` |
| Share or report | `wpk send`, `wpk get` | bundles, profiles, tiers |
| Finish | `wpk done` | clean, archive |

Maintenance comes down to three things, and the tools do all of them:
- sources are captured when the packet travels;
- the memento and history are written by the shift-end hooks;
- derived data is dropped by `done` and `send`.

The user's only ongoing job is to write the brief and answer questions.

## 8. What this changes in the existing designs

| Design | Change |
|---|---|
| `packet-format.md` §1 principles | Add: **no tool beyond a filesystem is required to read or write a packet.** Git is a workspace kind and a tool's choice of plumbing |
| `packet-format.md` §2.1 (two forms) | Replace with **record + workspace binding**. "In place" and "standalone" become attached and hosted bindings of the same record. Drop the split/tombstone operation |
| `packet-format.md` §2.2 (discovery) | Walk up for `PACKET.md` (store), `.packet` (plain folder) or `$GIT_DIR/packet` (git). The pointer resolves to the store |
| `packet-format.md` §2.3 | `recipe.toml` folds into `PACKET.md` front matter (`sources`, `setup`, `repro`, `artifacts`). `work/` leaves the format: where a managed workspace lives is the runtime's business. Add `files/` for scratch workspaces |
| `packet-format.md` §2.4 (packet dir is a git repo) | Demote from format rule to implementation choice (§4.1). The format's history is the journal; commit trailers are one way a tool may keep it |
| `packet-format.md` §6 (bundles) | A `report` bundle can be just a dehydrated `PACKET.md`. Bundles carry the record plus whatever of the workspace can't be rebuilt (§3 rule 1) |
| `long-running.md` §2 (`work/` is a folder of repos) | Becomes the git case of the hosted binding. Non-repo content in a workspace is normal, not a warning. Step rollback per workspace kind (§5.1) |
| `setup.md` `[setup]`, `project.toml` | The recipe moves to `PACKET.md`. `step_env`, limits and budgets become host profiles named by the binding. "Project" becomes an optional tag or board grouping |
| `workspace.py` (`work/<repo>` as a worktree on `wpk/<project>`) | The step worktree becomes detached scratch; landing in your checkout is part of the step commit (§5.2). The `wpk/<project>` branch goes |
| `docs/spec.md` §6 (children) | Children get a result ref and a scratch worktree; integration is a parent step, journaled as `integrate` (§5.4). Supersedes `long-running.md` §10's "a child that needs its own workspace" |
| `docs/spec.md` §4.5 (`.lease`) | A lease safe across hosts: host, pid and a heartbeat expiry, taken by exclusive create (§5.3) |
| `docs/spec.md` §4.4 and the protocol prompt (`prompts/protocol.md`) | Results go to the source; `state/` is for process only; `steps/NNNN/` gains `work.diff` for every workspace kind and holds no deliverables (§5.2) |
| `ergonomics.md` | The verbs carry over unchanged. §10's measured `git clean` problems are avoided rather than handled |

## 9. Open questions

| # | Question | Suggested default |
|---|---|---|
| Q1 | Store location: `~/packets/` or under the runner home `~/.work-packet/packets/`? | `~/packets/<slug>/`: readable, and the same with or without a runner. The runner keeps only its index |
| Q2 | Should `wpk work` in a directory with no packet create one without asking? | Ask for one line (the brief). An empty brief makes the packet a bookmark, titled after the directory or branch |
| Q3 | Does the in-place runner lock the user out, or always split? | Lock by default, as now. `--split` when you want to keep working. Revisit after use |
| Q4 | Does a failing-test packet carry the log excerpt inline? | Inline in the brief (a few KB); anything larger is a link |
| Q5 | `setup:` as one command, or a list? | One string. A list is a shell script in disguise; point at the project's script |
| Q6 | Packets in git refs as a server-free transport? | Later; prototype after `send`/`get` |
| Q7 | Attached workspace that is a folder of several repos plus loose files? | One `.packet` file at the top. The repos inside are detected and captured as sources; loose files travel as files |
| Q8 | Is a hidden git repo in the store acceptable as plumbing for history (§4.1 C), or must history avoid git entirely (§4.1 A)? **Decided: C.** Git as internal plumbing is fine; the format stays readable without it |
| Q9 | Size limit for a plain folder's shadow repo (§5.1)? | 100 MB, excluding ignored derived files; above it, steps there are non-atomic |
| Q10 | Does the outline (the plan) count as a result, landing in the source, or as process, staying in `state/`? | Process, in `state/`. `wpk open` shows it beside the source. An owner who wants the plan in the repo says so in the brief |
| Q11 | In split mode, may landing rebase the step onto commits you made meanwhile, or must it stop and ask? | Rebase when it applies cleanly and the step's check still passes; otherwise ask |
| Q12 | For a hosted packet, push after each step as an opt-in host profile setting? | Off by default; a profile may allow pushing the packet's branch (never the default branch) |
| Q13 | Shared filesystem: one mount path on every host, or relative worktrees (git 2.48+)? | **Decided: relative paths everywhere** (binding, pointers, worktrees); `wpk doctor` checks git ≥ 2.48 |
| Q14 | Upload mode: may a runner get ahead of the source when the link drops (`max_unlanded`)? | 0 by default: it waits. Raise it per host profile for long offline runs |
| Q15 | Integrate children as each completes, or all together at a parent-named point? | **Decided: when the parent finishes** (its `done`, or the end of its `wait children`), in spawn order, with a check after each merge |
| Q16 | May a child see a sibling's integrated work before it finishes (rebase onto the parent's newer state)? | **Decided: not at first.** A child sees its starting point only. Later: async messages between agents through mailboxes (the `mailbox/` in `packet-format.md` §2.3), carrying information, not merges |

## 10. A slice to test it

This replaces step 1 of `ergonomics.md` §9; steps 2–4 there are
unchanged.

1. The store at `~/packets/<slug>/` with `files/` for scratch, the
   `.packet` and `$GIT_DIR/packet` pointers, and discovery from `cwd`.
2. `wpk new "…"` for a scratch packet, and `wpk work` that creates the
   record on first use in any directory, git or not.
3. `wpk run`: write the binding. Capture sources only when the packet
   leaves the host.
4. Results land in the source: the protocol's rule on results vs
   process, and the shadow repo for plain folders (§5.1, §5.2).
5. A hand-written dehydrated `PACKET.md` for a real failing test, plus
   `wpk get` to hydrate it.

Use it on the next real task, and on one research task with no repo.
The measure: did starting and resuming take any thought?
