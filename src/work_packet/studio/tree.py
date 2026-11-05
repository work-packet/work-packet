"""The studio's file tree and what each path may do (docs/studio-v2.md §3).

Two kinds of path name a file:

- a path relative to the studio's folder (``src/cli.py``): the packet
  folder of the root packet, or a child's ``work/``;
- a ``wp:`` path into the packet's own files, shown as the tree's "Packet"
  section whatever the layout puts them:

  =========================  ===============================  ==========
  ``wp:card``                the root's ``<name>.wp.md``       edit
  ``wp:state/<rel>``         the run's ``state/`` (the plan)   edit
  ``wp:steps/<rel>``         the run's ``steps/``              read
  ``wp:child/<wpid>/state/…``  a child's ``state/``            read
  ``wp:child/<wpid>/steps/…``  a child's ``steps/``            read
  =========================  ===============================  ==========

Everything else of wpk's (status, memento, journal, mailbox, other runs) is
not reachable. In the folder every file may be edited but those under a
hidden directory (``.git``, ``packages``, ...), which are read-only, and
wpk's own (``.work-packet``, ``.studio``, a legacy project's ``packets/``
and ``project.toml``), which are not reachable.
"""

import glob
import hashlib
import os
import tempfile

from .. import fsutil, layout, schema
from ..packet import Packet
from . import kinds, model, watch

WP = "wp:"
PLAN = ("outline.md", "questions.md", "notes")
WPK_OWN = (".work-packet", model.DIR) + watch.TOP_EXCLUDE    # never reachable at the top
LIST_MAX = 2000             # entries of one directory listed
MARKUP = ("{++", "{--", "{~~", "{>>", "{==")


EDIT_MAX = 2 << 20          # bigger files are not opened in the editor (§4)


class TreeError(Exception):
    """No such path, or not allowed; the message says why."""


class Stale(TreeError):
    """The file changed since it was read: ``text`` and ``sha`` are what it holds
    now (None if it was deleted), for the merge view."""

    def __init__(self, msg, text=None, sha=None):
        super().__init__(msg)
        self.text = text
        self.sha = sha


def sha(text):
    """The sha a save checks: of the text as read (newlines kept), like
    ``dash/markup.py``'s."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def card_path(entry, wpid):
    """The root packet's card, or None (a child has none; a folder with no card)."""
    if wpid != entry.get("root"):
        return None
    folder = layout.packet_folder(entry["path"])
    named = layout.card_path(entry["path"], entry.get("name") or "")
    if os.path.isfile(named):
        return named
    got = sorted(glob.glob(os.path.join(glob.escape(folder), "*.wp.md")))
    return got[0] if len(got) == 1 else None


def places(entry, wpid):
    """``{folder, run, state, steps, card}`` of packet ``wpid``."""
    run = layout.run_dir(entry["path"], wpid)
    pkt = Packet(run)
    return {"folder": model.folder(entry, wpid), "run": run, "state": pkt.state_dir,
            "steps": pkt.steps_dir, "card": card_path(entry, wpid)}


def children(entry, wpid):
    """[(child wpid, title)] of the packet's children, in creation order."""
    out = []
    for c in Packet(layout.run_dir(entry["path"], wpid)).child_links():
        if not schema.is_wpid(c):
            continue
        try:
            meta, _ = Packet(layout.run_dir(entry["path"], c)).load_status()
        except Exception:       # noqa: BLE001 - a broken child still shows
            meta = {}
        out.append((c, meta.get("title") or meta.get("name") or ""))
    return out


def _under(base, parts):
    """The real path ``parts`` names under ``base``, never out of it."""
    if any(p in ("", ".", "..") or "\0" in p for p in parts):
        raise TreeError("bad path")
    base = os.path.realpath(base)
    p = os.path.realpath(os.path.join(base, *parts))
    if p != base and not p.startswith(base + os.sep):
        raise TreeError("the path leads out of its folder")
    return p


