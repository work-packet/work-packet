"""A project directory and the settings a step runs with (spec §3)."""

import os
from dataclasses import dataclass, field
from typing import List, Optional

from . import clock, profiles, registry, schema
from .tomlio import load_toml

LIMITS = ("step_timeout", "max_attempts", "step_budget_usd", "step_context_tokens",
          "carry_session", "carry_ttl", "carry_factor", "budget_usd_per_day",
          "budget_quota_per_week", "max_steps_per_hour")


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
    step_context_tokens: int = 80000
    carry_session: bool = False
    carry_ttl_s: int = 3300
    carry_factor: float = 4.0
    harness: str = "claude"
    profile: Optional[str] = None                 # named in project.toml, else chosen by model
    profiles: list = field(default_factory=list)  # profiles.load() order
    explicit: frozenset = frozenset()             # keys set in config.toml or project.toml
    allowed_tools: List[str] = field(default_factory=list)
    permission_mode: str = "acceptEdits"
    agent_md: Optional[str] = None
    setup: dict = field(default_factory=dict)     # [setup] (docs/setup.md §4)
    sizes: Optional[List[str]] = None             # job sizes steps may ask for (scheduler.md §5.2)
    weight: float = 1.0                           # fair share (§3.3)
    max_cores: int = 0                            # 0: no project limit
    budget_usd_per_day: float = 0.0               # caps (§4.5); 0: none
    budget_quota_per_week: float = 0.0
    max_steps_per_hour: int = 0


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
        raw = dict(config) if config is not None else registry.load_config_file()
    except registry.ConfigError as e:
        raise ProjectError(str(e)) from None
    cfg = dict(schema.CONFIG_DEFAULTS)
    cfg.update(raw)
    d = load_project(proj)
    try:
        profs = profiles.load(raw.get("profiles"))
    except profiles.ProfileError as e:
        raise ProjectError(str(e)) from None
    for k in ("model", "harness") + LIMITS:
        if k in d:
            cfg[k] = d[k]
    perms = dict(schema.PERMISSION_DEFAULTS)
    perms.update(d.get("permissions", {}))
    agent = os.path.join(proj, "agent.md")
    return Settings(
        project_dir=proj, name=d["name"], root=d["root"], tz=d.get("tz"),
        model=cfg["model"], step_timeout_s=schema.parse_duration(cfg["step_timeout"]),
        max_attempts=cfg["max_attempts"], step_budget_usd=float(cfg["step_budget_usd"]),
        step_context_tokens=cfg["step_context_tokens"], carry_session=cfg["carry_session"],
        carry_ttl_s=schema.parse_duration(cfg["carry_ttl"]),
        carry_factor=float(cfg["carry_factor"]), harness=cfg["harness"],
        profile=d.get("profile"), profiles=profs,
        explicit=frozenset(k for k in profiles.VALUE_KEYS if k in raw or k in d),
        allowed_tools=list(perms["allowed_tools"]),
        permission_mode=perms["permission_mode"],
        agent_md=agent if os.path.isfile(agent) else None,
        setup=d.get("setup") or {},
        sizes=list(d["sizes"]) if d.get("sizes") else None,
        weight=float(d.get("weight", 1.0)), max_cores=int(d.get("max_cores", 0)),
        budget_usd_per_day=float(cfg["budget_usd_per_day"]),
        budget_quota_per_week=float(cfg["budget_quota_per_week"]),
        max_steps_per_hour=int(cfg["max_steps_per_hour"]))


# --- wpk new and wpk adopt ---------------------------------------------------------

TEMPLATE = "blank@1"
SETUP_DIRS = ("state", "identity", "work")    # at the project root (docs/setup.md §10)
SETUP_REASON = "setup"        # PAUSED for setup until L1's HELD/setup (docs/setup.md §8)


def held_for_setup(meta):
    return meta.get("state") == "PAUSED" and meta.get("reason") == SETUP_REASON


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

    @property
    def packet(self):
        return os.path.join(self.path, "packets", self.root)


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


