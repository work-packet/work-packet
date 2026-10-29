"""Plugins: code a site package adds through entry points (design E1).

Each group is read once per process. ``[plugins] enable = [...]`` /
``disable = [...]`` in ``config.toml`` picks which are used (default: all
installed); a name there is the entry-point name or the name of the
distribution that provides it. ``[plugins.<name>]`` is that plugin's own
table, given to it by ``table(name)``; upstream checks only that it is a table.
A plugin that does not load is kept, with the error, and listed by ``wpk doctor``.
"""
from dataclasses import dataclass
from typing import Any, Optional

GROUPS = (
    "work_packet.harnesses",       # a harness adapter (E10)
    "work_packet.starters",        # a New-task starter
    "work_packet.cli",             # a command group (E2)
    "work_packet.credentials",     # a credential kind (E3)
    "work_packet.step_hooks",      # code around a harness run (E4)
    "work_packet.cost",            # a cost source (E5)
    "work_packet.budget",          # a budget provider (E6)
    "work_packet.dash",            # panels and routes (E7)
    "work_packet.sched_backends",  # a batch backend (E8)
)


@dataclass
class Plugin:
    name: str
    group: str
    module: str
    value: str = ""
    version: str = ""
    dist: str = ""
    obj: Any = None
    error: Optional[str] = None
    enabled: bool = True

    @property
    def ok(self):
        return self.enabled and self.error is None


_cache = {}         # group -> [Plugin]
_config = []        # [the [plugins] table], read once


def _reset():
    """Forget what was read (tests)."""
    _cache.clear()
    _config.clear()


def config():
    """The ``[plugins]`` table of config.toml; ``{}`` if there is none or it
    does not load (the config check reports that)."""
    if not _config:
        try:
            from . import registry
            t = registry.load_config_file().get("plugins", {})
        except Exception:             # noqa: BLE001  a bad config must not stop plugin loading
            t = {}
        _config.append(t if isinstance(t, dict) else {})
    return _config[0]


def table(name):
    """``[plugins.<name>]`` as a dict (``{}`` if absent)."""
    t = config().get(name)
    return dict(t) if isinstance(t, dict) else {}


def _enabled(names):
    c = config()
    enable, disable = c.get("enable"), c.get("disable") or []
    if any(n in disable for n in names if n):
        return False
    return enable is None or any(n in enable for n in names if n)


def _entry_points(group):
    try:
        from importlib.metadata import entry_points
        return list(entry_points(group=group))
    except Exception:                 # noqa: BLE001  (old Pythons, broken metadata)
        return []


def load(group):
    """The plugins of ``group``, in entry-point order. Disabled ones are listed
    (``enabled`` False, not loaded); a failed load has ``error`` set."""
    if group in _cache:
        return _cache[group]
    out = []
    for ep in _entry_points(group):
        d = getattr(ep, "dist", None)
        p = Plugin(ep.name, group, getattr(ep, "module", None) or ep.value.split(":")[0],
                   value=ep.value, version=getattr(d, "version", "") or "",
                   dist=getattr(d, "name", "") or "")
        p.enabled = _enabled((p.name, p.dist))
        if p.enabled:
            try:
                p.obj = ep.load()
            except Exception as e:    # noqa: BLE001  a broken plugin must not break wpk
                p.error = "%s: %s" % (type(e).__name__, e)
        out.append(p)
    _cache[group] = out
    return out


def loaded(group):
    """{name: object} of the plugins of ``group`` that loaded."""
    return {p.name: p.obj for p in load(group) if p.ok}


def everything():
    """Every plugin of every group (for ``wpk doctor``)."""
    return [p for g in GROUPS for p in load(g)]


__all__ = ["GROUPS", "Plugin", "load", "loaded", "everything", "config", "table"]
