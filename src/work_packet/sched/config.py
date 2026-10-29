"""``[sched]``: sizes and pool limits (docs/scheduler.md §5.2, §10)."""

import os
from dataclasses import dataclass, field
from typing import Optional, Tuple

from .. import registry, schema
from ..tomlio import load_toml


def sched_dir(h=None):
    return os.path.join(h or registry.home(), "sched")


_merge = registry.merge_tables


def load(h=None, raw=None):
    """``[sched]`` over ``schema.SCHED_DEFAULTS``. Sub-tables merge key by key,
    so ``[sched.sizes.sim]`` adds a size and keeps ``look``. ``raw``: an
    already loaded ``config.toml`` (else it is read; ConfigError if bad)."""
    if raw is None:
        raw = registry.load_config_file(h)
    cfg = _merge(schema.SCHED_DEFAULTS, raw.get("sched") or {})
    cfg["budget"] = _merge(schema.SCHED_BUDGET_DEFAULTS, cfg.get("budget") or {})
    cfg["max_concurrent"] = raw.get("max_concurrent", schema.CONFIG_DEFAULTS["max_concurrent"])
    cfg["step_timeout"] = raw.get("step_timeout", schema.CONFIG_DEFAULTS["step_timeout"])
    cfg["project_defaults"] = {k: raw.get(k, schema.CONFIG_DEFAULTS[k]) for k in PROJECT_KEYS}
    return cfg


# What the scheduler reads from each project.toml, with config.toml's value as default.
PROJECT_KEYS = ("step_budget_usd", "budget_usd_per_day", "budget_quota_per_week",
                "max_steps_per_hour")


@dataclass(frozen=True)
class Size:
    name: str
    cpus: int
    mem_mb: int = 0                  # 0: not asked for
    time_s: Optional[int] = None     # None: the step timeout
    partition: str = ""
    queue: str = ""
    extra: Tuple[str, ...] = ()
    resources: str = ""              # LSF: merged into the one -R
    constraint: str = ""             # SLURM: --constraint
    env: str = ""                    # lines run after node_env, for jobs of this size
    label: str = ""                  # shown in pickers in place of the name
    description: str = ""            # what the size is for: pickers, the prompt

    def describe(self):
        out = "%d core%s" % (self.cpus, "" if self.cpus == 1 else "s")
        if self.mem_mb:
            out += ", %s" % fmt_mem(self.mem_mb)
        if self.time_s:
            out += ", up to %s" % fmt_dur(self.time_s)
        return out

    @property
    def text(self):
        """A picker's option text."""
        return self.label or self.name

    @property
    def title(self):
        """A picker's tooltip: the shape, then what it is for."""
        return self.describe() + (": " + self.description if self.description else "")


