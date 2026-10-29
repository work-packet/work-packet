# Built docs on the board (plan and status)

Started 2026-10-29. Status: **built** 2026-10-29 (S1–S5), not yet committed. Decisions: D-Q1 (a), D-Q2 auto +
manual, D-Q3 (a), D-Q4 **no sandbox** (formatting first).

## Why

Many projects keep Sphinx docs in the repo. When an agent changes code or
docs, you want to check how the docs now read. Today you have to find the
packet's work folder, work out which Python env has Sphinx, run
`sphinx-build`, and open `_build/html/index.html` yourself. The board
should do this for you: notice the docs, build them when they are out of
date, and put a link to them where you are already looking.

## What exists today

- There is no detection of project features in work folders. The nearest
  pattern is the readiness checks in `setup.py` (`_work` at `:378` walks
  each `work/` entry, and `_clone_checks` emits `Check`s).
- `/p/<project>/doc?path=work/...` (`dash/app.py:1394`, path safety in
  `dash/data.py:641 work_doc`) serves single files from `work/`. It renders
  Markdown, sends other text as plain text and stops at 4 MB. It cannot
  serve an HTML site with relative CSS, JS and images.
- The global CSP (`dash/guard.py:27`) is `script-src 'self'` with
  `frame-ancestors 'none'`. Sphinx themes ship their own scripts, and some
  use inline ones.
- The dashboard does not start builds. The closest precedents are the
  web VS Code launch (`dash/ide.py:183`, or `sched/ide_job.py` as a
  scheduler job) and console-agent threads (`dash/agent.py:230`).
- The `.pbar` action bar (`templates/_tabs.html:28-67`) already has
  **Open PR** and **Open in VS Code ▾**, which has a per-`work/` table.

## Proposal

### 1. Detect (`work_packet/docs.py`)

`detect(entry_dir) -> [DocSet]`. Each `DocSet` holds a name, a source
directory (the one holding `conf.py`) and a builder (`html`).

- Look for `conf.py` in the usual places first: `docs/`, `doc/`,
  `docs/source/`, `doc/source/`, `sphinx/`. If none is found, do a
  shallow search (depth ≤ 3) that skips `.git`, `packages/`,
  `node_modules/`, `_build/`, `build/`, `.venv/` and `runs/`.
- Accept a candidate only if its `conf.py` mentions `sphinx` or sets
  `extensions`/`html_theme`/`project =`. This filters out unrelated
  `conf.py` files.
- An optional override in the project's settings, `[docs]`, can set
  `source = "path"`, a `python = "..."` interpreter, or `enabled = false`.
- Cache detection by entry path and the mtime of the candidate dirs, so
  pages stay cheap.

Which work entries to scan:
- **Packet layout:** the single work folder.
- **Legacy layout:** each `work/<name>` entry.

Where a run is active, see D-Q1.

### 2. Build

`docs.build(project, docset)` runs
`<python> -m sphinx -b html -d <doctrees> <src> <out>` in its own process
group, with a 10-minute timeout. The output goes to a log file.

- **Interpreter.** Use the first of these that exists and can
  `import sphinx`:
  1. `[docs] python` from the project's settings
  2. `<entry>/packages/python/bin/python` (IVPM)
  3. `<entry>/.venv/bin/python`
  4. `direnv exec <entry> python`, when `.envrc` exists and direnv is
     installed
  5. the dashboard's own `sys.executable`

  If none of them can import Sphinx, the board says so plainly and shows
  the fix (for example `pip install sphinx` in that env). It does not
  install anything itself.
- **Output** goes outside the work tree, at
  `$WPK_HOME/docs/<project>/<entry>/<docset>/{html,doctrees,build.log,build.json}`.
  This keeps the folder clean whether or not it is a git repo (see
  [[packets-not-git-bound]]). Keeping the doctrees makes rebuilds
  incremental and fast.
