"""D5 (docs/dash-history-v1.md): may a harvested packet's run directory be
removed without losing work in its workspaces?

For each harvested packet whose run directory still exists, every entry in
``work/`` is checked:

- a git repo is safe when every local branch head (and HEAD) is on a
  remote-tracking branch or in an M0 bundle, and it has no uncommitted
  changes, or they were saved as an M0 patch;
- anything that is not a git repo is listed, with its size, for Matt to keep,
  archive or drop.

    python scripts/workspace_gate.py [OUT]

Writes a Markdown report (default ``~/.work-packet/migration/workspaces.md``).
Reads only; changes nothing.
"""

import glob
import os
import subprocess
import sys

REAL = os.path.expanduser(os.environ.get("WPK_HOME") or "~/.work-packet")
MIG = os.path.join(REAL, "migration")


def git(d, *args):
    r = subprocess.run(["git", "-C", d] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def size_of(p):
    r = subprocess.run(["du", "-sb", p], capture_output=True, text=True)
    try:
        return int(r.stdout.split()[0])
    except (IndexError, ValueError):
        return 0


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.1f %s" % (n, u) if u != "B" else "%d B" % n
        n /= 1024.0


def bundle_heads(pid, name):
    out = set()
    for b in glob.glob(os.path.join(MIG, "bundles", "%s--%s.bundle" % (pid, name))):
        r = subprocess.run(["git", "bundle", "list-heads", b], capture_output=True, text=True)
        out.update(ln.split()[0] for ln in r.stdout.splitlines() if ln.strip())
    return out


def patches(pid, name):
    return sorted(glob.glob(os.path.join(MIG, "patches", "%s--%s*" % (pid, name))))


def check_repo(d, pid, name):
    """(safe, notes)."""
    notes = []
    safe = True
    heads = bundle_heads(pid, name)
    _, refs = git(d, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
    _, head = git(d, "rev-parse", "HEAD")
    tips = [ln.split() for ln in refs.splitlines() if ln.strip()]
    if head and head not in [t[1] for t in tips]:
        tips.append(["HEAD (detached)", head])
    for br, sha in tips:
        _, remote = git(d, "branch", "-r", "--contains", sha)
        if remote.strip():
            continue
        if any(git(d, "merge-base", "--is-ancestor", sha, h)[0] == 0 for h in heads):
            notes.append("`%s` is only local, in the M0 bundle" % br)
            continue
        safe = False
        notes.append("**`%s` (%s) is on no remote and in no bundle**" % (br, sha[:10]))
    _, st = git(d, "status", "--porcelain", "--untracked-files=normal")
    dirty = [ln for ln in st.splitlines() if ln.strip()]
    if dirty:
        ps = patches(pid, name)
        tracked = [ln for ln in dirty if not ln.startswith("??")]
        untracked = [ln[3:] for ln in dirty if ln.startswith("??")]
        if tracked:
            if ps:
                notes.append("%d changed files; M0 saved %s" % (
                    len(tracked), ", ".join(os.path.basename(p) for p in ps)))
            else:
                safe = False
                notes.append("**%d changed files, no M0 patch**" % len(tracked))
        saved = set()
        for x in glob.glob(os.path.join(MIG, "patches", "*", "")):
            saved.update(os.listdir(x))
        links = [u for u in untracked if os.path.islink(os.path.join(d, u.rstrip("/")))]
        kept = [u for u in untracked if u not in links and u in saved]
        left = [u for u in untracked if u not in links and u not in kept]
        if links:
            notes.append("untracked links %s (nothing to keep)" % ", ".join("`%s`" % u for u in links))
        if kept:
            notes.append("%d untracked saved by M0" % len(kept))
        if left:
            safe = False
            notes.append("**%d untracked: %s**" % (len(left), ", ".join(
                "`%s` (%s)" % (u, human(size_of(os.path.join(d, u)))) for u in left[:6])
                + (" …" if len(left) > 6 else "")))
    return safe, notes


def main(out):
    from work_packet import history, layout, registry
    paths = {e["name"]: e["path"] for e in registry.entries(REAL)}
    con = history.connect(REAL)
    rows = []
    for proj in history.projects(con):
        for pid in history.harvested(con, proj):
            if proj not in paths:
                continue
            run = layout.run_dir(paths[proj], pid)
            if not os.path.isdir(run):
                continue
            work = os.path.join(run, "work")
            items = sorted(os.listdir(work)) if os.path.isdir(work) else []
            ok = True
            lines = []
            for n in items:
                p = os.path.join(work, n)
                sz = size_of(p)
                if os.path.islink(p):
                    lines.append("- `%s`: a link to `%s`; nothing to keep" % (n, os.readlink(p)))
                elif os.path.isdir(p) and git(p, "rev-parse", "--is-inside-work-tree")[0] == 0 \
                        and os.path.exists(os.path.join(p, ".git")):
                    safe, notes = check_repo(p, pid, n)
                    ok = ok and safe
                    lines.append("- `%s` (git, %s): %s" % (
                        n, human(sz), "; ".join(notes) if notes else "clean, on a remote"))
                else:
                    ok = False
                    lines.append("- **`%s` (not git, %s)**: keep, archive or drop?" % (n, human(sz)))
            rows.append((proj, pid, ok, size_of(run), lines))
    con.close()

    total = sum(r[3] for r in rows)
    safe = [r for r in rows if r[2]]
    md = ["# Workspace check before removing harvested runs (D5)", "",
          "Generated by `scripts/workspace_gate.py`. Read-only; nothing was changed.", "",
          "%d harvested runs, %s in all; %d safe to remove (%s), %d need a decision." % (
              len(rows), human(total), len(safe), human(sum(r[3] for r in safe)),
              len(rows) - len(safe)), "",
          "| Project | Packet | Size | Safe |", "|---|---|---|---|"]
    for proj, pid, ok, sz, _ in rows:
        md.append("| %s | `%s` | %s | %s |" % (proj, pid[:8], human(sz), "yes" if ok else "**no**"))
    for proj, pid, ok, sz, lines in rows:
        md += ["", "## %s `%s`%s" % (proj, pid[:8], "" if ok else " — needs a decision"), ""]
        md += lines or ["- no `work/`"]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fp:
        fp.write("\n".join(md) + "\n")
    print("\n".join(md[:8 + len(rows) + 2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(MIG, "workspaces.md")))
