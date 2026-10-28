# Work data: master design (draft 1, 2026-10-27)

> **Revised 2026-10-28 (run binding, `docs/run-binding-v1.md`).** Three
> decisions change this draft: (1) **the clone is the packet**: the card
> and `.work-packet/` sit at the top of the clone, excluded from git through
> `.git/info/exclude`; a packet with no repo, or with several, is a plain
> folder; (2) **runs and the packet's blobs live in
> `<packet>/.work-packet/`**, not under `~/.work-packet/` (home space is
> often limited); `~/.work-packet/` keeps only small shared things
> (registry, index, config, locks, the statistics database), and `wpk done`
> copies the archive to a configurable archive directory; (3) **the runner
> works in the clone**, and parallel children get sibling worktrees
> `../<name>@<child>/` that are packets themselves. §5, §5.1, §13.1,
> §13.3, the P2 row and the glossary are updated; other sections still
> say `~/packets/<name>/` and `~/.work-packet/runs/<id>/`, and should be
> read through these rules.

Status: **for review.** Nothing here is built. This is the master design
for how work-packet captures, moves, keeps and shows the data of a
piece of work. It covers the durable record people and agents exchange
(the packet) and the ephemeral record of how the work was executed
(the run). It consolidates and supersedes the format and lifecycle
parts of earlier drafts (§17). Three working documents hold more depth
on parts of it:

| Document | Depth on |
|---|---|
| `docs/packet-card.md` | the card format, lifecycle, requests, bridges, attachments, clusters, user journeys |
| `docs/packet-views.md` | the view model, `@rev`, the CLI and the TUI browser |
| `docs/run-history.md` | harvest, the history store, retention |
| `docs/work-sessions.md` | terminal sessions, runs of commands, progress, the scribe |

Where this document and those disagree, this one is meant to win. Any
such disagreement is a bug to fix in review.

Contents:
1. Summary
2. Goals and non-goals
3. Principles
4. The data, sorted by kind
5. Architecture: six stores
6. The packet: the card format
7. References and attachments
8. Lifecycle
9. Requests between agents, and waking
10. Hand-off and freeze
11. Bridges
12. Travel: copies, bundles, hosts without shared disk
13. The run: the active record
14. Harvest and the history store
15. Seeing it: one view model, three surfaces
16. Safety and privacy
17. What this replaces, and migration
18. Phased plan
19. Decisions and open questions
20. Glossary

---

## 1. Summary

**Two kinds of data, treated differently.**

- **The packet** is what the work *is*: what was asked, what it refers
  to, what was said, what came of it. It is **one Markdown file, the
  card** (`uart-overrun.wp.md`), mostly references, readable like a
  GitHub issue. It **travels**: to the runner, to another agent, to a
  colleague, to a CI artifact, to an issue thread.
- **The run** is how the work was *done*: steps, plans as executed,
  diffs, transcripts, tokens, costs. It is **the server's own
  record**. It **never travels**. It lives as files while the packet
  is active, and is **harvested** into a history store owned by the
  server when the packet leaves the board, so the long view (cost,
  trends, comparisons, "what did we do last time") is kept.

**Request and response are one thread.** A packet's card holds a
conversation of entries: `sent`, `accepted`, `question`, `answer`,
`handoff`, `result`, `pinned`, `closed`. Each entry has one author and
is never edited. An agent asks another agent for work by sending a
card. It is woken when the `result` entry lands.

**Big files go in a blob store by content hash**, not in the card. The
store is a directory, an on-prem S3-compatible service, or R2.

**Everything is seen through one view model** with three surfaces: the
web dashboard, the CLI, and a TUI browser that steps back through
history (`uart-overrun@s4`). The view model reads active runs and
harvested history the same way.

```
          travels                          stays with the server that ran it
 ┌──────────────────────────┐        ┌──────────────────────────────────────────┐
 │ the card  (.wp.md)       │ Record:│ active run record   ── harvest ──►        │
 │ brief · refs · thread    │───────►│ ~/.work-packet/runs/<id>/   history store │
 └────────┬─────────────────┘  ref   │ steps, plan, diffs,         archives +    │
          │ refs                     │ transcripts, metrics        database      │
          ▼                          └──────────────────────────────────────────┘
 workspace (your clone, a folder,       blob store (by hash): attachments, and
 a managed clone, nothing)              the run's narrative, diffs, transcripts
```

## 2. Goals and non-goals

**Goals.**

1. A packet can be made from anything people start work from: the
   directory you are in, a repo URL, a question, a GitHub issue, a
   collection of files, a CI failure, another agent's need. Each takes
   one command and no directory navigation.
2. A packet is one readable file in most cases, made of references.
3. Agents hand work to each other with packets, and are woken by the
   response, safely and within a budget.
4. People see everything through names, never ids or deep paths.
5. A hand-off carries what the receiver needs to continue, and no
   more.
6. Execution detail is kept for the long view, but doesn't burden the
   packet or its receivers.
7. History is navigable: any packet, active or long finished, can be
   stepped through as it was.
8. Nothing requires git, a server or a shared filesystem. Each adds
   reach when present.

**Non-goals for this design.**

- Multi-user access control on the hub (`docs/product.md` §12 owns it).
- The scheduler and placement (`docs/scheduler.md`).
- A query language beyond `key:value` filters and SQL on the history
  database.
- Real-time collaborative editing of a card.

## 3. Principles

1. **The packet is a file; the run is the server's.** What travels and
   what stays are decided by kind of data (§4), not case by case.
2. **References, not copies.** Copies are made only when a receiver
   can't reach what is named, or when something named will disappear
   (§10.2).
3. **One author per entry, never edited.** Ownership is visible,
   merging is a union, history is trustworthy.
4. **Data lives in front matter and trailers. Prose is never parsed**
   (§6.5).
5. **Names for people, ids for machines.** Directories named by id
   exist only in machine areas.
6. **Location is not state.** Files don't move when state changes.
   Archiving is the one exception.
7. **The cold-start test.** Given only the card, a person or an agent
   can tell what the work is, where it stands, and how to pick it up.
8. **Files are the source of truth.** Every database is built from
   files and can be rebuilt from them (`docs/runner.md`).
9. **Every surface is a view.** The board, the TUI, the CLI and the IDE
   show what the data records. None keeps facts of its own
   (`docs/packet-format.md` §1 rule 9).
10. **Received text is data, not an instruction**, until its new owner
    accepts it (`docs/packet-format.md` §1 rule 7).

## 4. The data, sorted by kind

Every piece of data belongs to one kind. The kind decides where it
lives, whether it travels, and how long it is kept.

