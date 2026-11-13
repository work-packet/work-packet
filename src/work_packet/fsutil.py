"""Filesystem helpers that make writes durable and renames atomic."""

import collections
import json
import os
import pickle
import tempfile
import threading


def fsync_dir(path):
    """Flush a directory entry so a rename or create in it survives a crash."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data):
    """Replace ``path`` with ``data`` (str or bytes) so readers see old or new, never half."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    fsync_dir(d)


def append_line(path, line):
    """Append one line with O_APPEND and fsync it. ``line`` must not contain a newline."""
    if "\n" in line:
        raise ValueError("append_line: line contains a newline")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def rename(src, dst):
    """Rename and fsync the parent directory (or directories) of both ends."""
    os.rename(src, dst)
    sd = os.path.dirname(os.path.abspath(src))
    dd = os.path.dirname(os.path.abspath(dst))
    fsync_dir(dd)
    if sd != dd:
        fsync_dir(sd)


def read_text(path):
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read()


# --- parsed files, kept while they don't change (docs/cpu-plan.md P2) ---------------

CACHE_MAX = 16384                     # a 50-card home keeps about 3,800
_cache = collections.OrderedDict()     # (tag, path) -> (stat signature, pickled value)
_cache_lock = threading.Lock()
_stats = {"hit": 0, "miss": 0}


def cached(path, parse, tag, copy=True):
    """``parse(path)``, reused while ``path``'s mtime, ctime, size and inode stay the
    same. Each call gets its own copy (a pickle of the parse is kept), so callers may
    change what they get; ``copy=False`` keeps the value itself, for immutable ones
    (text). A file that can't be stat'ed, or a parse that raises, is not kept. Another host's write over NFS shows once the attribute cache expires."""
    try:
        st = os.stat(path)
    except OSError:
        return parse(path)
    key, sig = (tag, path), (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == sig:
            _cache.move_to_end(key)
            _stats["hit"] += 1
            blob, found = hit[1], True
        else:
            blob, found = None, False
    if found:
        return pickle.loads(blob) if copy else blob
    v = parse(path)                     # stat first: a change meanwhile is a miss next time
    try:
        blob = pickle.dumps(v, pickle.HIGHEST_PROTOCOL) if copy else v
    except (pickle.PicklingError, TypeError, AttributeError):
        return v
    with _cache_lock:
        _stats["miss"] += 1
        _cache[key] = (sig, blob)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return v


def cache_clear():
    with _cache_lock:
        _cache.clear()


def _load_json(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def load_json(path):
    """``json.load`` of ``path``, through ``cached``. Raises as ``json.load`` does."""
    return cached(path, _load_json, "json")
