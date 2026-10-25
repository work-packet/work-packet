"""``wpk tick``: one scheduler pass over every registered project (stage1-plan §5)."""

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List

from . import clock, frontmatter, lease, schema
from .packet import Packet


@dataclass(order=True)
class Due:
    due: str                      # the timestamp it became due: sort key
    project: str
    wpid: str
    path: str = field(compare=False)
    state: str = field(compare=False)


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
            out.append(Due(when, e["name"], w, pkt.path, st))
    return sorted(out)


def _start(d):
    return subprocess.Popen([sys.executable, "-m", "work_packet", "step", d.path],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True)


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


def run_pass(items, jobs, budget, report, stop=lambda: False):
    """Run ``wpk step`` for ``items``, at most ``jobs`` at once and ``budget`` in all.

    Once ``stop()`` is true no new step starts; running ones are waited for.
    """
    ran, queue, live = [], list(items)[:budget], []
    while queue or live:
        if stop():
            queue = []
        while queue and len(live) < jobs:
            d = queue.pop(0)
            live.append((d, _start(d)))
        time.sleep(0.02)
        for d, p in list(live):
            if p.poll() is None:
                continue
            live.remove((d, p))
            err = (p.stderr.read() or "").strip().splitlines()
            p.stderr.close()
            msg = err[-1] if err else ""
            if msg.startswith("wpk: "):
                msg = msg[5:]
            r = Ran(d, p.returncode, msg or "exit %s" % p.returncode)
            ran.append(r)
            report(r)
    return ran


def tick(entries, jobs=1, until_idle=False, max_steps=None, report=lambda r: None,
         stop=lambda: False):
    """One pass, or with ``until_idle`` passes until nothing is due or nothing moved.

    ``stop`` is checked before each step starts (the runner's shutdown).
    """
    res = TickResult()
    while not stop():
        budget = None if max_steps is None else max_steps - len(res.ran)
        if budget is not None and budget <= 0:
            break
        items = due(entries)
        if not items:
            break
        ran = run_pass(items, jobs, budget if budget is not None else len(items), report, stop)
        res.passes += 1
        res.ran += ran
        # Stop when nothing committed or failed: what is left is leased or not runnable.
        if not until_idle or not any(r.code in (0, 1) for r in ran):
            break
    return res
