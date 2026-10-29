"""``wpk sched doctor``: can this pool run steps on its farm? (plan Q4.7)

Checks the batch commands, then submits one small probe job that reports
whether the home and every project are visible from a node, whether
``wpk`` and ``claude`` are there, and the node's clock.
"""

import os
import shutil
import time
from dataclasses import dataclass, field

from .. import clock, registry
from . import config as sconfig

SKEW_S = 5
COMMANDS = {"slurm": ("sbatch", "squeue", "sacct", "scancel"), "lsf": ("bsub", "bjobs", "bkill")}


@dataclass
class Check:
    level: str                      # ok | warn | missing
    title: str
    detail: str = ""
    fix: list = field(default_factory=list)


def _users_on_host():
    """Login names with processes here (uid >= 1000), other than this one's."""
    import pwd
    me, out = os.getuid(), set()
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            uid = os.stat(os.path.join("/proc", d)).st_uid
        except OSError:
            continue
        if uid >= 1000 and uid != me and uid != 65534:
            try:
                out.add(pwd.getpwuid(uid).pw_name)
            except KeyError:
                out.add(str(uid))
    return sorted(out)


def run(h=None, probe=True, wait_s=180):
    h = h or registry.home()
    cfg = sconfig.load(h)
    raw = registry.load_config_file(h)
    out = []
    users = _users_on_host()
    listen = (raw.get("server") or {}).get("listen", "")
    if users and listen != "unix":
        out.append(Check("warn", "other users on this host (%s)" % ", ".join(users[:5]),
                         "the board's TCP port on 127.0.0.1 is open to every user here",
                         ['set [server] listen = "unix" in config.toml and use `wpk url` '
                          'for the ssh -L line']))
    else:
        out.append(Check("ok", "board listener: %s" % ("unix socket" if listen == "unix"
                                                       else "loopback, single-user host")))
    sp = registry.site_config_path()
    if sp and os.path.exists(sp):
        out.append(Check("ok", "site config: %s" % sp))
        locks = registry.overridden_locks(h)
        if locks:
            out.append(Check("warn", "config.toml sets locked keys: %s" % ", ".join(locks),
                             "the site config locks them; its values are used",
                             ["remove them from %s" % os.path.join(h, "config.toml")]))
    be =cfg.get("backend", "local")
    if be == "local":
        out.append(Check("ok", "backend local: steps run on this host"))
        return out
    sub = cfg.get(be) or {}
    bindir = sub.get("bin", "")
    miss = [c for c in COMMANDS[be] if not (os.access(os.path.join(bindir, c), os.X_OK)
                                             if bindir else shutil.which(c))]
    if miss:
        out.append(Check("missing", "batch commands not found: %s" % ", ".join(miss),
                         "looked in %s" % (bindir or "PATH"),
                         ["set [sched.%s] bin to their directory, or load the module" % be]))
        return out
    out.append(Check("ok", "%s commands found%s" % (be, " in " + bindir if bindir else "")))
    if probe:
        out += _probe(h, cfg)
    return out


def _probe(h, cfg):
    import shlex
    from .backends import DONE, LOST, Task
    from .backends import get as get_backend
    from .jobs import jobs_dir, new_id
    b = get_backend(cfg, h)
    paths = [h] + [e["path"] for e in registry.entries(h)]
    script = "; ".join(["echo start $(date +%s)"] +
                       ["test -d %s && echo seen %s || echo unseen %s" % (
                           shlex.quote(p), shlex.quote(p), shlex.quote(p)) for p in paths] +
                       ["command -v wpk >/dev/null && echo have wpk || echo lack wpk",
                        "command -v claude >/dev/null && echo have claude || echo lack claude",
                        "echo clock $(date +%s)"])
    env = (cfg.get("node_env") or "").strip()
    jid = new_id()
    log = os.path.join(jobs_dir(h), "probe-%s.log" % jid)
    size = sconfig.size(cfg, cfg["default_size"])
    task = Task(jid, "probe", "-", "-", h, size, log, name="wpk-probe:%s" % jid,
                argv=["bash", "-c", ("%s && " % env if env else "") + script])
    t0 = clock.real_now()
    try:
        ref = b.submit(task)
    except Exception as e:                       # noqa: BLE001: report, do not crash
        return [Check("missing", "cannot submit a probe job", str(e))]
    deadline = time.time() + 180
    st = None
    while time.time() < deadline:
        st = b.poll([ref]).get(ref)
        if st is not None and st.state in (DONE, LOST):
            break
        time.sleep(1)
    else:
        b.cancel(ref, hard=True)
        return [Check("warn", "the probe job did not finish in 3 minutes",
                      "queue wait may be long; try `wpk sched doctor` again later")]
    seen = {"have": set(), "lack": set(), "seen": [], "unseen": []}
    node_clock = None
    try:
        lines = open(log).read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        k, _, v = line.partition(" ")
        if k in ("have", "lack"):
            seen[k].add(v)
        elif k in ("seen", "unseen"):
            seen[k].append(v)
        elif k == "clock":
            try:
                node_clock = int(v)
            except ValueError:
                pass
    out = []
    if not lines:
        return [Check("missing", "the probe job wrote no output", "%s (state %s)" % (
            log, st.state if st else "?"))]
    if seen["unseen"]:
        out.append(Check("missing", "not visible from a node: %s" % ", ".join(seen["unseen"]),
                         "packets must be on a file system the nodes share, at the same path"))
    else:
        out.append(Check("ok", "the home and %d project%s are visible from a node" % (
            len(seen["seen"]) - 1, "" if len(seen["seen"]) == 2 else "s")))
    for tool in ("wpk", "claude"):
        if tool in seen["lack"]:
            out.append(Check("missing", "%s is not on the node's PATH" % tool, "",
                             ["set [sched] node_env to the line that puts it there "
                              "(a module load or a venv activate)"]))
        else:
            out.append(Check("ok", "%s found on the node" % tool))
    if node_clock is not None:
        # The node read its clock between our submit (t0) and now: outside that
        # window by more than SKEW_S, the clocks disagree.
        lo, hi = t0.timestamp() - SKEW_S, time.time() + SKEW_S
        if node_clock > hi or node_clock < lo:
            skew = node_clock - hi + SKEW_S if node_clock > hi else node_clock - lo - SKEW_S
            out.append(Check("warn", "the node's clock is about %+.0f s from this host's" % skew,
                             "leases compare times across hosts; run NTP on both"))
        else:
            out.append(Check("ok", "the node's clock agrees with this host's (within %d s)"
                             % SKEW_S))
    try:
        os.unlink(log)
    except OSError:
        pass
    return out
