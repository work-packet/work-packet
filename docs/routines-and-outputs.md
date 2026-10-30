# Routines and what they publish (proposal)

Draft 2, 2026-10-30. Status: **decisions taken** (§11); nothing is built.
Draft 2 splits the Inbox (incoming requests) from **Needs you** (requests
for input), per review.

## 1. The question

Periodic tasks ("routines") are mostly research on a timer. Examples:

- **CI health.** Every Monday at 07:00, look at the GitHub org. File a
  fix-it task for each CI pipeline that failed over the weekend.
- **Quarterly strategy.** Once a quarter, assess a board's projects and
  publish a "this quarter's strategy" page in the board's space.

Running something on a timer is the small part. The hard part is the
data a routine leaves behind. It has to be kept, shown at the right level
of the dash, and announced to the right person. Today none of that exists
except for one special case (watchers). This doc proposes one scheme for
all of it.

## 2. What is here today

| Piece | What it does | What it tells us |
|---|---|---|
| **Watchers** (`watch.py`, `[[watch]]` in `boards/<b>.toml`) | Poll trackers every `every` and make a packet per new issue. State in `$WPK_HOME/watch/<b>.<name>.json`; dedupe by origin; "Poll now" on the board | The one periodic producer we have. It is deterministic (no agent), configured on a board, and makes **tasks**. It is the template |
| **`resume: in N days`** (`clock.py`, `executor.py:829`) | A step re-arms itself as `wake_at` | A self-rescheduling packet works, but it costs a full step to find "nothing to do" (about $0.45 a day for `pss-registers-up-planning`, stats-review-2026-10.md:98) |
| **`every:`** | Reserved: `clock.py:23` marks it "Stage 2" | roadmap.md §"Scheduled resumption" has rules for it: recurrence kept by the executor, catch up once after missed wakes, a fake clock for tests. Open question there: one packet forever, or a fresh one per run? |
| **`report.md` and deliverables** (`report.py`) | Written once, at done/fail | A page-like output, but tied to the end of a packet, not to a place on the dash |
| **Sphinx docsets** (`docs.py`) | Built into `$WPK_HOME/docs/<project>/…`; the board links the newest | The only "publish a page" path today. Project level only |
| **Token charts** (`dash/tokens.py`, `history.db`) | SVG bar charts of cost and tokens | Charts render fine. There is no store for *user* series |
| **Unread / Needs attention** (`dash/data.py:338`, `POST /seen`) | Finished work you haven't looked at | The only notification surface. No push |
| **Inbox, Outbox** in the side tab (boards.md) | Placeholders, greyed out | product.md means bundles from teammates. Kept for that: incoming requests (§9) |
| **product.md §7.3, D7** | Badge, browser notifications, one push channel (ntfy) | The intended notification channels |
| **social.md** | "The unit of knowledge is a finding, not a packet" | A routine's item is close to a finding |

There is no "space" in the code. This doc uses the word for *the part of
the dash that belongs to one level* (§4).

## 3. The scheme in one picture

```
 trigger            producer                  outputs                  space            people
 ─────────          ────────                  ───────                  ─────            ──────
 every: mon 07:00 ─▶ probe (a script, free) ─┬▶ series point ────────▶ board:fvutils ─▶ chart
                    │                         │                         │
                    └▶ agent step (if needed) ─┼▶ items (findings) ────▶ │ ───────────▶ space, badge;
                                               │                         │              alerts → Needs you
                                               ├▶ tasks (packets) ─────▶ │ ───────────▶ board cards
                                               └▶ page (versioned) ────▶ │ ───────────▶ pinned page
                                                                         └─ rules ─────▶ push (ntfy)
```

Four ideas:

1. **Four kinds of output**, each with its own store and its own view:
   *tasks*, *items*, *series*, *pages* (§5).
2. **Every level of the dash has a space** that outputs are published
   into: home, board, project, packet (§4).
3. **One way in.** Agents write outputs under `.pending/publish/`; scripts
   and watchers call `wpk publish`. Both go through the same validation
   and the same commit (§7).
4. **Notification is a property of the output, not of the routine.** Each
   output carries how loudly to announce it; rules on series turn numbers
   into alerts (§8).

## 4. Spaces: where outputs live

Every level of the dash gets a space. The space is what that level's page
shows besides its cards and tasks.

