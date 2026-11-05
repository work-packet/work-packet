# VS Code session monitoring: handback

The answer to the upstream request in `vscode-monitor.md`. The design, the
steps and the open questions are in `docs/vscode-monitor-plan.md`. The user
reference is `docs/vscode-plan.md` §4.5.

Status, 2026-11-04: built and tested upstream. It is **not committed**: the
changes are in the working tree of local `main` (`d57fc2d` plus uncommitted
studio work). The farm checks and the Codex items wait on the remote agent's
answers (plan, "Questions for the remote agent").

## Where to find it on the board

- **Project page** `/p/<project>`, Overview tab: **VS Code sessions** above
  Tasks. Every session of the project is listed with its packet.
- **Packet page** `/p/<project>/<wpid>`: **VS Code sessions** under the Open in
  VS Code buttons. It also has "Shared editor (packet not determined)" rows.
- **Overview** `/`: **Recent VS Code sessions**, the 8 newest across packets.

All three refresh with the page (live). Only the board's owner sees them:
loopback, unix and allowed tailnet users, or the owner on a network listener.

## Configuration

Nothing is required. Defaults, under `[ide]` in `config.toml`:

```toml
sessions           = true   # collector and sections
sessions_poll_s    = 5
sessions_keep_days = 30
```

Requirements:
- `[ide] web = true`.
- Linux `/proc` on the host running the editor.
- For editors in jobs, a `$WPK_HOME` shared with the exec hosts. A job-hosted
  editor already needs that for its `endpoint` and `token`.
- No budget provider, model call or extra listener.

## Changed files

**New:**
- `src/work_packet/ide_launch.py`
- `src/work_packet/ide_sessions.py`
- `src/work_packet/dash/templates/_vscode.html`

**Changed:**
- `src/work_packet/dash/ide.py`: launch env, `register(..., project, wpid, by)`,
  and `--launch`/`--collect` in the job argv
- `src/work_packet/dash/app.py`: `is_owner`; the packet, project-overview and
  Overview views
- `src/work_packet/dash/guard.py`: `state.owner`
- `src/work_packet/dash/runner.py`: the `wpk-ide-sessions` thread
- `src/work_packet/sched/ide.py`: `request(..., launch=)`
- `src/work_packet/sched/dispatcher.py`: records the job ref and the end on
  the launch
- `src/work_packet/sched/ide_job.py`: `--launch` and `--collect`
- `src/work_packet/harness/codex.py`: `claude_names()` factored out
- `src/work_packet/schema.py`: the `[ide] sessions*` keys
- templates `packet.html`, `project.html` and `overview.html`

**Downstream:** the change to the IDE job is in its argv and in `ide_job.py`
only. The transport (endpoint, token, proxy) is untouched, so
`u20-ide-mtls.patch` should apply as before. Check that `ide_job.py` still
merges cleanly.

## Attribution by harness and launch

*Confirmed* means a live process under the editor carried this launch's id
and named its session. *Workspace match* means no process link, but the
session's file says a VS Code client wrote it, in the editor's folder, while
the editor ran.

| Harness / launch | Local editor | LSF-hosted editor |
|---|---|---|
| Claude, VS Code extension | **confirmed**; verified live (real Claude Code 2.1.280, stream-json, `entrypoint=claude-vscode`, under a stand-in editor). Falls back to workspace match when the process is gone before a poll. | confirmed by design (same code, run by `ide_job` on the exec host); **farm check pending** |
| Claude, integrated terminal | **confirmed** while the process lives (`sessions/<pid>.json` was verified for interactive and stream-json processes). If it ended before a poll: **not attributed**, because terminal sessions carry `entrypoint=cli`, which is no VS Code marker. | as local; farm check pending |
| Codex, VS Code extension | confirmed by design: the open-rollout fd link was verified with `codex exec` 0.147. Extension specifics are pending (remote Q1–Q2). Workspace match needs `source=vscode` (observed downstream, not here). | pending |
| Codex, integrated terminal | confirmed by design, as above. Not attributed if it ended before a poll (`source=cli`). | pending |

How the pieces were established:
- **Extension env:** the user confirmed the env is inherited. The Claude
  extension's `extension.js` builds its child env from `{...process.env}`.
- **Codex:** could not run a turn here (not logged in), so its usage and
  event formats are covered by fixtures built from the shapes seen in local
  rollouts. Those defaults await remote Q3–Q5.

## Test results (2026-11-04)

- `tests/test_ide_launch.py` (5), `tests/test_ide_sessions.py` (12),
  `tests/test_ide_sessions_bind.py` (16), `tests/test_ide_sessions_dash.py`
  (7), and `test_sched_ide.py::test_a_job_server_gets_its_launch...`: all pass.
  The binding tests passed three runs in a row.
- **Regressions:** across IDE, sched IDE, dash, server, login, schema,
  harness, studio and sched dash, 317 passed. `test_dash`, `test_packet_layout`
  and the new dash tests gave 45 passed.
- **Pre-existing failures, not from this work:** 12 in
  `tests/test_sched_batch.py` (steps on the fake farm). They also fail with
  HEAD's `dispatcher.py`.
- **Live** (`WPK_LIVE=1 pytest -m live tests/test_ide_sessions_live.py`):
  - Claude passed: a real haiku turn gave a confirmed row with
    `client=vscode-ext`, the model, "Turn finished", the tokens, packet p/W1,
    and no sentinel in the store.
  - Codex was skipped (not logged in here).
- **Full suite** (excluding `test_sched_batch.py`): 1080 passed, 23 skipped.
  - `tests/test_packet_layout.py::test_dash_pages_match_the_legacy_layout`
    is timing-flaky. It compares step durations (0.0s vs 0.1s) and failed
    once in each direction across three runs. Its diffs show no
    session-related content.

**Scenarios covered**, from the request's acceptance list:
- two packets sharing a checkout
- two sessions in one editor
- an unrelated CLI session in the same directory
- a scheduled step's session
- a session resumed after a restart and under a new launch
- a reused pid
- sentinel text in prompts, tool arguments, output, replies and env, which
  never reaches the store, the launch files or the pages
- a signed-in non-owner, who sees no section and no data
- appends while the board is open, updating the row
- missing usage or model, shown as "unreported"
- truncation, rotation, torn lines and big backlogs

## Still to do

1. **Remote agent:** answer plan questions 1–10, especially the Codex
   extension's process and `source`, `token_usage_record`, the
   approval-event names, and shared home and transport on the farm.
2. **Downstream smoke test on the farm** (plan §6):
   - Open a packet in an LSF-hosted editor and start Claude in the
     extension.
   - See the row appear with the job and host.
   - Run a turn and see it update.
   - Restart the board and check the same row and job, with no reset counts.
   - Repeat with Codex in a terminal.
3. **S4b push channel:** only if the farm's exec hosts do not share
   `$WPK_HOME`.
