# VS Code on a packet or a work folder: build plan

Status (2026-10-25): V0–V5 built and tested, plus the openvscode-server
backend and one server per target; the desktop link works from
Windows. Waiting on you: `sudo tailscale set --operator=$USER` for https on
the tailnet (V4 live). A fresh session can pick up
from this file and the status log at the end.

This plan **replaces the build plan in `docs/ide.md` §8**. ide.md was
written for the old layout (clones inside the packet) and v0.3 ownership
states. `docs/workflow-review.md` §4.1–§4.5 and §6.4 list what changed.
This plan is narrower: it covers **launching** desktop and web VS Code. It
does not cover take-back, Continue in VS Code, Review at step N, or an
extension; those are under "Later".

## 1. What you can open

There are three kinds of target. Each one has a desktop link and a web
URL.

| Target | Opens | When |
|---|---|---|
| **Packet** `wpk ide <project>[/<wpid>]` | a multi-root workspace (§2) | the usual case |
| **Your clone** `wpk ide <project> <repo>` | the folder `<project>/work/<repo>` | setup, merging `wpk/<project>`, your own edits |
| **Packet worktree** `wpk ide <project> <repo> --packet` | the folder `packets/<UUID>/work/<repo>` | looking at, or fixing, what the runner did |

A "work folder" means one entry of `work/`: a git clone, or a plain
directory such as `data/`. Plain directories exist only at the root (the
packet holds a link to them), so `--packet` on a plain directory opens the
same root folder and says so.

Which packet: `<project>` alone means the root packet, as `wpk path` does
today. Before the seed, the packet target opens the **project root**
instead (dash-tasks §5.4: before the seed you set up at the root, and the
packet is empty).

## 2. The packet's workspace file

```
<packet>/.vscode/packet.code-workspace     # before the seed: <project>/.vscode/project.code-workspace
<packet>/.vscode/settings.json             # the packet folder's files.exclude
```

Folders, after the seed:

```jsonc
"folders": [
  { "path": "../work/dv-solve", "name": "dv-solve (packet: wpk/dvs-enh)" },  // one per git worktree
  { "path": "../work/data",     "name": "data (shared, no rollback)" },      // plain dirs, via the link
  { "path": "../state",         "name": "state" },
  { "path": "..",               "name": "packet" }
]
```

Before the seed, the folders are the root's `work/*` (named
`dv-solve (your clone)`), `state/` and the root.

Rules (from workflow-review §4.1–§4.3):

- Your clone is never in a packet's workspace after the seed. Every folder
  name says which tree it is.
- The `packet` folder gets `files.exclude` for `work/`, `state/`,
  `steps/`, `.pending/`, so nothing shows twice.
- Always set: `files.watcherExclude` and `search.exclude` for
  `**/packages/**`, `**/rundir/**`, `**/build*/**`, `steps/`, `.pending/`.
  Terminal env: `WPK_PROJECT`, `WPK_WPID`, `WPK_PACKET`, `WPK_WORK` (the
  same as the browser shell); terminal cwd: the first worktree.
- `window.title` is `wpk: <name>${dirty}`: the project's name for the
  root, `<project>/<spawn name>` for a child. It names the window, and the
  browser tab in web VS Code (checked live). A title of your own (one not
  starting `wpk: `) is kept.
- **Merge, don't overwrite.** wpk owns `folders` and a fixed list of
  settings keys. It parses the JSONC, replaces only those keys, and writes
  only when they changed. Anything you add in VS Code stays.
- Written by `wpk ide` and by the board's open action, so a GET to a page
  never writes. The executor does not write it on every step commit.
- `.wpk/` is not part of the packet format. `wpk check` and the executor
  ignore it.

The single-folder targets need no workspace file. VS Code opens the folder
with the folder's own `.vscode/` settings.

## 3. Desktop VS Code

The board link opens VS Code on the computer where the browser runs, and
VS Code connects back over SSH:

```
vscode://vscode-remote/ssh-remote+<host><abs path>[?windowId=_blank]
```

- `<host>`: `[ide] ssh_host` if set (an alias from the laptop's
  `~/.ssh/config`, or `user@host`). Otherwise the node's MagicDNS name,
  from `dash/tailscale.py`.
