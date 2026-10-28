"""Starters: ways to make a new packet (docs/starters-v1.md).

A *starter* turns what you chose (``values``) into a *recipe*, a plain
dict; ``make`` carries any recipe out the same way. Built-in starters are in
``builtin``; more come from the entry-point group ``work_packet.starters``
(each entry point a Starter subclass).
"""

import copy as _copy
import json
import os
import shutil
import subprocess

from .. import layout

RECIPE_KEYS = ("name", "dir", "folder", "clone", "objective", "inputs", "origin", "model",
               "harness", "extra", "hold", "from", "board")
CLONE_KEYS = ("url", "ref", "branch", "share")


class StartError(Exception):
    pass


class Field:
    """One thing a starter asks for. ``kind``: text, textarea, repo, issue, project."""

    def __init__(self, key, label, kind="text", required=False, help="", placeholder=""):
        self.key, self.label, self.kind = key, label, kind
        self.required, self.help, self.placeholder = required, help, placeholder

    def as_dict(self):
        return dict(self.__dict__)


# Asked by every starter, before its own fields.
COMMON = (
    Field("name", "Name", placeholder="from what you pick, if empty",
          help="Lower case, digits, - and _. The packet folder is <directory>/<name>."),
    Field("dir", "In directory"),
)
# Asked by every starter, after its own fields.
TAIL = (
    Field("objective", "Objective", "textarea",
          help="The first instruction. Empty: you write it in Compose."),
    Field("from", "Copy the setup of", "project",
          help="Its limits, permissions, inputs and smoke tests; its one repo if nothing "
               "else is cloned."),
)


class Starter:
    name = ""
    title = ""
    help = ""
    fields = ()

    def all_fields(self):
        return list(COMMON) + list(self.fields) + list(TAIL)

    def search(self, key, query, values, h=None):
        """Choices for browsing field ``key``: [{value, label, detail}]."""
        return []

    def recipe(self, values, h=None):
        """The recipe for ``values`` (a dict of field values). Raises StartError."""
        raise NotImplementedError

    def base(self, values):
        """The recipe keys every starter fills the same way."""
        r = {k: values[k] for k in ("name", "dir", "objective", "from", "model", "harness",
                                    "board") if values.get(k)}
        if "hold" in values:
            r["hold"] = values["hold"] not in (False, "", "0", "no", "false")
        return r


# --- the registry -----------------------------------------------------------------

_REGISTRY = {}
_loaded = []


def register(cls):
    _REGISTRY[cls.name] = cls
    return cls


def _load():
    if _loaded:
        return
    _loaded.append(True)
    from . import builtin            # noqa: F401  (registers)
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="work_packet.starters")
    except Exception:                 # noqa: BLE001  (old Pythons, broken metadata)
        eps = []
    for ep in eps:
        try:
            register(ep.load())
        except Exception as e:        # noqa: BLE001  a broken plugin must not break New task
            _broken[ep.name] = str(e)


_broken = {}


def names():
    _load()
    return list(_REGISTRY)


def get(name):
    _load()
    if name not in _REGISTRY:
        raise StartError("no starter %r; there are: %s" % (name, ", ".join(_REGISTRY)))
    return _REGISTRY[name]()


def broken():
    """Entry-point starters that failed to load: {name: error}."""
    _load()
    return dict(_broken)


# --- the maker ----------------------------------------------------------------------

def check(recipe):
    """The recipe, normalized; raises StartError on a malformed one."""
    if not isinstance(recipe, dict):
        raise StartError("a recipe is a JSON object")
    bad = sorted(set(recipe) - set(RECIPE_KEYS))
    if bad:
        raise StartError("unknown recipe keys: %s" % ", ".join(bad))
    r = _copy.deepcopy(recipe)
    if not r.get("name"):
        raise StartError("the recipe has no name")
    c = r.get("clone")
    if c is not None:
        if isinstance(c, str):
            c = r["clone"] = {"url": c}
        if not isinstance(c, dict) or not c.get("url"):
            raise StartError("clone: needs a url")
        bad = sorted(set(c) - set(CLONE_KEYS))
        if bad:
            raise StartError("unknown clone keys: %s" % ", ".join(bad))
    for i in r.get("inputs") or []:
        if not (isinstance(i, dict) and i.get("name") and isinstance(i.get("text"), str)) \
                or os.path.basename(i["name"]) != i["name"] or i["name"].startswith("."):
            raise StartError("inputs: each needs a plain file name and text")
    if r.get("origin") is not None and not isinstance(r["origin"], dict):
        raise StartError("origin: a table")
    r.setdefault("hold", True)
    return r


def folder_of(r):
    if r.get("folder"):
        return os.path.abspath(os.path.expanduser(r["folder"]))
    return os.path.abspath(os.path.join(os.path.expanduser(r.get("dir") or "."), r["name"]))


def _setup_copy(r, h):
    """``from``: (the copied project.toml keys, the repo to clone if the recipe has none)."""
    from .. import archived, project, setup
    copy = None
    if r.get("from"):
        se = archived.get(r["from"], h)
        if se is None:
            raise StartError("no registered project named %r" % r["from"])
        copy = setup.copy_setup(project.load_project(se["path"]), r["name"], se["path"])
    try:
        copy, repo = setup.packet_clone(copy, (r.get("clone") or {}).get("url"))
    except setup.SetupError as e:
        raise StartError(str(e)) from None
    clone = r.get("clone")
    if clone is None and repo is not None:
        clone = {"url": repo["from"], "share": repo.get("share", [])}
    return copy, clone


