"""Sphinx docs in a project's work: find them, build them when stale, keep a
record of each build so the board can link to the newest (docs/sphinx-docs-v1.md).

A *docset* is one Sphinx source directory (the one holding ``conf.py``) in one
``work/`` entry. Its build lives outside the work, in
``$WPK_HOME/docs/<project>/<entry>/<docset>/``: ``html/``, ``doctrees/``,
``build.log``, ``build.json`` (the newest build) and ``builds.jsonl`` (all of
them). Run as ``python -m work_packet.docs build <proj>`` for a detached build.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

from . import fsutil, layout, registry, workspace
from .project import ProjectError, load_project

KNOWN = ("docs", "doc", "docs/source", "doc/source", "sphinx", "documentation")
SKIP = {".git", "packages", "node_modules", "_build", "build", "dist", ".venv", "venv",
        "runs", ".tox", "site-packages", "__pycache__", layout.DOT}
DEPTH = 3                 # how deep the fallback search for conf.py goes
FILES_MAX = 5000          # fingerprint: stop counting after this many files
TIMEOUT_S = 600
SPHINX_HINT = re.compile(r"\b(sphinx|extensions|html_theme)\b|^\s*project\s*=", re.M)
WARN = re.compile(r"\b(WARNING|ERROR|CRITICAL):")
FATAL = re.compile(r"\b((?:[A-Za-z]+Error|[Ee]xception|ERROR): .*)")   # why it failed
SLUG = re.compile(r"[^A-Za-z0-9_.-]+")
# The built pages run as Sphinx made them, on the board's origin, with no
# sandbox: themes need inline scripts and localStorage (D-Q4).
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
       "frame-ancestors 'self'; form-action 'self'; base-uri 'self'")


@dataclass
class DocSet:
    project: str          # the project's name
    entry: str            # the work/ entry it is in
    name: str             # slug of its directory within the entry: "docs", "doc-source"
    src: str              # the directory holding conf.py
    tree: str             # the entry's directory it was found in (a run's worktree, perhaps)
    wpid: str = None      # the run whose tree that is, or None for your own work/
    home: str = None      # the runner home its build goes in; None: registry.home()

    @property
    def out(self):
        return out_dir(self.project, self.entry, self.name, self.home)

    @property
    def html(self):
        return os.path.join(self.out, "html")


def out_dir(project, entry, name, h=None):
    return os.path.join(h or registry.home(), "docs", project, entry, name)


def settings(proj):
    """The project's ``[docs]`` table: source, python, enabled, auto."""
    try:
        d = load_project(proj).get("docs")
    except ProjectError:
        return {}
    return d if isinstance(d, dict) else {}


# --- detect ----------------------------------------------------------------------

def _sphinx_conf(d):
    p = os.path.join(d, "conf.py")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return bool(SPHINX_HINT.search(f.read(65536)))
    except OSError:
        return False


def find(tree, source=None):
    """The Sphinx source directories in ``tree``: ``source`` (a path or list of
    them, relative to ``tree``) if given, else the usual places, else a shallow
    search."""
    if source:
        want = [source] if isinstance(source, str) else list(source)
        return [os.path.join(tree, s) for s in want
                if os.path.isfile(os.path.join(tree, s, "conf.py"))]
    out = [os.path.join(tree, k) for k in KNOWN if _sphinx_conf(os.path.join(tree, k))]
    if out:
        return out
    for root, dirs, files in os.walk(tree):
        depth = os.path.relpath(root, tree).count(os.sep) + (root != tree)
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith(".")) \
            if depth < DEPTH else []
        if root != tree and "conf.py" in files and _sphinx_conf(root):
            out.append(root)
            dirs[:] = []
    return out


def slug(tree, src):
    rel = os.path.relpath(src, tree)
    return "root" if rel == "." else SLUG.sub("-", rel.replace(os.sep, "-")).strip("-")


def trees(proj, wpid=None):
    """``[(entry, dir, run wpid or None)]``: where each ``work/`` entry's newest
    edits are. A packet's own folder in the packet layout. Otherwise the run
    ``wpid``'s worktree if it has one, then the root packet's, then your clone."""
    if layout.is_packet_layout(proj):
        folder = layout.packet_folder(proj)
        return [(os.path.basename(folder), folder, None)]
    work = os.path.join(proj, "work")
    try:
        names = sorted(n for n in os.listdir(work) if not n.startswith("."))
    except OSError:
        return []
    try:
        root = load_project(proj).get("root")
    except ProjectError:
        root = None
    out = []
    for n in names:
        if not os.path.isdir(os.path.join(work, n)):
            continue
        pick = (os.path.join(work, n), None)
        for w in (wpid, root):
            p = os.path.join(layout.run_dir(proj, w), "work", n) if w else None
            if p and os.path.isdir(p) and not os.path.islink(p):
                pick = (p, w)
                break
        out.append((n, pick[0], pick[1]))
    return out


