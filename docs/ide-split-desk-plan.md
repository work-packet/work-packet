# Split IDE desks: hidden Claude sessions after a VS Code update

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