def _extra(r, copy, h):
    from .. import harness as harness_mod, registry
    extra = dict(copy or {})
    extra.update(r.get("extra") or {})
    hn = r.get("harness")
    if hn:
        if hn not in harness_mod.names():
            raise StartError("no harness %r; there are: %s" % (hn, ", ".join(
                harness_mod.names())))
        if hn != registry.load_config(h)["harness"]:
            extra["harness"] = hn
    if r.get("origin"):
        extra["origin"] = {k: v for k, v in r["origin"].items()
                           if isinstance(v, (str, int)) and v != ""}
    return extra


def preview(recipe, h=None):
    """What ``make`` would do, as lines; raises StartError if it would refuse."""
    from .. import project
    r = check(recipe)
    folder = folder_of(r)
    copy, clone = _setup_copy(r, h)
    _extra(r, copy, h)
    try:
        project.new(r["name"], None, path=folder, packet=True, dry_run=True, h=h)
    except project.ProjectError as e:
        raise StartError(str(e)) from None
    from .. import registry
    if r.get("board") and r["board"] not in [b["name"] for b in registry.boards(h)]:
        raise StartError("board: there is no board named %s" % r["board"])
    out = ["packet %s in %s%s" % (r["name"], folder, ", on board %s" % r["board"]
                                  if r.get("board") else "")]
    if clone:
        if os.path.lexists(folder) and os.listdir(folder):
            raise StartError("%s exists and is not empty: it cannot be cloned into" % folder)
        out.append("clone %s%s" % (clone["url"], " at %s" % clone["ref"]
                                   if clone.get("ref") else ""))
        if clone.get("branch"):
            out.append("on branch %s" % clone["branch"])
    elif os.path.isdir(folder):
        out.append("works in the folder as it is")
    for i in r.get("inputs") or []:
        out.append("input state/%s (%d lines)" % (i["name"], i["text"].count("\n") + 1))
    if r.get("origin"):
        o = r["origin"]
        out.append("from %s" % (o.get("url") or o.get("title") or o.get("kind")))
    if r.get("objective"):
        out.append("objective: %s" % r["objective"].strip().splitlines()[0][:100])
    out.append("held for setup: hand it off in Compose" if r["hold"] or not r.get("objective")
               else "runnable: the runner starts it")
    return out


def _git(folder, *args):
    res = subprocess.run(["git", "-C", folder] + list(args), capture_output=True, text=True)
    if res.returncode:
        raise StartError("git %s: %s" % (" ".join(args), (res.stderr or res.stdout).strip()))
    return res.stdout.strip()


def _branch(folder, ref, branch):
    if ref:
        _git(folder, "checkout", "-q", ref)
    if not branch:
        return
    have = subprocess.run(["git", "-C", folder, "rev-parse", "-q", "--verify",
                           "refs/remotes/origin/" + branch], capture_output=True).returncode == 0
    if have:                           # started before: carry on with it
        _git(folder, "switch", "-q", branch)
    else:
        _git(folder, "switch", "-q", "-c", branch)


def make(recipe, h=None):
    """Make the packet. Returns the project Plan. Nothing is left on a failure:
    a clone made here is removed."""
    from .. import fsutil, project, registry, setup
    from ..packet import Packet
    preview(recipe, h)                # every refusal before anything is made
    r = check(recipe)
    folder = folder_of(r)
    copy, clone = _setup_copy(r, h)
    extra = _extra(r, copy, h)
    made = None
    if clone:
        made = "new" if not os.path.lexists(folder) else "empty"
        try:
            setup.clone_packet({"name": "", "from": clone["url"],
                                "share": clone.get("share") or []}, folder)
        except setup.SetupError as e:
            _undo(folder, made)
            raise StartError(str(e)) from None
    try:
        if clone:
            _branch(folder, clone.get("ref"), clone.get("branch"))
        obj = r.get("objective") or None
        held = r["hold"] or not obj
        plan = project.new(r["name"], None if held else obj, path=folder,
                           model=r.get("model"), extra=extra, packet=True, h=h)
        if held and obj:
            text = obj if obj.endswith("\n") else obj + "\n"
            fsutil.atomic_write(os.path.join(plan.path, "prompt.md"), text)
        root = Packet(layout.run_dir(plan.path, plan.root))
        for i in r.get("inputs") or []:
            fsutil.atomic_write(os.path.join(root.state_dir, i["name"]), i["text"])
        if r.get("board"):
            registry.move(plan.name, r["board"], h)
    except (project.ProjectError, registry.BoardError, OSError) as e:
        _undo(folder, made)
        raise StartError(str(e)) from None
    except BaseException:
        _undo(folder, made)
        raise
    return plan


def _undo(folder, made):
    if made:                          # only what this make cloned
        shutil.rmtree(folder, ignore_errors=True)
        if made == "empty":
            os.makedirs(folder, exist_ok=True)


def from_values(starter, values, h=None):
    """The recipe a starter makes from ``values``; ``name`` and ``dir`` filled."""
    s = get(starter) if isinstance(starter, str) else starter
    vals = {k: (v.strip() if isinstance(v, str) and k != "objective" else v)
            for k, v in values.items()}
    for f in s.all_fields():
        if f.required and not vals.get(f.key):
            raise StartError("%s: required" % f.label)
    r = s.recipe(vals, h)
    for k in ("name", "dir", "objective", "from", "model", "harness"):
        if vals.get(k):
            r[k] = vals[k]            # what you typed wins over what the starter suggests
    return check(r)


def dumps(recipe):
    return json.dumps(recipe, indent=2, sort_keys=True)
