"""Progress of slow commands (packet creation's clone and dependencies):
run a command with its output streamed line by line, and read git's and
IVPM's plain text into progress events (dash-create-progress-design.md).

Events are plain dicts with a kind ``k``, so they can be journaled and sent
to a browser as they are:

- ``{"k": "pkg", "name", "state": "run"|"ok"|"fail", "type", "secs", "error", "loc"}``
- ``{"k": "task", "name", "state", "at", "total", "msg", "secs", "pkg", "sub"}``: ``at``
  of ``total`` (a "step" is a stage of whoever reads these)
- ``{"k": "git", "pkg", "phase", "pct", "cur", "total"}``: git's own progress, or
  a custom source's (p4_mkwa, say) steps ``[pkg] msg (a/b)``: a package's progress
- ``{"k": "detail", "pkg", "text"}``: a line about a package or task
- ``{"k": "diag", "severity", "loc", "msg"}``
- ``{"k": "summary", "data": {...}}``
- ``{"k": "phase", "name"}``: resolving, fetching, installing, finishing
"""

import contextlib
import os
import re
import signal
import subprocess
import threading

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][0-9A-Za-z]")


# Inherited from a shell in some IVPM project (wpk's own, say): IVPM sets
# them itself for the project it works on, and these would point it elsewhere.
IVPM_ENV = ("IVPM_PROJECT", "IVPM_PACKAGES")
GRACE_S = 3                           # after SIGTERM, before SIGKILL, on a cancel


class Cancelled(Exception):
    def __init__(self):
        super().__init__("cancelled")


class Canceller:
    """Cancels the ``run_streamed`` commands of the threads that run under it
    (``with c.on():``): the one running is killed, process group and all
    (git's ssh, ivpm's parallel clones), and the next ones raise Cancelled."""

    def __init__(self):
        self.lock = threading.Lock()
        self.procs = set()
        self.cancelled = False

    @contextlib.contextmanager
    def on(self):
        was = getattr(_local, "c", None)
        _local.c = self
        try:
            yield self
        finally:
            _local.c = was

    def cancel(self):
        with self.lock:
            self.cancelled = True
            procs = list(self.procs)
        for p in procs:
            _killpg(p.pid, signal.SIGTERM)
            threading.Timer(GRACE_S, _killpg, (p.pid, signal.SIGKILL)).start()

    def _add(self, p):
        with self.lock:
            self.procs.add(p)
            late = self.cancelled
        if late:
            _killpg(p.pid, signal.SIGTERM)

    def _drop(self, p):
        with self.lock:
            self.procs.discard(p)


_local = threading.local()


def _killpg(pgid, sig):
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def in_foreground():
    """True if this process is in its terminal's foreground: someone is at
    the terminal to answer a prompt (an ssh passphrase, say). wpkd run as a
    background job is not, and a child of it in its process group that touches
    the terminal stops the whole group, wpkd and the board with it; such a
    child gets a session of its own, with no terminal to touch."""
    try:
        fd = os.open("/dev/tty", os.O_RDONLY | os.O_NOCTTY)
    except OSError:
        return False
    try:
        return os.tcgetpgrp(fd) == os.getpgrp()
    except OSError:
        return False
    finally:
        os.close(fd)


