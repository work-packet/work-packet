"""``wpk check``: validate packets, projects and the registry against docs/spec.md."""

import json
import os
from dataclasses import dataclass
from typing import Optional

from . import frontmatter, journal, schema
from . import lease as lease_mod
from .packet import Packet

try:
    import tomllib
except ImportError:          # Python 3.10
    import tomli as tomllib


REQUIRED_ENTRIES = ("status.md", "memento.md", "state", "journal.jsonl")
KNOWN_ENTRIES = REQUIRED_ENTRIES + (
    "identity", "children", "steps", ".lease", ".pending", ".state.old",
    "stack", "mailbox",
)


@dataclass(frozen=True)
class Issue:
    path: str
    field: Optional[str]
    msg: str
    level: str = "error"

    def __str__(self):
        loc = self.path if self.field is None else "%s: %s" % (self.path, self.field)
        return "%s: %s: %s" % (self.level, loc, self.msg)


class Report:

    def __init__(self):
        self.issues = []

    def add(self, path, field, msg, level="error"):
        self.issues.append(Issue(path, field, msg, level))

    def extend(self, path, problems):
        for p in problems:
            self.add(path, p.field, p.msg, p.level)

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warning"]


def _load_toml(path, rep):
    try:
        with open(path, "rb") as fp:
            return tomllib.load(fp)
    except FileNotFoundError:
        rep.add(path, None, "missing")
    except tomllib.TOMLDecodeError as e:
        rep.add(path, None, "not valid TOML: %s" % e)
    return None


def _load_fm(path, rep):
    try:
        return frontmatter.load(path)
    except FileNotFoundError:
        return None
    except (frontmatter.FrontMatterError, UnicodeDecodeError) as e:
        rep.add(path, None, str(e))
        return None


lease_is_stale = lease_mod.is_stale


def _check_lease(pkt, rep):
    """Returns True if a live lease is held."""
    if not os.path.lexists(pkt.lease_path):
        return False
    try:
        with open(pkt.lease_path) as fp:
            lease = json.load(fp)
    except (OSError, ValueError) as e:
        rep.add(pkt.lease_path, None, "unreadable lease: %s" % e)
        return False
    if not isinstance(lease, dict):
        rep.add(pkt.lease_path, None, "lease is not a JSON object")
        return False
    for k in ("host", "pid", "step", "attempt", "expires"):
        if k not in lease:
            rep.add(pkt.lease_path, k, "missing")
    if lease_is_stale(lease):
        rep.add(pkt.lease_path, None, "stale lease (holder gone or expired); "
                "`wpk recover` removes it", "warning")
        return False
    return True


def _check_journal(pkt, status, rep):
    j = pkt.journal()
    jp = pkt.journal_path
    for n in j.bad_lines:
        rep.add(jp, "line %d" % n, "not valid JSON")
    if j.truncated_tail:
        rep.add(jp, None, "last line is incomplete (crash during append); "
                "it is ignored", "warning")
    expect = 1
    open_begin = None
    for i, rec in enumerate(j.records, 1):
        probs = schema.validate_journal_record(rec)
        rep.extend("%s:%d" % (jp, i), probs)
        if any(p.level == "error" for p in probs):
            continue
        t = rec["type"]
        if t == "commit-begin":
            if open_begin is not None:
                rep.add("%s:%d" % (jp, i), None,
                        "commit-begin for step %d while step %d is unfinished"
                        % (rec["step"], open_begin))
            if rec["step"] != expect:
                rep.add("%s:%d" % (jp, i), "step",
                        "commit-begin for step %d, expected %d" % (rec["step"], expect))
            open_begin = rec["step"]
        elif t == "commit-end":
            if open_begin != rec["step"]:
                rep.add("%s:%d" % (jp, i), None,
                        "commit-end for step %d has no matching commit-begin" % rec["step"])
            open_begin = None
            expect = rec["step"] + 1
    last = expect - 1
    if status is not None and schema.is_int(status.get("step")):
        if open_begin is not None:
            rep.add(jp, None, "ends in an unfinished commit of step %d; "
                    "`wpk recover` finishes it" % open_begin, "warning")
            if status["step"] not in (last, open_begin):
                rep.add(pkt.status_path, "step",
                        "is %d but the journal has committed %d" % (status["step"], last))
        elif status["step"] != last:
            rep.add(pkt.status_path, "step",
                    "is %d but the journal has committed %d" % (status["step"], last))