def new(name, prompt=None, path=None, model=None, tz=None, paused=False, dry_run=False, h=None,
        extra=None):
    """``docs/runner.md`` ``wpk new`` steps 1-4 with the blank template.

    With no ``prompt`` the root is held for setup (docs/setup.md): ``PAUSED``
    with reason ``setup``, an empty memento and an empty ``prompt.md``. Either
    way the project gets the structure you set it up in (docs/setup.md §10):
    ``prompt.md``, ``state/``, ``identity/`` and ``work/``. ``extra``
    holds more ``project.toml`` keys (``new --from-setup``).

    The project is built in a hidden sibling directory and renamed into
    place, and the registry entry is written last, so a ``wpk new`` that
    dies part-way leaves no project and no entry (E5).
    """
    import uuid
    from . import clock, faults, fsutil
    from .packet import Packet, new_status

    path = os.path.abspath(path or name)
    if prompt is not None and not prompt.strip():
        raise ProjectError("the prompt is empty")
    _check_new(name, path, tz, h)
    try:
        cfg = registry.load_config(h)
    except registry.ConfigError as e:
        raise ProjectError(str(e)) from None
    root = str(uuid.uuid4())
    extra = dict(extra or {})
    model = model or extra.pop("model", None) or cfg["model"]
    extra.pop("model", None)
    perms = dict(schema.PERMISSION_DEFAULTS)
    perms.update(extra.pop("permissions", {}))
    rel = os.path.join("packets", root)
    files = ["project.toml", "prompt.md"] + [d + "/" for d in SETUP_DIRS] + [
        rel + "/status.md", rel + "/memento.md", rel + "/journal.jsonl", rel + "/state/"]
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
    ptoml.update(extra)
    probs = [p for p in schema.validate_project(ptoml) if p.level == "error"]
    if probs:
        raise ProjectError("project.toml: %s: %s" % (probs[0].field, probs[0].msg))
    from .tomlio import save_toml
    save_toml(os.path.join(tmp, "project.toml"), ptoml)
    for d in SETUP_DIRS:
        os.makedirs(os.path.join(tmp, d))
    if prompt:
        text = prompt if prompt.endswith("\n") else prompt + "\n"
    else:
        text = ""                 # held for setup: you write prompt.md (or `wpk instruct`)
    fsutil.atomic_write(os.path.join(tmp, "prompt.md"), text)
    pkt = Packet(os.path.join(tmp, "packets", root))
    os.makedirs(pkt.state_dir)
    st = new_status(root, name, model, now)
    if not prompt:
        st.update(state="PAUSED", reason=SETUP_REASON)
    elif paused:
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


# --- wpk allow / deny / set (long-running.md §6) ---------------------------------

SETTABLE = ("model", "harness", "profile", "tz") + LIMITS + schema.PROJECT_SCHED_KEYS
PERMISSION_KEYS = ("permission_mode",)


def parse_value(raw):
    """A ``key=value`` value: a TOML literal (``3``, ``true``, ``"x"``), else a string."""
    from .tomlio import tomllib
    try:
        return tomllib.loads("v = " + raw)["v"]
    except ValueError:
        return raw


def change_settings(proj, change, by):
    """Apply ``change(d) -> [description, ...]`` to ``project.toml`` and save it.

    The result must pass ``schema.validate_project``. The root packet's lease
    is held while writing, so settings never change under a running step, and
    a ``config`` record goes in the root's journal. Returns the descriptions;
    an empty list means nothing changed and nothing was written.
    """
    from . import journal
    from .lease import Lease, LeaseHeld
    from .packet import Packet
    from .tomlio import save_toml
    d = load_project(proj)
    pkt = Packet(os.path.join(proj, "packets", d["root"]))
    try:
        meta, _ = pkt.load_status()
        lease = Lease(pkt.lease_path, meta["step"] + 1, 0, 60).acquire()
    except LeaseHeld as e:
        raise ProjectError("a step is running (%s); change the settings when it ends" % e) \
            from None
    except OSError as e:
        raise ProjectError(str(e)) from None
    try:
        d = load_project(proj)
        changes = change(d)
        if not changes:
            return []
        probs = [p for p in schema.validate_project(d) if p.level == "error"]
        if probs:
            raise ProjectError("%s: %s" % (probs[0].field, probs[0].msg))
        save_toml(os.path.join(proj, "project.toml"), d)
        journal.append(pkt.journal_path, {"type": "config",
                                          "t": schema.format_timestamp(clock.now()),
                                          "by": by, "changes": changes})
        return changes
    finally:
        lease.release()


