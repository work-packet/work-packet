# Studio: implementation, test and doc plan

Started 2026-10-30. Status: **P0, S1 and S2 done (exit checks scripted
and run with the real model); next S3.** The S0 pilot is skipped for
now (it needs a person in VS Code); decisions D1–D12 taken as assumed. Next: see the status log (§14).

The design is `docs/interactive-tasks.md` ("the design" below, cited by
§). This file is the tracker: a fresh session should be able to pick up
from it alone. Tick tasks as they finish and add a line to the status log
(§13) at the end of each working session.

## 1. Shape of the work

```
P0 foundations ──▶ S1 studio + documents ──▶ S2 data + charts ──▶ S3 renders + versions
   (take, recorded steps,                                              │
    studio agent, render service,                                      ▼
    vendoring, content origin)        S4 comments everywhere, diagrams, sketches, embeds
                                                                       │
                          ┌────────────────────┬───────────────────────┼───────────────┐
                          ▼                    ▼                       ▼               ▼
                    S5 research        S6 tool kinds (decks)   S7 branches, speed   S8 export, publish, phone
```

- **S0** (the VS Code pilot, the design §11) runs before P0 and can shrink
  the plan.
- After **S3** the studio is useful for its first worked example (data
  analysis). S5–S8 can be reordered by need; S8's "publish" needs
  routines-and-outputs.md R1.
- Estimates are working days for one person with an agent, and include
  tests and docs.

| Phase | What | Est. | Depends on |
|---|---|---|---|
| S0 | VS Code pilot | 0.5 | – |
| P0 | Foundations | 6 | – |
| S1 | Studio shell, documents, recording | 6 | P0 |
| S2 | Kernel, tables, Vega-Lite charts | 6 | S1 |
| S3 | Renders, versions, self-check | 5 | S1 (S2 for chart renders) |
| S4 | Comments on every kind, diagrams, Excalidraw, embeds | 7 | S3 |
| S5 | Sources, findings, citations, questions | 6 | S1, S3 |
| S6 | Tool kinds: decks, Quarto, figures; templates, assets | 6 | S3, P0.6 |
| S7 | Branches, shared editing, model per turn, priority | 5 | S3 |
| S8 | Export, publish, phone | 4 | S4, S6; routines R1 |

## 2. Decisions

Taken from the design §12. **Assumed** until you confirm; each is cheap to
change before the phase that depends on it.

| # | Decision | Status | First needed |
|---|---|---|---|
| D1 | One studio for all kinds, viewers per kind | assumed | S1 |
| D2 | Text sources only; `.docx`/`.pptx`/`.ipynb` are imports and exports | assumed | S1 |
| D3 | Vega-Lite as the chart format; matplotlib/plotly scripts as "figure" | assumed | S2 |
| D4 | DuckDB + pandas in a per-studio Python kernel, not Jupyter | assumed | S2 |
| D5 | One step per studio session, versions inside it | assumed | S1 |
| D6 | The studio takes the packet (v1: PAUSED, reason `studio`; §3 P0.1) | assumed | P0 |
| D7 | Slidev first for decks, Marp as the simple fallback | assumed | S6 |
| D8 | Studio metadata in `<packet folder>/.studio/`; versions in the run dir | assumed | S1 |
| D9 | Untrusted rendered content (agent HTML, dev servers) served on a sandboxed content path with a capability token, never on the dash origin (P0.6) | assumed | P0 |
| D10 | Headless Chrome found on the host, driven over CDP by our own small client; no Playwright | assumed | P0 |
| D11 | JS libraries vendored by a build script under `tools/vendor/`; Node needed only to rebuild them | assumed | P0 |
| D12 | The studio's agent runs on the server as the console does, not as a scheduler job, in v1 | assumed | P0 |

## 3. What exists that we build on

(From a survey on 2026-10-30; paths under `src/work_packet/`.)

- **Dash:** Starlette + Jinja + uvicorn. One flat route list in
  `dash/app.py:1608-1677` (catch-alls `/p/{project}/{wpid}[/{step}]` last);
  `render()` at `app.py:136`. Static files are a whitelist `STATIC`
  (`app.py:41`) plus `pyproject.toml` package-data.
- **Guard and CSP** (`dash/guard.py`): CSRF by header or form field;
  WebSockets check Origin, then the first message carries the token
  (`app.py:960`). CSP is `script-src 'self'`, `img-src 'self' data:`,
  **`frame-ancestors 'none'` and `X-Frame-Options: DENY`** (guard.py:26-33):
  the studio's iframes need per-route headers (P0.6).
- **Console agent** (`dash/agent.py`, `dash/console.py`): its own `claude
  -p` argv (`agent.py:244`), read-only `TOOLS`/`ALLOWED` (`agent.py:37`),
  one process per reply, transcript in `$WPK_HOME/console/<cid>/`, events
  to sockets via `publish()`. Scope from the page URL (`console.py:30`).
- **Harness** (`harness/claude.py:118`): `command(StepSpec)` builds a step's
  argv; `hook_settings(...)` (`:30`) wires bghook, pathhook and the notes
  hook.
- **Packet states** (`schema.py:17`): RUNNABLE, SLEEPING, NEEDS_INPUT,
  PAUSED, COMPLETED, FAILED. **No HELD, no take.** "Held for setup" is
  PAUSED with `reason="setup"`. `executor.admin(pkt, op)` (`executor.py:927`)
  does pause/wake/resume/handoff/continue under the lease;
  `request_pause` (`executor.py:1042`) pauses a running packet at commit.
- **Steps** (`executor._run`, `executor.py:695`): `steps/NNNN/` with
  `prompt.md`, `meta.json`, `summary.md`, `notes.seen`…; journal
  `step-start` → `commit-begin` → `_apply` (`:157`) → `commit-end`. No
  `worker` field anywhere.
- **Notes** (`notes.py:24`): `mailbox/<id>.json` `{id, t, by, text}`;
  mid-step delivery by the PostToolUse hook `ctxhook.py`.
- **Doc markup** (`dash/markup.py`, `markup.js`, `templates/doc.html`):
  `plugin`, `mark`, `resolve`, `edit` (atomic, sha-checked, `Stale`);
  `POST /p/{project}/markup`.
- **IDE proxy** (`dash/ide.py`): `Backend` processes on a unix socket,
  `proxy_http` (httpx) and `proxy_ws` (websockets), idle reaping, LRU.
- **Blobs** (`blobs.py`): `put_file`, `put_bytes`, `get_bytes`, `path_of`.
- **Sched classes** (`schema.SCHED_CLASSES`, `sched/classes.py`,
  `sched/queue.py:92`).
