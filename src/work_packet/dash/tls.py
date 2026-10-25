"""Tailscale certificates for the tailnet listener (server.md §2.3, S1b).

tailscaled issues a Let's Encrypt certificate for ``<host>.<tailnet>.ts.net``
through its LocalAPI to root or the configured operator (once:
``sudo tailscale set --operator=$USER``). wpkd keeps the pair in
``$WPK_HOME/tls/`` (0700; the key 0600) and fetches a new one when the one it
has ends within ``RENEW_DAYS``.

Web VS Code needs this: browsers give service workers and the clipboard only
to ``https://`` pages and ``localhost`` (docs/vscode-plan.md §4.3).
"""

import http.client
import os
import ssl
import time

from .. import fsutil
from . import tailscale

RENEW_DAYS = 30
OPERATOR_FIX = "sudo tailscale set --operator=$USER"


class TlsError(Exception):
    pass


def tls_dir(home):
    return os.path.join(home, "tls")


def paths(home, domain):
    d = tls_dir(home)
    return os.path.join(d, domain + ".crt"), os.path.join(d, domain + ".key")


def domain(tailnet):
    """The name the certificate is for: the node's first cert domain."""
    st = tailnet.status(fresh=True) or {}
    ds = st.get("CertDomains") or []
    if not ds:
        raise TlsError("this tailnet has no HTTPS certificates: turn on MagicDNS and "
                       "HTTPS in the Tailscale admin console (DNS page)")
    return ds[0]


def _get_raw(path, sock=None, timeout=120):
    conn = tailscale._UnixConnection(sock or tailscale.socket_path(), timeout)
    try:
        conn.request("GET", path, headers={"Sec-Tailscale": "localapi"})
        r = conn.getresponse()
        return r.status, r.read()
    except (OSError, http.client.HTTPException) as e:
        raise TlsError("tailscaled: %s" % e) from None
    finally:
        conn.close()


def split_pair(body):
    """``(cert PEM, key PEM)`` from LocalAPI's ``type=pair`` answer (both, either order)."""
    text = body.decode("ascii", "replace")
    certs, key = [], None
    for block in text.split("-----END "):
        start = block.find("-----BEGIN ")
        if start < 0:
            continue
        kind = block[start + 11:].split("-----", 1)[0]
        pem = block[start:] + "-----END " + kind + "-----\n"
        if kind == "CERTIFICATE":
            certs.append(pem)
        elif kind.endswith("PRIVATE KEY"):
            key = pem
    if not certs or key is None:
        raise TlsError("tailscaled answered without a certificate and key")
    return "".join(certs), key


def not_after(cert_path):
    """When the certificate ends, as a Unix time (0 if it cannot be read)."""
    try:
        info = ssl._ssl._test_decode_cert(cert_path)        # noqa: SLF001: stdlib, no deps
        return float(ssl.cert_time_to_seconds(info["notAfter"]))
    except (OSError, ValueError, KeyError, TypeError, ssl.SSLError):
        return 0.0


def fetch(home, name, sock=None):
    """Fetch and store the pair for ``name``; ``(cert path, key path)``."""
    status, body = _get_raw("/localapi/v0/cert/%s?type=pair" % name, sock)
    if status == 403:
        raise TlsError("tailscaled gives certificates only to root or its operator; "
                       "run once: %s" % OPERATOR_FIX)
    if status != 200:
        raise TlsError("tailscaled: HTTP %d: %s" % (status, body[:200].decode("ascii",
                                                                              "replace")))
    cert, key = split_pair(body)
    d = tls_dir(home)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    cp, kp = paths(home, name)
    fsutil.atomic_write(kp, key)
    os.chmod(kp, 0o600)
    fsutil.atomic_write(cp, cert)
    return cp, kp


def ensure(home, name, sock=None, now=None):
    """The stored pair, fetched first if missing or ending within RENEW_DAYS.
    ``(cert path, key path, fetched now)``."""
    now = time.time() if now is None else now
    cp, kp = paths(home, name)
    if os.path.exists(cp) and os.path.exists(kp) and \
            not_after(cp) - now > RENEW_DAYS * 86400:
        return cp, kp, False
    try:
        cp, kp = fetch(home, name, sock)
    except TlsError:
        if os.path.exists(cp) and os.path.exists(kp) and not_after(cp) > now:
            return cp, kp, False     # renewal failed, but the old one still works
        raise
    return cp, kp, True


def context(cert, key):
    """Check that the pair loads (uvicorn builds its own context from the files)."""
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    try:
        ctx.load_cert_chain(cert, key)
    except (OSError, ssl.SSLError) as e:
        raise TlsError("%s: %s" % (cert, e)) from None
    return ctx
