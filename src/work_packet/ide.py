"""VS Code on a packet or a work folder (docs/vscode-plan.md).

What to open (``resolve``), the workspace file wpk keeps for a packet
(``ensure_workspace``), and the links that open it: desktop VS Code through a
``vscode://`` URL, web VS Code under the board's ``/ide/``.

The workspace file is shared with VS Code, so wpk merges: it owns its folders,
its tasks (labels starting ``wpk: ``) and a few settings, and keeps anything
else you added. It writes only when its part changed.
"""

import getpass
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

from . import registry, setup, workspace
from .fsutil import atomic_write
from .packet import Packet

VSDIR = ".vscode"                       # in the packet or the project root; not packet format
WATCH_EXCLUDE = ["**/packages/**", "**/rundir/**", "**/build*/**"]
PACKET_HIDE = ["work", "state", "steps", "children", ".pending", ".state.old", VSDIR]
ROOT_HIDE = ["work", "state", "packets", "runs", ".setup", VSDIR]
TITLE_PREFIX = "wpk: "
# While the runner owns the packet (docs/vscode-plan.md §5, workflow-review §4.2):
# a guard against mistakes, not a security boundary.
GUARD = {"files.readonlyInclude": {"**": True}, "git.autorefresh": False,
         "git.autofetch": False, "editor.formatOnSave": False}


class IdeError(Exception):
    pass


@dataclass
class Open:
    """One thing to open in VS Code."""
    kind: str                   # packet | root | clone | worktree | plain
    path: str                   # the workspace file, or the folder
    label: str
    project: str
    wpid: str
    note: Optional[str] = None
    owner: str = "you"          # you | runner (docs/vscode-plan.md §5)
    folders: list = field(default_factory=list)   # a workspace's (name, abs path)

    @property
    def is_workspace(self):
        return self.path.endswith(".code-workspace")

    def to_json(self):
        return {"kind": self.kind, "path": self.path, "label": self.label,
                "project": self.project, "wpid": self.wpid, "note": self.note,
                "owner": self.owner, "workspace": self.is_workspace}


# --- what to open ----------------------------------------------------------------

def _packet_of(t, tg):
    """The packet ``t`` names, if it names one other than the root."""
    if registry.get(t) is not None or os.path.isfile(os.path.join(t, "project.toml")):
        return tg.packet
    try:
        p = registry.resolve(t)
    except registry.LookupFailed:
        return tg.packet
    return Packet(p)


def owner(pkt):
    """``runner`` while a step runs or the packet waits for its next one, else ``you``."""
    from . import lease as lease_mod
    old = lease_mod.read(pkt.lease_path)
    if old is not None and not lease_mod.is_stale(old):
        return "runner"
    try:
        meta = pkt.load_status()[0]
    except Exception:
        return "you"
    return "runner" if meta.get("state") in ("RUNNABLE", "SLEEPING") else "you"


def resolve(t, repo=None, packet=False):
    """What ``wpk ide <t> [<repo>] [--packet]`` opens."""
    try:
        tg = setup.target(t)
    except setup.SetupError as e:
        raise IdeError(str(e)) from None
    pkt = _packet_of(t, tg)
    who = owner(pkt)
    if repo is None:
        if pkt.path == tg.packet.path and not tg.started():
            ws, folders = ensure_root_workspace(tg)
            return Open("root", ws, "%s (project root: not started yet)" % tg.name,
                        tg.name, pkt.wpid, folders=folders)
        ws, folders = ensure_workspace(tg, pkt)
        return Open("packet", ws, "%s packet %s" % (tg.name, pkt.wpid[:8]), tg.name,
                    pkt.wpid, owner=who, folders=folders)
    if repo not in tg.entries():
        raise IdeError("no %r in %s's work/ (there is: %s)" % (
            repo, tg.name, ", ".join(tg.entries()) or "nothing"))
    clone = os.path.join(tg.work, repo)
    if not workspace.is_git(clone):
        note = "a plain directory is shared: the packet sees this one" if packet else None
        return Open("plain", clone, "%s work/%s (shared, no rollback)" % (tg.name, repo),
                    tg.name, pkt.wpid, note=note)
    if not packet:
        return Open("clone", clone, "%s work/%s (your clone)" % (tg.name, repo),
                    tg.name, pkt.wpid)
    tree = os.path.join(pkt.path, "work", repo)
    if not workspace.is_git(tree):
        raise IdeError("%s has no worktree of %s yet: it is made when a step starts"
                       % (pkt.wpid[:8], repo))
    return Open("worktree", tree, "%s work/%s (packet: %s)" % (tg.name, repo, tg.branch),
                tg.name, pkt.wpid, owner=who)


