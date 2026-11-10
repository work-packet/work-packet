# Desktop: GUI tools on the farm node, in a browser tab, started on demand

Status: **Desktop 1 built and checked live on the dev host (2026-11-07)**; scope in §0,
progress and what's left in §9. Not committed.
Proposal written 2026-11-06. Roadmap: the "GUI apps on
the node" gap in `roadmap-v2.md` §5 (M3-M4). Why: `positioning/competitive-position.md`
§6. This is the biggest gap for DV engineers (waveform viewers), and the one place
Open OnDemand, Altair and LSF Application Center are ahead.

Target farm, confirmed: TigerVNC `Xvnc`, `fvwm` and `xfce` are installed.

## 0. Scope for Desktop 1, and why VNC and not NX (2026-11-07)

### NX, Xpra or VNC

NX (NoMachine; `nxagent` from nx-libs, as used by X2Go) is the most efficient
of the three on a slow link: it compresses the X protocol itself and caches
images, rather than sending screen pixels. But **no open browser client for
NX exists**. NoMachine's web client comes only with its commercial servers,
and X2Go's HTML5 client never left alpha. NX would therefore need a native
client on each laptop (NoMachine or `x2goclient`) and an SSH or NX port to the
node, which breaks D1 (a browser tab) and D4 (only mTLS from wpkd, nothing
listening on the node).

| | In a browser | Efficiency | Fits wpk's transport |
|---|---|---|---|
| NX (nxagent) | no (commercial NoMachine only) | best on slow links | no: a native client and its own port |
| Xpra (HTML5 client) | yes | close to NX: per-window, H.264/VP8 for video-like areas | yes, as a second backend (§8) |
| **VNC (TigerVNC + noVNC)** | yes | good on a LAN or tailnet: Tight with JPEG, ZRLE | yes: one byte stream over a unix socket |

So Desktop 1 is **VNC**, as planned. The viewer starts with Tight encoding at
JPEG quality 6 and compression 2, which suits a LAN or tailnet; both can be
changed in the tab. The relay route and the WebSocket conversion carry an
opaque byte stream, so Xpra (or NX, if a browser client ever exists) can be
added behind the same `/desk/` route later without changing the transport.

### Desktop 1: what this round builds

Built from the spike (§9, X0) on the dev host, which has TigerVNC 1.13.1, xfce4 and
`xfwm4`, but not fvwm.

- **Both kinds of IDE server get a display:** the board's own local VS Code
  server (the :7878 board), and a scheduler job's server over `mtls`.
  `tcp-token` jobs get none, because their transport can't carry a second
  stream.
- **`xproxy` wraps the VS Code server** (`xproxy ... -- <server argv>`). It
  sets `DISPLAY`, `XAUTHORITY` and `[desktop.env]` for the server, and so for
  every terminal and session in it. It stops the display when the server exits.
  One process group means the board's start, stop, adoption after a restart,
  and job cancelling all work unchanged.
- **xproxy also owns the viewer socket** (`<priv>/vnc`): a viewer attaching is
  what starts Xvnc, just as an X client is. Xvnc's own VNC socket is hidden
  (`<priv>/x/rfb`).
- **wpkd `/desk/<key>/`**: the noVNC page, plus a WebSocket that is converted
  to the byte stream. It is owner only, with an Origin check and the CSRF token.
  For a local server, wpkd connects straight to `<priv>/vnc`. For a job, it
  goes through the relay with the TLS server name `vnc.wpk`.
- **`[desktop]` config**:
  - `enabled`, `wm` and `idle_min`;
  - `geometry`;
  - `[desktop.env]` and `unset`, applied over the built-in defaults, then the
    site file, then the user's file (the existing layering).
  
  The board and packet layers, `env_file`, and locked-key reports in doctor
  wait for later.
- **WM:** `auto` picks fvwm (with a small generated config), else xfwm4, else
  none. `xfce` runs a full session.
