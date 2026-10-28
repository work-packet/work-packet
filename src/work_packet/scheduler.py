"""``wpk tick``: one scheduler pass over every registered project (stage1-plan §5)."""

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

from . import clock, frontmatter, lease, schema
from .packet import Packet

log = logging.getLogger(__name__)


@dataclass(order=True)
class Due:
    due: str                      # the timestamp it became due: sort key
    project: str
    wpid: str
    path: str = field(compare=False)
    state: str = field(compare=False)
    next_size: Optional[str] = field(default=None, compare=False)   # status.md (§5.2)


@dataclass
class Ran:
    due: Due
    code: int
    msg: str


@dataclass
class TickResult:
    ran: List[Ran] = field(default_factory=list)
    passes: int = 0

    def count(self, code):
        return sum(1 for r in self.ran if r.code == code)


def due(entries, now=None):
    """Packets that may step now, oldest-due first. Leased ones are left out."""
    now = now or clock.now()
    out = []
    for e in entries:
        pdir = os.path.join(e["path"], "packets")
        try:
            names = sorted(os.listdir(pdir))
        except OSError:
            continue
        for w in names:
            if not schema.is_wpid(w):
                continue
            pkt = Packet(os.path.join(pdir, w))
            try:
                meta, _ = pkt.load_status()
            except (OSError, frontmatter.FrontMatterError):
                continue
            st = meta.get("state")
            if st == "RUNNABLE":
                when = meta.get("updated") or ""
            elif st == "SLEEPING" and meta.get("wake_at"):
                try:
                    if schema.parse_timestamp(meta["wake_at"]) > now:
                        continue
                except ValueError:
                    continue
                when = meta["wake_at"]
            else:
                continue
            held = lease.read(pkt.lease_path)
            if held is not None and not lease.is_stale(held, now):
                continue
            out.append(Due(when, e["name"], w, pkt.path, st, meta.get("next_size")))
    return sorted(out)


def next_wake(entries):
    """The earliest ``wake_at`` of a ``SLEEPING`` packet, or None."""
    best = None
    for e in entries:
        pdir = os.path.join(e["path"], "packets")
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for w in names:
            if not schema.is_wpid(w):
                continue
            try:
                meta, _ = Packet(os.path.join(pdir, w)).load_status()
                if meta.get("state") != "SLEEPING" or not meta.get("wake_at"):
                    continue
                t = schema.parse_timestamp(meta["wake_at"])
            except (OSError, frontmatter.FrontMatterError, ValueError):
                continue
            best = t if best is None or t < best else best
    return best


def tick(entries, jobs=1, until_idle=False, max_steps=None, report=lambda r: None,
         stop=lambda: False, home=None):
    """One pass, or with ``until_idle`` passes until nothing is due or nothing moved.

    A pass starts each packet due at its start at most once, through the
    dispatcher with the local backend (docs/scheduler-plan.md Q1.17), so the
    pool's mode, holds, classes and sizes apply; ``jobs`` steps at once.
    ``stop`` is checked before each step starts (the runner's shutdown).
    """
    from .sched.backends.local import Local
    from .sched.dispatcher import Dispatcher
    d = Dispatcher(home=home, backend=Local(home), jobs=jobs, report=report,
                   entries=lambda: entries)
    res = TickResult()
    _sync_requests(home)
    while not stop():
        budget = None if max_steps is None else max_steps - len(res.ran)
        if budget is not None and budget <= 0:
            break
        items, _ = d.context()
        if not items:
            break
        ran = d.tick_pass({it.key for it in items}, budget, stop)
        res.passes += 1
        res.ran += ran
        # Stop when nothing committed or failed: what is left is leased or not runnable.
        _sync_requests(home)
        if not until_idle or not any(r.code in (0, 1) for r in ran):
            break
    return res


def _sync_requests(home):
    """Bring back the results of finished requests (docs/delegation.md §5). Never raises:
    a request that can't be delivered now is tried again on the next pass."""
    from . import requests
    try:
        moved = requests.sync(home)
    except Exception:                  # noqa: BLE001 - keep the scheduler going
        log.exception("request sync failed")
        return
    for e, msg in moved:
        log.info("request %s of %s: %s", e["id"], e["from"]["wpid"][:8], msg)
