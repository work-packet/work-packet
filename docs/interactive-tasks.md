# Studio: interactive research and visualization (proposal)

Draft 2, 2026-10-30 (with §11, the case for VS Code). Status: **for review**. Nothing here is built.

Draft 1 proposed a studio for iterating on one visual thing, such as a
slide deck. Draft 2 widens it after review: **the studio is work-packet's
tool for interactive exploration**. You research a question, look at data,
chart it, sketch a diagram, write it up as a document or a deck, and see
each piece as you work on it.

## 1. The question

So far work-packet has run code-centric batch work. A step runs for
minutes and commits, and a person reviews a diff or a report later. Much
research and communication work doesn't fit that shape:

- *"What does our regression history say about flaky tests?"* Load the
  data, try three charts, keep one, write two paragraphs.
- *"Survey the open-source RISC-V verification tools."* Collect sources,
  read, take findings, compare in a table, write a page.
- *"Make the Q4 strategy deck."* Draft, look, react, many times.
- *"Explain the AXI port's architecture."* Sketch a diagram, adjust it,
  embed it in a document.

The work differs from batch work in three ways:

| | Batch | Studio |
|---|---|---|
| **Loop** | minutes to hours per step; you come back later | seconds to a minute per turn; you stay |
| **What you review** | a diff, a report, test results | the rendered thing: the chart, slide 7, the diagram |
| **Feedback** | about the work as a whole, or a line of code | about a *place*: "this bar", "the title on 3", "these points" |

There is also a shape that batch work doesn't have: **explore, then
compose**. You try many things, keep a few, and assemble what you kept into
something for other people.

## 2. What is here today

| Piece | What it gives us | Gap |
|---|---|---|
| **Console** (`dash/console.py`, console.md) | A Claude session per scope, streamed, continued with `--resume`, slash commands through `actions.py` | Read-only tools; text only |
| **Doc markup** (`dash/markup.py`, `markup.js`, doc-markup.md) | Rendered Markdown with line-mapped blocks (`data-src`); select text to comment, insert, delete, substitute, stored as CriticMarkup in the file; "Ask Claude" | The anchoring model for documents, already built. Markdown only |
| **Shells** (`dash/shells.py`) | Server-owned ptys that outlive the socket | The pattern for long-lived render and kernel processes |
| **Web VS Code** (`dash/ide.py`, ide.md §4) | `serve-web` proxied behind wpkd under one login | The proxy pattern for previews |
| **Ownership** (ide.md §5) | One writer at a time, by packet state | A studio has two writers: you and the agent |
| **Notes** (interaction.md §6a) | A note reaches a running step after its next tool call | Text only |
| **People's sessions, the scribe** (work-data-design.md §13.4) | Work by people is recorded; the scribe drafts the step | How a studio session gets recorded |
| **Token charts** (`dash/tokens.py`) | SVG charts in the dash | Hand-rolled for cost; no general chart spec |
| **Spaces: items, series, pages** (routines-and-outputs.md) | Findings, data series and versioned pages at board and project level | Where studio work is published, and a data source for it |
| **Blob store** (`blobs.py`) | Content-addressed files | Where snapshots of sources and renders go |
| **Priority classes** (`sched/classes.py`) | Ordering of batch work | Nothing that says "a person is waiting now" |

## 3. The shape

A **studio** is an interactive session on one packet. The packet is
**taken** (yours, HELD) while the studio is open, so the runner leaves it
alone. Closing the studio hands it back or leaves it HELD.

```
┌─ sources ──────┬─ canvas ───────────────────────────────┬─ conversation ─────┐
│ 📄 dvcon-23.pdf │ ┌ chart: flaky-by-week ┐ ┌ table ────┐ │ > which tests flip │
│ 🔗 riscv-dv     │ │  ▂▃▅▇▅▃              │ │ test  n   │ │   most?            │
│ 🗃 regress.csv  │ └──────────────────────┘ └───────────┘ │ ✓ query + chart    │
│                │ ┌ doc: findings.md ─────────────────┐  │   pinned           │
│ findings (4)   │ │ ## Flaky tests are clustered …    │  │                    │
│  • 60% in uart │ └───────────────────────────────────┘  │ [ message … ]      │
├────────────────┴────────────────────────────────────────┴────────────────────┤
│  v1  v2  v3 [v4]  ·  branch: dark-theme                     ← versions       │
└──────────────────────────────────────────────────────────────────────────────┘
```

