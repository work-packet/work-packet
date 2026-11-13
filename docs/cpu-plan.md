# Serve CPU: efficiency plan

Goal: `wpk serve` stays near 0% CPU when nothing is happening, even with tabs open. The
dashboard never freezes while a page is being built.

**Status (2026-11-12):** P0 code, P1 and P2 are done, uncommitted. Full suite passes.
Not yet measured in production, because `serve` hasn't been restarted. Next: get a
production py-spy run on the new code (the open P0 item), then decide on P3.

Update the checkboxes and the status line as each step lands, so a fresh session can pick
up from this file.

## Targets (check in P0 and after each phase)
| Measure | Today | Target |
|---|---|---|
| `serve` CPU with board, overview, studio and 2 IDE tabs open, nothing running | unknown (production: 70–100%) | < 2% |
| Same, while one step runs | unknown | < 5% |
| Scheduler wakes per minute when idle | about 240 when a job record exists | ≤ 2 |
| `data.board()` time, 49 cards, nothing changed | 0.3 s | < 30 ms |
| Longest event-loop stall | ≥ 0.3 s per board refresh | < 50 ms |

## Findings (why it burns CPU)
- **Measured on this host:** `serve` was idle at 0–2%, so production load wasn't captured.
  `data.board()` took 0.3 s warm and 0.5 s cold for 49 cards, and it runs on the event
  loop.
- **Scheduler** (`sched/dispatcher.py:563-576`):
  - It waits only `poll_s = 0.25` (`sched/backends/local.py:50`) whenever *any* job
    record exists, IDE jobs included.
  - Each wake re-parses config, registry TOML and every `status.md` with pure-Python YAML.
  - Suspected spin: when an overdue sleeper can't start (hold, drain, cap, budget,
    lease), `_timer_due()` stays true. That makes a full `fill()` run every 0.25–0.5 s.
- **Studio** (`studio/watch.py:19`): `os.walk` and `stat` of up to 20k files every 0.5 s,
  per socket, hidden tabs included.
- **Board pages** (`dash/data.py:602`, `dash/tokens.py:340`): no caching.
  - Each packet's `journal.jsonl` is parsed 3–4 times per request.
  - Running steps' transcripts are parsed in full.
  - `stats.packet_steps` re-parses old transcripts on every request.
  - Requests come from `live.js` every 10 s per visible tab and `/attention.json` every
    30 s per tab (only when notifications are on).
- **Sessions thread, every 5 s** (`ide_sessions.py:908-932`, `1139-1183`):
  - A `/proc` walk for each launch.
  - Unconditional record rewrites, which defeat `cached_records`.
- **Live view, every 3 s:** a full transcript parse plus a `/proc/*/environ` scan.
- **Environment:**
  - `/packets` is NFS, so inotify misses writes from other hosts (see
    `docs/scheduler.md` §"No file watches across hosts").
  - `os.pidfd_open` is available.
  - `yaml.__with_libyaml__` is True, but `frontmatter._Loader` subclasses the
    pure-Python `SafeLoader`.
  - `max_user_watches` is 65536, shared with VS Code.

Rule for the whole plan: **events make it fast; a slow rescan keeps it correct.** Every
event source keeps a 30–60 s fallback, for NFS, other hosts, hand edits and missed
events.

---

## P0. Baseline and instrumentation
- [x] `scripts/cpu_probe.py`: time `data.board()`, `tokens.board()`, `scheduler.next_wake()`
      and one `Dispatcher` pass on the real home; print the results as a table.
- [x] Dispatcher: count passes and fills; log one line a minute at debug level
      (`passes=… fills=… started=…`).
- [x] Event loop: turn on asyncio slow-callback logging (`loop.slow_callback_duration =
      0.05`) when `WPK_DEBUG_LOOP=1`.
- [ ] Record the baseline in the targets table: py-spy for 60 s with the standard tabs
      open, idle and with one step running. **Ask the user for a `py-spy dump` from
      production while it is hot**, to confirm the ranking.