| Kind | Examples | Lives in | Travels | Kept |
|---|---|---|---|---|
| **Ask** | title, brief, refs, budget, where to reply | card (only copy) | always | with the card |
| **Conversation** | questions, answers, notes, follow-ups, hand-offs | card (only copy); the journal mirrors it | always | with the card |
| **Outcome** | result, deliverables, total cost | card (summary); run (full report, deliverable snapshots) | the summary | card: always; run: as narrative |
| **Working knowledge** | plan, notes, tried and dropped, decisions taken without asking, environment quirks | run (`state/`, live) | **distilled into the card** at hand-off and freeze (§10) | narrative tier |
| **Provenance** | steps (by agents and by people), runs and jobs (command, exit, log, progress), diffs, transcripts, per-step tokens, cost, timings | run (only copy) | **never**; the card holds a pointer | per tier (§14.3) |
| **Control** | lease, `.pending/`, mailbox, scheduler state, terminal sessions and their scrollback, session ids, host paths, budgets in progress | run | never | not kept |
| **Attachments** | waves, logs, dumps, captured inputs | blob store, by hash | by reference; bytes only when needed | while a live card names them (§7.3) |
| **Work** | code, documents, results | the workspace | what can't be rebuilt (§12) | the workspace's own business |

## 5. Architecture: six stores

| Store | Where | Holds | Owner | Rebuilt from |
|---|---|---|---|---|
| **Cards** | `<packet>/<name>.wp.md` at the top of the packet folder (a clone, or a plain folder); agent-made sub-packets listed under the root run's `sub/` | packets | whoever holds the copy | n/a: the truth |
| **Workspaces** | the packet folder itself: the clone (IVPM dependencies in its `packages/`), or a plain folder of files or clones | the work | the owner of the moment | sources in the card |
| **Run records** | `<packet>/.work-packet/runs/<id>/` | active runs | the executor on this host | n/a: the truth while active |
| **Blob store** | per packet, `<packet>/.work-packet/blobs/`; plus remote stores per host config; archives copied at `wpk done` to the archive directory | attachments; harvested narrative, diffs, transcripts | the server; shared stores by the team | n/a: the truth for blobs |
| **Index** | `~/.work-packet/index.db` | cards' JSON form, run summaries, "last seen by you" | tools | a scan of cards and runs |
| **History store** | the statistics database in `~/.work-packet/history/` (metrics only, small); `.wph` archives in `<packet>/.work-packet/` while the packet exists, then in the archive directory (default `~/.work-packet/history/`, configurable) | harvested runs | the server (wpkd; `wpk` alone when no server runs) | the archives |

People's view of all of it:

```
~/work/
  uart-overrun/                 a clone, and the packet: cd here, open it in the IDE
    .git/
    uart-overrun.wp.md          the card, at the top (excluded from git)
    .work-packet/               runs, blobs, archive (excluded from git)
    ivpm.yaml
    packages/                   its dependencies, as IVPM made them
    rundir/…                    what steps produce, in plain view
  uart-overrun@fix-tx/          a parallel child: a worktree, and a packet
  axi-uvm-port/                 a plain folder: a packet with two repos
    axi-uvm-port.wp.md
    .work-packet/
    fw-axi/
    uvm-ref/
  uvm-versions/                 no repo (a question): a folder, filled or empty
    uvm-versions.wp.md
    .work-packet/
```

Shared things are under `~/.work-packet/` (small), and people never need
to go there.

### 5.1 The packet folder (revised 2026-10-28)

**The clone is the packet.** Most work is one repo, so the default shape
is a clone with the card and `.work-packet/` at its top.

- `wpk new --here` in a clone writes `<name>.wp.md` and `.work-packet/`
  there and adds both to `.git/info/exclude` (local, never pushed), so
  `git status` stays clean and the card is never committed. This is the
  main way to make a packet.
- `wpk new <repo> "<title>"` clones with IVPM (§5.2) into `<name>/` on
  branch `wpk/<name>`, then does the same.