def run_streamed(cmd, on_line=None, cwd=None, env=None, tail=40):
    """Run ``cmd`` (a list; a string runs in the shell) with stderr into stdout.
    ``on_line(text, final)`` gets each line as it comes, without its ending
    and ANSI codes: ``final`` is False for a ``\\r``-ended update (git's
    progress), which the next one replaces. Returns (returncode, the last
    ``tail`` final lines as one string)."""
    keep = []

    def line(raw, final):
        text = ANSI.sub("", raw.decode("utf-8", "replace"))
        if final:
            keep.append(text)
            if len(keep) > tail:
                del keep[0]
        if on_line is not None:
            on_line(text, final)

    c = getattr(_local, "c", None)
    if c is not None and c.cancelled:
        raise Cancelled()
    env = {k: v for k, v in (os.environ if env is None else env).items() if k not in IVPM_ENV}
    # A session of its own when it can be cancelled (its group is what is
    # killed) or no one is at the terminal to answer a prompt.
    p = subprocess.Popen(cmd, shell=isinstance(cmd, str), cwd=cwd, env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT,
                         start_new_session=c is not None or not in_foreground())
    if c is not None:
        c._add(p)
    buf = b""
    try:
        while True:
            chunk = os.read(p.stdout.fileno(), 65536)
            buf += chunk
            while True:
                m = re.search(rb"\r\n|\n|\r", buf)
                if m is None or (m.group() == b"\r" and m.end() == len(buf) and chunk):
                    break                 # a lone \r at the end: \r\n may follow
                line(buf[:m.start()], m.group() != b"\r")
                buf = buf[m.end():]
            if not chunk:
                break
        if buf:
            line(buf, True)
        rc = p.wait()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()
        if c is not None:
            c._drop(p)
            if c.cancelled:           # what is left of its group, before the clone is removed
                _killpg(p.pid, signal.SIGKILL)
    if c is not None and c.cancelled:
        raise Cancelled()
    return rc, "\n".join(keep).strip()


GIT_PCT = re.compile(r"(Counting|Compressing|Receiving|Resolving|Updating) "
                     r"(objects|deltas|files):\s+(\d+)% \((\d+)/(\d+)\)")
CLONING = re.compile(r"Cloning into '([^']*)'")


def git_progress(text):
    """git's progress in ``text`` (the last, as parallel clones can share a
    line): {phase, pct, cur, total}, or None."""
    m = None
    for m in GIT_PCT.finditer(text):
        pass
    if m is None:
        return None
    return {"phase": "%s %s" % (m.group(1), m.group(2)), "pct": int(m.group(3)),
            "cur": int(m.group(4)), "total": int(m.group(5))}


# IVPM's TranscriptUpdateTUI (update_tui.py, since v2.19.0), the output
# when stdout is not a terminal. The root clone of `ivpm clone` is the
# package "[clone]"; any other bracketed name is a handler task.
_DUR = r"(?: \((\d+(?:\.\d+)?)s\))?"
_RX = [
    ("task_start", re.compile(r"^(  )?>> \[([^\]]+)\](?: - .*)?$")),
    ("pkgtask_start", re.compile(r"^>> \[([^\]]+)\] \((.+)\)$")),
    ("task_error", re.compile(r"^(  )?<< \[([^\]]+)\] (?:\[([^\]]+)\] )?ERROR: (.*)$")),
    ("task_end", re.compile(r"^(  )?<< \[([^\]]+)\]" + _DUR + "$")),
    ("pkg_error", re.compile(r"^<< (\S+)(?: \((.*?)\))? ERROR: (.*)$")),
    ("pkg_end", re.compile(r"^<< (\S+)" + _DUR + "$")),
    ("pkg_start", re.compile(r"^>> (\S+)(?: \(([^)]*)\))?$")),
    ("resolved", re.compile(r"^   → (.*)$")),
    ("step", re.compile(r"^(  )?   (?:\[([^\]]+)\] )?(.*?) \((\d+)/(\d+)\)$")),
    ("indented", re.compile(r"^(  )?   (?:\[([^\]]+)\] )?(\S.*)$")),
    ("summary", re.compile(r"^Sub-Package Update Summary:$")),
    ("errors", re.compile(r"^Errors encountered:$")),
    ("diag", re.compile(r"^(?:(\S+:\d+(?::\d+)?): )?(note|warning|error|fatal): (.*)$")),
]
_PCT_TAIL = re.compile(r"\s+\d+%.*$")   # "Syncing files 25% (0h0m5s left)"
_KV = re.compile(r"^ +([A-Za-z][\w -]*?): +(\S.*)$")
ROOT = "[clone]"


