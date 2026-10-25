# work-packet

Agents as processes. A **packet** is a directory that holds everything needed
to pick a piece of LLM work up again: the next instruction (`memento.md`), its
status, its private state, links to the outside world, and a journal of every
step. A small deterministic executor (`wpk`) runs one step at a time with
`claude -p`, commits the result atomically, and decides when the packet runs
next: now, in ten days, or every Monday.

Status: pre-alpha. The Stage 1 commands work against a fake model in the
test suite, and short projects have run end to end against the real
`claude` with Haiku. A week of real use is next (M8 in
`docs/stage1-plan.md`).

```bash
wpk setup                  # a guided setup, with a shell built in (pip install 'work-packet[tui]')
wpk doctor my-project      # what the setup has, what it lacks, and the command for each
wpk new count-demo --prompt "Increment state/count.md until it reaches 8, then spawn a child that writes Hello World"
wpk tick --until-idle      # or from cron: */5 * * * * wpk tick -j 2
wpk ps                     # what is running, sleeping, paused or failed
wpk log count-demo         # the root packet's journal; --step N for one step
wpk check                  # validate everything against docs/spec.md
wpk dash                   # the board at http://127.0.0.1:7878/ (pip install 'work-packet[dash]')
wpk dash --tailnet         # also on your tailnet, for your tailnet login only (docs/server.md)
wpk dash --run             # ... and run due packets: New task, Compose with a shell, Next batch
wpk next my-project -f next.md   # a stopped (or finished) task's next batch of work
wpk stats                  # per harness, model and profile: calls, context, cost, advice
```

Also: `wpk step`, `recover`, `show`, `pause`, `resume`, `adopt` and `rm`;
for setup (docs/setup.md), `path`, `shell`, `add-input`,
`add-smoke` and `instruct`.
`wpk <command> --help` describes each.

## Documents

- `docs/roadmap.md`: the idea, lessons from the prototype, and phases 0–5.
- `docs/spec.md`: the packet format, v0.2. `wpk check` enforces it.
- `docs/runner.md`: design of the runner, the dashboard and `wpk new`.
- `docs/dash-tasks.md`: the board as a workbench: new tasks, Compose, a shell in
  the browser, the next batch of work, and the runner in the server.
- `docs/stage1-plan.md`: the detailed build plan for the first stage, with status.
- `docs/long-running.md`: design for long-running projects: hand-off between a
  person and the runner, a git workspace inside the packet, the runner daemon
  and board actions, with a walkthrough and build plan.
- `docs/setup.md`: setting a project up: `wpk doctor` (checks, each with a
  fix), the helper commands, `[setup]` in `project.toml`, and the `wpk setup`
  wizard with a shell built in.
- `docs/server.md`: `wpkd`, one daemon for the runner and the board; the
  board on the tailnet with Tailscale identity as the login, no root.
- `docs/vscode-plan.md`: VS Code on a packet or a work folder: `wpk ide`,
  desktop links over Remote-SSH, and web VS Code under the board's `/ide/`
  (`[ide] web = true`). Supersedes the build plan in `docs/ide.md`.
- `docs/context.md`: context size and session length: per-call measurement,
  the protocol in the system prompt, a context budget hook and session
  carry-over between steps, with live E7 measurements.
- `docs/harness.md`: harness adapters (Claude Code now; Codex and OpenCode
  surveyed), model profiles, and `wpk stats` with advice.
- `slides/work-packet.pptx`: overview deck (built from `slides/*.js`).
- `prototype/`: the original experiment, kept as evidence. Its failures become
  regression tests.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dash]' pytest httpx
.venv/bin/pytest -q
```

Python 3.10 is the floor, because that is what the Forgejo CI runner has.

## License

Apache-2.0.
