# Live DFM runs on the board

Status (2026-10-25): the DFM side (E1 and the DFM half of E4) is built in `packages/dv-flow-mgr`, uncommitted, and covered by unit tests only. The wpk side is not started. The work splits into a DFM side (dv-flow-mgr) and a wpk side. A fresh session should be able to pick up from this file and the status log at the end.

dv-flow-mgr (DFM) runs are often long, and today the only view into one is the CLI that launched it, which may sit inside a step's Bash tool where nobody can see it. The goal is for the board to show, for any DFM run started under wpk, what it **is** doing, what it **has** done and what it **plans** to do. The same channel should later feed a VS Code view of runs started in its terminals.

Key ideas:

1. **The board listens and DFM connects.** The board owns a Unix socket, and DFM connects to it when an env var names it. Every wpk child process inherits the variable, so DFM needs no other discovery and no configuration.
2. **One small event protocol in JSON lines.** It has a run header, a plan (nodes and edges), plan extensions, task state changes, live markers and a run end. It is written to be tool-neutral, so other producers can use it later.
3. **DFM already has the hooks.** It has a listener API (`listener(task, reason)`), and the full graph is known before execution, apart from control-flow subgraphs. The DFM change is one new listener plus three small notification gaps.
4. **The board keeps a journal and folds it.** Received events are appended to a file per run, and the pages read that journal the way `data.py` reads everything else. A board restart loses nothing it already received.
5. **Start with a list, not a graph.** The first view is Running / Done / Pending sections with a progress count, which is roughly the CLI's view plus the plan. A graph comes later and is cheap if it is drawn server-side from DOT.

Contents: §1 What DFM gives us · §2 Transport · §3 Protocol · §4 DFM changes · §5 wpk changes · §6 List or graph · §7 VS Code · §8 Build plan · open questions · status log.

## 1. What DFM gives us today

Paths are relative to `dv-flow-mgr/src/dv_flow/mgr/`, at HEAD `bfb54a7`.

- **Single asyncio runner.** `TaskSetRunner.run()` (`task_runner.py:170`) builds `_dep_map` with `buildDepMap` (`:232`). The map covers every node reachable through `needs` and compound subtasks, and the build step has already expanded matrix and `strategy.generate`. After that the runner marks every node NOT_STARTED and calls `enter()` (`:261`). **This is the plan.**
- **Listener API.** `add_listener(l, recursive=False)` (`:72`) and `_notify(task, reason)` (`:75`). `cmd_run` registers the console, trace and report listeners at `cmds/cmd_run.py:429-441`. The reasons it emits are `start`, `end`, `enter`, `checking`, `uptodate`, `run`, `cache_hit`, `base_hit` and `leave`. The payload is the live `TaskNode`: name, `needs`, rundir, `start`/`end`, and `result` (status, changed, markers, cache_hit).
- **Dynamic growth.** The control nodes (if/match/while/repeat), `std.RunTasks` and pytask `run_subgraph` all build nodes at run time. They are merged into `_dep_map` at `task_runner.py:949-961`. No event fires for this today.
- **Gaps:**
  - `_skip_task` (`:766`) does not notify, so tasks skipped after a failure just vanish.
  - Markers are only collected into `result.markers` and become visible at `leave`.
  - Exec start/end callbacks exist (`task_run_ctxt.py:43-44`) but nothing uses them.
  - Two nested runners are created without listeners, so their tasks are invisible: `task_node.py:173` and the `run_subgraph` fallback at `task_run_ctxt.py:386-394`.
- **Prior art in DFM.**
  - The DFM daemon (`daemon.py`, `daemon_events.py`) already pushes `{"method","params"}\n` events to subscribers, and `daemon_monitor.py` is a rich client for them.
  - `TaskListenerTrace` writes a Chrome trace, but only at close.
  - `dfm graph` emits DOT.
- **Env clash.** DFM sets `DFM_SERVER_SOCKET` in every task's environment. A nested `dfm` that sees it switches to client mode and asks the parent to run the work (`__main__.py:864`). The new variable must have a different name. As a bonus, nested `dfm run` calls inside tasks execute in the parent runner, so the parent's listener sees their tasks.

## 2. Transport

**The direction is producer to collector.** You suggested that DFM broadcast. If DFM listened, the board would have to discover every run's socket and would miss runs that finished before it connected. If the board listens, discovery is free (the env var), and a run with no listener costs nothing.

