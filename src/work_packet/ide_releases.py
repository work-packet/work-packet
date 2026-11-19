"""The VS Code server releases the board runs (docs/ide-direct-server-plan.md §3).

wpkd runs a desk's server straight from a release kept here, not through
``code serve-web``: serve-web updates itself whenever it likes and then
refuses the release a running desk was started on. Here a release changes
only when wpk installs one, and a desk keeps the one it started with.

Everything is under ``$WPK_HOME/ide/releases/<platform>/``:

``<commit>/``
    One release: VS Code's ``vscode-server-<platform>-web`` archive, unpacked
    (``bin/code-server``, ``product.json``, ...).
``<commit>.staging/``
    A download being unpacked; renamed to ``<commit>/`` once it checks out, so
    a half-finished one is never run.
``state.json``
    The last check: ``{"t", "latest", "version", "error"}``.

Stdlib only: ``sched/ide_job.py`` imports it on the exec host.
"""

import json
import os
import platform as _platform
import shutil
import tarfile
import threading
import time
import urllib.request

UPDATE = "https://update.code.visualstudio.com"
QUALITY = "stable"
SERVE_WEB_CACHE = os.path.expanduser("~/.vscode/cli/serve-web")
STAGING = ".staging"
STATE = "state.json"
KEEP_OLD = 1                # releases kept past the current one and those desks run
TIMEOUT_S = 30

# os.uname() machine -> the update service's platform name
MACHINES = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64",
            "armv7l": "armhf", "armv8l": "armhf"}


class ReleaseError(Exception):
    pass


def platform(system=None, machine=None):
    """This host's platform, as the update service names it: ``linux-x64``..."""
    system = (system or _platform.system()).lower()
    machine = (machine or _platform.machine()).lower()
    arch = MACHINES.get(machine)
    if system not in ("linux", "darwin") or arch is None:
        raise ReleaseError("VS Code's server has no build for %s/%s" % (system, machine))
    return "%s-%s" % (system, arch)


def _artifact(plat):
    # darwin x64 is plain "server-darwin-web"; every other platform names its arch
    return "server-darwin-web" if plat == "darwin-x64" else "server-%s-web" % plat


def root(home, plat=None):
    return os.path.join(home, "ide", "releases", plat or platform())


def path(home, commit, plat=None):
    return os.path.join(root(home, plat), commit)


def binary(home, commit, plat=None):
    return os.path.join(path(home, commit, plat), "bin", "code-server")


def info(d):
    """``{commit, version, date}`` of the release unpacked at ``d``, or None."""
    try:
        with open(os.path.join(d, "product.json")) as fp:
            p = json.load(fp)
    except (OSError, ValueError):
        return None
    if not (p.get("commit") and os.path.exists(os.path.join(d, "bin", "code-server"))):
        return None
    return {"commit": p["commit"], "version": p.get("version") or "", "date": p.get("date") or ""}