- **Same machine.** `vscode://file/<abs path>` comes first only when the
  request is on loopback *and* the browser's user agent is the host's OS
  (Linux here). Loopback alone is not enough: a browser on Windows reaching
  a loopback-only board through a forwarded port is on loopback too (found
  live, 2026-10-25). The page shows both links, and the one you click is
  remembered in the browser (`localStorage`) and followed next time.
  `[ide] desktop_link = "remote" | "local"` fixes the choice.
- `<host>` without `[ide] ssh_host` is `you@<name>`: the laptop's own login
  (a Windows user name, say) is often different.
- `<abs path>` is the workspace file for a packet, and the folder for a
  folder target. Spike V0 checks that a `vscode-remote` URI opens a
  `.code-workspace` file. If it does not, the packet target falls back to
  the folder, with the workspace file at the folder root so that VS Code
  offers to open it.
- wpk takes no part in SSH. If the laptop cannot SSH to the host, VS Code
  shows its own error.

`wpk ide … --open` from a shell:

| Where `wpk` runs | Runs |
|---|---|
| in a VS Code terminal (`VSCODE_IPC_HOOK_CLI` set: the remote CLI) | `code <path>`, which opens a window on the laptop |
| on a desktop with `code` and a display | `code <path>` |
| anything else | nothing: prints the link and the web URL |

Without `--open`, `wpk ide` prints the path, the `vscode://` link and the
`/ide/` URL. This makes it useful over plain SSH.

## 4. Web VS Code

wpkd serves VS Code under `/ide/` and proxies it to a backend on a unix
socket. The backend has no login and no port of its own (ide.md §4.1):

```
browser ─► wpkd Guard (identity, Host, Origin) ─► /ide/<key>/* ─► $WPK_HOME/ide/servers/<key>/serve.sock ─► code serve-web
```

`code serve-web` 1.98.2 on a9550 has `--socket-path`,
`--server-base-path`, `--without-connection-token`,
`--accept-server-license-terms` and `--server-data-dir` (checked
2026-10-25). `$WPK_HOME/ide/` is 0700, and wpkd refuses to start the
backend if it cannot create the directory with that mode.

URLs: `/ide/<key>/?folder=<abs path>` for a folder, and
`/ide/<key>/?workspace=<abs path>` for a packet. `<key>` is 12 hex digits
of the SHA-256 of the target's path: **one server per target**, so a
packet's extension host, terminals and crashes stay apart from other
packets'. Opening a target from the board registers it
(`$WPK_HOME/ide/servers/<key>/target`), so a reload after wpkd restarts
still finds it; a key the board never opened is a 404 and starts nothing.

### 4.1 Proxy (`dash/ide.py`)

- HTTP: `httpx.AsyncClient(transport=AsyncHTTPTransport(uds=…))`,
  streamed both ways. httpx joins the `dash` extra.
- WebSocket: accept, then `websockets.unix_connect` to the backend and
  pump frames both ways. VS Code's remote protocol runs over this
  connection, so this is the part to get right. Close both sides when
  either side closes.
- Guard on `/ide/*`: identity and Host as on every route. Origin must
  match on the WebSocket upgrade and on every non-GET request. **No CSRF
  token:** the browser shell's token in the first frame cannot apply,
  because VS Code's own client opens the socket. A matching Origin is what
  stops cross-site WebSocket hijacking, and the Guard already checks it.
  The Guard needs a path-based exemption from the token rule for `/ide/`
  only.
- Headers: forward the client's Host; forward only `vscode-*` cookies;
  drop any `X-Forwarded-*` that came from the client. Rewrite
  `enableWorkspaceTrust` in the workbench HTML (V0 finding 4). Responses under `/ide/` keep the backend's own CSP. The board's
  strict CSP applies to board routes only.

### 4.2 Lifecycle

- A target's server starts on the first `/ide/<key>/` request. Concurrent
  first requests wait on one start (with a ~15 s limit for the socket to
  appear), never two.
- Stopped after `[ide] idle_minutes` (default 60) with no open WebSocket,
  and with wpkd (SIGTERM, then SIGKILL after 5 s).
- One server per target. Its socket, log and pid file are in
  `$WPK_HOME/ide/servers/<key>/` (0700); all share `$WPK_HOME/ide/data`
  (extensions, machine settings), which both backends allow.
