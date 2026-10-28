"""Run one model step as a child process; the harness adapter builds the
command line and reads the transcript (``harness/``)."""

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional


def _parent_death_hook():
    """A ``preexec_fn`` that makes the model die with the step (Linux).

    The model runs in its own session so a timeout can kill its tool
    processes too, which means a step killed with SIGKILL (the scheduler's
    stop after KILL_AFTER_S, a batch system) would leave it running,
    spending tokens. ``PR_SET_PDEATHSIG`` has the kernel send it SIGKILL
    when the step goes. libc is resolved here, before the fork, so the
    child makes one call and nothing else. None where it is not available.
    """
    import sys
    if not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return None
    PR_SET_PDEATHSIG = 1
    sig = int(signal.SIGKILL)
    parent = os.getpid()

    def hook():
        prctl(PR_SET_PDEATHSIG, sig, 0, 0, 0)
        if os.getppid() != parent:          # the step died before the call
            os._exit(1)
    return hook


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
                                 stdout=out, stderr=err, start_new_session=True,
                                 preexec_fn=_parent_death_hook())
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
