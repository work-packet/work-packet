"""The runner home: ``$WPK_HOME`` or ``~/.work-packet`` (spec §2)."""

import os

from . import schema
from .tomlio import load_toml


class ConfigError(Exception):
    pass


def home():
    return os.path.abspath(os.environ.get("WPK_HOME") or
                           os.path.join(os.path.expanduser("~"), ".work-packet"))


def load_config(h=None):
    """``config.toml`` merged over the defaults. A missing file is all defaults."""
    path = os.path.join(h or home(), "config.toml")
    d = dict(schema.CONFIG_DEFAULTS)
    if os.path.exists(path):
        got = load_toml(path)
        probs = [p for p in schema.validate_config(got) if p.level == "error"]
        if probs:
            raise ConfigError("%s: %s: %s" % (path, probs[0].field, probs[0].msg))
        d.update(got)
    return d