- At most `[ide] max_servers` (default 8) run at once. Starting one more
  stops the least recently used server with no open WebSocket; if every
  one is in use, the request gets a 503 saying so. Each costs ~150–300 MB.
- serve-web sets its cookies on `Path=/`, and each server's secret half
  differs, so the proxy rewrites the path to `/ide/<key>`.
- If `code` is missing or has no `serve-web`, the web button is hidden
  and `wpk doctor` says why.

### 4.3 Secure context: loopback first, then the tailnet

VS Code web needs service workers (webviews, Markdown preview) and the
clipboard API. Browsers allow both only on `https://` or `localhost`
(workflow-review §4.4). So:

- **On loopback it works now:** on the host, or from the laptop through
  `ssh -L 7878:localhost:7878`. V3 targets this.
- **On the tailnet it needs `tls = "tailscale"`** (server.md S1b, not
  built). V4 is S1b plus a live check from the iPad. Until then, the web
  button on a plain-`http` tailnet page is shown disabled with "needs
  HTTPS (server.md S1b)".

### 4.3a A server in a job (TCP)

With the scheduler's `[sched.ide] slot` (docs/scheduler.md §8), the
server runs in a job of the pool on a compute node instead of on wpkd's
host. `dash/ide.py` then uses `JobBackend`: the same `/ide/<key>/` paths
and Guard, but the upstream is the TCP `host:port` the job wrote to
`ide/servers/<key>/endpoint`, and every upstream request carries the
server's connection token (`ide/servers/<key>/token`, 0600) as the
`vscode-tkn` cookie, since a port on a shared node is open to other farm
users. The Open menu gains a size select (`look`, `sim`, ...). While the
job waits for room the page shows "Waiting for room" and reloads every
5 s. Idle stop cancels the job; a board restart re-attaches to it.

### 4.4 Backends

`[ide] backend = "serve-web"` (the default) or `"openvscode-server"`.
openvscode-server (Gitpod) is the open-source build of VS Code's own server
(Code-OSS, MIT): the same flags as `serve-web`, no subcommand. The proxy
does not care which one runs. Differences that matter:

- **Licence.** The VS Code Server licence covers one person's own remote
  use. openvscode-server has no such limit, so it is the one for sharing
  the board with other people.
- **Install.** A release tarball (~250 MB unpacked) from
  github.com/gitpod-io/openvscode-server; put `bin/openvscode-server` on
  PATH or set `[ide] code`. No download on first start (serve-web fetches
  ~680 MB then, V0 finding 5), so it suits hosts with no outside access.
- **Extensions** come from Open VSX, not the Microsoft marketplace. Some
  Microsoft extensions (Pylance, C/C++ remote parts, Copilot) are not
  there.
- **Webviews still use `vscode-cdn.net`** (its product.json keeps
  `webviewContentExternalBaseUrlTemplate`), so a host with no outside
  access still loses Markdown preview and extension UIs. Fixing that means
  serving the webview files ourselves; not built.

code-server (Coder) is the other open-source option. It has its own CLI and
login, so it would need a different argv and its auth turned off; not built.

## 5. Opening a packet the runner owns

This plan does not build take-back. It builds only the protection that
costs nothing:

- **Your clone**: always yours. Open freely.
- **A packet, or a packet worktree, while a step runs or the packet is
  runnable**: the button still opens it, labelled "runner owns this:
  read-only". The workspace's wpk-owned keys then include
  `files.readonlyInclude: {"**": true}`, `git.autorefresh: false`,
  `git.autofetch: false` and `editor.formatOnSave: false`. They are
  removed when the packet is paused, needs input, has failed or has
  completed. This is a guard against mistakes, not a security boundary,
  and the label says so. A single-folder `--packet` open gets the same
  keys through a workspace file of its own,
  `.wpk/<repo>.code-workspace`.
- The executor retries a git command once on `index.lock`, because VS
  Code's git extension can hold it (workflow-review §4.2).
- When a packet is paused, it is yours: open it read-write. "Pause and
  open" is one button on the board, a POST to the existing `pause` action
  followed by the open. It is disabled while a step is running, until L1
  adds take-after-step.

## 6. Config

