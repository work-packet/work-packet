"""Setting a project up: the checks behind ``wpk doctor`` and ``wpk setup``,
and the helpers their fixes call (docs/setup.md).

You set a project up at its root (``prompt.md``, ``state/``, ``identity/``,
``work/``); the root packet is filled from there when a step starts
(``workspace.py``, docs/setup.md §10). Every front end (the CLI, the
wizard, the board) reads the same list of ``Check``s from ``readiness``;
none of them knows a setup rule of its own. A fix is a command line a
person can paste: helpers are ``wpk ...`` commands, so ``run_fix`` can run
exactly what was shown.

Git is used only for entries that are git repositories.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from string import Template
from typing import List

from . import clock, frontmatter, fsutil, layout, lease as lease_mod, registry, schema, workspace
from .packet import Packet
from .project import ProjectError, change_settings, held_for_setup, load_project, \
    project_of, settings

__all__ = ["held_for_setup"]

GROUPS = ("tools", "project", "work", "inputs", "instruction", "limits")
LEVELS = ("ok", "info", "warn", "missing")
SETUP_DIR = ".setup"          # <project>/.setup: smoke worktrees and logs, shell history
TEMPLATES = ("list", "outline", "plan-only")
TIMEOUT_MARGIN = 1.5          # step_timeout >= this x the smoke run's time


class SetupError(Exception):
    pass


@dataclass
class Check:
    id: str
    group: str
    level: str
    title: str
    detail: str = ""
    fix: List[str] = field(default_factory=list)
    safe: bool = False        # --fix and the wizard's "Do it" may run it unasked

    def to_json(self):
        return asdict(self)


@dataclass
class Target:
    """A project, resolved from a name, a directory or a packet in it."""
    name: str
    proj: str
    toml: dict
    packet: Packet

    @property
    def work(self):
        """The project's ``work/``: yours. The root packet references it."""
        return os.path.join(self.proj, "work")

    @property
    def packet_work(self):
        return os.path.join(self.packet.path, "work")

    @property
    def identity(self):
        return os.path.join(self.proj, "identity")

    @property
    def prompt_path(self):
        return os.path.join(self.proj, "prompt.md")

    @property
    def setup_dir(self):
        return os.path.join(self.proj, SETUP_DIR)

    @property
    def spec(self):
        return self.toml.get("setup") or {}

    @property
    def branch(self):
        return workspace.branch_for(self.name)

    def status(self):
        try:
            return self.packet.load_status()[0]
        except (OSError, frontmatter.FrontMatterError):
            return None

    def started(self):
        """The root packet has been filled from the root (or ran before that existed):
        inputs and the instruction now live in the packet."""
        meta = self.status() or {}
        return meta.get("step", 0) > 0 or workspace.seeded(self.packet)

    @property
    def state(self):
        """Where inputs go now: the root's ``state/`` until the first step, then the
        packet's."""
        return self.packet.state_dir if self.started() else os.path.join(self.proj, "state")

    def entries(self):
        """The names in the project's ``work/``."""
        try:
            return sorted(n for n in os.listdir(self.work) if not n.startswith("."))
        except OSError:
            return []

    def repos(self):
        """The git repositories in the project's ``work/``."""
        return [n for n in self.entries() if workspace.is_git(os.path.join(self.work, n))]

    def legacy(self):
        """Clones made inside the packet before the root held ``work/``."""
        try:
            names = sorted(os.listdir(self.packet_work))
        except OSError:
            return []
        root = set(self.entries())
        return [n for n in names if n not in root
                and not os.path.islink(os.path.join(self.packet_work, n))
                and workspace.is_git(os.path.join(self.packet_work, n))]

    def reload(self):
        self.toml = load_project(self.proj)
        return self


def target(t):
    """A ``Target`` from a registered name, a project directory, or a packet."""
    e = registry.get(t)
    if e is not None:
        proj = e["path"]
    elif os.path.isfile(os.path.join(t, "project.toml")):
        proj = os.path.abspath(t)
    else:
        try:
            proj = project_of(registry.resolve(t))
        except registry.LookupFailed as ex:
            raise SetupError(str(ex)) from None
        if proj is None:
            raise SetupError("%s is not in a project" % t)
    try:
        d = load_project(proj)
    except ProjectError as ex:
        raise SetupError(str(ex)) from None
    return Target(d["name"], proj, d, Packet(layout.run_dir(proj, d["root"])))


# --- quoting: commands people can paste ---------------------------------------------

def tilde(path):
    """``path`` for display and for pasting: ``~/x`` under the home directory, quoted."""
    path = os.path.abspath(path)
    h = os.path.expanduser("~")
    if path == h:
        return "~"
    if path.startswith(h + os.sep):
        return "~/" + shlex.quote(path[len(h) + 1:])
    return shlex.quote(path)


