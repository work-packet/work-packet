# Site packages: extending wpk for a site

A *site package* is an ordinary Python distribution that a site (a company,
a lab, a cluster) installs next to `wpk` to fit it to local systems: an
LLM gateway, a budget portal, a batch farm, a login flow. It plugs in
through entry points; nothing in `wpk` itself is patched. This guide lists
each extension point, its API, and how a site turns things on and off.

Every plugin call is guarded: a plugin that fails to import or raises is
reported (in `wpk doctor`, in the step's `meta.json`, or in its dash panel)
and never fails a step or breaks a page.

## 1. Entry-point groups

The groups are `work_packet.plugins.GROUPS`:

| Group | What it adds | Doc |
|---|---|---|
| `work_packet.harnesses` | a harness adapter (a `Harness` subclass) | harness.md §7 "Writing a harness" |
| `work_packet.starters` | a New-task starter | writing-a-starter.md |
| `work_packet.cli` | a `wpk <group> <cmd>` command group | §1.1 |
| `work_packet.credentials` | a credential kind (renew command) | §1.2 |
| `work_packet.step_hooks` | code around each harness run | §1.3 |
| `work_packet.cost` | a cost source for a step | §1.4 |
| `work_packet.budget` | a budget provider for wpkd | §1.5 |
| `work_packet.dash` | board panels and `/x/<name>/` routes | §1.6 |
| `work_packet.sched_backends` | a batch backend | scheduler.md §10 |

An entry point's value may be a class (made once, with no arguments) or an
instance. Names must not clash with built-ins (a harness called `claude`, a
backend called `lsf`, a command group called `check`); a clash is refused
and shown in `wpk doctor`.

### 1.1 Command groups (`work_packet.cli`)

```python
class Gateway:
    name = "gateway"                # default: the entry-point name
    help = "the site LLM gateway"
    def add_commands(self, parser):  # an argparse sub-parsers holder
        p = parser.add_parser("login", help="sign in")
        p.set_defaults(run=login)

def login(args, h):                  # h = the wpk home; None -> exit 0
    ...
```

`wpk gateway login` runs `login(args, h)`. A group with no command prints
its help (rc 2). Plugin groups get their own heading in `wpk --help`.

### 1.2 Credentials (`work_packet.credentials`)

The store, `work_packet.credentials`, keeps one JSON file per credential in
`$WPK_HOME/credentials/` (directory 0700, files 0600; a loose mode makes it
`invalid`):

- `put(name, data, subject=None, expires=None)`, `get(name)` -> `Credential`
- `check(name)` -> `(status, note)`; `status(name)`: `ok`, `expired`,
  `missing`, `invalid`
- `mark(name, "expired"|"invalid"|"ok", note)`: a plugin that saw the
  credential refused says so, until the next `put`

A credential-kind plugin names what to run to renew it:

```python
class GatewayToken:
    names = ["gateway"]              # credentials it covers (default: its name)
    renew = "wpk gateway login"
```

wpkd polls the directory (mtime) each pass and calls
`credentials_changed(names, h)` on any loaded plugin of any group that has
it, filtered by that plugin's `credentials` list (absent = all), so a new
login is picked up without a restart. `wpk doctor` and `/sched` show a row
per credential (owner-only, never the data) with the renew command when it
is not `ok`. Checking `subject` against the home's owner is the plugin's job.

### 1.3 Step hooks (`work_packet.step_hooks`)

```python
class Proxy:
    def start(self, ctx): ...        # before the run; may change ctx.env
    def finish(self, ctx, res): ...  # after each run; a dict -> meta.json ext[name]
    def stop(self, ctx): ...         # always, once, after the last run
```

`ctx` (`work_packet.hooks.StepContext`) has `step_dir`, `wpid`, `step`,
`attempt`, `harness`, `model`, `env` (mutable). A nudged step runs twice:
`finish` is called after each run. A hook that raises gets
`ext[name] = {"error": ...}` and is not called again, except `stop`.

### 1.4 Cost sources (`work_packet.cost`)

```python
def cost(meta, step_dir):            # None | a number | {usd, basis?, source?}
    ...
```

Called after the hooks' `finish`, so it may read `meta["ext"]` (a gateway's
own bill for the step, say). The first answer wins and sets
`meta["cost"] = {usd, basis, source, harness_usd}`; with none, the cost is
the harness's figure, or priced from the profile's `price` table. `wpk
stats --by basis` and the dash mark totals that mix bases with `*`.

### 1.5 Budget providers (`work_packet.budget`)

```python
from work_packet.sched.budget import BudgetProvider, BudgetReading, NeedsLogin, Unavailable

class Portal(BudgetProvider):
    credential = "gateway"           # for the renew command on NeedsLogin
    def changed(self): return True   # cheap; polled every 5 min
    def read(self):                  # BudgetReading, or raise NeedsLogin / Unavailable
        return BudgetReading(amount=500, spent=120.5, period_start=..., period_end=...,
                             tz="America/Los_Angeles", as_of=..., stage="25%",
                             blocked=False, url="https://portal/...", notes=[])
```