class IvpmTranscript:
    """Folds IVPM's plain-text output into packages, tasks and a summary.
    ``feed`` returns the events a line makes; [] for a line it does not
    know (the caller keeps it in the raw log)."""

    def __init__(self, root=None):
        self.root = os.path.abspath(root) if root else None
        self.packages = {}            # name -> {state, type, secs, error, loc}
        self.tasks = {}               # name -> {state, at, total, msg, secs, pkg}: a
                                      # package's task is "type:pkg" (p4_mkwa:mypkg)
        self.summary = {}
        self.diagnostics = []
        self.phase = "resolving"
        self._block = None            # "summary" or "errors": the lines that follow
        self._cloning = None          # the package of the last "Cloning into"
        self._last_pkg = None

    # --- what the panel shows
    def counts(self):
        st = [p["state"] for n, p in self.packages.items() if n != ROOT]
        return {"started": len(st), "done": st.count("ok"), "failed": st.count("fail")}

    def running(self):
        return [n for n, p in self.packages.items() if p["state"] == "run"]

    # --- reading
    def feed(self, text, final=True):
        if not final:
            return self._git(text)
        line = text.rstrip()
        if self._block:
            m = _KV.match(line)
            if m and self._block == "summary":
                self.summary[m.group(1).strip()] = m.group(2)
                return [{"k": "summary", "data": dict(self.summary)}]
            if line.startswith("  ") and self._block == "errors":
                return [{"k": "detail", "pkg": None, "text": line.strip()}]
            if line.strip() and not line.startswith("  "):
                self._block = None
            elif not line.strip():
                return []
        for kind, rx in _RX:
            m = rx.match(line)
            if m:
                return getattr(self, "_" + kind)(m)
        return self._git(line)

    def _set_phase(self, name):
        if self.phase == name:
            return []
        self.phase = name
        return [{"k": "phase", "name": name}]

    def _pkg(self, name, **kw):
        p = self.packages.setdefault(name, {"state": "run", "type": None, "secs": None,
                                            "error": None, "loc": None})
        p.update(kw)
        return dict(p, k="pkg", name=name)

    def _task(self, name, **kw):
        t = self.tasks.setdefault(name, {"state": "run", "at": None, "total": None,
                                         "msg": None, "secs": None, "pkg": None,
                                         "sub": False})
        t.update(kw)
        return dict(t, k="task", name=name)

    def _task_start(self, m):
        out = [] if self.phase == "finishing" else self._set_phase("installing")
        return out + [self._task(m.group(2), state="run", sub=bool(m.group(1)), at=None,
                                 total=None, msg=None)]

    def _pkgtask_start(self, m):
        if m.group(1) == "clone":     # `>> [clone] (git)`: the root clone, a package
            self._last_pkg = ROOT
            return [self._pkg(ROOT, state="run", type=m.group(2))]
        # Named for its package too: the name is the source type, which two
        # packages fetched at once share.
        return [self._task("%s:%s" % m.groups(), state="run", pkg=m.group(2), at=None,
                           total=None, msg=None, secs=None)]

    def _task_error(self, m):
        if m.group(2) == "clone":
            return [self._pkg(ROOT, state="fail", error=m.group(4))]
        name = m.group(2) if not m.group(3) else "%s:%s" % (m.group(2), m.group(3))
        return [self._task(name, state="fail", msg=m.group(4), pkg=m.group(3))]

    def _task_end(self, m):
        secs = float(m.group(3)) if m.group(3) else None
        if m.group(2) == "clone":
            return [self._pkg(ROOT, state="ok", secs=secs)]
        name = m.group(2)
        if name not in self.tasks:    # not printed for a package's task, but if it is
            run = [n for n, t in self.tasks.items() if t["state"] == "run" and t["pkg"]
                   and n.startswith(name + ":")]
            name = run[0] if len(run) == 1 else name
        return [self._task(name, state="ok", secs=secs)]

    def _pkg_start(self, m):
        out = self._set_phase("fetching") if self.phase == "resolving" else []
        self._last_pkg = m.group(1)
        return out + [self._pkg(m.group(1), state="run", type=m.group(2))]

    def _pkg_end(self, m):
        secs = float(m.group(2)) if m.group(2) else None
        return self._end_pkg_tasks(m.group(1), state="ok", secs=secs) + \
            [self._pkg(m.group(1), state="ok", secs=secs)]

    def _pkg_error(self, m):
        return self._end_pkg_tasks(m.group(1), state="fail", msg=m.group(3)) + \
            [self._pkg(m.group(1), state="fail", loc=m.group(2), error=m.group(3))]

    def _end_pkg_tasks(self, pkg, **kw):
        """A package's tasks end with it: IVPM prints no ``<< [task]`` for them."""
        return [self._task(n, **kw) for n in self._pkg_tasks(pkg)]

    def _pkg_tasks(self, pkg):
        return [n for n, t in self.tasks.items() if t["state"] == "run" and t["pkg"] == pkg]

    def _resolved(self, m):
        return [{"k": "detail", "pkg": self._last_pkg, "text": "→ " + m.group(1)}]

    def _active_task(self, pkg=None):
        """The task a line is about: the last running one of package ``pkg``
        (its ``[pkg]`` tag); for an untagged line, the last running one not a
        package's (a package's lines are tagged), else the last running."""
        run = [n for n, t in self.tasks.items() if t["state"] == "run"]
        if pkg:
            mine = self._pkg_tasks(pkg)
            if mine:
                return mine[-1]
        else:
            run = [n for n in run if not self.tasks[n]["pkg"]] or run
        return run[-1] if run else None

    def _step(self, m):
        pkg, msg, at, total = m.group(2), m.group(3), int(m.group(4)), int(m.group(5))
        name = self._active_task(pkg)
        out = [{"k": "detail", "pkg": pkg, "text": msg}] if name is None else \
            [self._task(name, at=at, total=total, msg=msg)]
        if pkg and self.packages.get(pkg, {}).get("state") == "run" and total:
            # On the package's row, as git's own progress is.
            out.append({"k": "git", "pkg": pkg, "phase": _PCT_TAIL.sub("", msg) or msg,
                        "pct": at * 100 // total, "cur": at, "total": total})
        return out

    def _indented(self, m):
        pkg, text = m.group(2), m.group(3)
        name = self._active_task(pkg)
        if name is not None and not pkg:
            return [self._task(name, msg=text)]
        out = [self._task(name, msg=text)] if name is not None and \
            self.tasks[name]["pkg"] == pkg else []
        return out + [{"k": "detail", "pkg": pkg or self._last_pkg, "text": text}]

    def _summary(self, m):
        self._block = "summary"
        return self._set_phase("finishing")

    def _errors(self, m):
        self._block = "errors"
        return []

    def _diag(self, m):
        d = {"k": "diag", "loc": m.group(1), "severity": m.group(2), "msg": m.group(3)}
        if d["severity"] == "note":
            return [d]                # common and harmless: not kept
        self.diagnostics.append(d)
        return [d]

    def _git(self, text):
        m = CLONING.search(text)      # a torn line can hold both
        g = git_progress(text)
        if m:
            self._cloning = self._pkg_of_path(m.group(1))
        if g is None:
            return []
        run = self.running()
        pkg = run[0] if len(run) == 1 else (self._cloning if self._cloning in run else None)
        return [dict(g, k="git", pkg=pkg)]

    def _pkg_of_path(self, path):
        path = os.path.abspath(path)
        if self.root and path == self.root:
            return ROOT
        if os.path.basename(os.path.dirname(path)) == "packages":
            return os.path.basename(path)
        return None
