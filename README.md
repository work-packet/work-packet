# work-packet

Agents as processes. A **packet** is a directory that holds everything needed
to pick a piece of LLM work up again: the next instruction (`memento.md`), its
status, its private state, links to the outside world, and a journal of every
step. A small deterministic executor (`wpk`) runs one step at a time with
`claude -p`, commits the result atomically, and decides when the packet runs
next: now, in ten days, or every Monday.

Status: pre-alpha. The Stage 1 commands work against a fake model in the
test suite; they have not yet been run against the real `claude` (that is
M8 in `docs/stage1-plan.md`).

```bash
wpk new count-demo --prompt "Increment state/count.md until it reaches 8, then spawn a child that writes Hello World"
wpk tick --until-idle      # or from cron: */5 * * * * wpk tick -j 2
wpk ps                     # what is running, sleeping, paused or failed
wpk log count-demo         # the root packet's journal; --step N for one step
wpk check                  # validate everything against docs/spec.md
```

Also: `wpk step`, `recover`, `show`, `pause`, `resume`, `adopt` and `rm`.
`wpk <command> --help` describes each.

## Documents

- `docs/roadmap.md`: the idea, lessons from the prototype, and phases 0–5.
- `docs/spec.md`: the packet format, v0.2. `wpk check` enforces it.
- `docs/runner.md`: design of the runner, the dashboard and `wpk new`.
- `docs/stage1-plan.md`: the detailed build plan for the first stage, with status.
- `slides/work-packet.pptx`: overview deck (built from `slides/*.js`).
- `prototype/`: the original experiment, kept as evidence. Its failures become
  regression tests.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/pytest -q
```

Python 3.10 is the floor, because that is what the Forgejo CI runner has.

## License

Apache-2.0.