def allow(proj, tools, by):
    def change(d):
        perm = d.setdefault("permissions", dict(schema.PERMISSION_DEFAULTS))
        cur = perm.setdefault("allowed_tools", list(schema.PERMISSION_DEFAULTS["allowed_tools"]))
        added = [t for t in tools if t not in cur]
        cur.extend(added)
        return ["allow %s" % t for t in added]
    return change_settings(proj, change, by)


def deny(proj, tools, by):
    def change(d):
        perm = d.setdefault("permissions", dict(schema.PERMISSION_DEFAULTS))
        cur = perm.setdefault("allowed_tools", list(schema.PERMISSION_DEFAULTS["allowed_tools"]))
        gone = [t for t in tools if t in cur]
        perm["allowed_tools"] = [t for t in cur if t not in gone]
        return ["deny %s" % t for t in gone]
    return change_settings(proj, change, by)


def set_values(proj, pairs, by):
    """``pairs``: ``[(key, raw)]``. An empty ``raw`` removes the key (back to the default).

    Each packet keeps its own model in ``status.md``, so a new ``model`` is
    passed on to packets too: see ``follow_model``.
    """
    for k, _ in pairs:
        if k not in SETTABLE + PERMISSION_KEYS:
            raise ProjectError("cannot set %r; settable: %s" % (
                k, ", ".join(SETTABLE + PERMISSION_KEYS)))
    old_model = settings(proj).model if any(k == "model" for k, _ in pairs) else None

    def change(d):
        out = []
        for k, raw in pairs:
            table = d.setdefault("permissions", dict(schema.PERMISSION_DEFAULTS)) \
                if k in PERMISSION_KEYS else d
            if raw == "":
                if k in table and k not in PERMISSION_KEYS:
                    del table[k]
                    out.append("unset %s" % k)
                continue
            v = parse_value(raw)
            if k == "sizes" and isinstance(v, str):     # wpk set sizes=look,sim
                v = [x.strip() for x in v.split(",") if x.strip()]
            if table.get(k) != v:
                table[k] = v
                out.append("set %s = %r" % (k, v))
        return out
    out = change_settings(proj, change, by)
    if old_model is not None:
        out += follow_model(proj, old_model, settings(proj).model, by)
    return out


def follow_model(proj, old, new, by):
    """Give ``new`` to the root packet and to every packet on ``old``, the
    project's model before the change; a packet whose step or parent chose
    another model keeps it. The root always follows, so this also mends a
    ``project.toml`` changed by hand. A running packet is left alone and
    named. Returns descriptions."""
    from . import frontmatter, journal
    from .lease import Lease, LeaseHeld
    from .packet import Packet
    root = load_project(proj)["root"]
    pdir = os.path.join(proj, "packets")
    out = []
    for w in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else ():
        pkt = Packet(os.path.join(pdir, w))
        try:
            meta, _ = pkt.load_status()
        except (OSError, frontmatter.FrontMatterError):
            continue
        if meta.get("model") == new or (w != root and meta.get("model") != old):
            continue
        try:
            lease = Lease(pkt.lease_path, meta["step"] + 1, 0, 60).acquire()
        except LeaseHeld:
            out.append("packet %s is running; it keeps model %s" % (w[:8], meta.get("model")))
            continue
        try:
            meta, body = pkt.load_status()
            was = meta.get("model")
            meta.update(model=new, updated=schema.format_timestamp(clock.now()))
            pkt.save_status(meta, body)
            change = "model %s -> %s" % (was, new)
            journal.append(pkt.journal_path, {"type": "config",
                                              "t": meta["updated"], "by": by,
                                              "changes": [change]})
            out.append("packet %s: %s" % (w[:8], change))
        finally:
            lease.release()
    return out
