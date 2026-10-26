"""``wpkd.lease``: one wpkd per home, across hosts (docs/scheduler.md §7.1).

A ``flock`` only works on one host; login nodes share ``$WPK_HOME`` over
NFS. The lease is a file made with ``O_EXCL`` naming host, PID and an
expiry 90 s ahead, refreshed every 30 s. Another wpkd may take it only
once it has expired, or at once if it names a dead PID on its own host.
"""

import json
import os
import socket
import threading
import time

from .. import clock, fsutil, registry, schema

TTL_S = 90
REFRESH_S = 30


class HomeBusy(Exception):
    def __init__(self, holder, path):
        super().__init__("wpkd is already running for this home: host %s, pid %s, since %s "
                         "(%s)" % (holder.get("host"), holder.get("pid"), holder.get("started"),
                                   path))
        self.holder = holder


def path(h=None):
    return os.path.join(h or registry.home(), "wpkd.lease")


def read(h=None):
    try:
        with open(path(h)) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}


def stale(d, now=None):
    now = now or clock.real_now()
    try:
        if schema.parse_timestamp(d["expires"]) <= now:
            return True
    except (KeyError, TypeError, ValueError):
        return True
    if d.get("host") == socket.gethostname():
        try:
            os.kill(int(d["pid"]), 0)
        except ProcessLookupError:
            return True
        except (PermissionError, KeyError, TypeError, ValueError):
            pass
    return False


def live(h=None):
    """The holder of a live lease, or None."""
    d = read(h)
    return d if d and not stale(d) else None


class HomeLease:
    def __init__(self, h=None):
        self.h = h or registry.home()
        self.path = path(self.h)
        self._stop = threading.Event()
        self._thread = None
        self.mine = None

    def _record(self, started=None):
        now = clock.real_now()
        from datetime import timedelta
        return {"host": socket.gethostname(), "pid": os.getpid(),
                "started": started or schema.format_timestamp(now),
                "expires": schema.format_timestamp(now + timedelta(seconds=TTL_S))}

    def acquire(self):
        os.makedirs(self.h, exist_ok=True)
        for _ in range(3):
            rec = self._record()
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                held = read(self.h)
                if held and not stale(held):
                    raise HomeBusy(held, self.path) from None
                # Expired or dead: take it. A rename over it is atomic, and the
                # read-back below catches a race with another taker.
                fsutil.atomic_write(self.path, json.dumps(rec) + "\n")
            else:
                with os.fdopen(fd, "w") as fp:
                    fp.write(json.dumps(rec) + "\n")
            time.sleep(0.05)
            got = read(self.h) or {}
            if (got.get("host"), got.get("pid")) == (rec["host"], rec["pid"]):
                self.mine = rec
                return self
        raise HomeBusy(read(self.h) or {}, self.path)

    def refresh(self):
        held = read(self.h) or {}
        if (held.get("host"), held.get("pid")) != (self.mine["host"], self.mine["pid"]):
            return False                       # taken over (we were too slow): stop
        self.mine = self._record(self.mine["started"])
        fsutil.atomic_write(self.path, json.dumps(self.mine) + "\n")
        return True

    def start_refresher(self, on_lost=None):
        def loop():
            while not self._stop.wait(REFRESH_S):
                try:
                    if not self.refresh():
                        if on_lost:
                            on_lost()
                        return
                except OSError:
                    pass
        self._thread = threading.Thread(target=loop, name="wpkd-lease", daemon=True)
        self._thread.start()

    def release(self):
        self._stop.set()
        held = read(self.h) or {}
        if self.mine and (held.get("host"), held.get("pid")) == (self.mine["host"],
                                                                  self.mine["pid"]):
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass
        self.mine = None
