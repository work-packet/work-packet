"""Run one model step as a child process; the harness adapter builds the
command line and reads the transcript (``harness/``)."""

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StepResult:
    exit_code: Optional[int] = None
    timed_out: bool = False
    is_error: bool = False
    got_result: bool = False         # the transcript has a ``result`` event
    subtype: Optional[str] = None
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None
    tokens: dict = field(default_factory=dict)
    context: list = field(default_factory=list)   # context size of each main-thread call
    cache_breaks: int = 0            # main-thread calls that re-wrote most of the cache
    cache_rewrite: int = 0           # ... and the tokens they wrote
    api_s: Optional[float] = None    # time spent in API calls
    quota: dict = field(default_factory=dict)     # {window: {first, last, resets_at}}
    duration_s: float = 0.0
    text: Optional[str] = None

    def failure(self):
        """Why the run failed, or None if it succeeded."""
        if self.timed_out:
            return "timeout"
        if self.exit_code != 0:
            return "model exited with status %s" % self.exit_code
        if not self.got_result:
            return "transcript has no result event"
        if self.is_error:
            return "model reported an error (%s)" % (self.subtype or "is_error")
        return None


def context_summary(sizes):
    """``meta.json``'s ``context``: first call (about the orientation cost), peak, last."""
    if not sizes:
        return None
    return {"first": sizes[0], "peak": max(sizes), "last": sizes[-1], "calls": len(sizes)}


def run(argv, prompt, cwd, env, timeout_s, transcript_path, stderr_path, parse,
        pid_path=None, append=False):
    """Run the model with ``prompt`` on stdin. A timeout kills the process group.

    ``parse(transcript_path, res)`` fills in the result from the transcript.
    ``pid_path``, if given, holds the model's PID while it runs: the board
    finds the step's processes from it (``procs.py``). With ``append``, the
    transcript and stderr are added to rather than replaced (a nudge).
    """
    res = StepResult()
    t0 = time.monotonic()
    mode = "ab" if append else "wb"
    with open(transcript_path, mode) as out, open(stderr_path, mode) as err:
        try:
            p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                 stdout=out, stderr=err, start_new_session=True)
        except OSError as e:
            err.write(("wpk: cannot run %s: %s\n" % (argv[0], e)).encode())
            res.exit_code = 127
            return res
        if pid_path:
            with open(pid_path, "w") as fp:
                fp.write("%d\n" % p.pid)
        try:
            p.communicate(prompt.encode("utf-8"), timeout=timeout_s)
        except subprocess.TimeoutExpired:
            res.timed_out = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
        except BaseException:       # SIGTERM from the scheduler (Stop now): take it along
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
            raise
        finally:
            if pid_path:
                try:
                    os.remove(pid_path)
                except OSError:
                    pass
        res.exit_code = p.returncode
    res.duration_s = round(time.monotonic() - t0, 3)
    return parse(transcript_path, res)
