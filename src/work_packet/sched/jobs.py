"""Job records and lost markers (docs/scheduler.md §5.4, plan decision 3).

``sched/jobs/<id>.json``: one per submitted task, removed when it is reaped,
so a restarted wpkd knows what it has in the batch system.
``sched/lost/<wpid>.json``: the packet's last job was ended by Stop now or by
the farm; its next launch passes ``wpk step --lost REASON`` so the attempt is
not counted. Removed once that launch is submitted.
"""

import dataclasses
import json
import os
import uuid
from dataclasses import dataclass
from typing import Optional

from .. import fsutil
from .config import sched_dir


@dataclass
class JobRecord:
    id: str
    backend: str
    kind: str                       # step | ide
    project: str
    wpid: str
    path: str                       # the packet directory (step) or IDE target
    by: str                         # the principal it runs for
    cls: str = "normal"
    size: str = "look"
    cpus: int = 1
    mem_mb: int = 0
    step: Optional[int] = None      # the step it was submitted for
    submitted: Optional[str] = None
    started: Optional[str] = None
    ref: Optional[str] = None       # the backend's job ID
    state: str = "PENDING"          # last seen: PENDING | RUNNING
    lost: Optional[str] = None      # passed as --lost
    estimate: Optional[float] = None
    log: Optional[str] = None
    cancel: Optional[str] = None    # when a cancel was asked for, and why
    cancel_why: Optional[str] = None
    pending_long: bool = False      # the max_pending event was written

    def to_json(self):
        return json.dumps(dataclasses.asdict(self), indent=1) + "\n"


def jobs_dir(h=None):
    return os.path.join(sched_dir(h), "jobs")


def lost_dir(h=None):
    return os.path.join(sched_dir(h), "lost")


def new_id():
    return uuid.uuid4().hex[:12]


def path(job_id, h=None):
    return os.path.join(jobs_dir(h), job_id + ".json")


def save(rec, h=None):
    os.makedirs(jobs_dir(h), exist_ok=True)
    fsutil.atomic_write(path(rec.id, h), rec.to_json())


def _load(p):
    with open(p, encoding="utf-8") as fp:
        d = json.load(fp)
    names = {f.name for f in dataclasses.fields(JobRecord)}
    return JobRecord(**{k: v for k, v in d.items() if k in names})


def load(job_id, h=None):
    try:
        return _load(path(job_id, h))
    except (OSError, ValueError, TypeError):
        return None


def all(h=None):
    """Every readable job record, oldest submission first."""
    out = []
    try:
        names = sorted(os.listdir(jobs_dir(h)))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json") or n.startswith("."):
            continue
        try:
            out.append(_load(os.path.join(jobs_dir(h), n)))
        except (OSError, ValueError, TypeError):
            continue
    return sorted(out, key=lambda r: (r.submitted or "", r.id))


def remove(job_id, h=None):
    try:
        os.unlink(path(job_id, h))
    except FileNotFoundError:
        pass


def log_path(job_id, h=None):
    return os.path.join(jobs_dir(h), job_id + ".log")


# --- lost markers ------------------------------------------------------------------

def mark_lost(wpid, reason, by, t, step=None, h=None):
    os.makedirs(lost_dir(h), exist_ok=True)
    fsutil.atomic_write(os.path.join(lost_dir(h), wpid + ".json"), json.dumps(
        {"wpid": wpid, "reason": reason, "by": by, "t": t, "step": step}) + "\n")


def lost(wpid, h=None):
    """The packet's lost marker, or None."""
    try:
        with open(os.path.join(lost_dir(h), wpid + ".json"), encoding="utf-8") as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) and d.get("reason") else None
    except (OSError, ValueError):
        return None


def clear_lost(wpid, h=None):
    try:
        os.unlink(os.path.join(lost_dir(h), wpid + ".json"))
    except FileNotFoundError:
        pass
