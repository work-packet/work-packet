# Writing a starter

A starter is one way to make a new packet (docs/starters-v1.md). It asks
for a few fields, and turns the answers into a *recipe*; `starters.make`
does the rest (clone, branch, the card, inputs, origin), the same for every
starter. So a new path is a small class, and it shows up in `wpk start` and
the dashboard's New task with no other change.

## The class

```python
from work_packet.starters import Field, StartError, Starter


class PlanItemStarter(Starter):
    name = "plan-item"                       # wpk start plan-item …; a tab in New task
    title = "From a plan item"
    help = "Pick an unchecked step of a plan in a repo: work on that step."
    fields = (                               # after name and dir; before objective and from
        Field("repo", "Repo", "repo", required=True,
              help="Type to search the forges, or give a path."),
        Field("plan", "Plan file", placeholder="docs/plan.md"),
        Field("step", "Step", "text", required=True, placeholder="S3"),
    )

    def search(self, key, query, values, h=None):
        """Choices for a browsing field, as you type: [{value, label, detail}]."""
        if key == "repo":
            from work_packet.starters.builtin import _repo_choices
            return _repo_choices(query, h)
        return []

    def recipe(self, values, h=None):
        """values: the fields, stripped. Raise StartError to refuse, with a reason
        the person can act on."""
        if not values["step"].startswith("S"):
            raise StartError("Step: like S3")
        r = self.base(values)                # name, dir, objective, from, model, harness, hold
        r.setdefault("name", "plan-" + values["step"].lower())
        r["clone"] = {"url": values["repo"], "branch": "wpk/" + values["step"].lower()}
        r.setdefault("objective", "Do step %s of %s, then tick it.\n" % (
            values["step"], values.get("plan") or "docs/plan.md"))
        r["origin"] = {"kind": "plan-item", "title": values["step"]}
        return r
```

- `Field` kinds: `text`, `textarea`, `repo` and `issue` (searched as you type
  through `search`), `project` (a registered project).
- `recipe` returns a dict with the keys in the recipe table of
  `docs/starters-v1.md`. What the person typed for name, dir and objective
  wins over what the starter suggests.
- `origin` is kept in `project.toml [origin]` (strings and integers only) and
  shown under the project's name; give it a `url` to make it a link.
- `inputs` (`[{name, text}]`) are put in the root packet's `state/`.
- Network calls go through `work_packet.forges` where they can (so the
  person's forges and tokens are used, and tests can fake them).

## Registering it

In the package's `pyproject.toml`:

```toml
[project.entry-points."work_packet.starters"]
plan-item = "my_package.starters:PlanItemStarter"
```

Install the package in the same environment as work-packet. A starter that
fails to load does not break the others: `wpk start` and New task say which
one failed and why.

## Trying it

```sh
wpk start                                     # is it listed, with its fields?
wpk start plan-item repo=~/src/x step=S3 --dry-run --json
wpk start plan-item repo=~/src/x --search repo   # the choices search gives
```

`--dry-run` shows the recipe and what `make` would do, and makes nothing.

## Testing it

See `tests/test_starters.py`: a fake Forgejo replaces `forges._get`, so
nothing leaves the machine. Check `from_values(...)` gives the recipe you
expect, then `make` it into `tmp_path`.

## Without a starter

A script that already knows what to make can skip the starter and write the
recipe itself: `wpk start --recipe recipe.json`, or `-` for stdin.
