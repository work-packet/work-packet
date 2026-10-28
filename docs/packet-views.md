# Viewing packets: one view model, three surfaces (design, 2026-10-27)

Status: a design for review. Nothing here is built. Consolidated into
`docs/work-data-design.md`, which wins where the two differ. It goes with
`docs/packet-card.md` (the format) and `docs/packet-page.md` (the
dashboard's packet page), and it serves the rule that history must stay
navigable: with many packets running, you review the work by browsing
what happened, not by reading files.

## 1. One view model

Today `dash/data.py` is the dashboard's view model: plain Python that
turns the packet's files into dicts the templates render (`tree`,
`tasks`, `card`, `packet`, `report`, `step`, `transcript`, …). It has
no web code in it, but only the dashboard uses it, and the CLI's `show`
and `log` work out the same things a second time.

**Proposal:** move it to `work_packet/view/`, have it read cards and run
records (`packet-card.md`), and make it the only reader for every
surface.

```
 cards (.wp.md) ─┐                              ┌─► web (dash: Jinja templates)
 run records ────┼─► index.db ─► view/ ─► dicts ┼─► CLI (wpk show, log, ls: text or --json)
 blobs, jobs ────┘   (cache)                    └─► TUI (wpk browse: Textual widgets)
```

- Every view function takes a target (a name with an optional `@rev`)
  and returns a dict that is also the `--json` output, so scripts and
  agents get exactly what people see.
- No surface computes anything itself. A fact one surface needs goes in
  the view model, and then all three have it.
- The view model has two backends: active run records, and the history
  store for packets that have left the board (`docs/run-history.md` §5).
  Views look the same on both.
- The surfaces differ only in reach: the web for sharing and the
  phone, the TUI over ssh to a cluster login node with no port
  forwarding, the CLI for scripts and quick looks.

## 2. What there is to look at

| Object | Holds | Comes from |
|---|---|---|
| **Home** | needs you, running, updated, yours idle | the index |
| **Packet** | the card: front matter, refs (reachable or not), the thread | the card |
| **Task** | one request→result: instruction, steps, cost, report, deliverables as they were at its end | the card's entries plus `tasks/NNNN/` (`history.md`) |
| **Step** | summary, diff of the work, the plan and the report as of that step, questions, notes seen, cost and tokens, transcript | `steps/NNNN/` |
| **Tree** | sub-packets, nested, each with its state | `parent` links in the index |
| **Job** | a long-running tool run: progress, log tail, exit | `jobs/<id>/` |
| **Files** | the workspace, or a deliverable as it was at a step | the workspace, `steps/NNNN/deliverables/` |

### 2.1 What the record must keep for this to work

Stepping back through history means seeing each thing **as it was**.
The run record already keeps a step's summary, diff, report and
deliverables. Two gaps:

- **The plan and notes as of each step.** `steps/NNNN/state.diff` holds
  a diff, not the state. The run record's hidden git repo
  (`packet-shapes.md` §4.1, option C, decided) fixes this cheaply: one
  commit per step of the record's files, so the outline at step 4 is
  `git show <step-4 commit>:state/outline.md`. Readers that don't use
  git can replay the diffs.
- **The card as of a step.** Nothing is needed: entries carry times,
  and the card as of step 4 is the entries up to step 4's end.

## 3. Points in history: `@rev`

Every view takes a target with an optional revision, the same on every
surface (`packet-card.md` §5.2):

| Rev | Means |
|---|---|
| none | now |
| `@s7` | step 7, at its end |
| `@t2` | task 2, at its end |
| `@-1`, `@-3` | one or three steps before the last |
| `@2026-10-27T10:00` | the last step that ended before that time |
| `.child` | a sub-packet: `uart-overrun.seed17@s2` |

A dashboard URL takes the same form (`/p/uart-overrun@s7`), so a link
pasted from the terminal opens the same view.

## 4. The CLI

| Command | Shows |
|---|---|
| `wpk` | the home screen (`packet-card.md` §10.2) |
| `wpk ls [filters]` | one line per packet. Filters are `key:value` terms over the index: `state:needs-input`, `to:runner`, `tag:uart`, `origin:gh:*`, `since:2d` |
| `wpk show <target>` | the card, rendered: state, refs, the thread folded to the latest exchange (`--all` for the whole thread) |
| `wpk log <target>` | the history like `git log --graph`: tasks, their steps one line each (time, cost, summary), sub-packets as branches, entries from other parties inline. `-p` adds each step's diff |
| `wpk report <target>` | a task's report, `@t2` for an earlier one, with deliverables as they were then |
| `wpk step <target>@s7` | one step: summary, diff, plan, questions, cost; `--transcript` for the transcript, tool calls folded |
| `wpk diff <target>@s4 @s9` | what changed between two points: work, plan, report, thread |
| `wpk watch <target>` | follows a packet live: new entries, step ends, job progress, until you stop it or the task ends |

Common to all of them:
- `--json` prints the view model's dict;
- Markdown is rendered with Rich when it is installed and printed plain
  when it isn't, or when the output is not a terminal;
- long output goes through `$PAGER`, as git does.

## 5. The TUI: `wpk browse`

A Textual app, in the `tui` extra the setup wizard already uses
(`work-packet[tui]`). It is a read-and-act browser, not an editor.