def vkey(version):
    """``"1.147.0"`` -> ``(1, 147, 0)``, for ordering."""
    out = []
    for part in (version or "").split("."):
        num = "".join(c for c in part if c.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def _order(r):
    return (vkey(r["version"]), r["date"])


def installed(home, plat=None):
    """The releases here, newest first."""
    d = root(home, plat)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = []
    for n in names:
        if n.endswith(STAGING) or not os.path.isdir(os.path.join(d, n)):
            continue
        r = info(os.path.join(d, n))
        if r is not None and r["commit"] == n:
            out.append(r)
    return sorted(out, key=_order, reverse=True)


def find(home, commit, plat=None):
    for r in installed(home, plat):
        if r["commit"] == commit:
            return r
    return None


def current(home, cfg, plat=None):
    """The release a desk starting now gets: ``[ide] release`` when it is
    installed, else the newest here. None when there is none."""
    rels = installed(home, plat)
    hold = (cfg or {}).get("release") or ""
    if hold:
        for r in rels:
            if r["commit"].startswith(hold) or r["version"] == hold:
                return r
        return None
    return rels[0] if rels else None


# -- getting releases ---------------------------------------------------------

def _get_json(url):
    req = urllib.request.Request(url, headers={"user-agent": "wpk"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.load(r)


def latest(plat=None, get_json=_get_json):
    """The newest release VS Code publishes: ``{commit, version}``."""
    d = get_json("%s/api/latest/%s/%s" % (UPDATE, _artifact(plat or platform()), QUALITY))
    if not isinstance(d, dict) or not d.get("version"):
        raise ReleaseError("VS Code's update service said %r" % (d,))
    return {"commit": d["version"], "version": d.get("productVersion") or d.get("name") or ""}


def _download(url, dest):
    req = urllib.request.Request(url, headers={"user-agent": "wpk"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r, open(dest, "wb") as fp:
        shutil.copyfileobj(r, fp, 1 << 20)


def _unpack(archive, dest):
    """The archive's one top directory (``vscode-server-<plat>-web/``) becomes ``dest``."""
    with tarfile.open(archive) as tf:
        members = []
        for m in tf.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            m.name = parts[1]
            if m.islnk():           # hard links name their target by the full path too
                m.linkname = m.linkname.split("/", 1)[-1]
            members.append(m)
        tf.extractall(dest, members=members, filter="tar")


def _staging(home, commit, plat):
    d = root(home, plat)
    os.makedirs(d, exist_ok=True)
    stage = os.path.join(d, commit + STAGING)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    return stage


def _commit(home, commit, plat, stage):
    r = info(stage)
    if r is None or r["commit"] != commit:
        shutil.rmtree(stage, ignore_errors=True)
        raise ReleaseError("the download of %s is not that VS Code server" % commit[:7])
    dest = path(home, commit, plat)
    if os.path.isdir(dest):            # another getter got there first
        shutil.rmtree(stage, ignore_errors=True)
    else:
        os.rename(stage, dest)
    return r


def install(home, commit, plat=None, download=_download):
    """Download and unpack ``commit``; its info. A no-op when it is here."""
    plat = plat or platform()
    have = find(home, commit, plat)
    if have is not None:
        return have
    stage = _staging(home, commit, plat)
    archive = os.path.join(stage, "server.tar.gz")
    url = "%s/commit:%s/%s/%s" % (UPDATE, commit, _artifact(plat), QUALITY)
    try:
        download(url, archive)
        _unpack(archive, stage)
        os.unlink(archive)
    except (OSError, tarfile.TarError, ValueError) as e:
        shutil.rmtree(stage, ignore_errors=True)
        raise ReleaseError("cannot get VS Code's server %s: %s" % (commit[:7], e)) from None
    return _commit(home, commit, plat, stage)


def _link_tree(src, dst):
    """Hard links where it can (a release is ~750 MB), copies where it can't."""
    def link(s, d):
        try:
            os.link(s, d)
        except OSError:
            shutil.copy2(s, d)
    shutil.copytree(src, dst, symlinks=True, copy_function=link, dirs_exist_ok=True)


def seed(home, plat=None, cache=SERVE_WEB_CACHE):
    """The newest release ``code serve-web`` downloaded, when it is newer than
    any here: no download on a machine that has been running serve-web. Its info,
    or None."""
    plat = plat or platform()
    if plat != platform():
        return None             # serve-web's cache holds this host's builds only
    try:
        names = os.listdir(cache)
    except OSError:
        return None
    found = [r for r in (info(os.path.join(cache, n)) for n in names
                         if not n.endswith(STAGING) and "." not in n) if r]
    if not found:
        return None
    best = max(found, key=_order)
    have = installed(home, plat)
    if have and _order(have[0]) >= _order(best):
        return None
    if find(home, best["commit"], plat) is not None:
        return None
    stage = _staging(home, best["commit"], plat)
    try:
        _link_tree(os.path.join(cache, best["commit"]), stage)
    except (OSError, shutil.Error) as e:
        shutil.rmtree(stage, ignore_errors=True)
        raise ReleaseError("cannot copy VS Code's server %s from serve-web: %s"
                           % (best["commit"][:7], e)) from None
    return _commit(home, best["commit"], plat, stage)


def gc(home, keep, plat=None):
    """Remove releases that are not in ``keep`` (commits), past the newest
    ``KEEP_OLD`` of the rest. Leftover staging directories go too. The removed
    commits."""
    plat = plat or platform()
    d = root(home, plat)
    gone = []
    spare = KEEP_OLD
    for r in installed(home, plat):
        if r["commit"] in keep:
            continue
        if spare > 0:
            spare -= 1
            continue
        shutil.rmtree(os.path.join(d, r["commit"]), ignore_errors=True)
        gone.append(r["commit"])
    if getting(plat):
        return gone             # its staging directory is in use
    try:
        names = os.listdir(d)
    except OSError:
        names = []
    for n in names:
        if n.endswith(STAGING):
            shutil.rmtree(os.path.join(d, n), ignore_errors=True)
    return gone


# -- the state of the last check ----------------------------------------------

def read_state(home, plat=None):
    try:
        with open(os.path.join(root(home, plat), STATE)) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(home, plat, **fields):
    d = root(home, plat)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, STATE + ".tmp")
    with open(tmp, "w") as fp:
        json.dump(dict(fields, t=time.time()), fp)
    os.replace(tmp, os.path.join(d, STATE))


def check(home, plat=None, get_json=_get_json, download=_download):
    """Get VS Code's newest release, when it is not here yet. Its info."""
    plat = plat or platform()
    try:
        rel = latest(plat, get_json)
    except (OSError, ValueError, ReleaseError) as e:
        _write_state(home, plat, error=str(e))
        raise ReleaseError("cannot ask VS Code's update service: %s" % e) from None
    try:
        r = install(home, rel["commit"], plat, download)
    except ReleaseError as e:
        _write_state(home, plat, latest=rel["commit"], version=rel["version"], error=str(e))
        raise
    _write_state(home, plat, latest=r["commit"], version=r["version"])
    return r


# -- getting one in the background --------------------------------------------

_lock = threading.Lock()
_getting = {}               # (commit or "latest", plat) -> the thread
_failed = {}                # plat -> (when, why) of the last failed background get


def getting(plat=None):
    """True while a background get for ``plat`` runs."""
    plat = plat or platform()
    with _lock:
        return any(p == plat and t.is_alive() for (_, p), t in _getting.items())


def last_failure(plat=None):
    with _lock:
        return _failed.get(plat or platform())


def start_get(home, plat=None, get_json=_get_json, download=_download):
    """Get the newest release on a thread, unless one is being got already."""
    plat = plat or platform()

    def run():
        try:
            check(home, plat, get_json, download)
            with _lock:
                _failed.pop(plat, None)
        except ReleaseError as e:
            with _lock:
                _failed[plat] = (time.time(), str(e))
        finally:
            with _lock:
                _getting.pop(("latest", plat), None)

    with _lock:
        t = _getting.get(("latest", plat))
        if t is not None and t.is_alive():
            return t
        t = threading.Thread(target=run, name="wpk-vscode-get", daemon=True)
        _getting[("latest", plat)] = t
    t.start()
    return t