def resolve(entry, wpid, path):
    """``(absolute path, access)`` for a tree path; access is ``edit`` or
    ``read``. The file need not exist. Raises TreeError."""
    path = str(path or "").strip()
    if not path:
        raise TreeError("no path")
    pl = places(entry, wpid)
    if path.startswith(WP):
        parts = path[len(WP):].split("/")
        head = parts[0]
        if head == "card" and len(parts) == 1:
            if not pl["card"]:
                raise TreeError("this packet has no card")
            return os.path.realpath(pl["card"]), "edit"
        if head == "state" and len(parts) > 1:
            return _under(pl["state"], parts[1:]), "edit"
        if head == "steps" and len(parts) > 1:
            return _under(pl["steps"], parts[1:]), "read"
        if head == "child" and len(parts) > 3 and parts[2] in ("state", "steps"):
            if parts[1] not in dict(children(entry, wpid)):
                raise TreeError("%s is not a child of this packet" % parts[1][:8])
            c = Packet(layout.run_dir(entry["path"], parts[1]))
            base = c.state_dir if parts[2] == "state" else c.steps_dir
            return _under(base, parts[3:]), "read"
        raise TreeError("no such packet file: %s" % path)
    parts = path.split("/")
    if parts[0] in WPK_OWN:
        raise TreeError("%s is wpk's; open it from the Packet section" % path)
    p = _under(pl["folder"], parts)
    hidden = any(_hidden(x, i == 0) for i, x in enumerate(parts[:-1]))
    return p, "read" if hidden else "edit"


def _hidden(name, top):
    if name in watch.EXCLUDE:
        return True
    return top and name.startswith(".") and name != ".github"


def _node(name, path, abspath, access, is_dir):
    n = {"name": name, "path": path, "dir": is_dir, "access": access}
    if not is_dir:
        try:
            n["size"] = os.path.getsize(abspath)
        except OSError:
            n["size"] = None
        k = kinds.kind_of(name)
        n["kind"] = k.name if k else None
    return n


def _list(dirpath, prefix, access, deep, top=False, show_hidden=False):
    """The entries of ``dirpath`` as nodes (``prefix`` + name); dirs first.
    ``deep``: list sub-directories too (the Packet section, which is small)."""
    try:
        names = sorted(os.listdir(dirpath), key=lambda n: n.lower())
    except OSError:
        return []
    dirs, files = [], []
    for n in names[:LIST_MAX]:
        if top and n in WPK_OWN:
            continue
        p = os.path.join(dirpath, n)
        if os.path.islink(p) and not os.path.exists(p):
            continue
        is_dir = os.path.isdir(p)
        hid = is_dir and _hidden(n, top)
        if hid and not show_hidden:
            continue
        a = "read" if hid else access
        node = _node(n, prefix + n, p, a, is_dir)
        if is_dir:
            if hid:
                node["hidden"] = True
            if deep:
                node["children"] = _list(p, prefix + n + "/", a, True)
            dirs.append(node)
        else:
            files.append(node)
    return dirs + files


def _badge(node, abspath):
    """Open doc markup in a Markdown file of the plan, as a count."""
    if node.get("dir") or not node["name"].lower().endswith((".md", ".markdown")):
        return
    try:
        if os.path.getsize(abspath) > (2 << 20):
            return
        text = fsutil.read_text(abspath)
    except OSError:
        return
    n = sum(text.count(t) for t in MARKUP)
    if node["name"] == "questions.md":
        n += sum(1 for ln in text.splitlines() if ln.lstrip().startswith(("- [ ]", "* [ ]")))
    if n:
        node["open"] = n