# --- the workspace file ------------------------------------------------------------

_JSONC = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.S)
_TRAILING = re.compile(r'("(?:\\.|[^"\\])*")|,(\s*[}\]])')


def parse_jsonc(text):
    """JSON with comments and trailing commas, as VS Code writes it."""
    text = _JSONC.sub(lambda m: m.group(1) or "", text)
    text = _TRAILING.sub(lambda m: m.group(1) or m.group(2), text)
    return json.loads(text) if text.strip() else {}


def _env(tg, pkt):
    return {"WPK_PROJECT": tg.name, "WPK_PROJECT_DIR": tg.proj, "WPK_WPID": pkt.wpid,
            "WPK_PACKET": pkt.path, "WPK_WORK": tg.work}


def _tasks(pkt):
    w = pkt.wpid
    return [{"label": "wpk: show", "type": "shell", "command": "wpk show %s" % w,
             "problemMatcher": []},
            {"label": "wpk: log", "type": "shell", "command": "wpk log %s" % w,
             "problemMatcher": []},
            {"label": "wpk: check", "type": "shell", "command": "wpk check %s"
             % shlex.quote(pkt.path), "problemMatcher": []}]


def packet_name(tg, pkt):
    """The project's name for its root; ``<project>/<name>`` for a child, with the
    name it was spawned under (or its short WPID)."""
    if pkt.path == tg.packet.path:
        return tg.name
    name = None
    try:
        parent = pkt.load_status()[0].get("parent")
        if parent:
            pp = Packet(os.path.join(os.path.dirname(pkt.path), parent))
            for r in pp.journal().records:
                if r.get("type") == "commit-begin":
                    for e in (r.get("decision") or {}).get("spawn") or ():
                        if e.get("wpid") == pkt.wpid:
                            name = e.get("name")
    except Exception:           # a name is a nicety; never fail the open for it
        name = None
    return "%s/%s" % (tg.name, name or pkt.wpid[:8])


def title(name):
    """The window title (the browser tab, in web VS Code)."""
    return "%s%s${dirty}" % (TITLE_PREFIX, name)


def _settings(tg, pkt):
    return {
        "window.title": title(packet_name(tg, pkt)),
        "files.watcherExclude": {p: True for p in WATCH_EXCLUDE},
        "search.exclude": {p: True for p in WATCH_EXCLUDE},
        "terminal.integrated.env.linux": _env(tg, pkt),
    }


def merge(old, folders, settings, tasks):
    """``old`` (a parsed workspace) with wpk's part replaced and yours kept.

    Folders: wpk's first, then yours (any path wpk did not write last time,
    as recorded under ``"wpk"``). Settings: dict-valued keys merge by entry,
    others are set. Tasks: the ``wpk: `` ones are replaced.
    """
    new = dict(old)
    mine = set((old.get("wpk") or {}).get("folders") or [])
    paths = [f["path"] for f in folders]
    yours = [f for f in old.get("folders") or []
             if isinstance(f, dict) and f.get("path") not in mine and f.get("path") not in paths]
    new["folders"] = list(folders) + yours
    st = dict(old.get("settings") or {})
    for k, v in settings.items():
        if k == "window.title" and not str(st.get(k, TITLE_PREFIX)).startswith(TITLE_PREFIX):
            continue            # a title of your own stays
        if isinstance(v, dict) and isinstance(st.get(k), dict):
            st[k] = dict(st[k], **v)
        else:
            st[k] = v
    new["settings"] = st
    tk = dict(old.get("tasks") or {"version": "2.0.0"})
    tk.setdefault("version", "2.0.0")
    tk["tasks"] = list(tasks) + [x for x in tk.get("tasks") or []
                                 if not str(x.get("label", "")).startswith("wpk: ")]
    new["tasks"] = tk
    new["wpk"] = dict(old.get("wpk") or {}, folders=paths)
    return new


