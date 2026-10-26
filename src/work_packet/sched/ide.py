"""IDE requests: an IDE on a packet takes a slot (docs/scheduler.md §8; plan Q5.2).

The board writes ``sched/ide/<key>.json`` when someone opens web VS Code
and the server is to run in a job (``[sched.ide] slot``). The dispatcher
starts it ahead of all agent work, never gated by the budget, and never
preempting a running step; the job writes ``host:port`` to
``ide/servers/<key>/endpoint``. Closing it (idle) cancels the job.
"""

import json
import os

from .. import clock, fsutil, registry, schema
from .config import sched_dir


def req_dir(h=None):
    return os.path.join(sched_dir(h), "ide")


def req_path(key, h=None):
    return os.path.join(req_dir(h), key + ".json")


def request(key, size, argv, by, target, h=None):
    """Ask for an IDE job (once: an existing request is kept)."""
    os.makedirs(req_dir(h), exist_ok=True)
    p = req_path(key, h)
    if os.path.exists(p):
        return False
    fsutil.atomic_write(p, json.dumps({
        "key": key, "size": size, "argv": list(argv), "by": by, "target": target,
        "t": schema.format_timestamp(clock.now())}) + "\n")
    return True


def withdraw(key, h=None):
    try:
        os.unlink(req_path(key, h))
    except FileNotFoundError:
        pass


def requests(h=None):
    """Every IDE request, oldest first."""
    out = []
    try:
        names = os.listdir(req_dir(h))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(req_dir(h), n)) as fp:
                d = json.load(fp)
            if isinstance(d, dict) and d.get("key") and d.get("argv"):
                out.append(d)
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda d: (d.get("t", ""), d["key"]))


def endpoint_path(key, h=None):
    return os.path.join(h or registry.home(), "ide", "servers", key, "endpoint")


def endpoint(key, h=None):
    """``(host, port)`` the job wrote, or None."""
    try:
        with open(endpoint_path(key, h)) as fp:
            host, _, port = fp.read().strip().rpartition(":")
        return (host, int(port)) if host else None
    except (OSError, ValueError):
        return None


def enabled(cfg):
    """IDE servers run in scheduler jobs: ``[sched.ide] slot``, by default when
    the backend is a batch system."""
    v = (cfg.get("ide") or {}).get("slot")
    if v is None or v == "":
        return cfg.get("backend", "local") != "local"
    return bool(v)
