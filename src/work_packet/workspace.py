"""The root packet's workspace, filled from the project root (docs/setup.md §10).

You set a project up at its root: ``prompt.md``, ``state/``, ``identity/``
and ``work/``. When a step of the root starts, ``prepare`` makes the packet
match, idempotently:

- before the first step commits (and only if the journal has no ``seed``
  record yet): the root's ``state/`` files are
  copied into the packet, and ``prompt.md`` becomes the instruction if the
  memento has none;
- every step: each root ``identity/`` link and ``work/`` entry the packet
  lacks is added. A git repository gets a ``git worktree`` on branch
  ``wpk/<project>``; anything else gets a relative link. Git is only run
  for entries that are git repositories.

Nothing is ever removed or replaced.
"""

import os
import shutil
import subprocess
import time

from . import clock, frontmatter, fsutil, journal, schema


LOCK_RETRY_S = 1.0


class WorkspaceError(Exception):
    pass


def is_git(path):
    """A git repository or worktree (``.git`` is a directory or a file)."""
    return os.path.lexists(os.path.join(path, ".git"))


def branch_for(project):
    return "wpk/%s" % project


def seeded(pkt):
    return any(r.get("type") == "seed" for r in pkt.journal().records)


def _git(repo, *args):
    for retry in (True, False):
        try:
            r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
        except OSError as e:
            raise WorkspaceError("git: %s" % e) from None
        # VS Code's git extension can hold the index lock for a moment
        # (docs/vscode-plan.md §5): wait once, then try again.
        if not (retry and r.returncode and "index.lock" in (r.stderr or "")):
            break
        time.sleep(LOCK_RETRY_S)
    if r.returncode:
        raise WorkspaceError("git %s in %s: %s" % (
            " ".join(args), repo, (r.stderr or r.stdout).strip()))
    return r.stdout.strip()