def project_name(proj):
    try:
        return load_project(proj)["name"]
    except (ProjectError, KeyError):
        return os.path.basename(os.path.normpath(proj))


def detect(proj, wpid=None, cfg=None, home=None):
    """The project's docsets, found in the trees ``trees`` picks."""
    cfg = settings(proj) if cfg is None else cfg
    if cfg.get("enabled") is False:
        return []
    name = project_name(proj)
    out = []
    for entry, tree, w in trees(proj, wpid):
        for src in find(tree, cfg.get("source")):
            out.append(DocSet(name, entry, slug(tree, src), src, tree, w, home))
    return out


# --- stale or not ------------------------------------------------------------------

def _autodoc_dirs(tree):
    """Where autodoc may read code: ``src/`` and top-level Python packages."""
    out = []
    if os.path.isdir(os.path.join(tree, "src")):
        out.append(os.path.join(tree, "src"))
    try:
        for n in sorted(os.listdir(tree)):
            p = os.path.join(tree, n)
            if n not in SKIP and os.path.isfile(os.path.join(p, "__init__.py")):
                out.append(p)
    except OSError:
        pass
    return out


def fingerprint(ds):
    """The newest mtime among the docs' sources and the code they may document."""
    newest, seen = 0.0, 0
    for top in [ds.src] + _autodoc_dirs(ds.tree):
        for root, dirs, files in os.walk(top):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            for f in files:
                seen += 1
                if seen > FILES_MAX:
                    return newest
                try:
                    newest = max(newest, os.stat(os.path.join(root, f)).st_mtime)
                except OSError:
                    pass
    return newest