- **Env var:** `DFM_EVENT_SINK`. Its value is a comma-separated list of URIs:
  - `unix:/path/to/sock`
  - `file:/path/events.jsonl` (append; useful for tests and offline replay)
  - optionally `tcp:host:port`, later and only if remote viewing needs it.

  A list matters for one case: a VS Code terminal inside a wpk IDE session wants both the board and the extension to see the run.
- **Context var:** `DFM_EVENT_CTX`. Whoever sets the sink also tells DFM which of its env variables to report back, so DFM never needs to know what its collectors care about.
  - The value is a comma-separated list of names. A trailing `*` makes an entry a prefix. wpk sets `WPK_*`; a VS Code extension might add `VSCODE_*`, or a variable of its own.
  - Collectors **append** to it the same way they append to `DFM_EVENT_SINK`. Every sink gets the union, which is fine because every sink belongs to the same user.
  - DFM reports only the names that match and ignores names that aren't set. It caps the block (64 entries, 4 KiB of values) so a careless `*` can't send the whole environment.
  - Unset means an empty `ctx`. The collector can still use the pid fallback in §3.1.
  - A collector that wants to tag a run with something that isn't already in the environment (a terminal id, a session id) exports a variable of its own and lists it. DFM needs no separate tags mechanism.
- **Heartbeat var:** `DFM_EVENT_HEARTBEAT`, in seconds (default 10; `0` turns it off). The collector chooses it, as with `DFM_EVENT_CTX`. After that long with nothing else sent, DFM sends `run.alive` listing what is running. A busy run sends no heartbeats; any line counts as one. It lets the collector tell a quiet run (one long simulation) from one that died without closing its stream: a `file:` sink never closes, and a socket may outlive a hung process.
- **Socket:** `$WPK_HOME/events/events.sock`, in a 0700 directory. It reuses the `dash/ide.py:40` `socket_path()` fallback for long `sun_path`. It is accepted on the Board's existing asyncio loop with `asyncio.start_unix_server`, so it needs no new thread.
- **Who sets it:** the board puts it in its own `os.environ` at startup, so the runner, `wpk step`, claude, Bash and finally `dfm` all inherit it, along with the shell sessions. It also goes into the IDE workspace's `terminal.integrated.env.linux` next to `WPK_PROJECT` and the other variables (ide.md). `executor.py:621` is the alternative if we would rather scope it to steps.
- **DFM must never be slowed or failed by the sink.**
  - Connect with a short timeout (about 200 ms). On failure, log once at debug level and go on without it.
  - Writes go through a bounded queue (4096 lines) per sink, drained by a daemon thread rather than an asyncio task, so a blocked send never touches the runner's loop. On overflow, drop events and count them; `run.end` carries `dropped`.
  - A broken pipe disables the sink for the rest of the run.
  - The collector never sends anything back, so this is one-way, with no RPC.

## 3. Protocol (v1)

There is one JSON object per line. Every line has this envelope:

```json
{"v":1, "src":"dfm", "sid":"01JB8Z3K9V6Q2T4X7M5N0P1R2S", "seq":17, "t":1761400000.123, "ev":"task.state", ...}
```

### 3.1 Identifying the sender

One collector serves the whole board, so it receives events from many runs at once, from different packets, shells and terminals. **Every line names its run**. The collector does not rely on the connection to tell runs apart.

- **`sid`, the stream id.** The emitter creates it once per `dfm` process, at startup, as a ULID (or uuid4 hex). It is unique across hosts and sessions, and as a ULID it sorts by time, which gives the runs list its order. **DFM's own `DFM_RUN_ID` cannot do this job.** `alloc_run_id` (`run_id.py:30`) is a per-rundir counter (`"0001"`, `"0002"`, …), so two sessions in different rundirs both send `"0001"`. It goes in `run.start` as `dfm_run_id`, for display only.
- **Why every line and not just the connection.** One connection per run is the normal case, but none of the following should break attribution:
  - a `file:` sink shared by several runs
  - a reconnect after the board restarts (if we ever add retry)
  - a VS Code relay that forwards several runs over one connection
  - lines that arrive with no `run.start` before them

  The cost is about 40 bytes per line.
