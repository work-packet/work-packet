# Work sessions: start it in a terminal, hide it, watch it on the board (direction, 2026-10-27)

Revised the same day: §3.5, an agent scribe that writes the notes people skip.

See `docs/work-data-design.md` §13.4 for how runs, person-steps and the
scribe fit the packet and run-record design. There the scribe also
drafts turnover notes and closing summaries, and its drafts become card
entries only when the person accepts them.

Status: a plan (§5) with assumed answers to its questions (§4). Nothing
here beyond what is marked "built" exists. It joins three designs that are already written:
sessions (`docs/product.md` §8), jobs and progress (§9) and the
messaging note (`docs/positioning/messaging.md` §3a, §5.3).

## 1. The flow

1. On the board, open a **session** on a packet: a terminal, one of
   several tabs in the packet's pane.
2. Work in it as in any terminal: set things up, then start a long
   run, say `dfm run sim`.
3. **Hide it.** Close the tab or the page. The run goes on.
4. The board shows the run under its packet: what is running, for how
   long, and for dv-flow-mgr its progress and task graph.
5. When the run ends, the board says so (a notice, and the packet under
   "Needs you"). Click through to the session, as it was left, or to
   the run's record: command, directory, commit, exit code, log.

The person never types `wpk job`. The session is where the work
starts; the packet is where its record lands.

## 2. What exists, and what is in the way

| Piece | State | Note |
|---|---|---|
| Browser terminals with tabs, replay on reattach | built (`dash/shells.py`, `docs/dash-tasks.md` §5) | xterm.js over a WebSocket |
| A prompt hook that reports to the server | built: `PROMPT_COMMAND` prints a private OSC (`ESC ] 7777 ; wpk-recheck BEL`) that the server strips | used only to rerun the setup checks today |
| Sessions that survive the server, idle vs active | designed (`product.md` §8: `wpk _hold`, tmux backend, `tcgetpgrp`) | not built |
| Jobs, progress lines, adapters (dfm, pytest, make, SLURM) | designed (`product.md` §9) | not built |
| Notices when something finishes | designed (`product.md` §7.3) | not built |

**One thing in the way today:** `shells.py` ends a session 30 minutes
after its last socket goes away (`IDLE_S`), whatever it is running.
Hiding a tab during a two-hour sim kills the sim. §8's rule fixes
this: a session whose foreground process is not the shell is
**active** and is never reaped. That rule should come first, before
any of the rest.

## 3. The design, in five pieces

### 3.1 Sessions that a hidden run cannot lose

`product.md` §8 as written: the `wpk _hold` holder (or tmux) owns the
pty, so a session outlives the page and the server. Active sessions are
never reaped. An idle one is dimmed, then reaped, and can be restored
in the same place.

### 3.2 Runs: commands in a session, recorded without `wpk job`

Extend the prompt hook to mark each command's start and end. Bash's
`PS0`/`DEBUG` trap, or zsh's `preexec`/`precmd`, prints:

```
ESC ] 7777 ; wpk-run-start ; <id> ; <cwd> ; <command> BEL
ESC ] 7777 ; wpk-run-end ; <id> ; <exit code> BEL
```

The holder strips both and records a **run**:

- every command that lasts longer than `run_min_s` (say 60 s) goes in
  the packet's history, as an entry by a person: command, directory,
  `work/` repo HEADs, start, end, exit code, and the log, as the slice
  of the session's output between the two marks;
- shorter ones are not recorded, so `ls` and `git status` stay out of
  the history.

A run is a job that started in a terminal (§9.1). It shares a job's
record (`jobs/<id>/`: `job.json`, `log`, `progress.jsonl`, `exit`), so
the board, the history (`docs/history.md` §2.5) and `resume: wait job:`
treat both the same. What differs is that a run keeps its terminal: it
can be interactive, and the person can come back to it.

### 3.3 Progress from inside a session

When a run starts, the hook sets `WPK_PROGRESS` to that run's
`progress.jsonl` for the command, so any tool that speaks the progress
protocol (`product.md` §9.2) reports into the right run with no
wrapper.

For dv-flow-mgr this changes the plan. §9.4's adapter works by adding
`-u log -v` to the command and reading its log, which a person typing
`dfm run sim` in a terminal bypasses. Two ways round it:

- **dfm writes progress natively when `WPK_PROGRESS` is set** (graph
  once at the start, then node state changes). Since dv-flow-mgr is
  ours, this is the better route. It is also the survey's "first Level 3
  producer outside wpk" (`positioning-survey.md` §7), and it serves
  agent-started jobs the same way.