def _check_steps(pkt, status, leased, rep):
    step = status.get("step") if status else None
    if not schema.is_int(step):
        return
    try:
        names = os.listdir(pkt.steps_dir)
    except FileNotFoundError:
        names = []
    committed = set()
    for name in names:
        p = os.path.join(pkt.steps_dir, name)
        parsed = schema.parse_step_dir(name)
        if parsed is None or not os.path.isdir(p):
            rep.add(p, None, "not a step folder (NNNN or NNNN.failed-A)", "warning")
            continue
        n, failed = parsed
        if failed is not None:
            if n > step + 1:
                rep.add(p, None, "failed attempt at step %d, but step is %d" % (n, step))
            continue
        if n <= step:
            committed.add(n)
        elif n == step + 1:
            if not leased:
                rep.add(p, None, "step folder with no commit and no live lease "
                        "(crashed step); `wpk recover` cleans it up", "warning")
        else:
            rep.add(p, None, "step %d is beyond step %d" % (n, step))
    for n in range(1, step + 1):
        if n not in committed:
            rep.add(pkt.step_dir(n), None, "missing folder for committed step %d" % n)


def check_packet(path, project=None, rep=None):
    """Check one packet directory. Returns (report, status meta or None)."""
    rep = rep or Report()
    pkt = Packet(path)
    if not schema.is_wpid(pkt.wpid):
        rep.add(pkt.path, None, "directory name is not a WPID")
    records = pkt.journal().records
    committing = journal.unfinished_commit(records) is not None
    pending_kids = journal.pending_children(records)
    for e in REQUIRED_ENTRIES:
        if not os.path.lexists(os.path.join(pkt.path, e)):
            if e == "state" and committing and os.path.isdir(pkt.state_old_dir):
                continue        # mid state swap; the journal warning covers it
            rep.add(os.path.join(pkt.path, e), None, "missing")
    for e in sorted(os.listdir(pkt.path)):
        if e not in KNOWN_ENTRIES:
            rep.add(os.path.join(pkt.path, e), None, "not part of the packet format",
                    "warning")
    for e in ("state", "steps", "children", "identity"):
        p = os.path.join(pkt.path, e)
        if os.path.lexists(p) and not os.path.isdir(p):
            rep.add(p, None, "must be a directory")

    status = None
    fm = _load_fm(pkt.status_path, rep)
    if fm is not None:
        status, body = fm
        rep.extend(pkt.status_path, schema.validate_status(status, body))
        if status is not None:
            if status.get("wpid") != pkt.wpid:
                rep.add(pkt.status_path, "wpid",
                        "is %r but the directory is %s" % (status.get("wpid"), pkt.wpid))
            if project is not None and status.get("project") != project:
                rep.add(pkt.status_path, "project",
                        "is %r but the project is %r" % (status.get("project"), project))
    fm = _load_fm(pkt.memento_path, rep)
    if fm is not None:
        rep.extend(pkt.memento_path, schema.validate_memento(fm[0], fm[1], proposal=False))

    leased = _check_lease(pkt, rep)
    if not leased:
        for p in (pkt.pending_dir, pkt.state_old_dir):
            if os.path.lexists(p):
                rep.add(p, None, "left over from a crashed step; `wpk recover` "
                        "cleans it up", "warning")
    _check_journal(pkt, status, rep)
    _check_steps(pkt, status, leased, rep)

    if os.path.isdir(pkt.identity_dir):
        for e in sorted(os.listdir(pkt.identity_dir)):
            p = os.path.join(pkt.identity_dir, e)
            if not os.path.islink(p):
                rep.add(p, None, "identity entries should be symlinks", "warning")
            elif not os.path.exists(p):
                rep.add(p, None, "dangling identity link -> %s" % os.readlink(p),
                        "warning")

    if status is not None and isinstance(status.get("children"), list):
        links = pkt.child_links()
        listed = set(c for c in status["children"] if isinstance(c, str))
        for c in sorted(listed - set(links)):
            rep.add(os.path.join(pkt.children_dir, c), None,
                    "child listed in status.md has no link")
        for c in sorted(set(links) - listed - pending_kids):
            rep.add(os.path.join(pkt.children_dir, c), None,
                    "link for a child not listed in status.md")
        for c, target in links.items():
            if target is None:
                rep.add(os.path.join(pkt.children_dir, c), None, "must be a symlink")
            elif target != os.path.join("..", "..", c):
                rep.add(os.path.join(pkt.children_dir, c), None,
                        "points to %r, expected %r" % (target, os.path.join("..", "..", c)))
    return rep, status


