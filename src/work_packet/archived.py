"""Projects whose runs have been removed, seen through the history store.

When a finished project's ``packets/`` directory is gone, its records
(every file but ``work/``) are written once from the blob store into
``<home>/cache/archived/<project>/packets/``, read-only, and the project's
entry is pointed there. Everything that reads a project by its path (the
dashboard above all) then works unchanged. The other top-level items of
the real project directory, such as ``project.toml``, are linked in.

Only whole projects are handled: a project with a ``packets/`` directory
is read from it as before.
"""

import json
import os
import shutil

from . import history, layout, registry

MARK = ".restored.json"


def cache_root(h=None):
    return os.path.join(h or registry.home(), "cache", "archived")


def is_archived(entry):
    return bool(entry.get("archived"))


def _wanted(con, entry):
    if os.path.isdir(layout.runs_dir(entry["path"])):
        return []
    return history.harvested(con, entry["name"])


def _current(d, ids):
    try:
        with open(os.path.join(d, MARK), encoding="utf-8") as fp:
            return json.load(fp).get("packets") == ids
    except (OSError, ValueError):
        return False


def _rmtree(d):
    for dp, dns, fns in os.walk(d):
        for x in fns:
            p = os.path.join(dp, x)
            if not os.path.islink(p):
                os.chmod(p, 0o644)
    shutil.rmtree(d)


def materialize(con, entry, ids, h=None):
    """The cache directory for ``entry`` holding packets ``ids``, written if
    it is missing or out of date."""
    d = os.path.join(cache_root(h), entry["name"])
    if _current(d, ids):
        return d
    tmp = "%s.tmp-%d" % (d, os.getpid())
    if os.path.lexists(tmp):
        _rmtree(tmp)
    os.makedirs(tmp)
    try:
        history.restore_project(con, entry["name"], tmp, h)
        if os.path.isdir(entry["path"]):
            for n in sorted(os.listdir(entry["path"])):
                if n != "packets":
                    os.symlink(os.path.join(entry["path"], n), os.path.join(tmp, n))
        with open(os.path.join(tmp, MARK), "w", encoding="utf-8") as fp:
            json.dump({"project": entry["name"], "path": entry["path"], "packets": ids}, fp)
    except BaseException:
        _rmtree(tmp)
        raise
    if os.path.lexists(d):
        _rmtree(d)
    os.replace(tmp, d)
    return d


def view(entry, h=None, con=None):
    """``entry``, or a copy pointed at the restored records when its runs are
    gone (``archived`` set, ``origin`` the real path)."""
    if os.path.isdir(layout.runs_dir(entry["path"])):
        return entry
    if not os.path.isfile(history.db_path(h)):
        return entry
    own = con is None
    if own:
        con = history.connect(h)
    try:
        ids = _wanted(con, entry)
        if not ids:
            return entry
        d = materialize(con, entry, ids, h)
    finally:
        if own:
            con.close()
    return dict(entry, path=d, origin=entry["path"], archived=True)


def entries(h=None):
    """``registry.entries``, with archived projects pointed at their records."""
    es = registry.entries(h)
    if not any(not os.path.isdir(layout.runs_dir(e["path"])) for e in es):
        return es
    if not os.path.isfile(history.db_path(h)):
        return es
    con = history.connect(h)
    try:
        return [view(e, h, con) for e in es]
    finally:
        con.close()


def get(name, h=None):
    e = registry.get(name, h)
    return view(e, h) if e is not None else None
