"""Profiles: per harness and model, how to size a step and the numbers to use
(docs/harness.md §4). Data, not code: built-ins in ``profiles.toml``, more in
the runner's ``config.toml`` under ``[profiles.<name>]``.
"""

import fnmatch
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .tomlio import load_toml

BUILTIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles.toml")
PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
VALUE_KEYS = ("step_context_tokens", "carry_factor")   # also settable in config/project
PRICE_KEYS = ("input", "output", "cache_write", "cache_read")
KEYS = ("version", "harness", "models", "sizing", "price") + VALUE_KEYS


class ProfileError(Exception):
    pass


@dataclass
class Profile:
    name: str
    version: int
    harness: str
    models: List[str]
    sizing: str
    values: Dict[str, object] = field(default_factory=dict)
    price: Optional[Dict[str, float]] = None

    @property
    def id(self):
        return "%s@%d" % (self.name, self.version)

    def matches(self, harness, model):
        return harness == self.harness and any(fnmatch.fnmatchcase(model, g)
                                               for g in self.models)


def sizings():
    return sorted(n[len("sizing-"):-3] for n in os.listdir(PROMPTS)
                  if n.startswith("sizing-") and n.endswith(".md"))


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(name, d):
    """Problems with one ``[profiles.<name>]`` table, as strings."""
    from .harness import names
    if not isinstance(d, dict):
        return ["must be a table"]
    out = ["unknown key %r" % k for k in d if k not in KEYS]
    if not (isinstance(d.get("version"), int) and not isinstance(d.get("version"), bool)
            and d["version"] >= 1):
        out.append("version: required; an integer >= 1")
    if d.get("harness") not in names():
        out.append("harness: required; one of %s" % ", ".join(names()))
    m = d.get("models")
    if not (isinstance(m, list) and m and all(isinstance(g, str) and g for g in m)):
        out.append("models: required; a list of globs")
    if d.get("sizing") not in sizings():
        out.append("sizing: required; one of %s" % ", ".join(sizings()))
    v = d.get("step_context_tokens")
    if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
        out.append("step_context_tokens: must be an integer >= 0")
    v = d.get("carry_factor")
    if v is not None and not (_num(v) and v > 1):
        out.append("carry_factor: must be a number > 1")
    p = d.get("price")
    if p is not None and not (isinstance(p, dict) and set(p) == set(PRICE_KEYS)
                              and all(_num(x) and x >= 0 for x in p.values())):
        out.append("price: must have %s, each a number >= 0" % ", ".join(PRICE_KEYS))
    return out


def _make(name, d):
    return Profile(name=name, version=d["version"], harness=d["harness"],
                   models=list(d["models"]), sizing=d["sizing"],
                   values={k: d[k] for k in VALUE_KEYS if k in d},
                   price=dict(d["price"]) if "price" in d else None)


def load(extra=None):
    """Profiles in lookup order: ``extra`` (from config.toml), then the built-ins.
    A name in ``extra`` replaces the built-in of that name."""
    builtin = load_toml(BUILTIN).get("profiles", {})
    out, seen = [], set()
    for src in (extra or {}, builtin):
        for name, d in src.items():
            if name in seen:
                continue
            probs = validate(name, d)
            if probs:
                raise ProfileError("profile %s: %s" % (name, probs[0]))
            seen.add(name)
            out.append(_make(name, d))
    return out


def select(profiles, harness, model, name=None):
    """The profile for a step. Raises ProfileError if there is none."""
    if name:
        for p in profiles:
            if p.name == name:
                if p.harness != harness:
                    raise ProfileError("profile %s is for harness %s, not %s"
                                       % (name, p.harness, harness))
                return p
        raise ProfileError("no profile named %r" % name)
    for p in profiles:
        if p.matches(harness, model):
            return p
    raise ProfileError("no profile for harness %s and model %s" % (harness, model))


def value(st, prof, key):
    """A setting from a TOML file wins over the profile, which wins over the default."""
    if key in st.explicit or key not in prof.values:
        return getattr(st, key)
    return prof.values[key]