```toml
[ide]
desktop      = true            # show the vscode:// buttons
web          = false           # serve VS Code under /ide/ (opt in)
backend      = "serve-web"     # or "openvscode-server"
code         = ""              # empty: "code" (serve-web) or "openvscode-server"
ssh_host     = ""              # empty: this node's MagicDNS name
idle_minutes = 60
max_servers  = 8               # one server per open target
```

## 7. Build plan

```
V0 spikes ──► V1 targets + wpk ide ──► V2 board desktop buttons
                                   └──► V3 web proxy (loopback) ──► V4 tailnet web (with S1b)
                                                                  V5 runner-owned settings (after V1)
```

### V0: Spikes (half a day, nothing kept)

- [ ] `vscode://vscode-remote/ssh-remote+a9550/<abs>.code-workspace` from
      the Windows desktop (desktop-4dl84an): does it open as a workspace?
      Also `windowId=_blank`.
- [ ] `code serve-web --socket-path … --server-base-path /ide
      --without-connection-token` behind a 40-line Starlette proxy on
      loopback: open `?folder=` and `?workspace=`, edit, use a terminal,
      open a Markdown preview (service worker), install an extension.
- [ ] The same with the host offline: what does serve-web download on its
      first run and on an update? Record the answer here.
- Write down: the URI forms that work, which query parameter opens a
      workspace, and anything the proxy has to rewrite.

### V1: Targets, workspace file, `wpk ide`

- [x] `ide.py`: `resolve(project, repo=None, packet=False) -> Target`
      (kind, abs path, label, owner state); `workspace(pkt)` builds and
      merges the JSONC (§2); `links(target, request_host)` returns the
      desktop and web URLs (§3, §4).
- [x] JSONC merge: read with comments stripped; write as plain JSON with
      wpk's keys replaced. A file that does not parse is left alone, with
      a warning (never clobber).
- [x] `wpk ide <project> [<repo>] [--packet] [--open] [--print]`.
- [x] `wpk check` and the executor ignore `.wpk/`.
- Tests: workspace before and after the seed; zero, one and two repos plus
  a plain dir; folder names; user-added folders and settings survive a
  merge; no write when nothing changed; `--packet` on a plain dir; link
  built from `ssh_host`, from a fake `tailscale status`, and as
  `vscode://file` for loopback; `--open` chooses the right command (with
  `code` faked on PATH).

### V2: Board desktop buttons

- [x] Packet page: **Open in VS Code**. It is a POST, so the workspace
      file is written by an action and not by a page view. It answers with
      a page that follows the `vscode://` link from `ide.js` (the board's
      CSP `form-action 'self'` blocks a redirect to another scheme), with
      the other link (this computer / Remote-SSH) beside it. On the tailnet
      the SSH host is the name the browser used for the board.
- [x] Project page: a `work/` list with **your clone** and **packet
      worktree** buttons for each repo.
- [x] The labels and disabled states from §5.
- Tests: the buttons for each state; the POST writes the file and
      redirects to the expected URL; GET routes leave the home
      byte-identical (the existing test).
- [x] Live: from desktop-4dl84an, click each button and check that the right
      tree opens.

### V3: Web VS Code on loopback

- [x] `dash/ide.py`: the HTTP and WebSocket proxy, the Guard exemption
      (no CSRF token under `/ide/`, Origin still checked), header and CSP
      handling (§4.1, V0 findings 2–4).
- [x] Lifecycle (§4.2): start on demand behind one lock; a pid file, so a
      server left by a board that crashed is taken over and stopped, not
      duplicated; idle stop; stop with the board, by process group. The
      `doctor` check `tools.code` (only with `web = true`).
- [x] Buttons: **In the browser** next to each desktop button (new tab),
      shown with `web = true`; disabled with the reason when the page is
      not a secure context or `code` is missing.
- Tests (`tests/test_ide.py`, fake backend `tests/fake_ide.py`): the
  above, plus Host and `vscode-*` cookies forwarded, other cookies not; the
  backend's CSP and cookies reach the browser, the board's frame headers
  do not; WebSocket text and binary frames both ways; another login gets
  403 and nothing starts; `web = false` is 404; one process for three
  concurrent first requests; idle stop; the whole process group stops.
