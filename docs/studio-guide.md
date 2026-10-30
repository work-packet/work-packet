# The studio: a user guide

The studio is where you work on a packet live with an agent, instead of
handing it to the runner and waiting for steps. You talk; the agent writes
files in the packet folder; what it makes shows on a **canvas** beside the
conversation, where you read it, comment on it, and pin what matters. When
you close the studio, the session is recorded as one step of the packet.

Design: `docs/interactive-tasks.md`. Build plan and status:
`docs/studio-plan.md`. This guide covers what is built (phase S1:
documents and images); later phases add charts, tables, diagrams, sketches,
decks, versions and research.

## Opening

- On the packet's task page, **Open studio**. It is offered on the root
  packet, and on a child packet that has a `work/` folder.
- On the project's Overview, **Studio** goes to the root packet's studio.
- In the console drawer, `/studio [packet]` goes to a packet's studio (the
  root packet's on a project page).
- Or from a shell: `wpk studio open <packet>` (then work in it on the
  board), `wpk studio status <packet>`.

Opening **takes** the packet (docs/interaction.md §6b): an idle packet is
paused with reason `studio` at once; a running one is taken when its step
ends (the page says "taking over after this step"). While you have it, the
runner leaves it alone and nobody else can resume it, hand it off or open
its studio. The board shows **IN STUDIO (you)** on its card and task page;
**Return to the studio** takes you back.

## Talking to the agent

Type in the conversation pane and Send (Ctrl+Enter). The agent:

- works in the packet folder, with the packet's model and step budget per
  turn, the project's tools and Bash allowlist, and write access;
- cannot change wpk's own files (`.work-packet/`), which the run's
  record lives in;
- is told, at each turn, what is on the canvas and which files *you*
  changed since its last turn (in the studio, an IDE or a shell), so it
  re-reads them before editing.

Its replies stream in, with a line for each tool call. At the end of a
turn, every document or image it made or changed gets a **card** with a
preview, **Pin** and **Open**. **Stop** ends a reply that is going the
wrong way.

## The canvas

- **Pin** a card to put the file on the canvas; each pinned file gets a
  tab. Click a tab to open it; × unpins it (the file stays).
- **Two up** shows two files side by side, for comparing.
- **Documents** (`.md`) render as on the board's doc pages, with **doc
  markup** (docs/doc-markup.md): select text to comment or suggest a change;
  click an item to accept or reject it. **Ask Claude** sends the file's
  markup to the studio's agent (not a note to a later step).
- **Images** (`.png .jpg .gif .webp .svg`) show as they are.
- When a pinned file changes, by the agent or by you anywhere, its tile
  reloads and its tab says who changed it last.

- **Tables** and **charts**: see below.

The canvas is kept between sessions: reopen the studio and it is as you
left it. Its state is in the packet folder's `.studio/` (excluded from git
where there is git).

## Data

Needs DuckDB in the studio's kernel: `pip install 'work-packet[studio]'`,
or `duckdb` in the packet's own IVPM venv (`packages/python`), which the
kernel uses when it has it.

- **Tables.** CSV, TSV, Parquet and JSON-lines files, SQLite files (`.db`,
  `.sqlite`: pick a table), and saved queries (`.sql`) show as a paged grid.
  Click a column to sort; type in a column's filter box and press Enter to
  keep the rows that contain it. **Stats** shows each column's type, nulls,
  min, max and distinct count.
- **SQL.** The **SQL** box runs one `SELECT` in DuckDB over the folder's
  files (`SELECT * FROM 'data/runs.csv'`) and `history.steps` (this
  project's steps: cost, tokens, duration, model, worker, failed). It can
  read only inside the folder and change nothing. **Save as .sql…** keeps
  the query as a file and pins it: a saved query is a table that runs again
  when its input files change.
- **The kernel.** One Python process per open studio, started on first
  use, in the folder. The agent uses it through `wpk studio query`, `wpk
  studio exec` and `wpk studio datasets` (you can too, in a shell in the
  folder). It keeps what `exec` loaded between turns; it stops when the
  studio closes, after `[studio] kernel_idle_minutes` (30) idle, or when a
  call runs over `kernel_timeout_s` (120; the next call starts a new one).
  Its log is `.studio/kernel.log`.

## Charts

- A chart is a Vega-Lite spec, `charts/<name>.vl.json`, that names its
  data by path (a table file or a `.sql`, relative to the spec). The board
  serves the rows, so the chart follows its data: change the CSV and the
  chart redraws. Specs that can't be drawn say why (a missing file, data
  outside the folder, an unknown mark).
- The studio's theme matches the board (the same series colours, light
  and dark).
- **Select** (brush a range or click a bar, where the chart has a
  selection), type a question under the chart and **Ask**: the agent gets
  the question with the selected rows, not a picture.
- **Spec** opens a small panel: mark, the x, y and colour fields (with type
  and aggregate) and the title. **Save to the spec** writes them into the
  file; anything else, edit the JSON or ask the agent.

## Closing

**Close studio…** shows a summary for the step: drafted from the
conversation and the files changed by the console's cheap model, or
from the plain facts when there is no model. Edit it, choose:

- **Hand it back to the runner**: a packet the studio paused becomes
  runnable again;
- **Keep it paused (held)**: it stays paused, reason `held`, until you
  resume it;

and **Close and record**. The session becomes one step of the packet,
marked **studio** in the Steps tab, with its transcript, cost, duration,
the files it created, changed and deleted, and your summary. A session that
neither talked nor changed anything records nothing.

From a shell: `wpk studio close <packet> [--hold] [--summary TEXT]`. The
shell's name (`you@host`) is not your board login, so closing a studio
opened on the board from a shell needs `--force`.

## Safety

- The studio's pages are on the board's origin. Anything that could run
  as a page (an HTML file, an SVG with scripts) is never served as a page
  there: raw files come back sandboxed, and HTML shows as text.
- Pages the agent makes are shown later on a separate sandboxed content
  origin (`/sc/...`, docs/server.md §6a) that cannot reach the board.