def check_project(path, rep=None):
    rep = rep or Report()
    path = os.path.abspath(path)
    ptoml = os.path.join(path, "project.toml")
    proj = _load_toml(ptoml, rep)
    name = None
    if proj is not None:
        rep.extend(ptoml, schema.validate_project(proj))
        name = proj.get("name")
    pdir = os.path.join(path, "packets")
    if not os.path.isdir(pdir):
        rep.add(pdir, None, "missing")
        return rep
    statuses = {}
    for e in sorted(os.listdir(pdir)):
        p = os.path.join(pdir, e)
        if e.startswith(".tmp-"):
            rep.add(p, None, "child left half-built by a crashed commit; "
                    "`wpk recover` on its parent finishes it", "warning")
            continue
        if not os.path.isdir(p) or os.path.islink(p):
            rep.add(p, None, "not a packet directory")
            continue
        _, st = check_packet(p, project=name, rep=rep)
        if st is not None:
            statuses[e] = st

    # Tree consistency.
    roots = sorted(w for w, s in statuses.items() if s.get("parent") is None)
    root = proj.get("root") if proj else None
    if root is not None:
        if root not in statuses and not os.path.isdir(os.path.join(pdir, str(root))):
            rep.add(ptoml, "root", "packet %s does not exist" % root)
        elif root in statuses and statuses[root].get("parent") is not None:
            rep.add(ptoml, "root", "packet %s has a parent" % root)
    for w in roots:
        if w != root:
            rep.add(os.path.join(pdir, w, "status.md"), "parent",
                    "packet has no parent but is not the project root")
    for w, s in statuses.items():
        sp = os.path.join(pdir, w, "status.md")
        par = s.get("parent")
        if par is not None:
            if par not in statuses:
                rep.add(sp, "parent", "parent %s does not exist in this project" % par)
            elif w not in (statuses[par].get("children") or []) and \
                    w not in journal.pending_children(
                        Packet(os.path.join(pdir, par)).journal().records):
                rep.add(sp, "parent", "parent %s does not list this packet as a child" % par)
        for c in s.get("children") or []:
            if c not in statuses:
                if not os.path.isdir(os.path.join(pdir, str(c))):
                    rep.add(sp, "children", "child %s does not exist" % c)
            elif statuses[c].get("parent") != w:
                rep.add(sp, "children", "child %s names parent %r"
                        % (c, statuses[c].get("parent")))
    return rep


def check_home(home, rep=None):
    rep = rep or Report()
    cfg = os.path.join(home, "config.toml")
    if os.path.exists(cfg):
        d = _load_toml(cfg, rep)
        if d is not None:
            rep.extend(cfg, schema.validate_config(d))
    pdir = os.path.join(home, "projects")
    if not os.path.isdir(pdir):
        return rep
    for e in sorted(os.listdir(pdir)):
        p = os.path.join(pdir, e)
        if not e.endswith(".toml"):
            rep.add(p, None, "not a registry entry (*.toml)", "warning")
            continue
        d = _load_toml(p, rep)
        if d is None:
            continue
        probs = schema.validate_registry_entry(d, stem=e[:-5])
        rep.extend(p, probs)
        path = d.get("path")
        if not isinstance(path, str):
            continue
        if not os.path.isfile(os.path.join(path, "project.toml")):
            rep.add(p, "path", "no project at %s" % path)
            continue
        try:
            with open(os.path.join(path, "project.toml"), "rb") as fp:
                proj = tomllib.load(fp)
        except (OSError, tomllib.TOMLDecodeError):
            proj = {}
        for k in ("name", "root"):
            if k in proj and k in d and proj[k] != d[k]:
                rep.add(p, k, "is %r but project.toml says %r" % (d[k], proj[k]))
        check_project(path, rep)
    return rep


def check(path=None, home=None):
    """Check whatever ``path`` is: a packet, a project or a runner home.

    With no path, check the runner home (``home`` or ``WPK_HOME`` or
    ``~/.work-packet``) and every project it registers.
    """
    rep = Report()
    if path is None:
        home = home or os.environ.get("WPK_HOME") or os.path.expanduser("~/.work-packet")
        if not os.path.isdir(home):
            rep.add(home, None, "runner home does not exist")
            return rep
        return check_home(home, rep)
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        rep.add(path, None, "not a directory")
    elif os.path.exists(os.path.join(path, "project.toml")):
        check_project(path, rep)
    elif os.path.exists(os.path.join(path, "status.md")):
        check_packet(path, rep=rep)
    elif os.path.isdir(os.path.join(path, "projects")) or \
            os.path.exists(os.path.join(path, "config.toml")):
        check_home(path, rep)
    else:
        rep.add(path, None, "not a packet, project or runner home")
    return rep
