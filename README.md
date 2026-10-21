# work-packet

Agents as processes. A **packet** is a directory that holds everything needed
to pick a piece of LLM work up again: the next instruction (`memento.md`), its
status, its private state, links to the outside world, and a journal of every
step. A small deterministic executor (`wpk`) runs one step at a time with
`claude -p`, commits the result atomically, and decides when the packet runs
next: now, in ten days, or every Monday.

Status: pre-alpha. Nothing works yet beyond `wpk --version`.

## Documents

- `docs/roadmap.md`: the idea, lessons from the prototype, and phases 0–5.
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
