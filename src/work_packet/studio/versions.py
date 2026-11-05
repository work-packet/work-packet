"""A studio's versions (docs/studio-plan.md S3.2; the design §5.4).

A version is the state of the studio's tracked files at the end of a turn
that changed any of them: ``<run dir>/studio/versions/vNNNN.json`` with each
file's sha256 (the bytes are in the blob store, ``blobs.py``), what changed
from the version before, who and when, the render of each changed file
(``renders.py``, by content key) and a ``keep`` flag. Not a git commit:
packets need not be git repos.

Tracked: files of a known kind (``kinds.py``) up to ``SIZE_MAX``, outside the
folders the watcher skips. ``restore`` writes a version's files back (and
removes tracked files it did not have), as a new version.
"""

import json
import os
import time

from .. import blobs, fsutil, layout
from . import kinds, watch

SIZE_MAX = 20 << 20


class VersionError(Exception):
    pass


def vdir(entry, wpid):
    return os.path.join(layout.run_dir(entry["path"], wpid), "studio", "versions")


def _path(entry, wpid, n):
    return os.path.join(vdir(entry, wpid), "v%04d.json" % n)


def numbers(entry, wpid):
    try:
        names = os.listdir(vdir(entry, wpid))
    except OSError:
        return []
    return sorted(int(n[1:5]) for n in names
                  if n.startswith("v") and n.endswith(".json") and n[1:5].isdigit())


def get(entry, wpid, n):
    try:
        with open(_path(entry, wpid, n), encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        raise VersionError("no version %d" % n)


def all_(entry, wpid):
    return [get(entry, wpid, n) for n in numbers(entry, wpid)]


def latest(entry, wpid):
    ns = numbers(entry, wpid)
    return get(entry, wpid, ns[-1]) if ns else None


def tracked(folder):
    """{rel: size} of the files a version holds; ``skipped``: [(rel, why)]."""
    out, skipped = {}, []
    for rel, (_, size) in watch.scan(folder).items():
        if kinds.kind_of(rel) is None:
            continue
        if size > SIZE_MAX:
            skipped.append((rel, "over %d MB" % (SIZE_MAX >> 20)))
            continue
        out[rel] = size
    return out, skipped


def snapshot(entry, wpid, folder, by, turn=None, note=None, home=None, now=None):
    """A new version when the tracked files differ from the last one (else
    None). The changed files go into the blob store."""
    files, skipped = tracked(folder)
    cur = {}
    for rel in sorted(files):
        try:
            cur[rel] = blobs.put_file(os.path.join(folder, rel), home)
        except OSError:
            continue                    # gone while we looked: the next version has it
    last = latest(entry, wpid)
    before = (last or {}).get("files", {})
    changed = sorted(r for r, sha in cur.items() if before.get(r) != sha)
    deleted = sorted(r for r in before if r not in cur)
    if last is not None and not changed and not deleted:
        return None
    if last is None and not cur:
        return None
    n = (last["n"] + 1) if last else 1
    v = {"n": n, "parent": last["n"] if last else None, "at": now or time.time(), "by": by,
         "turn": turn, "note": note, "keep": False, "files": cur, "changed": changed,
         "deleted": deleted, "renders": {},
         "skipped": [{"path": r, "why": w} for r, w in skipped]}
    os.makedirs(vdir(entry, wpid), exist_ok=True)
    fsutil.atomic_write(_path(entry, wpid, n), json.dumps(v, indent=1) + "\n")
    return v


def _save(entry, wpid, v):
    fsutil.atomic_write(_path(entry, wpid, v["n"]), json.dumps(v, indent=1) + "\n")


def set_render(entry, wpid, n, rel, key):
    v = get(entry, wpid, n)
    v.setdefault("renders", {})[rel] = key
    _save(entry, wpid, v)


def keep(entry, wpid, n, flag=True):
    v = get(entry, wpid, n)
    v["keep"] = bool(flag)
    _save(entry, wpid, v)
    return v


def restore(entry, wpid, n, folder, by, home=None, mark=None, now=None):
    """Write version ``n``'s files back and remove the tracked files it did
    not have; then a new version (noted "restored vN"). ``mark(rel)`` is
    called before each write or removal (the watcher's "you"). Returns the
    new version, or None when the folder already was version ``n``."""
    v = get(entry, wpid, n)
    now_files, _ = tracked(folder)
    for rel, sha in v["files"].items():
        p = os.path.join(folder, rel)
        if os.path.isfile(p) and blobs.sha256_file(p) == sha:
            continue
        try:
            data = blobs.get_bytes(sha, home)
        except OSError:
            raise VersionError("the blob for %s (v%d) is missing" % (rel, n))
        if mark:
            mark(rel)
        os.makedirs(os.path.dirname(p) or folder, exist_ok=True)
        fsutil.atomic_write(p, data)
    for rel in now_files:
        if rel not in v["files"]:
            if mark:
                mark(rel)
            try:
                os.unlink(os.path.join(folder, rel))
            except OSError:
                pass
    return snapshot(entry, wpid, folder, by, note="restored v%d" % n, home=home, now=now)


def since(entry, wpid, t):
    """The numbers of the versions made at or after ``t`` (a session's)."""
    return [v["n"] for v in all_(entry, wpid) if v["at"] >= t]