- **Tests:** flat pytest; `tests/conftest.py` has `make_project`, `_commit`
  and the `fake` fixture (`WPK_CLAUDE` → `tests/fakemodel/fake_claude.py`
  with behaviours in `tests/fakemodel/behaviors/`, `WPK_HOME`, `WPK_NOW`).
  Dash tests use `TestClient` wrapped in `Guard` (template:
  `tests/test_console.py:227`). A `live` marker exists. **No browser tests
  today;** Chromium, Chrome and Node are on this machine but unused.
- **Docs:** flat Markdown in `docs/`, design and plan docs plus a few
  guides (`sched-guide.md`, `setup.md`); no Sphinx tree for wpk, no
  changelog.

## 4. Code layout

New code goes in a `studio` package (logic, no web) and `dash/studio*.py`
(routes and sockets), so the logic is testable without the dash.

```
src/work_packet/studio/
  __init__.py
  model.py        Studio: open/close, paths, .studio/ files, canvas state
  kinds.py        the kind registry: patterns, viewer, anchor schema, render, exports
  watch.py        polling file watcher; who changed what
  record.py       the studio step (worker: studio), cost roll-up, summary
  render.py       render service: CDP client to headless Chrome; queue; thumbnails
  versions.py     snapshots, restore, keep, branches
  kernel.py       the per-studio Python kernel (S2): process, RPC, reaping
  kernel_main.py  runs inside the kernel process
  comments.py     anchors, crops, comments.jsonl, notes bridge (S4)
  sources.py      sources, capture, findings, citations, questions (S5)
  tools.py        [studio] tools, dev-server processes (S6)
  export.py       pandoc, deck exports, publish (S8)
src/work_packet/dash/
  studio.py       routes, the studio socket, content-origin handlers
  studio.js       the page: panes, canvas, conversation, version strip
  viewers/        one small JS module per kind (doc, image, table, chart, diagram, sketch, deck, page)
  templates/studio.html, studio_frame.html, sketch.html
  vendor/         vega, vega-lite, vega-embed, vega-interpreter, mermaid, excalidraw (built, §P0.5)
src/work_packet/prompts/studio.md   the studio agent's primer
tools/vendor/     package.json, lockfile, build.mjs, README (versions, licences)
tests/test_studio_*.py, tests/fakemodel/behaviors/studio.py, tests/fakechrome.py
```

