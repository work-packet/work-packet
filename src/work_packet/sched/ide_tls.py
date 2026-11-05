"""Certificates and TLS contexts for the IDE's mTLS transport (docs/scheduler.md §8.1).

Trust is pinned in both directions and needs no CA: wpkd has one client
certificate per home (``$WPK_HOME/ide/client.{key,crt}``, 0600), and each IDE
job makes its own key on the node and publishes only its self-signed
certificate. Both public certificates travel through the user's own 0700
directory, so the peer must hold exactly that certificate. TLS 1.3 only.
"""
import hashlib
import os
import shutil
import ssl
import subprocess
import tempfile

CLIENT_DAYS = 3650           # wpkd's certificate: one per home, for as long as the home lives
SERVER_DAYS = 3              # a job's certificate: longer than any run limit, regenerated each start

_CONF = """[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = %(cn)s
[ext]
basicConstraints = critical, CA:TRUE
keyUsage = critical, digitalSignature, keyCertSign
extendedKeyUsage = serverAuth, clientAuth
"""


def openssl():
    """``/usr/bin/openssl`` first: one earlier on PATH may be old (no ``-addext``)."""
    for c in ("/usr/bin/openssl", shutil.which("openssl")):
        if c and os.access(c, os.X_OK):
            return c
    raise RuntimeError("openssl is not installed here; the mtls IDE transport needs it")


def make_cert(key_path, crt_path, days, cn):
    """A self-signed EC certificate (CA:TRUE, so it is its own trust anchor), made
    through a config file because older openssl has no ``-addext``. The key is 0600."""
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False) as f:
        f.write(_CONF % {"cn": cn})
        conf = f.name
    try:
        old = os.umask(0o077)
        try:
            subprocess.run([openssl(), "req", "-x509", "-newkey", "ec", "-pkeyopt",
                            "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", key_path,
                            "-out", crt_path, "-days", str(days), "-config", conf],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            os.umask(old)
    finally:
        os.unlink(conf)
    os.chmod(key_path, 0o600)


def fingerprint(crt_path):
    """The certificate's SHA-256 (of its DER), in hex."""
    with open(crt_path) as f:
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).hexdigest()


def client_cert(home):
    """``(key, crt)`` paths of wpkd's client certificate for ``home``, made once."""
    d = os.path.join(home, "ide")
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    key, crt = os.path.join(d, "client.key"), os.path.join(d, "client.crt")
    if not (os.path.exists(key) and os.path.exists(crt)):
        make_cert(key, crt, CLIENT_DAYS, "wpkd-ide-client")
    return key, crt


def pinned_client_context(client_crt, client_key, server_crt):
    """For wpkd: our certificate, and the job's certificate as the only trust
    anchor. The host name is not checked; the certificate is."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(client_crt, client_key)
    ctx.load_verify_locations(cafile=server_crt)
    return ctx


def pinned_server_context(server_crt, server_key, client_crt):
    """For the relay: its own certificate, and wpkd's as the only client it accepts."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(server_crt, server_key)
    ctx.load_verify_locations(cafile=client_crt)
    return ctx