Four parts:

1. **Conversation:** a write-capable agent session (§5.1). What it makes
   appears in the conversation (a chart inline, a table) and can be pinned
   to the canvas.
2. **Canvas:** the things you're working on, each shown by a **viewer**
   for its kind (§4): a document, a deck, a chart, a table, a diagram. Open
   one full-width to work on it; tile several to compare.
3. **Sources:** what the research rests on: files, URLs, papers, datasets,
   other packets, a space's series (§6). Plus the **findings** taken so far.
4. **Versions:** every turn that changed something is a version of the
   studio (§5.4). Branches hold alternatives.

All of it is files in the packet's workspace, so the agent, the IDE, git
(where there is one), and a batch step all see the same thing.

## 4. Kinds: one model, many viewers

Every artifact in the studio has a **kind**. A kind says how its source
is stored, how it's rendered, how a comment points into it, what a version
snapshots, and what it exports to.

| Kind | Source (text, editable by the agent) | Rendered by | A comment points at | Exports |
|---|---|---|---|---|
| **Document** | Markdown (`.md`), Quarto (`.qmd`) | the dash's markdown-it, with doc markup; Quarto for executable docs | a text span: line range + occurrence (doc-markup.md) | HTML, PDF, `.docx` (pandoc) |
| **Deck** | Slidev or Marp Markdown | the tool's dev server, proxied | slide number + element + source range | PDF, `.pptx`, HTML |
| **Chart** | a Vega-Lite spec (`.vl.json`) naming a data file | Vega-Lite in the browser | a data selection (brushed points, a bar) + the mark | SVG, PNG, the spec |
| **Table** | CSV, Parquet, or a SQL query over them (`.sql`) | a grid viewer: sort, filter, column stats | cells, rows or a column | CSV, Markdown table |
| **Sketch** | Excalidraw (`.excalidraw`, JSON) | Excalidraw, embedded (§4.1) | an element by id, or a region | SVG, PNG |
| **Diagram** | Mermaid, Graphviz, D2 | in the browser (Mermaid) or by the tool | a node or edge by id | SVG, PNG |
| **Figure** | a script (`.py`) that writes an image | runs in the studio's kernel (§7.1) | a region of the image (box + crop) | PNG, SVG, PDF |
| **Page** | HTML/CSS/JS (a mock-up, an interactive explainer) | an iframe, served by wpkd | an element (CSS path) + crop | HTML, a page in a space |
| **Image** | PNG, SVG, JPEG (given, not made) | an image viewer | a region (box + crop) | as is |

Rules that make this work:

- **Text sources the agent can edit and diff.** Vega-Lite rather than a
  chart drawn in a notebook cell, Mermaid rather than a drawing tool,
  Markdown rather than `.pptx`. Binary formats are exports, never the
  source. (A `.docx` or `.pptx` brought in as input is converted to
  Markdown to work on.)
- **Built-in viewers first.** Documents, charts, tables, diagrams and
  images render in the browser with vendored libraries (markdown-it, Vega,
  Mermaid, a grid), with no toolchain in the packet. Decks, Quarto and
  figures need a tool, declared per packet (§7.1).
- **One anchor shape for every kind.** A comment is a note with `anchor
  = {artifact, kind, where}` and an optional crop image. `where` is
  kind-specific (the column above). The agent gets the anchor and the
  picture.
- **Artifacts reference each other, they don't copy.** A document or a
  slide embeds a chart by path (`![](charts/flaky-by-week.vl.json)`). The
  chart is defined once; change its data and every document and deck that
  shows it changes too. Exports render the embeds to images.
- **New kinds plug in.** A kind is a small record (file patterns, viewer,
  anchor parser, render command, exports). Waveforms (a VCD/FST viewer)
  and coverage reports are obvious DV kinds for later.

### 4.1 Sketches: Excalidraw

A crude hand-drawn sketch often gets a concept across better than a
tidy diagram. Excalidraw (MIT) is embeddable, and its file format is
JSON, so it fits the text-source rule.