def _seed(pkt, proj):
    """Copy the root's ``state/`` and ``prompt.md`` into the packet. Returns the files."""
    files = []
    src = os.path.join(proj, "state")
    if os.path.isdir(src):
        for dp, dns, fns in os.walk(src):
            dns.sort()
            for f in sorted(fns):
                s = os.path.join(dp, f)
                rel = os.path.relpath(s, src)
                d = os.path.join(pkt.state_dir, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                if os.path.islink(s):
                    if os.path.lexists(d):
                        os.unlink(d)
                    os.symlink(os.readlink(s), d)
                else:
                    shutil.copyfile(s, d)
                files.append("state/" + rel.replace(os.sep, "/"))
    prompt = os.path.join(proj, "prompt.md")
    if os.path.isfile(prompt):
        try:
            meta, body = pkt.load_memento()
        except FileNotFoundError:
            meta, body = None, ""
        if not body.strip():
            text = fsutil.read_text(prompt)
            if text.strip():
                fsutil.atomic_write(pkt.memento_path, frontmatter.dump(meta or None, text))
                files.append("memento.md")
    return files


def _link_target(src):
    """Where a link at the root points, as an absolute path."""
    t = os.readlink(src)
    return t if os.path.isabs(t) else os.path.normpath(os.path.join(os.path.dirname(src), t))


def _identity(pkt, proj):
    added = []
    src = os.path.join(proj, "identity")
    if not os.path.isdir(src):
        return added
    for n in sorted(os.listdir(src)):
        s, d = os.path.join(src, n), os.path.join(pkt.identity_dir, n)
        if os.path.lexists(d):
            continue
        os.makedirs(pkt.identity_dir, exist_ok=True)
        os.symlink(_link_target(s) if os.path.islink(s) else os.path.abspath(s), d)
        added.append("identity/" + n)
    return added


def shares(clone, listed=()):
    """Directories of ``clone`` to link into a worktree of it: ``listed`` (from
    ``[setup]``), and every top-level link git does not track."""
    out = [s.strip("/") for s in listed]
    for n in sorted(os.listdir(clone)):
        p = os.path.join(clone, n)
        if n != ".git" and n not in out and os.path.islink(p):
            r = subprocess.run(["git", "-C", clone, "ls-files", "--error-unmatch", "--", n],
                               capture_output=True, text=True)
            if r.returncode:
                out.append(n)
    return out


def link_shares(clone, tree, names):
    """Link ``clone/<name>`` into ``tree`` for each name that ``tree`` lacks, and
    exclude the names in git's ``info/exclude``. Git reads that file from the
    clone's common directory only, so it covers the clone and all its worktrees."""
    linked = []
    for n in names:
        s, d = os.path.join(clone, n), os.path.join(tree, n)
        if os.path.lexists(s) and not os.path.lexists(d):
            os.symlink(_link_target(s) if os.path.islink(s) else os.path.abspath(s), d)
            linked.append(n)
    if linked:
        exclude(clone, linked)


def exclude(clone, names):
    """Add ``names`` (top-level) to the clone's ``info/exclude`` unless listed."""
    common = _git(clone, "rev-parse", "--git-common-dir")
    p = os.path.join(clone, common, "info", "exclude")
    try:
        with open(p) as fp:
            have = {ln.strip().strip("/") for ln in fp}
    except FileNotFoundError:
        have = set()
    new = [n for n in names if n not in have]
    if new:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a") as fp:
            fp.write("".join("/%s\n" % n for n in new))


def add_worktree(clone, tree, branch=None, detach=False):
    """``git worktree add`` of ``clone`` at ``tree``: on ``branch`` (created from the
    clone's ``HEAD`` if it does not exist), or detached at ``HEAD``."""
    if detach:
        _git(clone, "worktree", "add", "--detach", tree, "HEAD")
        return
    exists = subprocess.run(["git", "-C", clone, "rev-parse", "--verify", "--quiet",
                             "refs/heads/" + branch], capture_output=True).returncode == 0
    if exists:
        _git(clone, "worktree", "add", tree, branch)
    else:
        _git(clone, "worktree", "add", "-b", branch, tree, "HEAD")


def _work(pkt, proj, project, spec):
    added = []
    src = os.path.join(proj, "work")
    if not os.path.isdir(src):
        return added
    listed = {r.get("name"): r for r in spec.get("repo", [])}
    dst = os.path.join(pkt.path, "work")
    for n in sorted(os.listdir(src)):
        s, d = os.path.join(src, n), os.path.join(dst, n)
        if os.path.lexists(d) or n.startswith("."):
            continue
        os.makedirs(dst, exist_ok=True)
        if os.path.isdir(s) and is_git(s):
            want = listed.get(n, {})
            branch = want.get("branch") or branch_for(project)
            add_worktree(s, d, branch)
            link_shares(s, d, shares(s, want.get("share", ())))
            added.append("work/%s (worktree on %s)" % (n, branch))
        else:
            os.symlink(os.path.relpath(s, dst), d)
            added.append("work/%s (link)" % n)
    return added


def prepare(pkt, proj, project, spec=None, first=True):
    """Make the root packet match the project root. Returns what it added.
    ``first``: no step has committed yet; only then is the packet seeded, so a
    packet that ran before this existed is never seeded. Raises WorkspaceError."""
    added = []
    try:
        if first and not seeded(pkt):
            files = _seed(pkt, proj)
            if files:            # nothing at the root (a `wpk new --prompt` project): no record
                journal.append(pkt.journal_path, {"type": "seed",
                                                  "t": schema.format_timestamp(clock.now()),
                                                  "files": files})
            added += files
        added += _identity(pkt, proj)
        added += _work(pkt, proj, project, spec or {})
    except OSError as e:
        raise WorkspaceError(str(e)) from None
    return added


def linked_dirs(pkt):
    """Real paths of the packet's ``work/`` entries that are links (plain directories
    shared from the root): the harness gets them like ``identity/`` links."""
    out = []
    w = os.path.join(pkt.path, "work")
    if os.path.isdir(w):
        for n in sorted(os.listdir(w)):
            p = os.path.join(w, n)
            if os.path.islink(p) and os.path.isdir(p):
                out.append(os.path.realpath(p))
    return out


def git_trees(pkt):
    """``{name: path}`` of the packet's ``work/`` entries that are git checkouts."""
    out = {}
    w = os.path.join(pkt.path, "work")
    if os.path.isdir(w):
        for n in sorted(os.listdir(w)):
            p = os.path.join(w, n)
            if not n.startswith(".") and not os.path.islink(p) and os.path.isdir(p) \
                    and is_git(p):
                out[n] = p
    return out


def heads(pkt):
    """``{name: sha}`` for each work repo (dash-tasks.md §6.6). Unreadable ones are left out."""
    out = {}
    for n, p in git_trees(pkt).items():
        try:
            out[n] = _git(p, "rev-parse", "HEAD")
        except WorkspaceError:
            pass
    return out


def dirty(pkt):
    """``{name: [porcelain lines]}`` for each work repo with uncommitted changes."""
    out = {}
    for n, p in git_trees(pkt).items():
        try:
            st = _git(p, "status", "--porcelain")
        except WorkspaceError as e:
            out[n] = [str(e)]
            continue
        if st:
            out[n] = st.splitlines()
    return out


def commits_since(pkt, old, limit=20):
    """``{name: ["sha subject", …]}``: commits in each work repo after ``old[name]``
    (the heads of the last step), newest first."""
    out = {}
    for n, p in git_trees(pkt).items():
        base = (old or {}).get(n)
        if not base:
            continue
        try:
            log = _git(p, "log", "--format=%h %s", "-n", str(limit), "%s..HEAD" % base)
        except WorkspaceError:
            continue
        if log:
            out[n] = log.splitlines()
    return out
