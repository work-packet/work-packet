# Concepts: packet, task, step, state (draft, 2026-10-26)

Status: a proposal for the words the dash (and later the CLI and docs)
use. Nothing is renamed yet. The file format (`docs/spec.md`) and code
keep their names for now; §3 maps one to the other.

## 1. The words

**Work packet** (or just *packet*). The unit of work the user owns: a
directory with its settings, its `work/` (repos and documents), and
the history of everything run on it. What the spec calls a *project*
together with its *root packet* is one work packet. It lives on a
board.

**Task**. One instruction run on the work packet until it is done,
needs input, or fails. Tasks come two ways:

- one after another: each instruction handed off through Compose is a
  task (the spec's *batch*);
- side by side: when a task splits work off, each piece is a task of
  its own (the spec's *child packet*), with its own instruction and
  its own state.

**Step**. One run of the model on a task. A task takes as many steps as
it needs; each step starts fresh from the task's state and ends by
committing it.

**State**. What a step leaves for the next: the next instruction
(`memento.md`), `state/` files, the outline, notes. Preserved after
every step (`steps/NNNN/`), so any step can be looked at, and the
task resumed, later.

```
work packet  (directory, settings, work/, board)
 ├─ task 1   "set up the testbench"         steps 1–6
 ├─ task 2   "fix the failing seeds"        steps 7–12
 │   ├─ task 2a  "triage seed 17"           steps 1–3
 │   └─ task 2b  "triage seed 40"           steps 1–4
 └─ task 3   "write the report"             steps 13–14   ← running
                                             each step: state in, state out
```

## 2. Rules of use

- "Packet" is only ever the top level. A child is never a "packet" in
  what the user sees.
- "Task" is never used for the packet itself.
- "Step" is never used for a task. "Batch" stops appearing in the UI.

## 3. Old name to new name

| Spec / code today | Dash today | Proposed |
|---|---|---|
| project (+ root packet) | project; "packet" for the root | **work packet** |
| batch (Compose, `plan.html` "Batch N") | "Next batch" | **task**; "New task" |
| child packet (a wpid under the root) | packet, child | **task** (a sub-task when shown under its parent) |
| step, `steps/NNNN/` | step | **step** (unchanged) |
| `state/`, `memento.md`, outline | state files, next instruction | **state** |
| board | board | board (unchanged) |

UI labels this changes:

| Where | Today | Proposed |
|---|---|---|
| Board header (`dash-tasks.md` §3) | New task (makes a project) | **New packet** |
| Project / packet page | Next batch | **New task** |
| Side tab, `/packets` | All packets (lists children too) | All packets (top level only), with its tasks under each |
| Project page | Packets tree, "Packets: 7" | **Tasks**, "Tasks: 7" |
| Per-wpid page `/p/E/<wpid>` | the packet page | **the task page** |

## 4. Open questions

1. **The root's own wpid.** In the spec the root packet runs every
   batch in turn, so one wpid holds several tasks. Do its steps get
   grouped by task on the page (task 1: steps 1–6 …), and does each
   task have its own page, or is the root's wpid page the packet page?
2. **CLI and spec.** Rename there too (`wpk new` makes a packet, a
   `task` noun for children), or keep the file format's words and only
   change what users read?
3. **Tasks as data.** Batches are already half first-class: each
   next-batch `handoff` record in the journal carries `batch` and
   `instruction` (`executor.batch_of`), and the outline and report are
   archived per batch (`state/history/outline-<n>.md`,
   `report-<n>.md`). Steps can be grouped by task by replaying the
   journal. A `task` field on each step record would make that
   direct; is it worth adding?