def packet_section(entry, wpid):
    """The tree's "Packet" section: Card, Plan, Inputs, Steps, Children."""
    pl = places(entry, wpid)
    out = []
    if pl["card"]:
        out.append(dict(_node("Card", WP + "card", pl["card"], "edit", False),
                        file=os.path.basename(pl["card"])))
    state = _list(pl["state"], WP + "state/", "edit", True)
    plan = [n for n in state if n["name"] in PLAN]
    plan.sort(key=lambda n: PLAN.index(n["name"]))
    for n in plan:
        _badge(n, os.path.join(pl["state"], n["name"]))
    out.append({"name": "Plan", "group": True, "children": plan})
    out.append({"name": "Inputs", "group": True,
                "children": [n for n in state if n["name"] not in PLAN]})
    steps = _list(pl["steps"], WP + "steps/", "read", True)
    out.append({"name": "Steps", "group": True, "access": "read", "children": steps[::-1]})
    kids = []
    for c, title in children(entry, wpid):
        cp = Packet(layout.run_dir(entry["path"], c))
        pre = "%schild/%s/" % (WP, c)
        kids.append({"name": c[:8] + (" " + title if title else ""), "group": True,
                     "wpid": c, "access": "read", "children": [
                         {"name": "Plan", "group": True,
                          "children": _list(cp.state_dir, pre + "state/", "read", True)},
                         {"name": "Steps", "group": True,
                          "children": _list(cp.steps_dir, pre + "steps/", "read", True)[::-1]}]})
    out.append({"name": "Children", "group": True, "access": "read", "children": kids})
    return out


def listing(entry, wpid, rel="", show_hidden=False):
    """One level of the folder: the entries of directory ``rel`` ("" for the top)."""
    folder = model.folder(entry, wpid)
    if rel:
        p, access = resolve(entry, wpid, rel)
        if not os.path.isdir(p):
            raise TreeError("%s is not a directory" % rel)
        return _list(p, rel.rstrip("/") + "/", access, False, show_hidden=show_hidden)
    return _list(folder, "", "edit", False, top=True, show_hidden=show_hidden)


def tree(entry, wpid, show_hidden=False):
    """``{packet: [...], files: [...]}``: the Packet section, whole, and the
    folder's top level (directories load as they are opened)."""
    return {"packet": packet_section(entry, wpid),
            "files": listing(entry, wpid, "", show_hidden)}


def watch_extra(entry, wpid):
    """The watcher's extra roots: ``{"wp:state/": state dir}``."""
    return {WP + "state/": places(entry, wpid)["state"]}


def _read_text(p):
    """The file's text with its newlines kept, or None if it is not UTF-8 text."""
    with open(p, "rb") as fp:
        raw = fp.read()
    if b"\0" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read(entry, wpid, path):
    """A file for an editor tab: ``{path, access, kind, size, text, sha}``;
    ``text`` is None for a binary file or one over ``EDIT_MAX`` (``why`` says
    which). Raises TreeError."""
    p, access = resolve(entry, wpid, path)
    if not os.path.isfile(p):
        raise TreeError("no file %s" % path)
    k = kinds.kind_of(p)
    out = {"path": path, "access": access, "kind": k.name if k else None,
           "size": os.path.getsize(p), "name": os.path.basename(p), "text": None}
    if out["size"] > EDIT_MAX:
        out["why"] = "large"
        return out
    text = _read_text(p)
    if text is None:
        out["why"] = "binary"
        return out
    out.update(text=text, sha=sha(text))
    return out


def save(entry, wpid, path, text, want_sha, create=False):
    """Write ``text`` to a file the studio may edit, if it still has
    ``want_sha`` (a new file: ``create`` and no file there yet). Atomic; the
    file keeps its mode. Returns ``(absolute path, new sha)``. Raises Stale
    when the file changed (or appeared, or went), TreeError otherwise."""
    p, access = resolve(entry, wpid, path)
    if access != "edit":
        raise TreeError("%s is read-only in the studio" % path)
    if not isinstance(text, str):
        raise TreeError("no text")
    if len(text.encode("utf-8")) > EDIT_MAX:
        raise TreeError("too large to save from the studio")
    if os.path.isdir(p):
        raise TreeError("%s is a directory" % path)
    if os.path.exists(p):
        now = _read_text(p)
        if now is None:
            raise TreeError("%s is not a text file" % path)
        if create or not want_sha or sha(now) != want_sha:
            raise Stale("%s changed since you opened it" % path, now, sha(now))
        mode = os.stat(p).st_mode & 0o7777
    else:
        if not create:
            raise Stale("%s was deleted since you opened it" % path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        mode = None
    fd, tmp = tempfile.mkstemp(prefix=".studio-", dir=os.path.dirname(p))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fp:
            fp.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        else:
            os.chmod(tmp, 0o666 & ~_umask())
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return p, sha(text)


def _umask():
    m = os.umask(0)
    os.umask(m)
    return m
