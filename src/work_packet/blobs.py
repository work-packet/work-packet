"""The blob store: files named by their sha256 (docs/work-data-design.md §7.3).

Only the directory backend exists so far: ``<home>/blobs/sha256/ab/<hash>``.
Blobs are written once and never changed; putting the same content twice
is free.
"""

import hashlib
import os
import shutil

from . import fsutil


def root(h=None):
    from . import registry
    return os.path.join(h or registry.home(), "blobs")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def path_of(sha, h=None):
    return os.path.join(root(h), "sha256", sha[:2], sha)


def has(sha, h=None):
    return os.path.isfile(path_of(sha, h))


def put_file(path, h=None):
    """Store the file at ``path``; returns its sha256."""
    sha = sha256_file(path)
    dst = path_of(sha, h)
    if not os.path.isfile(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".tmp-%d" % os.getpid()
        shutil.copyfile(path, tmp)
        if sha256_file(tmp) != sha:
            os.unlink(tmp)
            raise IOError("%s changed while it was being stored" % path)
        os.chmod(tmp, 0o444)
        os.replace(tmp, dst)
    return sha


def put_bytes(data, h=None):
    if isinstance(data, str):
        data = data.encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    dst = path_of(sha, h)
    if not os.path.isfile(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        fsutil.atomic_write(dst, data)
        os.chmod(dst, 0o444)
    return sha


def get_bytes(sha, h=None):
    with open(path_of(sha, h), "rb") as fp:
        return fp.read()


def verify(sha, h=None):
    p = path_of(sha, h)
    return os.path.isfile(p) and sha256_file(p) == sha
