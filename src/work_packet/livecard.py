"""Keep cards and the history store current as packets run (design P2).

``journal.append`` marks the packet whose journal changed; ``flush`` then
brings each marked packet's project up to date with ``migrate.keep_project``:
the thread rebuilt from the journal and merged into the card (so a live card
is exactly what ``wpk migrate`` would write), metrics synced provisionally,
and a project harvested once every packet in it is COMPLETED.

``flush`` runs at the end of ``executor.step`` and ``executor.admin``, after
each dashboard POST, and at process exit. It never raises: a card that
cannot be written is logged, and the next flush catches up, because every
flush rebuilds from the whole journal.

``WPK_NO_LIVECARD=1`` turns it off.
"""

import atexit
import fcntl
import hashlib
import logging
import os
import threading

log = logging.getLogger(__name__)

_dirty = set()
_mu = threading.Lock()


def enabled():
    return os.environ.get("WPK_NO_LIVECARD", "") in ("", "0")


def mark(journal_path):
    """Note that the packet owning ``journal_path`` changed. Cheap."""
    if enabled():
        with _mu:
            _dirty.add(os.path.dirname(os.path.abspath(journal_path)))


def _entry_of(run_dir, h=None):
    """The registry entry of the project holding run directory ``run_dir``
    (``<project>/packets/<wpid>`` or ``.work-packet/runs/<wpid>``), or None."""
    from . import layout, registry
    proj = layout.project_of_runs(os.path.dirname(run_dir))
    if proj is None:
        return None
    proj = os.path.realpath(proj)
    for e in registry.entries(h):
        if os.path.realpath(e["path"]) == proj:
            return e
    return None


def _lock(name, h=None):
    from . import registry
    d = os.path.join(h or registry.home(), "locks")
    os.makedirs(d, exist_ok=True)
    fp = open(os.path.join(d, "keep-%s" % hashlib.sha1(name.encode()).hexdigest()[:16]), "a")
    fcntl.flock(fp, fcntl.LOCK_EX)
    return fp


def update_project(entry, h=None):
    """``migrate.keep_project`` under the project's lock; None on failure."""
    from . import migrate
    fp = _lock(entry["name"], h)
    try:
        return migrate.keep_project(entry, h=h)
    except Exception:
        log.warning("could not update the card and history of %s", entry["name"],
                    exc_info=True)
        return None
    finally:
        fp.close()


def flush(h=None):
    """Update every project with a marked packet. Returns their names."""
    if not enabled():
        with _mu:
            _dirty.clear()
        return []
    with _mu:
        dirs = sorted(_dirty)
        _dirty.clear()
    done = []
    for d in dirs:
        try:
            e = _entry_of(d, h)
        except Exception:
            e = None
        if e is None or e["name"] in done:
            continue
        update_project(e, h)
        done.append(e["name"])
    return done


atexit.register(lambda: flush())
