"""The runner home: ``$WPK_HOME`` or ``~/.work-packet`` (spec §2)."""

import os

from . import clock, fsutil, schema
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


def load_config_file(h=None):
    """``config.toml`` as written (validated); ``{}`` if there is none."""
    path = os.path.join(h or home(), "config.toml")
    if not os.path.exists(path):
        return {}
    try:
        got = load_toml(path)
    except (OSError, ValueError) as e:
        raise ConfigError("%s: %s" % (path, e)) from None
    probs = [p for p in schema.validate_config(got) if p.level == "error"]
    if probs:
        raise ConfigError("%s: %s: %s" % (path, probs[0].field, probs[0].msg))
    return got


def load_config(h=None):
    """``config.toml`` merged over the defaults. A missing file is all defaults."""
    d = dict(schema.CONFIG_DEFAULTS)
    d.update(load_config_file(h))
    return d


def load_server_config(h=None):
    """The ``[server]`` table of ``config.toml`` over its defaults."""
    d = dict(schema.SERVER_DEFAULTS)
    d.update(load_config_file(h).get("server") or {})
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


LOCK_WAIT_S = 5.0
LOCK_STALE_S = 30.0


class EntryBusy(Exception):
    pass


def _lock_entry(name, h):
    """An ``O_EXCL`` lock file beside the entry; waits up to ``LOCK_WAIT_S``. A
    lock older than ``LOCK_STALE_S`` is from a writer that died, and is taken."""
    import time
    path = os.path.join(projects_dir(h), ".%s.lock" % name)
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, b"%d\n" % os.getpid())
            os.close(fd)
            return path
        except FileExistsError:
            try:
                if time.time() - os.stat(path).st_mtime > LOCK_STALE_S:
                    os.unlink(path)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise EntryBusy("%s is locked by another writer" % path) from None
            time.sleep(0.01)


def update(name, fn, h=None):
    """Change ``projects/<name>.toml``: read it, ``fn(entry)`` (changes it in
    place; may return a value), validate, write. Under the entry's lock, so two
    writers (the board and the CLI) never lose each other's change. Returns
    ``fn``'s value. Raises LookupFailed, ConfigError (invalid result), EntryBusy."""
    path = entry_path(name, h)
    if not os.path.exists(path):
        raise LookupFailed("no registered project named %r" % (name,))
    lock = _lock_entry(name, h)
    try:
        try:
            e = load_toml(path)
        except (OSError, ValueError) as ex:
            raise ConfigError("%s: %s" % (path, ex)) from None
        import copy
        before = copy.deepcopy(e)
        got = fn(e)
        probs = [p for p in schema.validate_registry_entry(e, name) if p.level == "error"]
        if probs:
            raise ConfigError("%s: %s" % (probs[0].field, probs[0].msg))
        if e != before:
            save_toml(path, e)
        return got
    finally:
        try:
            os.unlink(lock)
        except FileNotFoundError:
            pass


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




# --- boards (docs/boards.md) ------------------------------------------------

DEFAULT_BOARD = "main"


class BoardError(Exception):
    pass


def boards_dir(h=None):
    return os.path.join(h or home(), "boards")


def boards(h=None):
    """Every board, ``main`` first and the rest by name: ``[{"name", "created"?, "title"?}]``."""
    out = [{"name": DEFAULT_BOARD}]
    d = boards_dir(h)
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError:
        return out
    for n in names:
        if not n.endswith(".toml") or n.startswith(".") or n[:-5] == DEFAULT_BOARD:
            continue
        try:
            b = load_toml(os.path.join(d, n))
        except (OSError, ValueError):
            continue
        if not [p for p in schema.validate_board(b, n[:-5]) if p.level == "error"]:
            out.append(b)
    return out


def board_of(entry, names=None):
    """The board a registry entry is on; ``main`` if it names none, or one not in ``names``."""
    b = entry.get("board") or DEFAULT_BOARD
    return b if names is None or b in names else DEFAULT_BOARD


def new_board(name, title=None, h=None):
    if not schema.is_name(name):
        raise BoardError("%r is not a board name; use [a-z0-9][a-z0-9_-]*" % (name,))
    path = os.path.join(boards_dir(h), name + ".toml")
    if name == DEFAULT_BOARD or os.path.exists(path):
        raise BoardError("there is already a board named %s" % name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    b = {"name": name, "created": schema.format_timestamp(clock.now())}
    if title:
        b["title"] = title
    save_toml(path, b)
    return b


def _set_board(e, board, h):
    def change(e):
        if board == DEFAULT_BOARD:
            e.pop("board", None)
        else:
            e["board"] = board
    update(e["name"], change, h)


def move(project, board, h=None):
    """Put a project on a board. Returns the board it was on."""
    e = get(project, h)
    if e is None:
        raise BoardError("no registered project named %r" % (project,))
    names = [b["name"] for b in boards(h)]
    if board not in names:
        raise BoardError("no board named %r" % (board,))
    was = board_of(e, names)
    if was != board:
        _set_board(e, board, h)
    return was


def delete_board(name, h=None):
    """Remove a board; its projects go to ``main``. Returns their names."""
    if name == DEFAULT_BOARD:
        raise BoardError("%s is the default board and cannot be deleted" % name)
    path = os.path.join(boards_dir(h), name + ".toml")
    if not os.path.exists(path):
        raise BoardError("no board named %r" % (name,))
    moved = [e for e in entries(h) if e.get("board") == name]
    for e in moved:
        _set_board(e, DEFAULT_BOARD, h)
    os.unlink(path)
    fsutil.fsync_dir(os.path.dirname(path))
    return [e["name"] for e in moved]