Turn it on in config:

```toml
[sched.budget]
measure = "provider"
provider = "portal"
route = "key@gateway.example.com"  # glob on a step's account@host
stale_after = "6h"
```

wpkd reads when `changed()` says so, after an error, or hourly, and caches
the reading in `<home>/sched/budget-reading.json`. Spent = the reading's
`spent` plus local cost of matching steps started after `as_of`. A
`blocked` reading holds every class; a stale one (error, older than
`stale_after`, past its period) lets only high and urgent work through.
`/sched` shows the reading and, on NeedsLogin, the renew command. The read
runs in the wpkd loop, so a slow portal delays a pass: keep `read()` fast
and give it a timeout. Several homes using one portal each poll and cache
it on their own (there is no shared lock).

### 1.6 Dash panels and routes (`work_packet.dash`)

```python
class Board:
    public = False                   # default: only the home's owner sees it
    templates = "/path/or/jinja-loader"   # default: <package>/templates
    def panels(self, slot, ctx):     # slot: overview | sched | settings
        if slot == "sched":
            return ("Gateway", "gateway_panel.html", {"left": 12.5})
    def routes(self):                # Starlette routes, served at /x/<name>/
        return [Route("/", page)]
```

`panels` returns `(title, template, data)`, a list of them, or None. `ctx`
has `home`, `request`, `principal` and, on `settings`, `project`. The
board's templates come after the plugin's, so a panel may extend
`base.html` or import board macros. Everything sits behind the board's
Guard (Host check, CSRF on POST); the CSP is unchanged, so panels carry no
scripts. A failing panel shows its error in place. Panels are not shown on
the empty-home welcome page.

## 2. Turning plugins on and off

```toml
[plugins]
enable = ["acme-wpk"]            # only these (entry-point or distribution names)
disable = ["acme-wpk-budget"]    # never these; disable wins

[plugins.gateway]                # the plugin's own table: plugins.table("gateway")
url = "https://gateway.example.com"
```

One distribution name covers every entry point of that package. A disabled
plugin is listed in `wpk doctor` but not imported. `wpk doctor` shows one
row per plugin (ok, disabled, or the load error).

## 3. The site config layer

A site config is read under each home's `config.toml`:
`$WPK_SITE_CONFIG` if set (set but empty = none), else
`/etc/wpk/config.toml`. Tables merge key by key; the user's file wins,
except for keys the site locks:

```toml
[site]
locked = ["sched.backend", "harnesses.claude.env.ANTHROPIC_BASE_URL"]

[harnesses.claude]
env = { ANTHROPIC_BASE_URL = "https://gateway.example.com" }
env_file = "~/.wpk-gateway.env"   # KEY=VALUE; refused unless 0600

[sched]
backend = "lsf"
```

A locked key is forced to the site's value; `wpk doctor` names the site
file and warns about each user override it ignored. Per-home harness
environment (`[harnesses.<name>] env` / `env_file`) is in harness.md §3;
the step's route (`account@host`, never the key) goes into `meta.json`
and `wpk stats --by route`.

## 4. Job sizes

A size in `[sched.sizes.<name>]` (scheduler.md §5.2) may carry, beyond
cores and memory:

| Key | Meaning |
|---|---|
| `resources` | LSF `-R` text, merged with wpk's own (select and-ed, rusage joined, span replaced) |
| `constraint` | SLURM `--constraint` |
| `env` | shell lines run on the node before `wpk step` (SLURM node script; not used by LSF yet) |
| `label`, `description` | shown in pickers and the step prompt's size list |

```toml
[sched.sizes.xl]
cores = 16
mem = "64G"
resources = "select[type==X86_64] rusage[tmp=20000]"
env = "module load questa/2026.2"
label = "X-large"
description = "full-chip sims"
```

## 5. An example site package

```toml
# pyproject.toml of acme-wpk
[project]
name = "acme-wpk"
dependencies = ["work-packet"]

[project.entry-points."work_packet.cli"]
gateway = "acme_wpk.cli:Gateway"

[project.entry-points."work_packet.credentials"]
gateway = "acme_wpk.creds:GatewayToken"

[project.entry-points."work_packet.step_hooks"]
gateway = "acme_wpk.hooks:Proxy"

[project.entry-points."work_packet.cost"]
gateway = "acme_wpk.cost:cost"

[project.entry-points."work_packet.budget"]
portal = "acme_wpk.budget:Portal"

[project.entry-points."work_packet.dash"]
acme = "acme_wpk.dash:Board"

[project.entry-points."work_packet.sched_backends"]
farm = "acme_wpk.farm:Farm"

[project.entry-points."work_packet.harnesses"]
acme-agent = "acme_wpk.agent:AcmeAgent"
```

Install it into the same environment as `wpk`, then run `wpk doctor`: each
plugin should show as loaded.
