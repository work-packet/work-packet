# wpkd: one daemon, a board you reach directly, and login

Status (2026-10-23): S1 built (the board on the tailnet, `wpk dash
--tailnet`), except TLS (S1b). S2 and S3 not built. A fresh session should be able to
pick up from this file and the status log at the end.

Today `wpk dash` binds `127.0.0.1:7878` with no login, and you reach it
from elsewhere through an SSH tunnel (`docs/runner.md`). The runner
(`docs/long-running.md` §4) is a second systemd user service. This document
covers three changes:

1. **One daemon, `wpkd`**: the runner loop and the board in one process.
2. **Direct access**: the board listens on the tailnet, with no SSH
   tunnel and no reverse proxy.
3. **Login as the user who started it**: only the person who owns the
   daemon's account can use the board. No root is needed at any point.

Contents: §1 the constraint · §2 Tailscale identity (the main mode) · §3
other modes · §4 CSRF and DNS rebinding · §5 one daemon · §6 config and
commands · §7 build plan · status log.

## 1. The constraint: the board is a shell

Once the board has POST actions (L4: hand off, instruction editor, new
project), it can start agents that run with your project's tool list, and
that usually includes Bash. **Logging into the board is equivalent to a
shell on your account.** It needs the same care as SSH access:

- no listener off localhost unless authentication is on;
- every request is checked, not just the login page;
- the identity is recorded: the `by` field of `handoff` and `take-request`
  journal records (long-running.md §7) is the authenticated name, not a
  guess.

All of this works without root:

| Need | How, as a normal user |
|---|---|
| Listen on a port | Any port above 1024 (7878) |
| Keep running when logged out | `loginctl enable-linger` (once; most distros allow it for your own user) |
| Know who is asking | Tailscale LocalAPI `whois` (§2), or PAM via `unix_chkpwd` (§3) |
| TLS certificate | `tailscale cert` after a one-time `--operator` (§2.3), or your own files |

## 2. Tailscale identity (the main mode)

Tailscale already gives every connection a verified identity. A packet
arriving on the tailnet interface came through WireGuard from a known node,
and that node's owner is known. `tailscaled` will tell any local process
who that is:

```
GET /localapi/v0/whois?addr=100.101.102.103:51234
  over the unix socket /var/run/tailscale/tailscaled.sock
→ {"UserProfile": {"LoginName": "matt.ballance@gmail.com", ...},
   "Node": {"Name": "laptop.perch-char.ts.net.", "Tags": null, ...}}
```

Checked on a9550 (2026-10-23, Tailscale 1.102.2): the socket is mode
`0666`, and both `whois` and `status` answer a non-root caller.

### 2.1 How a request is checked

On every request, in middleware ahead of all routes:

1. **Which listener.** On the loopback listener (§2.2), allow and go to §4.
2. **Who.** Call `whois` with the peer address and port. Cache the answer
   for the connection, with a TTL of 60 s per peer IP.
3. **Refuse** with 403 if `whois` fails (not a tailnet address), if the
   node is tagged (tagged nodes have no user), or if `LoginName` is not in
   `allow`.
4. **Record** the login name on the request (`request.state.user`) so
   actions can journal it.

A failed `whois` is cached for only 5 s, so a device that has just joined
is not shut out for a minute.

`allow` defaults to the owner of this node: `Self.UserID` from
`/localapi/v0/status`, mapped to its login name. That is "the user who
started it" in tailnet terms: whoever's tailnet account this machine is
on. List more logins only to share the board on purpose.

This mode needs no passwords, no login page and no session cookie. Every
request carries its identity, so there is nothing to steal from the
browser. It does not cover the browser-side attacks in §4.

### 2.2 Listeners

wpkd listens on two sockets, both on port 7878 by default:

- **`127.0.0.1:7878`**: same as today, no identity check. Only processes
  on this machine can reach it, and on a single-user machine those are
  yours. On a shared machine, set `loopback = false`, or another local
  user could reach the board. A request carrying proxy headers
  (`Forwarded`, `X-Forwarded-*`, `X-Real-IP`, `Via`, any `Tailscale-*`) is
  refused here: it means something like `tailscale serve` forwarded it from
  off the machine, and the identity check would be skipped.
- **`<tailnet IPv4>:7878`** (and the IPv6 address), from `status`'s
  `TailscaleIPs`. Not `0.0.0.0`: the LAN never sees the port.

At boot `tailscaled` may not be up yet, and a user unit cannot order
itself after a system unit. So wpkd retries the tailnet bind every 5 s and
logs once while it waits. If the tailnet IP changes (rare), it rebinds.

