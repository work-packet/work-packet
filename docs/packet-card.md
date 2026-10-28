# Work packets: one file, a thread and a lifecycle (design, 2026-10-27)

Status: a design for review. Nothing here is built. Consolidated into
`docs/work-data-design.md`, which wins where the two differ. It takes the ideas
in `docs/packet-format.md`, `docs/packet-shapes.md`, `docs/packet-ux.md`,
`docs/ergonomics.md`, `docs/delegation.md` and `docs/concepts.md`, and
proposes one format and one lifecycle that work for people and for
agents talking to each other. §11 lists what it changes in those
documents. §12 lists the decisions that are yours to make.

## 0. In one page

**A work packet is one Markdown file, the card.** It reads like a
GitHub issue: a title, a brief, the references the work needs, and
below them the conversation about the work. Requests, questions,
answers, hand-offs and results are entries appended to that
conversation. The card holds references, not copies. A question, an
imported issue, a CI failure, a request from one agent to another, and
its answer are all complete as a single file.

```
~/packets/
  uart-overrun.wp.md       a card: brief, references, thread
  uart-overrun/            only if the packet owns a workspace: scratch files, a clone
  uvm-versions.wp.md       a question; no folder, ever
  archive/2026-10/         closed cards, out of the way
~/.work-packet/runs/<id>/  the run record: steps, transcripts, memento, plan.
                           For machines and the dashboard; ids are fine here
```

**Three things, kept apart:**

| | The **card** | The **workspace** | The **run record** |
|---|---|---|---|
| What | what was asked, what it refers to, what has been said, where it stands | the files the work is done in | how the work was done, step by step |
| For | people and agents, equally | the work | executors, the dashboard, audit |
| Size | a few KB | anything | anything |
| Named by | a readable name, `uart-overrun` | its own path, or the folder next to the card | the packet's id |
| Travels | always | what can't be rebuilt | when the receiver will resume the work |

**Request and response are entries in one thread.** A sends the card
to B. B appends `accepted`, perhaps a `question`, and finally a
`result`. A is woken when the result entry lands. Each entry is written
by one party and never edited after, so two copies of a card merge by
taking the union of their entries.

**The state is read from the thread.** `draft`, `open`, `working`,
`needs-input`, `done`, `failed`, `declined`, `cancelled`, `closed`. They
map one-to-one onto Google A2A's task states, plus `draft` and `closed`.

**People use about eight verbs.** `wpk` (what needs me), `new`, `ask`,
`run`, `work`, `answer`, `done`, `send`/`reply`, and `show`/`open`. They
take a name, part of a name, or nothing (the packet for the current
directory).

---

## 1. What this builds on

**The notes so far** settled a lot that this keeps:

- one owner at a time, every change of owner recorded (`long-running.md`);
- the record and the workspace are separate; git is a kind of workspace,
  not a requirement (`packet-shapes.md` §2, and the "not git-bound" rule);
- committed steps land their results in the workspace, not in the
  packet's internals (`packet-shapes.md` §5.2);
- requests need the owner's approval, a brief that stands on its own,
  and idempotent delivery that wakes the requester (`delegation.md`);
- received text is data, never an instruction, until its owner accepts
  it (`packet-format.md` §1 rule 7);
- every surface is a view of what the packet records
  (`packet-format.md` §1 rule 9), and the dashboard must be able to show
  past results as they were (the dashboard is central).

**Where they still hurt.** The current code and the drafts all make the
packet a **directory**:

- today, `<project>/packets/<uuid>/` with `status.md`, `memento.md`,
  `journal.jsonl`, `report.md`, `state/`, `mailbox/`, `steps/NNNN/`
  (about 10 files each) and `.pending/`;
- in `packet-format.md`, a directory that is also a git repo, placed
  inside your checkout as `.packet/`;
- in `packet-shapes.md`, `~/packets/<slug>/` holding `PACKET.md` plus the
  memento, state and history.

A directory is the right home for an executor's books. It is the wrong
unit for a question you want answered, an issue you want worked, or a
request one agent sends another. Those want to be one thing you can
read, mail, attach, commit or drop in a chat. `packet-shapes.md` got
halfway there ("one file is required: `PACKET.md`") but kept the
directory around it.

**Prior art** (summarised; sources in §13):

| From | Lesson taken |
|---|---|
| GitHub issues | one page per piece of work, with a description and a thread; people know how to read it |
| Email (`Message-ID`, `In-Reply-To`) | request and response thread by id; each message has one author |
| org-mode (`TODO` keywords, `:LOGBOOK:`) | one readable file with a state and an append-only log of changes |
| Google A2A Task | a small set of states with `input-required` as a pause, not a failure; outputs kept apart from chat |
| MCP tasks, 2026 | everything needed to resume travels in the messages, not in hidden server memory |
| Slurm `#SBATCH` | a single file that describes itself, including who to tell when it ends |
| BagIt `fetch.txt`, RO-Crate | a bundle can be mostly references, with checksums for what is copied |
| Temporal, OCI | a stable name chosen by the caller, separate from immutable ids |
| beads, git-bug | short ids and dotted children work for many writers; a log hidden in git refs does not work for people |
| Copilot coding agent | acknowledge at once, and make the result a reviewable thing linked to the request |
| Jupyter | keep bulky outputs out of the file people read |

## 2. Principles

1. **A packet is a file.** One Markdown file with front matter. You can
   read it with `cat`, write it by hand, mail it, attach it to an issue,
   commit it, or paste it into a chat with a model.
2. **References, not copies.** The card names repos at commits, files,
   issues, URLs and other packets. Copies are made only when a packet
   travels to someone who can't reach what it names (§9).
3. **The thread is the history people read.** What was asked, said and
   delivered is in the card, in order. The step-by-step record is
   elsewhere, for those who want it.
4. **Each entry has one author and is never edited.** That makes
   ownership visible, merging trivial, and the history trustworthy.
5. **Names for people, ids for machines.** People type `uart-overrun`.
   Machines key on the id. Directories named by id are only ever in
   machine areas.
6. **Location is not state.** A card does not move when its state
   changes (archiving is the one exception). Paths stay valid; the state
   is in the thread.
7. **The cold-start test.** Someone, or some agent, given only the card
   can tell what the work is, where it stands, and how to pick it up.
8. **Nothing is required beyond a filesystem** to read or write a card.
   Git, a server and the runner are optional and add reach.

## 3. The model

```
           requester                                 worker
   (a person, or an agent's packet)          (a person, the runner, an agent, a team)
                 │                                         │
                 │   ┌──────────── the card ────────────┐  │
                 └──►│ title · refs · brief             │◄─┘
                     │ ## sent       requester          │
                     │ ## accepted   worker             │
                     │ ## question   worker             │
                     │ ## answer     requester          │
                     │ ## result     worker             │
                     └──────────────────────────────────┘
                          │ names                 │ id
                          ▼                       ▼
                    the workspace           the run record
                (your clone, the folder   (~/.work-packet/runs/<id>/:
                 beside the card, none)    steps, transcripts, plan, memento)
```

- **Packet**: the card and everything it names. One piece of work with
  one subject, one thread, and at most one workspace.
- **Task**: one exchange in the thread, from a `request` (or the first
  `sent`) to its `result`. A packet that takes follow-up work gets more
  tasks, as `concepts.md` already describes; the "next batch" is a
  follow-up request entry.
- **Step**: one bounded run of a worker inside a task. Steps are in the
  run record, not in the card.
- **Requester** and **worker**: the two roles in each task. The same
  person can be both: a packet you make for yourself is to `me`, and its
  `sent` and `accepted` collapse into one action.
- **Sub-packet**: a packet whose `parent` is another packet. Requests an
  agent sends are sub-packets of the packet it is working on.

