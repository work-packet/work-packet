# Harnesses, model profiles and step statistics

Status: H1–H4 done; H5 (Codex) and H6 (OpenCode) need live probes. This file holds the plan and a status log, so a
fresh session can pick up from it alone. Builds on `context.md` (C1–C4).

## 1. Goal

Run steps under Claude Code, Codex or OpenCode, and with any model they
support, without changing the packet format. What differs between them is
kept in two places:

- a **harness adapter** (code): how to start a step, read its result, and
  which features it has;
- a **profile** (data): per harness and model, the wording that sizes a step
  and the numbers (context limit, carry factor, prices).

The engine then records statistics per harness, model and profile, and
**advises** profile changes ("this model stops early"). It does not change
prompts on its own; it may tune `carry_factor` within limits, since that can
be checked from cost data.

## 2. What is already harness-neutral

To wpk a step is a process: given a prompt, it works in the packet and
leaves `.pending/memento.md`, `summary.md` and `state/`. The journal, the
commit, `resume:`, spawning and the state files do not care which agent
ran. Because the packet always has enough to start fresh, carry-over and
step size can be tuned safely.

## 3. Harness adapters (H1)

`work_packet/harness/`, one module per harness:

```python
class Harness:
    name: str                       # "claude", "codex", "opencode"
    caps: Caps                      # what it can do, below
    def command(self, step: StepSpec) -> list[str]: ...
    def env(self, step: StepSpec) -> dict: ...         # extra environment
    def parse(self, transcript_path, res: StepResult) -> StepResult: ...
```

`StepSpec` holds what the executor knows: model, session id, permission
mode, allowed tools, budget, extra dirs, system text file, context limit,
hook marker, session to resume.

| Capability | Meaning | When missing |
|---|---|---|
| `system_slot` | fixed text can go in the system prompt | the protocol goes at the top of the step prompt |
| `inject` | a message can be added mid-step (C3) | no soft limit; budget and timeout only |
| `resume` | a session can be resumed by id (C4) | no carry-over |
| `fork` | resume under a new id | resume in place; the packet still holds the history |
| `set_session_id` | the id can be chosen up front | read it from the output |
| `reports_cost` | the output has a USD cost | wpk prices tokens from the profile |
| `cost_is_chain_total` | a resumed run reports the whole chain | wpk records the difference (Claude Code: yes) |

The protocol has a harness-neutral part (`prompts/protocol.md`) and a short
harness part (`prompts/harness-<name>.md`): Claude Code's "Read before
Write" rule and tool names live there.

### Per-home environment

A home can give a harness's runs extra environment, such as a gateway URL
and its key, in `config.toml`. The table is `[harnesses.<name>]` (plural:
the top-level `harness` key names the default harness):

```toml
[harnesses.claude]
env_file = "claude.env"          # relative to the home; ~ expanded

[harnesses.claude.env]
ANTHROPIC_BASE_URL = "https://gateway.example/v1"
```

The order is: wpk's own environment, then `env`, then `env_file`. The file
holds `KEY=VALUE` lines (`#` comments, `export ` and quotes allowed) and
must be mode 0600: if group or others can read it, wpk warns and skips the
file (the `env` table still applies). Keys belong in the file, not in
`config.toml`.

Each step's `meta.json` records its route, never the key:
`"route": {"account": "subscription", "host": "gateway.example"}`. The
account comes from the transcript (Claude Code's `apiKeySource`: `none` is
a subscription login, anything else is `key`; `unknown` if not reported);
the host from the adapter's `base_url_var` (`ANTHROPIC_BASE_URL` for
Claude), or `default`. `wpk stats --by route` gives token use and cost per
`account@host`.

## 4. Profiles (H2)

Built in at `work_packet/profiles.toml`, overridable in the runner's
`config.toml` (`[profiles.<name>]`) and chosen per project:

```toml
[profiles.claude-haiku]
version = 1
harness = "claude"
models = ["claude-haiku-*"]
sizing = "bounded"                  # prompts/sizing-<name>.md
step_context_tokens = 80000
carry_factor = 4.0
# USD per million tokens, for harnesses that do not report cost
price = { input = 1.0, output = 5.0, cache_write = 2.0, cache_read = 0.1 }
```

- **Sizing text**: `bounded` is today's "do one step's worth of work and
  stop"; `persistent` says "keep working until the instruction is done or
  you are told the context is large; do not stop to report progress", for
  models that stop early.
- **Choosing**: a project may name `profile`; otherwise the first profile
  whose harness matches and whose `models` glob matches the packet's model;
  otherwise a `default` profile for the harness.