**Feasibility (checked 2026-10-30).** `@excalidraw/excalidraw` 0.18.1 is
a React component (peer React 17-19) shipped as ESM with bare imports, so
it needs one bundling step: an esbuild bundle of it with React. A trial
build in the scratchpad took 0.2 s and gave about 250 KB gzipped for the
entry, with roughly 1 MB gzipped loaded on first open; fonts and the 55
locales are separate files fetched only when used (8.7 MB in total on
disk). That is fine for a dash served on a LAN.

- **Vendored, not loaded from a CDN.** The bundle and its fonts go into
  `dash/vendor/excalidraw/` (on-prem installs have no internet), built by
  a small script kept in the repo. Node is needed only to rebuild it, not
  to run wpk. `EXCALIDRAW_ASSET_PATH` points the fonts at our copy.
- **Its own page in an iframe** (`/p/<p>/sketch?path=…`), so React and
  its CSS stay out of the rest of the dash. The canvas shows the iframe;
  the rest of the dash stays plain JS.
- **Saving.** The page saves to the `.excalidraw` file on change
  (debounced), with the file's hash as in doc markup; a changed file gets
  409. When the agent changes the file, the page reloads the scene, and
  Excalidraw's per-element `version` lets the two sides' edits be merged
  rather than one overwriting the other.
- **Comments.** Excalidraw reports the selected element ids, so a comment
  pins to elements (and their text labels); a box drawn over empty space
  pins to a region.
- **The agent drawing.** Raw Excalidraw JSON is verbose (seeds,
  versions, coordinates). The agent instead writes either
  - Mermaid, converted by `@excalidraw/mermaid-to-excalidraw`, which gives
    a sketch-style flowchart you then rearrange by hand; or
  - a short "skeleton" (boxes, labels and arrows that name what they
    connect), turned into full elements by Excalidraw's
    `convertToExcalidrawElements`.

  Editing an existing sketch ("move the cache box under the bus", "add a
  DMA block") is an edit to elements by id and label, which the agent can
  do in the JSON.
- **Seeing it.** `exportToSvg` renders a sketch in the headless browser
  the studio already uses for renders (§5.3), for thumbnails, embeds in documents and decks, and
  the agent's own look at what it drew.
- **Embedding.** A document or slide embeds `sketches/arch.excalidraw` by
  path, like a chart; exports render it to SVG.
- **Outside the studio.** VS Code's Excalidraw extension opens the same
  `.excalidraw` files, so a sketch can be edited in either place.
- **Pen and touch.** Excalidraw works with a tablet and stylus, which suits
  sketching better than a mouse; the phone layout can allow sketching for
  this kind.
- **Not needed:** Excalidraw's live collaboration (it needs its own room
  server). Saving to the file and reloading on change covers one person and
  the agent.

Cost: about 2-3 days for the embed, save and reload, thumbnails and
embedding; 2-3 more for the agent paths (Mermaid conversion, skeletons)
and element comments. It fits S4 in the plan, beside Mermaid diagrams.

## 5. Working in the studio

### 5.1 The session

- **Open studio** on the packet page, or `/studio` in the packet's
  console. Uses the console's session code (`--resume`, a WebSocket
  stream, survives a closed tab), with write tools (Edit, Write, Bash
  under the packet's allowlist, web search and fetch where the packet
  allows) and the packet's harness settings.
- The primer: the packet's brief and `state/` outline, the canvas (each
  artifact's kind, path and a thumbnail), the sources and findings, and
  the files you changed since the agent's last turn (§5.5).
- **Output in the conversation.** When the agent makes or changes an
  artifact, the turn shows it rendered, with **Pin** (put it on the
  canvas) and **Open**. A quick query's answer is a table in the
  conversation, not a file, until you pin it. This is the notebook feel,
  without notebook files.
- **Recording.** One studio session is one step with `worker: studio`,
  built like the scribe's step for people's work: transcript, cost,
  timing, the versions made, the comments sent, and a summary the scribe
  drafts at close and you accept or edit. The Steps tab shows "studio,
  40 min, $1.10, 9 versions, 3 findings".

### 5.2 Comments pinned to the work

