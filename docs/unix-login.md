# Unix login: the board over HTTPS on a corporate network

Status (2026-10-27): built (U1 to U7); see the status log.
A fresh session should be able to pick up from this file alone.

## Why

On a corporate VPN there is no Tailscale, and the only way in today is
`listen = "unix"` plus `ssh -N -L …` from the laptop (server.md §6). That
needs a second shell that stays open, and colleagues will not run one. This
mode serves the board directly over HTTPS on the host. To sign in, you prove
in a shell you already have that you are a Unix user on the cluster.

Threat model: everyone is on the VPN, so outsiders are not the concern.
Other internal users are. The board is a shell on the owner's account
(server.md §1).

## How you sign in

1. Open `https://login07.corp.example:7878/`. Without a session, every page
   redirects to `/login`. That page shows a code, and the command to run:

   ```
   wpk login K7QF-29XA                                  # with wpk installed
   touch /home/matt/.wpk/login/K7QF-29XA                # without wpk
   ```

2. Run it in any shell on any host that shares the board's home (NFS) or on
   the board's own host.
3. The login page refreshes every 2 s. When the file appears, the server
   checks who owns it, sets a session cookie and sends you on to the page
   you asked for.

### How the drop file proves who you are

`$WPK_HOME/login/` has mode `1733`: anyone can create a file there, nobody
but the owner can list it, and the sticky bit means nobody can rename or
delete anyone else's file. To accept the drop file for code C, the server
checks that:

- `login/C` is a regular file (checked with `lstat`, so no symlinks), with
  exactly one link (`st_nlink == 1`, so it is not a hard link to someone
  else's file);
- C is a code this server issued less than 10 minutes ago, and has not been
  used yet;
- the file's owner uid maps to a user who may sign in (below).

The server then deletes the file. Codes are 8 characters from a 30-letter alphabet (about 39 bits), and since nobody
else can list the directory, nobody can see someone else's pending code.

The file's owner is set by the kernel, or by the NFS server under
root-squash. A user can't fake it unless they have root on an NFS client
without root-squash, and that person could become anyone anyway.

Colleagues need `o+x` on every directory down to `$WPK_HOME/login/`. If
your home is `0700`, nobody else can sign in at all, whatever `allow` says.
`wpk url` says when this is the case.

### Who gets in

- **The home's owner** (`authz.home_owner`): the full board.
- **Names in `[server] allow`**: read-only. Every request that is not
  GET/HEAD/OPTIONS gets a 403, and so do WebSockets (the browser shell) and
  `/ide/`. Today, POST routes are what change things, and the browser shell
  and `/ide/` are shells on the owner's account.
- Everyone else: refused at sign-in, and again on every request. The cookie
  is checked against `allow` each time, so removing a name from `allow`
  takes effect on that person's next request.

`allow = []` (the default) means only the owner.

### Sessions

The session is a signed cookie, `wpk_s_<port>`, containing
`<user>.<expiry>.<hmac>` with a key derived from `server.secret`. The cookie
is `Secure; HttpOnly; SameSite=Lax; Path=/` (Lax so a link from chat or mail still arrives signed in; POSTs are covered by Origin and CSRF). It lasts
`session_days` (default 30) and survives restarts. `POST /logout` clears it.
The port is part of the name because browsers share cookies for a host
across all of its ports.

Pending codes are kept in memory only, and are lost when the board
restarts. The browser that started a sign-in holds a cookie (`wpk_l_<port>`)
with a nonce, and the code is tied to that nonce. Someone else's browser
cannot pick up the session even if they see the code.

The CSRF token is per user on this listener (`hmac(secret, "csrf|" + user)`),
so a read-only colleague never sees the owner's token.

### TLS is required

A session cookie sent over plain HTTP on the VPN could be copied by anyone
in the right place, so the network listener refuses `tls = "off"`:

- `tls = "self-signed"`: wpkd makes a certificate for this host's names and
  addresses with `openssl`, stored in `$WPK_HOME/tls/self-signed.{crt,key}`.
  Each browser clicks through a warning once.
- `tls = "files"` with `tls_cert` and `tls_key`: your own certificate, e.g.
  from the corporate CA (no warning).

## Config

```toml
[server]
listen   = "network"        # all addresses (0.0.0.0 and ::), port 7878
auth     = "unix"
tls      = "self-signed"    # or "files" + tls_cert / tls_key
allow    = []               # Unix names given read-only access; [] = only you
session_days = 30
```

`wpk dash --host 10.1.2.3` with `auth = "unix"` serves on that one address.

## Not done (later)

- Confirming before `wpk login` approves a code: showing which browser
  (IP address, user agent) you are about to sign in, against phishing.
- Revoking every session (a rotating session key).
- Write access for names other than the owner.
- Kerberos/SPNEGO or corporate SSO as another `auth` that creates the same
  session.

## Build plan

- [x] U1 schema: `auth = "unix"`, `listen = "network"`, `tls = "self-signed" | "files"`,
      `tls_cert`, `tls_key`, `session_days`; validation (the network listener needs auth
      unix and TLS)
- [x] U2 `dash/login.py`: codes, the drop directory, checking drop files, signing cookies
- [x] U3 Guard kind `network`: session check, login routes, read-only for those who are
      not the owner, per-user CSRF
- [x] U4 server: bind all addresses with TLS; self-signed certificate; Host names; URLs in
      server.json
- [x] U5 CLI: `wpk login CODE [--home]`; `wpk url` hints
- [x] U6 tests; docs/server.md pointer
- [x] U7 live check on this machine

## Status log

### 2026-10-27: design

Written after the user said they wanted no tunnel and colleagues on a
corporate VPN. The earlier proposal also had a unix socket checked with
`SO_PEERCRED` for logins from the same node. It was dropped because the drop
file covers both the same node and other nodes.

### 2026-10-27: built

Files: `src/work_packet/dash/login.py` (codes, drop files, cookies, the
`Gate` and its login page), the `network` kind in `dash/guard.py`,
`Board._start_network` and `host_names` in `dash/server.py`,
`tls.self_signed`, `wpk login`, hints in `wpk url`, a sign-out button in
`base.html`; tests in `tests/test_unix_login.py`.

Changes from the design: the drop file only has to exist (`touch` is
enough). `lstat` and `nlink == 1` are the checks, and checking the contents
would break for users whose umask is 077. The cookie is `SameSite=Lax`, not
Strict, so a link from chat still arrives signed in. With
`listen = "network"` there is no separate loopback listener: `0.0.0.0`
covers it, and local users have to sign in as well.

Live on a9550 (port 7899, scratch home): signed out, `/p/x` gave 303 to
`/login?next=/p/x`. `wpk login CODE` signed in the curl session (303, then
200 with the sign-out form). No cookie gave 303. A foreign Host gave 421.
Plain http did not connect. The certificate's SAN listed the host name and
every address. `login/` was 1733 and the key 0600, and SIGTERM stopped it
cleanly.

Not tried: a second Unix user (needs a colleague's account), NFS
attribute-cache delay across login nodes, and a browser click-through of
the self-signed certificate.
