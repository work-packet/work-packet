#!/usr/bin/env python3
"""A stand-in for Xvnc in tests (docs/desktop.md): ``fake_xvnc.py :M -displayfd FD
-rfbunixpath P ...``. Listens on ``$FAKE_X_DIR/X<M>`` (echoes, prefixed ``X:``) and
on ``P`` (sends an RFB banner, then echoes); writes ``M`` to ``FD`` once ready."""
import os
import signal
import socket
import sys
import threading
import time

args = sys.argv[1:]
m = int(args[0].lstrip(":"))
fd = int(args[args.index("-displayfd") + 1])
rfb = args[args.index("-rfbunixpath") + 1]
xsock = os.path.join(os.environ["FAKE_X_DIR"], "X%d" % m)
with open(os.environ["FAKE_X_DIR"] + ".argv", "a") as f:
    f.write(" ".join(args) + "\n")


def serve(path, banner, prefix):
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)
    s.listen(16)

    def one(c):
        if banner:
            c.sendall(banner)
        while True:
            d = c.recv(65536)
            if not d:
                break
            c.sendall(prefix + d)
        c.close()
    while True:
        c, _ = s.accept()
        threading.Thread(target=one, args=(c,), daemon=True).start()


def bye(*_):
    for p in (xsock, rfb):
        try:
            os.unlink(p)
        except OSError:
            pass
    os._exit(0)


signal.signal(signal.SIGTERM, bye)
for path, banner, prefix in ((xsock, None, b"X:"), (rfb, b"RFB 003.008\n", b"V:")):
    threading.Thread(target=serve, args=(path, banner, prefix), daemon=True).start()
while not (os.path.exists(xsock) and os.path.exists(rfb)):
    time.sleep(0.01)
os.write(fd, b"%d\n" % m)
os.close(fd)
signal.pause()