- Until then, the session's rc file defines a `dfm` shell function that
  runs the real `dfm` through the adapter.

The board then shows the latest message, a bar when the total is
known, and the task graph coloured by node state (§9.2).

### 3.4 The board

- Each packet shows its sessions as tabs, and its runs: running, with
  elapsed time and progress, or finished.
- A finished run that has not been looked at puts its packet under
  **Needs you**, next to agents waiting on answers.
- A notice (browser, desktop, phone) when a run ends, with its exit
  code and last progress line.
- Across packets, one list of everything running, agents and runs
  alike. That list is what replaces the pages of terminal windows.

### 3.5 A scribe: the agent writes the notes people skip

An agent step leaves a summary, a log entry and, at the end, a report,
because the protocol makes it. A person's work leaves none of that:
nobody writes turnover notes after a sim. That is the gap the method
exists to close (`positioning-survey.md` §1, the turnover discipline),
and an agent can close it for people at little cost.

The **scribe** is a short, cheap agent call (a small model, no tools;
wpk hands it a bounded extract of the record, §4.5) that writes what
the person would not:

| When | Reads | Writes |
|---|---|---|
| A run ends | the command, exit code, log (head, tail and errors), progress, `work/` diffstats since the run started | a one-paragraph summary on the run: what ran, what happened, the first real error |
| The session goes idle, or the person closes it | the session's runs and their summaries, `state/` changes, `work/` diffstats (shell history only if the project opts in) | an entry in `state/log.md` and a step summary, so the person's stretch of work shows in the history like an agent's step |
| The person hands off or finishes | the task's runs, summaries, outline | a draft completion report (`docs/completion-report.md`) for the person to accept or edit |
| Any of the above | the same | suggested next actions and open questions, shown on the board, never acted on |

Rules:

- **It records, it does not act.** It writes only to the record (the
  run's summary, `state/log.md`, a draft report), never to `work/`, and
  never starts anything.
- **Marked as drafted.** Everything it writes says it was drafted by
  the scribe, until the person accepts or edits it. A draft report is
  not the person's report until they say so.
- **Opt-in per project, and local where it must be.** Logs from a
  silicon project may be under NDA (`positioning/onprem.md`). The scribe
  uses the project's configured model and harness; a project that
  allows no outside model gets no scribe, or a local one.
- **Cheap by design.** One call per event, on a bounded input (log
  head, tail and error lines, not the whole log). Its cost goes on the
  packet's metrics like any step's.

This also changes the messaging: the method's discipline (turnover
notes, a record per step, a report at the end) stops being a cost the
person pays. **People do the work; the record writes itself.**

## 4. Decisions (assumed 2026-10-27; revisit if use says otherwise)

1. **Runs outside the board: yes, second.** Board sessions come first,
   because their holder sees the output and can keep each run's log.
   Later, `eval "$(wpk hook bash)"` (or `zsh`) in any terminal (VS Code,
   SSH, tmux) records runs too, but without the log, since nothing
   captures that terminal's output: command, directory, times, exit
   code, repo HEADs. The hook appends one line per mark to a file
   (`printf >>`, no process started), so it adds no delay to the
   prompt; the server picks the lines up. `wpk job -- <cmd>` in such a
   terminal gets the log as well.
2. **Which commands count: a threshold, an ignore list, and a way to
   force it.**
   - Recorded if it runs longer than `run_min_s` (default 60 s).
   - Never recorded, however long: interactive programs that are not
     runs (`vim`, `nvim`, `emacs`, `less`, `more`, `man`, `top`, `htop`,
     `ssh`, `tmux`, `screen`, shells, `python` or `ipython` with no
     arguments). The list is `[sessions] run_ignore`, extendable.
   - Always recorded: anything started with `wpk job -- …`, whatever its
     length.
   - Prefix wrappers (`time`, `nice`, `env`, `sudo`) are skipped when
     matching.
3. **Farm jobs: the run follows the batch job.** For a recognised
   submit command (`sbatch`, `bsub`), the run reads the job ID from its
   output (`Submitted batch job N`, `Job <N> is submitted`), stays
   open, and polls `sacct` or `bjobs` until the batch job ends. Its exit
   code and end time are the batch job's. Blocking forms (`srun`,
   `bsub -K`) are ordinary runs. Other schedulers report through the
   progress protocol.
