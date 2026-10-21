"""Filesystem helpers that make writes durable and renames atomic."""

import os
import tempfile


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
