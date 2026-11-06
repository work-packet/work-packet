# Session checkpoints: current state for human-driven sessions

Status: proposal (2026-11-06). Builds on the scribe (`work-sessions.md` §3.5) and
orientation (`orientation.md` §2.2–2.3); neither is built yet.

## 1. Problem

The packet's original promise is that you can always see its current state: what was
done, where it stands, and what comes next. Autonomous steps keep that promise because
the executor writes `status.md` every step. Human-driven sessions don't:

- A studio session writes a summary only when the studio closes (`studio/record.py`
  `draft_summary`).
- A plain Claude or Codex session (in a terminal or VS Code) writes nothing. VS Code
  monitoring links the session to a packet through `WPK_WPID` but reads no content and
  writes no state.

So after a day of hand-driven work, the dash still shows the last autonomous summary.

Goal: the dash always shows a good current state for a packet, whoever did the work,
with very little extra effort from the person or the model.

## 2. Decisions

| # | Question | Decision |
|---|----------|----------|
| D1 | Does a human checkpoint update the memento (what an autonomous run resumes from)? | Only when the checkpoint gives an explicit next action. A plain status note never redirects the next autonomous step. |
| D2 | Should backstops that read the transcript be on by default? | **No.** One opt-in setting covers every session: `sessions_scribe` in the board's IDE config, next to `sessions_poll_s`. There is no per-packet setting. The board's home defaults to `~/.work-packet` (`WPK_HOME`), so for most users this one setting is effectively global. Until it is turned on, wpk keeps monitoring's rule of never reading session content. The board's owner can also switch it on and off in the dash, under any VS Code sessions table (§6, step 7). |
| D3 | Is the card's one line enough? | Probably not. Add a second line for the next action (§5). |

## 3. One way to write state: `wpk checkpoint`

```
wpk checkpoint [WPID] -m "status line" [--body FILE|-] [--next "next action"]
               [--tick ITEM ...] [--worker session|studio|scribe]
```

- WPID defaults to `$WPK_WPID` (which session terminals already have).
- It records a step through `executor.record_step(worker="session")`, the route the
  studio already uses. The Steps tab, cost totals, `history.db`, `wpk check` and the dash
  all pick it up without changes.
- The summary is `-m` (the first line) plus `--body`.
- `--next` adds a `Next: …` line to the summary. Per D1, it also rewrites the memento's
  instruction; the memento's `resume` field stays as it is.
- `--tick` marks items in `state/outline.md` as done. This is the only change it makes to
  `state/`, and it uses the same diff and commit route as a step.
- Takes the lease, as `record_step` does, so it can't race a running step. If the packet
  is running, the command refuses with a clear message.
- The studio's close switches to calling this command (worker `studio`), so there is one
  way to write state.

## 4. Triggers

### 4.1 Primary: a `/wpk-checkpoint` skill (manual)

The model in the session already has the full context, so its summary is the best and
cheapest one: no extra model call and no transcript parsing. The skill tells it to:

1. Write a status line: where things stand, at most about 80 characters.
2. Write a short body: what changed this session, and any decisions or open questions.
3. If the next action is clear, write it as one line.
4. Call `wpk checkpoint` with those, plus `--tick` for any outline items finished.

