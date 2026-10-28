# Starters: ways to make a new packet (plan and status)

Started 2026-10-28. Follows `docs/run-binding-v1.md`: a new packet is a
folder (usually a clone) with `.work-packet/` and a card at its top. This
plan adds an extensible way to *start* one: from a folder, a repo URL, a repo
picked on a forge, an issue, and more over time, by hand or by automation.

## Why

Making a packet is mostly the same few moves in different orders: get a
folder (clone something), maybe make a branch, write the objective, put some
inputs in `state/`, remember where it came from. Each new path (an issue, a
PR review, a failing CI run, a plan item) should be a small piece of code
that *decides* those moves, not new plumbing that *does* them.

## Design

Three parts, each replaceable on its own:

### Recipe: what to make

A plain dict (JSON-able, so scripts can write one):

| key | meaning |
|---|---|
| `name` | project name |
| `dir` | parent directory; the packet folder is `<dir>/<name>` (or `folder`, explicit) |
| `clone` | `{url, ref?, branch?, share?[]}`: clone `url` as the folder, check out `ref`, make and switch to `branch` |
| `objective` | the first instruction (`prompt.md`); none: held for setup |
| `inputs` | `[{name, text}]`: files put in the root's `state/` |
| `origin` | `{kind, url, title, ...}`: where it came from, kept in `project.toml [origin]` and shown on the dashboard |
| `model`, `harness`, `extra` | as `wpk new` |
| `hold` | true: held for setup even with an objective (look first, then hand off) |

### Maker: one way to carry a recipe out

`starters.make(recipe)`: check the name and folder first (nothing made on a
refusal), clone, check out, branch, `project.new(packet=True)`, inputs,
origin. If anything fails after the clone, the clone it made is removed.
`starters.preview(recipe)` says what `make` would do, without doing it.

### Starters: ways to fill a recipe

A starter has a `name`, a `title`, a list of `fields` (each with a kind:
`text`, `textarea`, `repo`, `issue`, `project`, …) and `recipe(values)`. Fields
of a browsing kind are filled by `search(field, query, values)` (a list of
choices), which the dashboard calls as you type.

Built in: `folder` (a plain or existing folder), `clone` (a repo path, URL,
or a repo picked on a forge), `issue` (an issue on a forge: clone its repo,
branch `wpk/<n>-<slug>`, the issue as objective and input). More come from
Python entry points (group `work_packet.starters`), so a new path is a
package, not an edit here.

### Forges: where repos and issues come from

`config.toml`:

```toml
[[forge]]
name = "home"                 # how it is shown and named in recipes
kind = "forgejo"              # forgejo | github
url = "https://a9550.perch-char.ts.net"
token_env = "FORGEJO_PAT"     # the token is read from the environment, never stored

[[forge]]
name = "github"
kind = "github"               # token: token_env, else GITHUB_TOKEN, else `gh auth token`
```

With no `[[forge]]`, GitHub is offered when a token is found. A forge lists
and searches repos and issues, reads an issue with its comments, and gives
a repo's clone URL. Tests use a fake forge.

### Automation

The same recipe from anywhere:

- `wpk start <starter> key=value… [--dry-run]`: fills a starter's fields from
  the command line, prints the recipe, makes it.
- `wpk start --recipe file.json` (or `-` for stdin): a recipe written by a
  script.
- the dashboard: New task picks a starter and fills its fields (with
  browsing), shows the preview, makes it.
- later: `POST /api/new` with a recipe; and *feeds*, which watch a source
  (issues with a label, failing CI) and start a packet per new item.

## Steps

- [x] S1. Recipe, maker, starter registry; `folder` and `clone` (path or
  URL) starters; `wpk start`; the dashboard's New task built from the
  starters; `[origin]` in `project.toml`.
- [x] S2. Forges: `[[forge]]`, GitHub and Forgejo clients; repo search in
  `clone`.
- [x] S3. `issue` starter: issue search, the objective from the issue, the
  issue and its comments as an input, the branch; origin shown on the
  dashboard.
- [~] S4. Automation: `wpk start --recipe` and entry-point starters done;
  `POST /api/new` and a guide for writing a starter to do.
- [ ] S5 (later). Feeds; finishing back to the forge (push the branch,
  open a PR: with R8 `wpk done`).

## Status

- 2026-10-28: plan written.
- 2026-10-28: S1–S3 built. `src/work_packet/starters/` (recipe, `check`,
  `preview`, `make`, registry; built-ins in `builtin.py`),
  `src/work_packet/forges.py` (GitHub, Forgejo), `wpk start`, the
  dashboard's New task (a tab per starter, search as you type via
  `/new/search`, a preview with the objective editable, then Create; held for
  setup unless "hand it to the runner" is ticked), `[origin]` shown under
  the project's name. `tests/test_starters.py` uses a fake Forgejo. Tried
  live (dry run) on GitHub: `wpk start issue repo=github:fvutils/pyvsc
  issue=280 --dry-run`. Suite 791 passed. The home Forgejo needs a
  `[[forge]]` entry in `~/.work-packet/config.toml` (not added).
