# Marking up documents on the board

Highlight text in a rendered Markdown document on `wpk dash` and add a comment,
an insertion, a deletion or a substitution. The board writes it into the `.md`
file as CriticMarkup, so the file stays the only record: VS Code, git diff and
Claude all see the same thing, and markup typed by hand shows on the board too.

## The markup (CriticMarkup)

| What | Source | Shown as |
|---|---|---|
| comment on a point | `{>> text <<}` | a note badge |
| comment on a span | `{==span==}{>> text <<}` | highlight + note |
| insertion | `{++ text ++}` | green |
| deletion | `{-- text --}` | red, struck through |
| substitution | `{~~ old ~> new ~~}` | old struck, new green |

Ask Claude to "resolve the markup in <file>": it applies or answers each item and
removes it. On the board, each item has Accept / Reject (a comment: Remove).

## Where

- Packet files: `/p/<project>/<wpid>/file?path=state/plan.md` (report deliverables).
- Project files: `/p/<project>/doc?path=work/<repo>/docs/x.md`, any `.md` under the
  project's `work/`; a folder path lists its `.md` files and subfolders.

## How it works

- Rendering: markdown-it gets a CriticMarkup inline rule; block elements carry
  `data-src="<first line>-<last line>"` from the token map.
- A selection is sent as: the block's line range, the selected text, and which
  occurrence of that text within the block's rendered text it is. The server
  projects the block's source to "visible" characters (dropping Markdown and
  CriticMarkup syntax and link targets), finds the occurrence there and maps it
  back to source offsets. Insertion is then a plain string splice.
- Accept/reject: each rendered item carries its raw markup and its occurrence
  number among identical raw strings; the server replaces that occurrence.
- Each POST carries the sha256 of the file it was made on; a changed file gets
  409 and the popover offers a reload. Writes are atomic (temp file + rename).
- POST `/p/<project>/markup` (JSON, X-CSRF-Token header) for both views.
- "Ask Claude": a packet file queues a note to that packet; a project file opens
  Compose with the instruction filled in (`?instruction=`).

## Notes

- A project file's markup is written to your clone in `work/`; a packet works in a
  worktree of it, so commit the markup before "Ask Claude ... (new task)", or ask
  Claude in the CLI instead.
- Matching is forgiving (whitespace and Markdown punctuation are ignored, the
  occurrence nearest the selection wins). A selection across two blocks, or one
  that cuts into existing markup, is refused with a message.
- An item is found again by its raw text and its count among identical items; a
  copy of the same raw text inside a code block can throw the count off.

## Status

Done (2026-10-26): `dash/markup.py`, `dash/markup.js`, `templates/doc.html`, routes
`GET /p/<project>/doc` and `POST /p/<project>/markup` in `dash/app.py`, a Documents
link on the project page, `?instruction=` on Compose. Tests: `tests/test_markup.py`;
checked end to end in headless Chrome against `wpk dash` (CSRF path included).