`wpk studio …` CLI subcommands (for the agent's Bash and for people)
live in `cli.py`, calling `studio/` functions, as other commands do.

## 4a. S0: VS Code pilot (the design §11)

- [ ] Do worked example 1 (flaky-test analysis over `history.db` and a
  CSV) in web VS Code from the board, with Jupyter and Claude Code.
- [ ] Write `docs/experiments/studio-pilot.md`: what worked, where it hurt
  (anchoring comments, comparing versions, keeping findings, reviewing on
  a phone), time taken.
- [ ] Decide: go ahead as planned, or trim (for example, drop the canvas
  and build only the record, versions and comments around VS Code).

## 5. P0: Foundations

Each task: what, where, tests. Docs for the phase at the end.

- [x] **P0.1 Take and release (v1).** *As built:* `executor.take/release/
  taking/taken_by` (not `actions`, so they share the lease code with
  `admin`); owner in `status.md` as `taken_by` + `taken` (not `by`, which
  could be confused with other fields). Only RUNNABLE/SLEEPING packets
  become PAUSED/`studio`; NEEDS_INPUT, COMPLETED, FAILED, PAUSED keep their
  state with `taken_by` set, and release restores nothing but the owner. A
  take on a running packet is a pause request with `take: true`, landing
  at the commit whatever state the step ended in (or at the next start /
  the dispatcher's pass). `admin` refuses everything but pause on a taken
  packet; `resumable()` excludes it. CLI `wpk take`, `wpk release [--hold]
  [--force]` (`--force` because CLI `user@host` and a dash login differ).
  Dash: IN STUDIO badge on cards, banner on the task page, hand-off form
  hidden. Tests: `tests/test_studio_take.py` (12).
  - `actions.take(pkt, why)` and `actions.release(pkt, how="resume"|"hold")`.
    Idle packet: `executor.admin(pkt, "pause", reason=why)`. Running: 
    `request_pause` with reason `studio`, and the studio waits for the
    commit (the page shows "taking over after this step").
  - `status.md` keeps `reason: studio` and `by: <user>`; the dash shows
    "In studio (matt)" on the card, task page and Overview, and the runner
    already leaves PAUSED packets alone.
  - Release `resume` → `admin(pkt, "resume")`; `hold` leaves it PAUSED
    with `reason: held`.
  - Tests (`tests/test_studio_take.py`): idle take/release; take while
    running (fake model mid-step) pauses at commit; double take by
    another user refused; release after the server restarts (state is all
    in files); runner does not pick a taken packet (`scheduler.due`).
- [x] **P0.2 Steps recorded from outside the executor.** *As built:*
  `executor.record_step(pkt, worker, summary, meta, files, notes_seen,
  state)` → `(Outcome, n)`, under the lease; refuses while an unfinished
  step needs `wpk recover`. Writes `meta.json` (+`worker`), `summary.md`,
  `result.md` (the unchanged memento, so memento readers work), an empty
  `state.diff`, and `files`; journals `step-start` (with `worker`,
  `session_id`) and `commit-begin` (decision keeps state, resume, wake,
  waits, `next_size`; `worker` in it), then `_apply`. `_carry_from` never
  carries a non-agent step's session. Readers: `stats.Step.worker`,
  `wpk stats --by worker`, `worker` on `dash.data.steps()` rows, a badge in
  the Steps tabs and on the step page. Tests:
  `tests/test_studio_record.py` (5).
  - Factor out of `executor._run` a `record_step(pkt, worker, meta,
    summary, files, notes_seen)` that writes `steps/NNNN/`, journals
    `step-start`/`commit-begin`, and applies through `_apply` without
    changing the memento or state (or with a given state).
  - `meta.json` gains `worker` (`agent` when absent). Readers that assume
    `harness`/`profile` (`dash/data.py`, `stats.py`, `history.py`,
    `dash/tokens.py`) tolerate a studio step and label it.
  - Tests: a recorded step appears in the Steps tab, in cost totals and
    in `history.db` harvest; a crash between `commit-begin` and `_apply`
    recovers as for normal steps (`tests/test_crash.py` pattern);
    `wpk check` accepts it.
- [x] **P0.3 A write-capable agent mode in `dash/agent.py`.** *As built:*
  `Agents.new(..., mode="studio")`; `_studio_spec` builds a `StepSpec`
  (project tools + `STUDIO_TOOLS` Read/Write/Edit/Glob/Grep, `acceptEdits`,
  `step_budget_usd`, `executor.step_dirs(pkt)`, notes inbox) for
  `harness.get("claude").command`; new `StepSpec.resume_same` makes later
  turns `--resume <session>` without a fork. `ask()` raises `NotTaken`
  unless the asker holds the take. cwd from `agent.studio_place(entry,
  wpid)` (root: the packet folder; child: its `work/`). The path hook gains
  `WPK_PROTECT` / `WPK_PROTECT_ALLOW` (`agent.protected()`): Edit/Write of
  `.work-packet/` (or legacy `packets/`, `project.toml`) are refused. No
  `[studio]` model/budget overrides yet (S7.4). The fake model gained
  Write calls that go through the PreToolUse hooks; behaviour
  `tests/fakemodel/behaviors/studio.py`. Tests:
  `tests/test_studio_agent.py` (8).
  - Conversations get a `mode` in `meta.json`: `console` (today) or
    `studio`. `Agents.command()` for `studio` builds its argv through
    `harness.get("claude").command(StepSpec)` so the tools, allowlist,
    `--add-dir` (work dir, identity, `workspace.linked_dirs`) and
    `hook_settings` (bghook, pathhook, notes hook) are the step's.
  - Permission mode `acceptEdits` plus the packet's Bash allowlist; model
    and budget from the packet (`[studio]` overrides, §S7.4), not
    `[console]`.
  - cwd = the packet folder. Refuse `studio` mode unless the packet is
    taken by the caller (P0.1).
  - Tests: argv for `studio` vs `console` (no write tools in console);
    refusal when not taken; fake behaviour `studio` that emits Write/Edit
    tool events and writes files; transcript and cost recorded.
- [x] **P0.4 Render service (`studio/render.py`).** *As built:*
  `find_browser` (google-chrome first: snap Chromium cannot write the
  hidden `$WPK_HOME`), `Browser` (one process, `--remote-debugging-port=0`,
  the ws URL read from stderr, profile in `$WPK_HOME/run/render-profile`,
  `reap()` after `[studio] render_idle_minutes`), `render(url, png, pdf,
  selector, full_page, width, height, script)` → `{ready, png, pdf, value,
  errors, size}` (errors: console errors, exceptions, error log entries),
  `Queue` (newest per key, `last(key)`). CDP client on
  `websockets.sync`; `[studio]` config validated in `schema.py`. The `live`
  marker now covers a browser too. Tests: `tests/test_studio_render.py`
  (8 + 1 live, with a PNG pixel reader), fake browser
  `tests/fakechrome.py`.
  - Find a browser: `[studio] chrome` in config, else `chromium`,
    `chromium-browser`, `google-chrome` on PATH. None → renders are
    skipped and the UI says so (the studio still works).
  - One headless Chrome per server (`--headless=new
    --remote-debugging-pipe` or a port on loopback), started on first use,
    reaped when idle, like `ide.Backend`.
  - A small CDP client over `websockets` (already a dash dependency):
    open page, wait for a ready signal (`window.__studioReady`), screenshot
    full page or an element, print to PDF, evaluate a script (for overflow
    checks), close.
  - A queue per artifact: only the newest request runs; the last good
    render is kept.
  - Tests: unit tests against `tests/fakechrome.py` (a fake CDP endpoint
    replaying canned responses); `live`-marked tests with real Chrome
    rendering a fixture HTML to PNG and PDF and checking size and a pixel.
- [x] **P0.5 Vendoring pipeline.** *As built:* `tools/vendor/`
  (`package.json`, lockfile, `entries/`, `build.mjs`, README). Pins: vega
  6.4.0, vega-lite 6.5.0, vega-embed 7.3.0, vega-interpreter 2.3.2,
  **mermaid 11.17.2** (not 12: mermaid-to-excalidraw 2.2.2, Excalidraw
  0.18.1's, imports Mermaid 11 internals), @excalidraw/excalidraw 0.18.1,
  **react 18.3.1** (radix peers ≤ 18), esbuild 0.28.2. Two bundles:
  `dash/vendor/vega/` (0.84 MB) and `dash/vendor/draw/` (Mermaid +
  Excalidraw + mermaid-to-excalidraw built together to share chunks; 8.93
  MB, 219 files; the 13 MB CJK font left out). Served at
  `/static/vendor/<path>` by `dash/vendored.py` from `manifest.json`
  (week-long cache, ETag/304); package data `dash/vendor/**/*`. Tests:
  `tests/test_studio_vendor.py` (5). Mermaid/Excalidraw under the CSP is
  still to check (P0.6 live).
  - `tools/vendor/package.json` + lockfile pinning vega, vega-lite,
    vega-embed, vega-interpreter, mermaid, @excalidraw/excalidraw 0.18.x,
    @excalidraw/mermaid-to-excalidraw, react, react-dom; `build.mjs`
    (esbuild) writes ESM bundles to `dash/vendor/<lib>/` and a
    `manifest.json` (file → sha, size).
  - Serve vendor files by manifest (replacing per-file `STATIC` entries
    for vendor; Excalidraw alone is ~180 files), with long cache headers;
    package-data glob in `pyproject.toml`.
  - `tools/vendor/README.md`: versions, licences, how to rebuild, sizes.
  - Tests: every manifest file is served with the right type; unknown
    paths 404; the manifest matches the files (catches a half-done
    rebuild); a size budget check (warn above the numbers in the README).
  - Note: Vega must use `vega-interpreter` (`ast: true`) to run under
    `script-src 'self'` without `unsafe-eval`. Check Mermaid and
    Excalidraw under the CSP in P0.6's live test.
- [x] **P0.6 Frames and a content origin.** *As built:* `guard.FRAME_RX`
  / `FRAME_HEADERS` (CSP adds `'wasm-unsafe-eval'`, `font-src 'self'
  data:`); `studio/content.py` (`Tokens`, process-wide `TOKENS`, 12 h TTL,
  `file_for` refuses `..`, dot-dirs, links out); the guard's `_content`
  checks the token in place of the login (also on the network listener,
  which would otherwise want a cookie), GET/HEAD only, replaces CSP with
  the sandbox one, adds `no-referrer` + `no-store`, strips `Set-Cookie`;
  route `GET /sc/{token}/{path}`. Excalidraw's esm.sh font fallback is
  removed at build time (`no-cdn-fonts` plugin in `build.mjs`), so its
  fonts load only from `/static/vendor/draw/`. Tests:
  `tests/test_studio_content.py` (5 + 2 live: the sandbox escape attempt,
  and Vega/Mermaid/Excalidraw rendering under the frame CSP with no
  violations, against a real uvicorn + Chrome).
  - Per-route headers: studio frames (`/p/{p}/{wpid}/studio/frame/…`,
    sketch editor) get `frame-ancestors 'self'` and `X-Frame-Options:
    SAMEORIGIN` instead of `none`/`DENY`; `img-src` adds `blob:`;
    `worker-src 'self' blob:` where a library needs it.
  - **Untrusted content** (agent-made HTML pages, deck dev servers, HTML
    from documents) is served under `/sc/<token>/…` with
    `Content-Security-Policy: sandbox allow-scripts allow-popups
    allow-downloads` (an opaque origin: no cookies, no CSRF token, no
    access to the dash), shown in `<iframe sandbox="allow-scripts">`
    without `allow-same-origin`. The token is a per-studio random
    capability checked by the guard instead of the login (the frame
    carries no cookies), expiring when the studio closes.
  - Tests: header sets per route; `/sc/` without or with a stale token is
    refused; `/sc/` responses never set cookies; a `live` test loads a
    page under `/sc/` that tries to read `document.cookie` and to POST to
    a dash route, and both fail.

**P0 docs (done):** a "Taking a packet" section in `docs/interaction.md` (§6b);
`worker` in the step record in `docs/packet-format.md`; render service and
content origin in a new section of `docs/server.md` (§6a); `tools/vendor/README.md`;
also `docs/spec.md` (`taken_by`, `taken`, `worker`).

**P0 exit (met 2026-10-30, by tests):** take/release works from the CLI (`wpk take`, `wpk release`);
a fake studio conversation can edit files in a taken packet; a fixture
page renders to PNG; vendor bundles serve; the sandbox test passes.

## 6. S1: Studio shell, documents, recording

- [x] **S1.1 `studio/model.py`.** *As built:* state is JSON,
  `.studio/studio.json` (canvas, layout, `session` now open, `sessions`
  before) + `baseline.json` (hashes at open, for "files changed"). API:
  `folder`, `state`, `open_studio(entry, wpid, user, conv)`, `set_conv`,
  `pin`, `unpin`, `set_layout`, `changed`, `close_studio(..., how,
  summary)`. Root packet: the packet folder; a child only with a `work/`
  (else `StudioError`). Git: `/.studio/` in `.git/info/exclude` (on its own
  line: git has no trailing comments). Close revokes the folder's content
  tokens. `open(pkt, user)` (take, create
  `.studio/` with `studio.toml`: canvas list, layout, open comments
  count), `close(pkt, how, summary)`, `state(pkt)`. `.studio/` is added to
  the packet folder's ignore list where there is git.
  - Tests: open/close round trip; reopen restores the canvas; two
    users.
- [x] **S1.2 `studio/kinds.py`.** *As built:* `Kind(name, patterns,
  viewer, anchor, render, exports, icon)`, ordered registry
  (`register(kind, before=)`), `kind_of`, `get`. `Kind(name, patterns, viewer, anchor,
  render, exports)`, registry, `kind_of(path)`. S1 kinds: document
  (`.md`), image (`.png .jpg .svg`).
  - Tests: classification, unknown files, patterns overlap rules.
- [x] **S1.3 `studio/watch.py`.** *As built:* `Watcher(root).poll()` →
  created/modified/deleted/renamed (rename by content hash) with `by`
  agent/you/outside from `agent_wrote()`/`saved()` marks within 10 s;
  touched-but-same files are not changes; files > 64 MB compared by
  size+mtime; excludes `.work-packet .git .studio node_modules packages
  .venv`, top-level dot-dirs, and a legacy project's `packets/` and
  `project.toml`. `diff(before, after)`. Poll mtimes and sizes of the packet
  folder (excluding `.work-packet`, `.git`, `packages/`) every 500 ms while
  a studio socket is open; hash on change; attribute each change to
  `agent` (a Write/Edit tool event in the same window), `you` (a save
  through the dash) or `outside` (anything else, e.g. the IDE).
  - Tests with `WPK_NOW` and a fake clock tick: create, modify, delete,
    rename; attribution.
- [x] **S1.4 Routes (`dash/studio.py`).** *As built:* `routes(home,
  agents, render, entry, who, not_found)` added to `create_app` before the
  catch-alls: page, `open` (takes, makes the `studio` conversation, form
  POST → redirect), `close` (form: `how`, `summary`), `draft`, `canvas`,
  `pin`/`unpin`/`layout`, `ask`, `cancel`, `markup`, `file`, `frame/doc`,
  `ws`. All but the page and `open` answer 403 unless the caller holds the
  take and the session is open. `file` never serves a page on the board's
  origin (HTML as text; `CSP: sandbox` on every raw file). The socket polls
  a per-studio `Live` (watcher + "yours" + this turn's agent changes) every
  0.5 s. Tests: `tests/test_studio_dash.py` (7).
  - `GET /p/{p}/{wpid}/studio` page; `POST …/studio/open`, `…/close`;
    `GET …/studio/canvas` (JSON); `POST …/studio/pin`, `…/unpin`,
    `…/layout`; `GET …/studio/file?path=` (raw, for viewers);
    `WS …/studio/ws`: conversation events (reusing the console's
    transcript events) plus `changed`, `pinned`, `render` events.
  - Registered before the `/p/{project}/{wpid}/{step}` catch-all.
  - Tests: TestClient + Guard, CSRF on every POST, token on the socket,
    403 when the packet is not taken by the caller, 404 on paths outside
    the packet folder (`..`, symlinks out).
- [x] **S1.5 The page.** `templates/studio.html`, `dash/studio.js`.
  *As built:* documents render in a same-origin **frame**
  (`studio_frame.html`, `base.html` gained a `frame` mode without header and
  drawer; markup CSS moved to `_markup_css.html`) and reuse `markup.js`
  unchanged, posting to `.../studio/markup`; "Ask Claude" goes to the
  studio agent. The conversation renderer is in `studio.js` (not a module
  shared with `console.js`, which is an IIFE bound to the drawer; revisit
  if they drift). Close dialog fetches the draft for edit. `base.html` got a
  `data:` favicon (the board 404'd `/favicon.ico` on every page). Live
  smoke: `tests/test_studio_live.py` (no console errors; frame, image,
  markup drawn).
  - Conversation pane: move the rendering functions out of
    `console.js` into a shared module both use.
  - Canvas: tabs and a two-up tile; artifact cards with kind icon,
    name, last changed by.
  - Document viewer: the doc-markup rendering as a fragment (factor
    `file_page()` so it can render into the canvas), with markup and
    "Ask Claude" sending into the studio conversation instead of a note.
  - Image viewer.
  - Tests: page renders for a taken packet with a document; the
    fragment route returns the same HTML as `doc.html`'s article; a
    `live` smoke test loads the page in headless Chrome with no console
    errors.
- [x] **S1.6 Output in the conversation.** *As built:* at a turn's `end`
  the socket polls once and appends an `output` event (files of a known
  kind the agent created or changed) to the transcript, once per turn
  however many sockets; cards have Pin, Open and a preview. When a turn creates or changes
  a file of a known kind, the turn ends with a card (rendered preview for
  documents and images) with **Pin** and **Open**.
  - Tests: from fake transcript events to cards; unknown kinds get a plain
    file link.
- [x] **S1.7 Primer (`prompts/studio.md`).** *As built:*
  `studio/primer.py build(entry, wpid, state, files, yours, memento)`:
  guide, packet and folder, instruction (2000 chars), canvas, other
  known-kind files, "Changed by the person since your last turn"; budget
  12000 chars. Snapshot-style checks in `test_studio_dash.py` (the primer
  names the person's change). What the studio is; the
  canvas (kinds, paths); "you changed …" list (from S1.3); conventions
  (text sources, where to put files: `docs/`, `charts/`, `data/`,
  `sketches/`, `assets/`); doc markup resolution; how to look at renders
  (S3). Built per turn by `studio/model.py`.
  - Tests: primer snapshot for a fixture studio; size stays under a
    budget.
- [x] **S1.8 Recording (`studio/record.py`).** *As built:* `record()`
  at close via `record_step(worker="studio")`: `transcript.jsonl` (the raw
  stream, so stats parse tokens) + `studio-transcript.jsonl`; cost = the
  conversation's (chain total); `meta.studio` {by, turns, conversation,
  created, modified, deleted, versions, comments}. Nothing recorded for a
  session with no turns and no changes. `draft_summary()` asks the
  console's model (one `claude -p --output-format json`, $0.05 cap), else
  `plain_summary()` from the facts. Still to do in S1.5: the close dialog
  that shows the draft for edit. On close: one step via
  `record_step(worker="studio")` with the transcript (copied from the
  console dir), cost summed from the replies, duration, files changed,
  comments sent, versions made (empty until S3). Summary: a one-shot
  cheap-model call drafts it from the transcript head and the changed
  files; the close dialog shows it for edit. With no model available, the
  person writes it.
  - Tests: step contents; cost equals the sum of replies; closing twice
    is a no-op; a studio left open over a restart can still be closed and
    recorded.
- [x] **S1.9 Entry points.** *As built:* "Open studio" (or "… after this
  step") on the task page when `data._studio_ok`; "Return to the studio" /
  "See the studio" when taken; `wpk studio open|close|status` (close
  `--hold --summary --force`); `/studio [packet]` in the console drawer
  (navigates; the root packet on a project page); a Studio panel on the
  project Overview (Return/See when taken). "Open studio" on the task page and the
  project page (root packet); `/studio` in the packet console; `wpk
  studio open|close|status <packet>`; "In studio" badges.
  - Tests: buttons by state (offered when idle or running, "return to
    studio" when taken by you, shown read-only when taken by someone
    else).

**S1 docs (done):** start `docs/studio-guide.md` (user guide: open, talk, pin,
comment on documents, close); update `docs/console.md` (modes),
`docs/doc-markup.md` (in the studio); README docs list.

**S1 exit (manual check):** open a studio on a scratch packet; ask for a
one-page findings document; it renders on the canvas; comment on a
sentence; the agent resolves it; edit the file in VS Code and see the
canvas update with "changed by you"; close; the Steps tab shows "studio,
N min, $x" with the summary.

*Done 2026-10-30, scripted:* `scripts/studio_s1_check.py [--model sonnet]
[--shot out.png]` runs it end to end on a scratch home with the real model
(a board on loopback, the routes the page uses, the socket). Everything but
"edit in VS Code" is the same path a person takes; the outside edit is a
plain file write, which is what VS Code does, so it shows as "by outside"
(not "by you": "you" is a save through the board). Runs: haiku $0.04–0.06,
all checks pass but it miscounted a test's failures (4 of 7, not 5);
sonnet $0.16, all pass with the right counts. Screenshot:
`docs/experiments/studio/s1-studio.png`. Found and fixed on the way: an
edit from outside within 10 s of the agent's was credited to the agent (a
mark now explains one change only); a board save is marked before the
write; tool lines show folder-relative paths.

## 7. S2: Data and charts

- [x] **S2.1 Kernel (`studio/kernel.py`, `kernel_main.py`).** *As built:*
  started by whoever calls first (the board or the CLI), detached, in the
  folder, `python -m work_packet.studio.kernel_main` with wpk's `src` on
  `PYTHONPATH` (so the packet's IVPM Python works when it has DuckDB);
  socket `/tmp/wpk-<uid>/k-<hash>.sock` (0700; a socket path under the
  folder is too long), `.studio/kernel.json` and `kernel.log`. One request
  per connection. Ops: `ping exec query page stats records selected tables
  datasets reset shutdown`. The kernel exits itself after
  `kernel_idle_minutes` (pings don't count); a call over `kernel_timeout_s`
  kills it; closing the studio stops it. All DuckDB runs in the kernel,
  not the dash: DuckDB's sandbox (`allowed_directories`) resolves relative
  paths against the process cwd, so only a process in the folder gets both
  relative paths and the sandbox (`file_search_path` does not pass the
  check). Two connections: the agent's (open) and the viewers' (sandboxed,
  SELECT only). A kernel whose cwd is not the folder (removed and made
  again at the same path) is replaced; exec's `chdir` is undone after each
  call. The extra is `studio = ["duckdb"]` (no pandas: DuckDB reads the
  files itself; the kernel uses pandas if the venv has it). One process
  per open studio, started on first use; Python from the packet's IVPM
  per open studio, started on first use; Python from the packet's IVPM
  venv when it has duckdb, else wpk's own; JSON-lines RPC over a unix
  socket: `exec(code)`, `query(sql, page, size, sort, filter)`,
  `datasets()`, `schema(path)`, `reset()`. Outputs: stdout/stderr text,
  rows (JSON, paged), images written to files. Idle reap with the
  studio; restart on demand; a time limit per call.
  - New optional extra `studio = ["duckdb", "pandas"]`; the studio
    explains what's missing when absent.
  - Tests: exec state persists across calls; a crash restarts cleanly;
    timeouts; query paging and sort over a fixture CSV and Parquet (skip
    when duckdb is not installed).
- [x] **S2.2 `wpk studio exec|query|datasets`** *As built:* find the
  studio from the cwd (`model.find`: `.studio/studio.json` now records the
  project); `exec CODE | -f FILE | -` (prints stdout, the last expression,
  stderr; `--reset`), `query SQL [--limit N] [--out f.csv|.parquet]` (text
  table), `datasets`; `wpk studio status` with no packet in a studio
  folder. Added to `STUDIO_TOOLS` as `Bash(wpk studio exec *)` etc. For the
  agent (added to
  the studio Bash allowlist), talking to the kernel; results as text
  tables or a written file.
  - Tests: CLI round trip against a running kernel.
- [x] **S2.3 Table kind and viewer.** *As built:* `studio/data.py` (runs
  in the kernel): sources (file, SQLite table, `.sql`, SQL text), `page`
  (sort, contains-filters per column, offset/limit ≤ 1000), `stats`
  (SUMMARIZE), `records`, `selected`, `datasets`, `check_select`
  (`extract_statements`: exactly one SELECT). Routes `/table`,
  `/table/stats`, `/table/tables`, `POST /sql`, `POST /sql/save`. The
  viewer is in `studio.js` (not a frame): grid, sort, filters, pager,
  Stats, SQL box with Save as .sql (pins it). Any data file changing
  reloads the canvas's tables and charts (so a `.sql` follows its inputs).
  SQLite needs DuckDB's sqlite extension (loaded before the lock; refused
  if not installed). Kinds: `.csv .parquet .jsonl`,
  `.sqlite` (tables listed), `.sql` (a saved query). Viewer: paged grid,
  server-side sort/filter through DuckDB, column stats (type, nulls,
  min/max, distinct), a SQL box (no model) that can be saved as `.sql`.
  - Tests: route paging; `.sql` re-runs when an input file changes;
    SQL box limited to read-only statements (DuckDB in read-only mode on
    the files).
- [x] **S2.4 Chart kind and viewer.** *As built:* `studio/chart.py`
  (`check`, `for_board` rewrites every `data.url` to `/studio/data?path=`
  with JSON rows, `theme` from the dash tokens (`PALETTE`/`INK`, tested
  against `base.html`), `summary`/`apply` for the spec panel). Data URLs
  are relative to the spec (like links). The frame is
  `/studio/frame/chart` (`studio_chart.html` + `studio_chart.js`, a
  module). Selections: params with `select` anywhere in the spec; the
  value less Vega's own keys; "Ask" posts `/select`, the kernel picks the
  rows (`selected`: intervals, points; epoch ms on date columns), and the
  question goes to the agent with up to 50 rows as a text table and the SQL
  filter. `?sql=` data URLs were not needed: a chart names a `.sql` file.
  `.vl.json`; vega-embed with
  `vega-interpreter`; data by URL to `…/studio/data?path=` or
  `?sql=<file>` (rows from the kernel); a spec panel (mark, x, y, color,
  scale, title) editing the JSON directly; selections (brush, click) send
  the selected rows as an anchor (S4 generalises anchors).
  - Studio theme: a Vega config generated from the dash tokens
    (`dash/tokens.py`, `_tokens.html`), light and dark, following the
    dataviz palette rules.
  - Tests: spec validation (required fields, data by path inside the
    packet only); the data route; theme config shape; `live`: a fixture
    chart renders without CSP errors.
- [x] **S2.5 Data sources beyond files.** *As built:* `history.steps`
  only: wpk writes the project's steps (`stats.collect`, which already
  merges harvested history) to `.studio/history/steps.jsonl` (at most every
  30 s, before kernel calls) and both connections have a typed view over
  it. Scoped to the project, so a shared board does not show other
  projects' history. Spaces wait for R1. `history.db` (read-only views
  of steps and cost), and (when routines R1 exists) a space's series as a
  table.
  - Tests: views exist and are read-only.
- [x] **S2.6 Primer and kinds** *As built:* the primer's "## Data" (the
  kernel's `datasets`, when the folder has table files); `prompts/studio.md`
  "Data and charts" (query, don't count by eye; history.steps; exec; saved
  queries; Vega-Lite by path; chart style; add a selection). Planned:
  datasets list with schemas, "use `wpk studio query` for questions about
  data, write charts as Vega-Lite referencing files".

**S2 docs (done):** `studio-guide.md` sections "Data" and "Charts" (with
the `studio` extra; `docs/setup.md` is about project setup, so the extra
is in the guide); the kernel in `docs/server.md` §6a.

**S2 exit:** worked example 1, part one: load `history.db` and a
regression CSV, ask "which tests flip most?", get a table and a chart,
brush a range and ask about those rows, pin both.

*Done 2026-10-30, scripted:* `scripts/studio_s2_check.py --model sonnet`
(shared board helper `scripts/_studio_board.py`; the S1 script uses it
too). A 30-night × 12-test CSV with known flip counts; the agent wrote
`queries/flips.sql` and `charts/flips.vl.json` (with a selection) using
`wpk studio query`, named the right top three, and the saved query's
counts match exactly; a selection of the top two bars went to the agent
with its rows and it answered about them; both pinned two-up; screenshot
`docs/experiments/studio/s2-studio.png`. sonnet: $0.18 a run (6 tool
calls for the first question). The first run found a stale kernel
answering for a re-made folder (the agent flailed for ~20 calls, $0.35,
then worked around it with `os.chdir`); fixed (replace a kernel whose cwd
is not the folder; undo exec's chdir), plus `wpk studio status` without a
packet, which the agent tried.
`history.db` itself is not in the check (the scratch project has no
steps); `history.steps` is tested in `test_studio_kernel.py`.

## 8. S3: Renders, versions, self-check

- [ ] **S3.1 Renders per kind** through the render service: documents
  (the fragment page), images (resized), charts (vega view → SVG/PNG in a
  render page), tables (first page as HTML). Thumbnails in
  `runs/<id>/studio/renders/` keyed by content hash; images stored in
  blobs.
  - Tests: one per kind with fake Chrome; cache hit on unchanged content;
    a `live` test per kind.
- [ ] **S3.2 Versions (`studio/versions.py`).** At the end of each turn
  that changed tracked files: `runs/<id>/studio/vNNNN/manifest.json`
  (path → blob sha, render shas, parent, turn id, who); files into blobs.
  Restore (writes files back, as a new version); Keep (a flag).
  - Tests: version per changing turn, none for a no-change turn; restore
    round trip byte-exact; deleted files; large files (size limit,
    skipped with a note).
- [ ] **S3.3 The strip.** Thumbnails, view, compare two side by side,
  flip in place, restore, keep; S1.8's record lists versions.
  - Tests: routes and JSON; `live` smoke.
- [ ] **S3.4 The agent looks.** `wpk studio look <path> [--part N]`
  writes the render PNG and prints its path; the primer says to `Read`
  the image of what it changed before ending a turn.
  - Tests: CLI; fake behaviour checks it is called; `live` with the real
    model on one example (manual).
- [ ] **S3.5 Cheap checks.** In the render page: overflow (scroll size >
  box) per element, broken images and embeds, Vega warnings; flags on the
  thumbnail and in the next turn's primer.
  - Tests: fixture pages with each fault are flagged; clean ones not.

**S3 docs:** guide "Versions"; design doc §5.3/§5.4 updated with what was
built.

**S3 exit:** worked example 1 complete: three charts tried, two kept, a
one-page document; flip between versions; the agent catches an
overflowing title by itself.

## 9. S4: Comments everywhere, diagrams, sketches, embeds

- [ ] **S4.1 Anchors (`studio/comments.py`).** `anchor = {artifact, kind,
  where}`; per-kind `where` schemas (document: line range + occurrence;
  chart: rows + mark; table: cells/rows/columns; diagram: node/edge id;
  sketch: element ids; image/page/deck: region box). Crops via the render
  service. `.studio/comments.jsonl`; documents keep CriticMarkup.
  - Notes gain optional `anchor` and `image` (`notes.py`); `ctxhook.py`
    and the prompt builder mention the image path so the agent can `Read`
    it.
  - Tests: schema per kind; crop geometry; notes back-compat (old entries
    load); "addressed in vN" set when the agent replies naming it.
- [ ] **S4.2 Comment UI per viewer** and pins on the canvas.
  - Tests: routes; `live` smoke per viewer.
- [ ] **S4.3 Diagrams.** `.mmd` (Mermaid, in the browser), `.dot`
  (Graphviz via `dot -Tsvg` when installed), node/edge ids from the SVG.
  - Tests: render, ids, missing `dot` handled.
- [ ] **S4.4 Sketches (Excalidraw; design §4.1).**
  - `templates/sketch.html` in a frame (P0.6 headers), the vendored
    bundle, `EXCALIDRAW_ASSET_PATH` to our fonts.
  - Save on change (debounced) through `POST …/studio/sketch` with the
    file sha; 409 on a stale sha → the page fetches the file and merges by
    element `version` (`reconcileElements` or our own merge on id +
    version), then saves.
  - Reload when the watcher reports an agent change.
  - Selection → element-id anchors.
  - Agent paths: `wpk studio sketch --from-mermaid F` and `--from-skeleton
    F` run `mermaid-to-excalidraw` / `convertToExcalidrawElements` in the
    render service's headless page (no Node at runtime) and write the
    `.excalidraw` file.
  - Thumbnails via `exportToSvg` in the render page.
  - Tests: save/409/merge with two fixture scenes (Python-side merge
    tests if the merge is ours); skeleton and Mermaid conversion
    (`live`); a hand-made fixture file renders; CSP clean (`live`).
- [ ] **S4.5 Embeds.** A markdown-it rule (server: `markdown-it-py`
  plugin next to `markup.plugin`) renders `![](charts/x.vl.json)`,
  `![](sketches/y.excalidraw)`, `![](diagrams/z.mmd)` as live viewers on
  the canvas and as render images in exports; a changed chart re-renders
  everywhere.
  - Tests: plugin output; missing target; cycles (a doc embedding
    itself).

**S4 docs:** guide "Comments", "Diagrams and sketches", "Embedding";
`docs/doc-markup.md` (anchors beyond Markdown); `docs/interaction.md`
§6a (notes with anchors and images).

**S4 exit:** worked example: sketch an architecture by hand, ask the agent
to "add a DMA block next to the bus", comment on a box, embed the sketch
in a document.

## 10. S5–S8 (planned in outline; detail when each starts)

### S5 Research
- [ ] S5.1 `studio/sources.py`: `sources.jsonl`; capture from the
  transcript's tool events (WebFetch, WebSearch, Read of files outside the
  canvas): URL, time, snapshot into blobs, extracted text; PDFs (text via
  `pdftotext` when present, metadata).
- [ ] S5.2 Sources pane and reading view: highlight → quote into a
  document with a citation, comment, or make a finding.
- [ ] S5.3 Findings: `findings.jsonl`, UI, links to sources and artifacts;
  publish as items when routines R1 exists (else kept local, flagged).
- [ ] S5.4 Citations: `[@key]` markdown-it rule, reference list, cheap
  check for numeric claims without a citation and dead sources.
- [ ] S5.5 Questions log (`.studio/questions.md`); open ones go into the
  packet report's open items at done.
- [ ] S5.6 Board-level source library (in the board's space; needs R1).
- Tests: capture from fixture transcripts (fake behaviour emitting
  WebFetch events), snapshots, citation rule, findings round trip.
- Docs: guide "Research"; social.md cross-reference for findings.
- Exit: worked example 2 (RISC-V verification tools survey, 15 sources,
  a table, a page with citations).

### S6 Tool kinds
- [ ] S6.1 `[studio]` in `project.toml`: `tools`, and per-kind `run` /
  `build` / `watch` / `export` (design §4, the earlier `[preview]`);
  schema validation in `schema.py`.
- [ ] S6.2 Dev-server processes (`studio/tools.py`), reusing `ide.Backend`
  patterns (Popen, socket or port, readiness, idle reap), proxied under
  the content origin `/sc/<token>/` including HMR WebSockets.
- [ ] S6.3 Deck kind (Slidev, then Marp): slide index from the source,
  slide-to-source mapping, per-slide renders, deck viewer with slide
  strip.
- [ ] S6.4 Quarto documents; figure kind (scripts run in the kernel).
- [ ] S6.5 Starters: `deck`, `report`, `analysis` with working `[studio]`
  settings (docs/writing-a-starter.md).
- [ ] S6.6 Templates (board or packet) and assets by drag and drop
  (multipart upload into `assets/` + blobs).
- Tests: process lifecycle with a fake dev server; proxy incl. WS; slide
  mapping on fixture decks; starters make a packet that opens a studio
  with a rendering deck (`live`).
- Docs: guide "Decks"; writing-a-starter.md; setup.md (Node, Slidev).
- Exit: worked example 3 up to a finished deck in the studio.

### S7 Branches, shared editing, speed
- [ ] S7.1 Branches in `versions.py` (a version tree), adopt, compare
  across branches; parallel variants via the agent's own sub-agents
  writing to branch folders.
- [ ] S7.2 "You changed …" per turn in the primer (from S1.3), and the
  agent re-reads before editing.
- [ ] S7.3 Direct manipulation: spec-panel edits, table cell edits, slide
  reorder, legend colours; each a small source edit attributed to you.
- [ ] S7.4 Model per turn (fast default, "Think harder"), `[studio]
  model` and `deep_model`; running cost in the header; packet budget
  applies.
- [ ] S7.5 `interactive` scheduling class (internal, not user-settable),
  for when studio turns run as scheduler jobs; v1 runs on the server
  (D12), so this only reserves the class and the gate rule.
- Tests: version tree operations; primer change lists; direct edits
  produce exact JSON edits; model switching argv; class ordering.
- Docs: guide "Branches", "Speed and cost"; scheduler.md (class).

### S8 Export, publish, phone
- [ ] S8.1 Exports: pandoc (HTML, PDF, docx) with embeds rendered; deck
  exports via the tool; PDF by Chrome print as the fallback.
- [ ] S8.2 Deliverables at done: kept artifacts and exports, with
  renders.
- [ ] S8.3 Publish to spaces (pages, tiles, items; needs routines R1).
- [ ] S8.4 Phone layout: one artifact at a time, the strip, tap to
  comment; sketching allowed on touch.
- Tests: export commands (fake pandoc), deliverables list, publish calls,
  phone layout `live` at 390 px width.
- Docs: guide "Finishing and publishing"; routines-and-outputs.md
  cross-references.

## 11. Test strategy

- **Unit (pytest, default run):** everything in `studio/` is plain Python
  with files in `tmp_path`; `WPK_NOW` for time; no network.
- **Dash:** `TestClient(create_app(...))` wrapped in `Guard` for every
  route that changes state (CSRF) and every socket (token); copy
  `tests/test_console.py:227`.
- **Fake model:** a `studio` behaviour in `tests/fakemodel/behaviors/`
  that scripts turns: emit Write/Edit tool events, write files, call
  `wpk studio look/query`, end. Faults via `WPK_FAKE_FAULT`.
- **Fake browser:** `tests/fakechrome.py` serves canned CDP replies so
  render-queue and caching logic run without Chrome.
- **Live (`-m live`, not in the default run):** real Chrome (renders,
  CSP, sandbox, page smoke with no console errors), real DuckDB, and a
  few real-model checks. Each phase adds its live tests; run them before
  ticking the phase.
- **JS:** kept thin (viewers call routes; logic in Python where possible).
  No JS unit framework for now; the live smoke test loads each viewer and
  fails on console errors. Revisit if viewers grow logic (the sketch merge
  is the candidate).
- **Acceptance:** each phase's exit check is done by hand on the three
  worked examples and noted in the status log, with screenshots under
  `docs/experiments/studio/`.
- **Regression:** the full suite must stay green at each task; studio
  tests are named `test_studio_*.py`.

## 12. Doc plan

| Doc | Kind | Written in |
|---|---|---|
| `docs/interactive-tasks.md` | design | updated at each phase end: "as built" notes where the build differed |
| `docs/studio-plan.md` (this) | tracker | every session |
| `docs/studio-guide.md` | user guide | started S1, a section per phase |
| `prompts/studio.md` | the agent's guide | S1, extended per phase; tested as a snapshot |
| `tools/vendor/README.md` | maintainer | P0.5, updated on each rebuild |
| `docs/interaction.md`, `console.md`, `doc-markup.md`, `server.md`, `setup.md`, `packet-format.md`, `scheduler.md`, `writing-a-starter.md` | existing | the sections named in each phase's docs line |
| README docs list | index | when a new doc appears |

## 13. Risks

| Risk | Mitigation |
|---|---|
| Untrusted HTML on the dash origin (XSS against CSRF tokens) | P0.6 content origin and sandbox, tested live before any HTML kind ships |
| CSP breaks Vega, Mermaid or Excalidraw | vega-interpreter; per-route CSP for frames; P0.6 live tests per library |
| No `HELD` state; take via PAUSED may confuse "paused" views | reason `studio` shown distinctly; move to the long-running.md take design later without changing the studio |
| Recording steps outside the executor breaks readers | P0.2 tests across data, stats, history and check |
| Headless Chrome missing on farm hosts | studio runs on the server host; renders optional, UI says so |
| Excalidraw bundle size and React upgrades | pinned versions, size check, iframe isolation |
| Kernel runs agent-written code | same trust as a step's Bash; cwd and allowlist as for steps; revisit with the step sandbox question |
| Scope creep (S5–S8) | S0 pilot first; S5–S8 planned in outline only until S3 is done |

## 14. Status log

### 2026-10-30
- Plan written from the design (draft 2 with §4.1 Excalidraw and §11 VS
  Code) and a survey of the code. Decisions D1–D12 assumed. Next: S0 pilot
  and confirm decisions.

### 2026-10-30 (later): P0 and S1 built
- Merged origin/main (plugins, credentials, budget provider, site config)
  first; full suite green after the merge.
- P0.1–P0.6 built and tested (as-built notes above): take/release,
  `record_step`, the studio agent mode, the render service, vendored
  Vega/Mermaid/Excalidraw, frame headers and the `/sc/` content origin.
  Live checks run here with Google Chrome 134: sandbox escape attempts fail;
  Vega (interpreter), Mermaid and Excalidraw render under the frame CSP with
  no violations.
- S1.1–S1.9 built (as-built notes above), with `docs/studio-guide.md`.
- Tests: `tests/test_studio_*.py` (take 12, record 5, agent 8, render 8+1
  live, vendor 5, content 5+2 live, model 11, dash 7, live page 1). Run the
  live ones with `WPK_LIVE=1 pytest -m live tests/test_studio_*.py`.
- Not done: the S1 exit check by hand (open a studio on a scratch packet,
  ask for a findings document with the real model, comment, resolve, edit
  in VS Code, close); S0 pilot; `/studio` in the console drawer. Nothing
  is committed: the work is in the working tree next to the uncommitted
  changes that were there before.
- Next: the S1 manual exit check, then S2 (kernel, tables, charts).

### 2026-10-30 (evening): S1 finished, S2 started
- S1.9 rest: `/studio [packet]` in the console drawer; a Studio panel on the
  project Overview.
- S1 exit check run with the real model (see the S1 exit note): haiku and
  sonnet both pass; one real bug found and fixed (outside edits credited
  to the agent).
- `studio` extra (`duckdb`) added to `pyproject.toml` and the ivpm
  default-dev set; DuckDB 2.0.0 in `packages/python`.
- Full suite: 1043 passed, 8 skipped; one flake
  (`test_packet_layout.py::test_dash_pages_match_the_legacy_layout`, a step
  duration shown as 0.1s vs 0.2s between two crawls; passes alone; not
  studio code).

### 2026-10-30 (night): S2 built
- S2.1–S2.6 built (as-built notes in §7): the kernel (`studio/kernel.py`,
  `kernel_main.py`, `data.py`), `wpk studio exec|query|datasets`, table and
  chart kinds and viewers (`studio/chart.py`, `studio_chart.html/.js`, the
  table viewer in `studio.js`), `history.steps`, the primer's data section
  and the guide's "Data and charts". Config `[studio] kernel_idle_minutes`,
  `kernel_timeout_s`.
- S2 exit check: `scripts/studio_s2_check.py --model sonnet` passes ($0.18);
  S1's check moved onto the shared `scripts/_studio_board.py`.
- Fixed on the way: stale kernels (see the S2 exit note); `kernel.stop`
  now waits until the kernel is gone (a test saw it answer one more ping,
  about 1 run in 15); the SQL box showed
  when it should start hidden; a saved query's SQL box starts from its
  text; the guide says `.sql` paths are the folder's, chart paths the
  spec's (the agent first got it wrong, then fixed it itself).
- Full suite: 1061 passed, 9 skipped. Tests: `test_studio_kernel.py` (8),
  `test_studio_charts.py` (9), one more
  live test (chart + table on the page). Lint (ruff F) clean on the studio
  code; unused imports from S1 removed.
- Not done: brushing in a real browser is not automated (the selection's
  server side and the Ask are tested; the brush itself is Vega's); the
  conversation shows the agent's Markdown as plain text (since S1).
- Next: S3 (renders per kind, versions, the strip, the agent looks).