- On any viewer: select text, click a slide element, brush points on a
  chart, select rows, click a node, or drag a box. Type, send.
- Documents keep using doc markup: the comment is written into the `.md`
  as CriticMarkup, and the agent resolves it. Other kinds store the
  comment beside the artifact (`.studio/comments.jsonl`) with its anchor
  and crop.
- In a studio, a comment goes straight into the conversation. On a packet
  that isn't in a studio, it's a note to the next step (`notes.py`, with
  new `anchor` and `image` fields).
- Open comments show as pins on their artifact; "addressed in v6" when the
  agent says so.

### 5.3 The agent sees what it made

- Every render is also captured as images (headless browser for HTML,
  Vega and Mermaid; `pdftoppm` for PDF): one small PNG per slide, page,
  chart or diagram.
- Before handing a turn back, the agent looks at what it changed and
  checks for the usual faults: text overflowing its box, clipped or
  overlapping labels, unreadable contrast, an empty slide, a chart whose
  axis hides the effect, colours that don't follow the palette.
- Cheap checks without a model run first and are flagged on the
  thumbnail: overflow in the browser (scroll size bigger than the box),
  Vega warnings, broken embeds, missing citations (§6.3).
- The same images serve as version thumbnails and comment crops: one
  renderer.

### 5.4 Versions and branches

- A **version** is a snapshot of the studio's changed files and their
  renders, taken at the end of each turn that changed something
  (`.work-packet/runs/<id>/studio/vNNNN/`, images in the blob store). A
  version is not a git commit; packets need not be git repos. Where there
  is git, "keep" can also commit.
- The strip: click to view; compare two side by side; **flip** in place
  (best for small changes); **Restore** (as a new version); **Keep** marks
  the ones worth showing first.
- **Branches** for alternatives: "try it as a heatmap", "a dark theme". A
  branch starts from a version and gets its own line in the strip; compare
  across branches; **Adopt** one, and the others stay, greyed. Branches
  are cheap because a version is files plus pictures. (roadmap.md Phase 4
  wanted snapshots and branching; this is where users first meet them.)
- **Several agents at once.** "Try three chart forms" can run three
  branches in parallel (the agent's own sub-agents, as steps may already
  use), and the canvas shows the three side by side.

### 5.5 You and the agent editing the same files

- The packet is HELD by you, so the IDE is writable while the studio is
  open. The canvas's editors (a document's markup, a table's cells, a
  chart's spec panel) are writable too.
- Before each turn the agent is told which files you changed since its
  last edit ("you changed `findings.md` lines 40-52"), and it re-reads
  them. The studio keeps a hash per file at the end of each turn.
- If you save while the agent edits the same file, the agent's edit fails
  on stale content and it re-reads. No locking.
- Direct manipulation where it is cheap and exact: drag a chart's colour
  legend, rename an axis, reorder slides in the strip, edit a table cell.
  Each is a small edit to the source file, shown to the agent as a change
  by you.

### 5.6 Speed

