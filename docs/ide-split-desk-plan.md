# Split IDE desks: hidden Claude sessions after a VS Code update

> **Superseded (2026-11-18)** by `docs/ide-direct-server-plan.md`. The pin (fix 1)
> failed: after an update, serve-web refuses the pinned release's paths. wpkd no
> longer runs serve-web. Fixes 2–4 still stand.

Report: `~/projects/packets/verilator-dvs-integ/docs/design/wpk_orphaned_ide_session.md`.

## What happens

`code serve-web` sends every request whose path has no `stable-<commit>/`
prefix to the newest VS Code release it knows of. When a release lands
(it checks on its own; all desks downloaded `dcd3ad6` at 00:27:58 and
`69047191` at ~14:15 on 2026-11-11), the next page load, and also any
WebSocket reconnect from a tab that is already open, goes to a *new*
server for the same desk. The old server keeps its terminals, and the
`claude` sessions in them, but no client can reach them again. serve-web's
idle "ending" kills only its `sh code-server` wrapper; `server-main` is
reparented to init and lives on (it stays in xproxy's process group; the
terminal shells are in sessions of their own).

Verified 2026-11-11: two packets (verilator-dvs-integ, fw-proto-axi-new)
each had a hidden claude in an orphaned `dcd3ad6` server. Both were
killed by hand (16 processes); the visible sessions were left alone.

`/<base>/stable-<commit>/` serves that commit's workbench, and WebSocket
upgrades work under it (checked against the live desk).

## Fixes

1. **Pin a desk to its release** (`dash/ide.py`): the proxy learns the
   desk's `stable-<commit>` (from the workbench page, or a request that
   carries one), records it on the launch (`release` in `launches.jsonl`),
   and prefixes every unprefixed request, HTTP and WebSocket, with it. A new
   launch starts unpinned and gets the newest release. `_vscode-cli/` and
   `__wpk/` paths are left alone.
2. **Duplicate-session warning** (`hookcmd.py`): at SessionStart, other live
   claude records for the same packet on this host (pid alive) go into the
   session's context; a shared `WPK_IDE_LAUNCH` says it may be in a VS Code
   window no tab shows.
3. **Split-desk detection** (`dash/ide.py`): a desk's process tree with more
   than one `server-main`; logged, and shown on the dashboard.
4. **Reap by launch** (`dash/ide.py`): when a desk stops, also end the
   processes whose environment carries its `WPK_IDE_LAUNCH` (escaped the
   process group via setsid or reparenting).

## Status

- [x] 1 pin: `Backend.route/pin/release` in `dash/ide.py`; the pin is the
  launch's `release` field.
- [x] 2 duplicate warning: `hookcmd.others_note`, added to the SessionStart
  briefing.
- [x] 3 split detection: `ide_stranded.py`. The idle loop logs it, and the
  packet page shows "Stranded VS Code server" with an End it button
  (`act` op `end-stranded`).
- [x] 4 reap: `Backend._stop_now` ends the desk's servers and the
  claude/codex under them, found before the killpg. Narrowed from "every
  process with the launch id" so that `nohup` jobs survive.
- [x] tests: `tests/test_ide_split_desk.py`.
- [ ] live check: after a board restart, open a desk and confirm in
  `serve.log`/`launches.jsonl` that the release is recorded and requests are
  prefixed (needs the board restarted on this code).

## The extension's idle session (2026-11-12)

What was reported as "two VS Code sessions on one packet" on
verilator-param-recursion was neither a split server nor a second tab. The
VS Code Claude extension starts a `claude` (entrypoint `claude-vscode`)
whenever the workbench loads. Its SessionStart hook made a presence record
("waiting"), so the terminal session started later got the "Another Claude
session is live" warning naming it (pid 3999087, "same VS Code launch as
you"), and the board counted it as a second Claude waiting for you. It had
no transcript: nobody had typed to it.

Fix: SessionStart (not after a compaction) records `prompted: false`, and
UserPromptSubmit sets it true. `presence.engaged(rec)` is false only for
such a record. The duplicate warning (`hookcmd.others`), the card's agent
summary (`dash/data.py`, `presence.where`) and attention (`attention.py`)
skip it. Older records without the field count as before. Test:
`test_a_session_nobody_has_typed_to_is_not_another_session`.

Also: the board's "VS Code (browser)" buttons opened `_blank`, so a repeated
click (e.g. after a slow first load) made a second tab on the same desk.
They now target a named tab per folder (`wpk-ide-<wpid>`,
`wpk-ide-<project>`, `wpk-ide-<project>-<repo>[-packet]`); a repeat click
reloads the tab already open. Links the CLI prints still open fresh. Test:
`test_browser_buttons_reuse_the_desks_tab`.