- **Getting there:**
  - a **Desktop** link in the web IDE (above the status bar; a link on the
    board's packet page is left for later);
  - `wpk desktop`, which prints the URL from a VS Code terminal;
  - a toast in the web IDE when a window opens and no viewer is attached.
- **Apps menu** (added 2026-11-07, after the first live use: xfwm4 alone has
  no menu): the tab's bar lists `[desktop.apps]` (a terminal by default) and
  starts one in the server's environment and the project's folder (§7.1).
  The tab is titled by project and packet.
- **Not in Desktop 1:**
  - `{file}` apps, waveform buttons and runner steps (X5);
  - journal records and the warning before reaping (rest of X6);
  - presence;
  - view-only sharing.

## 1. Goal

A packet's IDE job also gives you a **display**. Any GUI program started in that
job (from a VS Code terminal, a board button, or a runner step that opts in)
appears in a **desktop tab** in the browser. Nothing about the display runs until
a program or a viewer needs it.

## 2. Decisions

| # | Question | Decision |
|---|---|---|
| D1 | In VS Code or a separate tab? | **A separate browser tab** (`/desk/<key>/`). VS Code takes the keys GUI tools rely on (Ctrl+P/W, F-keys, Esc); a waveform viewer wants a full window or a second monitor; a webview iframe makes login cookies, fullscreen and clipboard fragile. VS Code gets a *link*: a toast, `wpk desktop`, and later a status-bar item. |
| D2 | Same job as the IDE, or its own? | **Same job** by default: same node, file system view, modules, licences and environment as the editor and sims. `[desktop] job = "separate"` is a later option for a different queue or more memory. |
| D3 | Always on, or on demand? | **On demand**, through a `DISPLAY` proxy (§4). The X server starts on the first X client or the first viewer, and stops after it has been idle. |
| D4 | Transport | Xvnc serves VNC on a **unix socket** in the job's private directory (`-rfbunixpath`), behind xproxy's own viewer socket `<priv>/vnc` (§0). The relay gains a route for the TLS server name `vnc.wpk`; a local board server is reached on the socket directly. wpkd converts the browser's WebSocket to the raw stream. No TCP port, no websockify on the node, no VNC password: mTLS and the board login do the authenticating. |
| D5 | Window manager | **`auto`: fvwm, else xfwm4, else none** (revised 2026-11-07: the dev host has xfwm4 but no fvwm). fvwm and xfwm4 start in well under a second. **xfce optional** (`[desktop] wm = "xfce"`) for people who want a full desktop. `none` is allowed, but windows can't then be moved. |
| D6 | Viewer | **noVNC**, bundled in `dash/vendor/novnc/` like xterm and codemirror. |
| D7 | Who gets `DISPLAY`? | **Every terminal and process in the IDE job, always**, once `[desktop] enabled`. That includes Claude and Codex sessions started in VS Code. Starting the server on demand keeps this cheap. Runner steps stay opt-in (`[desktop] steps`). (Decided 2026-11-06.) |
| D8 | How do tools behave correctly with a display present? | **A `[desktop.env]` table** set wherever `DISPLAY` is set. It is part of the normal config layers, so a **site** sets it in `/etc/wpk/config.toml` and can lock keys (`sites.md` §3). wpk ships safe defaults (§5.3). (Decided 2026-11-06.) |

## 3. The pieces

```
VS Code terminal / runner step                        ide_job (on the node)
  DISPLAY=:N ──▶ /tmp/.X11-unix/XN  ◀── xproxy (listens; no X server yet)
                                         │ first client or first viewer:
                                         │   Xvnc :M -rfbunixpath <priv>/vnc -auth <priv>/xauth
                                         │   start the WM (connects straight to :M)
                                         └─ splice each client ⇄ /tmp/.X11-unix/XM
browser /desk/<key>/ (noVNC) ─WS─▶ wpkd ─TLS+mTLS, name vnc.wpk─▶ ide_relay ─▶ <priv>/vnc
```

| Piece | Where | What |
|---|---|---|
| `sched/xproxy.py` (new) | runs inside `ide_job` | Allocates `:N` and owns its lock and sockets. Starts, watches and stops Xvnc and the WM. Joins client connections to the hidden display. Counts clients. Reports state to the server directory. |
| `ide_job.py` | node | Starts xproxy when `[desktop]` is enabled. Adds `DISPLAY`, `XAUTHORITY` and the merged `[desktop.env]` (§5.3) to the IDE server's environment, and writes `desktop.env.json`. |
| `ide_relay.py` | node | A new server-name route: `vnc.wpk` → `<priv>/vnc`. Advertised in `features` (`vnc-sni`), the same way as `fwd-sni`. |
| `dash/desk.py` (new) | wpkd | `/desk/<key>/` serves noVNC. `/desk/<key>/ws` converts WebSocket ⇄ the TLS stream with name `vnc.wpk`. Owner only, like `/ide/`. |
| `ide_forward.js` | web IDE page | Shows the "a window opened" toast (§6). |
| `sched/doctor.py` | | Probes for `Xvnc` (and whether it supports `-rfbunixpath` and `-displayfd`), `fvwm`, `xfce4-session`, `dbus-launch`, and `xauth`. |

## 4. On demand: the `DISPLAY` proxy

This is the same idea as `ssh -X` (a stand-in display) and GNOME's Xwayland
started on demand.

1. **Allocate `:N`.** Pick the lowest N for which none of these exist: the lock
   file `/tmp/.XN-lock`, the socket `/tmp/.X11-unix/XN`, or the abstract-namespace
   socket `@/tmp/.X11-unix/XN`. Create the lock file with our pid, the way an X
   server does, and bind **both** sockets. Linux X clients try the abstract socket
   first.
2. **Wait.** No X server runs yet. `DISPLAY=:N` is already set in the IDE's
   environment.
3. **First client, or first viewer attach** (wpkd tells xproxy through the server
   directory, or a control socket):
   - start `Xvnc -displayfd <fd> -rfbunixpath <priv>/vnc -auth <priv>/xauth
     -SecurityTypes None -nolisten tcp -extension MIT-SHM -geometry 1600x1000`
     (an initial size; the browser resizes it);
   - read `:M` from the `-displayfd` pipe;
   - start the WM and `vncconfig -nowin` (clipboard) connected **straight to
     `:M`**, so they don't count as clients;
   - then join the waiting client.
4. **Join.** Each accepted connection is copied byte for byte to
   `/tmp/.X11-unix/XM`. The splice carries bytes only, not ancillary data
   (`SCM_RIGHTS`), so X extensions that pass fds can't work through it. MIT-SHM
   1.2 returns its segments as fds: Qt 5.15's backing store
   (`xcb_shm_create_segment`) then waits forever for an fd that never comes,
   and its windows stay black. Xvnc therefore runs with `-extension MIT-SHM`,
   and clients fall back to plain socket transfers; `QT_XCB_NO_MITSHM = "1"`
   (a built-in `[desktop.env]` default) tells Qt5 the same. (`QT_X11_NO_MITSHM`
   is the Qt4 name; Qt 5.15 doesn't read it.)
5. **Idle stop.** When no client is connected through the proxy and no viewer
   has been attached for `[desktop] idle_min` (default 20), stop the WM, then
   Xvnc. Keep listening on `:N`. The next client starts it again from step 3.
6. **Job end.** Stop everything; remove the lock and sockets.

First-connect cost: Xvnc plus fvwm is expected to take well under a second.
xfce needs a few seconds (it starts a session bus and panels). The first client
waits; X clients tolerate a slow connect.

## 5. Security

### 5.1 The proxy socket

`/tmp/.X11-unix` is open to every user. On each accepted connection, xproxy
reads the caller's identity (`SO_PEERCRED`) and **closes any connection whose
uid isn't ours**. This is the main defence.

### 5.2 The hidden display

Xvnc's own `:M` socket is also in `/tmp/.X11-unix`, so it needs its own check:
- Xvnc runs with `-auth <priv>/xauth`, a fresh MIT cookie per job.
- The same cookie is added for `:N` to a job-private `XAUTHORITY`. Clients send
  it through the proxy unchanged.
- Another user can reach neither display: the proxy refuses them, and the hidden
  display needs the cookie.
- VNC is only on the private unix socket, behind mTLS.

### 5.3 Side effects of setting `DISPLAY`, and the environment that goes with it

`DISPLAY` is always set in the IDE job (D7), so anything started there sees a
display. That includes an interactive Claude's Bash tool, which has no terminal.
Known effects:
- `ssh` or `git` with no terminal will try a graphical password prompt and hang
  where nobody can see it;
- some tools switch to a GUI, or a different plot backend, when a display exists;
- Qt, GTK and OpenGL programs complain or misbehave without a GPU or session bus.

Anything that probes for a display (`xdpyinfo` in a login script) starts the
server. That is harmless: one start, reclaimed by the idle stop.

**`[desktop.env]`** holds the variables set together with `DISPLAY`. It
applies to the IDE server's environment (so every terminal, task and session in
VS Code), to apps started from `[desktop.apps]`, and to runner steps when
`steps = true`.

```toml
# /etc/wpk/config.toml (site)        or ~/.work-packet/config.toml (user)
[desktop]
enabled = true
unset = ["SSH_ASKPASS"]              # removed from the environment
env_file = "/etc/wpk/desktop.env"    # optional KEY=VALUE lines, after the table

[desktop.env]                        # set where DISPLAY is set
SSH_ASKPASS_REQUIRE = "never"        # built-in default
QT_XCB_NO_MITSHM = "1"               # built-in default: Qt5 without MIT-SHM (§4 step 4)
QT_X11_NO_MITSHM = "1"               # e.g. Qt4 apps under Xvnc
LIBGL_ALWAYS_SOFTWARE = "1"          # no GPU on farm nodes
NO_AT_BRIDGE = "1"                   # built-in default: quiet GTK accessibility-bus warnings
# GIT_ASKPASS is not a default (decided 2026-11-07): VS Code sets its own, for its git
# integration, and an empty one would also hide VS Code's prompt.
# EDA_TOOL_GUI_MODE = "batch"        # whatever a site's tools need

[site]
locked = ["desktop.env.SSH_ASKPASS_REQUIRE", "desktop.env.QT_X11_NO_MITSHM"]
```

Rules:

- **Order:**
  1. wpk's built-in defaults;
  2. the site file;
  3. the user's file;
  4. the board;
  5. the packet's settings;
  6. an app's own `env` in `[desktop.apps]`.

  Later wins, except for keys the site locks. `wpk doctor` warns about each
  override it ignored, as it does today.
- Values are literal strings, with one substitution: `{display}` (`:N`). No shell
  expansion. Anything that needs a shell (`module load …`) belongs in
  `sched.node_env` or a size's `env`, which already run before the job's command.
- `unset` removes variables, after the table is applied. An empty string sets a
  variable to empty, which isn't the same thing.
- The environment actually applied is written to the job's server directory
  (`desktop.env.json`, names and values, never `env_file` secrets). It is shown
  on the packet's desktop panel, so "why does this tool behave differently in
  wpk?" can be answered by looking.
- `wpk doctor` lists the merged table and where each key came from.

## 6. Noticing windows

xproxy knows when a client connects while no viewer is attached. It writes
`desktop.json` in the server directory:

```json
{"display": ":N", "x": "running", "clients": 2, "viewers": 0,
 "apps": ["verdi", "fvwm"], "since": "..."}
```

`apps` comes from the client pid's `comm`, looked up through `SO_PEERCRED`. Then:

- **Web IDE tab:** `ide_forward.js` shows a toast: "verdi opened a window: View
  desktop". The click opens the tab (pop-up blockers stop it opening by itself).
- **Card and packet page:** "Desktop: verdi, no viewer". It's a **notify** item
  (`collaboration.md` §4.3), with a "View" button.
- **Runner step:** a journal record `gui-client` (app name, time). If a step that
  opened a window then goes quiet, the card says so. An unattended tool waiting
  on an invisible modal dialog then shows up instead of hanging silently.
- **Presence:** an attached desktop viewer counts as presence, as a `desktop` kind
  (`collaboration.md` §4.2).

## 7. Automation

### 7.1 Apps and environment

**Built (Desktop 1):** the desktop tab's **Apps** menu. `[desktop.apps]` maps
a name to a command (`gtkwave = "gtkwave"`) or to `{ cmd, label }`; wpk adds
`terminal = { cmd = "xterm", label = "Terminal" }`, and `terminal = ""`
removes it. xproxy lists only entries whose program is on its host's PATH
(`launchers` in `desktop.json`). A click posts `/desk/<key>/run`; wpkd
drops a request in `<server dir>/desktop.run/`, and xproxy, which polls it
every 0.5 s, starts the command with `sh -c` in the server's own environment
(`DISPLAY`, `[desktop.env]`, `node_env`) and in the project's folder. A
request goes through the shared server directory, so it works the same for
the board's own servers and for jobs on other hosts. The menu doesn't depend
on the window manager, so it works with xfwm4 and `none` too.

**Still the plan:** `{file}` and `files` matching, waveform buttons, and
`wpk desktop APP [FILE]`:

```toml
[desktop]
enabled = true           # IDE jobs get a DISPLAY (on demand)
wm = "fvwm"              # fvwm | xfce | none
idle_min = 20
steps = false            # runner steps get DISPLAY too

[desktop.apps]           # per board; a packet's settings can add or override
verdi     = { cmd = "verdi -ssf {file}", files = ["*.fsdb"] }
simvision = { cmd = "simvision {file}",  files = ["*.shm", "*.trn"] }
gtkwave   = { cmd = "gtkwave {file}",    files = ["*.vcd", "*.fst"] }
xterm     = { cmd = "xterm" }
```

- Apps run with the packet's environment: the `node_env` IDE jobs already get,
  plus modules, ivpm and direnv when present. They start *on the display*, so
  starting one also starts the X server.
- **Waveforms:** the packet page lists matching files, newest first. So do the
  Timeline entries for runs and jobs that produced them. Each has an "Open in
  Verdi" button. Click → the app starts → the desktop tab opens. This is the DV
  workflow end to end.
- `wpk desktop [--open] [APP [FILE]]` from a VS Code terminal does the same,
  and prints the tab URL for Ctrl+click.

### 7.2 Window manager setup (generated, per job, in `<priv>/`)

- **fvwm:** a small generated config:
  - the packet name in the background and the title bars;
  - a root menu (left click) built from `[desktop.apps]`, followed by "Recent
    waveforms";
  - click-to-focus;
  - no pager.

  A personal `~/.fvwm/config` is used instead if `[desktop] wm_config = "user"`.
- **xfce:** run under `dbus-launch` with a job-private session. Turn off the
  screen locker and screensaver (`xfce4-screensaver`, `light-locker`), because a
  lock screen would ask for a password that nobody has. Turn off session saving,
  so each job starts clean.

### 7.3 Fit and comfort

- **Resize:** noVNC's remote resizing, plus RandR in Xvnc. The desktop follows
  the tab's size.
- **Clipboard:** `vncconfig -nowin` plus noVNC's clipboard handling. Recent
  browsers sync on focus with permission. Otherwise noVNC's clipboard panel is
  the fallback.
- **Reconnect:** closing the tab stops nothing. Reopening it reattaches to the
  same windows, until the idle stop (which only fires once no *clients* remain)
  or the job ends.

### 7.4 Licences and idle jobs

- The IDE job's idle reaping counts an attached viewer as activity. A **GUI
  client with no viewer** doesn't by itself keep the job alive past the IDE's
  idle limit. But before reaping, the board raises a warning ("verdi has been
  running 3h with no viewer; the job ends in 15 min: Keep / Close") and never
  silently kills a GUI app.
- The card shows which GUI apps are running, so a licence held by a forgotten
  window is visible.

## 8. Later

- **View-only sharing:** a read-only link for a colleague ("look at this
  waveform"), using noVNC's view-only mode. A first step towards
  `roadmap-v2.md` M6.
- **Agents looking at the screen** (opt-in, per packet): a skill that takes a
  screenshot of the display (`xwd`, or `import -window root`), so an agent can
  read a waveform or a dialog. It needs a guard: what is on the screen becomes
  input to the agent.
- **Xpra's HTML5 client** as a second backend: one browser window per app
  instead of a whole desktop.
- **A separate desktop job** (D2): a different queue or more memory.
- **fd passing through the proxy:** splice with `recvmsg`/`sendmsg` and carry
  `SCM_RIGHTS`, so MIT-SHM (and other fd-passing extensions) can be turned back on.
- **Desktop for packets without an IDE job:** "Open desktop" by itself submits a
  job with only xproxy and the relay.

## 9. Plan

Keep this table up to date as steps land.

| Step | What | State |
|---|---|---|
| X0 | Spike on the dev host (2026-11-07): Xvnc 1.13.1 with `-displayfd`, `-rfbunixpath` (0600), `-rfbport -1` and `-SecurityTypes None` is ready in 0.06 s; the MIT cookie is enforced; Xvnc binds the abstract socket too; xfwm4 runs standalone. **The `-rfbunixpath` limit is about 100 bytes** (a long scratch path failed): use `ide_job.local_dir`. Not yet tried on the LSF farm; fvwm isn't installed on the dev host | done (the dev host) |
| X1 | `sched/xproxy.py`: wraps the server; allocates `:N` from 20 (lock plus file and abstract sockets); Xvnc on a hidden `:M` started by the first X client **or viewer** (`<priv>/vnc`); byte splice; idle stop and restart; `SO_PEERCRED` check; one MIT cookie in a job-private `XAUTHORITY` (FamilyWild records, written directly; no `xauth` needed); `desktop.json`, `desktop.env.json`; runs the server without a display if Xvnc is missing. Tests use `tests/fake_xvnc.py`, plus one real-Xvnc test that skips where it isn't installed | done |
| X2 | Relay route `vnc.wpk` → the `vnc` path in `desktop.json` (`features`: `vnc-sni`); wpkd `/desk/<key>/` (noVNC page, `desk.js`), `/desk/<key>/state`, `/desk/<key>/ws` (CSRF token in `?t=`, Origin by the guard; a viewer counts as an IDE client); owner only in the guard; noVNC 1.7.0 vendored (`novnc`, es2022) | done |
| X3 | Wiring: the board's local `Backend` and `mtls` job argv run the server under xproxy when `[desktop] enabled` (read at each start); `[desktop]` schema and validation; `[desktop.env]` = wpk defaults < site < user (site locks work through the existing layering); `unset`; `wpk desktop`; doctor checks (`Xvnc` with `-rfbunixpath`, WM, noVNC built) and `Xvnc` in `wpk sched doctor`'s node probe. **Left:** board and packet layers of `[desktop.env]`, `env_file`, doctor listing each key's source | done (Desktop 1) |
| X4 | WM: `auto` = fvwm (small generated config: click to focus, root menu with a terminal) else xfwm4 (`--compositor=off --sm-client-disable`) else none; `xfce` under `dbus-run-session`. **Left:** fvwm menu from `[desktop.apps]`; xfce locker and session saving off; fvwm untested (not on the dev host) | partial |
| X5 | Apps and waveforms. **Done (2026-11-07):** `[desktop.apps]` (`name = "cmd"` or `{cmd, label}`; a default `terminal` = xterm; `""` removes one), the tab's **Apps** menu (only programs found on the server's host, from xproxy's `launchers`), `POST /desk/<key>/run` → a request file in `desktop.run/` → xproxy starts it with `sh -c` in the server's environment and the project's folder. The tab is titled by the project and packet of the last open (`demo · 3cc062ac — Desktop`) and links back to the packet. **Left:** `{file}` and file matching, waveform buttons on the packet page and Timeline | partial |
| X6 | Noticing windows: `ide_desk.js` in the workbench (a Desktop link above the status bar, and a toast when a new app opens a window with no viewer); `apps` from the client's `comm`. **Left:** card notify, `gui-client` journal records, reaping warning, a Desktop link on the board's packet page (needs the card → server key without `ide.resolve`) | partial |
| X7 | Docs: `ide.md` §7.1 and `sites.md` §3b done. Live check on the dev host (2026-11-07): a scratch board on :7891 with `serve-web` under xproxy; an xterm with the server's environment appears in headless Chrome's `/desk/` tab (xfwm4, resized to the tab); stopping the board leaves no processes, locks or sockets. **Left:** an `mtls` job on the SLURM pilot (p5810 has no Xvnc or WM yet); the LSF farm with Verdi | partial |

## 10. Open questions

1. Default `idle_min`: 20 minutes, or tied to the IDE's idle limit?
2. Should `wm = "xfce"` be the default for people who've used xfce before (a
   `~/.config/xfce4` check), or always fvwm unless asked?
3. ~~Is `DISPLAY` in VS Code terminals on by default?~~ Decided: always (D7),
   with `[desktop.env]` for tool behaviour (D8).
5. Should `[desktop] enabled` default to on when `Xvnc` is found on the farm
   (doctor probe), so a site only needs to supply `[desktop.env]`?
4. Does the farm's interactive queue need a different resource request for GUI
   work (memory for Verdi on large FSDBs)? This decides how soon D2's separate
   job is needed.