4. **Several packets, one terminal: the directory decides.** A run goes
   to the packet whose workspace holds its working directory at start,
   found as in `docs/work-data-design.md` §6.6 (a card, a `.packet`
   pointer, `$GIT_DIR/packet`, or a workspace folder
   `~/packets/<name>/`); otherwise to the session's packet. The
   board shows the run under that packet and marks it as started from
   another packet's session.
5. **What the scribe reads, by default:**
   - the run's command, exit code, times and progress;
   - its log, bounded: the first 100 lines, the last 200, and up to 50
     lines around error patterns;
   - `git diff --stat` of each `work/` repo since the run started, not
     the diff itself;
   - changes to `state/`, in full, since those are the work's notes.

   Opt-in per project (`[scribe] read`): `history` (shell history for
   the session) and `diffs` (full diffs of `work/`). Nothing outside the
   packet, ever.
6. **The scribe is its own light mechanism, not a step.** A step takes
   the lease, advances the step count and replaces `state/`, which
   would clash with a person who owns the packet and is working in it.
   So `work_packet/scribe.py`:
   - builds its input itself (§5 above), so the call needs no tools,
     and its size and cost are bounded;
   - calls the project's harness with a `scribe` profile: a small
     model, no tools, a short system prompt;
   - records each call as a `scribe` journal record with its cost and
     tokens, so it counts in the packet's metrics like a step;
   - takes no lease and never changes `memento.md`, `status.md` or
     `work/`.

   Where its notes go:
   - a run's summary: `jobs/<id>/summary.md`;
   - a stretch of a person's work (from the first run after the last
     agent step or stretch, to the session going idle or closing): a
     step folder `steps/NNNN/` with `worker: person` in `meta.json`,
     the summary, and the runs it covered. This is how a person's work
     enters the same history as an agent's (`docs/history.md` §2.5). It
     is only written while the person owns the packet, so it never
     races the runner;
   - an entry in `state/log.md`, marked `(drafted by the scribe)`;
   - a draft report: `report.draft.md`, shown on the board with
     Accept, Edit and Discard. Accept makes it the task's report, as a
     step's `resume: done` does.

   It is off unless the project turns it on (`[scribe] enabled`), and
   off whatever that setting says when the project allows no outside
   model.

## 5. Plan

Each stage is usable on its own. Status is kept here as each lands.

| # | Stage | Delivers | Status |
|---|---|---|---|
| 1 | Never reap an active session | `shells.py`: a session whose pty foreground process group (`tcgetpgrp`) is not the shell's is active and never reaped; the project page shows it as running | not started |
| 2 | Runs in board sessions | run marks in the rc hook (bash `PS0` and `PROMPT_COMMAND`, zsh `preexec` and `precmd`); the session manager strips them and writes `jobs/<id>/` (`job.json`, `log` slice, `exit`); `run_min_s`, `run_ignore`, wrappers (§4.2); routing by directory (§4.4); `wpk job -- <cmd>` forces a record | not started |
| 3 | Progress | `WPK_PROGRESS` per run; the `dfm` shell function through the adapter (`product.md` §9.4); native progress in dv-flow-mgr | not started |
| 4 | The board | runs under each packet; unseen finished runs under Needs you; browser notices when a run ends; one cross-packet list of everything running; a run page (command, log, exit, progress, graph) | not started |
| 5 | Farm jobs | `sbatch` and `bsub` recognised; the run follows the batch job (§4.3) | not started |
| 6 | Scribe: run summaries | `scribe.py`, the `scribe` profile, the bounded input (§4.5), `jobs/<id>/summary.md`, the journal record and its cost | not started |
| 7 | Scribe: a person's stretch | `steps/NNNN/` with `worker: person` when a session goes idle or closes; the `state/log.md` entry | not started |
| 8 | Scribe: draft reports | `report.draft.md` at hand-off or finish; Accept, Edit, Discard on the board | not started |
| 9 | Runs in any terminal | `wpk hook bash` and `zsh` (§4.1) | not started |
| 10 | Sessions that outlive the server | the `wpk _hold` holder and the tmux backend (`product.md` §8) | not started |

Stages 1–4 are the core: a sim started in a board terminal can be
hidden, watched and found again. Stage 3's native dfm progress can
proceed in dv-flow-mgr alongside, since it only needs `WPK_PROGRESS`
to be agreed. Stages 6–8 depend on 2. Stage 7 also needs
`docs/history.md` to allow steps with no model run.