def last(ds):
    """The newest build's record, or None."""
    try:
        with open(os.path.join(ds.out, "build.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def history(ds, n=10):
    """The newest ``n`` build records, newest first."""
    try:
        with open(os.path.join(ds.out, "builds.jsonl"), encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines[-n:]):
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def building(ds):
    """The pid of a build under way, or None (a stale lock is not one)."""
    try:
        with open(os.path.join(ds.out, "lock"), encoding="utf-8") as f:
            pid = int(f.read().strip() or 0)
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return pid


def is_stale(ds, rec=None):
    rec = last(ds) if rec is None else rec
    if not rec or not os.path.isfile(os.path.join(ds.html, "index.html")):
        return True
    return rec.get("src") != ds.src or fingerprint(ds) > rec.get("fingerprint", 0)


def state(ds):
    """What the board shows about a docset."""
    rec = last(ds)
    return {"entry": ds.entry, "name": ds.name, "src": ds.src, "wpid": ds.wpid,
            "rel": os.path.relpath(ds.src, os.path.dirname(ds.tree)),
            "built": rec, "building": building(ds) is not None,
            "has_html": os.path.isfile(os.path.join(ds.html, "index.html")),
            "stale": is_stale(ds, rec), "history": history(ds, 5)}


# --- build -------------------------------------------------------------------------

def _has_sphinx(argv, cwd):
    try:
        r = subprocess.run(argv + ["-c", "import sphinx"], cwd=cwd, timeout=60,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def interpreters(ds, cfg):
    """``[(argv, label)]`` to try, in order (docs/sphinx-docs-v1.md §2)."""
    out = []
    if cfg.get("python"):
        p = os.path.expanduser(cfg["python"])
        out.append(([p if os.path.isabs(p) else os.path.join(ds.tree, p)], "[docs] python"))
    for rel, label in ((("packages", "python", "bin", "python"), "IVPM packages/python"),
                       ((".venv", "bin", "python"), ".venv")):
        p = os.path.join(ds.tree, *rel)
        if os.path.isfile(p):
            out.append(([p], label))
    if os.path.isfile(os.path.join(ds.tree, ".envrc")) and shutil.which("direnv"):
        out.append((["direnv", "exec", ds.tree, "python"], "direnv"))
    out.append(([sys.executable], "the board's Python"))
    return out


def python_for(ds, cfg):
    """The first interpreter that can import sphinx: ``(argv, label)`` or None."""
    for argv, label in interpreters(ds, cfg):
        if _has_sphinx(argv, ds.tree):
            return argv, label
    return None


def _take_lock(ds):
    p = os.path.join(ds.out, "lock")
    for _ in range(2):
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            if building(ds) is not None:
                return False
            try:
                os.unlink(p)            # left by a build that died
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    return False


def _head(tree):
    if not workspace.is_git(tree):
        return None
    try:
        return workspace._git(tree, "rev-parse", "HEAD")
    except Exception:
        return None


def build(ds, cfg=None, by=None, timeout_s=TIMEOUT_S):
    """Build ``ds`` now. The record, or None if another build of it is under way."""
    cfg = {} if cfg is None else cfg
    os.makedirs(ds.out, exist_ok=True)
    if not _take_lock(ds):
        return None
    try:
        return _build(ds, cfg, by, timeout_s)
    finally:
        try:
            os.unlink(os.path.join(ds.out, "lock"))
        except FileNotFoundError:
            pass


def _build(ds, cfg, by, timeout_s):
    start = time.time()
    fp = fingerprint(ds)
    rec = {"start": start, "src": ds.src, "tree": ds.tree, "wpid": ds.wpid, "by": by,
           "fingerprint": fp, "head": _head(ds.tree), "warnings": 0}
    log = os.path.join(ds.out, "build.log")
    py = python_for(ds, cfg)
    if py is None:
        tried = ", ".join(label for _, label in interpreters(ds, cfg))
        with open(log, "w", encoding="utf-8") as f:
            f.write("No Python here can import sphinx (tried: %s).\n"
                    "Install it in the project's env (e.g. `pip install sphinx`, or add it to "
                    "ivpm.yaml), or set [docs] python in project.toml.\n" % tried)
        rec.update(result="failed", why="no Python with sphinx (tried: %s)" % tried)
        return _record(ds, rec)
    argv = py[0] + ["-m", "sphinx", "-b", "html", "-d", os.path.join(ds.out, "doctrees"),
                    ds.src, ds.html]
    rec["python"] = py[1]
    with open(log, "w", encoding="utf-8") as f:
        f.write("$ %s\n(in %s)\n\n" % (" ".join(argv), ds.src))
        f.flush()
        try:
            p = subprocess.Popen(argv, cwd=ds.src, stdin=subprocess.DEVNULL, stdout=f,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            f.write("could not start: %s\n" % e)
            rec.update(result="failed", why=str(e))
            return _record(ds, rec)
        try:
            code = p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
            code = None
    err = None
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            for ln in f:
                rec["warnings"] += bool(WARN.search(ln))
                m = FATAL.search(ln)
                err = m.group(1).strip()[:200] if m else err
    except OSError:
        pass
    if code is None:
        rec.update(result="failed", why="took over %ds" % timeout_s)
    elif code != 0:
        rec.update(result="failed", why=err or "sphinx exited %d" % code)
    else:
        rec["result"] = "warnings" if rec["warnings"] else "ok"
    return _record(ds, rec)


def _record(ds, rec):
    rec["end"] = time.time()
    fsutil.atomic_write(os.path.join(ds.out, "build.json"), json.dumps(rec, indent=1))
    fsutil.append_line(os.path.join(ds.out, "builds.jsonl"), json.dumps(rec))
    return rec


# --- in the background -------------------------------------------------------------

def kick(proj, wpid=None, if_stale=True, only=None, by=None, home=None, wait_s=0):
    """Start a detached build of the project's docsets (stale ones only, with
    ``if_stale``; ``only``: ``(entry, name)``). The docsets it started for.
    ``wait_s``: wait up to this long for the build to be under way, so a page
    shown next says "building"."""
    picked = [ds for ds in detect(proj, wpid, home=home)
              if (only is None or (ds.entry, ds.name) == tuple(only))
              and building(ds) is None and (not if_stale or is_stale(ds))]
    if not picked:
        return []
    argv = [sys.executable, "-m", "work_packet.docs", "build", proj]
    if wpid:
        argv += ["--wpid", wpid]
    if if_stale:
        argv.append("--if-stale")
    if only:
        argv += ["--only", "%s/%s" % tuple(only)]
    if by:
        argv += ["--by", by]
    env = dict(os.environ)
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = os.pathsep.join([src] + [p for p in [env.get("PYTHONPATH")] if p])
    if home:
        env["WPK_HOME"] = home
    os.makedirs(picked[0].out, exist_ok=True)
    with open(os.path.join(os.path.dirname(os.path.dirname(picked[0].out)), "kick.log"),
              "a") as log:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True, env=env)
    end = time.time() + wait_s
    while time.time() < end and p.poll() is None and building(picked[0]) is None:
        time.sleep(0.05)
    return picked


def after_step(pkt_path):
    """A step of the run at ``pkt_path`` ended: rebuild stale docs, unless the
    project says ``[docs] auto = false``. Never raises."""
    try:
        proj = layout.project_of_runs(os.path.dirname(os.path.abspath(pkt_path)))
        if proj is None or settings(proj).get("auto") is False:
            return []
        return kick(proj, os.path.basename(pkt_path), by="step")
    except Exception:
        return []


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m work_packet.docs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("proj")
    b.add_argument("--wpid")
    b.add_argument("--if-stale", action="store_true")
    b.add_argument("--only")
    b.add_argument("--by")
    a = ap.parse_args(argv)
    cfg = settings(a.proj)
    for ds in detect(a.proj, a.wpid, cfg):
        if a.only and "%s/%s" % (ds.entry, ds.name) != a.only:
            continue
        if a.if_stale and not is_stale(ds):
            continue
        rec = build(ds, cfg, by=a.by)
        print("%s/%s: %s" % (ds.entry, ds.name, rec["result"] if rec else "already building"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