- **Precedence** for `step_context_tokens` and `carry_factor`: built-in
  default < profile < `config.toml` < `project.toml`. A key set in a TOML
  file wins over the profile.
- `meta.json` records `harness` and `profile` (`name@version`), so a profile
  change is a before/after comparison.

## 5. Short steps (H3)

A step is **short** if it ends `resume: now`, made few calls (≤ 2 tool
calls), changed little (`state.diff` and later `work.diff` small), and its
context peak is well under the limit. With carry-over on, the next step
already resumes the warm session, so an early stop costs about one call plus
a commit. Nothing more is needed in the engine; stats (H4) report how often
it happens, and the advice is to use `sizing = "persistent"` and carry-over.

A harness `Stop` hook that refuses to stop (Claude Code has one) could avoid
even that, but it hides progress until the step ends. Left as an option.

## 6. Statistics and advice (H4)

`wpk stats [project...] [--since 7d] [--json]` reads every `meta.json`
(steps and failed attempts) and the journals, and groups by
harness, model and profile:

| Figure | From |
|---|---|
| steps, failed attempts, retry rate | journal |
| calls per step (median, p90) | `context.calls` |
| output tokens per step | `tokens` |
| tokens: context read (cache read and write shares), output (thinking share), share spent on failed attempts, cache breaks | `tokens`, `context.cache_breaks` |
| context base, peak (median, p90) | `context` |
| short-step rate | §5 rule |
| hook rate (soft, hard) | `ctxhook.fired` |
| cost per step, carried and fresh | `cost_usd`, `carried_from` |
| cost and steps per finished packet | journal |

Advice rules, each with a minimum sample (30 steps) and shown with the
numbers that triggered it:

| Seen | Advice |
|---|---|
| short-step rate > 40% | "stops early": `sizing = "persistent"`, `carry_session = true` |
| hook fires on > 25% of steps, or hard level at all | "steps run long": tighten instructions, or raise `step_context_tokens` if the context window allows |
| carried steps near the reset cost more than the median fresh step | lower `carry_factor` (the break-even multiple is printed) |
| carried steps never reach the reset and stay cheaper | `carry_factor` can go up |
| retry rate > 10% | harness or protocol trouble, not step size |

The board gets the same figures in a panel later; `wpk stats` comes first.

`wpk stats --by project|packet|model|day|step` prints a table of token use
and cost per row instead: steps, cost, context tokens read, cache writes,
output, thinking share, cache hit rate, the share on failed attempts and
cache breaks (`--json` for the rows). It is the data for the token trend
views planned in `docs/token-dashboard.md`.

`wpk stats --tools [tool|kind|target]` splits steps' context by the tool
results that put it there (docs/token-dashboard.md, view 5).

Token counts come from Claude Code's `result` events, summed over a step's
runs (a nudged step has two). Their `usage` covers one run even on a
resumed session; `total_cost_usd` and `modelUsage` cover the whole chain
(probed 2026-10-23). A step recorded before these fields existed is filled
in from its transcript when `wpk stats` reads it.

## 7. Other harnesses (H5, H6)

Each starts with probes, as for Claude Code in `context.md`: the command,
the output format and where token usage is, resume and fork, mid-step
injection, how cost is reported, and caching (the break-even in context.md
§1 depends on the provider's write premium and read discount).

What their CLIs offer, from `--help`, local files and the official docs
(2026-10-22, no model run; "inferred" = not documented or tested):

| | Claude Code | Codex 0.147.0 | OpenCode 1.18.18 |
|---|---|---|---|
| Run | `claude -p`, prompt on stdin | `codex exec -` (stdin), `-C dir` | `opencode run`, stdin + message, `--dir` |
| Events | `--output-format stream-json` | `--json`: `thread.started`, `turn.completed`, `item.*` | `--format json`: `step_start`, `step_finish`, `tool_use`, `text` |
| Usage per call | `assistant.message.usage` | per turn in `--json`; per call in the rollout file (`event_msg` `token_count`, `info.last_token_usage`) | `step_finish.part.tokens {input, output, cache{read, write}}` |
| USD cost | yes (chain total on resume) | **no**: wpk prices tokens | yes, per call (`step_finish.part.cost`) |
| Isolation | `--setting-sources ""`, `--strict-mcp-config`, `--tools` | `--ignore-user-config`, `--ignore-rules`; safest is a temp `CODEX_HOME` with the auth file | `--pure`, `OPENCODE_DISABLE_*`, `OPENCODE_CONFIG_CONTENT`; temp `XDG_CONFIG_HOME` (inferred) |
| Tools/approval | `--tools`, `--allowedTools`, `--permission-mode` | `-s workspace-write`, `-c approval_policy="never"` | `permission` / `tools` config, `--auto` |
| System text | `--append-system-prompt-file` | `-c developer_instructions=...` | `instructions` config (files) |
| Choose session id | yes | no (`thread.started.thread_id`) | no (`sessionID` on every line) |
| Resume | `--resume` | `codex exec resume <id> -` | `run -s <id>` |
| Fork | `--fork-session` | **no** in `exec` (interactive only) | `--fork` |
| Mid-step message | `PostToolUse` hook, `additionalContext` (probed) | `PostToolUse` hook, `additionalContext` (cap 2500 tokens); hooks must be trusted or `--dangerously-bypass-hook-trust` | plugin `tool.execute.after` (can edit tool output) or `experimental.chat.messages.transform` (inferred) |
| Refuse a stop | `Stop` hook `decision: block` | `Stop` hook `decision: block`, reason sent as a user prompt | none; `session.idle` + a follow-up prompt (inferred) |
| Caps | `--max-budget-usd` | none (budgets "under development") | agent `steps` (max iterations) |
| Cache | 1-hour TTL in use | automatic (provider) | automatic; markers on system and last messages |
| Transcript on disk | `~/.claude/projects/<cwd>/<id>.jsonl` | `~/.codex/sessions/Y/M/D/rollout-*.jsonl` | SQLite `~/.local/share/opencode/opencode.db` |

Consequences for the adapters:

- Codex: no fork, so carry-over resumes in place; cost comes from the
  profile's prices; the C3 hook reads the rollout file (or counts from the
  `--json` stream per turn). Codex has the `Stop` hook, so the
  short-turn remedy can be in-harness there.