def fmt_mem(mb):
    if mb and mb % (1024 * 1024) == 0:
        return "%dT" % (mb // (1024 * 1024))
    if mb and mb % 1024 == 0:
        return "%dG" % (mb // 1024)
    return "%dM" % mb


def fmt_dur(s):
    if s % 3600 == 0:
        return "%dh" % (s // 3600)
    if s % 60 == 0:
        return "%dm" % (s // 60)
    return "%ds" % s


def _size(name, t):
    return Size(name=name, cpus=int(t["cpus"]),
                mem_mb=schema.parse_mem(t["mem"]) if t.get("mem") else 0,
                time_s=schema.parse_duration(t["time"]) if t.get("time") else None,
                partition=t.get("partition", ""), queue=t.get("queue", ""),
                extra=tuple(t.get("extra") or ()),
                resources=t.get("resources", ""), constraint=t.get("constraint", ""),
                env=t.get("env", ""), label=t.get("label", ""),
                description=t.get("description", ""))


def sizes(cfg):
    """{name: Size}, in config order."""
    return {n: _size(n, t) for n, t in (cfg.get("sizes") or {}).items()}


def size(cfg, name):
    """The Size called ``name``, or None."""
    t = (cfg.get("sizes") or {}).get(name)
    return _size(name, t) if isinstance(t, dict) else None


def allowed_sizes(cfg, project_sizes):
    """The size names a project's steps may ask for: its ``sizes``, else the
    default size; names the config does not know are left out."""
    known = cfg.get("sizes") or {}
    names = list(project_sizes) if project_sizes else [cfg["default_size"]]
    return [n for n in names if n in known]


# --- pool limits and the grant (scheduler.md §14) -------------------------------

@dataclass
class Limits:
    cores: int = 0                   # 0: no limit
    mem_mb: int = 0
    jobs: int = 0
    budget_amount: Optional[float] = None    # None: [sched.budget] amount
    grant: Optional[dict] = None             # the grant in force, if one lowered anything
    notes: list = field(default_factory=list)

    def describe(self):
        def lim(v, f=str):
            return f(v) if v else "no limit"
        return "cores %s, mem %s, jobs %s" % (lim(self.cores), lim(self.mem_mb, fmt_mem),
                                             lim(self.jobs))


def grant_path(h=None):
    return os.path.join(sched_dir(h), "grant.toml")


GRANT_KEYS = ("cores", "mem", "jobs", "budget", "by", "expires")


def validate_grant(d):
    out = schema._unknown(d, GRANT_KEYS)
    for k in ("cores", "jobs"):
        if k in d and not (schema.is_int(d[k]) and d[k] >= 0):
            out.append(schema._err(k, "must be a whole number >= 0"))
    if "mem" in d:
        try:
            schema.parse_mem(d["mem"])
        except ValueError as e:
            out.append(schema._err("mem", str(e)))
    b = d.get("budget", {})
    if not isinstance(b, dict) or set(b) - {"amount"} or not isinstance(
            b.get("amount", 0), (int, float)) or isinstance(b.get("amount"), bool):
        out.append(schema._err("budget", "must be a table with only amount = <number>"))
    if "by" in d and not isinstance(d["by"], str):
        out.append(schema._err("by", "must be a principal string"))
    if "expires" in d and not schema.is_timestamp(d["expires"]):
        out.append(schema._err("expires", "must be a UTC timestamp"))
    return out


def read_grant(h=None):
    """(grant dict or None, problem or None)."""
    p = grant_path(h)
    if not os.path.exists(p):
        return None, None
    try:
        d = load_toml(p)
    except (OSError, ValueError) as e:
        return None, "%s: %s" % (p, e)
    probs = [x for x in validate_grant(d) if x.level == "error"]
    if probs:
        return None, "%s: %s: %s" % (p, probs[0].field, probs[0].msg)
    return d, None


def _lower(a, b):
    """The lower of two limits where 0 means none."""
    if not a:
        return b
    if not b:
        return a
    return min(a, b)


def pool_limits(cfg, h=None, now=None, jobs=None):
    """The pool's limits: ``[sched]`` cores, mem and jobs (jobs 0 is
    ``max_concurrent``; ``jobs`` overrides both, as ``wpk tick -j``), each
    lowered by an unexpired ``sched/grant.toml``. A grant never raises a limit.
    An expired grant is ignored, with one ``grant_expired`` event."""
    from .. import clock
    from . import events
    now = now or clock.now()
    lim = Limits(cores=cfg.get("cores") or 0,
                 mem_mb=schema.parse_mem(cfg["mem"]) if cfg.get("mem") else 0,
                 jobs=jobs or cfg.get("jobs") or cfg.get("max_concurrent") or 1)
    g, bad = read_grant(h)
    if bad:
        lim.notes.append("grant ignored: %s" % bad)
        return lim
    if g is None:
        return lim
    if g.get("expires") and schema.parse_timestamp(g["expires"]) <= now:
        _note_expired(h, g)
        lim.notes.append("grant expired %s; config limits apply" % g["expires"])
        return lim
    before = (lim.cores, lim.mem_mb, lim.jobs)
    lim.cores = _lower(lim.cores, g.get("cores", 0))
    lim.mem_mb = _lower(lim.mem_mb, schema.parse_mem(g["mem"]) if g.get("mem") else 0)
    lim.jobs = _lower(lim.jobs, g.get("jobs", 0))
    amt = (g.get("budget") or {}).get("amount")
    cfg_amt = (cfg.get("budget") or {}).get("amount") or 0
    if amt is not None and (not cfg_amt or amt < cfg_amt):
        lim.budget_amount = float(amt)
    if (lim.cores, lim.mem_mb, lim.jobs) != before or lim.budget_amount is not None:
        lim.grant = g
    return lim


def _note_expired(h, g):
    """One ``grant_expired`` event per grant (keyed by its ``expires``)."""
    from .. import fsutil
    from . import events
    mark = os.path.join(sched_dir(h), "grant-expired")
    try:
        with open(mark) as fp:
            if fp.read().strip() == g["expires"]:
                return
    except OSError:
        pass
    os.makedirs(sched_dir(h), exist_ok=True)
    fsutil.atomic_write(mark, g["expires"] + "\n")
    events.append("grant_expired", h=h, by=g.get("by", "unknown"), expires=g["expires"])