Unlike `tailscale serve`, this involves no proxy and no change to the
node's serve config. Your existing `:443 → 127.0.0.1:3000` serve config
on a9550 stays as it is.

### 2.3 TLS

WireGuard already encrypts the traffic, so plain HTTP over the tailnet is
not readable on the wire. Because §2 needs no cookies, it does not need a
browser "secure context" either. TLS is optional, and the default is
`tls = "off"` on the tailnet listener.

`tls = "tailscale"` gives a real certificate for
`<host>.<tailnet>.ts.net` with no browser warning:

- Tailscale only issues certificates to root or the configured operator.
  Once: `sudo tailscale set --operator=$USER`. After that wpkd fetches and
  renews through LocalAPI (`/localapi/v0/cert/<domain>?type=pair`), keeps
  the files in `$WPK_HOME/tls/`, and reloads them before they expire
  (they last 90 days; renew at 30 left).
- The name is already in public certificate-transparency logs on a9550,
  since the existing `serve :443` has one.
- With TLS on, the Host check (§4) accepts the `ts.net` name, and the URL
  becomes `https://a9550.perch-char.ts.net:7878/`.

## 3. Other modes

**On a corporate network without Tailscale, see `docs/unix-login.md`:**
`auth = "unix"` with `listen = "network"` serves the board over HTTPS on
every address, and you sign in by running `wpk login CODE` in any shell on
the cluster. Built 2026-10-27; it replaces the need for `token` and `pam`
below in that setting.

These are for machines without Tailscale, and to keep a way in when
Tailscale is down. They share the cookie session below. They are
**S3 in the build plan, not needed for a9550**.

| `auth` | How you prove it is you | Notes |
|---|---|---|
| `tailscale` | §2 | Default when `tailscaled.sock` answers |
| `token` | `wpk url` prints `http://…/login?t=<token>`; the token is in `$WPK_HOME/server.token` (0600) | The Jupyter model: reading the file proves you are the user. One-time link; it sets a session cookie |
| `pam` | Your Unix password on a login form, checked through PAM service `login` with the username fixed to the daemon's own user | No root: `pam_unix` runs `/sbin/unix_chkpwd` (setgid `shadow`), which checks the caller's *own* password only. Fails on accounts with no password (key-only VMs). Needs `python-pam` |
| `none` | Nothing | Allowed only when every listener is loopback |

Rules for `token` and `pam`:

- **TLS is required** on any listener that is not loopback: wpkd refuses to
  start without it. Use your own `cert`/`key`, or `tls = "self-signed"`
  (made on first start; its SHA-256 fingerprint is logged and printed by
  `wpk url` so you can check the browser warning).
- **Session cookie**: random 256-bit ID, server-side table, `HttpOnly;
  Secure; SameSite=Strict; Path=/`, 12 h idle and 7 days total. `wpk
  logout --all` clears the table.
- **Rate limit**: 5 failed logins per minute per address, then 429.
  `unix_chkpwd` adds its own delay.

## 4. CSRF and DNS rebinding

Tailscale identity is *ambient*. Any request from your laptop carries it,
including one sent by a hostile web page open in your laptop's browser.
The same is true of a cookie. Two attacks, two checks, on every listener:

- **DNS rebinding**: a hostile name resolves to 100.x or 127.0.0.1, and
  the page then reads the board as same-origin. **Host check**: the `Host`
  header must be one of: `localhost`, `127.0.0.1`, the tailnet IPs, the
  MagicDNS short name (`a9550`), the FQDN (`a9550.perch-char.ts.net`), and
  `extra_hosts` from config, each with the right port. Anything else gets
  421. This covers GETs too, so the board cannot be read cross-site.
- **CSRF**: a hostile page posts a form to the board. On every
  non-GET request:
  - `Origin` must be present and match an allowed host from the list
    above, otherwise 403. Browsers send `Origin` on every POST.
  - A `csrf` form field or `X-CSRF-Token` header must equal
    `HMAC(server_secret, "csrf")`. The server puts it in every page; a
    page from another origin cannot read it.
- GET routes never change state. This is already true, and a test keeps
  it true.
- Responses carry `X-Frame-Options: DENY` and a strict
  `Content-Security-Policy` (`default-src 'self'`; htmx is vendored, so no
  CDN is needed).

The CLI never goes through HTTP. It reads and writes the files, and pokes
the runner (§5).

## 5. One daemon

`wpkd` (the same as `wpk serve`) runs both:

- **the runner loop** from long-running.md §4, unchanged: lock, poke,
  limits, events, SIGTERM;