- OpenCode: reports cost per call (sum it; check whether a forked run
  repeats the parent's cost); C3 needs a small JS plugin; the step's
  `steps` cap can stand in for a budget.
- Neither lets wpk choose the session id, so carry-over takes it from the
  previous step's `meta.json` (as it already does).

## 8. Build plan

- [x] H1: `harness/` package with `Caps`, `StepSpec`, the Claude adapter
  (moved from `model.py`, no behaviour change); `harness` key (default
  `claude`); `prompts/harness-claude.md`; executor uses the adapter; tests.
- [x] H2: `profiles.toml`, profile choice and precedence, sizing fragments,
  `harness` and `profile` in `meta.json`; tests.
- [x] H4: `wpk stats` and advice rules; tests on synthetic projects.
- [x] H3: short-step rule (shared by stats); nothing else unless the
  numbers ask for it.
- [ ] H5: Codex probes, then the adapter.
- [ ] H6: OpenCode probes, then the adapter.

## Status log

### 2026-10-22: design
Plan written. Codex 0.147.0 and OpenCode 1.18.18 are installed here.

### 2026-10-22: H1 done
`work_packet/harness/` (`Caps`, `StepSpec`, `Claude`); `model.py` keeps the
generic runner. Without `system_slot` the protocol leads the step prompt
(and `prompt.md`); without `inject` no hook; without `resume` no carry-over;
the chain-cost correction applies only with `cost_is_chain_total`.
`meta.json` records `harness`. The Read-before-Write rule moved to
`prompts/harness-claude.md`. 274 tests pass. CLI survey of Codex and
OpenCode added to §7.

### 2026-10-22: H2 done
`profiles.py` + built-in `profiles.toml` (`claude-haiku@1`, `claude@1`; no
prices, since Claude Code reports cost). `[profiles.*]` in `config.toml`
are checked first; a project may name `profile`. `step_context_tokens` and
`carry_factor` set in a TOML file win over the profile (`Settings.explicit`).
The sizing sentence moved out of `protocol.md` into
`prompts/sizing-bounded.md`; `sizing-persistent.md` is the "keep going"
text. No profile for the step's harness and model is a usage error (no
attempt used). 286 tests pass.

### 2026-10-22: H3, H4 done
`stats.py` and `wpk stats [project|dir ...] [--since 7d] [--json] [--min N]`.
Groups by (harness, model, profile); steps from before C1 get `context`
from their transcript, so old runs count (profile shows as `-`). The
`carry_factor` break-even is a least-squares line of carried-step cost
against peak/base, solved for the median fresh cost; on the E7 numbers it
gives about 4. On yesterday's three E7 runs: 27 steps, 4 calls median,
base 10.9k, $0.0164 a step, 15% short, no advice. 293 tests pass.

Next (H5): Codex probes cost money on the Codex account, so they wait for
a go-ahead. Order: `codex exec --json` with a temp `CODEX_HOME`, usage and
`thread_id`; `exec resume`; a `PostToolUse` hook with `additionalContext`
(and hook trust); then the adapter with prices in a `codex-*` profile.