- **`seq`** counts per `sid`, starting at 0 for `run.start`. A gap means lines were dropped. A `sid` whose first line is not seq 0 is shown as "partial".
- **Who and where: the `run.start` origin block.**
  - `host`, `pid`, `ppid`, `uid`, `cwd`, `argv`, `rundir`
  - `ctx`: the variables that `DFM_EVENT_CTX` names (§2), as `{name: value}`, taken from DFM's own environment at startup. DFM has no built-in list. Under wpk this gives `WPK_PROJECT`, `WPK_WPID`, `WPK_STEP`, `WPK_ATTEMPT` and so on.
  - `term`: `TERM_PROGRAM`, plus `VSCODE_IPC_HOOK_CLI` if set (§7)
  - `parent`: `DFM_EVENT_PARENT`, if inherited

  Later lines carry only the envelope. The collector joins them to the origin through `sid`.
- **Nesting.** The emitter exports `DFM_EVENT_PARENT=<sid>` into its tasks' env. A separate `dfm` process started under a task (one not in client mode) then reports with its own `sid` and `parent` set, and the board nests it under that task's run.
  - A nested `dfm` in client mode (`DFM_SERVER_SOCKET` set) runs its work in the parent runner, so it shows up under the parent's `sid` without anything extra.
- **Cross-check on a Unix socket.** The collector reads the peer's pid with `SO_PEERCRED` at accept time and records it next to the claimed `pid`.
  - That lets it catch a mismatch.
  - When `ctx` is missing, the collector can still attribute the run by walking `/proc/<pid>` ancestry, or by scanning `/proc/<pid>/environ` for `WPK_WPID`/`WPK_STEP` as `procs.py` already does. That covers a run whose environment was scrubbed, for example by `env -i` in a Makefile.
- **Trust.** The socket is 0700 and owned by the user, so all senders are the user's own processes. Identification is for attribution, not security. The collector still rejects a line whose `sid` was first seen from a different peer pid, so that one stray process can't write into another run.

The journal is keyed by `sid` (`$WPK_HOME/runs/dfm/<sid>.jsonl`). The board joins runs to packets through `ctx`.

### 3.2 Events