- [x] Live (2026-10-25, headless Chrome on a9550 through `wpk dash` on
      127.0.0.1 with real `serve-web`): the project page's **In the
      browser** opened the workspace in a new tab; labelled folders; no
      Restricted Mode; a terminal with `WPK_PROJECT` set; SIGTERM to wpkd
      left none of the server's 9 processes. Not yet: a person editing
      through `ssh -L` from the laptop.

### V4: Web VS Code on the tailnet

- [x] server.md S1b (`tls = "tailscale"`): `dash/tls.py` fetches the pair
      from LocalAPI, keeps it in `$WPK_HOME/tls/` (0700, key 0600), renews
      within 30 days of the end and keeps the old one if renewal fails. The
      tailnet listener serves https only (no http fallback; without a
      certificate it is not started and the log says why), under the
      certificate's name. uvicorn's graceful shutdown is capped at 3 s: an
      idle TLS keep-alive held SIGTERM open for good (plain http did not).
      Tests: `tests/test_tls.py`.
- [ ] Live: needs `sudo tailscale set --operator=$USER` once (LocalAPI
      answers 403 to this user now). Then `[server] tls = "tailscale"`,
      `tailnet = true`, `[ide] web = true`, and open
      `https://a9550.perch-char.ts.net:7878/` from the iPad and
      desktop-4dl84an.

### V5: Runner-owned settings

- [x] The read-only and git keys of §5 (`ide.GUARD`), applied when the
      runner owns the packet and taken off, restoring what they replaced,
      when it is yours. Applied on open and by the executor after every
      step and admin action (`ide.set_owner`; only a packet someone opened
      has a workspace file; a broken file never fails a step).
- [x] `workspace._git` waits once (1 s) and retries on `index.lock`. (The
      executor does not commit or reset work repos yet, so this covers
      `worktree add`, `status` and `rev-parse`.)
- [x] **Pause and open** on the packet page (disabled while a step runs).
- Not done: a single-folder **Packet worktree** open gets no read-only
  settings. They would have to go in the worktree's `.vscode/`, which a
  step would commit; the page says the runner owns it instead.

## Later (not in this plan)

Take-after-step (L1), Continue in VS Code (ide.md §6, as a terminal
profile), Review / Open at step N (workflow-review §5.4), the packet
session terminal profile (`wpk attach`), a
VS Code extension (needs the JSON API), and hosts other than wpkd's (ide.md
open question 2).

## Open questions

1. **Repo name vs packet name collisions** in `wpk ide <project> <x>`:
   does `<x>` mean a repo or a wpid? Proposed: a repo, and use
   `<project>/<wpid>` for a packet.
2. **Extensions in web VS Code** live in `$WPK_HOME/ide/data`, apart from
   the desktop's. Settings Sync, or a list in `[ide] extensions` that wpk
   installs on the first start?
3. **Child packets with their own worktrees** (long-running.md §10.2):
   separate workspaces, or extra folders in the parent's?

## Status log

### 2026-10-25: V0 web spike done

Spike: `serve-web` on a socket, a 60-line Starlette proxy (httpx over the
socket, `websockets.unix_connect` for the upgrade), and headless Chrome
through Playwright on `http://localhost:7991/ide/`. Both `?folder=` and
`?workspace=` open; workspace folder names show in the explorer; the
terminal works; `isSecureContext` is true on localhost. Findings that
change the design:

1. **Socket path length.** `$WPK_HOME/ide/serve.sock` can exceed the
   108-byte `sun_path` limit (it did in a scratch dir). Use the home path
   when it fits, else `$XDG_RUNTIME_DIR/wpk-ide-<hash8>/serve.sock`
   (0700), else `/tmp/wpk-ide-<uid>-<hash8>/`.
2. **Forward Host.** serve-web builds `remoteAuthority`, its CSP's
   `script-src` and resource URLs from the request's Host header. The
   proxy forwards the client's Host (already checked by the Guard).
3. **Cookies pass through.** serve-web sets `vscode-secret-key-path` and
   `vscode-cli-secret-half` (Path=/), used for secret storage. The board
   sets no cookies, so the proxy forwards `vscode-*` cookies and drops
   any others. (Replaces "strip Cookie" in §4.1.)