- **Model per turn.** A fast model for tweaks ("larger title", "log
  scale"); the packet's strong model for analysis and restructuring. A
  selector, plus `/model`. Default: fast, with **Think harder** on demand.
- **No model when none is needed.** Direct manipulation (§5.5), a query
  you type in the table viewer, and switching a chart's mark in its spec
  panel cost nothing.
- **Hot rendering.** Built-in viewers re-render on file change in
  milliseconds; tool-based kinds prefer a dev server (`run`) over a full
  build; a slow build is queued (only the newest runs) and the last good
  render stays up meanwhile.
- **Scheduling.** An `interactive` priority class above every batch class
  in `sched/classes.py`: a studio turn takes the next free slot first, and
  an idle studio (no turn in 10 minutes) gives its slot back.
- **Cost.** The studio shows its running cost; the packet's budget
  applies.

## 6. Research

### 6.1 Sources

The sources pane lists what the work rests on. A source is a record in
`.studio/sources.jsonl`:

| Source | Captured as |
|---|---|
| A URL | the fetched page as text and a snapshot (blob store), the time fetched |
| A paper or PDF | the file (blob store), its text extracted, title/authors/year |
| A file in the workspace or another packet | a path, with the content hash it was read at |
| A dataset | a path, schema and row count (§7) |
| A space's series or items (routines-and-outputs.md) | the address and the range read |
| A person ("Matt said, 2026-10-30") | the note |

- **The agent's reading is recorded.** Every web fetch, search and file
  read the agent does in a studio adds (or updates) a source, so "where
  did that come from?" always has an answer, even after the page changes.
- **Reading view.** Open a source to read it in the studio: highlight a
  passage to quote it into a document (with its citation), to comment, or
  to make a finding.
- Sources can be **shared across packets** on a board: a board-level
  library in the board's space, so a survey's sources are there for the
  next one.

### 6.2 Findings

A **finding** is a short claim with its evidence: "60% of flaky failures
are in the UART block (regress.csv, weeks 30-42; chart flaky-by-block)."

- Made by the agent or by you, from a passage, a chart selection or a
  query result. It links to its sources and to the artifacts that show it.
- Kept in `.studio/findings.jsonl`, listed in the sources pane.
- **Published as items** to a space (routines-and-outputs.md §5.2): a
  finding is social.md's unit of knowledge, and a studio is where most of
  them will be made.
- Findings are the bridge from exploring to composing (§8): a document's
  outline is often "these five findings, in this order".

### 6.3 Citations

- In documents and decks, a citation is `[@key]` (pandoc style), keyed to
  a source. The viewer shows it as a link to the source; exports render a
  reference list.
- A cheap check flags claims with numbers and no citation, and citations
  to sources that no longer resolve.

### 6.4 Questions log

Research raises questions faster than it answers them. The studio keeps
open questions (`.studio/questions.md`): asked by you or the agent,
answered with a link to the finding or source. Questions still open at
close go into the packet's report as open items.

## 7. Data

### 7.1 Datasets and the kernel

- A **dataset** is a file in the workspace (CSV, Parquet, JSON lines,
  SQLite) or a source that reads one (a space's series, a run's history
  in `history.db`, an API the packet may call).
- The studio has a **kernel**: one long-lived Python process per studio
  (like a shell, server-owned, restarted on demand) with DuckDB, pandas
  and the packet's own environment. Figures (§4) and the agent's analysis
  run there, so a loaded dataset stays loaded between turns.
- **Queries are SQL in DuckDB** over the files, typed in the table viewer
  or written by the agent as `.sql` files. A saved query is a table
  artifact: re-run when its inputs change.
- A packet declares extra tools it needs (Slidev, Quarto, R) in
  `[studio]` in `project.toml`; the kernel runs in the packet's IVPM
  environment, so it has what the packet's work has.

### 7.2 Charts

- **Vega-Lite is the chart format.** It's declarative JSON the agent can
  write and edit precisely, renders in the browser with tooltips,
  selection and zoom, and exports SVG/PNG. The spec names a data file or
  a query, not inline data, so a chart follows its data.
- **A spec panel** beside the chart: mark, encodings, scales, title,
  editable directly (§5.5).
- **The palette and rules** from the dataviz guidance and the dash's
  tokens (stats-spend.md: bars over pies, labelled values) are the
  studio's defaults, in light and dark. The agent is told them in the
  primer.
- **Selections are anchors.** Brush points or click a bar and comment:
  the agent gets the selected rows, not just a picture. "Why are these
  three weeks high?" becomes a query over exactly those rows.
- Matplotlib/plotly scripts remain as the **figure** kind for what
  Vega-Lite can't draw.

### 7.3 Live data

A chart over a space's series (routines-and-outputs.md §5.3) stays live:
open it next quarter and it shows the new points. Publishing it (§9) puts
the same spec on the board's page, so a studio is also where a board's
standing charts are designed.

## 8. From exploring to composing

The studio's canvas is a working table: many things tried, a few kept.
Composing turns the kept things into something for other people.

- **Pin, then arrange.** Pinned artifacts and findings are the material.
  "Outline a document from these" or "make a 10-slide deck from these" is a
  turn like any other, and the result embeds the pinned charts and
  diagrams by reference (§4).
- **One source, many outputs.** The same findings and charts can make a
  2-page document, a 6-slide deck and a board page. A chart fixed once is
  fixed in all three.
- **Batch hand-off.** Settle the style on three slides or one section in
  the studio, then "do the other 25 like these" as a batch step: hand off
  with that brief. The step gets the studio's summary and the current
  thumbnails as reference. When it finishes, its `ask:` links straight
  back into the studio to review.
- **Templates and house style.** A packet or board names a template (a
  deck theme, a document style, a chart palette, a brand guide); new
  artifacts start from it, and its rules go into the primer ("titles in
  sentence case; at most 6 bullets").
- **Assets** dragged into the conversation or the canvas go into the
  workspace under `assets/` and the blob store, and the agent is told.

## 9. Finishing and publishing

- **Export** any artifact to its formats (§4). Documents and decks via
  pandoc, the deck tool, or Quarto; embeds rendered to images.
- **Deliverables:** at done, the kept artifacts and their exports are the
  packet's deliverables, as today, with their render images.
- **Publish to a space** (routines-and-outputs.md): a document or deck as
  a versioned **page**, a chart as a pinned **tile** over a series,
  findings as **items**. A routine can re-run a studio's composition every
  quarter (the strategy deck), with the studio as where its look was
  designed.
- **Reviewing on a phone.** The canvas, versions and comments work on a
  narrow screen (one artifact at a time, tap to pin a comment). Editing
  stays a desk job.

## 10. Plan

Each step is useful by itself. S1–S3 make a usable studio for documents
and charts; decks and research follow.

| Step | What | Builds on |
|---|---|---|
| **S1** | Studio view: take the packet, a write-capable session, the canvas with document (doc markup) and image viewers, pin from the conversation; recorded as a `worker: studio` step with a scribe summary | console session, doc markup, take/hand-off, scribe |
| **S2** | Data: the kernel (DuckDB, pandas), datasets, the table viewer with SQL, Vega-Lite charts with a spec panel and selections as anchors | shells (process model), vendored Vega |
| **S3** | Renders to images; versions with thumbnails, compare, flip, restore, keep; the agent checks its render; cheap checks | blob store, headless browser |
| **S4** | Comments on every kind (anchors + crops); diagrams (Mermaid, Graphviz); Excalidraw sketches (§4.1); embeds by reference across documents | S1–S3 |
| **S5** | Research: sources pane, recording the agent's reading, reading view with quote-to-document, findings, citations, questions log | blob store, web fetch |
| **S6** | Decks and tool-based kinds: `[studio]` tools, dev-server proxy, Slidev/Marp, Quarto, figure scripts; templates and assets | IDE proxy, IVPM environment |
| **S7** | Branches (incl. parallel variants), shared-edit notices, direct manipulation, model per turn, `interactive` priority class | ide.md §5, `sched/classes.py` |
| **S8** | Export (pandoc, deck tools), publish to spaces (pages, tiles, items), phone layout, board-level source library | routines-and-outputs.md R1 |

Worked examples to build against, one per kind of work:

1. **Data:** flaky-test analysis over `history.db` and a regression CSV:
   three charts, two kept, a one-page findings document.
2. **Research:** a survey of open-source RISC-V verification tools: 15
   sources, a comparison table, a page with citations.
3. **Presentation:** the Q4 strategy deck from findings and two charts,
   finished as a PDF in a board's space.

## 11. Why the board, and not VS Code?

The contrary position: this belongs in VS Code. It deserves a fair
hearing, because much of it exists there already.

**What VS Code already has.** Markdown preview; Jupyter notebooks with
charts inline (data exploration, largely solved); Mermaid, Vega, CSV and
PDF viewers as extensions; Data Wrangler for tables; Slidev and Quarto
extensions with live preview; Claude Code in the editor with write tools
and diffs; git, search, multi-file editing. And we already serve web VS
Code behind wpkd (ide.md §4). The studio's S1–S2 would be mostly done on
day one, and it's the environment developers already live in.

**Where it limits us.** The parts that make the studio more than an editor
are the parts VS Code can't easily give:

| Studio needs | In VS Code |
|---|---|
| Comments pinned to a chart selection, a slide element, a diagram node (§5.2) | Each kind's preview belongs to a different extension, in a sandboxed webview we can't reach into. Anchoring across kinds means writing our own custom editor for every kind: building the studio anyway, inside VS Code's webview limits |
| A canvas mixing kinds, tiled and compared (§3) | Editor groups of separate tabs; webviews can't talk to each other or share a selection |
| Visual versions and branches: thumbnails, flip, compare across branches (§5.4) | The timeline and diff are text, per file |
| Output inline in the conversation, pinned onward (§5.1) | Claude Code's panel shows text and diffs; Jupyter shows outputs, but only in a notebook |
| Sources, findings, citations, questions as records (§6) | Not VS Code concepts; an extension's tree view at best |
| Publishing to spaces; one history with batch work (§9) | The board's concepts; VS Code only links to them |
| Review by someone who isn't a developer, or on a phone (§9) | An IDE is the wrong tool for a manager reviewing a deck; web VS Code on a phone is poor |
| Cost, sessions and versions recorded in the packet (§5.1) | Possible from an extension, but we'd be re-implementing the console's session handling in a second place |

The pattern: VS Code is excellent at **editing sources** and weak at
**looking at results together, pointing at them, and keeping what you
learned**. The studio's value is mostly the second.

**Proposal: web-first studio, VS Code as the source editor.**

- The studio is a board page. That is where you look, compare, comment,
  compose and publish.
- **Open in VS Code** stays one click from any artifact, on the same
  workspace (ide.md §2). Hand-editing a long document or a query is often
  better there. The studio sees your edits as "changed by you" (§5.5), so
  the two coexist on the same files.
- **The studio inside VS Code**, for those who live there: the planned
  extension (ide.md I4) opens `/p/<p>/studio` in a webview panel beside the
  editor. One studio, written once for the web, hosted in both places. We
  don't build against VS Code's editor APIs.
- **Don't reinvent what VS Code does well.** No code editor in the studio
  beyond small spec and cell edits; no git UI; no file tree beyond the
  canvas and sources.
- **Jupyter as an import.** People with notebooks keep them; a notebook's
  outputs can be pinned to the canvas as images and its data as datasets.

**Testing it cheaply.** Before S1, do worked example 1 (flaky-test
analysis) in web VS Code with Jupyter and Claude Code, and write down where
it hurts. If the list is short, the studio should be smaller than this
doc, and the extension route deserves more weight.

## 12. Decisions for you

1. **Studio is one tool for all kinds**, with viewers per kind, rather than
   separate "deck studio", "data studio" tools. Recommended: one tool, so
   charts, findings and documents can be mixed on one canvas.
2. **Text sources only** (Vega-Lite, Mermaid, Markdown); binary formats are
   imports and exports. Recommended, because the agent edits and diffs
   them reliably and versions stay small.
3. **Vega-Lite as the chart format**, with matplotlib/plotly scripts as
   the fallback "figure" kind.
4. **DuckDB + pandas in a per-studio Python kernel**, rather than Jupyter
   notebooks. Recommended: the conversation is the notebook, and `.ipynb`
   files are hard for the agent to edit and diff. Jupyter files could be an
   import kind later.
5. **One step per studio session**, with versions inside it.
6. **The studio takes the packet** (HELD by you), so ownership rules stay
   as they are.
7. **Decks: Slidev first**, Marp as the simple fallback.

## 13. Open questions

- **Studio without a packet?** A quick exploration ("chart this CSV")
  shouldn't need a packet made first. Proposal: **New studio** makes a
  scratch packet on the board (a starter), so everything is still
  recorded; it can be renamed or deleted after.
- **Kernel isolation.** The kernel runs code the agent writes. It runs as
  the user, in the packet's folder, under the packet's Bash allowlist
  rules? Or in a sandbox? Same question as for steps; follow whatever steps
  do.
- **Large data.** Datasets of GBs: DuckDB handles them, but the browser
  can't. Charts over large data aggregate in the kernel and ship only
  what's drawn; the table viewer pages.
- **Several people.** One drives, others comment: fits the comment model;
  who holds the take is the open part.
- **Remote hosts.** A packet on a farm node has its files there. Server-side
  studio only at first; most exploration doesn't need a farm.
- **DV kinds.** Waveforms (VCD/FST), coverage reports and logs as viewers
  with anchors (a signal at a time, a cover point, a log line). These would
  make the studio a debug tool as well, and the kind model is meant to
  allow them.
