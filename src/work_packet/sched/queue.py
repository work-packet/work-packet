"""The due list in the order the scheduler would start it (docs/scheduler.md §3.3)."""

import os
from dataclasses import dataclass, field
from typing import Optional

from .. import schema, scheduler
from ..project import ProjectError, load_project
from . import classes
from .config import Size, allowed_sizes, size as size_of


@dataclass
class Project:
    """What the scheduler needs from a project: its entry and ``project.toml``."""
    name: str
    entry: dict
    sizes: list                      # allowed size names (config-known)
    weight: float = 1.0
    max_cores: int = 0
    hold: bool = False
    problem: Optional[str] = None    # project.toml unreadable
    limits: dict = field(default_factory=dict)   # config.PROJECT_KEYS: caps, step budget


@dataclass
class Item:
    project: str
    wpid: str
    path: str
    state: str
    due: str                         # when it became due (sort key within a project)
    cls: str                         # effective class
    cls_from: str                    # packet | project | default
    aged: str                        # the class it is ordered by
    size: Size
    size_from: str                   # memento | packet | project | default
    next: bool = False               # run next, once
    waited_s: float = 0.0
    notes: list = field(default_factory=list)

    @property
    def key(self):
        return (self.project, self.wpid)


def projects(entries, cfg):
    out = {}
    dflt = cfg.get("project_defaults") or {}
    for e in entries:
        p = Project(name=e["name"], entry=e, sizes=[], hold=e.get("sched") == "hold",
                    limits=dict(dflt))
        try:
            d = load_project(e["path"])
            p.limits.update({k: d[k] for k in dflt if k in d})
            p.weight = float(d.get("weight", 1.0))
            p.max_cores = int(d.get("max_cores", 0))
            p.sizes = allowed_sizes(cfg, d.get("sizes"))
        except ProjectError as ex:
            p.problem = str(ex)
            p.sizes = allowed_sizes(cfg, None)
        out[e["name"]] = p
    return out


def choose_size(cfg, proj, wpid, next_size):
    """(Size, where it came from, notes): the memento's ``size:`` for this step,
    else the packet's, the project's, ``[sched] default_size`` (§5.2)."""
    notes = []
    if next_size:
        if next_size in proj.sizes:
            return size_of(cfg, next_size), "memento", notes
        notes.append("asked for size %s, which the project no longer allows" % next_size)
    for name, where in ((classes.packet_settings(proj.entry, wpid).get("size"), "packet"),
                        (proj.entry.get("size"), "project")):
        if name:
            s = size_of(cfg, name)
            if s is not None:
                return s, where, notes
            notes.append("%s size %s is not in [sched.sizes]" % (where, name))
    s = size_of(cfg, cfg["default_size"]) or Size(cfg["default_size"], 1)
    return s, "default", notes


def build(entries, cfg, now, projs=None):
    """Every due packet as an Item (leased ones are left out, as by ``scheduler.due``)."""
    projs = projs if projs is not None else projects(entries, cfg)
    age_after = schema.parse_duration(cfg["age_after"])
    out = []
    for d in scheduler.due(entries, now):
        proj = projs[d.project]
        cls, where = classes.effective(proj.entry, d.wpid)
        try:
            waited = max(0.0, (now - schema.parse_timestamp(d.due)).total_seconds())
        except ValueError:
            waited = 0.0
        sz, sz_from, notes = choose_size(cfg, proj, d.wpid, d.next_size)
        out.append(Item(project=d.project, wpid=d.wpid, path=d.path, state=d.state, due=d.due,
                        cls=cls, cls_from=where, aged=classes.aged(cls, waited, age_after),
                        size=sz, size_from=sz_from,
                        next=bool(classes.packet_settings(proj.entry, d.wpid).get("next")),
                        waited_s=waited, notes=notes))
    return out


def order(items, usage, projs):
    """Run next first; then by aged class; within a class the project with the
    fewest cores in use per unit of weight; within a project the oldest due."""
    def key(it):
        p = projs.get(it.project)
        share = usage.project_cores(it.project) / (p.weight if p else 1.0)
        return (0 if it.next else 1, classes.VALUE[it.aged], share, it.due, it.project, it.wpid)
    return sorted(items, key=key)


def exists(path):
    return os.path.isdir(path)
