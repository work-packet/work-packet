"""What an IDE job runs (plan Q5.2): start VS Code's server on a free TCP
port, write ``host:port`` to the server directory's ``endpoint`` once it
listens, and wait. SIGTERM (the job cancelled, the IDE idle) stops it.

``python -m work_packet.sched.ide_job <server dir> [--launch ID] -- <server argv>``,
where the argv's ``{port}`` is replaced by the port chosen here. ``--launch``:
the server gets ``WPK_IDE_LAUNCH`` (``work_packet.ide_launch``), and the
launch gets this host.
"""

import os
import signal
import socket
import subprocess
import sys
import time


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


def main(argv):
    d, rest = argv[0], argv[argv.index("--") + 1:]
    opts = argv[1:argv.index("--")]
    lid = opts[opts.index("--launch") + 1] if "--launch" in opts else None
    home, key = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(d)))), \
        os.path.basename(os.path.abspath(d))
    port = free_port()
    cmd = [a.replace("{port}", str(port)) for a in rest]
    endpoint = os.path.join(d, "endpoint")
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

    def stop(signum, frame):
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
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
        try:
            os.unlink(endpoint)
        except FileNotFoundError:
            pass
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
