"""``.lease``: one step at a time per packet (spec §4.5)."""

import json
import os
import socket
import threading
from datetime import timedelta

from . import clock, fsutil, schema

REFRESH_S = 60


class LeaseHeld(Exception):
    """Another live process holds the packet's lease."""

    def __init__(self, lease):
        super().__init__("lease held by %s pid %s (step %s, expires %s)" % (
            lease.get("host"), lease.get("pid"), lease.get("step"), lease.get("expires")))
        self.lease = lease


def is_stale(lease, now=None):
    """True if a parsed .lease has expired or names a dead PID on this host."""
    now = now or clock.now()
    try:
        if schema.parse_timestamp(lease["expires"]) <= now:
            return True
    except (KeyError, TypeError, ValueError):
        return True
    if lease.get("host") == socket.gethostname():
        try:
            os.kill(int(lease["pid"]), 0)
        except ProcessLookupError:
            return True
        except (PermissionError, KeyError, TypeError, ValueError):
            pass
    return False


def read(path):
    """The parsed lease, {} if it is unreadable, or None if there is none."""
    try:
        with open(path) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}


class Lease:
    """A lease this process holds. ``ttl_s`` bounds how long it outlives us."""

    def __init__(self, path, step, attempt, ttl_s):
        self.path = path
        self.step = step
        self.attempt = attempt
        self.ttl_s = ttl_s
        self.broken = None           # the stale lease that acquire() removed
        self._stop = None
        self._thread = None

    def _record(self):
        return {"host": socket.gethostname(), "pid": os.getpid(), "step": self.step,
                "attempt": self.attempt,
                "expires": schema.format_timestamp(clock.now() + timedelta(seconds=self.ttl_s))}

    def acquire(self):
        """Create the lease, breaking a stale one. Raises LeaseHeld."""
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                old = read(self.path)
                if old is None:
                    continue
                if not is_stale(old):
                    raise LeaseHeld(old)
                self.broken = old
                os.unlink(self.path)
                continue
            with os.fdopen(fd, "w") as fp:
                json.dump(self._record(), fp)
                fp.flush()
                os.fsync(fp.fileno())
            fsutil.fsync_dir(os.path.dirname(self.path))
            return self
        raise LeaseHeld(read(self.path) or {})

    def refresh(self, step=None, attempt=None):
        if step is not None:
            self.step = step
        if attempt is not None:
            self.attempt = attempt
        fsutil.atomic_write(self.path, json.dumps(self._record()))

    def start_refresher(self, interval_s=REFRESH_S):
        self._stop = threading.Event()

        def loop():
            while not self._stop.wait(interval_s):
                try:
                    self.refresh()
                except OSError:
                    pass
        self._thread = threading.Thread(target=loop, name="wpk-lease", daemon=True)
        self._thread.start()

    def stop_refresher(self):
        if self._thread is not None:
            self._stop.set()
            self._thread.join()
            self._thread = None

    def release(self):
        self.stop_refresher()
        cur = read(self.path)
        if cur is not None and cur.get("pid") == os.getpid() \
                and cur.get("host") == socket.gethostname():
            os.unlink(self.path)
            fsutil.fsync_dir(os.path.dirname(self.path))