## P1. Quick wins (small and independent; each is its own change)
- [x] **1.1 libyaml.** `frontmatter._Loader` should subclass `yaml.CSafeLoader` when it
      is available.
      - Keep the custom resolver table, which still drops timestamps.
      - Test: `tests/test_frontmatter.py` passes, and times still load as strings.
- [x] **1.2 Scheduler poll scope.** `wait_s` uses `poll` only while *step* jobs are out.
      IDE-only jobs use 30 s.
      - Test in `tests/test_sched_dispatch.py`: with only an IDE job record,
        `wait_s() ≥ 30`.
- [x] **1.3 Blocked-sleeper spin.** `_next_wake` counts only sleepers that `fill()` could
      start. Also: after a fill that started nothing, don't re-fire for the same
      `wake_at`. Remember the last fired wake time, and fire again only when it changes
      or on a poke.
      - Test: a held project with an overdue sleeper gives one fill per `FALLBACK_S`,
        not one per 0.5 s.
- [x] **1.4 Off the event loop.** Run the sync bodies in `run_in_threadpool`:
      - `data.board` (overview, board, packets, stats, runs, attention, brief)
      - `data.tree`, `data.packet`, `data.live`, `tokens.board`, `render()`
      - `tailnet.status(fresh=True)` (`server.py:389`)
      
      Add a **single-flight** `board()`: concurrent callers share one in-flight build,
      and the result is reused for 2 s.
      - Test: two concurrent board requests trigger one build, and a slow `board()` does
        not delay `/desk/{k}/state`.
- [x] **1.5 Sessions writes.** `_store` and `hook_pass` compare the record with what is
      on disk and skip identical writes. `descendants()` scans `/proc` once per pass,
      shared across launches.
      - Test: two passes with no change make zero writes, and `cached_records` hits.
- [x] **1.6 Token stats.** When a finished step's meta lacks `cache_breaks`,
      `thinking_tokens` or `quota`, compute them once and write them back to
      `meta.json`. Don't write back for running steps.
      - Test: the second `stats.collect` doesn't open the transcript.
- [x] **1.7 Studio stopgap.** Until P4: add build, sim, `.git` and `node_modules`
      excludes; raise `INTERVAL_S` to 2 s; skip scans while the tab reports itself
      hidden.

## P2. Parse cache (removes most of the repeated work)
- [x] `fsutil.cached(path, parse)`: an LRU of about 4096 entries keyed by
      `(path, st_mtime_ns, st_size, st_ino)`. On a hit it costs one `os.stat`.
      Thread-safe, since the threadpool, runner threads and loop all call it.
- [x] Callers may mutate what they get back. Audit the 11 `frontmatter.load` and 12
      `journal.read` call sites. Return a `copy.deepcopy` by default (still far cheaper
      than parsing), and add a `readonly=True` fast path for audited callers.
- [x] Apply it to `frontmatter.load`, `journal.read`, `tomlio.load_toml`, step
      `meta.json`, and the registry and config loads.
- [x] **Transcripts:** `transcript_tail(path)` keeps `(offset, state)` per path and
      parses only the bytes appended since the last read. If the file shrank or its
      inode changed, it re-parses from the start. Use it in `data.activity`, `data.live`
      and `card()`.
- [x] Tests:
  - A cache hit returns an equal object.
  - Editing a file (same size, new mtime) is seen.
  - Atomic replace (new inode) is seen.
  - Appending to a transcript updates the state incrementally.
- [ ] Measure: `data.board()` with nothing changed should be < 30 ms.

## P3. Event sources and an event-driven scheduler
- [ ] **`fswatch.py`:** one interface, two implementations.
  - `InotifyWatcher`: a ctypes wrapper of about 80 lines, no new dependency. It watches
    explicit directories (not recursive), turns `IN_Q_OVERFLOW` into a "rescan all"
    event, and has its own watch budget.
  - `PollWatcher`: an mtime poll at a configurable interval. Used on other platforms and
    when inotify is unavailable or over budget.
  - Output: a callback with the set of changed paths, batched over about 100 ms.
- [ ] **`jobwatch.py`:** `pidfd_open` for each local job, for both started and adopted
      refs. One thread blocks in `select.poll` over the pidfds plus an eventfd (for
      add/remove), and calls `on_exit(ref)` when a job exits. It falls back to the
      current `poll()` when `pidfd_open` fails.
