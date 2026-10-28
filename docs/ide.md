# VS Code from the board: open a packet in an editor

Status (2026-10-25): design only. Nothing built. **The build plan (§8)
is superseded by `docs/vscode-plan.md`**, which follows the built layout.
A fresh session should be able to pick up from this file and the status
log at the end.

The board shows packets but you cannot edit anything from it, and we do not
want to build an IDE into it. VS Code is already a good editor for a folder
on another machine, both on the desktop (Remote-SSH) and in a browser
(`code serve-web`). This document covers:

1. **Open in VS Code**: a button on a packet (and on a step) that opens the
   packet in desktop VS Code on your laptop, connected over SSH to the host
   where the packet lives.
2. **Open in the browser**: the same packet in a web VS Code served by
   wpkd under `/ide/`, behind the board's own login.
3. **Ownership**: what the button does when the runner owns the packet,
   so an editor never races the executor.

Contents: §1 what we have · §2 the workspace file · §3 desktop VS Code ·
§4 web VS Code · §5 ownership · §6 continuing a step's conversation ·
§7 config · §8 build plan · open questions · status log.

## 1. What we have

- The board is on the tailnet with Tailscale identity checks
  (`docs/server.md` S1). wpkd knows its MagicDNS name from
  `tailscale status`.
- Each packet is a directory on the host. Under `long-running.md` §2 its
  workspace is `work/`, a folder of git repositories, and its plan
  documents are in `state/`.
- Ownership follows from state (`long-running.md` §1): `HELD` and
  `COMPLETED` are yours, `RUNNABLE` and `SLEEPING` are the runner's.
  `wpk handoff` is built; `wpk take` is not yet (L1).
- `step-start` journal records carry the Claude Code `session_id`.
- The laptop already uses VS Code Remote-SSH to this host
  (`~/.vscode-server` exists on a9550), and VS Code 1.98 on the host
  includes `code serve-web`.

So the desktop button needs no new server, only a URL. The web version
needs wpkd to proxy one more local process.

## 2. The packet's workspace file

`work/` holds several repositories, so open a multi-root workspace rather
than a single folder. wpk writes one per packet:

```
<packet>/.wpk/packet.code-workspace      # not in any work repo; not part of the packet format
```

```jsonc
{
  "folders": [
    { "path": "../work/fw-uart16550" },   // one per work repo
    { "path": "../state", "name": "state" },
    { "path": "..", "name": "packet" }    // memento.md, journal, notes
  ],
  "settings": {
    "terminal.integrated.cwd": "${workspaceFolder:fw-uart16550}",
    "terminal.integrated.env.linux": { "WPK_WPID": "<wpid>" },
    "files.readonlyInclude": {}           // filled in while the runner owns it (§5)
  },
  "tasks": {
    "version": "2.0.0",
    "tasks": [
      { "label": "wpk: status",   "type": "shell", "command": "wpk show <wpid>" },
      { "label": "wpk: check",    "type": "shell", "command": "wpk check <wpid>" },
      { "label": "wpk: hand off", "type": "shell", "command": "wpk handoff <wpid>" },
      { "label": "wpk: take",     "type": "shell", "command": "wpk take <wpid>" }
    ]
  }
}
```

