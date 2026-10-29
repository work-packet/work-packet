# Interaction: questions, answers, and acting on packets from the board and a TUI

Status: I1–I3 built, I6 partly (live view), 2026-10-23; 376 tests pass. I4, I5 and the Markdown part of I6 to do. Not committed. This file holds the plan and a
status log, so a fresh session can pick up from it alone.

## 1. The problem

Driving the dv-solve trial showed the gap. A packet asks something, and you
answer by reading `state/questions.md` in a shell, then typing `wpk handoff
-m "…"` with the answers in free text. Changing a setting means remembering
`wpk allow` or `wpk set`.

What you want instead: see the open questions and answer them inline, in
the web board and in a terminal UI. Approving a permission should be one
action.

Two things are missing:

1. **Questions have no structure.** `ask:` is one string, so a front end can
   only offer a single text box.
2. **The board is read-only.** It has no actions.

## 2. Structured questions

`ask:` takes either a string (as now) or a list of questions:

```yaml
---
resume: now
ask:
  - id: bash
    q: Allow Bash for builds, tests and commits?
    recommend: "yes"
    grants: [Bash]
  - id: chains
    q: Build the exact chain detector only if more than 5% of classes have chains?
    recommend: "yes"
    choices: ["yes", "no", "always"]
---
Once answered: start item 0a in state/outline.md. ...
```

| Key | Type | Required | Meaning |
|---|---|---|---|
| `id` | name (`[a-z0-9][a-z0-9_-]*`) | yes | unique within the list |
| `q` | non-empty string | yes | the question |
| `recommend` | string | no | the agent's recommended answer; "take the recommendations" uses it |
| `choices` | list of strings | no | the answers a front end offers as buttons; free text is still allowed |
| `grants` | list of tool strings | no | answering yes (`yes`, `y`, `true`, `ok`, `approve`, `grant`) runs `wpk allow` for these tools before the hand-off |
| `request` | name | no | answering yes sends the request `state/requests/<name>.md` before the hand-off (docs/delegation.md §3); the brief must exist when the step commits |

- `status.reason` becomes a one-line summary: the question itself for one,
  "N questions: <first>" for more.
- The full list stays in the committed `memento.md` front matter, which
  already keeps the step's front matter as a record (spec §4.2). Front ends
  read the questions from there while the packet is `NEEDS_INPUT`.
- A string `ask:` counts as one question, with id `q1` and no
  recommendation.

## 3. Answers

An answer is a hand-off with `answers`: a map from question id to text,
plus the optional free-text note. The `handoff` journal record gains:

- `questions`: the list, copied from the memento, so the record stands
  alone;
- `answers`: `{id: text}`.

The step prompt's Hand-off section lists each question with its answer.
A question left unanswered is shown as unanswered, so the model asks again
or uses its recommendation, as the note says.

**Take the recommendations** fills every unanswered question from its
`recommend`. Grants run first: `project.allow`, with a `config` record. Then
the hand-off happens.

## 4. One set of actions

`work_packet/actions.py` holds what a front end can do, as plain functions
over a packet or a project:

| Action | Does | CLI |
|---|---|---|
| `answer(pkt, answers, note, take_recommendations)` | grants, then `handoff` with answers | `wpk answer <target> [id=text…] [-r] [-m NOTE]` |
| `handoff(pkt, note)` | `executor.admin(…, "handoff")` | `wpk handoff` |
| `pause(pkt)` / `resume(pkt)` | `executor.admin`; while a step runs, a pause is a request honoured when it ends (docs/pause-v1.md) | `wpk pause` / `wpk resume` |
| `pause_project(e)` / `resume_project(e)` / `stop_project(e)` | the project's whole tree; resume only what was paused by hand; stop also ends running steps (not counted) | `wpk pause` / `wpk resume <project>`; the board |
| `allow`, `deny`, `set` | `project.*` | `wpk allow` / `deny` / `set` |
| `questions(pkt)` | the open questions, normalised | `wpk show` prints them |

The CLI, the web board and the TUI call these and add no logic of their
own.

## 5. The web board

**Security is out of scope for now: the board is in-house.** The existing
`Guard` (Host/Origin checks and a CSRF token on POST, server.md §4) stays in
place, because it costs nothing. The pages put its token in every form.

- **Packet page, `NEEDS_INPUT`:** an **Answer** panel at the top. Each
  question shows:
  - its text and the recommendation;
  - buttons for its `choices`, or a text box filled in with the
    recommendation;
  - "grants: Bash" when answering yes grants something.

  Below the questions there is a note box and two buttons, **Send answers**
  and **Take the recommendations**.
- **Packet page, `PAUSED` / `FAILED`:** **Hand off**, with a note box.
- **Packet page, `RUNNABLE` / `SLEEPING`:** **Pause**.
- **Project page:** **Settings**:
  - the allowed tools, each with a remove button, and a box to add one;
  - the limits and the model, as `key = value` fields, which run `set`.
