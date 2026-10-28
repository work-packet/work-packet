# The packet format: layout and lifecycle (outline, draft 0)

Status (2026-10-26): an outline for review. Nothing here is built.
Revised the same day to add the in-place form (§2.1), discovery (§2.2),
and the packet directory as a git repository (§2.4). It proposes taking the packet layout and lifecycle out of wpk's
implementation documents and publishing them as a standalone open
specification. The reasons are in `docs/positioning-survey.md` §7.

## 0. What changes and why

Today the format is defined by wpk for wpk:

- `docs/spec.md` (v0.2) is "the on-disk contract between the executor
  (`wpk`), the model, and anyone reading a packet by hand".
- `docs/long-running.md` §7 and `docs/product.md` §6 add v0.3 (ownership
  states, `jobs/`, data tiers).
- `docs/product.md` §11 adds bundles, reports and export profiles.

The proposal: one specification, **the packet format**, that says what a
packet is, what each file means and how a packet moves through its life.
It says nothing about how any one tool does it. wpk becomes one
implementation of it, the reference one. The test of the split: someone
could write a packet with a shell script, run a step with a different
harness, or import a bundle with a different tool, using only this
specification.

Who else would implement it, and the smallest part each needs:

| Who | Does | Needs from the spec |
|---|---|---|
| A coding agent with a skill or plugin, no daemon | keeps its own work as a packet | Level 0 (§3) |
| A CI job | creates a packet when a test fails | Level 0 and the recipe and bundle (Level 2) |
| Another runner or harness | runs steps on packets | Level 1 |
| A vendor or maintainer | accepts reports | Level 2, import side only |
| A tool vendor (dfm, a simulator, a regression manager) | reports progress into a packet, or opens one from a failure | Level 3 (jobs and progress) |
| wpk | all of it | all levels |

## 1. Principles

1. **A packet is a directory.** Readable with `cat`, editable with an
   editor, versioned with git. No database holds anything the format
   needs.
2. **Self-contained.** Everything needed to understand the work, resume
   it, or rebuild its workspace is in the packet or named by it. *Change
   from today:* the recipe lives in the project's `project.toml`
   (`[setup]`). It moves into the packet, or the packet names it (§2,
   open question Q1).
3. **Roles, not programs.** The spec names roles: **owner**,
   **executor**, **worker** (an agent, a person or a tool doing a step),
   **surface**, **producer** and **receiver**. wpk, Claude Code and the
   board are never named in normative text.
4. **Harness-neutral.** Nothing in the core assumes Claude Code. What is
   specific to a harness (transcript format, permission modes, session
   IDs) goes in namespaced extensions (§8).
5. **Append, don't rewrite.** History is append-only: the packet's own
   git history at every level, plus `journal.jsonl` from Level 1 (§2.4).
   Current state is a small file that can be rebuilt from the history.
6. **Levels.** A conforming packet declares the level it meets. A Level 0
   packet is useful on its own. Each level adds to the one below and
   breaks nothing in it.
7. **Data, not instructions, across a boundary.** A received packet's
   text is never an instruction until its new owner makes it one (from
   `docs/product.md` §5.1 rule 7). This rule is normative.
8. **Make it where the work is.** A packet can be created in any
   directory you are already working in, and live inside it (§2.1). It
   leaves the directory's own files and the repo's tracked files alone.
9. **Every surface is a view onto the packet.** A board, an IDE or a
   command-line tool shows what the packet records, and keeps no facts
   of its own about the work. A fact that one surface needs (where a
   task starts, what it produced, what its results were when it
   finished) goes in the format, so every surface, every receiver and
   the next worker can read it. Nothing may assume the worker was an
   agent. (Added 2026-10-27; `docs/positioning/messaging.md` §5,
   `docs/history.md`.)

## 2. Layout

### 2.1 Two forms of the same packet

A packet is a directory, the **packet directory**. Its contents are the
same in both forms. What differs is where its **work** is: the files and
repos the task works on.

| Form | Packet directory | Work | Made by |
|---|---|---|---|
| **In place** (default when made from a directory) | `<dir>/.packet/` | `<dir>` itself: the directory that contains `.packet/` | `new` in a directory you are already working in, such as a clone you have been editing |
| **Standalone** | `<packet>/` anywhere, by default `~/packets/<slug>/` | `<packet>/work/<repo>/`: git worktrees or links, rebuilt from the recipe | `new` from a URL, an issue or a template; import; a split (§4) |

