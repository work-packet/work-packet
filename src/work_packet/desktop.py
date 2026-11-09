"""A packet's desktop: GUI programs started in its IDE server, shown in a
browser tab (docs/desktop.md).

``[desktop]`` in ``config.toml`` turns it on. wpkd writes the merged table to
the server's directory (``desktop.conf.json``) and starts the server under
``sched/xproxy.py``, which reads it there, on whichever host runs the
server; xproxy reports in ``desktop.json`` next to it.
"""

import json
import os
import sys
import time

from . import registry, schema

# wpk's own [desktop.env] (§5.3): set wherever DISPLAY is, under the site's and yours.
ENV_DEFAULTS = {
    "SSH_ASKPASS_REQUIRE": "never",    # ssh with no terminal: fail, not a hidden prompt
    "NO_AT_BRIDGE": "1",               # quiet GTK's accessibility-bus warnings
    "QT_XCB_NO_MITSHM": "1",           # Qt5: no MIT-SHM; xproxy can't pass its fds
}
# The Apps menu's own entries, under [desktop.apps]; `terminal = ""` removes one.
APP_DEFAULTS = {"terminal": {"cmd": "xterm", "label": "Terminal"}}
RUN = "desktop.run"                   # the board's requests to start an app, for xproxy
CONF = "desktop.conf.json"
STATE = "desktop.json"
ENV = "desktop.env.json"


def load_config(h=None):
    """``[desktop]`` over the defaults; ``env`` over wpk's own (site and user
    layers come from ``registry.load_config_file``)."""
    t = registry.load_config_file(h).get("desktop") or {}
    d = dict(schema.DESKTOP_DEFAULTS)
    d.update(t)
    d["env"] = dict(ENV_DEFAULTS, **(t.get("env") or {}))
    d["unset"] = list(t.get("unset", schema.DESKTOP_DEFAULTS["unset"]))
    d["apps"] = apps(t.get("apps") or {})
    return d


def apps(table):
    """``[desktop.apps]`` over wpk's own, each as ``{"cmd", "label"}``; an
    empty command removes an entry."""
    out = dict(APP_DEFAULTS)
    for k, v in table.items():
        v = {"cmd": v} if isinstance(v, str) else dict(v)
        if not (v.get("cmd") or "").strip():
            out.pop(k, None)
            continue
        out[k] = {"cmd": v["cmd"], "label": v.get("label") or k}
    return out


def workdir(target):
    """Where apps start: the folder a workspace file is for, or the folder."""
    t = (target or "").rstrip("/")
    if t.endswith(".code-workspace"):
        d = os.path.dirname(t)
        return os.path.dirname(d) if os.path.basename(d) == ".vscode" else d
    return t or None


def request_run(server_dir, name):
    """Ask xproxy to start app ``name`` (it watches ``desktop.run/``)."""
    import secrets
    d = os.path.join(server_dir, RUN)
    os.makedirs(d, mode=0o700, exist_ok=True)
    p = os.path.join(d, "%d-%s.json" % (int(1000 * time.time()), secrets.token_hex(4)))
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"app": name}, f)
    os.replace(p + ".tmp", p)
    return p


def title(target, key=""):
    """A name for the tab: the folder, or the project or packet a workspace
    file is for (``<dir>/.vscode/<name>.code-workspace``)."""
    t = (target or "").rstrip("/")
    if t.endswith(".code-workspace"):
        d = os.path.dirname(t)
        if os.path.basename(d) == ".vscode":
            return os.path.basename(os.path.dirname(d)) or key
        return os.path.basename(t)[:-len(".code-workspace")] or key
    return os.path.basename(t) or key


def label(home, key, target):
    """What the tab is called, most telling first: the project and packet that
    last opened this server (``ide_launch`` opens), else ``title``."""
    from . import ide_launch
    last = (ide_launch.opens(home, key) or [{}])[-1]
    proj, wpid = last.get("project"), last.get("wpid")
    if proj:
        return "%s · %s" % (proj, wpid[:8]) if wpid else proj
    return title(target, key)


def path(key):
    return "/desk/%s/" % key


def write_conf(server_dir, cfg, title=None, cwd=None):
    """What xproxy reads, in the server's directory (0600)."""
    rec = dict(cfg, title=title or "wpk", cwd=cwd)
    p = os.path.join(server_dir, CONF)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(rec, f, sort_keys=True)
    os.replace(tmp, p)
    return p


def wrap(server_dir, key, argv):
    """``argv`` run under xproxy, which gives it the display."""
    return [sys.executable, "-m", "work_packet.sched.xproxy", "--conf",
            os.path.join(server_dir, CONF), "--state", server_dir, "--key", key, "--"] + list(argv)


def _read(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def state(server_dir):
    """xproxy's report (``desktop.json``), or None: no display was set up."""
    return _read(os.path.join(server_dir, STATE))


def applied_env(server_dir):
    return _read(os.path.join(server_dir, ENV))


def live(server_dir):
    """The report while its xproxy still serves the viewer socket, else None."""
    st = state(server_dir)
    if not st or st.get("x") in ("ended", "unavailable") or not st.get("vnc"):
        return None
    return st
