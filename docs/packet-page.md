# The packet page: a snapshot first, then tabs (draft, 2026-10-26)

Status: being built (§6 tracks progress). Words as in
`docs/concepts.md`: a **work packet** (the spec's project and its root
packet) runs **tasks** (the spec's batches, and child packets) over
**steps**, each step preserving the task's **state**.

## 1. The problem

The packet page, `/p/<name>` (`dash/templates/project.html`), has grown
one panel at a time. Top to bottom, it now shows:

| # | Block | Kind |
|---|-------|------|
| 1 | Name, state, RUNNING badge | status |
| 2 | "Running: … step N" panel, links to live and processes | status |
| 3 | "Next batch" / "Set it up" link | action |
| 4 | Completion report, when the root is COMPLETED or FAILED | status |
| 5 | Key/values: Directory, Documents, Packets, Spend, Last step, Board | snapshot (+ a setting) |
| 6 | Scheduling: class, size, queue | setting |
| 7 | VS Code: open the packet, and each `work/` repo | action |
| 8 | Timeline: steps over time, a row per task | snapshot |
| 9 | Tokens: quota, figures, two charts, by task, by plan item, where the context went | metrics |
| 10 | "Packets" tree: the root and its child tasks | status |
| 11 | Recent steps (last 50) | history |
| 12 | Settings: allowed tools, limits and model | setting |

Four questions share one scroll:

- **What is this packet, where is it at?** 1, 2, 4, 5, 8, 10
- **What can I do next?** 3, 7
- **What has it done, and what did it cost?** 9, 11
- **How is it set up?** 6, 12, and Board from 5

The settings are split: two panels (6, 12) and a form inside the
key/values (Board). The actions (3, 7) are far apart. And the Timeline,
the best single picture of the packet, sits below a screenful of forms.

## 2. Proposal

### 2.1 The page top

```
myproj   [RUNNING] [SLEEPING]
[New task]  [Open in VS Code ▾]  [Live view]
 Overview | Tasks | Steps | Cost | Settings
```

- **Header**: name and state, on every tab.
- **Action bar**: the next steps, as one row of buttons chosen by
  state. New task / Set it up (3, today "Next batch"); Open in VS Code,
  a menu holding "the packet", each `work/` repo, "your clone" and
  "packet worktree", and "in the browser" with its size (7); Live view
  when a step is running (2). The first button for the state is
  highlighted.
- **Tabs**: plain links to separate routes, so each is a
  server-rendered page and can be bookmarked; no tab code in the
  browser.

### 2.2 Overview: the snapshot first

The first thing under the top is a single **Snapshot** panel: what the
packet is and where it is at, at a glance. It merges the key/values
(5) and the Timeline (8):

```
┌ Snapshot ──────────────────────────────────────────────────────────────┐
│ Directory  /home/…/myproj           Tasks      5 · 3 COMPLETED · 1 …    │
│ Documents  work/ (read, mark up)    Spend      $12.40 total, $1.10 today│
│ Board      main                     Last step  3 minutes ago            │
│                                                                        │
│ fix seeds     ███ ██  █████                     █ ██                    │
│  └ seed 17         ██ ███                                               │
│  └ seed 40                  ████ █ ██ ███                               │
│               Oct 24          Oct 25           Oct 26                   │
└────────────────────────────────────────────────────────────────────────┘
```

- The key/values go in two columns above the timeline, so the panel is
  short.
- Board is shown as a link to the board. **Moving** the packet to
  another board goes to Settings.
- The timeline keeps a row per task and its click-through to each
  step, and the line saying what the gaps are.

Under the snapshot, on the Overview:

1. **Running panel** (2), when a step is running.
2. **Completion report** (4), when the current task is COMPLETED or
   FAILED.
3. **Tasks** (10): the tasks, in order, with sub-tasks under the task
   that split them off. One line each: state, steps, spend, last
   summary.

### 2.3 The tabs

| Tab | Route | Contents | Today |
|-----|-------|----------|-------|
| **Overview** | `/p/E` | Snapshot; running panel; report; tasks | 1, 2, 4, 5, 8, 10 |
| **Tasks** | `/p/E/tasks` | Every task with every column, filters by state; each task's instruction and report | 10, in full |
| **Steps** | `/p/E/steps` | All steps, newest first, with paging, filterable by task | 11 |
| **Cost** | `/p/E/cost` | Quota, figures, charts per day, by task, by plan item, where the context went | 9 |
| **Settings** | `/p/E/settings` | §2.4 | 6, 12, Board |

### 2.4 Settings

Everything that governs how the packet runs and where it shows up:

- **Permissions**: allowed tools (`_settings.html`).
- **Limits and model**: step timeout, budget, model, harness
  (`_settings.html`).
- **Scheduling**: class, size and queue (`_sched.html`
  `project_panel`).
- **Board membership**: which board it is on, and moving it.

### 2.5 Things that move

- **Old anchors** (`#tokens`, `#context`, `#settings`, `#sched`,
  `#vscode`) are linked from elsewhere on the board (for example
  `overview.html` links `/p/<name>#tokens`). Point those links at the
  new tabs, and have a small script on the Overview redirect any
  others.
- **Compose** stays where it is; New task in the action bar links to
  it, as Next batch does today.

## 3. The task page, after

`/p/E/<wpid>` (`packet.html`) is today's page for one wpid, which in
the new words is a task (or, for the root, the run of tasks). It has
the same problem: 17 blocks and five separate action panels. The same
pattern fits it:

- Snapshot first: state, step, outline done/total, spend, next
  instruction, parent and sub-tasks.
- An action bar: answer questions, hand off, pause, run next, note,
  open in VS Code.
- Tabs: Overview, Live (today's Live page), Steps (the steps table and
  journal), Plan, Cost, State (`memento.md`, `state/` files), Settings
  (its scheduling class and size; the rest shown as "the packet's"
  until a task can override them).

Do this one after the packet page, reusing its header, action bar and
tab macros. How the root's wpid page relates to the packet page is
`docs/concepts.md` §4 Q1.

## 4. Build notes

- `_tabs.html`: header, action bar and tab strip, one macro for the
  packet and one for a task, called with the active tab.
- `_snapshot.html`: the Snapshot panel, with the timeline SVG and its
  styles moved out of `project.html`.
- The `project` route in `app.py` stops building tokens, settings and
  the 50 recent steps; the Cost, Settings and Steps routes build them
  instead, so the Overview loads less.
- Labels change with `docs/concepts.md` §3 (Next batch → New task,
  "Packets" → "Tasks"); templates and routes keep their file names
  until the code is renamed, if ever.
- Tests that look for text on the page will need to look on the new
  tab, and for the new labels.

## 5. Open questions

1. **Report or snapshot first**, when the current task is finished? The
   proposal puts the snapshot first always. A finished task might lead
   with its outcome instead.
2. **Tasks tab**: is a separate tab worth it, or is the list on the
   Overview enough until packets have dozens of tasks?
3. **Cost vs Metrics**: just tokens and money, or also time per step,
   failure rate and so on? If the latter, call it Metrics.
4. **A Files tab**: `work/` documents and repos are reached from
   Documents and the VS Code menu today. A Files tab could list
   `work/`, the root's `state/` and the docs together.
5. **Per-task settings**: should a sub-task be able to override
   permissions, limits and model, the way it can override its
   scheduling class?

## 6. Progress

The packet page (§2) is built; the task page (§3) is next, not started.

- [x] `data.tasks()` (`dash/data.py`): the root's steps split at each
      hand-off of a new instruction, children nested under the task
      whose step spawned them. Task 1 has no instruction text: the
      first instruction is not recorded anywhere a step can be tied to.
- [x] `_snapshot.html`: key/values in two columns plus the timeline,
      one row per task (and per sub-task)
- [x] `_tabs.html`: header, action bar (New task, Live view, Open in
      VS Code ▾), tab strip
- [x] Routes `/p/E/tasks` (filter `?state=`), `/p/E/steps` (filter
      `?task=<n or wpid>`, 50 a page), `/p/E/cost`, `/p/E/settings`;
      templates `project_*.html`, the task table in
      `_project_tasks.html`
- [x] Overview (`project.html`): snapshot, running panel, report,
      tasks. Old anchors redirect by script; `overview.html` links to
      `/p/E/cost`
- [x] Settings forms (permissions, limits, scheduling, board) come
      back to the Settings tab
- [x] Board-level "New task" (makes a packet) renamed **New packet**
      (`base.html`, `new.html`, `overview.html`, `packets.html`)
- [x] Tests: moved to the new tabs; new
      `test_plan.py::test_packet_page_tabs_and_tasks`,
      `test_dash.py::test_tasks_nest_children_under_the_task_that_spawned_them`.
      Full suite: 697 passed, 4 skipped
- [x] A page per root task, `/p/E/tasks/<n>` (`task.html`,
      `data.task()`): its instruction, **its** completion report (the
      last task's `report.md`; an earlier one's from
      `state/history/report-<n>.md`, archived by the hand-off), its
      sub-tasks, its steps, and links to the tasks either side. A task
      report rolls up only the children that task spawned. The Tasks
      table links each task's name and "report" here.
- [x] Results kept as they were: the step that writes a report copies
      what it lists to `steps/NNNN/deliverables/` (`report.snapshot`,
      `.git` left out, 64 MiB a report, `deliverables.json` says what was
      kept; spec §4.4). The task page reads the report from that step and
      its links add `&step=NNNN`, served read-only from the copy. A
      deliverable not kept (too large) is marked and opens as it is now;
      so do all of a report written before snapshots (it says so).

Left open:

- The timeline links a task's row to the root's wpid page, which shows
  all tasks' steps together (`concepts.md` §4 Q1).
- §5's questions are unanswered; the build takes the defaults (snapshot
  first, a Tasks tab, "Cost").
