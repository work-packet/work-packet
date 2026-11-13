"""TOML read and write, with ``tomli`` on Python 3.10."""

import tomli_w

from . import fsutil

try:
    import tomllib
except ImportError:          # Python 3.10
    import tomli as tomllib


def _load(path):
    with open(path, "rb") as fp:
        return tomllib.load(fp)


def load_toml(path):
    """Reused while the file is unchanged (fsutil.cached)."""
    return fsutil.cached(path, _load, "toml")


def save_toml(path, d):
    fsutil.atomic_write(path, tomli_w.dumps(d))
