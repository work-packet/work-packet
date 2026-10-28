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
- *watchers* on a board, which poll issue trackers and start a packet per
  new issue (below).

No `POST /api/new`: the board takes only same-origin browser requests with
its CSRF token, and a credential for scripts is more to guard than it is
worth. Scripts on the machine use `wpk start --recipe -`; remote ones, ssh.

### Watchers: a board polls issue trackers

A board covers a piece of work that often spans several repos, so a watcher
belongs to a board and watches any number of repos, on any forges.
`boards/<board>.toml` (`main` too: `boards/main.toml` may hold just
watchers):

```toml
[[watch]]
name = "bugs"
repos = ["home:mballance/dv-solve", "github:fvutils/*"]   # owner/*: all its repos
labels = ["wpk"]          # open issues with all of these labels
dir = "~/work"            # where the packet folders go (required)
every = "15m"             # how often to poll (default 15m)
hold = true               # held for setup (default); false: the runner starts it
from = "dv-solve-base"    # copy this project's setup (optional); model, harness too
max_new = 5               # at most this many packets per poll (default 5)
enabled = true
```

Each new issue becomes a packet made by the `issue` starter (its own repo
cloned, branch `wpk/<n>-…`, the issue as objective and input), put on the
board. The runner in the board's server polls (one per home, by its lease,
so two servers never make the same packet); `wpk watch poll` polls by hand
or from cron. What a watcher has seen is kept in
`$WPK_HOME/watch/<board>.<name>.json`; an issue already the origin of a
registered project is never made twice, even if that file is lost. A failed
issue is kept with its error and tried again next poll.

Later, *sub-boards*: a board that is a slice of another (e.g. a sub-board
per repo under an org's board), so a watcher on `github:fvutils/*` can file
each issue on its repo's sub-board. For now one watcher files on one board;
`owner/*` covers an org.

An issue whose work needs *several* of the board's repos at once needs a
packet with sibling clones: that waits for R7 (run-binding-v1.md). Until
then the packet clones the issue's repo, and the objective names the
board's other repos.

## Steps

- [x] S1. Recipe, maker, starter registry; `folder` and `clone` (path or
  URL) starters; `wpk start`; the dashboard's New task built from the
  starters; `[origin]` in `project.toml`.
- [x] S2. Forges: `[[forge]]`, GitHub and Forgejo clients; repo search in
  `clone`.
- [x] S3. `issue` starter: issue search, the objective from the issue, the
  issue and its comments as an input, the branch; origin shown on the
  dashboard.
- [x] S4. Automation: `wpk start --recipe` and entry-point starters.
- [x] S4b. Starter guide (`docs/writing-a-starter.md`). `POST /api/new`
  dropped (above).
- [x] S5. Watchers: `[[watch]]` on boards, label filter on the forges'
  issue lists, `watch.py` (poll, dedupe, make, put on the board), the
  runner polls, `wpk watch [list|poll]`, shown on the board page with
  "Poll now"; `owner/*` for all of an org's repos.
- [ ] S6 (later). Finishing back to the forge (push the branch, open a PR:
  with R8 `wpk done`); multi-repo issue packets (with R7); sub-boards
  (a watcher files each issue on its repo's sub-board).

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
- 2026-10-28: S4 and S5 built. `docs/writing-a-starter.md` (its example
  run end to end). `POST /api/new` dropped (scripts use `wpk start
  --recipe`). Watchers: `[[watch]]` in `boards/<board>.toml`
  (`schema.validate_watches`, kept apart from the board's own validation so
  a bad watcher never hides a board), `src/work_packet/watch.py` (poll with
  a lock, dedupe by state file and by registered projects' `[origin]`, new
  issues before retries, `max_new`, the packet put on the board, the board's
  other repos named in the objective), a `wpk-watch` thread in the
  in-server runner (every 60s, polls those due), `wpk watch [list|poll
  [board[/name]] [--dry-run]]`, a Watchers table on `/b/<board>` with "Poll
  now" (`POST /b/<board>/watch/<name>/poll`). Forges: `labels=` on issue
  lists, `owner_repos`. Tests in `tests/test_starters.py` (10).
