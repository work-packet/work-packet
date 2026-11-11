# Is the agent working? Claude and Codex state at a glance

Source request (2026-11-10): "When I have a session open in VS Code (under
work-packet) with a Claude session running, I'd love to see whether Claude is
working or idle in the dash. What about Codex?"

This file is the tracking document. Update **Status** as each step lands, so a
fresh session can pick up from here alone.

## Status

| Step | What | State |
|---|---|---|
| A1 | Codex presence: the session collector writes presence records for live Codex sessions | done 2026-11-10 |
| A2 | Presence readers take Codex too: `presence.where`, `attention.session_items`, `attention.log_waits` | done 2026-11-10 |
| A3 | Board card chip: "Claude · working", "Codex · your turn", "Claude · needs OK"; the VS Code sessions table's turn is a chip too | done 2026-11-10 |
| A4 | Packet page: the same chip in the packet's header, for its own sessions | done 2026-11-10 |
| A5 | Tests, docs (`docs/vscode-plan.md` §4.5) | done 2026-11-10; not yet seen in a live browser with a real Codex |
| A6 | Optional: Codex `notify` (turn-end program) for faster updates | not started; check what codex-cli 0.147 supports first |

## 1. What exists today

- **Claude, with hooks** (`sessionhooks.py`, `hookcmd.py`, on by default):
  every turn event writes a presence record to `<project>/presence/claude-<sid>.json`
  with `turn` set to `working`, `waiting` or `blocked` (plus `tool`). This is exact and
  immediate, and it is the only source that sees a permission prompt.
- **The session collector** (`ide_sessions.py`, runs on the board every 5 s for
  editors the board opened): it reads Claude transcripts and Codex rollouts and
  keeps a `turn_state` (`working`, `waiting`, `finished`, `interrupted`). Codex
  `task_started` maps to working and `task_complete` to waiting (a person drives it).
  A sub-agent's rollout (`session_meta.source.subagent.thread_spawn`) is part of its
  root's session: its tokens count there. While one is mid-turn after the root's
  turn has ended, the session stays working (`background`: "1 background agent").
  Codex doesn't wake the root when a sub-agent finishes, so after that it is your
  move. A sub-agent asking for approval makes it waiting.
- **Where it shows:**
  - The VS Code sessions table (packet, project and Overview pages) shows the turn
    as a small grey line under "Last event". It's easy to miss.
  - The card's one-line brief, when someone is present: "you · VS Code (web) ·
    Claude ×1 (1 waiting)". "Working" is never said, and Codex is never counted.
  - The attention list shows "Claude is waiting for you" after `idle_escalate`
    and "Claude wants to run X". It covers Claude only, and is hidden while
    the web VS Code tab is visible.

**The gaps:**
1. Nothing on the card says plainly "working" or "idle".
2. Codex never reaches presence, so neither the card nor attention knows about it.

## 2. Design

### A1: Codex presence from the collector

Codex has no hooks wired by wpk, so the collector writes Codex's presence record
for it, from its `turn_state`:

- Source `codex-<sid>`, `kind="codex"`, and `via` from the client (`vscode` or
  `terminal`), plus `session`, `wpid`, `launch` and `host`.
- `turn`: `working` for BUSY, `waiting` for WAITING, FINISHED or INTERRUPTED (a
  person drives it, so a finished turn is their move).
- Write only on a change of turn, or every `BEAT_S` (60 s) while working, so it
  doesn't rewrite the file every 5 s. `turn_since` is kept across beats of the
  same turn.
- When the session is no longer live, call `presence.end`.
- Only for sessions with a project (`_packet(env)` or the previous record).
- Claude stays with its hooks: the collector does not write Claude records, which
  would overwrite the hook's `blocked`. (A follow-up could do it for Claude when the
  hooks are off.)

Limits: Codex can be up to one poll (5 s) behind, and an approval prompt is not
seen, because the rollout doesn't show it. Only editors the board opened are
collected, and a Codex run in a plain terminal is not.

### A2: Readers take Codex

- `presence.AGENTS = {"claude": "Claude", "codex": "Codex"}`, and `presence.where` counts both, by
  harness name ("Claude ×1 (1 waiting) · Codex ×1").
- `attention.session_items`: the same rules for both kinds, with the text naming
  the harness ("Codex (VS Code) is waiting for you").

### A3: Card chip

`data.card` adds `agents`: a summary of the project's live agent presence records,
the most urgent first (blocked > waiting > working). In the card's `.tags` (always
visible, also when folded), a chip:

| state | chip | style |
|---|---|---|
| working | `Claude · working` | pulsing dot, running colour |
| waiting | `Claude · your turn` | NEEDS_INPUT colour |
| blocked | `Claude · needs OK` | FAILED/alert colour, tool in the title |

When several sessions are present: `2 agents · your turn` (`3 agents · 2 working` when more than one share the top state), with the details in
the title. The board page already refreshes live, so the chip follows.

### A4: Packet page

The same chip in the packet page's header, from the records whose `wpid` is the
packet (falling back to the project's records with no `wpid`).

## 3. Tests

- `ide_sessions`: a Codex session going from task_started to task_complete writes
  `codex-<sid>` with working, then waiting. It doesn't rewrite with no change inside
  `BEAT_S`, and it ends when the process goes.
- `presence.where` and `attention.session_items` with Codex records.
- `data.card` `agents` summary ordering, and the board renders the chip.

## Notes

- 2026-11-10: plan written.
- 2026-11-10: A1–A5 implemented, not committed. Changed: `ide_sessions.py`
  (`Collector._presence`, `PRESENCE_HARNESSES`, `TURN_KIND`, `turn_kind` on rows),
  `presence.py` (`AGENTS`, `where`), `attention.py`, `dash/data.py` (`agents()`,
  `card`/`packet` carry `agents`), templates `base.html` (`.agent` chip), `board.html`,
  `packet.html` and `_vscode.html`. Tests: `test_presence.py::test_where`,
  `test_collab_c4.py` (`test_codex_sessions_need_you_too`, `test_agents_chip`,
  `test_the_board_and_packet_page_show_the_chip`),
  `test_ide_sessions_bind.py::test_codex_turns_reach_presence`. Full suite passed:
  1475 passed, 15 skipped.
- Design choices made while implementing:
  - The chip reads presence with no freshness limit (`ttl=None`). An open session
    that has waited for an hour still says "your turn". Reaping by pid ends records
    of processes that are gone.
  - A waiting Codex session beats once, not every `BEAT_S`, as Claude's hooks do.
    Otherwise an idle open Codex would keep the card in "Working: you" forever.
  - The Codex record carries the process pid and this host, so `presence.reap`
    ends it if the board stops before the process does.
- Next: look at it live (board with a real Codex in web VS Code). Then A6 (Codex
  `notify`), and maybe collector-written Claude presence when the hooks are off.