- **Staleness.** Take a fingerprint of the newest mtime under the source
  dir, plus `conf.py`, plus the Python package dirs that `autodoc` might
  read (the entry's `src/` or top-level packages). Store it with the
  build. Docs are **stale** when the current fingerprint is newer. The
  check is mtime-only, so it is cheap enough for every page view, capped
  at a few thousand files.
- **When builds run** (see D-Q2):
  - on demand, through a **Build** or **Rebuild** button
  - automatically when a step ends, if the docs are stale
  - lazily, on the first click of **Docs** when nothing has been built yet

  Only one build runs per docset at a time (a lock file). A click during
  a build shows "building…" and the page refreshes when it is done.
- **Record.** `build.json` holds the start and end time, the result
  (`ok`/`warnings`/`failed`), the warning count, the source fingerprint,
  the git HEAD if the entry is a git repo, the run wpid it was built
  from, and the interpreter. Each build also adds a line to `builds.jsonl`
  so the board can show past builds ([[dashboard-is-central]]). Only the
  newest HTML is kept (see D-Q3).

### 3. Serve

New route `/p/{project}/docs/{entry}/{docset}/{path:path}`. It serves
static files from the built `html/` dir.

- **Path safety.** Use the same `realpath` containment as `work_doc`. A
  path ending in `/` (or an empty path) maps to `index.html`. The media
  type comes from `mimetypes`.
- **Its own CSP for this prefix only** (in `guard.py`, like the
  `IDE_PREFIX` special case): `default-src 'self'; script-src 'self'
  'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  font-src 'self' data:; frame-ancestors 'self'`. No `sandbox`, so themes
  work exactly as they do from disk (localStorage, theme toggles).
  Residual risk, accepted (D-Q4): script in the built docs runs on the
  board's origin with your session. If that ever matters, serve docs from
  a second port (a different origin), which isolates them without
  breaking themes.
- Responses are cached with `ETag`/mtime so moving between pages is
  quick.

### 4. Show

- **`.pbar` → Docs ▾** sits next to Open PR and shows only when a docset
  is detected.
  - With one docset, the button opens the docs in a new tab.
  - With several, it is a menu with one row per docset, like the VS Code
    table.

  Each row shows **Open**, "built 12 min ago", the warnings count (which
  links to `build.log`), a **stale** badge, and **Rebuild**.
- **Run page.** If a step's changes made the docs stale and the
  automatic build ran, add a line "Docs rebuilt after this step ·
  N warnings · Open" to the run's summary.
- **History.** A Docs tab or section lists the `builds.jsonl` rows (when,
  from which run, result, warnings, log).
- **CLI.** `wpk docs [--build] [--open] [project]` uses the same module.
  It prints the docsets, their state and the URL or path.

### 5. Tests

- Detection: a fixture tree with `docs/conf.py`, `doc/source/conf.py`, a
  decoy `conf.py` and a skipped `_build/`.
- Interpreter choice: fake interpreters on `PATH`, one without Sphinx.
- Building against a real minimal Sphinx project, if Sphinx is installed
  in the test env; otherwise skip. The checks are the
  stale → build → fresh change, the lock, and a failed build recording
  the log.
- The route: containment (`..`, symlink escape), media types, and the
  CSP header on `/docs/` only, while the rest of the board keeps the
  strict CSP.

## Steps

| # | Step | Status |
|---|------|--------|
| S1 | `docs.py`: detect, choose interpreter, fingerprint, build, records; unit tests | done |
| S2 | Static route; the route sets its own CSP (the guard keeps a CSP the app set), so `guard.py` is unchanged | done |
| S3 | `.pbar` **Docs** (opens the newest build) + **▾** menu: state, Build/Rebuild, Log, earlier builds; `docs_wait.html` while the first build runs | done |
| S4 | `executor.step` calls `docs.after_step` after each step: a detached `python -m work_packet.docs build --if-stale` | done |
| S5 | Run page line ("Docs … rebuilt after a step from this run"), `wpk docs [--build] [--force] [--open]` | done |

Tests: `tests/test_docs.py` (20). Full suite: 881 passed, 4 skipped.

### Notes from trying it on real projects

- Six registered projects have docs; detection and the staleness check
  each take under 15 ms.
- `fw-aes-demo` built with its IVPM Python in 0.7 s. `pssc/docs` built
  with 6 warnings.
- `pssc/doc-source` fails: it wants `sphinx_rtd_theme`, and only the
  board's Python has Sphinx there. The interpreter check only asks for
  `import sphinx`, so the board names the real error ("ThemeError: no
  theme named 'sphinx_rtd_theme'") instead of an exit code. The fix is on
  the project's side: install the theme in its env, or set
  `[docs] python`.

## Decisions

- **D-Q1. Which tree is "the most recent docs"?** Decided: the suggestion.
  - **(a)** While a packet has an active run, build from the run's work
    folder (`runs/<wpid>/work/<name>`), which has the agent's newest
    edits. Otherwise build from the project's work folder.
  - **(b)** Always build from the project's work folder.

  *Suggested: (a).* The docs set then gets a "from run <wpid>" label.
- **D-Q2. Build automatically when a step ends, or only when you ask?** Decided: the suggestion.
  *Suggested:* automatically when a step ends, if stale, plus a manual
  Rebuild. A build does not block the next step; it only reads the tree.
- **D-Q3. Keep older builds' HTML?** Decided: the suggestion.
  - **(a)** Keep only the newest HTML; history keeps the records and logs.
  - **(b)** Keep a snapshot per finished run, so you can compare.

  *Suggested: (a)* for v1. Snapshots can come later if they are wanted.
- **D-Q4. Sandbox the served docs?** **Decided: no.** Docs should look
  and behave exactly as built; the risk is noted in §3.