- **Board, "Needs you" card:** the question, and an **Answer** link to the
  packet page's panel.
- **After a POST,** the page redirects back (303) and shows a one-line
  result ("handed off: 2 answers, granted Bash").

## 6. The TUI (`wpk tui`)

The TUI is built with Textual, as an optional extra (`work-packet[tui]`).

- **Left:** the projects and packets, as on the board, with "Needs you"
  first.
- **Right,** for the selected packet:
  - the Answer panel, laid out like the web form, with keys to accept a
    recommendation and to send;
  - the outline and state files, rendered as Markdown;
  - a live tail of the running step's status.
- **Keys:** `a` answer, `r` take the recommendations, `h` hand off, `p`
  pause, `s` settings, `t` transcript.

The status feed and the Markdown rendering are the same work as
long-running.md §5 "Viewing (later)" (L4b), so they are designed once and
used in both front ends.

## 6a. Notes to a task at any time (I7)

A hand-off only reaches a packet that has stopped (`NEEDS_INPUT`, `PAUSED`
or `FAILED`). A **note** reaches it in any state, and doesn't change the
state. A typical case: the live view shows the model fighting slow tests,
and the owner wants to say "add a `pytest.ini` that limits collection to
`tests/`".

- **Sending a note:** `wpk note <target> -m TEXT` (or `--note-file F`),
  `actions.note`, or the note box on the packet page and live view. The
  note goes into the packet's inbox, `mailbox/<id>.json` (`id`, `t`, `by`,
  `text`), the `mailbox/` reserved in spec §4. The inbox is outside the committed files, so a note can arrive
  while a step runs, without the lease and without breaking the step's
  snapshot check.
- **Delivery while a step runs:** the PostToolUse hook (`ctxhook.py`), now
  always installed when the harness can inject, sends any note it hasn't
  sent yet. The model gets it as added context after its next tool call.
- **Delivery in the next prompt:** every note still in the inbox when a
  step's prompt is built is shown under "Notes from the owner".
- **Tracking:** each attempt lists the notes it saw, and how (`prompt` or
  `hook`, with the time), in `steps/NNNN/notes.seen`.
- **When a step commits:** it carries the notes it saw in its
  `commit-begin` decision, with their text, as the permanent record. The
  commit then removes them from the inbox. A failed attempt removes
  nothing, so its retry sees the same notes in its prompt.
- **`--wake`:** a `SLEEPING` packet becomes `RUNNABLE` at once (an
  `admin` record with op `wake`). A packet in `NEEDS_INPUT`, `PAUSED` or
  `FAILED` keeps its notes until it is handed off.
- **Where notes show:**
  - the packet page lists the queued notes;
  - the step page lists the notes that step got.

  Claude Code's stream doesn't contain a hook's added context, so the log
  view can't place a note at its call.

## 7. Build plan

- [x] **I1: structured `ask:`.** Schema, `questions.py` (normalise,
  summary, is-yes), the executor's reason summary, and the `handoff`
  record's `questions` and `answers`. The Hand-off section lists them.
  `wpk show` prints open questions. Protocol text: how to write questions
  (with ids and recommendations, and `grants` for permissions).
- [x] **I2: `actions.py` and `wpk answer`.** Answer with grants, take the
  recommendations; the CLI.
- [x] **I3: web actions.** The routes, forms, redirect and result line;
  Answer, Hand off, Pause; Settings on the project page; the Answer link
  on the card.
- [ ] **I4: the dv-solve trial on the board.** The next gate is answered
  from the board.
- [ ] **I5: TUI.** The packet list, the Answer panel, the state viewer and
  the keys; status tail after L4b.
- [x] **I7: notes (§6a).** Inbox, hook delivery, prompt section, commit
  record, `wpk note`, the board's note box, tests.
- [~] **I6: viewing (L4b).** Live view and raw transcript done (2026-10-23); Markdown rendering to do. The status feed, the raw transcript and
  rendered Markdown, on the board and in the TUI.

## Status log

### 2026-10-23: plan
Written after the dv-solve trial's first gate. The user asked to start
with the web board, with security out of scope (in-house).

### 2026-10-23: I1–I3 built
- `questions.py` validates, normalises and summarises questions, and works
  out answers and grants. `ask:` takes a string or a list.
- `actions.answer`: grants first, then the hand-off with `questions` and
  `answers` in the record. `wpk answer <target> [id=text…] [-r] [-m]`, and
  `wpk show` lists the open questions.
- The board:
  - POST `/p/<project>/<wpid>/act` (answer, recommend, handoff, pause,
    resume);
  - POST `/p/<project>/settings` (allow, deny, set);
  - a 303 back to the page, with a result line;
  - the Answer panel, the Hand off and Pause forms, the Settings panel,
    and the "Needs you" card linking to `#answer`.
