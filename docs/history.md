# Task history in the packet format (proposal, 2026-10-27)

Status: a proposal for review. Nothing here is built.

The dashboard's task page (`docs/packet-page.md` §6) shows each task's
instruction, report and results as they were when it finished. Today the
packet format records part of that and wpk's dashboard works out the rest
itself. Every other client (the VS Code extension, `wpk` on the command
line, an agent writing a report, a receiver of a bundle) would have to
work it out again. This proposal puts task history in the format, so it
has one home and one reader.

## 1. What is there today

| What | Where | Written by | Problem |
|---|---|---|---|
| Where tasks start and end | `journal.jsonl`: `step-start`, `handoff` with `instruction`, `commit-begin` spawns | executor | only `dash/data.py` `tasks()` turns it into tasks, by replaying the journal |
| A task's instruction | the `handoff` record | executor | task 1's is not recorded anywhere; `memento.md` is overwritten |
| A finished task's outline | `state/history/outline-<n>.md` | executor, at hand-off | inside `state/`, which the agent owns and a step replaces |
| A finished task's report | `state/history/report-<n>.md` and `steps/NNNN/report.md` | executor | two copies; the first is in `state/` |
| Its results as they were | `steps/NNNN/deliverables/` and `deliverables.json` | executor, at commit | added today; nothing points to it except `tasks()` |
| Its steps, cost, children | `steps/`, `meta.json`, journal | executor | summed by each client |

So the facts are mostly recorded, but **the task is not a thing in the
format**: the format has no task record, and `state/history/` mixes the
executor's history into the agent's working files.

## 2. Proposal

### 2.1 `tasks/NNNN/`, a folder per task (Level 1, core tier)

```
tasks/
  0001/
    task.json        what the task is and how it went (below)
    instruction.md   the instruction it started from, in full
    outline.md       the outline when it ended, if it had one
    report.md        the report it ended with (a copy of the step's)
  0002/
    …
```

`task.json`:

```json
{"n": 2, "started": "2026-10-27T09:12:00Z", "by": "owner", "from": "handoff",
 "steps": [7, 12], "state": "COMPLETED", "ended": "2026-10-27T11:40:03Z",
 "reports": [{"step": 12, "outcome": "Fixed the overrun flag; 67/67 pass."}],
 "children": ["…wpid…"], "cost_usd": 4.12}
```

- Written by the executor only: created when the task starts (a new
  packet, or a hand-off with a new instruction), updated as its steps
  commit, closed when the next task starts. A closed task never
  changes.
- `reports` is a list because a task can end, be resumed without a new
  instruction and end again; each entry names the step that wrote it.
  **The results stay in that step** (`steps/NNNN/deliverables/`), so
  they are stored once.
- **Rebuildable from the history**, per format principle 5: one new core
  journal record, `task-start` (`n`, `instruction`, `by`), written when
  the packet is created and at each new-instruction hand-off. `tasks/`
  can then be rebuilt from `journal.jsonl` and `steps/` alone, and
  `wpk check` can verify that it matches.

### 2.2 `state/history/` stops being written

New outlines and reports go to `tasks/NNNN/`. Existing
`state/history/` files are left alone, since they are the agent's files
now. The protocol (`prompts/protocol.md` §report, §hand-off) tells the
agent to read earlier tasks from `tasks/` instead. They are files in the
packet, outside `state/`, so the agent can still read them, and a step
does not replace them.

### 2.3 One reader, and a JSON form for other clients

- `work_packet/history.py`: `tasks(pkt)` reads `tasks/`, and falls back
  to replaying the journal for packets made before it. The dashboard's
  `data.tasks()` becomes a thin wrapper.
- `wpk tasks <project>[/<wpid>] [--json]` and
  `wpk task <project> <n> [--json]`: the same data from the command line.
  The JSON shape is `task.json` plus resolved paths, documented in the
  spec. This is the "JSON API" that `docs/vscode-plan.md` names as the
  extension's blocker.
- `/p/E/tasks.json` on the dash returns the same shape, for a remote client.

### 2.4 Migration

`wpk migrate` (or the first step after upgrading) builds `tasks/` for an
existing packet from its journal, `state/history/` and `steps/`. Task 1
gets its instruction from `prompt.md` where the project has one, and is
otherwise marked unknown. Older tasks have no `deliverables/`; their
`task.json` says so, as the task page does today.

### 2.5 People do tasks too

Nothing in `tasks/` assumes a model ran. A task a person works (Level 0
shift-end commits, `docs/packet-format.md` §2.4) gets the same
`task.json`, with its steps taken from the commits, and the same report
and kept results (`docs/positioning/messaging.md` §5). A person working in
a board session gets steps too: `steps/NNNN/` with `worker: person` in
`meta.json`, written by the scribe (`docs/work-sessions.md` §4.6).
Readers must not assume a step has a transcript, a model or a cost.

## 3. Spec changes

- `docs/packet-format.md` §2.3: add `tasks/NNNN/` (L1, core); §5: add
  `task.json` and the `task-start` record; the data-tier table lists
  `tasks/` as core and `steps/*/deliverables/` as record, since it can
  be large.
- `docs/spec.md` §4.4/§4.7: the wpk profile writes it; hand-off stops
  moving files into `state/history/`.
- `docs/concepts.md`: "task" gets a definition in the format, not only
  in the UI.

## 4. Open questions

1. **Agents and `tasks/`**: should a step be able to read `tasks/`
   (proposed: yes, read-only by convention), or should the prompt quote
   the last task's report instead?
2. **Sub-tasks**: a child packet is a task in the UI (`concepts.md`) but
   has its own `tasks/`. Should the parent's `task.json` name only its
   children's wpids (proposed), or copy their outcomes too?
3. **Bundles**: does a `report` bundle carry `steps/*/deliverables/` of
   every task, or only the last?

## 5. Plan

1. `task-start` record and `tasks/NNNN/` written by the executor; spec text.
2. `history.py` with the journal fallback; `data.tasks()` on top of it.
3. Stop writing `state/history/`; protocol text; `wpk check` rule.
4. `wpk tasks` / `wpk task` `--json`; `/p/E/tasks.json`.
5. Migration for existing packets.

Status: not started.
