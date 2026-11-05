"""What an IDE job runs (plan Q5.2): start VS Code's server, publish where it
is once it is up, and wait. SIGTERM (the job cancelled, the IDE idle) stops it.

``python -m work_packet.sched.ide_job <server dir> [--transport T] [--launch ID [--collect S]] -- <server argv>``

``tcp-token`` (the default): the server listens on a free TCP port (``{port}``
in the argv is replaced by it); ``host:port`` goes to ``<server dir>/endpoint``.
The port is plaintext, so use it only on clusters where that is acceptable.

``mtls`` (docs/scheduler.md §8.1): the server listens on a **unix socket** in a
private directory on the node's local disk (``{sock}`` in the argv), and
``ide_relay`` listens on the TCP port with TLS 1.3 and a required client
certificate: only wpkd's (``<server dir>/client.crt``) is accepted. The job's
key stays on the node; ``server.crt``, ``fingerprint`` and, last, ``endpoint``
go to the server directory.

``--launch``: the server gets ``WPK_IDE_LAUNCH`` (``work_packet.ide_launch``),
and the launch gets this host. ``--collect S``: watch its sessions every S seconds.
"""

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

LOCAL_ONLY_BAD = ("nfs", "nfs4", "autofs", "cifs", "smb3", "lustre", "gpfs", "beegfs", "ceph",
                  "glusterfs", "afs", "9p")
SOCK_MAX = 90                # AF_UNIX paths are limited to about 104 bytes


def free_port():
    s = socket.socket()
    s.bind(("0.0.0.0", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def listening(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


def collect(home, key, lid, server, every):
    """Watch the sessions under ``server`` here, on the exec host, until it ends
    (docs/vscode-monitor-plan.md §2.4): a daemon thread, so it never holds the
    job up. Its records go to the shared home."""
    import threading
    from .. import ide_launch, ide_sessions

    def loop():
        c = None
        while True:
            done = server.poll() is not None
            try:
                if c is None:
                    rec = ide_launch.find(home, lid)
                    if rec is not None:
                        c = ide_sessions.Collector(home, rec, root=server.pid)
                if c is not None:
                    c.pass_once()
            except Exception as e:          # keep watching; say why on the job's log
                print("wpk: session watch: %s" % e, file=sys.stderr, flush=True)
            if done:
                return
            time.sleep(every)
    threading.Thread(target=loop, name="wpk-ide-sessions", daemon=True).start()


def fstype(path, mountinfo="/proc/self/mountinfo"):
    """The file system type of the mount holding ``path`` ('' if unknown)."""
    path = os.path.realpath(path)
    best, kind = -1, ""
    try:
        with open(mountinfo) as f:
            for line in f:
                left, _, right = line.partition(" - ")
                point = left.split()[4].replace("\\040", " ")
                if (path == point or path.startswith(point.rstrip("/") + "/")) and len(point) > best:
                    best, kind = len(point), right.split()[0]
    except (OSError, IndexError):
        return ""
    return kind


def local_dir(environ=None, mountinfo="/proc/self/mountinfo"):
    """A new 0700 directory on this node's local disk with a short path, for the
    server's socket and the relay's key (a socket on NFS does not cross hosts,
    and a key must not be on shared storage)."""
    environ = os.environ if environ is None else environ
    for base in (environ.get("XDG_RUNTIME_DIR"), environ.get("TMPDIR"), "/tmp", "/dev/shm"):
        if not base or not os.path.isdir(base) or not os.access(base, os.W_OK):
            continue
        if fstype(base, mountinfo) in LOCAL_ONLY_BAD:
            continue
        try:
            d = tempfile.mkdtemp(prefix="wpk-ide-", dir=base)
        except OSError:
            continue
        if len(os.path.join(d, "s")) > SOCK_MAX:
            shutil.rmtree(d, ignore_errors=True)
            continue
        os.chmod(d, 0o700)
        return d
    raise OSError("no local directory with a short enough path for the server's socket")


def _stop_group(p, sig):
    try:
        os.killpg(p.pid, sig)
    except ProcessLookupError:
        pass


def _unlink(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def run_tcp(d, rest, started):
    port = free_port()
    cmd = [a.replace("{port}", str(port)) for a in rest]
    endpoint = os.path.join(d, "endpoint")
    p = started(cmd)

    def stop(signum, frame):
        _stop_group(p, signal.SIGTERM)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while p.poll() is None and not listening(port):
            time.sleep(0.1)
        if p.poll() is None:
            tmp = endpoint + ".tmp"
            with open(tmp, "w") as fp:
                fp.write("%s:%d\n" % (socket.gethostname(), port))
            os.replace(tmp, endpoint)
        while True:
            try:
                return p.wait()
            except InterruptedError:
                continue
    finally:
        _unlink(endpoint)
        if p.poll() is None:
            _stop_group(p, signal.SIGKILL)


def run_mtls(d, rest, started):
    ld = local_dir()
    sock = os.path.join(ld, "s")
    cmd = [a.replace("{sock}", sock) for a in rest]
    server = started(cmd)
    relay = None

    def stop(signum, frame):
        _stop_group(server, signal.SIGTERM)
        if relay is not None and relay.poll() is None:
            relay.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while server.poll() is None and not os.path.exists(sock):
            time.sleep(0.1)
        if server.poll() is not None:
            return server.returncode
        relay = subprocess.Popen([sys.executable, "-m", "work_packet.sched.ide_relay", "--sock", sock,
                                  "--client-cert", os.path.join(d, "client.crt"),
                                  "--key-dir", os.path.join(ld, "key"), "--publish-dir", d],
                                 stdin=subprocess.DEVNULL)
        while server.poll() is None and relay.poll() is None:
            time.sleep(0.2)
        if relay.poll() is not None and server.poll() is None:      # the relay failed: nothing could reach the server
            _stop_group(server, signal.SIGTERM)
            return relay.returncode or 1
        return server.returncode
    finally:
        _unlink(os.path.join(d, "endpoint"), os.path.join(d, "server.crt"), os.path.join(d, "fingerprint"))
        if relay is not None and relay.poll() is None:
            relay.terminate()
            try:
                relay.wait(5)
            except subprocess.TimeoutExpired:
                relay.kill()
        if server.poll() is None:
            _stop_group(server, signal.SIGKILL)
        shutil.rmtree(ld, ignore_errors=True)


def main(argv):
    d, rest = argv[0], argv[argv.index("--") + 1:]
    opts = argv[1:argv.index("--")]
    transport = opts[opts.index("--transport") + 1] if "--transport" in opts else "tcp-token"
    lid = opts[opts.index("--launch") + 1] if "--launch" in opts else None
    home, key = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(d)))), \
        os.path.basename(os.path.abspath(d))

    def started(cmd):
        """Start the server; with ``--launch``, tell the launch and watch its sessions."""
        env = None
        if lid:
            from .. import ide_launch
            env = dict(os.environ, **ide_launch.env(lid, key))
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True, env=env)
        if lid:
            try:
                ide_launch.update(home, key, lid, host=socket.gethostname(), pid=p.pid)
            except OSError:
                pass
        if lid and "--collect" in opts:
            collect(home, key, lid, p, float(opts[opts.index("--collect") + 1]))
        return p

    if transport == "mtls":
        return run_mtls(d, rest, started)
    return run_tcp(d, rest, started)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
