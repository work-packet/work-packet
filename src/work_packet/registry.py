"""The runner home: ``$WPK_HOME`` or ``~/.work-packet`` (spec §2)."""

import os

from . import fsutil, schema
from .tomlio import load_toml, save_toml



class ConfigError(Exception):
    pass


class LookupFailed(Exception):
    pass


def home():
    return os.path.abspath(os.environ.get("WPK_HOME") or
                           os.path.join(os.path.expanduser("~"), ".work-packet"))


def projects_dir(h=None):
    return os.path.join(h or home(), "projects")


def load_config(h=None):
    """``config.toml`` merged over the defaults. A missing file is all defaults."""
    path = os.path.join(h or home(), "config.toml")
    d = dict(schema.CONFIG_DEFAULTS)
    if os.path.exists(path):
        try:
            got = load_toml(path)
        except (OSError, ValueError) as e:
            raise ConfigError("%s: %s" % (path, e)) from None
        probs = [p for p in schema.validate_config(got) if p.level == "error"]
        if probs:
            raise ConfigError("%s: %s: %s" % (path, probs[0].field, probs[0].msg))
        d.update(got)
    return d


def entry_path(name, h=None):
    return os.path.join(projects_dir(h), name + ".toml")


def entries(h=None):
    """Every readable registry entry, sorted by name. Broken ones are skipped."""
    out = []
    d = projects_dir(h)
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError:
        return out
    for n in names:
        if not n.endswith(".toml") or n.startswith("."):
            continue
        try:
            e = load_toml(os.path.join(d, n))
        except (OSError, ValueError):
            continue
        if not [p for p in schema.validate_registry_entry(e, n[:-5]) if p.level == "error"]:
            out.append(e)
    return out


def get(name, h=None):
    for e in entries(h):
        if e["name"] == name:
            return e
    return None


def register(entry, h=None):
    """Write ``projects/<name>.toml`` atomically. Raises FileExistsError on a clash."""
    path = entry_path(entry["name"], h)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        raise FileExistsError(path)
    save_toml(path, entry)


def unregister(name, h=None):
    path = entry_path(name, h)
    os.unlink(path)
    fsutil.fsync_dir(os.path.dirname(path))


def find_packets(prefix, h=None):
    """[(entry, packet path)] for packets whose WPID starts with ``prefix``."""
    out = []
    for e in entries(h):
        pdir = os.path.join(e["path"], "packets")
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for n in sorted(names):
            if n.startswith(prefix) and schema.is_wpid(n):
                out.append((e, os.path.join(pdir, n)))
    return out


def resolve(target, h=None):
    """A packet directory from a path, a project name, or a (unique prefix of a) WPID."""
    p = os.path.abspath(target)
    if os.path.isfile(os.path.join(p, "status.md")):
        return p
    if os.path.isfile(os.path.join(p, "project.toml")):
        try:
            root = load_toml(os.path.join(p, "project.toml"))["root"]
        except (OSError, ValueError, KeyError) as e:
            raise LookupFailed("%s/project.toml: %s" % (target, e)) from None
        return os.path.join(p, "packets", root)
    if os.sep in target or target in (".", ".."):
        raise LookupFailed("%s is not a packet or project directory" % target)
    e = get(target, h)
    if e is not None:
        return os.path.join(e["path"], "packets", e["root"])
    t = target.lower()
    if len(t) >= 4 and all(c in "0123456789abcdef-" for c in t):
        hits = find_packets(t, h)
        if len(hits) == 1:
            return hits[0][1]
        if len(hits) > 1:
            raise LookupFailed("%s matches %d packets: %s" % (
                target, len(hits), ", ".join(os.path.basename(x[1]) for x in hits[:5])))
    raise LookupFailed("no packet, project or registered project named %r" % target)