- It is written when the packet is created and rewritten when its work
  repos or owner change (`handoff`, `take`, a step's final commit). VS Code
  reloads workspace settings from the file, so an open window picks up
  the change.
- With `step_env = "direnv:<repo>"` (L2) the terminal opens in that repo
  and the usual direnv hook applies. wpk does nothing extra.
- The tasks give you hand-off and take from inside the IDE with no
  extension. A packet without `work/` (today's packets) still gets a
  workspace file, with just `state/` and the packet folder.
- `wpk ide <target>` prints the workspace path and the two URLs (§3, §4),
  for use without the board.

## 3. Desktop VS Code: a link

The button is a link that the browser passes to VS Code on the laptop:

```
vscode://vscode-remote/ssh-remote+<ssh_host><packet>/.wpk/packet.code-workspace?windowId=_blank
```

- `<ssh_host>` defaults to this node's MagicDNS name. `[ide] ssh_host`
  overrides it with an alias from the laptop's `~/.ssh/config`, or
  `user@host`.
- SSH works however it already works: Tailscale SSH or normal keys. wpk
  does not take part in the connection, so it adds nothing to the
  security picture. If the laptop cannot SSH to the host, the link fails
  in VS Code with VS Code's own error.
- The same link works whether you reach the board over the tailnet or
  through an SSH tunnel. When the board and VS Code are on the same
  machine, `vscode://file/<path>` would be simpler (open question 1).

**Not `code tunnel`.** A tunnel would let the laptop reach a host it
cannot otherwise reach, through Microsoft's dev-tunnels relay, with a
GitHub or Microsoft login. The tailnet already gives us reachability and
identity, so a tunnel only adds a third party and a second login.

**To check first:** that a `vscode-remote` URI opens a `.code-workspace`
file and not only a folder. If it does not, the link opens the packet
folder and you open the workspace file from VS Code's prompt (VS Code
offers to open a workspace file it finds at the folder root, so the file
would move to `<packet>/packet.code-workspace`).

## 4. Web VS Code: `serve-web` behind wpkd

For a browser, including the iPad, wpkd serves VS Code under `/ide/`.

| Option | Why or why not |
|---|---|
| **`code serve-web`** (Microsoft's VS Code CLI) | Real VS Code with Microsoft's marketplace. Has `--socket-path`, `--server-base-path` and `--without-connection-token`, which is everything a proxy needs. **Chosen** |
| code-server (Coder), openvscode-server (Gitpod) | Open source, but extensions come from Open VSX, which lacks some Microsoft ones (Pylance, the remote packs). A second, separately updated VS Code |
| vscode.dev + `code tunnel` | No server to host, but the relay and the extra login of §3 |

### 4.1 One login

`docs/server.md` §1: logging into the board is equivalent to a shell, and
a web IDE is a shell outright. So the IDE has no login of its own and no
port of its own. wpkd proxies it, and the request passes the same `Guard`
as every board route (identity, Host, Origin):

```
browser ──► wpkd (Guard: whois, Host, Origin) ──► /ide/* ──► unix socket ──► code serve-web
```

```
code serve-web --socket-path $WPK_HOME/ide/serve.sock \
               --server-base-path /ide \
               --without-connection-token \
               --accept-server-license-terms \
               --server-data-dir $WPK_HOME/ide/data
```

`--without-connection-token` is safe only because the socket is reachable
by our user alone (the socket lives in a 0700 directory) and wpkd checks
every request before forwarding it. The proxy must refuse to start
`serve-web` if it cannot create that directory with that mode.

### 4.2 The proxy

- `dash/ide.py`: a Starlette route for `/ide/{path:path}` (HTTP, via
  httpx over the unix socket) and a WebSocket route (bytes in both
  directions, via `websockets` over the unix socket). VS Code's remote
  protocol runs over the WebSocket, so this is the part that matters.
- Strip `Cookie` and the CSRF token before forwarding. Do not forward
  `X-Forwarded-*` headers that came from the client.
- CSP: the board's CSP is strict (no inline script). VS Code's web UI
  needs its own, so `/ide/*` responses keep the headers `serve-web` sends
  and the board's CSP applies only to board routes. Host and Origin checks
  still apply to `/ide/*`.
- The button links to `/ide/?workspace=<packet>/.wpk/packet.code-workspace`
  (VS Code web also accepts `?folder=`).

### 4.3 Lifecycle

- Started on the first `/ide/` request, not at wpkd start. The first
  request waits (up to ~10 s) for the socket to appear, then is forwarded.
- Stopped after `[ide] idle_minutes` (default 60) with no open WebSocket.
  Stopped with wpkd (SIGTERM, then SIGKILL after 5 s).
- One `serve-web` for all packets; each tab opens its own workspace.
- Its stdout and stderr go to `$WPK_HOME/ide/serve.log`.
- `code` not on `PATH`, or too old for `serve-web`: the button is hidden
  and `wpk doctor` says why.

## 5. Ownership: who may edit

An editor on a packet the runner owns races the executor. Edits saved
during a step are swept into the step's commit, and the step's commit
changes files under your open buffers. So the button depends on the
state:

| State | Owner | Buttons |
|---|---|---|
| `HELD`, `COMPLETED` | you | **Open in VS Code**, **Open in browser** |
| `RUNNABLE`, `SLEEPING` | runner | **Take back & open**, **Open read-only** |

- **Take back & open** posts the board's take action (L1 `wpk take`).
  The packet is not running: it is yours at once and the editor opens. It
  is running: the board shows "taking back after this step" and opens the
  editor read-only. The workspace file becomes editable when the step's
  commit ends in `HELD`/`taken`.
- **Open read-only**: while the runner owns the packet, the workspace file
  has `"files.readonlyInclude": {"**": true}`. VS Code marks every file
  read-only and refuses to save. This guards against mistakes; it is not
  a security boundary (a terminal in the same window can still write).
- **Hand off from the editor**: the `wpk: hand off` task. Hand-off
  already commits your uncommitted work-repo changes (L2), so unsaved
  buffers are the only thing to warn about. VS Code's own "save before
  running task" setting covers it.

The `files.readonlyInclude` flip is the only place where wpk changes a
file to suit the editor. It happens in `.wpk/`, which is not part of the
packet format: steps never read or write it, and `wpk check` ignores it.

## 6. Continuing a step's conversation

A step page gets **Continue in VS Code**. It opens the workspace and runs
one more task:

```
claude --resume <session_id> --fork-session
```

in the packet directory. You talk to the model with the step's context,
and can ask "why did you do that?". `--fork-session` leaves the
executor's carried session untouched, so the next step is not affected.

- Fine while the packet is yours. While the runner owns it, the button is
  offered only in read-only form, and the forked session runs in plan
  mode (`--permission-mode plan`), so it cannot edit what the runner is
  editing.
- **To check first:** the `--fork-session` flag and how it behaves with
  `--resume` in the current Claude Code CLI.

## 7. Config and commands

In `$WPK_HOME/config.toml`:

```toml
[ide]
desktop       = true          # show "Open in VS Code" (vscode:// link)
web           = false         # serve VS Code under /ide/ (opt in)
ssh_host      = ""            # empty = this node's MagicDNS name
code          = "code"        # VS Code CLI used for serve-web
idle_minutes  = 60            # stop serve-web after this long with no client
```

| Command | Does |
|---|---|
| `wpk ide <target>` | Writes or refreshes the workspace file; prints its path, the `vscode://` link and the `/ide/` URL |
| `wpk ide <target> --open` | Runs `code --remote ssh-remote+<host> <workspace>` (or `code <workspace>` on the same machine) |
| `wpk doctor` | Also reports whether `code serve-web` is available |

New files: `<packet>/.wpk/packet.code-workspace` (per packet; `wpk
check` ignores `.wpk/`), and `$WPK_HOME/ide/` (0700: `serve.sock`, `serve.log`,
`data/`).

## 8. Build plan

Order: I1 needs nothing new and can start now. I2 needs L1's `wpk take`.
I3 is built on S1's `Guard`, and is easier once S2 puts everything in one
daemon. I4 is only worth doing if the tasks prove clumsy.

```
I1 (now) ──► I2 (after L1 take) ──► I3 (after S1, best after S2) ──► I4 (maybe)
```

### I1: Workspace file and the desktop link

- [ ] `ide.py`: write `.wpk/packet.code-workspace` (folders from `work/`,
      `state/`, the packet; terminal env; tasks). `wpk check` and the
      executor ignore `.wpk/`.
- [ ] Rewrite it on `wpk new`, `handoff`, and a step's final commit.
- [ ] `[ide]` config; `wpk ide <target> [--open]`.
- [ ] Board: **Open in VS Code** on the packet page.
- Tests: workspace JSON for a packet with no `work/`, one repo, two
  repos; rewrite on hand-off; link built from `ssh_host` and from a fake
  `tailscale status`; the board's GET routes still leave the home
  byte-identical (the workspace file is written by commands, not by
  page views).
- Live check: click the button on the board from the laptop; VS Code
  opens the packet over SSH with all folders and the tasks.
  Settle the open question in §3 here.

### I2: Ownership-aware buttons

- [ ] Buttons by state (§5); **Take back & open** through the board's
      take action.
- [ ] `files.readonlyInclude` while the runner owns the packet; flipped
      on take and hand-off.
- [ ] **Continue in VS Code** on a step page (§6).
- Tests: the buttons shown for each state; the workspace file's readonly
  setting after `handoff`, `take` (not running), and `take` while running
  then the step's commit.

### I3: Web VS Code under /ide/

- [ ] Spike first (half a day): `serve-web` on a socket behind a minimal
      Starlette proxy with `--server-base-path /ide`. Open a workspace,
      edit, use a terminal, install an extension.
- [ ] `dash/ide.py`: HTTP and WebSocket proxy, header handling, CSP split
      (§4.2).
- [ ] Lifecycle: start on demand, idle stop, stop with wpkd (§4.3).
- [ ] Board: **Open in browser**; hidden without `code` or with
      `web = false`.
- Tests: a fake upstream on a unix socket (echoes HTTP and WebSocket
  frames). Through the proxy: an allowed login reaches it; another login
  gets 403 and never reaches the upstream; a bad Origin on the WebSocket
  upgrade gets 403; idle stop after a short configured time; a second
  request while starting waits rather than starting a second process.
- Live check from the iPad over the tailnet.

### I4: A VS Code extension (maybe)

- [ ] Status bar item with the packet's state and owner; hand off and
      take as commands; a tree of the project's packets; a link back to
      the board. Only if the I1 tasks prove clumsy in daily use.

## Open questions

1. **Same machine.** When the board and VS Code run on the same machine,
   `vscode://file/<path>` is simpler than `ssh-remote`. Decide by
   comparing the request's address with the listener (loopback means
   local), or always offer both.
2. **Several hosts.** When steps run on another host (interaction.md
   mentions it), the link needs that host's name, not wpkd's. Read it
   from the packet's lease or the step record.
3. **Children with workspaces** (long-running.md §10.2). A child with its
   own `git worktree`s gets its own workspace file; the parent's could
   list the children's worktrees as extra folders, or not.
4. **Extensions in web VS Code.** `serve-web` keeps its own extension set
   in `$WPK_HOME/ide/data`, separate from the desktop's. Settings Sync can
   cover it, or a list in config that wpk installs on first start.

## Status log

### 2026-10-25: design

Written after a discussion with the user. Decided: desktop over SSH on
the tailnet, not `code tunnel`. Web VS Code is Microsoft's `serve-web`,
proxied by wpkd on a unix socket behind the board's `Guard`, so there is
one login. Ownership decides the buttons, with a read-only workspace while
the runner owns the packet. Not yet checked: workspace files in
`vscode-remote` URIs (§3), `serve-web` behind a path prefix (I3 spike),
`--fork-session` (§6).