- The guard's CSRF token goes into every form (`scope.state.csrf`).
- `live.js` doesn't refresh while a form is being filled in.
- Tests: `tests/test_ask.py`, the actions in `tests/test_dash.py`, and the
  token through the real guard in `tests/test_server.py`.

- `actions.py` has only `answer` so far. The other actions in §4 are still
  direct calls to `executor.admin` and `project.allow` / `deny` /
  `set_values`. Wrap them when the TUI (I5) needs them.

### 2026-10-23: live view (part of I6)
- `/p/<project>/<wpid>/live` refreshes every 3 s. It shows:
  - a header: running or not, step and attempt, elapsed time, calls,
    context and output tokens;
  - **What it is doing**: a feed of the newest 80 events (the model's
    text; each tool call as its description, command or path, with the
    last line of its result, or "… running");
  - **This step's tasks**, from the last `TodoWrite`, if the step has that
    tool;
  - **Outline**: the checklist in `state/outline.md` (the `.pending/` copy
    while a step runs), with progress and the current item;
  - **Steps done**: each with its cost and summary.
- `/p/<project>/<wpid>/<step>/raw` serves the transcript JSONL as it is. The
  step page links to it and to the live view.
- On the board, a running card links to the live view and shows the latest
  event.
- `data.activity`, `data.outline` and `data.live` are front-end neutral, so
  the TUI (I5) reuses them.
- Still to do for I6: rendered Markdown with a source toggle.

### 2026-10-23: processes in the live view
- While a step runs, `model.run` writes the model's PID to
  `steps/<n>/model.pid`, and removes it when the model exits.
- `procs.py` scans `/proc` for the step's processes, which it finds in two
  ways:
  - the session ID equals the model's PID (the model runs in its own
    session);
  - the environment holds `WPK_WPID` and `WPK_STEP`. This also catches
    processes that called `setsid()`, and steps with no `model.pid`.
- For each process it gives the PID, the command line, the state, CPU
  time, memory (RSS) and age, as a tree.
- The Bash tool's `bash -c 'source <snapshot> … eval '<cmd>''` is shown as
  `$ <cmd>`.
- Live view: a **Processes** panel (`#procs`), up to 60 rows, with
  "… and N more" after that. A step on another host says where it runs.
  There are no kill actions.
- Links:
  - project page: a "Running: … Live view · processes" line, and a `live`
    link on every packet row;
  - packet page: a link to the processes.
- Tests: `tests/test_procs.py`, plus `test_live_page_processes` in
  `tests/test_dash.py`.

### 2026-10-23: scrolling transcript and a log view
- **Scroll panes** (`pane.js`, on every page). The live feed and the step
  page's transcript scroll inside a pane, up to 72% of the window.
  - A pane follows the newest output while you are at its bottom. If you
    scroll up, a refresh keeps your place.
  - A finished step's transcript starts at the top.
  - `live.js` fires `wpk:beforeswap` and `wpk:swap` around each refresh.
    It also pauses while text is selected, so you can copy from the page.
- **Log view** (`?view=log`, on the live view and the step page), modelled
  on GitHub Actions:
  - a dark console with numbered lines that you can link to (`#L120`);
  - each tool call is a collapsible group holding its input (`$ cmd`, or
    `key: value` lines) and its output, up to 20,000 characters;
  - error groups and the running call are open;
  - **Expand all** and **Collapse all** buttons;
  - paths are relative to the packet.
- **Downloads:** `<step>/log.txt` is the same log as plain text, uncut.
  The raw JSONL link is still there.
- The fork command's Copy button had an inline `onclick`, which the CSP
  blocks. It now uses `data-copy`, handled by `pane.js`.
- `data.log` and `data.log_text` are front-end neutral, for the TUI.
- Test: `test_log_view` in `tests/test_dash.py`.

### 2026-10-23: notes (I7)

- `notes.py` holds the inbox (`mailbox/<id>.json`); `actions.note` queues a
  note; `wpk note <target> -m TEXT [--wake]`.
- `ctxhook.py` takes `<inbox> <notes.seen>` as well and sends new notes
  after a tool call. It is now installed whenever the harness can inject,
  with limit 0 when the context limit is off.
- The prompt section, `notes.seen`, the decision's `notes`, and their
  removal in `_apply` (safe to redo when rolling forward).
- Board: a note box on the packet page and the live view, with the queued
  notes listed; the step page shows the notes that step got. The live
  view's refresh doesn't swap out a form you are typing in.
- The protocol has a "Notes from the owner" section.
- Tests: `tests/test_notes.py`, plus `test_note_box` in `tests/test_dash.py`.
  The fake model runs PostToolUse hooks once and can drop a note in
  mid-run. 404 pass.
- Not yet checked with real Claude Code: whether the model acts on a
  mid-step note. Delivery is the same hook path that already carries the
  context warning, which steps do act on.