| Space | Address | Shown on | Stored in |
|---|---|---|---|
| Home | `home` | Overview (`/`) | `$WPK_HOME/space/home/` |
| Board | `board:<b>` | `/b/<b>` | `$WPK_HOME/space/board/<b>/` |
| Project | `project:<p>` | `/p/<p>` (a new **Space** tab) | `<project>/.work-packet/space/` |
| Packet | `packet:<p>/<wpid>` | the task page | the run directory, as today |

- A project's space lives in the project folder, so it moves with the
  project (packets are not tied to git or to one host). Home and board
  spaces are shared state and live in `$WPK_HOME`.
- The packet "space" is what the packet already has (report, deliverables,
  notes). It is listed for completeness; nothing new is stored there.
- Outputs **roll up for display, never for storage.** The board shows its
  own space plus a summary line per project space ("strategy page updated
  3 days ago; 2 open items"). The side tab shows a dot on each board with
  unread items; **Needs you** gathers the alerts from every space (§9).
- Deleting a board moves its projects to `main` today. Its space should
  move to `space/board/main/` with its items tagged by the old board name,
  so nothing is lost.

Layout of one space:

```
space/board/fvutils/
  items/<key>.json          one file per item (current state); items.jsonl is its log
  items.jsonl
  series/<name>.toml        the definition: unit, kind, chart, rules
  series/<name>/2026-10.jsonl   points, one file per month
  pages/<name>/page.toml    title, pinned, who publishes it
  pages/<name>/v0007.md     each version; the newest is the page
  log.jsonl                 every publish into this space, with its producer
```

Files are the truth, as for the scheduler (runner.md). `index.db` indexes
items and the last point of each series so the Overview stays fast; it
can be rebuilt from the files.

## 5. The four kinds of output

### 5.1 Tasks

New packets on a board, as watchers make today.

```json
{"key": "ci:fvutils/pyvsc:main", "board": "fvutils", "starter": "issue-fix",
 "title": "Fix pyvsc CI on main (red since Sat)", "brief": "…",
 "refs": ["https://github.com/fvutils/pyvsc/actions/runs/…"], "hold": true}
```

- **`key` is required and is the dedupe.** If a live packet already has
  this key as its origin, nothing new is made; the existing one gets a note
  ("still failing as of Mon 2026-11-09"). Watchers already do this with
  the issue URL; this generalises it.
- `hold = true` by default, as for watchers: a person starts it.
- `max_new` per run, as for watchers, so a confused agent cannot file 200
  packets.
- Made through `starters.make`, so a task from a routine is the same as
  one from `/new`.

### 5.2 Items

A small, keyed record that someone should see: a finding, a warning, a
link to look at. This is social.md's "finding" in its local form, and it
is what a board's **Findings** list holds (§9).

```json
{"key": "ci:fvutils/pyvsc:main", "title": "pyvsc main is red",
 "body": "3 runs failed since Sat 02:10. First bad commit a1b2c3 …",
 "severity": "warn", "state": "open",
 "links": [{"label": "run", "url": "…"}], "task": "ci:fvutils/pyvsc:main"}
```

- Lifecycle: `open` → `seen` (someone looked) → `done` or `dismissed`, by
  a person; or `resolved` by the producer.
- **Republishing a key updates the item; it does not add one.** So a
  routine can say "still red" or "now green, `state: resolved`", and an
  item drops out of the open list (and out of Needs you) by itself when the condition clears. A
  dismissed item stays dismissed until its content changes materially (the
  producer bumps `rev`).
- An item can point at a task it caused (`task`), and the dash shows the
  link both ways. "Make a task from this" on an item calls the same
  starter path.
- `severity`: `info`, `warn`, `alert`. It sets the default loudness
  (§8).

### 5.3 Series

Numbers over time, for charts and for alerts.

`series/ci-red.toml`:

```toml
title = "Red pipelines"
unit = "count"          # count, usd, pct, seconds, or free text
kind = "gauge"          # gauge (a reading) or counter (adds up per period)
chart = "line"          # line, bar, stacked (by label)
labels = ["repo"]       # optional: one line per label value
[[rule]]                # §8
when = "value > 0"
for = "2 runs"
notify = "badge"
```

A point:

```json
{"series": "ci-red", "t": "2026-11-02T07:00:12Z", "value": 3,
 "labels": {"repo": "pyvsc"}}
```

- The **first point publishes the definition** if none exists (from the
  routine's declaration, §6), so an agent never has to write TOML.
- The latest value is a **tile**: a board can pin series tiles to its
  header ("Red pipelines 3 ▲2"). A categorical "health" view (each repo
  green/red) is a series with `unit = "state"` and values from a fixed
  list, shown as a row of chips instead of a line.
- Rendering reuses `tokens.chart`, which already draws stacked bars with
  tooltips. The dataviz rules in docs/stats-spend.md (bars, not pies)
  carry over.
- The cost and token series we already chart are, in this model, series
  in the home space that wpk publishes itself. We don't need to move them,
  but they should look and behave the same.

### 5.4 Pages

A document with versions: a strategy, a weekly digest, a status report.

```
pages/strategy/v0003.md
---
title: Strategy, 2026 Q4
summary: Ship the AXI port; park the CHI study; two risks.
period: 2026-Q4
---
## Where we are
…
```

- **The newest version is the page; older versions stay** and are
  listed with their summaries. "What changed" shows a diff against the
  previous version, which is usually what a reader wants from a periodic
  page.
- `summary` is required. It is what shows in the space strip, the unread
  list ("Strategy, 2026 Q4 published") and a push.
- A page can be **pinned** to its space's header.
- Markdown is rendered with our own markup (`dash/markup.py`), so links
  to packets, steps and other pages work. A page can attach files
  (images, CSV) the same way deliverables are attached.
- A Sphinx docset is the heavyweight kind of page. Later, `docs.py`
  builds could appear in the same Pages list, with "rebuilt" as their
  version. Not needed for the first cut.

### 5.5 Why not fewer kinds?

- Items vs tasks: an item costs nothing to keep and is seen; a task costs
  tokens when it runs. "Pipeline red" should not always be a packet.
  Keeping both lets a routine say "here is what I saw" without committing
  someone to work.
- Items vs pages: items are many, small, and keyed; a page is one long
  thing with a history. An agent that dumped findings into a page would
  lose dedupe and per-item state.
- Series vs items: a number per run is a point, not a thing to read.

## 6. Routines

### 6.1 A routine is a project; each firing is a task

This answers roadmap.md's open question ("one packet forever, or a fresh
one per run?"): **a fresh child per run, under one routine project.**

- The routine is a registered project on a board, like any other, with a
  `[routine]` table in its `project.toml`.
- Each firing makes a child task `ci-health · 2026-11-02`. The project's
  Tasks tab is then the routine's run history, its Cost tab is what the
  routine costs, and each run's page shows exactly what it published.
  No new dash level is needed.
- A run that fails doesn't break the cycle: the executor re-arms the
  routine, not the task (roadmap.md design rule 2).
- A run is kept small: the outputs live in the space, so old runs can be
  harvested and archived like any packet.

```toml
[routine]
every = "mon 07:00"            # or "1st of quarter 09:00", "daily 06:30", "4h"
tz = "America/Los_Angeles"
brief = "brief.md"             # what each run is asked to do
probe = "scripts/ci_probe.py"  # optional; §6.3
publishes = [                  # where it may write; anything else is refused
  "board:fvutils/items",
  "board:fvutils/tasks",
  "board:fvutils/series/ci-red",
]
max_new = 5
budget = "$1.00"               # per run
overlap = "skip"               # skip (default) or queue, if the last run hasn't finished
```

### 6.2 Each run sees what the last runs published

A routine is only useful if it compares with last time. The run's prompt
gets, from the spaces it publishes into:

- the items it owns that are still open, with their keys, so it updates
  rather than duplicates;
- the newest version of each page it publishes, and the date;
- the last few points of each series it writes;
- the time of the run, the time it was due, and how late it is
  (roadmap.md design rule 4).

This replaces "keep notes in state/ and hope the next step reads them".
The space *is* the routine's memory, and people can see it.

### 6.3 Probes: don't pay an agent to find nothing

Most runs of a monitoring routine find nothing. A **probe** is a command
run before the agent, in the routine's folder, with no model.

- It may publish (through `wpk publish`, §7.2): typically a series point
  and item updates ("all green, `resolved`").
- Its exit status decides whether the agent runs: `0` "nothing more to
  do", `10` "run the agent" (with whatever the probe wrote to
  `probe.json` as extra input), anything else is a probe failure (shown
  on the run, and the routine stays armed).
- A routine with only a probe and no brief is a pure script on a timer.
  **A watcher is exactly that**: its probe polls the trackers and
  publishes tasks. Watchers can become routines later (§10, R6) without
  changing what they do.
- A DFM flow can be a probe (`dfm run …`), which fits the DV users'
  existing checks.

For CI health the probe calls the GitHub API, writes the `ci-red` points,
resolves items for pipelines now green, and calls the agent only if
something is newly red. The agent's job is the part that needs judgement:
read the logs, find the first bad commit, write a useful item and a task.

### 6.4 Triggers other than time

Not for the first cut, but the scheme should not prevent them: `on =
"push:fvutils/*"`, `on = "series ci-red > 0"`, `on = "page strategy
changed"`. They are just other ways to fire the same routine.

## 7. How outputs get in

### 7.1 From an agent: `.pending/publish/`

The protocol already says the agent writes only under `.pending/`. Add:

```
.pending/publish/
  items.jsonl      one item per line
  tasks.jsonl      one task per line
  series.jsonl     one point per line
  pages/<name>.md  a new version of a page, front matter as in §5.4
```

- Addresses default to the routine's first matching `publishes` entry, so
  the agent usually writes no address at all.
- The executor validates at commit. A bad line, an address not in
  `publishes`, or more than `max_new` tasks makes the step fail to commit
  with a message the agent sees on its next step, as for a bad memento.
- Outputs are applied **in the same commit as the step**: if the step
  doesn't commit, nothing is published. Each publish is recorded with
  its producer (project, wpid, step), so every item, point and page
  version links back to the step that made it.
- The protocol prompt gains a short section, shown only to packets whose
  project has a `[routine]` or `publishes` (so ordinary packets pay no
  prompt tokens for it).

Any packet, not only routines, may be given `publishes` in its settings.
A research packet that ends with a page in its board's space is just as
useful.

### 7.2 From a script: `wpk publish`

```
wpk publish item  board:fvutils --key ci:pyvsc:main --title "…" --severity warn
wpk publish point board:fvutils ci-red 3 --label repo=pyvsc
wpk publish page  board:fvutils strategy page.md
wpk publish task  board:fvutils --key … --starter issue-fix --title "…"
wpk publish -f outputs.jsonl          # many at once, same format as §7.1
```

- Inside a probe, `WPK_PUBLISH_AS` names the routine, and the same
  `publishes` check applies.
- Outside a routine (cron, CI, by hand), it publishes as the person
  running it. That lets any existing script feed a board's charts.
- One code path for the dash, the CLI and the executor, as for
  `sched/control.py`.

## 8. Notification

Loudness is per output, with defaults by kind, overridable by the
producer and, more importantly, by the person (who decides what reaches
their phone).

| Level | Meaning |
|---|---|
| `quiet` | Stored and shown in its space. Nothing else |
| `badge` | Counts as unread in its space: a dot and count on the board in the side tab |
| `needs` | A request for input: listed in **Needs you** until someone acts |
| `push` | Also sent to the push channel (ntfy, product.md D7) and the browser |

| Output | Default |
|---|---|
| Task | `badge`, through the existing Needs attention once it stops or needs you |
| Item | `info` → `quiet`, `warn` → `badge`, `alert` → `needs` + `push` |
| Page version | `badge`, with the page's summary as the text |
| Series point | `quiet`; a **rule** firing → its `notify` level |

- **Rules** on series are evaluated by wpk, not by the agent: `value > 0`,
  `value > 1.5 * avg(4)`, `for = "2 runs"`. A rule that fires makes an
  item (`key = rule:<series>:<rule>`) and resolves it when the rule
  stops holding. So alerts are items too, and an alert lands in Needs you
  like any other request for input.
- **Unread is per person.** It reuses the `seen` mechanism behind Needs
  attention, extended from packets to items and page versions.
- **Digest instead of a stream.** Settings per person: push now, or
  batch into one message at a chosen time ("weekday 08:30 digest").
  social.md's "batched, budgeted inbox" points the same way.
- A routine that publishes 40 items in one run causes one push ("ci-health:
  6 new, 2 resolved"), not 40.

## 9. On the dash

Three lists, kept apart because they ask different things of you:

| Side tab | Holds | Asks you to |
|---|---|---|
| **Needs you** (new) | True requests for input: open questions (`ask:`), packets stopped on a failure or a limit, held tasks waiting to be started, and `alert` items (including series rules that fired) | Answer, decide or act. Its count is what's waiting on you, nothing else |
| **Inbox** (placeholder today) | Incoming requests: work others send you (teammate deliveries, product.md §11) and requests from other projects (`requests.py`) | Accept or decline |
| A board's **Findings** | The board's open items (`info`, `warn`), newest first, with filters (severity, routine) | Read when you like. Unread shows as a dot and count on the board in the side tab; nothing pushes |

- Actions on an item, wherever it shows: open, mark seen, dismiss, make a
  task.
- A routine never writes to the Inbox. Its outputs land in its space, and
  only alerts reach Needs you.
- Finished work you haven't looked at (today's "Needs attention" on the
  Overview) is not a request for input. It stays on the Overview as
  "New since you looked", beside new page versions.
- **Overview**: the home space's pinned tiles and pages; a line per board
  with its open items; "next runs" lists routines with their next firing
  (the existing "what runs and wakes next" panel).
- **Board page** (`/b/<b>`): a strip above the columns with pinned tiles
  (series) and pinned pages; below it, the board's Findings. A
  **Routines** list replaces the Watchers list: each with schedule, last
  run (ok/failed, cost), next run and "Run now".
- **Project page**: a **Space** tab with its pages, items, charts; a
  routine project's **Tasks** tab is its run history.
- **Run page** (a routine's task): what it published, each linked to
  where it now lives.
- **Page view** (`/b/<b>/page/<name>`, `/p/<p>/page/<name>`): the page,
  a version list with summaries, "changes since v6".
- **Series view**: the chart with rule lines, and each point linked to
  the run that wrote it (the dashboard-is-central rule: history must stay
  navigable).

## 10. Plan

Each step is useful by itself.

| Step | What | Uses |
|---|---|---|
| **R1** | Space store (home, board, project) and `wpk publish` for items, points and pages; board page shows items, tiles and pages | files under `space/`, `tokens.chart` |
| **R2** | `.pending/publish/` in the protocol; validation and commit in the executor; provenance links | executor commit path |
| **R3** | Routines: `[routine]`, `every:` (clock.py's Stage 2), fresh task per firing, catch up once, `overlap`, "Run now"; prompt gets the space context (§6.2) | runner loop beside `_watch_loop` |
| **R4** | Probes, with exit-code gating | R3 |
| **R5** | Needs you side tab, per-space unread, series rules, ntfy push, digest | `seen`, product.md §7.3 |
| **R6** | Tasks as an output with key dedupe; watchers re-expressed as routines with a probe; Sphinx docsets listed as pages | `watch.py`, `starters.make`, `docs.py` |

Worked examples to build against: CI health (R1–R4, R6) and quarterly
strategy (R1–R3: one page per run, no probe).

## 11. Decisions (taken 2026-10-30)

1. **Names: "routine"** for the periodic thing, **"space"** for a level's
   published area.
2. **A routine is a project with a fresh task per run** (§6.1), not a
   `[[routine]]` table on the board. The stored history (runs, cost,
   what each run published) is worth the extra card on the board.
3. **Three lists, not one Inbox** (§9). The Inbox is for incoming
   requests. A new **Needs you** pane holds true requests for input,
   alerts among them. Other findings stay in their space.
4. **Project spaces travel with the project** (`.work-packet/space/`);
   board and home spaces stay in `$WPK_HOME`. Bundling a board's space for
   a teammate or hub is a later problem.
5. **Items resolved by the producer** leave the open list without a
   person acting, but stay visible, struck through, for 7 days.

Still open from the review: whether `warn` items should also be able to
reach Needs you (e.g. by a per-board setting), or only `alert`.

## 12. Open questions

- **Ownership of a key across routines.** Two routines publishing the
  same item key: last writer wins, or keys namespaced by routine? Proposal:
  namespaced by default (`ci-health/ci:pyvsc:main`), shared only when
  both declare it.
- **Retention.** Series points are small; keep forever? Page versions
  forever? Dismissed items for 90 days?
- **Who may publish to `home`.** Probably only wpk itself and routines
  the owner marks as such.
- **Multi-user.** Unread is per person; is dismiss per person or for
  everyone? Proposal: dismiss is for everyone on that board, seen is per
  person.
- **Budget across runs.** A per-run budget is easy. A monthly cap per
  routine (stop firing when exceeded) belongs in the scheduler's budget
  (`sched/budget.py`), which already has a ledger.
- **External publishing.** A page or digest copied to Slack, email or a
  GitHub discussion. social.md says syndicated copies, never the source;
  that fits as one more `notify` target per page.
