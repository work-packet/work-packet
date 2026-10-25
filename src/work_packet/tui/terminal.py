"""A terminal pane for Textual: a program on a pty, drawn with pyte (docs/setup.md §6).

The pane takes every key while it has focus, except the ones in ``PASS``
(the app's own: function keys, ``ctrl+q``, and ``ctrl+]`` to leave the
pane), so editors and pagers work inside it.
"""

import fcntl
import os
import signal
import struct
import subprocess
import termios

import pyte
from rich.segment import Segment
from rich.style import Style
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget

PASS = {"ctrl+q", "ctrl+right_square_bracket"} | {"f%d" % i for i in range(1, 13)}

KEYS = {
    "enter": "\r", "tab": "\t", "shift+tab": "\x1b[Z", "backspace": "\x7f",
    "escape": "\x1b", "delete": "\x1b[3~", "insert": "\x1b[2~",
    "home": "\x1b[H", "end": "\x1b[F", "pageup": "\x1b[5~", "pagedown": "\x1b[6~",
    "up": "\x1b[A", "down": "\x1b[B", "right": "\x1b[C", "left": "\x1b[D",
}
DECCKM = 1 << 5          # private mode 1 (application cursor keys), as pyte stores it
APP_CURSOR = {"up": "\x1bOA", "down": "\x1bOB", "right": "\x1bOC", "left": "\x1bOD"}

_NAMES = {"brown": "yellow"}


def _color(c):
    if c == "default" or not c:
        return None
    if len(c) == 6 and all(x in "0123456789abcdefABCDEF" for x in c):
        return "#" + c
    if c.startswith("bright"):
        base = _NAMES.get(c[6:], c[6:])
        return "bright_" + base
    return _NAMES.get(c, c)


class Terminal(Widget, can_focus=True):
    """``argv`` running on a pty in ``cwd`` with ``env``."""

    DEFAULT_CSS = """
    Terminal { height: 1fr; background: $surface; }
    Terminal:focus { background: $boost; }
    """

    class Exited(Message):
        def __init__(self, terminal, code):
            super().__init__()
            self.terminal = terminal
            self.code = code

    def __init__(self, argv, cwd=None, env=None, **kw):
        super().__init__(**kw)
        self.argv, self.cwd, self.env = argv, cwd, env
        self.screen_ = pyte.Screen(80, 24)
        self.stream = pyte.ByteStream(self.screen_)
        self.screen_.write_process_input = self._answer
        self.fd = None
        self.proc = None

    # --- the child --------------------------------------------------------------

    def on_mount(self):
        self.start()

    def start(self):
        cols, rows = max(self.size.width, 20), max(self.size.height, 4)
        self.screen_.resize(rows, cols)
        master, slave = os.openpty()
        self._winsize(master, rows, cols)
        env = dict(self.env or os.environ, TERM="xterm-256color", COLUMNS=str(cols),
                   LINES=str(rows))

        def child():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=env, stdin=slave,
                                     stdout=slave, stderr=slave, preexec_fn=child,
                                     close_fds=True)
        os.close(slave)
        self.fd = master
        os.set_blocking(master, False)
        import asyncio
        asyncio.get_running_loop().add_reader(master, self._readable)

    def _readable(self):
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._hangup()
            return
        self.stream.feed(data)
        self.refresh()

    def _hangup(self):
        import asyncio
        if self.fd is None:
            return
        try:
            asyncio.get_running_loop().remove_reader(self.fd)
        except (RuntimeError, ValueError):
            pass
        os.close(self.fd)
        self.fd = None
        code = self.proc.wait() if self.proc else None
        self.post_message(self.Exited(self, code))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGHUP)
            except OSError:
                pass
        if self.fd is not None:
            self._hangup()

    def on_unmount(self):
        self.stop()

    @property
    def alive(self):
        return self.fd is not None

    def _answer(self, data):
        self.write(data)

    def write(self, data):
        """Send ``data`` to the program, as if typed."""
        if self.fd is None:
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def text(self):
        """The screen as plain text, one line per row (for tests)."""
        return "\n".join(line.rstrip() for line in self.screen_.display)

    # --- size and keys ------------------------------------------------------------

    @staticmethod
    def _winsize(fd, rows, cols):
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def on_resize(self, event):
        cols, rows = max(event.size.width, 20), max(event.size.height, 4)
        if (rows, cols) != (self.screen_.lines, self.screen_.columns):
            self.screen_.resize(rows, cols)
            if self.fd is not None:
                self._winsize(self.fd, rows, cols)
            self.refresh()

    def on_key(self, event):
        if event.key in PASS:
            return
        seq = None
        if event.key in APP_CURSOR and DECCKM in self.screen_.mode:
            seq = APP_CURSOR[event.key]
        elif event.key in KEYS:
            seq = KEYS[event.key]
        elif event.character:
            seq = event.character
        if seq is not None:
            event.stop()
            event.prevent_default()
            self.write(seq)

    def on_paste(self, event):
        event.stop()
        self.write(event.text)

    # --- drawing --------------------------------------------------------------

    def render_line(self, y):
        sc = self.screen_
        width = self.size.width
        if y >= sc.lines:
            return Strip.blank(width)
        row = sc.buffer[y]
        cur = (sc.cursor.y == y and not sc.cursor.hidden and self.has_focus)
        segs = []
        text, style = [], None
        for x in range(min(sc.columns, width)):
            ch = row[x]
            st = Style(color=_color(ch.fg), bgcolor=_color(ch.bg), bold=ch.bold,
                       italic=ch.italics, underline=ch.underscore,
                       reverse=ch.reverse != (cur and x == sc.cursor.x),
                       strike=ch.strikethrough)
            if st != style and text:
                segs.append(Segment("".join(text), style))
                text = []
            style = st
            text.append(ch.data or " ")
        if text:
            segs.append(Segment("".join(text), style))
        return Strip(segs).adjust_cell_length(width)