- [ ] **Dispatcher loop:** `poke.wait(timeout)`, where `timeout` is the earliest of:
  - The next *startable* `wake_at`.
  - `backoff_until`.
  - For batch backends only: `poll`.
  - `FALLBACK_S` (60 s).
  
  These events set poke and record *which* packets are dirty: a job exit, an inotify
  change under `packets/*/status.md`, `mailbox/` or `journal.jsonl`, and SIGUSR1.
  Remove `poll_s` from `Local`.
- [ ] **Incremental pass:** keep an in-memory packet index. A pass rereads only the
      dirty packets plus anything whose `(mtime, size)` changed (one `stat` each).
      `next_wake` is computed from the index.
- [ ] **Coverage of mutating commands:** check that every one sends `home_lease.poke()`:
      `new`, handoff, answer, wake, hold, mode, edits of status through the CLI and
      board, and step exit. (Inotify covers hand edits on this host.)
- [ ] Tests:
  - A job exit wakes the dispatcher in under 0.5 s with no polling.
  - An idle dispatcher wakes ≤ 2 times a minute.
  - A hand-edited `status.md` is picked up through inotify, or by the fallback when
    inotify is disabled.
  - LSF and Slurm tests are unchanged.

## P4. Studio on fswatch
- [ ] One shared watcher per packet folder, reference-counted by the sockets that use it.
      It watches only directories outside the excludes. Over the watch budget (about 2k
      dirs) it switches to `PollWatcher` at 5 s and tells the UI.
- [ ] The socket reports visibility, and the watcher stops when no visible socket
      remains. A full rescan happens on overflow and every 30 s as a fallback.
- [ ] Tests: `tests/test_studio_live.py` passes with inotify and with poll mode. Two
      sockets on one packet share one watcher.

## P5. Board push instead of polling
- [ ] The server keeps a `board_gen` counter, bumped by P3 events (job exit, packet
      changes, pokes) and by the server's own writes.
- [ ] A `/events` stream per tab (SSE, or reuse a websocket) sends `{"board": gen,
      "attention": n}`.
  - `live.js` refetches only when the generation changes and the tab is visible.
  - `notify.js` takes its data from the stream.
  - A 60 s timer stays as the fallback.
- [ ] Live view: pushes on transcript changes, using P2's tail reader, in place of the 3 s
      poll. `procs.of_step` only runs while the step's job is alive, at most once
      every 10 s.
- [ ] Tests: a tab with no changes makes no page fetches in 60 s, and a change shows up
      in under 2 s.

## P6. Only if still needed
- [ ] Run the scheduler and the sessions collector in a separate process (the `wpkd`
      split). Do this only if the P0 numbers after P1–P5 still show them competing with
      requests for the GIL.

## Order and risk
- P0 and P1 come first. Each P1 item is small, independent, and testable on its own.
  1.2, 1.3 and 1.4 probably fix most of the production symptom.
- P2 is mechanical, but the mutation audit is the main risk.
- P3–P5 change behaviour, so do them one phase at a time. Each phase keeps its fallback
  poll, which makes a missed event cost latency, not correctness.
- After each phase: run the full tests (`> test.log 2>&1`), then measure with py-spy and
  update the targets table.

## Log
- **P0:**
  - `scripts/cpu_probe.py` times the board, tokens and scheduler pieces.
  - `WPK_DEBUG_LOOP=1 wpk serve` (or `=0.1` for the threshold in seconds) logs
    event-loop callbacks slower than 50 ms. It also logs the dispatcher's
    passes, fills and starts once a minute.
- **P1.1:** `frontmatter._Loader` is based on `CSafeLoader`. The dumper stays pure Python,
  because libyaml escapes non-BMP text (emoji) and files would churn.
  `data.board`: 0.30 s → 0.18 s.
- **P1.2 and 1.3** (`sched/dispatcher.py`, `scheduler.next_wake(after=)`):
  - IDE-only job records poll every 5 s (`IDE_POLL_S`).
  - Local `poll_s` is 0.25 → 2 s. A local job's exit now wakes the loop at once:
    `Local.on_exit` runs on a `wpk-job-wait` thread per job (an early piece of P3).
  - A `wake_at` that the last fill already saw is not waited on again.
  - Tests are at the end of `tests/test_sched_dispatch.py`.
- **Extra:** `registry.get(name)` reads its own file instead of every project's.
  A board build had made about 2,260 TOML parses; it now makes about 390.
  `data.board` is now 0.14 s.
- **P1.4** (`dash/app.py`):
  - `board_of()` is single-flight: requests that arrive while a build runs share it,
    and an action (`back()`) starts a fresh build. Each caller gets a copy through a
    pickle round trip.
  - A 2 s reuse window was tried and dropped. It showed stale boards after CLI and API
    changes (`test_collab_f3` caught it). P2's cache is the way to make repeat builds
    cheap.
  - `tokens.board`, `data.tree`, `data.packet`, `data.live`, `tokens.packet`,
    `packet_top` and template rendering (`arender`) now run in the threadpool.
    `not_found` and three other sync paths still render on the loop; they are small.
  - Tests: `tests/test_dash_load.py`.
- **P2 hint:** after P1, a board build is still 1,356 front-matter loads, 171 journal
  reads, 391 TOML loads and about 4,300 `strptime` calls. That is exactly the parse
  cache's target.
- **P1.5** (`ide_sessions.py`, `session_usage.py`):
  - `_put` and `session_usage.put` skip writes that are byte-identical.
  - The Collector remembers ended sessions (`_final`) and doesn't store them again
    until their transcript grows.
  - `proc_children()` scans `/proc` once per `local_pass`.
  - Tests are in `test_ide_sessions_bind.py` and `test_collab_g.py`.
- **P1.6** (`stats.py`):
  - A finished step's missing token fields are written back to `meta.json` once, with
    `filled_from_transcript: true`. Running steps are never written.
  - The first `tokens.board` after deploying is slow, about 0.8 s, because it fills in
    every old step once. After that it takes 82 ms, down from 146 ms.
  - `dash/tokens.py:step` (one step page) still re-reads; it reads the transcript
    anyway.
- **P1.7** (`studio/watch.py`, `dash/studio.py`, `dash/studio.js`):
  - `WALK_EXCLUDE` adds `build`, `sim_build`, `obj_dir` and `rundir`. The tree still
    shows them.
  - `INTERVAL_S` is 2 s.
  - The tab sends `{"type":"visible"}` messages, and the socket skips scans while the
    tab is hidden.
- **P2** (`fsutil.cached`, `fsutil.load_json`):
  - Keyed on (mtime_ns, ctime_ns, size, inode). It keeps a pickle and gives each
    caller its own copy, so there was no mutation audit to do; text is kept as is
    (`copy=False`).
  - Wired into `frontmatter.load`, `journal.read`, `tomlio.load_toml`, `card.load`,
    `data._read`/`_json`, `presence._load` and the `meta.json` loads in `stats`.
  - `schema.parse_timestamp` has an LRU (datetimes are immutable), and
    `is_timestamp` uses it.
  - `CACHE_MAX` is 16384. On this home the cache is about 3,800 entries and 4.6 MB.
  - Over NFS, another host's write shows once the client's attribute cache expires
    (`acregmin`, about 3 s).
  - **Transcripts:** `data.activity` keeps a per-file feed state (`_feeds`, 256
    files) and parses only whole lines appended since the last read. A trailing line
    with no newline is applied to the returned copy only. A replaced or shorter file
    starts over. It matched the old reader on 40 real transcripts, read whole and in
    chunks cut mid-line.
  - Tests: `tests/test_fsutil_cache.py`.
- **Timings after P2** (`scripts/cpu_probe.py`, 50 cards, warm):
  - `data.board`: 300 → 51 ms. The 30 ms target isn't met; what's left is about
    4,400 `stat` calls plus pickle copies. A `readonly=True` path for audited callers
    would close the gap.
  - `tokens.board`: 146 → 52 ms.
  - `scheduler.next_wake` and `due`: 3 → 0.5 ms each.