| `ev` | When | Payload |
|---|---|---|
| `run.start` | `enter()` | the origin block (§3.1), plus `dfm_run_id`, `roots`, `jobs` |
| `graph.plan` | after `_dep_map` is built | `nodes: [{id, name, kind: leaf\|compound, parent, needs:[{id, block}], rundir}]` |
| `graph.extend` | dynamic merge at `task_runner.py:949` | `scope` (subgraph name), `nodes` as above |
| `task.state` | every listener reason, plus `skipped` | `id`, `state`: `enter\|checking\|run\|uptodate\|cache_hit\|base_hit\|done\|skipped`, then on `done`: `status`, `changed`, `cache_hit`/`base_hit` (when true), `dur`, `rundir`, `log` (path, if the file exists) |
| `task.marker` | `TaskRunCtxt.marker`/`add_marker` as they happen; at `done` for markers the task returned in its result (each marker once) | `id`, `severity`, `msg` (truncated at 2000), `loc: {path, line, pos}` |
| `task.exec` | `TaskRunCtxt.exec` start and end | `id`, `phase: start\|end`, `cmd` (argv, truncated), `logfile`, `rc` (on end) |
| `run.alive` | heartbeat: `DFM_EVENT_HEARTBEAT` seconds with nothing else sent | `running` (up to 32 node ids, oldest first), `n_running` |
| `run.end` | `leave()` of the outermost runner, or after the run if it raised | `status`, `result: ok\|fail\|error`, `counts` (`ok`, `uptodate`, `cache_hit`, `base_hit`, `failed`, `skipped`), `dropped` (this sink's) |

Node records in `graph.plan`/`graph.extend` also carry `label` when the display name differs from `name`. Nested runners (input updates, the `run_subgraph` fallback) report their new nodes as `graph.extend` with `scope: null`.

Notes:
- **Node ids** are the task's fully qualified name, which the runner already keys completions on. A second node object with a name already in use gets `name#2`, `name#3` and so on (the emitter keys on object identity), which settles open question 2 on the wire.
- **What the payloads leave out:** params, outputs and file sets. They can be large, and the rundir has them. The run header gives the board the rundir, so it can open `exec_data.json` or the logs on demand.
- **Neutral envelope.** Nothing in the envelope is DFM-specific. Another producer (a VS Code session or a Claude hook) uses its own `src` and its own `ev` names under the same envelope (§7).

## 4. DFM changes (in dv-flow-mgr)

They are small and kept to a few places. **Built 2026-10-25**; see "As built" at the end of this section.

1. A new `TaskListenerEvents` (an `event_sink.py` file holding the sink and the URI parsing), registered next to `trace.event` at `cmd_run.py:430` when `DFM_EVENT_SINK` is set. It maps listener reasons onto `task.state`.
2. The runner has to give the listener the plan. Add a new reason, `plan`, fired from `run()` once `_dep_map` exists, with the map reachable from the runner. Add `extend` at the dynamic merge. Existing listeners ignore reasons they don't know; check that `TaskListenerProgress` and `TaskListenerTui` do.
3. `_skip_task` calls `self._notify(task, "skipped")`.
4. Live markers: `TaskRunCtxt.marker()` also notifies through the runner (a new `marker` reason, or a separate channel like `marker_l`).
5. Exec start/end: wire the existing `_exec_start_callback`/`_exec_end_callback` to the runner's listeners.
6. Pass `recursive=True` listeners to the two nested runners (`task_node.py:173`, `task_run_ctxt.py:388`).
7. Tests: drive a small flow with `DFM_EVENT_SINK=file:...`. Assert that the plan covers every node, that every node reaches a terminal state, that skips appear after a failure, and that a dead socket path changes neither the exit status nor the run time.

Items 1-3 are enough for a first useful board. Items 4-6 make it complete. Nothing here touches the up-to-date logic or the scheduling.

**As built** (paths under `packages/dv-flow-mgr/src/dv_flow/mgr/`):

- **Detail listeners instead of new classic reasons.** The existing listeners don't all ignore reasons they don't know: `TaskListenerTrace` treats any other reason as an end event and reads `task.end`, and `TaskListenerTui` prints a line for it. So the new reasons go to a separate list, `TaskRunner.event_listeners` (`add_event_listener`), called as `l(subject, reason, info)`. Those listeners get every classic reason too (with `info=None`), plus `plan`, `extend`, `skipped`, `marker` and `exec`. Classic listeners are unchanged. A detail listener that raises is logged at debug level and ignored. Nested runners copy `event_listeners` (`task_node.py`, `task_run_ctxt.py`), not the classic list, so the console UIs never see a nested `start`.
- `event_sink.py`: `new_sid` (ULID), `ctx_block` (the `DFM_EVENT_CTX` match and caps), `parse_sinks` (`unix:`, `file:`, `file://`; other schemes are skipped), the `UnixSink`/`FileSink` writer threads, and `EventEmitter` (envelope, `seq`, origin block, per-sink `run.end`). `tcp:` is not built.
- Heartbeat: a third daemon thread in `EventEmitter` (`start_heartbeat`), started after `run.start` and stopped before `run.end`, so its lines keep `seq` in order. `TaskListenerEvents` supplies the running set. This is the other reason for threads: a heartbeat on the runner's loop would stall exactly when a task blocks the loop.
- `task_listener_events.py`: `TaskListenerEvents`. It tracks runner depth, so only the outermost runner gives `run.start`/`graph.plan`/`run.end`.
- `cmds/cmd_run.py`: `_open_event_sink` registers it just before `asyncio.run`, sets `DFM_EVENT_PARENT=<sid>` in the runner's env, and closes it in a `finally`.
- `task_runner.py`: `plan` after `enter()`, `extend` at the dynamic merge, `skipped` in `_skip_task`.
- `task_run_ctxt.py`: `_task` (set by `task_node_leaf.py`), and `marker`/`add_marker`/`exec` report through it. Only leaf tasks set `_task`, so markers from control nodes arrive at `done`.
- Fix on the way: `schedule_subgraph` never put the sub-graph's `name` in the queue item, so every dynamic scope was named `subgraph_N` (`dynamic_scheduler.py`).
- Tests: `tests/unit/test_event_sink.py` (18 tests, three of them for the heartbeat) covers the sink layer, a dead socket, overflow, a peer that goes away, a runner run with a failure, skips, live and returned markers and exec, a dynamic sub-graph with repeated names, a listener that raises, and `CmdRun` with a file sink, including `DFM_EVENT_PARENT` reaching a task's shell. The full `tests/unit` suite passes (1982 passed, 10 skipped, 5 xfailed).

## 5. wpk changes

- **Collector** (`dash/events.py`):
  - A unix server on the Board loop. It reads lines, validates `v` and `src`, and appends them as received to `$WPK_HOME/runs/dfm/<sid>.jsonl`, and checks the peer pid (§3.1).
  - It also keeps a small in-memory index (`sid`, origin, `ctx`, `parent`, last `seq`, live or finished) so the runs list doesn't rescan files.
  - It caps line length and runs per connection, and ignores anything else.
  - A connection that closes without `run.end` marks the run `lost` (the process was killed). So does silence for about three heartbeat intervals (`run.alive`, §2), which also covers `file:` journals replayed later and a process that hangs with its socket open.
- **Fold** (`data.py`): `dfm_run(path)` replays a journal into a run model with three lists:
  - **nodes by state:** pending, running, done or skipped.
  - **counts**
  - **"waiting on"** for each pending node: its first unfinished need.

  Replaying a few thousand lines per page load is fine. If big runs make it slow, cache by file size.
- **Pages:**
  - `/runs` lists recent runs, newest first, live ones on top.
  - `/runs/{sid}` is the run page (§6).
  - The step page shows "DFM runs" linked through `ctx.WPK_WPID`/`WPK_STEP`, and the packet page shows a count. Runs with no wpk context, started from a shell, still show under `/runs`.
- **Live updates:** at first, the existing `live.js` polling at `LIVE_MS` (3 s) while a run is live. The SSE stream already planned in `runner.md`/`server.md` can come later, fed by the collector's own events rather than by tailing a file.
- **Retention:** keep the last N runs, or those under M days old, using the same pruning as the rest of `$WPK_HOME`.

## 6. List or graph

**Recommendation: build the list first, keep the plan data graph-complete, and add the graph as a second tab rendered server-side.**

The list view mirrors the CLI and adds the plan, which the CLI doesn't show.

```
dfm run sim.regress   ▶ running  0:14:32   ████████░░░░  41/96   2 failed
Running (3)  sim.tests.t17.run  3:02   vcs -R ...   [log]
             sim.tests.t18.run  2:55
             ...
Pending (52) sim.tests.t31.run  waiting on sim.build
             sim.report         waiting on 52 tasks
Done (41)    ✗ sim.tests.t04.run  1:12  2 errors  [log]
             ✓ sim.build          6:40
             · 30 up-to-date (collapsed)
```

Why the list comes first:
- It answers the three questions (is doing, has done, plans to do) directly.
- It scales to the hundreds of nodes a matrix produces, which a node-link drawing doesn't.
- It needs no JavaScript. That fits the CSP (`script-src 'self'`) and the no-build-step rule.
- It maps one-to-one onto a VS Code TreeView (§7).
- Grouping by `parent` gives the compound tree for free.

When we want the graph:
- **Cheap path:** emit DOT from the plan, colour nodes by state, and render it with `dot -Tsvg` on the server. This needs graphviz on the host, with a fallback to the list when it is missing. DFM's `dfm graph` already shows the DOT shape people are used to.
- **Rich path:** vendor elkjs or dagre for client-side layout and live recolouring. That is more work and more JS, and only worth it if people use the cheap path.
- **Timeline:** a Gantt-style view of start and duration per task may answer "why is this slow" better than a graph. It comes from the same events, and DFM's Chrome trace already proves the shape. Worth considering before a graph.

## 7. VS Code

The same protocol works, with the extension as a second collector.

- **Listening:** the extension listens on its own socket. It adds itself to `DFM_EVENT_SINK` with `context.environmentVariableCollection.append` (or `prepend`) and a comma separator. That reaches every new integrated terminal, wpk's own included.
- **Display:** runs appear in a TreeView (run, then Running/Pending/Done, then tasks), with "open log" and "reveal rundir" commands.
- **Other terminal sessions:** "status events from sessions run under a VS Code terminal" generalise the producer. A Claude Code session in a terminal could emit `src:"claude"` events through a hook, just as `ctxhook.py` runs today. The extension and the board fold any `src` they understand and list the rest generically. That is a reason to keep the envelope neutral now, even though only DFM produces events at first.
- **Without a board:** the extension does not need the board to be running. The board does not need the extension.

This depends on the deferred extension work in `vscode-plan.md` ("Later") and is listed here only so the protocol doesn't box it in.

## 8. Build plan

The milestones carry an E prefix.

**E1 — DFM emitter (dv-flow-mgr).** §4 items 1-3, plus the `file:` and `unix:` sinks.
- [x] `event_sink.py`: URI parsing, bounded queue, never-fail semantics; `DFM_EVENT_CTX` matching and caps; `sid` and `DFM_EVENT_PARENT`
- [x] `TaskListenerEvents`, registered in `cmd_run` when `DFM_EVENT_SINK` is set
- [x] `plan` and `extend` reasons on the runner; skip notifications
- [x] Tests with a file sink; dead-socket test
- [ ] A real `dfm run` against a live socket, then a PR to dv-flow-mgr
- Estimate: about a day. This is a change to another repo, so it needs its own PR and review there.

**E2 — wpk collector and journal.**
- [ ] `dash/events.py` unix server on the Board loop; `DFM_EVENT_SINK` exported at board start
- [ ] Journal under `$WPK_HOME/runs/dfm/`; `lost` detection; pruning
- [ ] Test: a fake producer (or real DFM with a file sink, replayed) gives the expected folded model

**E3 — board list view.**
- [ ] `data.dfm_run` fold; `/runs` and `/runs/{sid}` pages; links from step and packet pages
- [ ] Polling while live
- [ ] Test in `test_dash.py` with a canned journal

**E4 — completeness (DFM).** Live markers, exec start/end with the current command, nested-runner listeners, `graph.extend` for control nodes. Tests with a `repeat` flow and a nested `dfm run`.
- [x] Live markers, exec start/end, nested-runner listeners, `graph.extend` (built with E1; unit-tested through `run_subgraph`)
- [ ] Tests with a real `repeat`/`while` flow and a nested `dfm run`

**E5 — graph and/or timeline tab.** DOT to SVG on the server, or a timeline. Decide after using E3.

**E6 — VS Code collector.** Waits for the extension work in vscode-plan.md.

E1 and E2 can be built in parallel against the protocol in §3. E2 can be tested with a file sink before E1 lands.

## Open questions

1. **Env var name.** `DFM_EVENT_SINK` is clear for DFM. If other tools join, we may want a neutral name that wpk sets and DFM also reads. Proposal: start with `DFM_EVENT_SINK` and add an alias later if needed.
2. ~~**Stable node ids across dynamic iterations.**~~ On the wire: the emitter suffixes `#N` (§3.2). Still worth checking what names `task_node_repeat.py` gives, since `#2` says less than an iteration index. while/repeat bodies may produce the same task name more than once. We could suffix an iteration index in the emitter, or have DFM make the names unique. This needs a look at the names `task_node_repeat.py` actually produces.
3. ~~**Where the variable is set.**~~ Decided: board-wide (`os.environ`). The board exports `DFM_EVENT_SINK` and `DFM_EVENT_CTX=WPK_*`, and `ctx` ties each run to its step.
4. **Remote runs.** Runs on another host (LSF or slurm) still report from the runner host, so nothing changes. A DFM run on a different machine from the board would need `tcp:` over the tailnet, plus auth. Deferred.
5. **Should DFM also write `rundir/log/events.jsonl` by default?** It costs little, makes runs replayable without any collector, and would let the board show runs it missed. That is a DFM product decision.
6. **Does DFM's own daemon (`daemon_events.py`) want this format too?** It could, but that is out of scope here.

## Status log

### 2026-10-25: scoping
Read the DFM runner, listener, daemon and subprocess code, and the board server, data and env plumbing. Confirmed that `_skip_task` never notifies, that `DFM_SERVER_SOCKET` forces nested `dfm` into client mode, and that dynamic nodes are merged at `task_runner.py:949-961`. Nothing built.

### 2026-10-25: sender identification
The board-wide collector receives events from many sessions at once, so every line now carries a `sid` that the emitter generates (§3.1). Found that `DFM_RUN_ID` is a per-rundir counter and collides across sessions, so it is now display-only (`dfm_run_id`). Added the origin block, `DFM_EVENT_PARENT` for nesting, and the `SO_PEERCRED` cross-check.

### 2026-10-25: collector-chosen context
Decided: the variables are set board-wide. Added `DFM_EVENT_CTX` (§2): the collector names, or names by prefix, the env variables DFM echoes back in `run.start.ctx`. Collectors append to it, and the block is capped. DFM no longer knows anything about wpk.

### 2026-10-25: DFM emitter built (E1, DFM half of E4)
Built in `packages/dv-flow-mgr`, uncommitted (§4, "As built"). Changed from the plan: the new reasons go to separate detail listeners, because the trace and TUI listeners don't ignore unknown reasons; the sink drains on a thread, not an asyncio task; `task.state` adds `enter`; repeated node names get `#N`. Fixed sub-graph names in `schedule_subgraph`. 15 new unit tests; the DFM unit suite passes. Not yet run against a live collector.

### 2026-10-25: heartbeat
Added `run.alive` and `DFM_EVENT_HEARTBEAT` (§2, §3.2): sent only after a quiet interval, with the running node ids. The collector's `lost` rule now includes silence for about three intervals (§5). 3 more tests; the DFM unit suite passes.