def guard(ws, runner):
    """``ws`` with the GUARD settings on (``runner``) or off. What they replaced
    is kept under ``"wpk"`` and put back when they come off."""
    new = dict(ws)
    st = dict(new.get("settings") or {})
    meta = dict(new.get("wpk") or {})
    prior = meta.get("guard")
    if runner and prior is None:
        prior = {}
        for k, v in GUARD.items():
            prior[k] = st.get(k)
            st[k] = dict(st[k], **v) if isinstance(v, dict) and isinstance(st.get(k), dict) \
                else v
        meta["guard"] = prior
    elif not runner and prior is not None:
        for k, v in GUARD.items():
            if prior.get(k) is None:
                st.pop(k, None)
            else:
                st[k] = prior[k]
        del meta["guard"]
    new["settings"] = st
    new["wpk"] = meta
    return new


def _load(path):
    """A workspace or settings file, parsed; ``{}`` if there is none."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fp:
            got = parse_jsonc(fp.read())
    except (OSError, ValueError) as e:
        raise IdeError("%s does not parse (%s); fix or delete it" % (path, e)) from None
    if not isinstance(got, dict):
        raise IdeError("%s is not a JSON object; fix or delete it" % path)
    return got


def _save(path, old, new):
    if new == old:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write(path, json.dumps(new, indent=2) + "\n")
    return True


def set_owner(pkt):
    """Turn the GUARD settings on or off in a packet's workspace file, if it has
    one, to match who owns the packet now. The executor calls it after a step and
    after pause, hand-off and the rest."""
    path = workspace_path(pkt)
    if not os.path.exists(path):
        return False
    old = _load(path)
    return _save(path, old, guard(old, owner(pkt) == "runner"))


def _write_merged(path, folders, settings, tasks, runner=False):
    """Merge into ``path``; True if it changed. A file that does not parse is left alone."""
    old = _load(path)
    return _save(path, old, guard(merge(old, folders, settings, tasks), runner))


def _hide(folder, names):
    """``<folder>/.vscode/settings.json`` hides ``names`` (folder settings, merged)."""
    path = os.path.join(folder, VSDIR, "settings.json")
    try:
        old = _load(path)
    except IdeError:
        return False            # yours, and broken: leave it
    new = dict(old)
    new["files.exclude"] = dict(old.get("files.exclude") or {}, **{n: True for n in names})
    return _save(path, old, new)


def packet_folders(tg, pkt):
    """``[(name, abs path)]`` for a packet's workspace (docs/vscode-plan.md §2)."""
    out = []
    w = os.path.join(pkt.path, "work")
    if os.path.isdir(w):
        for n in sorted(os.listdir(w)):
            p = os.path.join(w, n)
            if n.startswith(".") or not os.path.isdir(p):
                continue
            if workspace.in_packet(p):
                out.append(("%s (the packet folder)" % n, os.path.realpath(p)))
            elif os.path.islink(p):
                out.append(("%s (shared, no rollback)" % n, p))
            elif workspace.is_git(p):
                out.append(("%s (packet: %s)" % (n, tg.branch), p))
    out.append(("state", pkt.state_dir))
    out.append(("packet", pkt.path))
    return out


def root_folders(tg):
    out = []
    for n in tg.entries():
        p = os.path.join(tg.work, n)
        if os.path.isdir(p):
            out.append(("%s (your clone)" % n if workspace.is_git(p)
                        else "%s (shared, no rollback)" % n, p))
    out.append(("state", os.path.join(tg.proj, "state")))
    out.append(("project", tg.proj))
    return out


