# work-packet

Agents as processes. A **packet** is a directory that holds everything needed
to pick a piece of LLM work up again: the next instruction, its status, its
private state, links to the outside world, and a journal of every step. A
small deterministic executor, `wpk`, runs one step at a time, commits the
result atomically, and decides when the packet runs next: now, in ten days,
or every Monday. The board, `wpk dash`, shows every packet and whose move it
is.

Status: pre-alpha.

## Install

```bash
pip install work-packet              # the wpk command
pip install 'work-packet[dash]'      # and the board
pip install 'work-packet[dash,tui,studio]'   # everything
```

Python 3.10 or later, on Linux. Steps run with the
[Claude Code](https://claude.com/claude-code) CLI, which has to be installed
and logged in.

## A first packet

```bash
wpk setup                  # a guided setup (needs the tui extra)
wpk new count-demo --prompt "Increment state/count.md until it reaches 8"
wpk tick --until-idle      # run due steps until nothing is left to do
wpk ps                     # what is running, sleeping, paused or failed
wpk log count-demo         # the packet's journal
wpk dash                   # the board at http://127.0.0.1:7878/
```

`wpk <command> --help` describes each command.

```{toctree}
:maxdepth: 2
:caption: Guides

collaboration-guide
sched-guide
studio-guide
writing-a-starter
```

```{toctree}
:maxdepth: 2
:caption: Reference

spec
```
