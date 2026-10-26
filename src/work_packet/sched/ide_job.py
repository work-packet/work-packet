"""What an IDE job runs (plan Q5.2): start VS Code's server on a free TCP
port, write ``host:port`` to the server directory's ``endpoint`` once it
listens, and wait. SIGTERM (the job cancelled, the IDE idle) stops it.

``python -m work_packet.sched.ide_job <server dir> -- <server argv>``, where
the argv's ``{port}`` is replaced by the port chosen here.
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


def main(argv):
    d, rest = argv[0], argv[argv.index("--") + 1:]
    port = free_port()
    cmd = [a.replace("{port}", str(port)) for a in rest]
    endpoint = os.path.join(d, "endpoint")
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True)

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
