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


# --- wpk new and wpk adopt ---------------------------------------------------------

TEMPLATE = "blank@1"


@dataclass
class Plan:
    """What ``wpk new`` will create, for ``--dry-run`` and for the real thing."""
    name: str
    path: str
    root: str
    files: List[str]
    model: str
    tz: Optional[str]
    allowed_tools: List[str]
    permission_mode: str


def _check_new(name, path, tz, h):
    if not schema.is_name(name):
        raise ProjectError("name %r must match [a-z0-9][a-z0-9_-]{0,63}" % name)
    if registry.get(name, h) is not None or os.path.exists(registry.entry_path(name, h)):
        raise ProjectError("a project named %r is already registered" % name)
    if os.path.exists(path) and (not os.path.isdir(path) or os.listdir(path)):
        if os.path.isfile(os.path.join(path, "project.toml")):
            raise ProjectError("%s already holds a project; `wpk adopt %s` registers it"
                               % (path, path))
        raise ProjectError("%s already exists and is not an empty directory" % path)
    if tz is not None and not schema.is_zone(tz):
        raise ProjectError("unknown time zone %r" % tz)


def new(name, prompt, path=None, model=None, tz=None, paused=False, dry_run=False, h=None):
    """``docs/runner.md`` ``wpk new`` steps 1-4 with the blank template.

    The project is built in a hidden sibling directory and renamed into
    place, and the registry entry is written last, so a ``wpk new`` that
    dies part-way leaves no project and no entry (E5).
    """
    import uuid
    from . import clock, faults, fsutil
    from .packet import Packet, new_status

    path = os.path.abspath(path or name)
    if not prompt or not prompt.strip():
        raise ProjectError("the prompt is empty")
    _check_new(name, path, tz, h)
    try:
        cfg = registry.load_config(h)
    except registry.ConfigError as e:
        raise ProjectError(str(e)) from None
    root = str(uuid.uuid4())
    model = model or cfg["model"]
    perms = dict(schema.PERMISSION_DEFAULTS)
    rel = os.path.join("packets", root)
    files = ["project.toml", "prompt.md", rel + "/status.md", rel + "/memento.md",
             rel + "/journal.jsonl", rel + "/state/"]
    plan = Plan(name, path, root, files, model, tz, perms["allowed_tools"],
                perms["permission_mode"])
    if dry_run:
        return plan

    now = schema.format_timestamp(clock.now())
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, ".%s.wpk-new" % os.path.basename(path))
    if os.path.lexists(tmp):
        import shutil
        shutil.rmtree(tmp)
    os.makedirs(os.path.join(tmp, "packets"))
    ptoml = {"name": name, "root": root, "created": now, "template": TEMPLATE}
    if tz is not None:
        ptoml["tz"] = tz
    if model != cfg["model"]:
        ptoml["model"] = model
    ptoml["permissions"] = perms
    from .tomlio import save_toml
    save_toml(os.path.join(tmp, "project.toml"), ptoml)
    text = prompt if prompt.endswith("\n") else prompt + "\n"
    fsutil.atomic_write(os.path.join(tmp, "prompt.md"), text)
    pkt = Packet(os.path.join(tmp, "packets", root))
    os.makedirs(pkt.state_dir)
    st = new_status(root, name, model, now)
    if paused:
        st.update(state="PAUSED", reason="created with --paused")
    pkt.save_status(st)
    fsutil.atomic_write(pkt.memento_path, text)
    fsutil.atomic_write(pkt.journal_path, "")
    faults.point("new-before-rename")
    if os.path.isdir(path):
        os.rmdir(path)            # empty, checked above
    fsutil.rename(tmp, path)
    faults.point("new-before-register")
    registry.register({"name": name, "path": path, "root": root, "created": now,
                       "template": TEMPLATE}, h)
    return plan


def adopt(path, h=None):
    """Register an existing project directory. Returns the entry."""
    path = os.path.abspath(path)
    d = load_project(path)
    if registry.get(d["name"], h) is not None:
        raise ProjectError("a project named %r is already registered" % d["name"])
    if not os.path.isfile(os.path.join(path, "packets", d["root"], "status.md")):
        raise ProjectError("root packet %s is missing" % d["root"])
    e = {"name": d["name"], "path": path, "root": d["root"], "created": d["created"]}
    if "template" in d:
        e["template"] = d["template"]
    registry.register(e, h)
    return e
