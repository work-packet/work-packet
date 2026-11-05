"""Who changed what in a studio's folder (docs/studio-plan.md S1.3).

A polling watcher: ``poll()`` compares every file's mtime and size with the
last pass, hashes only the files that differ, and reports created, modified,
deleted and renamed files. Each change is attributed to ``agent`` (a Write or
Edit tool call on that path was seen within ``window_s``, and no change has
used that mark yet), ``you`` (a save
through the board, ``saved()``) or ``outside`` (anything else: the IDE, a
shell). The dash polls every ``INTERVAL_S`` while a studio socket is open.

``extra`` watches more folders outside the root under a prefix: the studio
watches the run's ``state/`` as ``wp:state/...`` (docs/studio-v2.md §3).
"""

import hashlib
import os
import time

INTERVAL_S = 0.5
WINDOW_S = 10.0
EXCLUDE = (".work-packet", ".git", ".studio", "packages", "node_modules", "__pycache__",
           ".venv")
TOP_EXCLUDE = ("packets", "project.toml")      # a legacy project's runs, at its top only
MAX_FILES = 20000
HASH_MAX = 64 << 20         # bigger files are compared by mtime and size only


def _hash(path):
    try:
        if os.path.getsize(path) > HASH_MAX:
            st = os.stat(path)
            return "size:%d:%d" % (st.st_size, st.st_mtime_ns)
    except OSError:
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fp:
            for chunk in iter(lambda: fp.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def scan(root, exclude=EXCLUDE, prefix="", folder=True):
    """{relative path: (mtime_ns, size)} of the regular files under ``root``.
    ``folder``: skip what a packet folder holds of wpk's at its top; else
    (an extra root) take everything. Paths get ``prefix``."""
    out = {}
    root = os.path.abspath(root)
    for dirpath, dirs, names in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        top = folder and rel_dir == "."
        dirs[:] = sorted(d for d in dirs if (d not in exclude or not folder) and not (
            top and (d in TOP_EXCLUDE or d.startswith(".") and d != ".github")))
        for n in names:
            if top and n in TOP_EXCLUDE:
                continue
            p = os.path.join(dirpath, n)
            try:
                st = os.stat(p, follow_symlinks=False)
            except OSError:
                continue
            if not os.path.isfile(p) or os.path.islink(p):
                continue
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            out[prefix + rel] = (st.st_mtime_ns, st.st_size)
            if len(out) >= MAX_FILES:
                return out
    return out


class Watcher:
    def __init__(self, root, exclude=EXCLUDE, window_s=WINDOW_S, clock=time.time, extra=None):
        self.root = os.path.abspath(root)
        self.extra = {k: os.path.abspath(v) for k, v in (extra or {}).items()}
        self.exclude = exclude
        self.window_s = window_s
        self.clock = clock
        self.stats = self._scan()
        self.hashes = {}
        self.marks = {}             # path -> (who, t)
        self.hashes_now()           # the baseline: renames are found by content

    def _scan(self):
        out = scan(self.root, self.exclude)
        for prefix, d in self.extra.items():
            out.update(scan(d, prefix=prefix, folder=False))
        return out

    def abspath(self, rel):
        """The file a watched path names."""
        for prefix, d in self.extra.items():
            if rel.startswith(prefix):
                return os.path.join(d, rel[len(prefix):])
        return os.path.join(self.root, rel)

    def hashes_now(self):
        """{path: sha256} of every file (hashing what is not cached)."""
        for rel in self.stats:
            if rel not in self.hashes:
                self.hashes[rel] = _hash(self.abspath(rel))
        return dict(self.hashes)

    def agent_wrote(self, path, t=None):
        """A Write/Edit tool call of the studio's agent named ``path``."""
        self._mark(path, "agent", t)

    def saved(self, path, t=None):
        """The board saved ``path`` for the person."""
        self._mark(path, "you", t)

    def _mark(self, path, who, t):
        rel = self._rel(path)
        if rel is not None:
            self.marks[rel] = (who, self.clock() if t is None else t)

    def _rel(self, path):
        for prefix, d in self.extra.items():
            if path.startswith(prefix):
                return path
            p = os.path.normpath(os.path.join(self.root, path))
            if p.startswith(d + os.sep):
                return prefix + os.path.relpath(p, d).replace(os.sep, "/")
        p = os.path.normpath(os.path.join(self.root, path))
        if p != self.root and not p.startswith(self.root + os.sep):
            return None
        return os.path.relpath(p, self.root).replace(os.sep, "/")

    def forget(self, path):
        """Take back a mark (the save it announced did not happen)."""
        rel = self._rel(path)
        self.marks.pop(rel, None)

    def _who(self, rel, now):
        """Who made the change to ``rel``: a mark explains one change only, so
        an edit from outside just after the agent's is not the agent's."""
        got = self.marks.pop(rel, None)
        if got and now - got[1] <= self.window_s:
            return got[0]
        return "outside"

    def poll(self):
        """The changes since the last poll: [{path, change, by, sha?, from?}],
        ``change`` one of created, modified, deleted, renamed."""
        now = self.clock()
        new = self._scan()
        old = self.stats
        gone = {p for p in old if p not in new}
        made = [p for p in new if p not in old]
        changed = [p for p in new if p in old and new[p] != old[p]]
        gone_sha = {p: self.hashes.get(p) for p in gone}
        out = []
        for p in sorted(changed):
            sha = _hash(self.abspath(p))
            if sha is not None and sha == self.hashes.get(p):
                continue                    # touched, not changed
            self.hashes[p] = sha
            out.append({"path": p, "change": "modified", "by": self._who(p, now), "sha": sha})
        for p in sorted(made):
            sha = _hash(self.abspath(p))
            self.hashes[p] = sha
            src = next((g for g in sorted(gone) if gone_sha.get(g) and gone_sha[g] == sha), None)
            if src is not None:
                gone.discard(src)
                out.append({"path": p, "change": "renamed", "from": src,
                            "by": self._who(p, now), "sha": sha})
            else:
                out.append({"path": p, "change": "created", "by": self._who(p, now), "sha": sha})
        for p in sorted(gone):
            out.append({"path": p, "change": "deleted", "by": self._who(p, now)})
        for p in list(self.hashes):
            if p not in new:
                del self.hashes[p]
        self.stats = new
        self.marks = {p: m for p, m in self.marks.items() if now - m[1] <= self.window_s}
        return out


def diff(before, after):
    """Changed paths between two ``{path: sha}`` maps: (created, modified, deleted)."""
    created = sorted(p for p in after if p not in before)
    deleted = sorted(p for p in before if p not in after)
    modified = sorted(p for p in after if p in before and after[p] != before[p])
    return created, modified, deleted
