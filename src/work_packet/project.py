"""A project directory and the settings a step runs with (spec §3)."""

import os
from dataclasses import dataclass, field
from typing import List, Optional

from . import registry, schema
from .tomlio import load_toml

LIMITS = ("step_timeout", "max_attempts", "step_budget_usd")


class ProjectError(Exception):
    pass


@dataclass
class Settings:
    project_dir: str
    name: str
    root: str
    tz: Optional[str]
    model: str
    step_timeout_s: int
    max_attempts: int
    step_budget_usd: float
    allowed_tools: List[str] = field(default_factory=list)
    permission_mode: str = "acceptEdits"
    agent_md: Optional[str] = None


def project_of(packet_path):
    """The project directory holding ``packets/<WPID>``, or None."""
    pdir = os.path.dirname(os.path.abspath(packet_path))
    proj = os.path.dirname(pdir)
    if os.path.basename(pdir) == "packets" and \
            os.path.isfile(os.path.join(proj, "project.toml")):
        return proj
    return None


def load_project(proj):
    path = os.path.join(proj, "project.toml")
    try:
        d = load_toml(path)
    except (OSError, ValueError) as e:
        raise ProjectError("%s: %s" % (path, e)) from None
    probs = [p for p in schema.validate_project(d) if p.level == "error"]
    if probs:
        raise ProjectError("%s: %s: %s" % (path, probs[0].field, probs[0].msg))
    return d


def settings(proj, config=None):
    """Defaults, then the runner's config.toml, then project.toml."""
    try:
        cfg = dict(config) if config is not None else registry.load_config()
    except registry.ConfigError as e:
        raise ProjectError(str(e)) from None
    d = load_project(proj)
    for k in ("model",) + LIMITS:
        if k in d:
            cfg[k] = d[k]
    perms = dict(schema.PERMISSION_DEFAULTS)
    perms.update(d.get("permissions", {}))
    agent = os.path.join(proj, "agent.md")
    return Settings(
        project_dir=proj, name=d["name"], root=d["root"], tz=d.get("tz"),
        model=cfg["model"], step_timeout_s=schema.parse_duration(cfg["step_timeout"]),
        max_attempts=cfg["max_attempts"], step_budget_usd=float(cfg["step_budget_usd"]),
        allowed_tools=list(perms["allowed_tools"]),
        permission_mode=perms["permission_mode"],
        agent_md=agent if os.path.isfile(agent) else None)