4. **Workspace trust.** VS Code web opens every workspace in Restricted
   Mode, which disables tasks and the workspace settings wpk relies on
   (read-only, excludes). User settings in the server data dir do not
   help (web user settings live in the browser). The proxy rewrites
   `enableWorkspaceTrust` to false in the workbench HTML when `[ide]
   workspace_trust = false` (the default): the runner already runs this
   code unattended as the same user, so trust adds no protection here.
5. **First start downloads** the server (~680 MB unpacked, to
   `~/.vscode/cli/serve-web/<commit>/`) and answers 202 until done (~30 s
   here). Webviews use `frame-src https://*.vscode-cdn.net`, so offline
   hosts lose webviews (Markdown preview, extension UIs) and the first
   start fails. openvscode-server avoids the download but not the CDN (§4.4).
6. **Process tree.** `code` is a shell wrapper → node → `code-tunnel` →
   `code-server` → node. Killing the parent orphans the server. Start the
   backend in a new session and SIGTERM the process group; the server then
   cleans up its own terminals (checked).
7. The multi-root terminal asks which folder to start in; a
   `terminal.integrated.cwd` setting does not stop the prompt. Accepted.

Not done: the desktop `vscode-remote` link to a `.code-workspace` file
needs a click from the laptop; V1 builds both link forms so the answer
only picks the default.

### 2026-10-25: plan

Written from ide.md, workflow-review.md §4/§6.4, setup.md §10 and
dash-tasks.md §5. Checked on a9550: `code` 1.98.2 at `/usr/bin/code` with
`serve-web` and the needed flags; the Guard already handles WebSocket
scopes (`guard.py:123`); httpx is not a dependency yet. Next: V0.

### 2026-10-25: V1–V5 built

`wpk ide`, the workspace file in `<packet>/.vscode/` (one non-format entry
instead of `.wpk/` plus a folder settings file), board buttons, web VS Code
under `/ide/`, Tailscale TLS, and the runner-owned guard. Deviations from
the plan above: the board answers the open action with a page that follows
the `vscode://` link (CSP `form-action`); web needs no CSRF token under
`/ide/`; serve-web's cookies pass through; workspace trust is rewritten off.
Full suite: 508 passed, 4 skipped. Live: web VS Code through wpkd on loopback.

### 2026-10-25: the desktop link, live from Windows

First click from desktop-4dl84an (board on 127.0.0.1 through a forwarded
port): VS Code reported that the path does not exist on this machine. The
board had sent `vscode://file/...`, because it took loopback to mean "the
browser is here". Fixed as in §3: loopback plus the same OS, both links on
the page, the choice remembered, `desktop_link` to override, and `you@` in
the SSH host. The Remote-SSH link ("VS Code on another computer") works from
Windows, which also answers V0's question: a `vscode-remote` URI opens a
`.code-workspace` file.

### 2026-10-25: openvscode-server backend

`[ide] backend = "openvscode-server"` runs Gitpod's open-source build in
place of `code serve-web` (§4.4); `[ide] code` now defaults to the
backend's own program. `wpk doctor` and the disabled web button name the
missing program. Live on a9550 with v1.109.5 through the board's proxy on
loopback, in headless Chrome: `?folder=` and `?workspace=` open, the
terminal runs, no Restricted Mode (the trust rewrite works unchanged), and
stopping the board stops the server and its terminal shells. Two 404s for
`vsda` (Microsoft's closed signing module) are expected and harmless.

### 2026-10-25: one server per target

Each target the board opens (a packet's workspace file, a repo folder) gets
its own server under `/ide/<key>/` (§4, §4.2), for both backends.
`dash.ide.Backends` holds them; `[ide] max_servers` caps them, and the
least recently used idle one makes room. Spike first: two serve-web and two
openvscode-server instances on one shared data dir both start;
openvscode-server sets no cookies, serve-web sets `vscode-cli-secret-half`
on `Path=/` with a different value per server, hence the cookie path
rewrite. Live on a9550 with both backends, two targets in one browser: both
load, each terminal starts in its own folder, the first reloads after the
second opens, the cookies sit on `/ide/<key>`, and stopping the board stops
both servers. A server from the old single-server layout
(`$WPK_HOME/ide/serve.pid`) is not adopted; one left by a crashed board
must be stopped by hand.