How it ships (built: `skills.py`): one `SKILL.md` for both harnesses, installed for
the user in `$CLAUDE_CONFIG_DIR/skills` (else `~/.claude/skills`) and `$CODEX_HOME/skills`
(else `~/.codex/skills`) each time the board (or `wpk ide`) opens VS Code for a packet
(`ide.resolve`). It does nothing in a session without `WPK_WPID`, so other projects are
not affected. A copy someone edited (the work-packet marker line removed) is left alone.
It runs `wpk checkpoint` (or this Python's `-m work_packet` when `wpk` is not on the PATH).

The person runs it before shutting down. Most of the value comes from this step.

### 4.2 Primary backstop: summarize when a session ends

The aim is that a packet always has a summary, even if nobody ran the skill. VS Code
session monitoring already notices when a session ends. Nothing reacts to that yet.

**How an end is detected today**
- The dash runner calls `ide_sessions.local_pass` every `sessions_poll_s` (5 s by
  default). For an IDE job, a thread on the job's host (`sched/ide_job.py`) calls
  `Collector.pass_once`.
- A session is live while its process is running: a Claude process with a
  `sessions/<pid>.json`, or a Codex process holding its rollout file open
  (`live_sessions`).
- When the process goes away, `pass_once` reads what the session wrote last and stores the
  record with `live: False`.
- When the editor closes, the launch is marked ended and gets one last pass, so every
  session in it ends.
- `/clear` in Claude starts a new session id in the same process. The old id ends the same
  way, and that is a good moment to summarize too.

**The trigger** (built: `scribe.due`, `scribe.pass_once`). One rule covers sessions that
ended and sessions left open: each session pass (the board's loop, and an IDE job's
watcher on its host) looks at the stored records and drafts for a session when all of
these hold:

- `sessions_scribe` is on (D2);
- the session is linked to a packet (`project` and `wpid` are set);
- it changed something: its `last_work_t` (the last edit or shell event, from the new
  per-category counts) is after the packet's last step, of any worker;
- it ended (a confirmed session whose process is gone, `live: false`) or has been idle
  for `scribe_idle_s` (30 minutes by default). Workspace-only matches, never live, are
  caught by the idle rule;
- its work is less than two days old (so turning it on does not draft for old sessions);
- this host can read its transcript (else the job host's watcher drafts it);
- no claim file `ide/scribe/<harness>-<session>-<work time>` exists. The claim is
  taken (O_EXCL) before drafting, so the board and a job host never both draft it, and a
  session is drafted once per burst of work.

At most one session per packet per pass (the one with the latest work). Drafting runs in
one background thread so the pass stays fast.

**The job**
- It runs outside the pass loop (the loop has to stay fast). There is at most one job per
  session, and each job has a time limit.
- It reads the last ~N KB of the transcript: user prompts, assistant text, and the names
  and targets of tool calls, not their full output.
- It makes one small model call with no tools, using `state/outline.md` and the current
  `status.md` summary as context. The call returns a status line, a short body and,
  optionally, a next action.
- It writes the result with `wpk checkpoint --worker scribe`. Per D1, the scribe never
  writes `--next` to the memento; its next action goes only into the summary text.
- If a manual checkpoint lands while the job is running, the scribe's result is dropped.

**Gaps**
- **Sessions found only by the workspace sweep.** They are always stored as
  `live: False`, so they never change from live to ended. For these, the trigger is
  being idle: no activity for `scribe_idle_s` (30 minutes by default) and no checkpoint
  since. The same rule catches sessions that stay open but are left idle.
- **IDE jobs on another host.** The end is seen on the job's host, where the transcript
  also lives. The scribe runs there, and `wpk checkpoint` writes to the packet the same
  way a job's steps already do. The local case is simple.
- **Terminal sessions outside VS Code** are not monitored. They rely on the skill and on
  the hooks in §4.3.

### 4.3 Other backstops: checked, not built

From the Claude Code hooks reference (code.claude.com/docs/en/hooks):

1. **SessionEnd hook.** It gets `session_id`, `transcript_path`, `cwd` and `reason`
   (`clear`, `resume`, `logout`, `prompt_input_exit`, `other`), runs in the VS Code
   extension too, and has a short time budget (about 1.5 s unless raised), so it could
   only queue the scribe. It would have to live in the person's `~/.claude/settings.json`
   or in each repo's `.claude/settings.json`; hooks in a skill's front matter are active
   only after the skill is invoked, so they cannot be a backstop. Its only gain over the
   monitor, which sees an end within `sessions_poll_s`, is a terminal session outside
   VS Code with `WPK_WPID` set by hand. Not built; revisit if those become common.
2. **PreCompact hook.** It cannot make the model act (no tool calls); it can only block
   or add context. The scribe reads the transcript file, which compaction does not
   remove, so it needs nothing here. Not built.
3. **Stop-hook nudge.** Possible (`decision: "block"` once, `stop_hook_active` to avoid a
   loop), but it costs a turn and also needs the global settings file. Not built.

## 5. Dash

- **Two-line card.** Line 1 is the status line, as today (`_first_line(body)`). Line 2 is
  a muted `Next: …` line, taken in this order:
  1. a `Next:` line in the `status.md` body;
  2. otherwise, for packets run autonomously, the first line of the memento instruction.

  Name this field `intent` in `dash/data.py`. The card's existing `next` field is the
  schedule (wake time or running step) and keeps that meaning.
- **Show when the summary is out of date, without a model call.** Next to the summary,
  show "as of 14:02". When a linked session has been active since the last checkpoint,
  add "· session active since · 23 edits since", using the per-category event counts
  from §4.2. The card is honest even when nobody checkpointed: an old summary is
  visibly old.
- The packet page is unchanged: it shows the whole body, and session checkpoints appear
  in the Steps table with worker `session` or `scribe`.

## 6. Plan

The main ways people use wpk are the web dash and VS Code, not the command line. So the
order puts what the dash shows, and what happens without anyone typing a command, first.
`wpk checkpoint` is still built, but as the command the skill and a VS Code task call,
not as something a person is expected to type.

| # | Step | Status |
|---|------|--------|
| 1 | The write path: `checkpoint.record()` (one function used by the dash, the scribe, the studio and the CLI), a thin `wpk checkpoint`, tests. The studio's close records through it. | done: `checkpoint.py`, `record_step(prepare=)`, `wpk checkpoint`, studio close, `tests/test_checkpoint.py` |
| 2 | Dash: the folded card shows the status line, not just "step N"; a muted `Next:` line (`intent`); "as of 14:02 · session active since" when a linked session has done more since. The packet page gets a **Checkpoint** form (status, next, body) and a **Draft from session** button that runs the scribe now. Per-category event counts in `ide_sessions`. | done (the **Draft from session** button comes with step 3) |
| 3 | The scribe (§4.2): runs on session end or idle, with Claude and Codex transcript-tail readers; off until `sessions_scribe` is on. The dash's **Draft from session** button uses the same code. | done: `scribe.py`, wired into `dash/runner.py` and `sched/ide_job.py`; `[ide] sessions_scribe`, `scribe_idle_s`; **Draft from session** fills the Update status form (asked for by the person, so it works with the setting off); `tests/test_scribe.py`. Tried on a real transcript: a usable draft for about $0.03. |
| 4 | VS Code: the `/wpk-checkpoint` skill, set up for the sessions in editors the dash opens (no install step for the person), for Claude Code and Codex. | done: `skills.py`, installed from `ide.resolve`; `tests/test_skills.py`. (A `wpk: checkpoint` VS Code task is dropped: the dash's Update status panel covers it.) |
| 5 | SessionEnd hook (§4.3), queuing the same scribe job. | not built (§4.3): little gain over the monitor, and it would mean editing the person's global Claude settings |
| 6 | Check whether the PreCompact hook can work before building it; then the Stop-hook nudge (optional, last). | checked (§4.3): PreCompact cannot make the model act, and the scribe does not need it; the nudge is not built |
| 7 | A board switch for the scribe in the dash, under each VS Code sessions table (Overview, project, packet), for the board's owner. It is kept in `ide/scribe.json` and wins over `[ide] sessions_scribe`; `config.toml` is the person's file and is never rewritten. | done: `scribe.enabled`/`set_enabled`, `POST /sessions/scribe` |

## 7. Open questions

- Should the "since" marker count only edits and commits, or all tool events?
- Should a checkpoint mark the packet `seen`? (Probably yes when the owner made it.)
- What should happen when the scribe and a manual checkpoint disagree? Proposal: the
  scribe never overwrites a manual checkpoint made after the last activity.