- `wpk new "<title>"` with no repo makes a folder holding the card and
  `.work-packet/`; files may be added before it runs. A task with several
  repos is a plain folder with the clones in it (most "other repos" are
  IVPM dependencies in the clone's `packages/` anyway).
- **`git clean -x`/`-X` is denied** to agents: it deletes ignored files,
  the card and the run among them (`git clean -fd` is safe).
- **The runner works in the clone.** Outputs (build trees, logs,
  waveforms) appear where the person looks. Opening the IDE pauses the
  packet first, since a failed step resets tracked files.
- **Parallel children** get sibling worktrees `../<name>@<child>/`, each a
  packet with its own card and `.work-packet/`; `wpk ide` opens them as
  extra roots.
- **Discovery** walks up from the current directory to the first folder
  holding `.work-packet/` (as git finds `.git`), so anything inside
  resolves to the packet (§6.6).
- **When the task is done** and its branches are pushed, `wpk done` lists
  ignored outputs and asks what to keep, harvests, copies the archive to
  the archive directory, freezes the card (§10.2) and deletes the folder.

### 5.2 Workspaces are materialized with IVPM

IVPM is the canonical way to clone a git workspace, because it brings
in the repo's dependencies (`ivpm.yaml`) at the right versions, along
with its environment (venv, direnv). Plain git would miss them. It also
works for a repo with no `ivpm.yaml`: `ivpm clone` then just clones,
and checks out or creates the branch.

| Operation | Command wpk runs |
|---|---|
| New task from a repo | `ivpm clone <url> <name> -b wpk/<name> [-d <dep-set>]` |
| Hydrate a frozen packet, exactly | `ivpm clone <url> <dir> -r <commit>`, then `ivpm update --lock-file <pinned package-lock.json>` |
| Refresh after the card's `setup` changes | `ivpm update` in the workspace |
| Environment for steps and sessions | `direnv exec <repo> …` (the binding's `env = "direnv"`, `packet-shapes.md` §5) |
| A bundle for a receiver who can't reach the git servers | `ivpm snapshot` of the workspace, stored as a blob |

On the card, a `git:` workspace ref is always materialized this way.
The dep-set goes in the ref's long form:

```yaml
work:
  - ref: git:https://github.com/featherweight-ip/fw-uart16550@uart-overrun
    dep-set: default-dev
```

**A workspace is several repos.** The repo you cloned is one. Each
editable dependency IVPM cloned into `packages/` is another, which
matters when a task co-develops a dependency (fixing pssc while working
on pss-registers). So every rule that applies per repo applies to all
of them:

- **Steps:** commit and roll back each repo that changed, the root and
  the editable dependencies alike. Cached dependencies (`cache: true`)
  are read-only links and never change.
- **Freeze** pins the root at a commit and `packages/package-lock.json`
  as a blob. The lock records every dependency's resolved commit. Any
  editable dependency with commits that aren't upstream is pushed to a
  `refs/packets/…` ref or bundled, as the root is (§10.2).
- **Hand-off checks** cover every editable dependency: a clean tree, and
  no work that exists only locally.
- **Done** refuses to delete a task folder whose root or editable
  dependencies hold unpushed or uncommitted work, and says which.

**Disk and speed** come from IVPM, not from wpk: `IVPM_CACHE` for
read-only dependencies shared across tasks, and `--deps-source` to copy
from a "golden" workspace. wpk keeps no mirrors of its own.

One caution: IVPM makes a git worktree reuse its parent worktree's
`packages/` by symbolic link. A split-mode scratch worktree would then
edit the same dependency clones as the person. wpk creates those with
`--no-worktree-deps-source`, or with `--deps-source-mode=copy`.

**Asks of IVPM** that would make this cleaner (IVPM is ours):

| Ask | For |
|---|---|
| `ivpm status --json`: every repo in the workspace, with dirty, ahead/behind and editable or cached | the step commit, freeze, hand-off checks and `done` enumerate repos from one call, not by parsing |
| `ivpm clone --reference <dir>` (git alternates) for the root and editable dependencies | per-task clones that share objects, as worktrees would |
| A lock-file field marking a dependency with local commits not on its remote | freeze knows what must be pushed or bundled |
| `ivpm update --lock-file` accepting a URL or stdin | hydrating from a blob store or the hub without a temporary file |

## 6. The packet: the card format

### 6.1 The file

- Named `<name>.wp.md`: recognisable anywhere, rendered as Markdown
  everywhere.
- UTF-8, YAML front matter, then the **brief** (text before the first
  entry), then the **thread** (entries).
- The smallest valid card is a title and a brief. Tools add `packet`,
  `id` and `name` on first touch.

```markdown
---
title: Survey of RISC-V cache coherence verification approaches
---
Find what's published on formal vs simulation approaches, 2022 onwards.
```

### 6.2 Front matter

| Key | Meaning | Default |
|---|---|---|
| `packet` | format version, `1` | added |
| `id` | ULID; never changes | added |
| `name` | `[a-z0-9][a-z0-9-]{0,47}`, unique in its home | from the title |
| `title` | one line | required |
| `by` | requester: a person, or `pkt:<name>` | you |
| `to` | worker it was sent to: `me`, `runner`, a person, `pkt:<name>`, a bridge (`gh:owner/repo`) | `me` |
| `parent` | the packet this one was made for | none |
| `origin` | where it came from | none |
| `work` | the workspace: a ref, `folder`, or `none` | the current directory for `new`; `none` for `ask` |
| `inputs` | refs to read | none |
| `setup`, `repro` | one command each, in the project's own tooling | none |
| `reply`, `watch` | where results also go; what to watch for changes | `origin` when made from an issue |
| `notify` | which entries to tell the requester about at once | `question, result` |
| `budget`, `due`, `tags` | limits and sorting | host profile; none |
| `state`, `updated` | **caches** of what the thread says | tools |

The brief and the keys above `state` are **frozen at send**; the `sent`
entry records their hash. Changes after that are entries. Host facts
(managed paths, leases, permissions, sessions) never go on a card, so a
received card can't bring its own permissions. Unknown keys are kept;
implementations namespace theirs (`x-wpk`).

### 6.3 The thread

Each entry starts with a heading in a fixed form and ends at the next:

```
## <kind>[ <arg>] · <who> · <YYYY-MM-DD HH:MM:SSZ>
```

The body is free Markdown with headings at level 3 or deeper. An entry
may end with **trailers**, git-style `Key: value` lines. An entry's key
is (time, who, kind); copies merge by the union of entries.

| Kind | By | Means | Trailers |
|---|---|---|---|
| `sent` | requester | brief frozen, handed to `to` | `Brief-Sha`, `Budget` |
| `request` | requester | a follow-up task | `Budget` |
| `accepted` / `declined` | worker | taken on / refused | `Workspace` |
| `question <id>` / `answer <id>` | worker / requester | needs input / gives it | `Recommend`, `Choices`, `Grants` |
| `note` | anyone, a bridge | information | `Source` |
| `handoff` | current owner | ownership moves; turnover note (§10.1) | `To`, `Head`, `Branch`, `Dirty`, `Plan`, `Notes`, `Record`, `Steps`, `Cost` |
| `progress` | worker | an occasional milestone | `Step`, `Cost` |
| `result` | worker | the task is finished | `Outcome`, `Deliverable`…, `Cost`, `Record` |
| `pinned` | current owner | a freeze (§10.2) | `Pin`…, `Record` |
| `cancelled`, `closed`, `reopened`, `replied` | requester | as named | `Posted` (replied) |

The thread holds what the other party needs to know. Steps,
transcripts and plans stay in the run.

### 6.4 An example

```markdown
---
packet: 1
id: 01JBF3K8Q2V7N0WZ3T5Y6R9M4C
name: uart-overrun
title: UART overrun flag not cleared after LSR read
by: matt
to: runner
origin: gh:featherweight-ip/fw-uart16550#41
work: git:~/work/fw-uart16550@uart-overrun
inputs:
  - blob:sha256:9c1e4a…          # waves.fst from CI run 8812
repro: dfm run uart.test_overrun
reply: origin
watch: origin
budget: 5 USD
state: done
updated: 2026-10-27 11:40:12Z
---
test_overrun fails at 41/67: OE stays set after LSR is read.

## sent · matt · 2026-10-27 09:12:03Z

Brief-Sha: 4be1c0

## accepted · runner · 2026-10-27 09:12:40Z

Working in your clone on branch uart-overrun.

## question q1 · runner · 2026-10-27 10:02:51Z

Clear OE on every LSR read, or only when the FIFO is empty?

Recommend: on every read
Choices: on every read | only when empty

## answer q1 · matt · 2026-10-27 10:30:17Z

On every read.

## result · runner · 2026-10-27 11:40:12Z

OE now clears on every LSR read. Added a read-while-full test; 67/67 pass.

Outcome: done
Deliverable: git:~/work/fw-uart16550@a1b2c3d the fix and the test
Deliverable: gh:featherweight-ip/fw-uart16550#52 pull request
Cost: 1.84 USD
Record: run:01JBF3K8Q2V7N0WZ3T5Y6R9M4C@7d3e2a1
```

More examples (a question, a file collection, an agent request, a CI
failure) are in `packet-card.md` §4.6.

### 6.5 Parsing

- **Grammar:** YAML front matter (scalars, lists, one level of maps,
  typed by a schema); the heading regex, ignored inside fenced code;
  trailers by `git interpret-trailers` rules.
- **One canonical JSON form** (`card.parse()`, `wpk show --json`), with
  a published JSON Schema and test vectors of card/JSON pairs. Tools
  work from the JSON, never the text.
- **Lenient reader, strict writer.** Reading never fails; what doesn't
  parse is kept in the previous entry's body and listed in `problems`.
  `card.append()` is the only writer and writes canonical form, which
  round-trips byte for byte. `wpk check` is strict.
- **Numbers never come from cards.** Metrics come from the run and the
  history database. A card's `Cost:` is a copy for people.

### 6.6 Names and addresses

| Form | Means |
|---|---|
| `uart-overrun`, `uart` | a name or a unique prefix |
| `.` or nothing | the packet of the current directory: walk up for a task folder (a directory holding `<its name>.wp.md`), then for `$GIT_DIR/packet` or a `.packet` pointer (attached clones) |
| `-` | the packet you last acted on |
| `uart-overrun.seed17` | a sub-packet |
| `matt/uart-overrun` | someone else's packet, through the hub |
| `@s7`, `@t2`, `@-1`, `@<time>` | a point in history (§15.2) |
| `pkt:01JBF3…` | an id |

## 7. References and attachments

### 7.1 References

`scheme:target[@rev][#sha256=…]`: `git:` (path or URL, at a branch,
tag or commit), `file:` (path or glob), `dir:`, `gh:owner/repo#n`,
`https://…`, `pkt:`, `run:<id>[@commit][/step]`, `job:`, `blob:sha256:…`.
Relative paths are relative to the card. The key a ref is listed under
says what it is for. Unreachable refs are shown as such.

### 7.2 Attachments

Files that nothing else holds (waves, dumps, logs from a run directory
that will be cleaned, a customer's test case) go to a **blob store**,
and the card names them by hash:

```yaml
inputs:
  - ref: blob:sha256:9c1e4a…
    name: waves.fst
    size: 1.4 GB
    from: /proj/sims/run42/waves.fst
    regen: dfm run uart.test_overrun --waves
```

- `wpk attach <name> <files…>` hashes the files, stores them and adds
  the refs.
- Fetching is lazy. A fetched blob appears as
  `~/packets/<name>/inputs/<file>`, a link into the local cache.
- `regen` lets a receiver rebuild instead of fetching. Store a file
  when it was expensive to make, or can't be reproduced.

### 7.3 Blob stores

The store interface is put, get, has and list. Stores are **host
configuration**, tried in order; a card may carry a hint, never
credentials.

| Store | Use |
|---|---|
| directory | the local cache; a team share where one exists |
| S3-compatible, on-prem | **recommended for clusters**: Ceph RGW if present; Garage (small); SeaweedFS (large); MinIO with care over its licence |
| R2 | the recommended cloud store: S3 API, no egress fees; when data may leave the site |
| Forgejo LFS / packages | no new service, but repo-bound |

- Keys are `sha256/<2>/<rest>`. A write is HEAD then PUT, and needs no
  lock. Every read is checked against the hash.
- People and jobs without credentials get **presigned, time-limited
  URLs**, in bundles and messages and never on cards.
- **Retention:** a blob is kept while any live card names it or the
  history store needs it (§14.3), plus a grace period. Pinning keeps it
  for good. Deletions are recorded.

## 8. Lifecycle

### 8.1 States

The state of a task is read from its entries. The state of a packet is
that of its latest task, plus `closed`.

```
 draft ─send─► open ─accept─► working ⇄ needs-input   (question / answer)
                 │               │
              decline          result
                 ▼               ▼
             declined      done │ failed ──close──► closed ──► archive (harvest, §14)
                                 │   ▲
                   follow-up ────┘   └── reopen
 cancel: from any state before done
```

| State | Read from | Next to act | A2A |
|---|---|---|---|
| `draft` | no `sent` | requester | |
| `open` | `sent`/`request`, not accepted | worker | `submitted` |
| `working` | `accepted`/`handoff`, no open question | worker | `working` |
| `needs-input` | an unanswered `question` | requester | `input-required` |
| `done` / `failed` | `result` with that `Outcome` (`partial` counts as done) | requester | `completed` / `failed` |
| `declined`, `cancelled` | those entries | | `rejected` / `canceled` |
| `closed` | `closed` | nobody; may reopen | |

**Sub-states of `working`** come from the run and are shown, never
stored on the card: queued, running, sleeping until, waiting on
packets or jobs, held (budget, limit, taken).

### 8.2 Moves

| Move | By | Entry | Wakes |
|---|---|---|---|
| send | requester (an agent needs approval by policy) | `sent` | worker |
| accept / decline | worker | `accepted` / `declined` | requester |
| ask / answer | worker / requester | `question` / `answer` | the other |
| hand off | current owner | `handoff` | new owner |
| result | worker | `result` | requester, and every packet waiting on it |
| follow up | requester | `request` | worker |
| freeze | current owner | `pinned` | |
| close, cancel, reopen, reply | requester | as named | worker (quietly) |

Ownership of the workspace is the last `accepted` or `handoff`. `wpk
run` on your own packet is a hand-off to `runner`; `wpk work` takes it
back. The lease enforcing it is in the run.

**The current workspace** is the `Workspace:` trailer of the last
`accepted` or `handoff` entry, resolved through the last `pinned`
entry. `work:` in the front matter is frozen at send and names the
requester's view. Every party reads the current workspace from the
thread, so after Alice accepts, her task folder is current, not your
path.

### 8.3 The executor's states

The executor keeps its own states privately in the run and moves the
card by writing entries at commit time, under the lease:

| Run (v0.2 / v0.3) | Card |
|---|---|
| `PAUSED`(setup) / `HELD(setup)` | `open`, or `draft` if never sent |
| `RUNNABLE`, `SLEEPING` | `working` with a sub-state |
| `NEEDS_INPUT` / `HELD(question)` | `needs-input`; `ask:` mirrored as `question` entries |
| `PAUSED`(owner), `FAILED`(attempts) / `HELD(taken, failed, limit)` | `working`, held; a `progress` entry says why |
| `COMPLETED` | `done` or `failed` from `report.md`'s `outcome`, as a `result` entry |

## 9. Requests between agents, and waking

1. **A step writes a card** to `.pending/out/<name>.wp.md` (title, `to`,
   brief, refs). The executor fills in `by`, `parent`, `id` and a
   budget reserved from the parent's.
2. **The memento says how to wait:** `resume: wait <name>`,
   `wait any: […]`, `wait all: […]`, or carry on.
3. **At commit, the policy decides:** send, or ask the owner.
   ```toml
   [requests]
   send = "ask"          # or "auto"
   auto_to = ["runner"]
   auto_budget = "2 USD"
   max_depth = 3
   max_open = 5
   ```
4. **Delivery** appends `sent` and hands the card to the worker: a new
   runner packet, a follow-up on a long-lived packet (`pkt:pssc`), a
   person, or a bridge.
5. **Every append checks for waiters.** A `result`, `declined` or
   `cancelled` on Q wakes every packet waiting on Q, with Q's result in
   its next prompt under "Replies". A `question` on Q wakes Q's
   requester. An agent requester may answer it, or ask its own
   requester; a person is notified once, when the chain reaches them.
   Appends are keyed, so delivery is idempotent.

Agent-made sub-packets live in `runs/<parent>/sub/`. People see them
nested under the parent, by name, and they move to `~/packets/` only
if someone asks to keep one.

## 10. Hand-off and freeze

### 10.1 What a hand-off carries

| Hand-off | Receiver has the run? | Mechanical | Written |
|---|---|---|---|
| you ⇄ your runner, same host | the same one | nothing | nothing: the memento suffices; a one-line `handoff` |
| your runner on another host | its core tier is staged (§12.3) | pins, portable refs | nothing |
| a colleague who will resume | no (§13.3) | pins, portable refs | **turnover note** |
| a request to another agent | no, and must not | the refs the brief needs, pinned | the brief |
| a report outward | no | pins, captured inputs | the result and a repro |
| close / freeze | the run will be harvested | pins | **closing summary** |

The **turnover note** is a `handoff` entry:
- Its trailers are **extracted mechanically**: `Head`, `Branch`,
  `Dirty`, `Steps`, `Cost`, the plan and notes as `blob:` refs, and
  `Record: run:<id>@<commit>`.
- Its sections are **written**: Where it stands, Next, Tried and
  dropped, Decisions taken without asking, Environment.
- The **scribe** (§13.4) drafts it, from the plan, the notes, the last
  summaries and, for a person's stretch of work, the runs it covered.
  You accept or edit the draft. It is on by default for hand-offs to a
  person, where the project's model policy allows a model, and off on
  the same host.
- The protocol asks agents to keep "tried and dropped" and
  "decisions taken without asking" in their notes as they go, so the
  draft condenses rather than reconstructs.

Nothing is ever extracted by parsing transcripts.

### 10.2 Freeze

Freezing makes the card mean the same thing later. It appends a
`pinned` entry and changes nothing else:

| Ref | Pinned to |
|---|---|
| `git:…@branch` | a commit; unpushed work pushed to `refs/packets/…` or bundled as a blob |
| an IVPM workspace's dependencies | `packages/package-lock.json` as a blob, plus each editable dependency's commit, pushed or bundled as above (§5.2) |
| `git:~/host/path` | the remote URL at the commit |
| `file:` | `blob:sha256:…` |
| an expiring URL (CI artifacts) | a blob if kept, otherwise its `regen` |
| `pkt:<name>` | `pkt:<id>@<rev>` |
| the run | `run:<id>@<commit>` |

Freezing happens on **close** (with the closing summary), on any
**hand-off to another host, send or reply**, and on demand with
`wpk freeze`. It never copies the run into the card.

## 11. Bridges

A bridge can **create** a card, **watch** a ref, and **reply** to one.

- **GitHub** (through `gh` first, webhooks through the hub later):
  - `wpk new gh:owner/repo#41` makes a card with the issue quoted as
    data, and `origin`, `watch` and `reply` set;
  - comments arrive as `note` entries;
  - `wpk reply` drafts a comment from the result and posts it only on
    confirmation, then watches the issue;
  - `to: gh:owner/repo` files an issue;
  - a finished packet can reply to any issue (`wpk reply <name> gh:…`).
- **CI:** create a card from a failed run, attach or link its
  artifacts, reply as a check comment.
- Others (mail, dfm runs) implement the same three verbs.

## 12. Travel: copies, bundles, hosts without shared disk

### 12.1 Copies and sync

- **On one host there is one card.** Appends take a short lock,
  re-read the card, and write with an atomic rename.
- **Across hosts each party has a copy.** Syncing takes the union of
  entries; the frozen part must match, and caches are recomputed. The
  hub, when there is one, holds the reference copy.

### 12.2 Bundles

A card travels alone when its refs are reachable. Otherwise it travels
as `<name>.wp.zip`:

```
uart-overrun.wp.zip
  uart-overrun.wp.md    the card, frozen; packed refs rewritten to files/…
  files/                captured inputs, the workspace folder's contents
  blobs/<hash>          only with --with-blobs, or under the size threshold
  git/<repo>.bundle     commits the receiver can't fetch
  manifest.json         sha256 of everything, and the original ref of each copy
```

Profiles: **report** (the card plus essential inputs) and **team**
(plus the workspace folder and the plan and notes). The run is not in
any profile (§13.3). An imported packet arrives `open`, nothing runs,
and the brief is data.

### 12.3 Clusters without shared disk (Slurm)

A compute node needs network access to the git server (source), the
object store (blobs), and the hub (card entries, run upload, leases).
It also needs local scratch disk.

1. **Submit:** `wpk run <name> --on slurm` writes and submits an
   `sbatch` script from the host profile. Presigned URLs for the job's
   reads and writes expire with its time limit.
2. **Stage in** to node-local scratch: the card, the run's core tier,
   the workspace by `ivpm clone -r <commit>` and `ivpm update
   --lock-file` (§5.2), with `IVPM_CACHE` on node-local disk so
   dependencies are fetched once per node, and the blobs, each checked
   against its hash.
3. **Work:** steps commit locally.
4. **Stage out after every step commit:** commits (to a `refs/packets/`
   ref or as a bundle), entries and the step's run data to the hub,
   kept attachments to the store. A step counts as committed only once
   this lands, so a job killed at its time limit loses at most the step
   in progress.
5. **Clean:** only the node's blob cache stays. That cache is safe to
   share between jobs, because blobs are named by hash.

Leases are held by the hub with heartbeats. One step runs on one node;
a multi-node simulation is a `job:` that the step waits on.

## 13. The run: the active record

### 13.1 Contents

`<packet>/.work-packet/runs/<id>/` (revised 2026-10-28; was
`~/.work-packet/runs/<id>/`), today's packet directory (`docs/spec.md`
v0.2) re-homed and keyed by id:

| Path | Holds |
|---|---|
| `journal.jsonl` | the executor's append-only record |
| `status.md`, `memento.md` | the executor's state; the next instruction |
| `state/` | the plan, notes (including tried and dropped, decisions), `env.md` |
| `steps/NNNN/` | per step: summary, diffs, report, deliverables snapshot, `meta.json` (worker, tokens, cost, timing), transcript. A person's stretch of work is a step too, with `worker: person`, no transcript, and the runs it covered (§13.4) |
| `tasks/NNNN/` | per task: instruction, final plan and report (`docs/history.md`) |
| `jobs/<id>/` | jobs and runs: `job.json` (command, directory, workspace heads, start, end, exit, batch job id), `log`, `progress.jsonl`, `graph.json`, `summary.md` (the scribe's) |
| `report.draft.md` | a report drafted by the scribe, waiting for the person to accept, edit or discard it |
| `mailbox/`, `.lease`, `.pending/` | control |
| `sub/<name>.wp.md` | agent-made sub-packets' cards |
| `.git/` | the private repo: one commit per step of the record's own files, so any step's plan and notes can be read as they were |

### 13.2 Metrics as steps commit

Each step commit also writes the step's metrics row to the history
database, marked provisional. Then `wpk stats` and the token dashboard
read one source for active and harvested work alike.

### 13.3 The run never travels

Now that the run lives inside the packet folder (revised 2026-10-28),
anything that copies, bundles or hands off a packet folder excludes
`.work-packet/`; the card carries the pins.

- **To a colleague,** what they need comes as the turnover note and
  the plan and notes as blobs.
- **To your own runner on another host,** the core tier is staged for
  execution (§12.3), and the steps it runs are uploaded back. That is
  the same server's run, carried out elsewhere.
- **To another agent,** nothing goes. A run can hold other repos'
  paths, secrets in tool output, and costs.

### 13.4 Work done by people: sessions, runs and the scribe

Not all work is done by agents. A person works in a terminal on the
packet, starts a two-hour sim, and hides the tab (`docs/work-sessions.md`).
That work belongs in the same record, and the same history, as an
agent's:

- **Runs.** A command in a packet's terminal that lasts longer than
  `run_min_s` is recorded as a **run**: a job that started in a
  terminal, under `jobs/<id>/`. A submitted farm job (`sbatch`, `bsub`)
  is followed until the batch job ends. Tools that speak the progress
  protocol report through `$WPK_PROGRESS`.
- **Routing.** A run goes to the packet whose workspace holds its
  working directory, found as in §6.6: a card, a `.packet` pointer,
  `$GIT_DIR/packet`, or a workspace folder `~/packets/<name>/`. If none
  is found, it goes to the session's packet.
- **The scribe** is a short model call with no tools, given a bounded
  extract (log head, tail and error lines; diffstats; `state/`
  changes). It writes what people skip:
  - a run's summary;
  - a step with `worker: person` when a stretch of work ends;
  - a draft report, at hand-off or finish;
  - the turnover note and the closing summary (§10).
- **The scribe drafts; people author.** The scribe never writes a card
  entry. A draft becomes an entry (a `result`, a `handoff`, a `closed`)
  only when the person accepts it. The entry is then theirs, with a
  `Drafted-By: scribe` trailer. This keeps one author per entry
  (§3 rule 3).
- **It records, it does not act.** It never writes to the workspace,
  takes no lease, and starts nothing. Each call is journaled with its
  cost, which counts in the packet's metrics.
- **Model policy.** The scribe uses the project's model and harness.
  A project whose data may not go to an outside model gets a local
  model or no scribe. When there is no scribe, the person writes the
  note, with the mechanical trailers already filled in.
- **What reaches the card.** A run never appears in the thread by
  itself, since it is provenance. A finished run nobody has looked at
  puts its packet under **Needs you** on the home screen. A run that
  matters to the requester reaches them through the person's next
  `progress` or `result` entry, with the run as a `job:` ref.
- **Terminal sessions** are control: they are kept alive while active
  and reaped when idle, but never harvested. What is kept of them is
  their runs' logs.

## 14. Harvest and the history store

### 14.1 When

A packet's run is harvested when the packet leaves the board:
- after `close` and archiving (14 days by default, or at once);
- when it is discarded (its metrics are still kept);
- for sub-packets, with their root;
- **for your part of the run, when you hand the packet to another
  person.** You will run no more steps on it, so its detail is final.
  The card stays on your board as "with alice" until it closes, and its
  `Record:` points to your history store.

Only `wpk purge` removes a packet without trace, and it asks first.

### 14.2 How

Each step can be repeated if a harvest stops part-way.

1. Freeze the card.
2. Write the archive `history/<yyyy>/<mm>/<id>.wph`.
3. Load the archive into the database in one transaction.
4. Check the database's totals against the run.
5. Remove the run directory.

The card's `Record:` now resolves to the history store.

```
<id>.wph (zip)
  manifest.json     ids, card hash, the run's final commit, blob hashes and their tiers
  card.wp.md        the frozen card
  metrics.jsonl     per step, per task, per packet
  narrative.jsonl   blob hashes of summaries, plans, notes, reports, instructions
```

The archives are the truth; the database is built from them
(`wpk history rebuild`). Backup means copying `history/` and the blob
store.

### 14.3 Tiers and retention

| Tier | Contents | Kept (default; per host) |
|---|---|---|
| metrics | per step: worker (agent or person), tokens by kind, cost, durations, model, harness, profile, attempts, outcomes, tool cost; per run or job: command, exit, duration, batch job id, final progress; scribe calls and their cost; question waits; the sub-packet tree | for good |
| narrative | summaries, plans and notes per step, instructions, reports | for good |
| changes | per-step diffs | 1 year |
| transcripts | full transcripts and stderr | 90 days; `--keep` per packet |
| logs | run and job logs, `progress.jsonl` (the final progress and the graph are narrative) | 90 days, as transcripts; `--keep` per run |

Expiry removes blobs, never rows or archives. A view of expired data
says what expired and when.

### 14.4 The database

SQLite (WAL, versioned schema) by default; Postgres for a team hub.
Tables: `packet`, `task`, `step`, `tool_cost`, `question`, `edge`,
`tag` (`run-history.md` §4), plus `job` (packet, step, command,
directory, start, end, exit, batch job id, scheduler, `log_blob`,
`summary_blob`) and `call` (scribe and other model calls outside steps:
packet, kind, model, tokens, cost).

### 14.5 Packets that moved between servers

Each server keeps the segment of the run it executed. The card's
`handoff` and `pinned` entries carry `Record:` with the host, so views
can stitch the segments together. By default the hub collects nothing;
teams may opt in to sharing the metrics tier only.

### 14.6 Reopening

A reopened packet gets a new run seeded with the last plan and notes
(from narrative blobs) and a memento rebuilt from the closing summary.
Step numbers continue, and views join the history and the new run.

## 15. Seeing it: one view model, three surfaces

### 15.1 The view model

`dash/data.py` becomes `work_packet/view/`, the only reader for every
surface. It has two backends, active runs and the history store, and
returns dicts that are also the `--json` output.

```
 cards, index ─┐                               ┌─► web dashboard
 active runs ──┼─► view/ ─► dicts (= --json) ──┼─► CLI
 history store ┘                               └─► TUI (wpk browse)
```

### 15.2 Points in history

`<target>@s7` (step 7), `@t2` (task 2), `@-1`, `@<time>`. Every surface
accepts the same form, including dashboard URLs. "As of a step" means:
- that step's summary and diff;
- the plan and notes from the run's private repo (or from narrative
  blobs once harvested);
- the report as it stood;
- the card's entries up to that time.

### 15.3 Surfaces

| | CLI | TUI `wpk browse` | Web |
|---|---|---|---|
| home, lists, filters | `wpk`, `wpk ls state:needs-input tag:uart` | left pane | board, inbox |
| a packet's thread | `wpk show` | Thread tab | packet page |
| step through history | `wpk log`, `wpk step @s4`, `wpk diff @s4 @s9` | Record tab: `[` `]` per step, `{` `}` per task, as-of views | step timeline, `@rev` URLs |
| reports, plans, transcripts | `wpk report`, `--transcript` | `o`, `p`, `x` | tabs |
| act: answer, run, note, work | ✓ | `a`, `R`, `n`, `W` | ✓ |
| live | `wpk watch` | ✓ | ✓ |
| over ssh, no browser | ✓ | ✓ | |
| share, phone, comments, charts | | | ✓ |
| search across history | `wpk history <filters>` | `/` | ✓ |

The TUI uses Textual, from the existing `tui` extra. The CLI renders
Markdown with Rich when it is present and as plain text otherwise.
Long output goes through `$PAGER`. Layouts are sketched in
`packet-views.md` §5.

### 15.4 The verbs people use

`wpk` (home), `new`, `ask`, `run`, `work`, `answer`, `show`/`open`,
`done`, `send`/`get`/`reply`, `note`, `attach`, `freeze`, plus
`browse`, `log`, `history`. Each takes a name, a prefix, `.` or `-`.
The journeys for every way of starting a packet are in
`packet-card.md` §10.3.

## 16. Safety and privacy

- **Data, not instructions.** Received briefs, other parties' entries
  and bridge text are shown to workers as quoted data. They become an
  instruction only through an `accepted` entry written by the owner or
  by policy. Bridge text is never an instruction, even in an accepted
  card.
- **Permissions never travel.** Budgets, profiles and tool grants are
  host configuration. Budgets nest: a sub-packet's is reserved from its
  parent's.
- **No loops:** a request whose `parent` chain already holds its worker
  is refused, as is one past `max_depth`.
- **Outward-facing actions need confirmation:** `reply`, filing
  issues, sending to people outside the host.
- **Model policy covers everything drafted.** The scribe, the
  turnover note and the closing summary use only the model the
  project allows, and send it a bounded extract, never whole logs or
  shell history unless the project opts in.
- **The run stays home** (§13.3). Transcripts and run logs are the first things
  expired. Credential patterns are redacted at harvest (open: H2).
- **Credentials** live in host configuration and CI secrets. Others get
  presigned URLs that expire.
- **Integrity:** blobs are checked against their hash, bundles carry a
  sha256 manifest, and the frozen brief carries its hash.

## 17. What this replaces, and migration

| Document | Status after this design |
|---|---|
| `packet-format.md` (draft 0) | Superseded on layout: the packet is a card, not a directory. Gone: the `.packet/` in-place directory, the packet directory as a git repo, split and tombstones. Kept: levels, as a guide for implementers (L0 a card with a thread; L1 a run; L2 bundles, bridges and blobs; L3 jobs) |
| `packet-shapes.md` | `PACKET.md` becomes the card, at the top of the task folder `~/packets/<name>/`, which holds the workspace (§5.1). Its "attached" shape is now the exception (`wpk new --here`). Kept: bindings, landing, shadow repos, integration of children, remote runners, pointers for attached clones |
| `packet-ux.md`, `ergonomics.md` | Verbs carried over. `ask` now makes a question packet; `status` becomes `show` and the home screen; `reply`, `attach`, `freeze` and `browse` are added |
| `concepts.md` | Packet = a card and its thread; task = one request→result; spawned children are sub-packets, shown nested |
| `delegation.md`, `interaction.md`, `completion-report.md` | Requests are cards. Questions, answers and results are mirrored as entries. `wait` is added |
| `history.md` | `tasks/NNNN/` is kept in the run (§13.1) |
| `spec.md` v0.2 | The packet directory becomes the run, under `runs/<id>/`; new ids are ULIDs and UUIDs stay valid |
| `token-dashboard.md`, `stats.py` | Read the history database (§13.2) |
| `work-sessions.md` | Kept as the plan for sessions, runs and the scribe. Its runs and person-steps are part of the run (§13.4). Its routing uses §6.6 discovery, and its scribe is the one mechanism that drafts turnover notes and closing summaries |

**Migration** is planned in detail, project by project, in
`docs/migration-v1.md`: first securing the commits that exist only on
local `wpk/*` branches (M0), then adopting the projects without moving
anything (M1), moving the one active packet to a task folder (M2),
harvesting the finished ones (M3) and tidying up (M4). In outline, `wpk migrate` does this for each registered project:
1. Write a card from the root packet:
   - title from `prompt.md`, `work` from `[setup]`;
   - a `sent` entry for the first instruction and a `request` per
     later batch (from the journal's `handoff` records);
   - a `result` per completed batch (from `state/history/report-<n>.md`).
2. Link the packet directory as its run.
3. Backfill metrics rows from `steps/*/meta.json`.

A dry run prints what it would do, so it can be checked against
`~/work-packet-runs/`.

## 18. Phased plan

Each phase is usable on its own and is tried on real work before the
next one starts.

| Phase | Builds | Done when |
|---|---|---|
| **P1 Card** | `card.py` (parse, append, merge, state); JSON Schema and test vectors; `wpk check` for cards; `~/packets/` and `index.db`; `wpk`, `new`, `ask`, `show`, name resolution | a question and a hand-written CI card round-trip through parse and render and show on the home screen |
| **P2 Run binding** | the clone is the packet; `wpk new --here` / `<repo>` through `ivpm clone` (§5.1–§5.2); the run under `<packet>/.work-packet/runs/<id>/`; `wpk convert`; plan in `docs/run-binding-v1.md`; the executor writes `accepted`/`question`/`progress`/`result` entries; ownership as `handoff`; `wpk migrate` | an existing project, migrated, runs a follow-up task with the card updating live |
| **P3 View model** | `dash/data.py` → `view/`; `@rev`; the private repo commit per step; CLI `log`, `step`, `report`, `diff`, `--json` | the dashboard is unchanged on top of `view/`; `wpk step x@s4` shows the plan as it was |
| **P4 Requests** | `.pending/out/`, policy, delivery on append, `wait`, waking, sub-packets | the pss-registers → pssc request runs end to end with a wake |
| **P5 Blobs** | the store interface; directory and S3 backends (R2 and on-prem documented); `attach`, lazy fetch, retention | a CI card with waves attached is fetched on demand on another host |
| **P6 Hand-off and freeze** | portable refs, `pinned`, the turnover note drafted by the scribe (`work-sessions.md` stage 6 first), bundles, `send`/`get` | a packet goes to a second machine with no shared disk and resumes from the card and the bundle |
| **P7 History** | `.wph` archives, the database (with `job` and `call`), harvest, provisional metrics, the history backend, `wpk history`, `stats` on the database | the existing runs are harvested and deleted, and stats and the dashboard show the same numbers as before |
| **P8 TUI** | `wpk browse`: read-only first, then actions and live refresh | a week of daily use without opening the dashboard for history |
| **P9 GitHub bridge** | `new gh:…`, `reply`, `watch` | a real fw-* issue worked, answered and followed up |
| **P10 Slurm** | staging, upload landing, hub leases | a packet runs on a cluster node with no shared disk and survives a time-limit kill |

Status, 2026-10-28: P1 done. P7 harvest done for all finished runs; the
dashboard reads the history store when a run folder is gone, and deleting
the old folders waits for the go (`docs/dash-history-v1.md` D6). P2: the
executor keeps cards and history current (E1–E4); the packet layout,
`wpk new --here` and `wpk convert` for projects without a repo are built
(stage A, `docs/run-binding-v1.md`); the card taking over the settings,
repo conversion and sibling worktrees are next.

## 19. Decisions and open questions

**Decisions this design asks you to make** (each with a recommendation):

| # | Decision | Recommendation |
|---|---|---|
| D1 | The whole thread in one file, rather than separate request and reply files | one file |
| D2 | Memento, plan and history live in the run, not where people browse | yes |
| D3 | The `.wp.md` suffix | yes |
| D4 | ULIDs for new ids | yes |
| D5 | States named to map onto A2A | yes |
| D6 | Spawned children are sub-packets (reverses a `concepts.md` rule) | yes |
| D7 | `ask` makes a question packet | yes |
| D8 | Requests need approval by default, with an `auto` policy | yes |
| D9 | The run never travels; a hand-off carries a turnover note and the plan and notes as blobs | yes |
| D10 | Harvest to archives plus a database, rather than to a database alone | yes |
| D11 | Metrics stream to the history database as steps commit (provisional) | yes |
| D12 | One scribe drafts run summaries, person-steps, draft reports, turnover notes and closing summaries; it drafts, and people author the card entries | yes |
| D13 | A task folder per packet holds the card and its workspace; attaching an existing clone is the exception | **agreed 2026-10-28** |
| D14 | IVPM is the canonical way to materialize git workspaces; per-repo rules cover editable dependencies | **agreed 2026-10-28** |
| D15 | Your part of a run is harvested when you hand the packet to another person | yes |

**Open questions** (default assumed):

| # | Question | Default |
|---|---|---|
| O1 | When to archive closed cards | `done` asks; after 14 days anyway |
| O2 | How often `progress` entries are written | at plan milestones, at most every 30 min |
| O3 | Cards committed in a team repo as the live copy | allowed; the index records the path |
| O4 | Escalating questions to a person above a budget | off; policy `escalate_over` |
| O5 | Bridges in core or as plugins | GitHub in core, others as plugins |
| O6 | Which blob backends first; CI waves stored or `regen` | directory + S3 (R2 documented); CI writes `regen` unless asked |
| O7 | Multi-node steps on Slurm | no: one node per step; multi-node runs are jobs |
| O8 | The scribe's default for turnover notes | on for hand-offs to people where the project's model policy allows; otherwise the person writes it, with trailers prefilled. (`work-sessions.md` has the scribe off by default for run summaries; the two defaults are worth deciding together) |
| H1 | Retention of diffs and transcripts | 1 year / 90 days |
| H2 | Redact credentials at harvest | yes, known patterns |
| H3 | History without a running server | `wpk` harvests into the same files |
| H5 | Delegated sub-packets on another server, in the requester's history | a row with outcome and cost, and a link |
| V1 | Bare `wpk` prints, or opens the TUI | prints; `wpk browse` is the TUI |
| V2 | Rich required | no, optional |

## 20. Glossary

| Word | Means |
|---|---|
| **packet** | a piece of work: its card and what the card names |
| **card** | the packet's file, `<name>.wp.md` |
| **brief** | the text of the ask, before the first entry |
| **thread**, **entry** | the conversation in the card; one message in it |
| **task** | one request→result exchange in a thread |
| **step** | one bounded run of a worker inside a task |
| **requester**, **worker** | the two roles in a task |
| **sub-packet** | a packet with a `parent` |
| **workspace** | the files the work is done in: usually one or more IVPM workspaces in a task folder |
| **packet folder** (was *task folder*) | the clone, or a plain folder, with the card and `.work-packet/` at its top |
| **run**, **run record** | the server's record of executing a packet: `<packet>/.work-packet/runs/<id>/` |
| **blob** | a file in a blob store, named by its sha256 |
| **turnover note** | a `handoff` entry written for a receiver who doesn't have the run |
| **run** (of a command) | a command in a packet's terminal long enough to record, kept as a job (§13.4). Not to be confused with *the run*, the run record |
| **scribe** | the short, tool-less model call that drafts summaries and notes for people to accept |
| **freeze**, **pin** | resolve the card's mutable refs to immutable ones (`pinned`) |
| **harvest** | move a finished run into the history store and remove it |
| **history store** | `.wph` archives plus the database built from them |
| **bridge** | a link to an outside system that can create, watch and reply |
| **hub** | the multi-user server, when there is one |

## Status

- 2026-10-28: P1 (card), the directory blob store and P7's history store
  built, and today's packets migrated with every statistic checked
  identical: `docs/implementation-v1.md`.
- 2026-10-28: task folders (§5.1), IVPM as the way workspaces are
  cloned (§5.2), the current-workspace rule (§8.2), harvest at hand-off
  (§14.1).
- 2026-10-27: draft 1 written for review, consolidating
  `packet-card.md`, `packet-views.md` and `run-history.md`. Nothing
  built.