```
┌ wpk browse ─────────────────┬──────────────────────────────────────────────────────┐
│ Needs you                   │ uart-overrun · done · runner · 1.84 USD · 7 steps    │
│ > uart-overrun         2h   │ [h]ome [t]hread [r]ecord [f]iles                     │
│   pss-regs.pssc-req    5m   │                                                      │
│ Running                     │ task 1  ●──●──●──◆──●──●──●                          │
│   riscv-survey  s6  0.90$   │                  ▲ step 4 · 10:02 · 0.31 USD         │
│   ├ .cache-papers  working  │ ── step 4 ────────────────────────────────────────── │
│   └ .formal-tools  done     │ Summary  Found OE gated on fifo_empty in uart_regs.sv│
│ Updated                     │ Asked    q1: clear OE on every read, or when empty?  │
│   fifo-depth          new   │ Diff     uart_regs.sv +3 −1 · tests/test_lsr.py +40  │
│ Yours, idle                 │ Plan     [x] reproduce [x] locate [ ] fix [ ] test   │
│   spi-port            2d    │ Cost     0.31 USD · 41k in / 3k out · 2m10s          │
└─────────────────────────────┴──────────────────────────────────────────────────────┘
 [ ] step  { } task  d diff  p plan  o report  x transcript  a answer  R run  e edit  q quit
```

**Left: the list.** The home screen's sections, with sub-packets folded
under their parent. `/` filters with the same terms as `wpk ls`.

**Right: the selected packet, in tabs.**
- **Thread**: the card as a conversation, newest at the bottom, with
  questions waiting on you highlighted.
- **Record**: the history browser (below).
- **Files**: the workspace tree, or, at a past step, the deliverables
  as they were.

**Stepping through history**, on the Record tab:
- a timeline of steps per task, with question (◆), failure (✗) and
  sub-packet (┬) marks;
- `[` and `]` move one step back and forward, `{` and `}` one task;
  `g` jumps to a step number or a time;
- everything on the right is shown **as of the selected step**: its
  summary, its diff, the plan, the report so far, the thread up to that
  point;
- `d`, `p`, `o` and `x` open the step's diff, plan, report and
  transcript full-screen; `D` diffs the selected step against another
  you mark with `m`;
- `Enter` on a sub-packet opens it, and `Backspace` comes back.

**Acting**, so a browse doesn't end in a second terminal:
- `a` answer the questions waiting on you, in a form built from the
  question's `Choices`;
- `R` run or hand off, `W` take it back and work (suspends the TUI and
  starts the agent, as the wizard's F2 shell does), `n` add a note;
- `e` the card in `$EDITOR`, `O` the workspace in the IDE, `y` copy the
  target with its `@rev`, for pasting into a note or a chat.

**Live.** The list and the open packet refresh when cards or records
change: by watching the files on the same host, and by the hub's event
stream when browsing remote packets. The selected step never moves
while you look at it; a "new: step 8" marker appears instead.

## 6. The web

The dashboard keeps its pages (`packet-page.md`) and reads the same
view model:
- the packet page leads with the thread (the issue view), with the
  Record tab beside it;
- the step timeline has the same marks and the same `[`/`]` keys, and
  the URL carries the `@rev`;
- what only the web does: sharing a link, the phone, comments with
  CriticMarkup (`doc-markup.md`), charts (`token-dashboard.md`), and
  the IDE in the browser.

## 7. What each surface does

| | CLI | TUI | Web |
|---|---|---|---|
| Home, lists, filters | ✓ | ✓ | ✓ |
| Read the thread | ✓ | ✓ | ✓ |
| Step through history with `@rev` | ✓ (one view at a time) | ✓ (scrubbing) | ✓ |
| Diffs, plans, reports as they were | ✓ | ✓ | ✓ |
| Transcripts | ✓ (paged) | ✓ (folded) | ✓ (folded) |
| Answer, run, note, take back | ✓ | ✓ | ✓ |
| Live updates | `watch` | ✓ | ✓ |
| Over ssh, no browser | ✓ | ✓ | |
| Share a link, phone, comments, charts | | | ✓ |
| `--json` for scripts and agents | ✓ | | the API |

## 8. Open questions

| # | Question | Default |
|---|---|---|
| V1 | One `wpk browse`, or the TUI as what bare `wpk` opens on a terminal? | Bare `wpk` prints the home screen and exits; `wpk browse` is the TUI. Printing composes with scripts and scrollback |
| V2 | Rich as a hard dependency for the CLI's rendering? | No: optional, with plain text as the fallback |
| V3 | How long are transcripts kept, given they are the bulk of a record? | All, until the packet is archived; then by the export profile |
| V4 | Does the TUI browse remote packets through the hub, or only local ones? | Local first; the hub's API later, with the same view model behind it |

## 9. A slice

1. Move `dash/data.py` to `view/`, reading cards and run records, with
   `--json` tests that pin each view's dict. The dashboard keeps working
   on top of it.
2. `@rev` resolution, and the plan as of a step from the record's git
   repo.
3. CLI: `wpk`, `ls` with filters, `show`, `log`, `step`, `report`,
   `diff`.
4. `wpk browse` read-only: list, thread, and the Record tab with
   stepping.
5. Then its actions (answer, run, note, work) and live refresh.

## Status

- 2026-10-27: design written. Nothing built.
