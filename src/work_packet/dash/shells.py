"""Shells in the browser: pty sessions the server owns (docs/dash-tasks.md §5).

A session outlives its WebSocket: a reload or a dropped connection reattaches
and gets the recent output again. It ends when the shell exits, after
``IDLE_S`` with nothing attached, on a hand-off of its project, or when the
server stops. Everything here runs on the server's event loop, except
``close``, which may be called from any thread.

The rc file's ``PROMPT_COMMAND`` prints ``RECHECK`` after each command. The
session strips it from the output and tells the page, which reloads its
Checks panel.
"""

import asyncio
import errno
import fcntl
import logging
import os
import pty
import secrets
import signal
import struct
import termios
import time

from .. import clock, schema

log = logging.getLogger("wpk.shells")

MAX_SESSIONS = 8
IDLE_S = 30 * 60            # with no socket attached
BUFFER = 256 * 1024         # output kept for a reattach
KILL_AFTER_S = 5            # SIGHUP, then SIGKILL
RECHECK = b"\x1b]7777;wpk-recheck\x07"
HOOK = r"printf '\033]7777;wpk-recheck\007'"


class ShellError(Exception):
    pass


class Session:
    def __init__(self, sid, project, cwd, by, pid, fd):
        self.sid, self.project, self.cwd, self.by = sid, project, cwd, by
        self.pid, self.fd = pid, fd
        self.started = clock.now()
        self.buf = bytearray()
        self.tail = b""              # a split RECHECK sequence, held back
        self.queue = None            # the attached socket's outbox
        self.detached_at = time.monotonic()
        self.exit = None

    def info(self):
        return {"sid": self.sid, "project": self.project, "cwd": self.cwd, "by": self.by,
                "started": schema.format_timestamp(self.started),
                "attached": self.queue is not None}


class Shells:
    def __init__(self, max_sessions=MAX_SESSIONS, idle_s=IDLE_S, log_path=None):
        self.max_sessions, self.idle_s, self.log_path = max_sessions, idle_s, log_path
        self.sessions = {}
        self.loop = None
        self._reaper = None

    # -- queries (any thread) ---------------------------------------------------

    def of_project(self, project):
        return [s.info() for s in list(self.sessions.values()) if s.project == project]

    def get(self, sid):
        return self.sessions.get(sid)

    # -- life ---------------------------------------------------------------------

    def open(self, project, argv, cwd, env, by, log_path=None):
        """Start ``argv`` on a new pty. Call on the event loop."""
        if len(self.sessions) >= self.max_sessions:
            raise ShellError("%d shells are open already; close one first" % self.max_sessions)
        self.loop = asyncio.get_running_loop()
        if self._reaper is None:
            self._reaper = self.loop.create_task(self._reap())
        pid, fd = pty.fork()
        if pid == 0:                                   # the child: never returns
            try:
                os.chdir(cwd)
                os.execvpe(argv[0], argv, env)
            except BaseException as e:
                os.write(2, ("wpk: cannot start %s: %s\n" % (argv[0], e)).encode())
            os._exit(127)
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
        s = Session(secrets.token_urlsafe(12), project, cwd, by, pid, fd)
        self.sessions[s.sid] = s
        self.loop.add_reader(fd, self._readable, s)
        path = log_path or self.log_path
        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8") as fp:
                    fp.write("%s open %s by %s in %s\n" % (
                        schema.format_timestamp(s.started), s.sid, by, cwd))
            except OSError:
                pass
        return s

    def close(self, sid):
        """SIGHUP the shell's process group, SIGKILL after a while. Any thread."""
        s = self.sessions.get(sid)
        if s is None:
            return False
        for sig in (signal.SIGHUP, signal.SIGCONT):
            try:
                os.killpg(s.pid, sig)
            except OSError:
                pass

        def kill():
            if s.exit is None:
                try:
                    os.killpg(s.pid, signal.SIGKILL)
                except OSError:
                    pass
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.call_later, KILL_AFTER_S, kill)
        return True

    def close_project(self, project):
        n = 0
        for s in list(self.sessions.values()):
            if s.project == project and self.close(s.sid):
                n += 1
        return n

    def shutdown(self):
        for sid in list(self.sessions):
            self.close(sid)
        if self._reaper is not None:
            self._reaper.cancel()

    async def _reap(self):
        while True:
            await asyncio.sleep(min(30, max(1, self.idle_s / 4)))
            now = time.monotonic()
            for s in list(self.sessions.values()):
                if s.queue is None and now - s.detached_at > self.idle_s:
                    log.warning("closing idle shell %s (%s)", s.sid, s.project)
                    self.close(s.sid)

    # -- I/O (event loop) ---------------------------------------------------------

    def _readable(self, s):
        try:
            data = os.read(s.fd, 65536)
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EINTR):
                return
            data = b""                                 # EIO: the shell is gone
        if not data:
            return self._ended(s)
        data, recheck = self._strip(s, data)
        if data:
            s.buf += data
            if len(s.buf) > BUFFER:
                del s.buf[:len(s.buf) - BUFFER]
            if s.queue is not None:
                s.queue.put_nowait(("data", data))
        if recheck and s.queue is not None:
            s.queue.put_nowait(("ctl", {"recheck": True}))

    @staticmethod
    def _strip(s, data):
        data = s.tail + data
        s.tail = b""
        recheck = RECHECK in data
        if recheck:
            data = data.replace(RECHECK, b"")
        # hold back a prefix of RECHECK at the end, to join with the next read
        for k in range(min(len(RECHECK) - 1, len(data)), 0, -1):
            if RECHECK.startswith(data[-k:]):
                s.tail, data = data[-k:], data[:-k]
                break
        return data, recheck

    def _ended(self, s):
        if s.fd is not None:
            self.loop.remove_reader(s.fd)
            try:
                os.close(s.fd)
            except OSError:
                pass
            s.fd = None
        try:
            pid, status = os.waitpid(s.pid, os.WNOHANG)
        except ChildProcessError:
            pid, status = s.pid, None
        if pid == 0:                     # the pty closed before the shell exited
            self.loop.call_later(0.1, self._ended, s)
            return
        s.exit = os.waitstatus_to_exitcode(status) if status is not None else -1
        self.sessions.pop(s.sid, None)
        if s.queue is not None:
            s.queue.put_nowait(("ctl", {"exit": s.exit}))
            s.queue.put_nowait(None)

    def attach(self, s):
        """A new outbox for ``s``; any earlier socket is told it was taken over.
        Returns (queue, the output to replay)."""
        if s.queue is not None:
            s.queue.put_nowait(("ctl", {"taken": True}))
            s.queue.put_nowait(None)
        s.queue = asyncio.Queue()
        return s.queue, bytes(s.buf)

    def detach(self, s, queue):
        if s.queue is queue:
            s.queue = None
            s.detached_at = time.monotonic()

    def write(self, s, data):
        if s.fd is None:
            return
        try:
            os.write(s.fd, data)
        except OSError:
            pass

    def resize(self, s, cols, rows):
        if s.fd is None:
            return
        try:
            fcntl.ioctl(s.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass
