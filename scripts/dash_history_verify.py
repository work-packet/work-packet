"""D4 on the real projects (docs/dash-history-v1.md): every dashboard page of
each harvested project, from its runs and then from the history store.

Nothing real is moved. A scratch home is made whose registry points at
scratch project directories holding links to the real ones; the history
store and blobs are linked in. The pages are fetched, the ``packets`` link
of each project is removed, and they are fetched again.

    python scripts/dash_history_verify.py [OUT_DIR]

Writes ``summary.txt`` and, per project, the differences, to OUT_DIR
(default ``~/.work-packet/migration/dash-verify``).
"""

import collections
import difflib
import os
import re
import shutil
import sys
import tempfile

REAL = os.path.expanduser(os.environ.get("WPK_HOME") or "~/.work-packet")


def main(out):
    from work_packet import history, registry
    real_entries = {e["name"]: e for e in registry.entries(REAL)}
    con = history.connect(REAL)
    names = [n for n in history.projects(con) if history.harvested(con, n)
             and n in real_entries
             and os.path.isdir(os.path.join(real_entries[n]["path"], "packets"))]
    con.close()

    tmp = tempfile.mkdtemp(prefix="dash-verify-")
    home = os.path.join(tmp, "home")
    os.makedirs(os.path.join(home, "projects"))
    for n in ("history", "blobs"):
        os.symlink(os.path.join(REAL, n), os.path.join(home, n))
    for n in ("config.toml", "boards"):
        src = os.path.join(REAL, n)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(home, n))
        elif os.path.isfile(src):
            shutil.copy(src, os.path.join(home, n))
    dirs = {}
    for n in names:
        e = real_entries[n]
        d = os.path.join(tmp, "p", n)
        os.makedirs(d)
        for x in os.listdir(e["path"]):
            os.symlink(os.path.join(e["path"], x), os.path.join(d, x))
        registry.register(dict(e, path=d), home)
        dirs[n] = d

    os.environ["WPK_HOME"] = home
    os.environ.setdefault("WPK_NOW", "2026-10-28T12:00:00Z")
    from starlette.testclient import TestClient
    from work_packet import archived
    from work_packet.dash import crawl
    from work_packet.dash.app import create_app

    before = {n: crawl.crawl(TestClient(create_app()), n) for n in names}
    for n in names:
        os.unlink(os.path.join(dirs[n], "packets"))
    after = {n: crawl.crawl(TestClient(create_app()), n) for n in names}

    os.makedirs(out, exist_ok=True)
    lines, bad = [], 0
    for n in names:
        e = archived.get(n, home)
        probs = crawl.compare(before[n], after[n], [(e["path"], dirs[n])])
        bad += bool(probs)
        lines.append("%-28s %4d pages  %s" % (n, len(before[n]),
                                             "identical" if not probs else
                                             "%d differ" % len(probs)))
        with open(os.path.join(out, n + ".txt"), "w") as fp:
            fp.write("\n".join(probs) + "\n" if probs else "identical\n")
            for pr in probs:
                u = pr.split(": ")[0]
                if u in before[n] and u in after[n] and isinstance(after[n][u][1], str):
                    b = after[n][u][1].replace(e["path"], dirs[n])
                    d = difflib.unified_diff(before[n][u][1].splitlines(), b.splitlines(),
                                             "before", "after", n=1, lineterm="")
                    fp.write("\n### %s\n%s\n" % (u, "\n".join(list(d)[:40])))
            kinds = collections.Counter(re.sub(r"[?/].*", "", u.split("/", 4)[-1])
                                        for u in before[n])
            fp.write("\n### pages by kind: %s\n" % kinds.most_common(8))
    with open(os.path.join(out, "summary.txt"), "w") as fp:
        fp.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    shutil.rmtree(tmp)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else
                  os.path.join(REAL, "migration", "dash-verify")))