**Two namespaces.** People see `~/packets/`, cards by name. Machines
use `~/.work-packet/` (today's runner home), keyed by id. A packet an
agent makes for another agent lives in the machine area; people reach it
through `wpk` and the dashboard by name, and it is shown under its
parent. It moves into `~/packets/` only when a person asks to keep it.
This is the answer to "unique directories are fine for agents, not for
people": both exist, and they never mix.

## 4. The card

### 4.1 The file

- Name: `<name>.wp.md`. The `.wp.md` suffix lets a tool or an editor
  recognise a card anywhere (Downloads, a repo, an attachment) and still
  renders as Markdown everywhere. Inside `~/packets/` the suffix is
  still used, so a glob finds every card.
- Encoding: UTF-8 Markdown with YAML front matter, as `status.md` and
  `memento.md` are today, so `frontmatter.py` reads it.
- Three parts, in order: **front matter** (facts about the packet),
  **brief** (the text before the first entry), **thread** (entries).

The smallest valid card is a draft:

```markdown
---
title: Survey of RISC-V cache coherence verification approaches
---
Find what's published on formal vs simulation approaches, 2022 onwards.
Output: a comparison table and a reading list.
```

Tools add `packet`, `id` and `name` the first time they touch it, and
never require anything else.

### 4.2 Front matter

| Key | Meaning | Written by | Default |
|---|---|---|---|
| `packet` | format version, `1` | tools | added on first touch |
| `id` | ULID: global, sortable by time, made without coordination | tools | added on first touch; never changes |
| `name` | the handle people type, `[a-z0-9][a-z0-9-]{0,47}`, unique in its home | tools, from the title; the user may rename | from the title |
| `title` | one line | requester | required |
| `by` | the requester: a person (`matt`), or `pkt:<name>` for an agent's packet | tools | you |
| `to` | the worker it was sent to: `me`, `runner`, a person, `pkt:<name>` (a long-lived packet), a bridge (`gh:owner/repo`). Who holds it *now* is in the thread (§6.2) | requester | `me` |
| `parent` | the packet this one was made for | tools | none |
| `origin` | where it came from: an issue, a CI run, a packet | tools | none |
| `work` | the workspace: a ref (§4.3), `folder` (the folder beside the card), or `none` | requester | `none` for `ask`; `.` resolved for `new` in a directory |
| `inputs` | refs to read: files, URLs, issues, packets, runs | requester | none |
| `setup`, `repro` | one command each, in the project's own tooling (`packet-shapes.md` §3) | requester | none |
| `reply` | where results also go: `origin`, or refs | requester | none |
| `watch` | refs whose changes are posted into the thread: `origin`, or refs | requester | `origin` when made from an issue |
| `notify` | which entries to tell the requester about at once: `question`, `result`, `update` | requester | `question, result` |
| `budget` | the most the worker may spend, e.g. `5 USD` | requester | host profile |
| `due` | a date, for sorting and reminders | requester | none |
| `tags` | free words; boards are saved filters over tags | anyone | none |
| `state` | **cache** of the state read from the thread (§6) | tools | |
| `updated` | **cache** of the last entry's time | tools | |

Rules:

- **Frozen at send.** The front matter above `state`, and the brief,
  stop changing when the card is sent. The `sent` entry records their
  hash (`Brief-Sha:`). To change what you asked, append a `request`
  (a follow-up) or a `note`; `wpk check` flags a frozen part that was
  edited.
- **Caches are never trusted.** `state` and `updated` exist so `grep`
  and a file listing are useful. Any tool recomputes them from the
  thread and rewrites them.
- **Host facts never go here.** Paths of managed workspaces, leases,
  permission profiles, `step_env`, session ids and costs in progress are
  in the run record and the host profile, never on the card
  (`packet-shapes.md` §3 rule 6). A received card can't bring its own
  permissions.
- **Unknown keys are kept** and ignored. Implementations namespace
  their own: `x-wpk`, `x-dfm`.

### 4.3 References

One string per reference, `scheme:target`, with an optional `@rev` and
an optional `#sha256=…` for content pinning. Bare paths and URLs are
recognised without a scheme.

| Ref | Means | Example |
|---|---|---|
| `git:<path or URL>[@rev]` | a repository, at a branch, tag or commit | `git:~/work/fw-uart16550@uart-overrun`, `git:https://github.com/featherweight-ip/fw-uart16550@3f0c9a2` |
| `file:<path or glob>` | a file or files | `file:rtl/*.sv`, `file:~/scratch/trace.log#sha256=9c1e…` |
| `dir:<path>` | a folder, read in place | `dir:/proj/sims/run42` (a shared path) |
| `gh:<owner>/<repo>#<n>` | an issue or pull request | `gh:featherweight-ip/fw-uart16550#41` |
| `https://…` | anything on the web, e.g. CI artifacts | `https://ci.example/run/8812/waves.fst` |
| `pkt:<name or id>` | another packet | `pkt:fifo-depth` |
| `run:<id>[/step]` | a run record, or one step of it | `run:01JBF3K8/0007` |
| `job:<id>` | a long-running job (`work-sessions.md`) | `job:dfm-1142` |
| `blob:sha256:<hash>` | an attachment in a blob store, by content (§9.1) | `blob:sha256:9c1e4a…` |

- Relative paths are relative to the card's folder, so a card committed
  in a repo can name the repo's files. Tools write paths under `$HOME`
  as `~/…`.
- A ref says *where*, not *what for*. The key it is listed under says
  what for (`work`, `inputs`, `origin`, `reply`, `watch`).
- A ref that can't be resolved is shown as such (`wpk show` marks it),
  never silently dropped.

### 4.4 The thread

An entry starts with a level-2 heading in a fixed form, and runs to the
next entry heading:

```
## <kind>[ <arg>] · <who> · <YYYY-MM-DD HH:MM:SSZ>
```

The body is free Markdown. Headings inside a body are level 3 or
deeper; tools demote any that aren't. An entry may end with
**trailers**, `Key: value` lines after a blank line, the same form as
git trailers and as the `Packet-*` trailers in `packet-format.md` §2.4.
Models write trailers reliably; they don't write JSONL reliably.

The key of an entry is its (time, who, kind). Two copies of a card merge
by taking the union of their entries, sorted by time.

**Entry kinds:**

| Kind | Written by | Means | Trailers |
|---|---|---|---|
| `sent` | requester | the brief is frozen and handed to `to` | `Brief-Sha`, `Budget` |
| `request` | requester | a follow-up task on the same packet | `Budget` |
| `accepted` | worker | taken on; the body says where and how | `Workspace` (a ref) |
| `declined` | worker | won't do it, and why | |
| `question <id>` | worker | needs an answer to go on | `Recommend`, `Choices`, `Grants` (as `interaction.md`) |
| `answer <id>` | requester | the answer | |
| `note` | anyone, or a bridge | information; changes no state | `Source` (e.g. a GitHub comment URL) |
| `handoff` | the current owner | ownership moves; the body is where things stand and what's next | `To` |
| `progress` | worker | an occasional milestone, not every step | `Step`, `Cost` |
| `result` | worker | the task is finished | `Outcome` (`done`, `failed`, `partial`), `Deliverable` (repeatable, a ref plus a few words), `Cost`, `Record` |
| `cancelled` | requester | stop | |
| `closed` | requester | the result is accepted; nothing more is expected | |
| `replied` | requester | the result was posted to a `reply` target | `Posted` |
| `reopened` | requester | a closed packet takes work again | |
| `pinned` | the current owner | a freeze: every mutable ref resolved to an immutable one as of now (§6.5) | `Pin` (repeatable: `<ref> = <immutable ref>`), `Record` |

The thread is for what the other party needs to know. Steps, tool
calls, transcripts and plans stay in the run record. A runner writes a
`progress` entry at most every few steps, or at a plan milestone.

### 4.5 A full card

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
  - https://ci.example/run/8812/waves.fst
  - file:notes/lsr-timing.md
repro: dfm run uart.test_overrun
reply: origin
watch: origin
budget: 5 USD
state: done
updated: 2026-10-27 11:40:12Z
---
test_overrun fails at 41/67: the RX overrun flag stays set after LSR is
read. Seen on main at 3f0c9a2. Expected: OE clears on the LSR read
(spec §8.4).

### Done when
`dfm run uart.test_overrun` passes, and the full suite still passes.

## sent · matt · 2026-10-27 09:12:03Z

Brief-Sha: 4be1c0
Budget: 5 USD

## accepted · runner · 2026-10-27 09:12:40Z

Working in your clone on branch uart-overrun.

Workspace: git:~/work/fw-uart16550@uart-overrun

## question q1 · runner · 2026-10-27 10:02:51Z

§8.4 says OE clears "on read of LSR". The RTL also gates it on the FIFO
being empty. Clear on every read, or only when the FIFO is empty?

Recommend: on every read
Choices: on every read | only when empty

## answer q1 · matt · 2026-10-27 10:30:17Z

On every read.

## result · runner · 2026-10-27 11:40:12Z

OE now clears on every LSR read (`uart_regs.sv`). Added a directed test
for read-while-full. 67/67 pass.

Outcome: done
Deliverable: git:~/work/fw-uart16550@a1b2c3d the fix and the test
Deliverable: gh:featherweight-ip/fw-uart16550#52 pull request
Cost: 1.84 USD
Record: run:01JBF3K8Q2V7N0WZ3T5Y6R9M4C
```

Rendered, that is an issue page. `grep -l 'state: needs-input'
~/packets/*.wp.md` works.

### 4.6 More cards, smaller

**A question.** No workspace, no folder, no setup.

```markdown
---
title: Which UVM versions does the pssc runtime support?
to: runner
work: none
---
Check pssc's docs and CI matrix. One paragraph, with links.
```

**A collection of files.**

```markdown
---
title: Review the AXI write-path changes
to: alice
inputs:
  - file:~/work/fw-axi/rtl/axi_wr_*.sv
  - file:~/work/fw-axi/docs/axi-wr.md
  - file:~/Downloads/axi-spec-excerpt.pdf#sha256=77ad…
---
Look for ordering bugs between AW and W. Comments as a note per file.
```

**A request from one agent to another**, written by the requester's step
(`parent` and `by` are filled in by the tools):

```markdown
---
title: Lower reg_c register access in pssc sv-native
to: pkt:pssc
parent: pss-registers-up-planning
inputs:
  - git:~/projects/pssc@main
budget: 3 USD
---
### Task
`pssc sv-native` emits no access methods for `reg_c` (a register with a
`reg_c` component type). Add them.

### Reproduce
`pssc sv-native tests/regs/reg_c.pss` prints no `reg_c_read`.

### Done when
The output has `reg_c_read`/`reg_c_write`, and pssc's tests pass.
```

**A failing test from CI**, written by a few lines of shell and
uploaded as a build artifact:

```markdown
---
title: test_overrun fails on main
origin: https://ci.example/run/8812
work: git:https://github.com/featherweight-ip/fw-uart16550@3f0c9a2
setup: ivpm update
repro: dfm run uart.test_overrun
inputs:
  - https://ci.example/run/8812/sim.log
  - https://ci.example/run/8812/waves.fst
---
41/67: `OE still set after LSR read` at 1.2 ms.
```

### 4.7 Reading it mechanically

Markdown is a problem for tools only when data hides in prose. The rule
that prevents it: **data lives in two places, the front matter and
entry trailers. Prose is never parsed.** The brief and entry bodies are
for people and models; a tool may show them, never mine them.

**The grammar is small and strict:**

| Part | Grammar | Read with |
|---|---|---|
| front matter | YAML between `---` lines; scalars, lists, and one level of maps (the long form of a ref) | `frontmatter.py`'s loader, which already keeps timestamps as strings; values are then typed by a schema, so `no` never becomes `false` |
| entry headings | `^## (\w[\w-]*)(?: (\S+))? · (.+?) · (\d{4}-\d\d-\d\d \d\d:\d\d:\d\dZ)$`, outside fenced code blocks | a line scanner that tracks fences; no Markdown library needed |
| trailers | the entry's last paragraph, every line `Key: value`, keys `[A-Z][A-Za-z-]*`, repeatable | the same rules as `git interpret-trailers` |
| values | typed per key: `Outcome` an enum, `Cost` an amount and a currency, `Deliverable` a ref and words, times UTC with `Z` | the schema |

**One canonical JSON form.** `card.parse()` and `wpk show --json` give
the same structure, and every tool works from it, never from the text:

```json
{"packet": 1, "id": "01JBF3K8…", "name": "uart-overrun",
 "front": {"title": "…", "to": "runner", "work": "git:~/work/fw-uart16550@uart-overrun", "…": "…"},
 "brief": "test_overrun fails at 41/67 …",
 "entries": [
   {"kind": "question", "arg": "q1", "who": "runner", "at": "2026-10-27T10:02:51Z",
    "body": "§8.4 says …", "trailers": {"Recommend": ["on every read"], "Choices": ["…"]}}],
 "state": "done",
 "problems": []}
```

A JSON Schema for this form ships with the format, and the test vectors
are pairs of a card and its JSON.

**Lenient to read, strict to write.**
- The reader never fails on a card. What it can't parse (a heading
  that doesn't match, a bad trailer) stays in the body of the entry
  before it and is listed in `problems`.
- The writer (`card.append()`) is the only way tools change a card,
  and it writes the canonical form. A tool-written card survives
  parse → JSON → render byte for byte; bodies are kept as raw text.
- `wpk check` is strict and reports every problem, for hand-written
  cards and for CI.
- People edit the brief by hand before sending, and may type an entry
  by hand. Anything else they want to say, they say with `wpk note`.

**Numbers come from the run record, not from cards.** Cost, tokens,
durations and step counts are in `meta.json` and `journal.jsonl`, which
are JSON. The `Cost:` trailer on a result is a summary copied from
there, for people. Statistics (`wpk stats`, the token dashboard) read
the record and never scrape cards.

**The index makes it fast.** `~/.work-packet/index.db` (SQLite, from
the standard library) holds each card's JSON form and its record's
summary, keyed by id, and is refreshed when a card's size or mtime
changes. `wpk ls`, the home screen and the dashboard query it. It is a
cache: deleting it costs one scan.

## 5. Where packets live, and how they are named

### 5.1 Homes

| Where | What | Who looks there |
|---|---|---|
| `~/packets/<name>.wp.md` | cards you made or that came to you | you |
| `~/packets/<name>/` | the packet's own workspace, when it has one: scratch files (`work: folder`), collected copies, or a clone the runner made for a packet created from a URL | you, `wpk cd`, the IDE |
| `~/packets/archive/<yyyy-mm>/` | closed cards (and their folders), moved by `wpk done` or after N days | rarely |
| anywhere else | a card you keep in a repo, a share or Downloads; `wpk` finds it through the index, or `wpk get <path>` adds it | you |
| `~/.work-packet/runs/<id>/` | the run record: `journal.jsonl`, `steps/`, `tasks/`, `memento.md`, `state/` (plan, notes), `mailbox/`, `.lease`, `.pending/`, and `sub/<name>.wp.md` for sub-packets made by agents | the runner, the dashboard |
| `~/.work-packet/index` | a cache: id → card path, name, state, last seen by you | tools; rebuilt by a scan |
| `~/.work-packet/history/` | the history store: execution detail of packets that have left the board, as an archive per packet plus a database (`docs/run-history.md`) | the dashboard, `wpk stats`, `wpk history` |

Workspaces you already have stay where they are. A packet attached to
your clone gets no folder; its card names the clone in `work:`, and the
clone gets the pointer from `packet-shapes.md` §4 (`$GIT_DIR/packet`, or
a one-line `.packet` file in a plain folder) so that `wpk` in the clone
knows its packet.

The folder beside the card holds only the **work**. It never holds the
executor's books. That is the change from `packet-shapes.md`, which put
the memento, state and history in `~/packets/<slug>/`: those are the run
record now, in the machine area, and what a person needs from them comes
into the card as `handoff` and `result` entries.

### 5.2 Names and addresses

- **Name**: made from the title (the first three or four significant
  words), unique in its home; a clash gets `-2`. `wpk mv` renames, and
  the id stays.
- **Sub-packets** are shown as `parent.child`: `uart-overrun.seed17`.
  The child's own name is `seed17`; the dotted form is how it is
  addressed and displayed.
- **What commands accept**, tried in order:
  1. a name, or a unique prefix of one (`uart` → `uart-overrun`);
  2. `.` or nothing: the packet of the current directory (walk up for a
     card, a `.packet` pointer or `$GIT_DIR/packet`);
  3. `-`: the packet you last acted on, as `cd -`;
  4. a path to a card;
  5. an id, or a long enough prefix of its random part.
- **Across people and hosts**: `<home>/<name>` (`matt/uart-overrun`),
  as GitHub writes `owner/repo`, or the hub URL
  (`https://hub/matt/uart-overrun`). The id is what the hub keys on, so
  a rename doesn't break a link.
- **A point in its history**: `<name>@<rev>`, as git does. `@s7` is
  step 7, `@t2` is task 2 (its end), `@-1` the step before the last,
  `@2026-10-27T10:00` the last step before that time. Every viewer
  accepts it (`docs/packet-views.md` §3).

Short numbers (`#12`) were considered. They need a single numbering
authority, which a file-first, server-optional design doesn't have.
Names plus prefixes cover the same need.

## 6. Lifecycle

### 6.1 States

The state of a task is read from its entries; the state of a packet is
the state of its latest task, plus `closed`.

```
              wpk new                       to: me collapses sent + accepted
                 │
                 ▼
              draft ── send ──► open ── accept ──► working ◄─────────┐
                 │                │                  │  │            │
                 │             decline          ask  │  │ handoff    │
                 │                ▼                  │  │ (owner     │
                 │            declined               ▼  │  changes)  │
                 │                         needs-input ─┴─ answer ───┘
                 │                                   │
                 │                          result   │
                 │                   ┌───────────────┴───────────┐
                 │                   ▼                           ▼
                 │                 done                        failed
                 │                   │  ▲                        │
                 │       follow-up   │  │ follow-up / reopen     │
                 │       request ────┼──┘ (back to open)         │
                 │                   ▼                           │
                 │                 closed ◄──────────────────────┘
                 │                   │
   cancel from any state before done │ after N days, or wpk done
                 ▼                   ▼
             cancelled          archive/
```

| State | Read from | Who acts next | A2A name |
|---|---|---|---|
| `draft` | no `sent` | requester | (none) |
| `open` | `sent` or `request`, not yet `accepted` | worker | `submitted` |
| `working` | `accepted` or `handoff` after the last request; no open question | worker | `working` |
| `needs-input` | a `question` with no `answer` | requester | `input-required` |
| `done` | `result` with `Outcome: done` or `partial` | requester (close, follow up, reply) | `completed` |
| `failed` | `result` with `Outcome: failed` | requester | `failed` |
| `declined` | `declined` | requester | `rejected` |
| `cancelled` | `cancelled` | nobody | `canceled` |
| `closed` | `closed` after a result | nobody; `reopen` is allowed | (none) |

`working` has **sub-states** that are not lifecycle states and never
appear in the card's `state:`. They come from the run record:
`queued`, `running`, `sleeping until 14:00`, `waiting on 2 packets`,
`waiting on job dfm-1142`, `held: budget`. Surfaces show them after the
state: `working · waiting on pssc-reg-lowering`.

### 6.2 Who may do what

| Move | By | Entry | Precondition | Wakes / notifies |
|---|---|---|---|---|
| send | requester | `sent` | a title and a brief; with an agent requester, the owner's approval unless the host policy allows it (§7.3) | the worker |
| accept | worker | `accepted` | the worker can resolve `work` and `inputs`, or will fetch them | the requester, quietly (no notification) |
| decline | worker | `declined` | | the requester |
| ask | worker | `question <id>` | | the requester (§7.2) |
| answer | requester | `answer <id>` | an open question | the worker |
| note | anyone | `note` | | the worker if working; the requester's "Updated" otherwise |
| hand off | current owner | `handoff` | the body says where things stand and what's next | the new owner |
| result | worker | `result` | `Outcome`; deliverables that exist (`completion-report.md`) | the requester |
| follow up | requester | `request` | `done`, `failed` or `closed` | the worker |
| reply | requester | `replied` | a `reply` target, and your confirmation (it is outward-facing) | |
| close | requester | `closed` | `done`, `failed` or `declined` | the worker, quietly |
| cancel | requester | `cancelled` | not `done`/`closed` | the worker, which stops at the end of its current step |

**Ownership is in the thread.** Who owns the workspace at any moment is
the last `accepted` or `handoff`. `wpk run` on your own packet is a
`handoff` to `runner`; `wpk work` takes it back with a `handoff` to
`me`, after the runner's current step. This is `long-running.md`'s
ownership rule, recorded where people can read it. The lease that
enforces it stays in the run record.

**One worker per task.** A worker that wants help sends sub-packets; it
does not add workers to its own task.

### 6.3 How this maps to the executor

The executor's states (today's `status.md`) stay. They are the worker's
private view, in the run record, and they set the card's state through
entries:

| Run record state (v0.2) | v0.3 (`long-running.md`) | Card |
|---|---|---|
| `PAUSED` (reason `setup`, or a request not yet handed off) | `HELD(setup)` | `open`, or `draft` if it was never sent |
| `RUNNABLE`, `SLEEPING` | `RUNNABLE`, `SLEEPING` | `working`, sub-state from the run record |
| `NEEDS_INPUT` | `HELD(question)` | `needs-input`; the memento's `ask:` is mirrored as `question` entries |
| `PAUSED` (by the owner), `FAILED` (attempts used up) | `HELD(taken / failed / limit)` | `working` with a `held` sub-state; a `progress` entry says why. `failed` on the card is a result, decided by the worker, not a crashed step |
| `COMPLETED` | `COMPLETED` | `done` or `failed`, from `report.md`'s `outcome`, as a `result` entry |

The executor writes the entries at commit time, under the lease, as
part of `_apply`: a question becomes a `question` entry, a completion
becomes a `result` entry with `report.md`'s outcome and deliverables as
trailers. `report.md` stays in the run record as the long form; the
card gets its first paragraph and the deliverables.

### 6.4 What lives where, and what crosses at a hand-off

Six kinds of information, and where each lives:

| Kind | Examples | Card | Run record (the private repo) |
|---|---|---|---|
| **The ask** | title, brief, refs, budget | ✓ (the only copy) | |
| **The conversation** | questions and answers, notes, follow-ups | ✓ (the only copy) | the journal mirrors it |
| **Outcomes** | result, deliverables, total cost | ✓ summarised | `report.md`, `deliverables/` in full |
| **Working knowledge** | the plan; notes; what was tried and dropped, and why; decisions taken without asking; what was learned about the environment (how to build, which seed, a tool quirk) | **distilled, at hand-off and freeze** | ✓ live, in `state/`, changing every step |
| **Provenance** | steps, diffs, transcripts, per-step cost and tokens, timings | refs only (`Record: run:<id>@<commit>`) | ✓ (the only copy) |
| **Control** | lease, `.pending/`, mailbox, scheduler state, session ids, host paths, budgets in progress | never | ✓ (never travels) |

So the answer to "does a hand-off need anything from the record?"
depends on whether the receiver gets the record:

| Hand-off | Receiver has the record? | Mechanical extraction | Written distillation |
|---|---|---|---|
| you ⇄ the runner, same host | yes, the same one | none | none: the memento is enough. A one-line `handoff` entry |
| to the runner on another host (farm, Slurm) | yes: the core tier travels (§9.2) | **required**: pins (§6.5), portable refs | none beyond the memento |
| to a colleague, who will resume | no: the run never travels (`work-data-design.md` §13.3); the plan and notes go as blobs | **required**: pins, portable refs | **required**: the turnover note (below) |
| a request to another agent | **no**, and must not: the record may hold other repos' paths, secrets in tool output, costs | the refs the brief needs, pinned | the brief is the distillation, written by the requester |
| a report to a vendor or maintainer | no | pins; expiring inputs captured as blobs | the result entry, and a repro |
| freeze or close | the record may later be thinned or deleted | **required**: pins (§6.5) | **required**: the closing summary (below) |

**The turnover note** is the `handoff` entry's body when the receiver
is a person, or an agent on a different record. It is what a good
engineer writes when going on leave:

```markdown
## handoff · runner · 2026-10-28 17:05:00Z

### Where it stands
OE clears on read; 66/67 pass. test_lsr_burst fails only at 2:1 clocks.

### Next
Check the CDC of `lsr_rd` into the RX domain; the pulse is one fast cycle.

### Tried and dropped
- Gating on `fifo_empty`: contradicts spec §8.4 (q1).
- Widening the pulse in the testbench: hides the bug rather than fixing it.

### Decisions taken without asking
- Kept the register map unchanged; the fix is inside `uart_regs.sv`.

### Environment
`ivpm update` first; sims need `DFM_JOBS=4` on the laptop or they swap.

To: alice
Head: git:https://github.com/featherweight-ip/fw-uart16550@9e41d07
Branch: uart-overrun
Dirty: no
Plan: blob:sha256:51ac…
Notes: blob:sha256:c2f0…
Record: run:01JBF3K8Q2V7N0WZ3T5Y6R9M4C@7d3e2a1
Steps: 11
Cost: 2.43 USD
```

- **Two halves.** The trailers are **extracted mechanically** from the
  record and the workspace: heads, branch, whether the tree is clean,
  step count, cost, and blob refs for the plan and notes as files. The
  sections are **written**: by the scribe (`work-sessions.md` §3.5; one short
  model run over the plan, the notes and the last few summaries), or by
  you, with the agent's draft in `$EDITOR`. Nothing is extracted by
  parsing transcripts.
- **Sections are a convention, not a schema** (§4.7): a tool may show
  "Next" by its heading, but never relies on it.
- **The plan and notes travel as attachments, not inline.** The card
  stays small; the receiver opens them if it needs them.
- **"Tried and dropped" and "Decisions taken without asking"** are
  the two things most often lost at a hand-off and most expensive to
  rediscover. The protocol (`prompts/protocol.md`) should ask agents to
  keep them in `state/notes/` as they go, so the scribe distils
  rather than reconstructs.
- **Same host, no note.** Handing to your own runner and taking it back
  happens many times a day. It must stay free: the memento already
  carries the next instruction, and the record is shared.

### 6.5 Freeze: making the card stand alone

A card names things that change: a branch moves, a file is edited, a
CI artifact expires after 90 days, an issue is edited, the record is
thinned when archived. **Freezing** makes the card mean the same thing
later. It appends a `pinned` entry and changes nothing else.

| Ref as written | Pinned to |
|---|---|
| `git:…@<branch>` | the same repo at a commit. Unpushed commits: pushed to a `refs/packets/…` ref if a remote allows, otherwise a git bundle as a blob |
| `git:~/work/<clone>` (a host path) | its remote URL at the commit, so the ref works on any host |
| `file:<path>` | `blob:sha256:…`, captured into the store |
| an `https://` CI artifact, or anything with an expiry | a blob, if it is kept (§9.1); otherwise pinned with its `regen` |
| `gh:owner/repo#41` | the same, plus the time it was read; the issue's text as it was is captured as a blob only for a report |
| `pkt:<name>` | `pkt:<id>@<rev>` |
| the run record | `run:<id>@<commit>` of its private repo, so a retained record can be found as it was |

```markdown
## pinned · matt · 2026-10-28 18:00:00Z

Pin: git:~/work/fw-uart16550@uart-overrun = git:https://github.com/featherweight-ip/fw-uart16550@9e41d07
Pin: file:notes/lsr-timing.md = blob:sha256:e09b…
Pin: https://ci.example/run/8812/waves.fst = blob:sha256:9c1e…
Record: run:01JBF3K8Q2V7N0WZ3T5Y6R9M4C@7d3e2a1
```

When freezing happens:
- **Always, as part of `close`**, and before a card is archived. The
  close also asks for (or drafts) a **closing summary** in the `closed`
  entry: the outcome in two lines, the decisions that matter to anyone
  touching this code again, and what was learned that should outlive
  the packet. That summary is what remains useful once transcripts are
  gone.
- **At any cross-host hand-off, send and reply**, since the receiver
  can't resolve host paths.
- **On demand:** `wpk freeze <name>`, for example before citing a packet
  in an issue or a review, so the link keeps meaning what it meant.

A frozen card is still a card: work can carry on, and later entries
simply come after the pins. `name@t1` (a task's end) resolves through
the last `pinned` entry before it, when there is one.

**What freezing does not do** is copy the record into the card.
Provenance stays in the record, and the card points at the exact
version of it. What happens to the record afterwards (kept, thinned to
its core tier, or deleted) is a retention policy per host, and the card
stays meaningful under all three.
The default is `docs/run-history.md`: when the packet leaves the board,
its record is harvested into the server's history store and removed.

## 7. Request and response between agents

### 7.1 Sending

An agent working on packet A (in a step, or interactively) wants work
done somewhere it may not write: another repo, another expert, a
person.

1. **The step writes a card** to `.pending/out/<name>.wp.md`, with
   `title`, `to`, the brief and the refs. The executor fills in `by`,
   `parent`, `id` and `budget` (taken from A's own budget, §7.4).
2. **The memento says how to wait:** `resume: wait pssc-reg-lowering`,
   or `wait any: [a, b]`, `wait all: [a, b]`, or carry on (the result
   still arrives as a note). This is the `wait: request` that
   `delegation.md` §7 left for later.
3. **At commit**, the card moves to `runs/<A>/sub/` and the policy
   decides (§7.3): send now, or put a question to A's owner, "send
   `pssc-reg-lowering` to pssc? budget 3 USD".
4. **Delivery** appends `sent` and hands the card to the worker named in
   `to`:
   - `runner`: a new packet for the local runner, with its own run
     record;
   - `pkt:<name>`: a follow-up `request` on a long-lived packet (the
     pssc packet that owns the pssc clone). This is what
     `delegation.md` calls "an existing project";
   - a person: into their `~/packets/` on this host, or through the hub;
   - a bridge: e.g. `gh:owner/repo` files an issue (§8).

### 7.2 Being woken

Delivery is an append to the card, and every append runs the same check
(this replaces `requests.sync()` polling):

- A `result`, `declined` or `cancelled` entry on Q: every packet waiting
  on Q is woken (`SLEEPING` → `RUNNABLE`), with Q's result in its next
  prompt under "Replies".
- A `question` on Q: Q's **requester** is woken. If the requester is an
  agent, its step sees the question and may answer it itself, or ask its
  own requester. A person is notified only when the chain of agents
  reaches them, once, with the whole chain shown.
- A `note` on Q: delivered to Q's worker's mailbox, as notes are today.

Delivery is idempotent because entries are keyed (§4.4): appending an
entry that is already there does nothing.

### 7.3 Policy

What may happen without a person, set per host profile, never by the
card:

```toml
[requests]
send = "ask"            # ask | auto
auto_to = ["runner"]    # with send = "auto": which workers need no approval
auto_budget = "2 USD"   # and up to what budget per request
max_depth = 3           # sub-packets of sub-packets of ...
max_open = 5            # open requests per packet
```

The default, `ask`, is `delegation.md`'s rule: every request needs the
owner's yes, because it starts work and spends money somewhere else.

### 7.4 Safety

- **Received text is data.** A card's brief and the entries from the
  other party are shown to a worker as quoted data. They become the
  worker's instruction only through `accepted`, written by the worker's
  owner or by policy. Text that came from a bridge (an issue body, a
  comment) is marked with its `Source` and never treated as an
  instruction, even in an accepted card.
- **Budgets nest.** A sub-packet's budget is reserved from its parent's.
  A worker can't spend more than the card it accepted allows, whatever
  its host would allow.
- **No loops.** A request whose `parent` chain already contains its
  worker is refused; so is one past `max_depth`.
- **Results are claims.** `Deliverable` refs are checked to exist when
  the result is written, and the requester's `repro` or "done when"
  check runs on its side before it relies on them, as `delegation.md`
  asks.

## 8. Bridges: GitHub, CI, and others

A bridge connects a packet to something outside: it can **create** a
card, **watch** a ref, and **reply** to a ref. GitHub is the first.

| | GitHub (through `gh`, or the hub's webhooks later) |
|---|---|
| create | `wpk new gh:owner/repo#41` (or the issue URL). Title from the issue; the brief quotes the issue body, marked as from the issue; `origin`, `watch` and `reply` are set to the issue; `work` is the repo at its default branch (attached if you have a clone, otherwise the folder beside the card) |
| watch | new comments, label and state changes on the issue, and on any PR in the deliverables, arrive as `note` entries with `Source:`. While working they reach the worker's mailbox; after `done` they show under **Updated** |
| reply | `wpk reply` drafts a comment from the result (summary, deliverables, the PR) and shows it; it is posted only when you confirm, then a `replied` entry records the URL. Never automatic: posting is outward-facing |
| close | when the issue is closed upstream, the packet offers to close too |
| `to: gh:owner/repo` | files the card as an issue, then watches it: an agent's request to a human maintainer |

Other bridges have the same three verbs: CI (create from a failed run;
reply as a check comment), a mail address, a dfm run (watch its job).

## 9. Copies, sync and bundles

**On one host** there is one card. `wpk`, the runner and the dashboard
append to it under a short file lock with an atomic rename, and re-read
it first, as the dashboard's markup writes already do
(`doc-markup.md`).

**Across hosts** each party has a copy. Syncing is the union of entries;
the front matter's frozen part must match, and the caches are
recomputed. Through the hub, the hub holds the reference copy and
pushes new entries both ways.

**A card can travel alone** whenever its refs are reachable by the
receiver: pushed commits, URLs, issues, shared paths. That covers most
requests, questions, issues and CI failures.

**Otherwise it travels as a bundle**, `<name>.wp.zip`. A zip, because
every system can open one:

```
uart-overrun.wp.zip
  uart-overrun.wp.md      the card; refs that were packed are rewritten to files/…
  files/                  copies of local inputs, and the folder's contents
  git/<repo>.bundle       commits the receiver can't fetch (unpushed work)
  manifest.json           sha256 of every file, and the original ref of each copy
```

What goes in follows `packet-format.md` §6's profiles: **report** (the
card, plus inputs it can't do without) and **team** (plus the folder,
and the plan and notes as blobs). The run itself is in no profile: it
stays with the server that ran it (`work-data-design.md` §13.3). Derived files are
dropped by default, and anything over a size threshold is listed before
it is sent (`bigger_picture.md`: clean before hand-off). On arrival the
packet is `open` for the receiver, nothing runs, and the brief is data
(§7.4).

### 9.1 Attachments: big files by reference

Some packets need files that nothing else holds: waves, a core dump, a
sim log from a run directory that will be cleaned, a customer's test
case. They don't go in the card, and they shouldn't be copied into every
bundle. They go in a **blob store**, and the card names them by content.

```yaml
inputs:
  - blob:sha256:9c1e4a…             # the short form
  - ref: blob:sha256:9c1e4a…        # the long form, when there is more to say
    name: waves.fst
    size: 1.4 GB
    from: /proj/sims/run42/waves.fst   # where it was taken from (a hint, may be gone)
    regen: dfm run uart.test_overrun --waves   # how to make it again instead of fetching
```

- **Named by content.** A `blob:` ref is a hash, not a place, so it
  stays valid wherever the bytes end up, and the same file attached to
  ten packets is stored once.
- **Stores are host configuration, not card data.** Each host lists the
  stores it can reach, in order: the local cache
  (`~/.work-packet/blobs/`), a team share (`/proj/wpk-blobs`), an S3 or
  R2 bucket, the hub. Resolving a blob tries them in turn. A card may
  carry a hint (`at: s3://fw-blobs`), but never credentials.
- **`wpk attach <name> <files…>`** hashes each file, puts it in the
  default store (on a share, by hard link or copy; to a bucket, by
  upload), and adds the ref. A CI job does the same with a few lines of
  shell (hash, upload, write the ref), or uses CI artifact URLs directly
  as `https://` refs, which works until the CI system expires them.
- **Fetched lazily.** Nothing is downloaded when a card arrives. Triage
  usually needs the log excerpt and the links, not the 1.4 GB of waves.
  `wpk fetch <name>`, opening the packet's workspace, or a step that
  reads the file brings it into the cache. It then appears in the
  packet's folder as `~/packets/<name>/inputs/waves.fst`, a link into
  the cache, so tools see an ordinary path.
- **Regenerate rather than store, when it's cheap.** Waves are usually
  derived: the repo at a commit, a seed and `repro` make them again. A
  `regen` command lets the receiver choose. Store them when the run took
  hours, the seed was lost, or the inputs aren't reproducible elsewhere.
- **Retention.** A store keeps a blob while any card it knows of names
  it and is not archived, plus a grace period (30 days by default).
  `wpk attach --keep` pins one. Removing a blob is journaled, so a ref
  that no longer resolves says when and why it went.
- **In bundles.** The `report` profile carries blob refs but not blobs
  over a size threshold (say 50 MB). The receiver fetches them if it can
  reach a store, or asks the sender. `--with-blobs` packs them into
  `blobs/<hash>` in the zip. `manifest.json` lists every blob, packed
  or not.
- **Don't invent the storage.** The store is an interface (put, get,
  has, list). The backends are things that already exist: a directory,
  an S3-compatible bucket, an OCI registry through ORAS. git-annex and
  DVC are the model: content-addressed files kept out of the repo, with
  pointers kept in it. Git LFS is the same idea tied to one git host,
  which packets can't assume.

#### An R2 bucket as the shared store

R2 is S3-compatible, so it is the `s3` backend with Cloudflare's
endpoint. It suits blobs well because R2 charges nothing for egress:
waves get downloaded many times (by you, the runner, a farm host, a
colleague), and on S3 those downloads are what costs money.

Host configuration (never the card):

```toml
[[blobs.store]]
name = "fw-r2"
kind = "s3"
endpoint = "https://<account-id>.r2.cloudflarestorage.com"
bucket = "fw-blobs"
region = "auto"
credentials = "env:R2"     # R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY, or an aws-cli profile
```

- **Keys are the hash**: `sha256/9c/1e4a…`. `put` is a HEAD then a PUT
  if the key is missing. Two writers racing on the same key write the
  same bytes, so no lock is needed. Large files go up as a multipart
  upload. The hash is checked on fetch, so a corrupt or substituted
  object is rejected whatever the store says.
- **Access without credentials.** A colleague or a CI job without an
  R2 token gets a **presigned URL**: `wpk send` and `wpk attach --share`
  can put time-limited GET URLs into the bundle or the message, never
  into the card itself. CI uploads with a token scoped to the one
  bucket, held as a CI secret.
- **Retention.** wpk's own rule (§9.1) decides what may go: a blob is
  deleted only when no live card names it. A bucket lifecycle rule
  (for example, delete after 180 days) is a backstop for blobs that
  CI uploaded and no card ever kept.
- **Cards and bundles too.** The same bucket can hold whole packets,
  under `packets/<id>/`: the card and, if made, its `.wp.zip`. Then
  `wpk get r2://fw-blobs/packets/<id>` (or a presigned URL to it) is
  how a CI failure or a hand-off is picked up. This is the "packets
  stored in an R2 or S3 bucket" case from `bigger_picture.md`.
- **Implementation.** boto3 as an optional extra (`work-packet[s3]`),
  so the core package stays dependency-light. The same code serves S3,
  R2, MinIO and others; only the endpoint changes.
- **Rough cost**, at R2's list prices as of writing (check before
  relying on them): about 0.015 USD per GB-month stored, with a small
  free tier, a few dollars per million writes and less per million
  reads. So 1 TB of waves is about 15 USD a month, however often they
  are fetched.

### 9.2 Clusters with no shared disk (Slurm)

Packets move by reference, so a compute node needs no shared
filesystem. It needs to reach three services over the network, and
local scratch disk to work on:

| What | Comes from | Typical service |
|---|---|---|
| source | a git server, at the commit the card names | the team's Forgejo or GitHub |
| blobs and bundles | an object store, by hash | S3-compatible, on-prem (below) |
| the card's entries and the run record | the hub, or the submitting host | wpkd, over HTTPS |

**Recommended store: an S3-compatible object store on the cluster's
own network.** It uses the same `s3` backend as R2, so nothing in wpk
changes; only the endpoint does.

| Option | When |
|---|---|
| **Ceph RGW** | the site already runs Ceph; use it |
| **Garage** | a small team or a few nodes; one small binary, built for modest hardware, AGPL |
| **SeaweedFS** | many files, large and small, at larger scale; Apache-2.0 |
| MinIO | widely known, but its community edition has narrowed since 2025; check its current terms first |
| Forgejo's LFS or generic package registry | no new service at all if Forgejo already runs, but it is tied to repos and less suited to many large, short-lived blobs |
| R2 | only if the compute nodes may reach the internet and the data may leave the site. For chip design IP it often may not |

**How a job runs** (the download-and-upload mode of `packet-shapes.md`
§5.3, made concrete for Slurm):

1. **Submit.** `wpk run <name> --on slurm` writes an ordinary `sbatch`
   script with the `#SBATCH` options from the host profile (partition,
   time, licences as `--licenses`), and submits it. The submitting host
   also creates **presigned URLs** for the blobs the job will read, and
   upload URLs for what it may write. They expire with the job's time
   limit, so compute nodes hold no long-lived credentials.
2. **Stage in**, on the node, in `$TMPDIR` or the node's local scratch:
   fetch the card and the run record's core tier from the hub; clone or
   fetch the source at its commit (a node-local mirror makes repeat
   clones cheap: `git clone --reference`); fetch the blobs, checking
   each hash.
3. **Work.** Steps run and commit locally, exactly as on a laptop.
   Waves and builds stay on local scratch.
4. **Stage out**, after each step commit, not only at the end:
   - new commits as a git bundle (or a push to a `refs/packets/…` ref
     on the git server);
   - new entries and the step's record to the hub;
   - attachments the step chose to keep (`wpk attach` inside the job)
     to the object store.

   The step counts as committed only once that has landed
   (`max_unlanded`, `packet-shapes.md` §5.3). A job killed at its time
   limit loses at most the step in progress.
5. **Clean.** The job removes its scratch. Nothing is left on the node
   except the blob cache.

**A node-local blob cache.** Because blobs are named by hash, a cache
on each node (`/local/wpk-blobs`, evicted least-recently-used) can be
shared safely by every job on that node. The second job that needs the
same 1.4 GB of waves reads them from local disk.

**Leases** need no shared disk either: the hub holds them, with the
heartbeat expiry of `packet-shapes.md` §5.3. A job whose node died is
noticed when its heartbeat stops, and the packet goes back to the
queue at its last landed step.

**Slurm's own tools** help but aren't required: `sbcast` can copy a
staged file from the job's first node to the others in a multi-node
job, and sites with burst buffers can stage in through them.

## 10. The user experience

### 10.1 The verbs

| Verb | Does |
|---|---|
| `wpk` | the home screen: what needs you, what's running, what changed, what's yours (§10.2) |
| `wpk new "<title>" [refs…] [--to X] [-m brief]` | a card. Refs may be a repo URL, an issue, files, a CI run. In a directory with no refs, the directory is the workspace. No `-m`: `$EDITOR` on the card |
| `wpk ask "<question>" [refs…] [--wait]` | a question to the runner: `work: none`; `--wait` prints the answer when it comes |
| `wpk run [name] [-m "…"]` | hand it to the runner (send, or hand off). On a done packet, `-m` is a follow-up request |
| `wpk work [name]` | an interactive agent in the packet's workspace; takes the packet back if the runner has it |
| `wpk answer [name]` | answer open questions; with no name, walks through every question waiting on you |
| `wpk show [name]` | the card, rendered: state, refs (marked if unreachable), the thread folded to the latest exchange |
| `wpk open [name]` | the workspace in the IDE; `--card` the card in `$EDITOR`; `--dash` the packet's page |
| `wpk done [name]` | the context decides: as worker, write the result (asks for a summary, checks deliverables); as requester, close it and offer to reply and archive |
| `wpk send name <who or file>` | to a person, another packet, a bridge, or a bundle file |
| `wpk reply name [ref]` | post the result to the origin, or to `ref`, and watch it afterwards |
| `wpk get <file, URL or address>` | take in a card or a bundle |
| `wpk note name "…"` | add a note |

Plus the shell niceties from `ergonomics.md` §4: name completion,
`wpk cd <name>` (the workspace; a shell function), and `wpk prompt` for
`PS1`.

**`ask` changes meaning** from `ergonomics.md`, where it listed open
questions. Asking a question is the more natural use of the word, and
`wpk answer` with no name already walks through open questions.

### 10.2 The home screen

```
$ wpk
Needs you
  uart-overrun        question q1: clear OE on every read, or only when empty?    2h
  pss-regs.pssc-req   send request to pkt:pssc? budget 3 USD                      5m
Running
  riscv-survey        runner · step 6 · 0.90 USD · waiting on 2 sub-packets
  fifo-regress        job dfm-1142 · 312/400 tests
Updated
  fifo-depth          done · "Depth 16 is enough at 2:1 clocks; table in fifo-depth/report.md"
  uart-overrun        gh #41: new comment from @jdoe
Yours, idle
  spi-port            last shift 2 days ago · next: wire the CS decode
```

"Updated" is per reader: what changed since you last looked, kept in
the index, not in the card. The dashboard's Inbox shows the same
sections; the board's columns are the states.

### 10.3 Journeys

Each is the user's whole interaction.

**A question.**
```
$ wpk ask "Which UVM versions does the pssc runtime support?"
uvm-versions · open · runner
$ wpk                                  # later
Updated
  uvm-versions   done · "1.2 and IEEE 1800.2-2020; 2017 untested (CI matrix)"
$ wpk show uvm                         # the answer, with its links
```
No directory was made. The card is `~/packets/uvm-versions.wp.md`.

**From the repo I'm standing in.**
```
$ cd ~/work/fw-uart16550
$ wpk new "Fix overrun flag clear"
uart-overrun · yours · workspace: this clone (branch uart-overrun)
$ wpk work                             # an agent, here; shift-ends recorded
$ wpk run                              # hand it over and go home
```

**From a repo elsewhere.**
```
$ wpk new https://github.com/featherweight-ip/fw-axi@v1.2 "Port the testbench to UVM 1.2"
axi-uvm-port · yours · workspace: ~/packets/axi-uvm-port/fw-axi (cloning…)
```

**From a GitHub issue, replying and watching.**
```
$ wpk new gh:featherweight-ip/fw-uart16550#41
uart-overrun · "RX overrun flag not cleared" · workspace: ~/work/fw-uart16550
Hand to the runner now? [Y/n] y
…
$ wpk                                  # a question, then later:
Updated
  uart-overrun   done · PR #52 · 1.84 USD
$ wpk reply uart-overrun
Comment on featherweight-ip/fw-uart16550#41:
  Fixed in #52: OE now clears on every LSR read (spec §8.4) …
Post? [y/N] y
posted · watching #41
```
Later comments on #41 appear under **Updated**, and in the card as
notes. `wpk run uart-overrun -m "also cover parity errors"` makes a
follow-up task in the same packet.

**A finished packet answers an issue it didn't come from.**
```
$ wpk reply fifo-depth gh:featherweight-ip/fw-fifo#9
```
The card gains `reply` and `watch` entries for #9. The issue never
needed to be the origin.

**A collection of files.**
```
$ wpk new "Review the AXI write path" rtl/axi_wr_*.sv docs/axi-wr.md --to alice
axi-wr-review · open · alice · 4 files (by reference)
```
`--copy` snapshots them into `~/packets/axi-wr-review/` instead. Sending
to Alice on another host packs whatever she can't reach (§9).

**Agent to agent.** Shown from the owner's side:
```
$ wpk
Needs you
  pss-regs.pssc-req   send request to pkt:pssc? budget 3 USD
$ wpk answer
pss-regs wants to send "Lower reg_c register access in pssc sv-native" to pssc.
  (brief: 14 lines · inputs: git:~/projects/pssc@main)   [s]how  [y]es  [n]o  > y
sent · pss-regs is waiting on it
```
When pssc's packet writes its result, pss-regs wakes with the result in
its prompt. The owner sees both in **Running**, then the parent's own
result.

**A failing test from CI.** CI writes the card (§4.6) and uploads it as
an artifact.
```
$ wpk get https://ci.example/run/8812/artifacts/test_overrun.wp.md
overrun-fail · open · from CI · not hydrated
$ wpk show overrun-fail                # triage from the card and the links alone
$ wpk work overrun-fail                # only now: clone at 3f0c9a2, ivpm update, repro
```

**To a colleague.**
```
$ wpk send uart-overrun alice
handoff to alice · via hub (refs reachable; no bundle needed)
```

### 10.4 The other surfaces

- **Dashboard.** The packet page is the card, rendered as a thread (the
  issue view), with a **Record** tab for steps, transcripts and the plan
  (`packet-page.md`). Comments on the card use the CriticMarkup support
  already built (`doc-markup.md`); each resolved comment becomes a `note`.
- **Editor.** A `.wp.md` file is a Markdown file. The VS Code extension
  adds actions above entries (Answer, Run, Done, Reply) and the state in
  the status bar. You can also just edit a draft by hand and `wpk run`
  it.
- **Agents.** The same verbs with `--json`, and as MCP tools
  (`packet_new`, `packet_send`, `packet_wait`, `packet_answer`,
  `packet_result`) for harnesses that aren't the runner.
  A Level 0 agent with only a skill keeps its packet by appending
  `handoff` entries at each shift-end.

### 10.5 What a user must learn

- **A packet is a file you can read.** Everything about the work is in
  it or linked from it.
- **The thread is the history.** What's next is at the bottom.
- The verbs in §10.1, most of which they will meet only when needed.

They don't need: ids, the run record, levels, tiers, the executor's
states, or where any of it lives except `~/packets/`.

## 11. What this changes

| In | Change |
|---|---|
| `packet-format.md` §1–§2 | The packet is the card, not a directory. In-place `.packet/`, the packet directory as a git repo, the split and tombstones all go. Levels stay as a guide for implementers: **L0** a card with a thread (agents append `handoff` at shift-end); **L1** a run record; **L2** bundles and bridges; **L3** jobs |
| `packet-shapes.md` §3–§4 | `PACKET.md` becomes `<name>.wp.md`. `~/packets/<slug>/` keeps only the workspace (`files/` flattens into it). Memento, state and history move to the run record. Bindings, landing, shadow repos and integration (§5) stand unchanged |
| `concepts.md` | Packet = a card and its thread. Task = one request→result exchange in it. A spawned child is a sub-packet, shown nested under its parent (the "a child is never a packet" rule changes: §12 D6) |
| `delegation.md` | The brief is a card; `state/requests/<id>.md` becomes `.pending/out/<name>.wp.md`; the requests index becomes the general index; `sync` becomes delivery on append; `wait` is added |
| `interaction.md` | Questions and answers are mirrored into the card as entries. The run record keeps the `handoff` journal record as now |
| `completion-report.md` | `report.md` stays the long form in the run record; its `outcome` and `deliverables` also become the `result` entry's trailers |
| `ergonomics.md` §4 | The verbs carry over, plus `ask` (new meaning), `reply`, bare `wpk`; `status` becomes `show` and the home screen |
| `spec.md` v0.2 | The packet directory becomes the run record, keyed by id, under `~/.work-packet/runs/`. Its file contract is otherwise unchanged. WPIDs: new packets get ULIDs; existing UUIDs remain valid ids |
| `boards.md` | A board is a saved filter (tags, `to`, origin); children no longer need to stay on their root's board, but are shown under it by default |
| Code | new `card.py` (parse, write, append, merge, derive state); `wpk check` learns cards; the executor writes entries in `_apply`; `requests.py` becomes delivery plus wake; `registry.py`/`views.py` read the index; `dash/data.py` renders the thread |

**Migration.** `wpk migrate` writes a card for each registered project's
root packet: title from `prompt.md`, `work:` from `[setup]`, a `sent`
entry for the first instruction, a `request` entry per later batch (from
the journal's `handoff` records), a `result` entry per completed batch
(from `state/history/report-<n>.md`). The packet directory stays where
it is and is linked as its run record.

## 12. Decisions for you

| # | Decision | Recommendation | Why, and the alternative |
|---|---|---|---|
| D1 | One file holding the whole thread, or the email model (the request and each reply as separate files linked by `in-reply-to`)? | **One file** | One file is what you asked for, and an issue page is the most familiar way to read work. Single authorship per entry gives the email model's safety (no edit conflicts) without scattering files. The cost: a long-lived packet's card grows; follow-ups that are really new work should be new packets with `origin: pkt:…` |
| D2 | Move the memento, plan and history out of the human area into the run record? | **Yes** | They are the executor's books. People get what they need as `handoff`/`result` entries and on the dashboard. It also ends the `git clean` and grep hazards of `.packet/` |
| D3 | The `.wp.md` suffix? | **Yes** | Recognisable anywhere, still Markdown. Alternative: plain `.md` with `packet:` in the front matter, which works in `~/packets/` but not in Downloads or a repo |
| D4 | ULID ids for new packets? | **Yes** | Sortable by time and made without coordination. UUIDs stay valid for existing packets |
| D5 | Packet states named as above, mapping to A2A? | **Yes** | Lets the runner speak A2A later at little cost. The executor keeps its own states privately |
| D6 | Spawned children as sub-packets (cards in the run record, shown nested), reversing `concepts.md`'s rule that a child is never a packet? | **Yes** | A child and a request to another agent are then the same thing with a different `to`. The UI can still label them "sub-tasks" |
| D7 | `ask` = make a question packet? | **Yes** | See §10.1 |
| D8 | Requests default to needing approval? | **Yes**, with the `auto` policy for small budgets to the local runner | `delegation.md`'s rule, made adjustable |

**Open questions** (defaults assumed above):

| # | Question | Default |
|---|---|---|
| O1 | Archive after how long, and does `done` archive at once? | `done` asks; closed cards older than 14 days are archived by `wpk` itself |
| O2 | How often may a runner write `progress` entries? | At plan milestones, and at most one per 30 minutes |
| O3 | Can a card in a repo (committed, for team tracking) be the live card, with its run record on each host? | Yes; the index records its path. Concurrent edits from two hosts are a sync (§9), through git if the team commits them |
| O4 | Should questions within a chain of agents always reach a person when the budget is above some level? | Not by default; a policy key `escalate_over` |
| O5 | Bridges in core or as plugins? | GitHub in core (through `gh`), others as plugins with the create, watch, reply contract |
| O6 | Is `partial` a separate state? | No: a `done` with `Outcome: partial`, shown as such |
| O7 | Blob stores: which backends first, and do waves default to stored or regenerated? | A directory (local or shared) and the S3 backend together, with R2 as the documented remote (no egress fees). Stored when attached by hand; CI attaches only on request, and otherwise writes a `regen` |
| O8 | On Slurm, do packets ever span nodes (multi-node jobs), or is one step always one node? | One node per step; a multi-node simulation is a `job:` the step starts and waits on |
| O9 | Should the scribe (a model run that drafts the hand-off note) be on by default for every hand-off to a person, given its cost? | Yes: it is small (a few cents), and the note is the most valuable thing a hand-off carries. Off for same-host hand-offs |

## 13. A first slice

1. `card.py`: parse, write, append under a lock, merge, derive state;
   `wpk check` validates cards. Test vectors: the cards in §4.5–§4.6.
2. `~/packets/` and the index; `wpk`, `wpk new`, `wpk ask`, `wpk show`,
   name resolution (§5.2).
3. The executor creates a run record from a card, and writes `accepted`,
   `question`, `progress` and `result` entries at commit.
4. Requests as cards: `.pending/out/`, the policy question, delivery on
   append, `resume: wait <name>` and waking.
5. The GitHub bridge: `new gh:…`, `reply`, and `watch` by polling
   `gh api` from `wpk tick` and wpkd.
6. `wpk migrate` for the existing projects.

Try it on three real things: a question, an issue on a fw-* repo, and
the pss-registers → pssc request that `delegation.md` was built for.
The measure: was anything typed that wasn't the work itself?

**Prior-art sources:** A2A specification (a2a-protocol.org/latest/specification),
MCP tasks (modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks;
the 2026-07-28 release candidate), beads (github.com/steveyegge/beads),
git-bug, Fossil tickets, org-mode property and logbook syntax, BagIt
(RFC 8493), RO-Crate, the OCI image manifest (`subject`), RFC 5322
threading, maildir, Slurm `#SBATCH`, Temporal workflow and run ids,
ULID, jj change ids, the GitHub Copilot coding agent docs, and Claude
Code subagent files.
