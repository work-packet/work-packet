"""Where tasks run (docs/scheduler.md §5.1). A backend asks the batch system
for a slot of a task's size and starts the task in it; the dispatcher keeps
the job records and does all the accounting."""

from dataclasses import dataclass, field
from typing import List, Optional

from ..config import Size

PENDING, RUNNING, DONE, LOST = "PENDING", "RUNNING", "DONE", "LOST"


@dataclass(frozen=True)
class JobState:
    state: str                       # PENDING | RUNNING | DONE | LOST
    code: Optional[int] = None       # DONE: the exit status, if known
    reason: Optional[str] = None     # LOST: why (preempted, node failure, ...)
    started: Optional[str] = None    # when it began to run, if the backend knows
    ended: Optional[str] = None      # ... and when it ended
    cpu_s: Optional[float] = None    # CPU time used, if known (sacct TotalCPU)
    counted: bool = True             # LOST/DONE: does the attempt count (§5.5)


@dataclass
class Task:
    job_id: str
    kind: str                        # step | ide
    project: str
    wpid: str
    path: str
    size: Size
    log: str
    step: Optional[int] = None
    lost: Optional[str] = None       # wpk step --lost REASON
    argv: List[str] = field(default_factory=list)   # ide: the command to run
    env: dict = field(default_factory=dict)
    name: str = ""                   # the batch job name (wpk:<home-id>:<wpid>:<step>)


class BackendError(Exception):
    """The backend could not do it now (the batch system is unreachable)."""


class Backend:
    name = "?"
    poll_s = 1.0
    holds_room_while_pending = True

    def submit(self, task):
        """Start ``task`` (or queue it); return the job's ref (a string)."""
        raise NotImplementedError

    def poll(self, refs):
        """{ref: JobState} for each of ``refs``."""
        raise NotImplementedError

    def cancel(self, ref, hard=False):
        raise NotImplementedError

    def list_ours(self):
        """{ref: job name} of every job this pool has in the batch system."""
        raise NotImplementedError

    def close(self):
        pass


def get(cfg, h=None):
    """The backend ``[sched] backend`` names."""
    name = cfg.get("backend", "local")
    if name == "local":
        from .local import Local
        return Local(h)
    if name == "slurm":
        from .slurm import Slurm
        return Slurm(cfg, h)
    if name == "lsf":
        from .lsf import Lsf
        return Lsf(cfg, h)
    raise ValueError("unknown backend %r" % name)
