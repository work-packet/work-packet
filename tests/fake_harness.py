"""Stand-ins for an editor server and the harness processes under it
(docs/vscode-monitor-plan.md S3 tests). Each process sleeps until it is killed.

``fake_harness.py server <spec.json>``
    Starts each child in the spec (``[{"argv": [...], "env": {...}}]``), so the
    children inherit its environment (``WPK_IDE_LAUNCH``), as VS Code's
    extension host and terminals do.
``fake_harness.py claude <config dir> <cwd> <session id> <entrypoint> [<procStart>]``
    Writes ``<config dir>/sessions/<pid>.json`` the way Claude Code 2.1.280
    does, then waits. The test appends the transcript itself.
``fake_harness.py codex <rollout path>``
    Holds ``<rollout path>`` open, as a running Codex does.
"""

import json
import os
import subprocess
import sys
import time


def forever():
    while True:
        time.sleep(60)


def main(argv):
    mode = argv[0]
    if mode == "server":
        with open(argv[1]) as fp:
            spec = json.load(fp)
        for c in spec:
            subprocess.Popen(c["argv"], env=dict(os.environ, **c.get("env", {})))
        forever()
    if mode == "claude":
        cfg, cwd, sid, entry = argv[1:5]
        with open("/proc/self/stat") as fp:
            start = fp.read().rpartition(")")[2].split()[19]
        start = argv[5] if len(argv) > 5 else start
        os.makedirs(os.path.join(cfg, "sessions"), exist_ok=True)
        p = os.path.join(cfg, "sessions", "%d.json" % os.getpid())
        with open(p + ".tmp", "w") as fp:
            json.dump({"pid": os.getpid(), "sessionId": sid, "cwd": cwd, "procStart": start,
                       "kind": "interactive", "entrypoint": entry, "status": "busy",
                       "version": "2.1.280", "messagingSocketPath": "/SENTINEL-SOCK"}, fp)
        os.replace(p + ".tmp", p)
        forever()
    if mode == "codex":
        os.makedirs(os.path.dirname(argv[1]), exist_ok=True)
        fp = open(argv[1], "a")     # noqa: SIM115  (held open: that is the point)
        with open(argv[1] + ".ready", "w"):
            pass
        forever()
        fp.close()
    raise SystemExit("unknown mode %r" % mode)


if __name__ == "__main__":
    main(sys.argv[1:])
