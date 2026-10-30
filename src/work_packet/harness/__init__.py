"""Harness adapters: how a step runs under a given agent CLI (harness.md §3).

Everything harness-specific lives in an adapter: the command line, extra
environment, reading the transcript, and the features it has (``Caps``).
The executor and the packet format do not depend on the harness.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Caps:
    system_slot: bool = False          # fixed text can go in the system prompt
    inject: bool = False               # a message can be added mid-step (context.md C3)
    resume: bool = False               # a session can be resumed by id (C4)
    fork: bool = False                 # ... under a new id
    set_session_id: bool = False       # the id can be chosen up front
    reports_cost: bool = False         # the output has a USD cost
    cost_is_chain_total: bool = False  # a resumed run reports the whole chain's cost


@dataclass
class StepSpec:
    """What the executor knows about one model run."""
    model: str
    session_id: str
    permission_mode: str
    allowed_tools: List[str]
    budget_usd: float
    add_dirs: List[str] = field(default_factory=list)
    system_file: Optional[str] = None   # protocol text for the system prompt
    context_limit: int = 0              # C3 soft limit; 0 = off
    marker: Optional[str] = None        # C3 hook's state file
    notes: Optional[tuple] = None       # (inbox, notes.seen) for mid-step notes
    resume_from: Optional[str] = None   # C4: session to resume


class Harness:
    name = "?"
    caps = Caps()
    base_url_var = None     # the environment variable that points the CLI at another API host

    def command(self, spec):
        raise NotImplementedError

    def env(self, spec):
        """Extra environment for the run, over the executor's. An adapter that
        overrides this should apply ``home_env(self.name)`` last."""
        return home_env(self.name)

    def parse(self, transcript_path, res):
        """Fill ``res`` (a ``model.StepResult``) from the run's transcript."""
        raise NotImplementedError

    def models(self):
        """``[(model, label)]`` to offer when choosing one. Not a limit: the
        harness may take others (none of them can list what an account may use)."""
        return []


def read_env_file(path):
    """``KEY=VALUE`` lines of an ``env_file``; blank lines and ``#`` comments
    are skipped, and one pair of quotes round a value is taken off."""
    out = {}
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            k, eq, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if not eq or not k:
                raise ValueError("line %d: not KEY=VALUE" % i)
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k] = v
    return out


def home_env(name, cfg=None, home=None, warn=None):
    """The environment ``[harnesses.<name>]`` in the home's ``config.toml`` sets
    (docs/harness.md): ``env``, then ``env_file`` over it. ``cfg`` is the
    config as written (read if None). An ``env_file`` that others can read,
    or that cannot be read, is left out and ``warn`` (stderr by default) is
    told why: it holds secrets, and its name is all that is said about it."""
    from .. import registry
    if warn is None:
        def warn(msg):
            sys.stderr.write("wpk: %s\n" % msg)
    h = home or registry.home()
    if cfg is None:
        try:
            cfg = registry.load_config_file(h)
        except registry.ConfigError:
            return {}
    t = (cfg.get("harnesses") or {}).get(name) or {}
    out = dict(t.get("env") or {})
    path = t.get("env_file")
    if path:
        path = os.path.join(h, os.path.expanduser(path))
        try:
            mode = os.stat(path).st_mode
            if mode & 0o077:
                warn("[harnesses.%s] env_file %s is mode %o; it must be 0600 (not used)"
                     % (name, path, mode & 0o777))
            else:
                out.update(read_env_file(path))
        except (OSError, ValueError) as e:
            warn("[harnesses.%s] env_file %s: %s (not used)" % (name, path, e))
    return out


GROUP = "work_packet.harnesses"
_plugins = {}       # name -> class, from entry points
_broken = {}        # name -> why it did not load
_loaded = []


def _load():
    """Read the ``work_packet.harnesses`` entry points once. A built-in keeps
    its name; a plugin that does not load is kept in ``broken()``."""
    if _loaded:
        return
    _loaded.append(True)
    from .. import plugins
    for p in plugins.load(GROUP):
        if not p.enabled:
            continue
        if p.name in _REGISTRY:
            p.error = "the name is a built-in harness (%s not used)" % p.value
        elif p.error is None and not (isinstance(p.obj, type) and issubclass(p.obj, Harness)):
            p.error = "TypeError: %s is not a Harness subclass" % p.value
        if p.error is not None:
            _broken[p.name] = p.error
            continue
        _plugins[p.name] = p.obj


def _reset():
    """Forget the entry points read (tests)."""
    from .. import plugins
    from ..sched import backends
    plugins._reset()
    backends._reset()
    _loaded.clear()
    _plugins.clear()
    _broken.clear()


def names():
    _load()
    return sorted(set(_REGISTRY) | set(_plugins))


def get(name):
    """The adapter for ``name``. Raises KeyError for an unknown harness, or
    one whose plugin did not load (the message says why)."""
    _load()
    cls = _REGISTRY.get(name) or _plugins.get(name)
    if cls is None:
        if name in _broken:
            raise KeyError("harness %r did not load: %s" % (name, _broken[name]))
        raise KeyError("no harness %r; there are: %s" % (name, ", ".join(names())))
    return cls()


def broken():
    """Entry-point harnesses that were not used: {name: why}."""
    _load()
    return dict(_broken)


from .claude import Claude  # noqa: E402  (needs Harness above)
from .codex import Codex    # noqa: E402

_REGISTRY = {"claude": Claude, "codex": Codex}

__all__ = ["Caps", "StepSpec", "Harness", "Claude", "Codex", "get", "names", "broken"]