def _folders_json(ws, folders):
    d = os.path.dirname(ws)
    return [{"path": os.path.relpath(p, d), "name": n} for n, p in folders]


def workspace_path(pkt):
    return os.path.join(pkt.path, VSDIR, "packet.code-workspace")


def root_workspace_path(tg):
    return os.path.join(tg.proj, VSDIR, "project.code-workspace")


def ensure_workspace(tg, pkt):
    """Write or refresh a packet's workspace file; ``(path, folders)``."""
    ws = workspace_path(pkt)
    folders = packet_folders(tg, pkt)
    _write_merged(ws, _folders_json(ws, folders), _settings(tg, pkt), _tasks(pkt),
                  runner=owner(pkt) == "runner")
    _hide(pkt.path, PACKET_HIDE)
    return ws, folders


def ensure_root_workspace(tg):
    ws = root_workspace_path(tg)
    folders = root_folders(tg)
    _write_merged(ws, _folders_json(ws, folders), _settings(tg, tg.packet), [])
    _hide(tg.proj, ROOT_HIDE)
    return ws, folders


# --- links ----------------------------------------------------------------------

def load_config(h=None):
    from . import schema
    d = dict(schema.IDE_DEFAULTS)
    d.update(registry.load_config_file(h).get("ide") or {})
    return d


def ssh_host(cfg, ts=None, name=None):
    """What the laptop's VS Code SSHes to: ``[ide] ssh_host`` as written (an alias
    from your ~/.ssh/config, or user@host); else ``you@`` the name the browser
    used (``name``), the MagicDNS name or the host name. The user is named because
    the laptop's own login (on Windows, say) is often a different one."""
    if cfg.get("ssh_host"):
        return cfg["ssh_host"]
    if not name and ts is not None:
        st = ts.status() or {}
        fq = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
        name = fq.split(".")[0] if fq else None
    return "%s@%s" % (getpass.getuser(), name or socket.gethostname())


def same_machine(listener, user_agent, platform=None):
    """Whether the browser is likely on this machine, so ``vscode://file`` works.

    Loopback alone does not say so: a browser on another computer reaches a
    loopback-only board through a forwarded port. So the browser must also run
    the same OS as this host (docs/vscode-plan.md §3)."""
    if listener != "loopback":
        return False
    ua = user_agent or ""
    platform = sys.platform if platform is None else platform
    if platform.startswith("linux"):
        return ("Linux" in ua or "X11" in ua) and "Android" not in ua
    if platform == "darwin":
        return "Macintosh" in ua and "iPhone" not in ua and "iPad" not in ua
    if platform.startswith("win"):
        return "Windows" in ua
    return False


def desktop_choice(cfg, listener, user_agent):
    """``local`` or ``remote``: which ``vscode://`` link the board follows first."""
    pick = cfg.get("desktop_link") or "auto"
    if pick in ("local", "remote"):
        return pick
    return "local" if same_machine(listener, user_agent) else "remote"


def desktop_url(op, host=None):
    """``vscode://`` link: ``file`` when VS Code runs here (``host`` None), else
    Remote-SSH to ``host``."""
    p = quote(op.path, safe="/")
    if host is None:
        return "vscode://file%s" % p
    return "vscode://vscode-remote/ssh-remote+%s%s?windowId=_blank" % (quote(host, safe="@"), p)


def web_path(op, base="/ide/"):
    return "%s?%s=%s" % (base, "workspace" if op.is_workspace else "folder",
                         quote(op.path, safe="/"))


def open_command(op, env=None, which=shutil.which):
    """The command ``wpk ide --open`` runs, or None when there is no VS Code to talk to."""
    env = os.environ if env is None else env
    code = which("code")
    if code is None:
        return None
    if env.get("VSCODE_IPC_HOOK_CLI") or env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return [code, op.path]
    return None


def launch(op):
    argv = open_command(op)
    if argv is None:
        raise IdeError("no VS Code to open it in here (no `code`, or no display and not "
                       "in a VS Code terminal); use a link below")
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return argv