def _git(repo, *args, check=False):
    r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)
    if check and r.returncode:
        raise SetupError("git %s: %s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r


def _head(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _busy(tg):
    """The lease, if a step is running in the root right now."""
    old = lease_mod.read(tg.packet.lease_path)
    if old is not None and not lease_mod.is_stale(old):
        return old
    return None


def _not_busy(tg):
    if _busy(tg):
        raise SetupError("a step is running in %s; set up when it ends" % tg.name)


# --- the checks -----------------------------------------------------------------

def _tools(need_git=False):
    out = []
    exe = shlex.split(os.environ.get("WPK_CLAUDE") or "claude")
    if shutil.which(exe[0]) is None:
        out.append(Check("tools.claude", "tools", "missing", "%s is not on PATH" % exe[0],
                         "Steps run Claude Code (claude -p).",
                         ["npm install -g @anthropic-ai/claude-code"]))
    else:
        try:
            r = subprocess.run(exe + ["--version"], capture_output=True, text=True, timeout=20)
            ver = (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, IndexError):
            ver = None
        if ver is None:
            out.append(Check("tools.claude", "tools", "warn", "%s --version failed" % exe[0],
                             "Check that `%s -p hello` works in a shell." % exe[0]))
        else:
            out.append(Check("tools.claude", "tools", "ok", "claude %s" % ver))
    if need_git and shutil.which("git") is None:
        out.append(Check("tools.git", "tools", "missing", "git is not on PATH",
                         "work/ holds git repositories; steps get a git worktree of each."))
    out.extend(_ide_tools())
    return out


def _ide_tools():
    """Web VS Code needs the VS Code CLI (docs/vscode-plan.md §4.2); only when it is on."""
    from . import ide
    try:
        cfg = ide.load_config()
    except registry.ConfigError:
        return []
    if not cfg.get("web"):
        return []
    from .dash.ide import command
    code = command(cfg)
    if shutil.which(code) is None:
        if cfg.get("backend") == "openvscode-server":
            how, url = "openvscode-server (the open-source build)", \
                "https://github.com/gitpod-io/openvscode-server/releases"
        else:
            how, url = "`code serve-web`", "https://code.visualstudio.com/download"
        return [Check("tools.code", "tools", "warn", "%s is not on PATH" % code,
                      "[ide] web = true serves VS Code under the board's /ide/ with "
                      "%s; the board hides the button without it." % how, [url])]
    return [Check("tools.code", "tools", "ok", "%s (web VS Code)" % code)]


def _project(tg, meta):
    from .check import check_project
    out = []
    e = registry.get(tg.name)
    if e is None or os.path.abspath(e["path"]) != tg.proj:
        out.append(Check("project.registered", "project", "missing",
                         "%s is not registered" % tg.name,
                         "The runner and the board only see registered projects.",
                         ["wpk adopt %s" % tilde(tg.proj)]))
    rep = check_project(tg.proj)
    for i, iss in enumerate(rep.errors[:5]):
        loc = os.path.relpath(iss.path, tg.proj) + (": %s" % iss.field if iss.field else "")
        out.append(Check("project.format.%d" % i, "project", "missing",
                         "%s: %s" % (loc, iss.msg), "From `wpk check`."))
    if not rep.errors:
        out.append(Check("project.format", "project", "ok", "project.toml and packets valid"))
    if meta is None:
        return out
    st = meta.get("state")
    if held_for_setup(meta):
        out.append(Check("project.held", "project", "ok", "root is held for setup"))
    elif st in ("RUNNABLE", "SLEEPING") and meta.get("step") == 0:
        out.append(Check("project.held", "project", "warn",
                         "root is %s and has not run: a tick would start it now" % st,
                         "Hold it while you set it up.", ["wpk pause %s" % tg.name]))
    elif meta.get("step", 0) > 0:
        out.append(Check("project.held", "project", "info",
                         "root is %s after %d steps" % (st, meta["step"])))
    return out


def _status(repo):
    """(untracked top-level links, other changed paths) in ``repo``."""
    links, dirty = [], []
    for ln in _git(repo, "status", "--porcelain").stdout.splitlines():
        path = ln[3:].strip().strip('"').rstrip("/")
        if ln.startswith("??") and "/" not in path and os.path.islink(os.path.join(repo, path)):
            links.append(path)
        else:
            dirty.append(path)
    return links, dirty


def _few(paths):
    return ", ".join(paths[:3]) + (", ..." if len(paths) > 3 else "")


def _clone_checks(tg, name, want):
    """Your clone in the project's ``work/``."""
    out = []
    r = os.path.join(tg.work, name)
    q = tilde(r)
    branch = (want or {}).get("branch") or tg.branch
    br = _git(r, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if br == branch:
        other = next((b for b in ("main", "master") if _git(
            r, "rev-parse", "--verify", "--quiet", "refs/heads/" + b).returncode == 0), None)
        out.append(Check("work.%s.branch" % name, "work", "missing",
                         "%s is on %s, the steps' branch" % (name, branch),
                         "Steps work in a git worktree on %s, which git allows only if no "
                         "other checkout has it. Switch your clone to another branch." % branch,
                         ["git -C %s switch %s" % (q, other or "-")]))
    else:
        out.append(Check("work.%s.branch" % name, "work", "ok",
                         "%s: your clone, on %s; steps work on %s" % (
                             name, br or "a detached HEAD", branch)))
    links, dirty = _status(r)
    if dirty and not tg.started():
        out.append(Check("work.%s.clean" % name, "work", "warn",
                         "%s has uncommitted changes (%s)" % (name, _few(dirty)),
                         "The steps' worktree starts from HEAD, without them. Commit what "
                         "the steps should see.",
                         ["cd %s && git add -A && git commit -m 'Setup'" % q]))
    if links:
        out.append(Check("work.%s.share" % name, "work", "info",
                         "%s/%s: linked into the steps' worktree, and excluded from git"
                         % (name, ", ".join(links))))
    for s in (want or {}).get("share", []):
        if not os.path.lexists(os.path.join(r, s)):
            src = os.path.join(os.path.expanduser(want["from"]), s)
            out.append(Check("work.%s.share.%s" % (name, s), "work", "missing",
                             "%s/%s is not linked" % (name, s),
                             "[setup] shares it from %s." % tilde(src),
                             ["ln -s %s %s" % (tilde(src), tilde(os.path.join(r, s)))]))
    tree = os.path.join(tg.packet_work, name)
    if os.path.lexists(tree):
        out.append(Check("work.%s.tree" % name, "work", "ok",
                         "%s: the root packet's worktree is at %s" % (
                             name, os.path.relpath(tree, tg.proj))))
    if os.path.isfile(os.path.join(r, ".envrc")):
        out.append(Check("work.%s.envrc" % name, "work", "info",
                         "%s has an .envrc: steps do not load it" % name,
                         "step_env is not built yet (long-running.md §2). Name the tools "
                         "by path in the instruction, or put them on PATH."))
    return out


def _legacy_checks(tg, name):
    """A clone made inside the packet (before work/ moved to the root)."""
    out = []
    r = os.path.join(tg.packet_work, name)
    q = tilde(r)
    br = _git(r, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if not br:
        out.append(Check("work.%s.branch" % name, "work", "missing",
                         "%s is on a detached HEAD" % name,
                         "Steps commit on a branch, so main stays as it is until you merge.",
                         ["git -C %s switch -c %s" % (q, tg.branch)]))
    else:
        out.append(Check("work.%s.branch" % name, "work",
                         "ok" if br.startswith("wpk/") else "warn",
                         "%s (in the packet) on %s" % (name, br)))
    links, dirty = _status(r)
    for s in links:
        out.append(Check("work.%s.share.%s" % (name, s), "work", "missing",
                         "%s/%s is an untracked link" % (name, s),
                         "The model's `git add` would commit it. Exclude it in this clone only.",
                         ["echo %s >> %s" % (shlex.quote(s),
                                             tilde(os.path.join(r, ".git", "info", "exclude")))],
                         safe=True))
    if dirty:
        out.append(Check("work.%s.clean" % name, "work", "missing",
                         "%s has uncommitted changes (%s)" % (name, _few(dirty)),
                         "Steps work on top of them, so their changes and the steps' mix. "
                         "Commit them, or ignore build output.",
                         ["cd %s && git add -A && git commit -m 'Setup'" % q]))
    return out


def _work(tg):
    if layout.is_packet_layout(tg.proj):
        folder = layout.packet_folder(tg.proj)
        return [Check("work.packet", "work", "ok",
                      "steps work in %s%s" % (tilde(folder), " (a git clone)"
                                              if workspace.is_git(folder) else ""),
                      "The packet folder is the work: put what the task needs in it.")]
    out = []
    names = tg.entries()
    want = {r["name"]: r for r in tg.spec.get("repo", [])}
    for n, r in want.items():
        if n not in names:
            out.append(Check("work.%s.cloned" % n, "work", "missing",
                             "%s is not cloned" % n, "[setup] lists it.",
                             clone_commands(tg, r), safe=True))
    legacy = tg.legacy()
    if not names and not want and not legacy:
        out.append(Check("work.none", "work", "warn", "nothing in work/",
                         "Put what the task works on in %s: a git clone, or any directory. "
                         "Steps get a git worktree of each clone." % tilde(tg.work),
                         ["git clone <path-or-url> %s" % tilde(os.path.join(tg.work, "<name>"))]))
    for n in names:
        p = os.path.join(tg.work, n)
        if workspace.is_git(p):
            out += _clone_checks(tg, n, want.get(n))
        else:
            out.append(Check("work.%s.plain" % n, "work", "warn",
                             "%s is not git: steps change it in place" % n,
                             "A failed step's changes to it are not rolled back."))
    for n in legacy:
        out += _legacy_checks(tg, n)
    return out


def _inputs(tg):
    from .prompt import FILE_MAX
    out = []
    state = tg.state
    where = "the root packet's state/" if tg.started() else \
        "state/ (copied into the root packet at the first step)"
    for i in tg.spec.get("input", []):
        src = os.path.expanduser(i["from"])
        name = i.get("to") or os.path.basename(src)
        if not os.path.exists(os.path.join(state, name)):
            out.append(Check("inputs.%s" % name, "inputs", "missing",
                             "state/%s is missing" % name,
                             "[setup] copies it from %s." % tilde(src),
                             ["wpk add-input %s %s" % (tg.name, tilde(src))], safe=True))
    files, big = [], []
    for dp, dns, fns in os.walk(state):
        dns[:] = sorted(d for d in dns if d != "archive")
        for f in sorted(fns):
            p = os.path.join(dp, f)
            rel = "state/" + os.path.relpath(p, state).replace(os.sep, "/")
            files.append(rel)
            if os.path.getsize(p) > FILE_MAX:
                big.append("%s (%.1f KB)" % (rel, os.path.getsize(p) / 1024.0))
    if files:
        out.append(Check("inputs.state", "inputs", "ok" if not big else "info",
                         "%s: %d file%s%s" % (
                             where, len(files), "" if len(files) == 1 else "s",
                             ", %d over 4 KB (listed by size in the prompt, not shown)"
                             % len(big) if big else ""),
                         "; ".join(big) if big else ", ".join(files)))
    links = {}
    for d in (tg.identity, tg.packet.identity_dir):
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if n in links:
                continue
            p = links[n] = os.path.join(d, n)
            if not os.path.exists(p):
                out.append(Check("inputs.identity.%s" % n, "inputs", "missing",
                                 "identity/%s is a dangling link" % n,
                                 "-> %s" % (os.readlink(p) if os.path.islink(p) else "?"),
                                 ["rm %s" % tilde(p)]))
            else:
                out.append(Check("inputs.identity.%s" % n, "inputs", "ok",
                                 "identity/%s -> %s (read-only)" % (
                                     n, tilde(os.path.realpath(p)))))
    for ln in tg.spec.get("link", []):
        src = os.path.expanduser(ln["from"])
        n = ln.get("name") or os.path.basename(src.rstrip("/"))
        if n not in links:
            out.append(Check("inputs.identity.%s" % n, "inputs", "missing",
                             "identity/%s is not linked" % n, "[setup] lists it.",
                             link_commands(tg, ln), safe=True))
    return out


def instruction(tg):
    """(the first instruction as it stands, where it is)."""
    try:
        _, body = tg.packet.load_memento()
    except FileNotFoundError:
        body = ""
    if body.strip() or tg.started():
        return body, "memento.md"
    try:
        return fsutil.read_text(tg.prompt_path), "prompt.md"
    except OSError:
        return "", "prompt.md"


def _instruction(tg):
    try:
        body, where = instruction(tg)
    except frontmatter.FrontMatterError as e:
        return [Check("instruction.body", "instruction", "missing", "memento.md: %s" % e)]
    if not body.strip():
        return [Check("instruction.body", "instruction", "missing", "no instruction yet",
                      "It is what the first step is told to do (prompt.md, which becomes "
                      "the root packet's memento.md).",
                      ["wpk instruct %s --template outline" % tg.name])]
    out = [Check("instruction.body", "instruction", "ok",
                 "%s: %s" % (where, body.strip().splitlines()[0][:70]))]
    names = tg.entries() + tg.legacy()
    if names and "work/" not in body:
        out.append(Check("instruction.repo", "instruction", "warn",
                         "the instruction does not name work/%s" % names[0],
                         "Say which repo to work in, and on which branch.",
                         ["wpk instruct %s" % tg.name]))
    for m in sorted(set(m.rstrip(".") for m in re.findall(r"work/([A-Za-z0-9._-]+)", body))):
        if m not in names:
            out.append(Check("instruction.repo.%s" % m, "instruction", "warn",
                             "the instruction names work/%s, which is not in work/" % m,
                             "", ["wpk instruct %s" % tg.name]))
    return out


def smoke_results(tg):
    try:
        with open(os.path.join(tg.setup_dir, "smoke.json")) as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return None


def _heads(tg):
    return {n: _head(os.path.join(tg.work, n)) for n in tg.repos()}


def _limits(tg):
    out = []
    try:
        st = settings(tg.proj)
    except ProjectError as e:
        return [Check("limits.settings", "limits", "missing", str(e))]
    shown = []
    for k, v in (("step_timeout", "%dm" % (st.step_timeout_s // 60)),
                 ("step_budget_usd", "%.2f" % st.step_budget_usd),
                 ("step_context_tokens", str(st.step_context_tokens)),
                 ("model", st.model)):
        shown.append("%s %s%s" % (k, v, "" if k in tg.toml else " (default)"))
    out.append(Check("limits.values", "limits", "info", ", ".join(shown),
                     "Change one with `wpk set %s key=value`." % tg.name))
    smoke = tg.spec.get("smoke", [])
    res = smoke_results(tg)
    names = tg.entries()
    if not smoke:
        if names:
            out.append(Check("limits.smoke", "limits", "warn", "no smoke commands",
                             "A build or test command that doctor --run can check, and "
                             "time, before the hand-off.",
                             ["wpk add-smoke %s --repo %s '<build or test command>'"
                              % (tg.name, names[0])]))
    elif res is None or res.get("commands") != [s["run"] for s in smoke]:
        out.append(Check("limits.smoke", "limits", "warn", "smoke commands not run yet",
                         "A packet that cannot build spends its steps on setup.",
                         ["wpk doctor %s --run" % tg.name]))
    elif not res.get("ok"):
        bad = next((r for r in res["runs"] if r["code"] != 0), res["runs"][-1])
        out.append(Check("limits.smoke", "limits", "missing",
                         "smoke failed: %s (exit %s)" % (bad["run"], bad["code"]),
                         "Fix it by hand first; see %s." % tilde(bad["log"]),
                         ["tail -30 %s" % tilde(bad["log"]), "wpk doctor %s --run" % tg.name]))
    else:
        heads = _heads(tg)
        stale = [n for n, h in res.get("heads", {}).items() if heads.get(n) != h]
        secs = sum(r["seconds"] for r in res["runs"])
        if stale:
            out.append(Check("limits.smoke", "limits", "warn",
                             "smoke passed, but %s has changed since" % ", ".join(stale), "",
                             ["wpk doctor %s --run" % tg.name]))
        else:
            out.append(Check("limits.smoke", "limits", "ok",
                             "smoke passed in %s" % _dur(secs)))
        need = int(secs * TIMEOUT_MARGIN)
        if need > st.step_timeout_s:
            mins = -(-need // 60)
            out.append(Check("limits.timeout", "limits", "warn",
                             "step_timeout %dm is short: the smoke commands take %s" % (
                                 st.step_timeout_s // 60, _dur(secs)),
                             "A step that builds and tests needs at least %.1fx that."
                             % TIMEOUT_MARGIN,
                             ["wpk set %s step_timeout=%dm" % (tg.name, mins)], safe=True))
    tools = st.allowed_tools
    if "Bash" in tools:
        out.append(Check("limits.bash", "limits", "info", "Bash is unrestricted",
                         "Steps can run anything your user can. The instruction should "
                         "forbid push and network use; or list patterns instead, such as "
                         "'Bash(git commit *)'."))
    elif (names or tg.legacy()) and not any(t.startswith("Bash") for t in tools):
        out.append(Check("limits.bash", "limits", "warn", "steps have no Bash",
                         "They cannot build, test or commit in work/.",
                         ["wpk allow %s Bash" % tg.name]))
    out.append(Check("limits.tools", "limits", "info", "tools: %s (%s)" % (
        ", ".join(tools), st.permission_mode)))
    return out


def _dur(s):
    s = int(round(s))
    return "%dm%02ds" % (s // 60, s % 60) if s >= 60 else "%ds" % s


def readiness(tg, tools=True):
    """Every check for ``tg``, in group order."""
    try:
        tg.reload()
    except ProjectError as e:
        return [Check("project.toml", "project", "missing", str(e))]
    meta = tg.status()
    out = _tools(need_git=bool(tg.repos() or tg.legacy())) if tools else []
    out += _project(tg, meta) + _work(tg) + _inputs(tg) + _instruction(tg) + _limits(tg)
    return out


def missing(checks):
    return [c for c in checks if c.level == "missing"]


def next_step(tg, checks):
    """The one thing to do next: the first fix of the first missing (or warned) check,
    else the hand-off."""
    for lvl in ("missing", "warn"):
        for c in checks:
            if c.level == lvl and c.fix and "<" not in c.fix[0]:
                return c.fix[0]
        if lvl == "missing" and missing(checks):
            return missing(checks)[0].title
    meta = tg.status() or {}
    if meta.get("state") in ("PAUSED", "NEEDS_INPUT", "FAILED"):
        return "wpk handoff %s -m \"Set up; start\"" % tg.name
    return "wpk show %s" % tg.name


def run_fix(cmd, cwd=None):
    """Run a fix as shown. ``wpk`` means this interpreter's work_packet."""
    if cmd.startswith("wpk "):
        cmd = "%s -m work_packet %s" % (shlex.quote(sys.executable), cmd[4:])
    return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)


# --- [setup] in project.toml ------------------------------------------------------

def _record(tg, kind, entry, key):
    """Add ``entry`` to ``[[setup.<kind>]]`` unless one with the same ``key`` is there."""
    def change(d):
        lst = d.setdefault("setup", {}).setdefault(kind, [])
        for e in lst:
            if e.get(key) == entry.get(key):
                return []
        lst.append(entry)
        return ["setup.%s += %s" % (kind, entry.get(key))]
    try:
        out = change_settings(tg.proj, change, _who())
    except ProjectError as e:
        raise SetupError(str(e)) from None
    tg.reload()
    return out


def _who():
    from .executor import _who
    return _who()


def _home_rel(path):
    """``path`` as stored in [setup]: ``~/...`` when under the home directory."""
    path = os.path.abspath(os.path.expanduser(path))
    h = os.path.expanduser("~")
    return "~/" + path[len(h) + 1:] if path.startswith(h + os.sep) else path


# --- the helpers ---------------------------------------------------------------

def _src(src):
    """A ``[setup]`` ``from`` as a command argument: a path (``~/...``), or a URL."""
    p = os.path.expanduser(src)
    if os.path.isabs(p) or os.path.exists(p):
        return tilde(p)
    return shlex.quote(src)


def clone_commands(tg, r, dst=None):
    """The commands that make ``[[setup.repo]]`` entry ``r``: a ``git clone`` into the
    project's ``work/`` (or ``dst``), and a link for each shared directory."""
    dst = dst or os.path.join(tg.work, r["name"])
    cmds = ["git clone %s %s" % (_src(r["from"]), tilde(dst))]
    for sh in r.get("share", []):
        cmds.append("ln -s %s %s" % (tilde(os.path.join(os.path.expanduser(r["from"]), sh)),
                                     tilde(os.path.join(dst, sh))))
    return cmds


def packet_clone(copy=None, clone=None):
    """For a new packet (docs/run-binding-v1.md): its folder is the one clone
    steps work in, so ``[setup]`` repos are not cloned into ``work/``. Returns
    ``copy`` without them, and the repo to clone as the folder (``clone``, a
    path or URL, or the copied setup's one repo), or None."""
    copy = json.loads(json.dumps(copy or {}))
    s = copy.get("setup", {})
    repos = s.pop("repo", [])
    if not s:
        copy.pop("setup", None)
    if clone:
        return copy, {"name": "", "from": clone}
    if len(repos) > 1:
        raise SetupError("that setup clones %d repos (%s); a packet works in one clone: "
                         "give the one to clone" % (len(repos),
                                                    ", ".join(r["name"] for r in repos)))
    return copy, (repos[0] if repos else None)


def clone_packet(r, folder):
    """Clone repo ``r`` as the packet folder ``folder`` (absent or empty), with its
    shared links. Returns the commands run."""
    if os.path.lexists(folder) and not (os.path.isdir(folder) and not os.listdir(folder)):
        raise SetupError("%s exists: to work in it, leave the repo empty" % tilde(folder))
    out = []
    for cmd in clone_commands(None, r, dst=folder):
        res = run_fix(cmd)
        if res.returncode:
            raise SetupError("%s: %s" % (cmd, (res.stderr or res.stdout).strip()))
        out.append(cmd)
    return out


def repo_entries(proj):
    """``[[setup.repo]]`` entries read from a project's ``work/``: each git clone, its
    ``origin``, and the top-level links git does not track (shared directories)."""
    out = []
    work = os.path.join(proj, "work")
    try:
        names = sorted(n for n in os.listdir(work) if not n.startswith("."))
    except OSError:
        return out
    for n in names:
        p = os.path.join(work, n)
        if not workspace.is_git(p):
            continue
        origin = _git(p, "remote", "get-url", "origin").stdout.strip()
        if not origin:
            continue
        e = {"name": n, "from": _home_rel(origin) if os.path.isabs(origin) else origin}
        sh = workspace.shares(p)
        if sh:
            e["share"] = sh
        out.append(e)
    return out


def add_input(tg, files, record=True, force=False):
    """Copy files into ``state/``: the root's until the first step, then the packet's."""
    from .prompt import FILE_MAX
    started = tg.started()
    if started:
        _not_busy(tg)
    state = tg.state
    msgs = []
    for f in files:
        src = os.path.abspath(os.path.expanduser(f))
        if not os.path.isfile(src):
            raise SetupError("%s is not a file" % src)
        dst = os.path.join(state, os.path.basename(src))
        rel = "state/" + os.path.basename(src)
        if os.path.exists(dst):
            with open(src, "rb") as a, open(dst, "rb") as b:
                same = a.read() == b.read()
            if same:
                msgs.append("%s is already there" % rel)
            elif not force:
                raise SetupError("%s exists and differs; --force replaces it" % rel)
        if not os.path.exists(dst) or force:
            os.makedirs(state, exist_ok=True)
            shutil.copyfile(src, dst)
            size = os.path.getsize(dst)
            msgs.append("copied %s to %s%s%s" % (
                tilde(src), rel, " in the root packet" if started else "",
                " (%.1f KB: listed by size in the prompt, not shown)" % (size / 1024.0)
                if size > FILE_MAX else ""))
        if record:
            msgs += _record(tg, "input", {"from": _home_rel(src)}, "from")
    return msgs


def link_commands(tg, ln):
    """The commands that make ``[[setup.link]]`` entry ``ln``: a link in the project's
    ``identity/``."""
    src = os.path.expanduser(ln["from"])
    n = ln.get("name") or os.path.basename(src.rstrip("/"))
    return ["mkdir -p %s && ln -s %s %s" % (tilde(tg.identity), tilde(src),
                                           tilde(os.path.join(tg.identity, n)))]


def link_entries(proj):
    """``[[setup.link]]`` entries read from a project's ``identity/`` links."""
    out = []
    d = os.path.join(proj, "identity")
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        p = os.path.join(d, n)
        if not os.path.islink(p):
            continue
        t = workspace._link_target(p)
        e = {"from": _home_rel(t)}
        if n != os.path.basename(t.rstrip("/")):
            e["name"] = n
        out.append(e)
    return out


def add_smoke(tg, cmd, repo=None):
    if repo is None:
        names = tg.entries()
        if len(names) > 1:
            raise SetupError("several entries in work/; give --repo")
        repo = names[0] if names else None
    entry = {"run": cmd}
    if repo:
        entry["repo"] = repo
    return _record(tg, "smoke", entry, "run") or ["already listed: %s" % cmd]


def template_text(tg, name):
    from importlib import resources
    if name not in TEMPLATES:
        raise SetupError("no template %r; there are: %s" % (name, ", ".join(TEMPLATES)))
    raw = resources.files("work_packet").joinpath("prompts/instruct-%s.md" % name) \
        .read_text(encoding="utf-8")
    names = tg.entries() or tg.legacy()
    plans = []
    if os.path.isdir(tg.state):
        plans = ["state/" + f for f in sorted(os.listdir(tg.state))
                 if os.path.isfile(os.path.join(tg.state, f))]
    return Template(raw).safe_substitute(
        repo=names[0] if names else "<repo>", branch=tg.branch, project=tg.name,
        plan=plans[0] if plans else "state/<plan>.md")


def instruct(tg, text):
    """Set the first instruction: ``prompt.md`` at the root until the first step (it
    becomes the memento then), the root packet's memento body afterwards."""
    if not text.strip():
        raise SetupError("the instruction is empty")
    if not text.endswith("\n"):
        text += "\n"
    try:
        meta, body = tg.packet.load_memento()
    except FileNotFoundError:
        meta, body = None, ""
    except frontmatter.FrontMatterError as e:
        raise SetupError("memento.md: %s" % e) from None
    if not tg.started() and not body.strip():
        fsutil.atomic_write(tg.prompt_path, text)
        return ["wrote the instruction to %s (%d lines); the first step starts from it"
                % (tilde(tg.prompt_path), len(text.splitlines()))]
    _not_busy(tg)
    probs = [p for p in schema.validate_memento(meta, text, proposal=False)
             if p.level == "error"]
    if probs:
        raise SetupError("%s" % probs[0].msg)
    fsutil.atomic_write(tg.packet.memento_path, frontmatter.dump(meta or None, text))
    return ["wrote the instruction to the root packet's memento.md (%d lines)"
            % len(text.splitlines())]


def smoke_tree(tg, name):
    """Where smoke commands run for ``work/<name>``: a worktree of a clone, detached at
    its ``HEAD`` and kept between runs; a plain directory itself."""
    src = os.path.join(tg.work, name)
    if not workspace.is_git(src):
        return src
    tree = os.path.join(tg.setup_dir, "smoke", name)
    try:
        if not os.path.lexists(tree):
            os.makedirs(os.path.dirname(tree), exist_ok=True)
            workspace.add_worktree(src, tree, detach=True)
        else:
            workspace._git(tree, "checkout", "--quiet", "--detach", _head(src))
        listed = {r.get("name"): r.get("share", []) for r in tg.spec.get("repo", [])}
        workspace.link_shares(src, tree, workspace.shares(src, listed.get(name, ())))
    except workspace.WorkspaceError as e:
        raise SetupError(str(e)) from None
    return tree


def run_smoke(tg, echo=None):
    """Run every ``[[setup.smoke]]`` command, output to ``.setup/smoke-N.log``.

    A command for a clone runs in a worktree of it (``smoke_tree``), so it
    builds from scratch, as the first step will. Stops at the first failure.
    Writes ``.setup/smoke.json``. ``echo(msg)`` reports progress.
    """
    smoke = tg.spec.get("smoke", [])
    if not smoke:
        raise SetupError("no smoke commands; add one with `wpk add-smoke %s CMD`" % tg.name)
    os.makedirs(tg.setup_dir, exist_ok=True)
    limit = schema.parse_duration(tg.spec.get("smoke_timeout", "60m"))
    runs, ok = [], True
    for i, s in enumerate(smoke, 1):
        cwd = smoke_tree(tg, s["repo"]) if s.get("repo") else tg.proj
        log = os.path.join(tg.setup_dir, "smoke-%d.log" % i)
        if echo:
            echo("[%d/%d] %s (in %s)" % (i, len(smoke), s["run"], tilde(cwd)))
        t0 = time.monotonic()
        with open(log, "w") as fp:
            try:
                code = subprocess.run(s["run"], shell=True, cwd=cwd, stdout=fp,
                                      stderr=subprocess.STDOUT, timeout=limit).returncode
            except subprocess.TimeoutExpired:
                code = "timeout"
        secs = time.monotonic() - t0
        runs.append({"run": s["run"], "repo": s.get("repo"), "cwd": cwd, "code": code,
                     "seconds": round(secs, 1), "log": log})
        if echo:
            echo("      %s in %s" % ("ok" if code == 0 else "FAILED (%s)" % code, _dur(secs)))
        if code != 0:
            ok = False
            break
    res = {"t": schema.format_timestamp(clock.now()), "ok": ok,
           "commands": [s["run"] for s in smoke], "runs": runs, "heads": _heads(tg)}
    fsutil.atomic_write(os.path.join(tg.setup_dir, "smoke.json"), json.dumps(res, indent=1))
    return res


def apply(tg, echo=None):
    """Do what ``[setup]`` asks that is not done yet: clones, inputs, links."""
    msgs = []
    have = tg.entries()
    # A packet works in its folder: its [setup] repos are not cloned (packet_clone).
    for r in [] if layout.is_packet_layout(tg.proj) else tg.spec.get("repo", []):
        if r["name"] not in have:
            for cmd in clone_commands(tg, r):
                res = run_fix(cmd)
                if res.returncode:
                    raise SetupError("%s: %s" % (cmd, (res.stderr or res.stdout).strip()))
                msgs.append(cmd)
    for i in tg.spec.get("input", []):
        src = os.path.expanduser(i["from"])
        if not os.path.exists(os.path.join(tg.state, os.path.basename(src))):
            msgs += add_input(tg, [src], record=False)
    for ln in tg.spec.get("link", []):
        src = os.path.expanduser(ln["from"])
        n = ln.get("name") or os.path.basename(src.rstrip("/"))
        if not os.path.lexists(os.path.join(tg.identity, n)):
            for cmd in link_commands(tg, ln):
                res = run_fix(cmd)
                if res.returncode:
                    raise SetupError("%s: %s" % (cmd, (res.stderr or res.stdout).strip()))
                msgs.append(cmd)
    return msgs or ["nothing to do"]


def copy_setup(src_toml, name, src_proj=None):
    """The parts of another project's ``project.toml`` that ``new --from-setup`` copies:
    ``[setup]`` (branches renamed for the new project), ``[permissions]`` and limits.
    Clones in ``src_proj``'s ``work/`` and links in its ``identity/`` that
    ``[setup]`` does not list are added (``repo_entries``, ``link_entries``)."""
    from .project import LIMITS
    old = src_toml.get("name")
    out = {}
    for k in ("model", "harness", "profile", "tz") + LIMITS:
        if k in src_toml:
            out[k] = src_toml[k]
    if "permissions" in src_toml:
        out["permissions"] = json.loads(json.dumps(src_toml["permissions"]))
    if "setup" in src_toml:
        s = json.loads(json.dumps(src_toml["setup"]))
        for r in s.get("repo", []):
            if r.get("branch") == "wpk/%s" % old:
                del r["branch"]
        out["setup"] = s
    if src_proj:
        s = out.setdefault("setup", {})
        have = {r["name"] for r in s.get("repo", [])}
        s.setdefault("repo", []).extend(r for r in repo_entries(src_proj)
                                        if r["name"] not in have)
        have = {ln["from"] for ln in s.get("link", [])}
        s.setdefault("link", []).extend(ln for ln in link_entries(src_proj)
                                        if ln["from"] not in have)
        for k in ("repo", "link"):
            if not s[k]:
                del s[k]
        if not s:
            del out["setup"]
    return out


# --- a shell at the project root ---------------------------------------------------

def shell_env(tg, extra=None):
    env = dict(os.environ, WPK_PROJECT=tg.name, WPK_PROJECT_DIR=tg.proj,
               WPK_WPID=tg.packet.wpid, WPK_PACKET=tg.packet.path, WPK_WORK=tg.work)
    env.update(extra or {})
    return env


def shell_dir(tg, repo=None):
    """``work/<repo>`` at the project root, or the root itself."""
    if repo:
        return os.path.join(tg.work, repo)
    return tg.proj


def shell_argv(tg, prompt_hook=None):
    """``$SHELL``, with a ``[wpk:<name>]`` prompt prefix for bash.

    ``prompt_hook`` is a shell command run before each prompt (the wizard
    uses it to recheck after every command).
    """
    sh = os.environ.get("SHELL") or "/bin/sh"
    if os.path.basename(sh) != "bash":
        return [sh]
    os.makedirs(tg.setup_dir, exist_ok=True)
    rc = os.path.join(tg.setup_dir, "bashrc")
    lines = ["[ -f ~/.bashrc ] && . ~/.bashrc",
             'PS1="[wpk:%s] $PS1"' % tg.name,
             'HISTFILE=%s' % shlex.quote(os.path.join(tg.setup_dir, "history")),
             "shopt -s histappend",
             "PROMPT_COMMAND=\"history -a${PROMPT_COMMAND:+; $PROMPT_COMMAND}\""]
    if prompt_hook:
        lines.append('PROMPT_COMMAND="$PROMPT_COMMAND; %s"' % prompt_hook.replace('"', '\\"'))
    fsutil.atomic_write(rc, "\n".join(lines) + "\n")
    return [sh, "--rcfile", rc, "-i"]