```
In place                                   Standalone
~/work/dv-solve/          ← the work       ~/packets/uart-overrun/   ← the packet directory
  .packet/                ← the packet       PACKET.md  memento.md  state/  …
    PACKET.md  memento.md  state/  …         work/
  src/  tests/  …         your files           dv-solve/             ← worktree on wpk/uart-overrun
```

Rules for the in-place form:

- **The repo is untouched.** The producer adds `.packet/` to
  `.git/info/exclude` of every repo that contains it. That is a local
  file, not `.gitignore`, so the repo's tracked files don't change.
  Committing `.packet/` into the repo is allowed but not the default.
- **The work is implicit.** There is no `work/` entry. The recipe
  (`recipe.toml`) records each git repository found in the work: the
  directory itself if it is one, and the repos under it, up to a depth
  the recipe states. Directories managed by a package manager (for
  example IVPM's `packages/`) are recorded through that manager's file,
  not one by one.
- **No worktree inside the work.** A worktree under the checkout
  doubles every file for `grep -r`, build globs and test discovery.
  When the task needs a second copy of the code, the packet **splits**
  into the standalone form (§4).
- **A pointer form.** `.packet` may be a symbolic link to a packet
  directory elsewhere (`~/packets/<slug>/`). The packet is still in
  place. Its data survives `git clean -ffdx` and a fresh clone, because
  clean removes the link, not its target.

Measured with git 2.43 (`docs/ergonomics.md` §10):

- `git clean -fdx` removes every untracked file under `.packet/` unless
  `.packet/` is itself a repository, which it then skips;
- `git clean -ffdx` removes a nested repository too, but not the
  target of a symbolic link.

### 2.2 Discovery

A tool finds the packet for a path the way git finds a repo:

1. Walk up from the path.
2. At each directory, check for `.packet/PACKET.md` (in place) or
   `PACKET.md` (standalone), and stop at the first match.
3. Stop at the filesystem root or at `$PACKET_CEILING_DIRECTORIES`,
   like git's `GIT_CEILING_DIRECTORIES`.

A standalone packet's `work/<repo>` therefore resolves to its packet,
and so does any file in an in-place packet's work. A tool may also keep
an index of known packets (`~/packets/index`), but the index is a
cache: the directories are the truth.

### 2.3 The packet directory

The whole layout of the packet directory, marked by level (L0–L3).
Names in *italics* are optional at that level.

```
<packet directory>/
  PACKET.md          L0  front matter: format version, id, title, level, state; body: what this
                         work is, for a human or an agent arriving cold (new; see Q2)
  memento.md         L0  the next instruction (today's §4.2)
  state/             L0  plan, notes, outline: the work's own files
  journal.jsonl      L1  append-only record (today's §4.3); optional at L0, where the packet's
                         commits are the history (§2.4)
  steps/NNNN/        L1  one folder per committed step: summary, result, state.diff, meta.json
  status.md          L1  executor-owned current state (today's §4.1); at L0 the state is in PACKET.md
  recipe.toml        L2  how to rebuild the workspace: repos at commits, inputs, links, smoke check
                         (today's project.toml [setup], moved into the packet)
  work/<repo>/       L2  standalone form only: git worktrees or links, rebuilt from the recipe
  .git/              L0  the packet directory is a git repository (§2.4)
  identity/          L2  named links to outside resources, rebound on import
  jobs/<id>/         L3  long-running non-agent work: job.json, log, progress.jsonl, graph.json, exit
  mailbox/           L1  notes from the owner, waiting for the next step
  children/          L1  links to spawned packets
  .lease, .pending/  L1  executor working files; not part of a bundle
  .x-<impl>/         any implementation-private files (wpk's .wpk/); ignored by other readers
```

The packet directory's `.gitignore` excludes the derived tier,
`work/`, `jobs/*/log`, `.lease` and `.pending/`. So the packet's repo
holds the core tier and the chosen record files, which is what travels
in a `team` bundle.

### 2.4 The packet directory is a git repository

Required at every level.

- **It is the history at Level 0.** A Level 0 writer records each
  shift-end (§4) as a commit of the packet directory. The commit
  message is the summary, followed by trailers:

  ```
  Fix the overrun flag clear; tests 41/67 pass.

  Packet-Event: shift-end
  Packet-By: matt
  Packet-Item: 2a
  Packet-Head: dv-solve 3f0c9a2
  Packet-Cost: 1.84 USD
  ```

  An agent with only a skill can do this, because writing a commit
  message is something models do reliably. Hand-written JSONL is not.
- **It protects the packet.** Because the packet is a repository,
  `git clean -fdx` in the work skips it.
- **It gives every surface diffs and blame of the plan and notes** with
  no extra tooling.
- **`journal.jsonl` keeps its role.** From Level 1 it is required and
  authoritative for the executor (ordering, commit protocol, costs). The
  executor also commits the packet directory once per committed step,
  with the same trailers, so the two histories line up. At Level 0
  `journal.jsonl` is optional; a tool may write it alongside the commits.
- **Converting.** A Level 0 packet raised to Level 1 gets a
  `journal.jsonl` rebuilt from its commit trailers. Nothing is lost
  going up.

The packet's repository is separate from the repos in its work. Its
commits never touch them. Their HEADs appear only as `Packet-Head`
trailers and in journal records.

### 2.5 Points still to settle

- **Data tiers are normative** (from `docs/product.md` §6). Every path
  belongs to a tier:
  - **core**: always travels, never cleaned;
  - **record**: transcripts and logs; travels by choice;
  - **derived**: work trees, builds, waves, coverage; cleaned, and
    replaced by a pointer on export.
  The spec lists the tier of every name above. An unknown path is
  derived by default.
- **Project vs packet.** Today a project holds a root packet and its
  children, and the configuration sits at the project level. The spec
  defines the **packet** first and the **project** as a thin container:
  a name, a root, and defaults the packets inherit. A single packet with
  no project must be valid (needed for CI and reports).
- **Identifiers.** Keep WPIDs as UUIDs (v4 roots, v5 children,
  deterministic from the spawn). An address is `pkt:<uuid>`, optionally
  `@<origin>`. *Change from today:* the `wpk:` prefix becomes neutral
  (Q3).

## 3. Levels

| Level | Name | What it adds | What it enables |
|---|---|---|---|
| **0** | **Readable** | `PACKET.md`, `memento.md`, `state/`, the packet directory as a git repo with a commit per shift-end | Any agent or person can take over the work cold. An agent can keep its work this way with only a skill and no executor |
| **1** | **Stepped** | `journal.jsonl`, `status.md`, `steps/`, the commit protocol, leases, `.pending/`, mailbox, children, step metrics | An executor can run bounded steps atomically, recover after a crash, and charge cost to steps |
| **2** | **Portable** | `recipe.toml`, `work/`, `identity/`, tiers, the bundle and manifest, export profiles, `clean` | Hand-off to another person or host, CI-created packets, reports to another organization |
| **3** | **Supervised** | `jobs/`, the progress protocol, `wait job:` | Long-running tools take turns with agents, and a board can show their progress |

Level 0 is the strategic piece: it is what a plugin, a skill or another
harness can adopt in an afternoon. It must stand without an executor. A
writer at this level (a small CLI, hooks, or the agent itself)
updates the memento and `state/` and commits the packet directory at
each shift-end (§2.4). The history is git commits with trailers, not
hand-written JSONL. v0.2 took the books away from the model because
models keep them badly; commits are the form they keep well. At Level 1
the executor keeps the books.

## 4. Lifecycle

The states, who owns the packet in each, and the moves between them. This
is v0.3 (`docs/long-running.md` §1, `docs/product.md` §6) stated without
reference to wpk commands.

```
            create
              │
              ▼
   ┌────► HELD(setup) ── materialize, smoke check ──┐
   │          │                                     │
   │          ▼              hand off               ▼
   │      HELD(…)  ◄──────────────────────────► RUNNABLE ⇄ SLEEPING
   │   question/failed/        take              │   (resume: in/at/wait job)
   │   limit/taken                               │
   │          │                                  ▼ resume: done
   │          └──────────── next batch ◄──── COMPLETED
   │                                             │
   └──── import ◄── export (bundle) ◄────────────┤
                                                 ▼
                                       clean → ARCHIVED (new; Q4)
   ASSIGNED: ownership moved to another person; this copy is a read-only pointer
```

The spec states, for each transition:

- **Who may make it.** Owner, executor or receiver.
- **Preconditions.** For example, hand-off needs an instruction, a
  passing check, and every work repo on a branch with a clean tree.
- **What the journal records.** The record type and its required keys.
- **What happens to each tier.**

Lifecycle events to define explicitly, because they matter most to
anyone else implementing the format:

| Event | Today | For the spec |
|---|---|---|
| **create** | `wpk new`, templates | From a template, from CI, from an issue, by hand: all produce the same Level 0–2 packet. A `created` journal record names the producer |
| **materialize** | setup.md §10, import §11.1 | Rebuild `work/` from `recipe.toml`, rebind `identity/`, run the smoke check. Normative, because every receiver does it |
| **shift-end** | none | Level 0: the interactive counterpart of a step. Not atomic. Writes the memento and summary, then commits the packet directory with the trailers in §2.4. Made by a person, a hook at session end or compaction, or a context-limit nudge |
| **step** | spec.md §7 commit protocol | Level 1 only. Atomic. On success the work repos are committed with `Packet:`/`Step:` trailers, and so is the packet directory. On failure tracked files are reset. **Untracked files are removed only if the step created them:** the executor records the untracked set before the step. An in-place work holds the owner's own scratch files, so a blanket `git clean -fd` is not allowed |
| **split** | none | In place → standalone. Make worktrees of the work's repos at their current commits, outside the work (a sibling directory or `~/packets/<slug>/work/`). Move or copy the packet directory there, and leave a tombstone `.packet/PACKET.md` that names the new location. Needed for a second packet on the same clone, or to let the runner work while the owner keeps editing |
| **hand off / take** | long-running.md §1 | The ownership rule: one owner at a time, ownership follows from the state, every move recorded. In place, while the runner owns the packet, the work is the runner's too: surfaces make it read-only, as they do now. Splitting first avoids that |
| **assign / consult** | product.md §11.7 | Assign moves ownership to another person. Consult makes copies with `origin`. Define both in the format so bundles carry them |
| **clean** | `wpk clean` | Remove the derived tier and keep the recipe. **Default before hand-off and export** (from `bigger_picture.md`). Record what was removed |
| **export / import** | product.md §11.1 | The bundle (§6) and its profiles |
| **archive** | not defined | New. A completed, cleaned packet that will take no more batches; still readable, still an address |

## 5. Files in detail

For each file, the spec gives its keys and a short example, taken from
`docs/spec.md` and stripped of wpk-specific detail:

- **`PACKET.md`** (new). Front matter: `packet` (format version), `id`,
  `slug`, `title`, `level`, `form` (`in-place` or `standalone`),
  `created`, `producer`, `origin` (for copies), `tags`, and `moved_to`
  in a tombstone after a split.
  Body: a short brief.
- **`memento.md`**. Keys: `resume`, `reason`, `ask`, `spawn`, `item`.
  The body is the next instruction. The resume grammar (`now`, `done`,
  `fail`, `in`, `at`, `wait job:`, later `every`) moves here from
  spec.md §5.
- **`status.md`**. Today's keys plus `held_for` and `owner`. The `wpk`
  key becomes `packet`. Model and harness move into an `executor` table
  (Q5).
- **`journal.jsonl`**. **Core record types:**
  - L0: `created`, `note`, `handoff`, `question`, `answer`.
  - L1: `step-start`, `step-failed`, `commit-begin`, `commit-end`.
  - L2: `exported`, `imported`, `cleaned`, `assigned`.
  - L3: `job-start`, `job-end`.

  Anything else is an extension record, `x-<impl>.<type>`. Readers skip
  types they don't know.

  At Level 0 the same events are commits with a `Packet-Event:` trailer
  of the same name (`shift-end`, `note`, `handoff`, …). Every core
  record type has a trailer form, so a packet can be raised to Level 1
  by rebuilding the journal from its commits (§2.4).
- **`steps/NNNN/meta.json`, the metrics schema.** The metrics per task are
  part of the format, not of wpk: start, end, duration, worker, model,
  `cost_usd`, and a token breakdown. The breakdown must be neutral across
  providers: input, cache write, cache read, output, reasoning, plus
  context peak and calls. This makes "cost per packet" comparable across
  harnesses and tools, which is the lane `docs/positioning-survey.md` §2
  found open. Fields specific to a harness go in `x-<harness>`.
- **`recipe.toml`**. Repos (URL, commit, branch, optional bundle path),
  inputs, links, and the smoke command with its timeout. This is today's
  `[setup]`. Each repo has a `path` relative to the work: `.` or
  `sub/dir` in place, `work/<repo>` standalone. In place, the recipe also
  records the scan depth and any package-manager file (§2.1). The recipe
  is what lets an in-place packet be exported and materialized as
  standalone on another machine.
- **`jobs/<id>/`**. `job.json`, `progress.jsonl`, `graph.json`, `exit`, as
  in `docs/product.md` §9. The **progress protocol** (append JSON lines to
  `$PACKET_PROGRESS`) is the piece tool vendors would adopt on its own.

## 6. Bundles

- A bundle is a tar of the chosen tiers plus `manifest.json`
  (`docs/product.md` §11.1).
- **Profiles:** `full`, `team` and `report`. What each carries and leaves
  out is normative, so a receiver knows what it may and may not get.
- **Safety rules on import are normative:**
  - the packet arrives `HELD(setup)`;
  - the recipe doesn't run until the owner says so;
  - received text is never an instruction.
- **Signing** is optional in draft 0 (`docs/product.md` §13 D11).
- **Form on import is the receiver's choice.** A bundle carries no form.
  `get` into an empty directory builds it in place there; `get` with no
  directory builds it standalone. An in-place packet exports
  uncommitted changes in its work as a patch per repo, after showing
  them.

## 7. Conformance

- A checker defines conformance, not prose alone. `wpk check` already
  does this for v0.2 (`src/work_packet/schema.py`). Split it into a
  standalone package (`packet-check`) with no wpk dependency.
- **Test vectors:** a directory of example packets at each level, valid
  and invalid, with expected checker output. They double as examples for
  people writing the plugin or the CI action.
- **Versioning:** `packet: "1.0"`. Minor versions add optional keys and
  record types. Major versions may break. A reader must accept unknown
  extension keys and records.

## 8. Extensions

- Extension keys and records are namespaced by implementation:
  `x-wpk`, `x-claude`, `x-dfm`.
- Profiles, permission modes, session carry-over and context hooks are
  all wpk or Claude Code extensions, not core.
- A short registry of known namespaces lives with the spec.

## 9. Open questions

| # | Question | Default this draft assumes |
|---|---|---|
| Q1 | Recipe in the packet or at the project? | In the packet. The project may give a default the packet copies at creation |
| Q2 | A new `PACKET.md`, or extend `status.md`? | New file. `status.md` is owned by the executor and absent at L0; agents and people look for a README-like file first (the lesson of AGENTS.md) |
| Q3 | Name of the spec and of the address scheme | "Packet format", `pkt:`. Check for clashes before publishing |
| Q4 | Is `ARCHIVED` a state, or `COMPLETED` plus a `cleaned` record? | A state, so a board and a receiver can tell "may take a next batch" from "finished for good" |
| Q5 | Do model and harness belong in `status.md` at all? | Move them to an `executor` table. They are what Level 1 records, not what the work is |
| Q6 | Is the parent/child tree core or Level 1? | Level 1. A Level 0 packet is a single packet |
| Q7 | Where the spec lives and its licence | A separate repo (for example in DVKit, or `packet-format`), CC-BY for the text and Apache-2.0 for the checker and vectors |
| Q8 | How v0.2 and v0.3 packets migrate | `wpk migrate`, plus a reader that accepts `wpk: "0.2"`/`"0.3"` as aliases for the matching level. A v0.2 project becomes a standalone root packet; its project-level `work/` clones become the recipe's sources |
| Q9 | Is the packet directory a git repo? | **Decided: yes, at every level** (§2.4) |
| Q10 | Name of the in-place directory: `.packet/`, or `.wpk/`, which is used today for surface files (`docs/product.md` §6)? | `.packet/`, neutral like the spec. Surface files move to `.packet/.x-wpk/` |
| Q11 | In place, does a packet commit to the owner's current branch? | Yes, and the packet records the base commit. On the default branch, `new` offers a `wpk/<slug>` branch first. `done` offers to squash |
| Q12 | How deep the work scan goes for repos, in place | Depth 2, skipping directories that a package-manager file accounts for; the recipe records what was found, and the owner can edit it |

## 10. Plan

1. Settle Q1–Q8 and Q10–Q12, then write draft 1 of the spec from this outline,
   reusing the text of spec.md and long-running.md §7.
2. Mark `docs/spec.md` as the **wpk profile** of the format: wpk's
   extensions and its executor behaviour. Leave the normative layout to
   the new spec.
3. Pull `wpk check` out into `packet-check`, with test vectors for each
   level.
4. Build the two cheapest producers on Level 0–2, as the first users of
   the spec outside wpk:
   - a **Claude Code plugin or skill** that keeps a Level 0 packet with
     no daemon;
   - a **CI action** that writes a Level 2 report bundle when a test
     fails (`docs/product.md` §11.2).
5. Adopt the progress protocol in dv-flow-mgr natively, without an
   adapter, as the first Level 3 producer outside wpk.
6. Publish: the spec repo, the checker, the vectors, and a short talk
   or post, "Agents are shift workers: a format for the turnover".
