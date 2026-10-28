"""``wpk convert``: a v0.2 project into the packet layout
(docs/run-binding-v1.md R9, stage A).

Renames only, on one file system; nothing is copied or deleted but empty
template folders. A tarball of the project is written first. Stage A
converts projects without a repo; a project whose ``work/`` holds anything
is refused for now.

The packet folder is the project directory's parent when that holds nothing
else (``…/solver-research/solver-research`` → ``…/solver-research``), else
the project directory itself. Then:

- the project directory (or, in place, its project files) becomes
  ``<packet>/.work-packet/``, and ``packets/`` becomes ``runs/``;
- the card moves to ``<packet>/<name>.wp.md``;
- the registry entry points at ``.work-packet/``, keeping its other keys;
- the card, the index and the history store are brought up to date.
"""

import os
import subprocess

from . import clock, layout, lease, registry, schema
from .packet import Packet

# What a v0.2 project directory holds besides the card; all of it goes into
# .work-packet/ when converting in place.
PROJECT_ITEMS = ("project.toml", "prompt.md", "agent.md", "state", "identity", "work",
                 ".setup", ".vscode", layout.LEGACY_RUNS)


class ConvertError(Exception):
    pass


def _empty(d):
    return not os.path.isdir(d) or not any(os.scandir(d))


def plan(name, h=None):
    """What converting ``name`` does: a dict; raises ConvertError if it cannot."""
    e = registry.get(name, h)
    if e is None:
        raise ConvertError("no registered project named %r" % name)
    proj = os.path.normpath(e["path"])
    if layout.is_packet_layout(proj):
        raise ConvertError("%s is already in the packet layout" % name)
    if not os.path.isdir(layout.runs_dir(proj)):
        raise ConvertError("%s has no %s/ (archived?)" % (proj, layout.LEGACY_RUNS))
    if not _empty(os.path.join(proj, "work")):
        raise ConvertError("%s/work/ is not empty: projects with repos are not converted yet"
                           % proj)
    runs = sorted(n for n in os.listdir(layout.runs_dir(proj)) if schema.is_wpid(n))
    for w in runs:
        if not _empty(os.path.join(layout.runs_dir(proj), w, "work")):
            raise ConvertError("run %s has a work/: not converted yet" % w[:8])
        lz = lease.read(Packet(layout.run_dir(proj, w)).lease_path)
        if lz is not None and not lease.is_stale(lz):
            raise ConvertError("run %s is stepping; convert when it ends" % w[:8])
    parent = os.path.dirname(proj)
    in_place = os.listdir(parent) != [os.path.basename(proj)]
    folder = proj if in_place else parent
    dot = os.path.join(folder, layout.DOT)
    if os.path.lexists(dot):
        raise ConvertError("%s already exists" % dot)
    card = os.path.join(proj, name + ".wp.md")
    return {"name": name, "from": proj, "folder": folder, "dot": dot, "in_place": in_place,
            "runs": runs, "card": card if os.path.isfile(card) else None,
            "new_card": layout.card_path(dot, name),
            "items": sorted(n for n in os.listdir(proj) if n in PROJECT_ITEMS)
            if in_place else None}


def backup(p, h=None):
    """A tarball of the project directory, before anything moves. Returns its path."""
    d = os.path.join(h or registry.home(), "migration", "convert")
    os.makedirs(d, exist_ok=True)
    ts = schema.format_timestamp(clock.now()).replace(":", "")
    out = os.path.join(d, "%s-%s.tar.gz" % (p["name"], ts))
    src = p["from"]
    r = subprocess.run(["tar", "-czf", out, "-C", os.path.dirname(src), os.path.basename(src)],
                       capture_output=True, text=True)
    if r.returncode:
        raise ConvertError("backup failed: %s" % (r.stderr or r.stdout).strip())
    return out


def convert(name, dry_run=False, h=None):
    """Convert ``name``. Returns the plan, with ``backup`` and ``checks`` added."""
    p = plan(name, h)
    if dry_run:
        return p
    p["backup"] = backup(p, h)
    src, dot = p["from"], p["dot"]
    if p["in_place"]:
        tmp = os.path.join(src, ".work-packet.convert")
        os.mkdir(tmp)
        for n in p["items"]:
            os.rename(os.path.join(src, n), os.path.join(tmp, n))
        os.rename(tmp, dot)
    else:
        os.rename(src, dot)
    os.rename(os.path.join(dot, layout.LEGACY_RUNS), os.path.join(dot, layout.RUNS))
    w = os.path.join(dot, "work")
    if os.path.isdir(w) and _empty(w):
        os.rmdir(w)
    for r in p["runs"]:
        rw = os.path.join(layout.run_dir(dot, r), "work")
        if os.path.isdir(rw) and _empty(rw):
            os.rmdir(rw)
    old_card = os.path.join(dot, name + ".wp.md") if p["card"] else None
    if old_card and os.path.isfile(old_card):
        os.rename(old_card, p["new_card"])

    def repoint(e):
        e["path"] = dot
    registry.update(name, repoint, h)
    p["checks"] = verify(name, h)
    return p


def verify(name, h=None):
    """Problems after converting: the card, index and history brought up to
    date; history verifies against the runs; stats agree; ``wpk check``."""
    from . import history, index, livecard, stats
    from .check import check
    e = registry.get(name, h)
    probs = []
    if livecard.update_project(e, h) is None:
        probs.append("could not update the card and history")
    c = index.connect(h)
    with c:                             # rows left at the card's old place
        for cid, path in c.execute("SELECT id, path FROM card WHERE project = ?",
                                   (name,)).fetchall():
            if not os.path.isfile(path):
                c.execute("DELETE FROM card WHERE id = ?", (cid,))
    c.close()
    con = history.connect(h)
    try:
        probs += history.verify_project(con, name, e["path"])
    finally:
        con.close()
    if stats.report(stats.groups(*history.collect([name], h=h))) != \
            stats.report(stats.groups(*stats.collect([(name, e["path"])]))):
        probs.append("stats from history differ from stats of the runs")
    probs += ["check: %s" % i for i in check(e["path"]).issues]
    return probs