- **the board**: the Starlette app from `wpk dash` behind the §2–§4
  middleware, under uvicorn, in the same asyncio loop. The runner's steps
  are subprocesses, so a busy board never delays one.

Why one process:

- one `runner.lock`, one unit, one place for config and logs;
- board actions poke the runner in-process, with no file-mtime round
  trip;
- live updates (SSE, Stage 2) come from the runner's own event stream,
  not from tailing `events.jsonl`.

What stays separate:

- `wpk runner` runs the loop without a board (headless machines, tests).
- `wpk dash` serves the board without a runner, on loopback only, with no
  auth (today's behaviour, for looking at a home that is not yours to run).
- If wpkd is running, `wpk runner` exits on the lock as before. `wpk dash`
  can still run alongside on another port.

The unit replaces the two units in long-running.md §4:

```ini
# ~/.config/systemd/user/wpkd.service
[Unit]
Description=work-packet daemon (runner + board)
[Service]
ExecStart=%h/.local/bin/wpk serve
Restart=on-failure
TimeoutStopSec=35min
[Install]
WantedBy=default.target
```

On SIGTERM the board stops accepting connections at once, and the runner
does what §4 says (wait for steps).

## 6. Config and commands

In `$WPK_HOME/config.toml`:

```toml
[server]
port     = 7878
loopback = true              # listen on 127.0.0.1, no identity check
tailnet  = false             # also listen on this node's tailnet addresses (opt in)
auth     = "tailscale"       # tailscale | token | pam | none
allow    = []                # tailnet logins; empty = this node's owner
tls      = "off"             # off | tailscale | self-signed | {cert=…, key=…}
extra_hosts = []             # more Host names to accept (e.g. a CNAME)
listen   = ""                # "unix": $WPK_HOME/run/wpkd.sock (dir 0700) instead of 127.0.0.1
```

`listen = "unix"` is for a shared host such as a login node, where a TCP
port on 127.0.0.1 is open to every user there (docs/scheduler.md §7.1).
The board is then reached with `ssh -N -L 7878:$WPK_HOME/run/wpkd.sock
you@login` from the laptop; `wpk url` prints the line. The Guard treats
the socket like loopback (no identity check: only you can open it) and
keeps the Host, Origin and CSRF checks; any port is accepted with a
loopback Host name, since it is the laptop's.

| Command | Does |
|---|---|
| `wpk dash [--tailnet] [--port N] [--host ADDR]` | The board alone (S1, built). `--tailnet` overrides `[server] tailnet`; `--host` replaces both listeners with one, identity-checked unless loopback |
| `wpk url` | Prints the running board's URLs (built); with `auth = "token"`, a fresh login link (S3) |
| `wpk serve [-j N] [--detach] [--ensure]` | The daemon (§5): board and scheduler (built with the scheduler, docs/scheduler-plan.md Q4.6). `--detach` starts it in the background, log in `$WPK_HOME/log/wpkd.log`; `--ensure` does that only if no wpkd holds `wpkd.lease` (for cron on a login node) |
| `wpk serve --install-unit` | Writes `wpkd.service`; prints the `enable-linger` and `systemctl --user enable --now` lines (S2) |
| `wpk logout --all` | Clears sessions (token and pam modes, S3) |

New files in `$WPK_HOME`: `server.secret` (0600, CSRF HMAC key, made on
first start), `server.token` (token mode), `tls/` (certificates), and
`server.json` (pid, listeners, URLs; written at start, read by `wpk url`).

## 7. Build plan

Order relative to long-running.md §11: **S1 can start now**, against the
read-only board; it does not depend on L1 or L2. S2 follows L3. L4's POST
actions are built on S1's middleware.

```
S1 (now) ──► L1 ──► L2 ──► L3 ──► S2 ──► L4
                                         S3 (when needed)
```

### S1: The board on the tailnet

- [x] `dash/tailscale.py`: LocalAPI client (unix socket, `whois`, `status`),
      with a per-peer cache.
- [x] `dash/guard.py`: identity check per listener (§2.1), Host check,
      proxy-header refusal on loopback, Origin and CSRF check on non-GET
      requests, security headers (§4). The board's refresh script moved
      to `/static/live.js` so the CSP needs no inline script.
- [x] `dash/server.py`: two listeners (loopback, tailnet), each its own
      uvicorn server and `Guard` in one loop; retry while tailscaled is
      not up; rebind on address change; `server.json`, `server.secret`.
- [x] `[server]` config (validated); `wpk dash --tailnet`; `wpk url`.
      The board shows who you are signed in as.

### S1b: Tailscale TLS

- [x] `tls = "tailscale"`: fetch, store, renew (§2.3), in
      `dash/tls.py` (built with docs/vscode-plan.md V4; tests in
      `tests/test_tls.py`). Not tried live yet: needs
      `sudo tailscale set --operator=$USER` once.
- Tests: a fake `tailscaled` LocalAPI on a unix socket in a temp dir
  (`whois` table and `status`) via `WPK_TAILSCALE_SOCKET`. Allowed login
  → 200; another login, a tagged node, or an unknown address → 403;
  tailscaled down → 403 on the tailnet listener and 200 on loopback; bad
  Host → 421; POST with no or a wrong Origin or token → 403; every GET
  route leaves the home byte-identical.
- Live check on a9550: open the board from another tailnet device; a
  device signed in to another tailnet login is refused.

`tests/test_server.py` (38 tests) has all of the above except the
refused-login half of the live check, plus a subprocess test of `wpk dash
--tailnet` with 127.0.0.2 standing in for the tailnet address.

### S2: One daemon

- [x] `wpk serve` runs the scheduler and the board in one process;
      in-process poke; SIGTERM order (§5). (docs/scheduler-plan.md Q4.6)
- [ ] `--install-unit`; long-running.md §4 points here for units.
- Tests: the L3 runner tests pass under `wpk serve`; `wpk runner` beside
  `wpk serve` exits on the lock; SIGTERM closes listeners at once and
  waits for a running fake step.

### S3: Without Tailscale (when needed)

- [ ] Sessions, `token` mode, `wpk url` login link, `wpk logout`.
- [ ] `pam` mode (optional extra `pam`), rate limit.
- [ ] `self-signed` and file TLS; refuse non-loopback without TLS.
- Tests: link works once; expired or cleared session → login page; cookie
  flags; 6th bad password in a minute → 429; PAM through a stub (no real
  password in tests).

## Open questions

- **Read-only sharing.** Should a second `allow` list (`viewers`) see the
  board but get 403 on every POST? Cheap to add in S1 if wanted.
- **Phones.** On the tailnet, a phone counts as one of your devices, so
  the board works as-is. Is a layout for small screens wanted before L4?

## Status log

### 2026-10-23: design

Written after the user asked for a daemon with a board reachable without a
proxy and a login as the launching user, without root. The user is on
Tailscale and the tailnet is private, so Tailscale identity is the main
mode, and token/PAM are kept for later (S3). Checked on a9550: LocalAPI
`whois` and `status` answer a non-root caller over the 0666 socket; the
node's owner is `matt.ballance@gmail.com`; `/sbin/unix_chkpwd` is setgid
`shadow` and the account has a password (so PAM is possible later). Not
built.

### 2026-10-23: S1 built

Changes from the design above: S1 is `wpk dash --tailnet`, not `wpk serve
--no-runner` (`wpk serve` arrives with the runner in S2); `tailnet` is off
by default, so nothing new listens until you ask; TLS moved to S1b; the
`whoami-check` command was dropped; loopback refuses proxied requests
(§2.2). Full suite: 331 passed, 4 skipped.

Live on a9550 (port 7879): `wpk url` listed loopback, MagicDNS, FQDN, IPv4
and IPv6 URLs; this machine's own tailnet IPv4 and IPv6 addresses and the
FQDN gave 200, with `matt.ballance@gmail.com` shown on the page; a
rebinding Host gave 421; a POST with a foreign Origin, and one with the
right Origin but no token, gave 403; SIGTERM exited 0 and removed
`server.json`; `server.secret` is 0600. Not yet tried: a second device,
and a device on another login (should be 403). On a9550 itself, `a9550`
resolves to 127.0.1.1 through `/etc/hosts`, so use the FQDN there; other
devices get the tailnet address from MagicDNS.

### 2026-10-25: part of S2 through dash-tasks.md T1

`wpk dash --run` (or `[server] run = true`) runs the scheduler in the
board's process, poked by every board action, with `runner.lock` for one
per home and SIGTERM waiting for running steps (docs/dash-tasks.md §7).
Still open from S2: the `wpk serve` name and `--install-unit`.

### 2026-10-26: `wpk serve` and `listen = "unix"` (scheduler Q4.6)

`wpk serve` is built: `wpk dash --run` under the daemon's name, with
`--detach` and `--ensure`. One per home is now `$WPK_HOME/wpkd.lease`
(host, PID, expiry; refreshed every 30 s, 90 s TTL) instead of the
`runner.lock` flock, so it holds across login nodes that share the home.
`[server] listen = "unix"` serves the board on `run/wpkd.sock`. Still
open: `--install-unit`.
