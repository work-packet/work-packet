"""Validation of every file format in docs/spec.md.

Each ``validate_*`` function takes parsed data and returns a list of
``Problem(field, msg, level)``. They never touch the filesystem; cross-file
consistency is in ``check.py``.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from . import clock

FORMAT_VERSION = "0.2"

STATES = ("RUNNABLE", "SLEEPING", "NEEDS_INPUT", "PAUSED", "COMPLETED", "FAILED")
RESERVED_STATES = {"WAITING": "Stage 3"}

STATUS_FIELDS = (
    "wpk", "wpid", "project", "state", "step", "attempts", "parent",
    "spawn_key", "children", "resume_expr", "wake_at", "model", "reason",
    "updated", "next_size",
)
STATUS_OPTIONAL = ("next_size",)      # docs/scheduler-plan.md decision 4

MEMENTO_FIELDS = ("resume", "reason", "ask", "spawn", "item", "size")
ITEM_MAX = 80
MEMENTO_LATER = {"every": "Stage 2", "wait": "Stage 3"}
SPAWN_FIELDS = ("name", "instruction", "copy", "model")

PERMISSION_MODES = ("acceptEdits", "auto", "bypassPermissions", "dontAsk",
                    "manual", "plan")

CONFIG_DEFAULTS = {
    "model": "claude-opus-5-5",
    "harness": "claude",              # harness.md §3
    "max_concurrent": 1,
    "step_timeout": "120m",
    "max_attempts": 3,
    "step_budget_usd": 1.00,
    "step_context_tokens": 80000,     # context.md C3; 0 = off
    "carry_session": False,           # context.md C4
    "carry_ttl": "55m",
    "carry_factor": 4.0,              # C4: fresh again at this multiple of O
    "budget_usd_per_day": 0,          # per project; 0 = no cap (docs/scheduler.md §4.5)
    "budget_quota_per_week": 0,       # share of the weekly quota per project; 0 = no cap
    "max_steps_per_hour": 0,          # per packet; 0 = no cap
}
SERVER_DEFAULTS = {                   # server.md §6
    "port": 7878,
    "loopback": True,
    "tailnet": False,
    "auth": "tailscale",
    "allow": [],
    "tls": "off",
    "extra_hosts": [],
    "run": False,                      # dash-tasks.md §7: the runner in the server
    "listen": "",                      # "unix": $WPK_HOME/run/wpkd.sock, not 127.0.0.1 (§7.1);
                                       # "network": every address, with auth = "unix" (unix-login.md)
    "tls_cert": "",                    # tls = "files": your own certificate and key
    "tls_key": "",
    "session_days": 30,                # auth = "unix": how long a sign-in lasts
}
IDE_DEFAULTS = {                      # docs/vscode-plan.md §6
    "desktop": True,                   # vscode:// buttons
    "web": False,                      # VS Code under the board's /ide/
    "backend": "serve-web",
    "code": "",                        # empty: `code` (serve-web) or `openvscode-server`
    "ssh_host": "",                    # empty: you@ the board's name or MagicDNS name
    "desktop_link": "auto",            # auto | remote | local: the vscode:// link to follow
    "idle_minutes": 60,
    "max_servers": 8,                  # one server per open target; LRU idle one makes room
    "workspace_trust": False,          # V0 finding 4: the runner already runs this code
}
SCHED_DEFAULTS = {                    # docs/scheduler.md §10
    "backend": "local",                # local | slurm | lsf
    "cores": 0,                        # pool limits; 0 or "" = no limit
    "mem": "",
    "jobs": 0,                         # 0: max_concurrent
    "default_size": "look",
    "spare_size": "look",              # background leaves room for one of these
    "backfill_for": "10m",
    "age_after": "4h",
    "max_pending": "30m",
    "poll": "",                        # empty: the backend's own (local 1s, batch 15s)
    "tz": "",
    "start_mode": "run",               # run | drain: when control.toml is missing
    "node_env": "",
    "sizes": {"look": {"cpus": 1, "mem": "4G"}},
    "budget": {},
    "slurm": {},
    "lsf": {},
    "ide": {},
}
SCHED_BACKENDS = ("local", "slurm", "lsf")
SCHED_CLASSES = ("urgent", "high", "normal", "low", "background")
SCHED_MODES = ("run", "drain", "stop")
SIZE_KEYS = ("cpus", "mem", "time", "partition", "queue", "extra")
SCHED_BUDGET_DEFAULTS = {             # §4; Q2
    "measure": "",                     # usd | tokens | quota; empty: no budget
    "amount": 0.0,
    "period": "week",                  # day | week | month (ignored for quota)
    "slack": 0.1,
    "hard_cap": 0.0,                   # 0: amount
    "default_step": 0.0,
    "cache_read_weight": 0.1,
    "stale_after": "6h",
    "tz": "",
    "shape": {},
}
SCHED_BACKEND_KEYS = {
    "slurm": ("bin", "partition", "account", "extra", "poll"),
    "lsf": ("bin", "queue", "project", "extra", "poll"),
    "ide": ("reserve", "run_limit", "slot"),
}
_MEM_RX = re.compile(r"^(\d+)([KMGT]?)$")
IDE_BACKENDS = ("serve-web", "openvscode-server")   # docs/vscode-plan.md §4.4
SERVER_AUTH = ("tailscale", "unix", "none")    # unix: docs/unix-login.md
SERVER_TLS = ("off", "tailscale", "self-signed", "files")   # server.md §2.3
SERVER_LISTEN = ("", "unix", "network")
PERMISSION_DEFAULTS = {
    "allowed_tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
    "permission_mode": "acceptEdits",
}

JOURNAL_TYPES = {
    "step-start": ("step", "attempt", "model", "session_id"),
    "step-failed": ("step", "attempt", "why"),
    "step-nudge": ("step", "attempt", "why"),
    "commit-begin": ("step", "decision"),
    "commit-end": ("step",),
    "admin": ("op", "by"),
    "note": ("msg",),
    "handoff": ("by", "from", "to"),
    "config": ("by", "changes"),
    "seed": ("files",),               # docs/setup.md §10: the root filled from the project root
    "request": ("op", "id", "by"),    # docs/delegation.md: sent, received, done
}
DECISION_FIELDS = ("state", "resume_expr", "wake_at", "reason", "model",
                   "summary", "spawn")
DECISION_SPAWN_FIELDS = ("name", "wpid", "spawn_key", "instruction", "copy",
                         "model")

_WPID_RX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TS_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DUR_RX = re.compile(r"^(\d+)([smh])$")
_STEP_DIR_RX = re.compile(r"^(\d{4,})(?:\.failed-(\d+))?$")


@dataclass(frozen=True)
class Problem:
    field: Optional[str]
    msg: str
    level: str = "error"     # error | warning


def _err(field, msg):
    return Problem(field, msg, "error")


def _warn(field, msg):
    return Problem(field, msg, "warning")


# --- scalar types ---------------------------------------------------------

def is_wpid(v):
    return isinstance(v, str) and bool(_WPID_RX.match(v))


def is_name(v):
    return isinstance(v, str) and bool(_NAME_RX.match(v))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_timestamp(v):
    if not isinstance(v, str) or not _TS_RX.match(v):
        return False
    try:
        datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def format_timestamp(dt):
    """The one way the executor writes a time: UTC, seconds, ``Z``."""
    if dt.tzinfo is None:
        raise ValueError("format_timestamp needs an aware datetime")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(v):
    return datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_duration(v):
    """``"20m"`` -> 1200 seconds. Raises ValueError."""
    m = _DUR_RX.match(v) if isinstance(v, str) else None
    if not m:
        raise ValueError("expected a duration like 90s, 20m or 2h, got %r" % (v,))
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


def is_zone(v):
    if not isinstance(v, str):
        return False
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(v)
    except Exception:
        return False
    return True


def step_dir_name(n):
    return "%04d" % n


def parse_step_dir(name):
    """``"0007"`` -> (7, None); ``"0007.failed-2"`` -> (7, 2); otherwise None."""
    m = _STEP_DIR_RX.match(name)
    if not m:
        return None
    return int(m.group(1)), (int(m.group(2)) if m.group(2) else None)


def _unknown(d, known, where=None):
    out = []
    for k in d:
        if k not in known:
            f = k if where is None else "%s.%s" % (where, k)
            out.append(_err(f, "unknown key"))
    return out


def _opt_str(d, k, field=None):
    v = d.get(k)
    if v is not None and not isinstance(v, str):
        return [_err(field or k, "must be a string or null")]
    return []


# --- status.md ------------------------------------------------------------

def validate_status(meta, body=""):
    if meta is None:
        return [_err(None, "status.md has no front matter")]
    out = _unknown(meta, STATUS_FIELDS)
    for k in STATUS_FIELDS:
        if k not in meta and k not in STATUS_OPTIONAL:
            out.append(_err(k, "missing"))
    if "wpk" in meta and meta["wpk"] != FORMAT_VERSION:
        out.append(_err("wpk", "must be the string %r, got %r" % (FORMAT_VERSION, meta.get("wpk"))))
    if "wpid" in meta and not is_wpid(meta["wpid"]):
        out.append(_err("wpid", "not a WPID: %r" % (meta["wpid"],)))
    if "project" in meta and not is_name(meta["project"]):
        out.append(_err("project", "not a valid name: %r" % (meta["project"],)))
    st = meta.get("state")
    if "state" in meta:
        if st in RESERVED_STATES:
            out.append(_err("state", "%s is reserved for %s" % (st, RESERVED_STATES[st])))
        elif st not in STATES:
            out.append(_err("state", "must be one of %s, got %r" % (", ".join(STATES), st)))
    for k in ("step", "attempts"):
        if k in meta and not (is_int(meta[k]) and meta[k] >= 0):
            out.append(_err(k, "must be an integer >= 0"))
    parent, key = meta.get("parent"), meta.get("spawn_key")
    if parent is not None and not is_wpid(parent):
        out.append(_err("parent", "must be a WPID or null"))
    if key is not None:
        parts = key.split(":") if isinstance(key, str) else []
        if (len(parts) != 3 or not is_wpid(parts[0]) or not parts[1].isdigit()
                or not parts[2].isdigit()):
            out.append(_err("spawn_key", "must be '<parent WPID>:<step>:<index>'"))
        elif parent is not None and parts[0] != parent:
            out.append(_err("spawn_key", "names %s but parent is %s" % (parts[0], parent)))
    if (parent is None) != (key is None):
        out.append(_err("spawn_key", "must be set exactly when parent is"))
    ch = meta.get("children")
    if "children" in meta:
        if not isinstance(ch, list) or not all(is_wpid(c) for c in ch):
            out.append(_err("children", "must be a list of WPIDs"))
        elif len(set(ch)) != len(ch):
            out.append(_err("children", "has duplicates"))
    out += _opt_str(meta, "resume_expr")
    wake = meta.get("wake_at")
    if wake is not None and not is_timestamp(wake):
        out.append(_err("wake_at", "must be a UTC timestamp like 2026-10-21T18:02:11Z"))
    if st == "SLEEPING" and wake is None:
        out.append(_err("wake_at", "required when SLEEPING"))
    if st in STATES and st != "SLEEPING" and wake is not None:
        out.append(_err("wake_at", "must be null unless SLEEPING"))
    if "model" in meta and not (isinstance(meta["model"], str) and meta["model"]):
        out.append(_err("model", "must be a non-empty string"))
    out += _opt_str(meta, "reason")
    if "next_size" in meta and not is_name(meta["next_size"]):
        out.append(_err("next_size", "must be a size name"))
    if st in ("NEEDS_INPUT", "PAUSED", "FAILED") and not meta.get("reason"):
        out.append(_err("reason", "required when %s" % st))
    if "updated" in meta and not is_timestamp(meta["updated"]):
        out.append(_err("updated", "must be a UTC timestamp like 2026-10-21T18:02:11Z"))
    if list(k for k in meta if k in STATUS_FIELDS) != [k for k in STATUS_FIELDS if k in meta]:
        out.append(_warn(None, "keys are not in the spec order"))
    return out


# --- memento.md -----------------------------------------------------------

def _validate_glob(g):
    if not isinstance(g, str) or not g:
        return "must be a non-empty string"
    if g.startswith("/"):
        return "must be relative to state/"
    if ".." in g.replace("\\", "/").split("/"):
        return "must not contain '..'"
    return None


def validate_spawn(spawn):
    if not isinstance(spawn, list):
        return [_err("spawn", "must be a list")]
    out = []
    names = set()
    for i, ent in enumerate(spawn):
        w = "spawn[%d]" % i
        if not isinstance(ent, dict):
            out.append(_err(w, "must be a mapping"))
            continue
        out += _unknown(ent, SPAWN_FIELDS, w)
        name = ent.get("name")
        if not is_name(name):
            out.append(_err(w + ".name", "required; must match [a-z0-9][a-z0-9_-]*"))
        elif name in names:
            out.append(_err(w + ".name", "duplicate name %r" % name))
        else:
            names.add(name)
        ins = ent.get("instruction")
        if not isinstance(ins, str) or not ins.strip():
            out.append(_err(w + ".instruction", "required; must be a non-empty string"))
        cp = ent.get("copy")
        if cp is not None:
            if not isinstance(cp, list):
                out.append(_err(w + ".copy", "must be a list of globs"))
            else:
                for j, g in enumerate(cp):
                    why = _validate_glob(g)
                    if why:
                        out.append(_err("%s.copy[%d]" % (w, j), why))
        out += _opt_str(ent, "model", w + ".model")
    return out


def memento_item(meta):
    """The plan item a step worked on, from its memento's optional ``item``, as
    a string (a list is joined with ", "), or None. Never an error: a missing
    or odd ``item`` only means the step's tokens are not charged to an item."""
    v = meta.get("item") if isinstance(meta, dict) else None
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x).strip() for x in v
                      if isinstance(x, (str, int, float)) and not isinstance(x, bool)
                      and str(x).strip())
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if not isinstance(v, str):
        return None
    v = " ".join(v.split())
    return v[:ITEM_MAX] or None


def validate_memento(meta, body, proposal=True):
    """Check a memento.

    ``proposal=True`` is the model's ``.pending/memento.md``: front matter
    and ``resume`` are required. ``proposal=False`` is a committed memento:
    front matter may be absent or empty (a packet that has never run).
    """
    out = []
    if not meta:
        if proposal:
            return [_err(None, "memento has no front matter (resume: is required)")]
        if not body.strip():
            out.append(_err(None, "memento has no instruction"))
        return out
    for k, stage in MEMENTO_LATER.items():
        if k in meta:
            out.append(_err(k, "not supported yet: %s adds it" % stage))
    out += _unknown(meta, MEMENTO_FIELDS + tuple(MEMENTO_LATER))
    r = None
    if "resume" not in meta:
        out.append(_err("resume", "missing"))
    else:
        try:
            r = clock.parse_resume(meta["resume"])
        except clock.ResumeError as e:
            out.append(_err("resume", str(e)))
    out += _opt_str(meta, "reason")
    if r is not None and r.kind == "fail" and not meta.get("reason"):
        out.append(_err("reason", "required with resume: fail"))
    if "ask" in meta:
        from . import questions
        probs = questions.validate(meta["ask"])
        if probs:
            out += probs
        elif r is not None and r.kind in ("done", "fail"):
            out.append(_err("ask", "cannot go with resume: %s; the step after the answer "
                            "needs a resume" % r.kind))
        elif not body.strip():
            out.append(_err(None, "body is empty; with ask: it is the instruction for "
                            "after the answer"))
    if "spawn" in meta and meta["spawn"] is not None:
        out += validate_spawn(meta["spawn"])
    if "size" in meta and not is_name(meta["size"]):
        out.append(_err("size", "must be the name of a job size, such as look"))
    if r is not None and r.kind not in ("done", "fail") and not body.strip():
        out.append(_err(None, "body is empty; the next step needs an instruction"))
    return out


# --- TOML files -----------------------------------------------------------

def _validate_limits(d):
    out = []
    if "model" in d and not (isinstance(d["model"], str) and d["model"]):
        out.append(_err("model", "must be a non-empty string"))
    if "harness" in d:
        from .harness import names
        if d["harness"] not in names():
            out.append(_err("harness", "must be one of: %s" % ", ".join(names())))
    if "max_concurrent" in d and not (is_int(d["max_concurrent"]) and d["max_concurrent"] >= 1):
        out.append(_err("max_concurrent", "must be an integer >= 1"))
    if "max_attempts" in d and not (is_int(d["max_attempts"]) and d["max_attempts"] >= 1):
        out.append(_err("max_attempts", "must be an integer >= 1"))
    if "step_timeout" in d:
        try:
            parse_duration(d["step_timeout"])
        except ValueError as e:
            out.append(_err("step_timeout", str(e)))
    if "step_budget_usd" in d:
        v = d["step_budget_usd"]
        if not (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0):
            out.append(_err("step_budget_usd", "must be a number > 0"))
    if "step_context_tokens" in d and not (is_int(d["step_context_tokens"])
                                           and d["step_context_tokens"] >= 0):
        out.append(_err("step_context_tokens", "must be an integer >= 0"))
    if "carry_session" in d and not isinstance(d["carry_session"], bool):
        out.append(_err("carry_session", "must be true or false"))
    if "carry_factor" in d:
        v = d["carry_factor"]
        if not (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 1):
            out.append(_err("carry_factor", "must be a number > 1"))
    if "carry_ttl" in d:
        try:
            parse_duration(d["carry_ttl"])
        except ValueError as e:
            out.append(_err("carry_ttl", str(e)))
    for k in ("budget_usd_per_day", "budget_quota_per_week"):
        v = d.get(k, 0)
        if not (isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0):
            out.append(_err(k, "must be a number >= 0 (0: no cap)"))
    if "max_steps_per_hour" in d and not (is_int(d["max_steps_per_hour"])
                                          and d["max_steps_per_hour"] >= 0):
        out.append(_err("max_steps_per_hour", "must be a whole number >= 0 (0: no cap)"))
    return out


def _validate_profiles(d):
    from .profiles import validate
    t = d.get("profiles")
    if t is None:
        return []
    if not isinstance(t, dict):
        return [_err("profiles", "must be a table of [profiles.<name>] tables")]
    return [_err("profiles.%s" % name, msg) for name, pd in t.items()
            for msg in validate(name, pd)[:1]]


def _validate_server(d):
    t = d.get("server")
    if t is None:
        return []
    if not isinstance(t, dict):
        return [_err("server", "must be a table")]
    out = _unknown(t, tuple(SERVER_DEFAULTS), "server")
    port = t.get("port", 7878)
    if not (isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536):
        out.append(_err("server.port", "must be a port number"))
    for k in ("loopback", "tailnet", "run"):
        if k in t and not isinstance(t[k], bool):
            out.append(_err("server." + k, "must be true or false"))
    if t.get("auth", "tailscale") not in SERVER_AUTH:
        out.append(_err("server.auth", "must be one of %s (token and pam are not built yet)"
                        % ", ".join(SERVER_AUTH)))
    elif t.get("auth") == "none" and t.get("tailnet"):
        out.append(_err("server.auth", "\"none\" cannot be used with tailnet = true"))
    elif t.get("auth") == "unix" and t.get("tailnet"):
        out.append(_err("server.auth", "\"unix\" is for listen = \"network\", not the tailnet"))
    for k in ("allow", "extra_hosts"):
        v = t.get(k, [])
        if not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
            out.append(_err("server." + k, "must be a list of strings"))
    if t.get("listen", "") not in SERVER_LISTEN:
        out.append(_err("server.listen", "must be \"unix\", \"network\" or empty "
                        "(a TCP port on loopback)"))
    if t.get("tls", "off") not in SERVER_TLS:
        out.append(_err("server.tls", "must be one of %s" % ", ".join(SERVER_TLS)))
    for k in ("tls_cert", "tls_key"):
        if not isinstance(t.get(k, ""), str):
            out.append(_err("server." + k, "must be a path"))
    if t.get("tls") == "files" and not (t.get("tls_cert") and t.get("tls_key")):
        out.append(_err("server.tls", "\"files\" needs tls_cert and tls_key"))
    days = t.get("session_days", 30)
    if not (isinstance(days, int) and not isinstance(days, bool) and 0 < days <= 366):
        out.append(_err("server.session_days", "must be a number of days (1 to 366)"))
    if t.get("listen") == "network":
        if t.get("auth") != "unix":
            out.append(_err("server.listen", "\"network\" needs auth = \"unix\" "
                            "(docs/unix-login.md)"))
        if t.get("tls", "off") not in ("self-signed", "files"):
            out.append(_err("server.tls", "listen = \"network\" needs tls = \"self-signed\" "
                            "or \"files\": a session cookie must not cross the network "
                            "in clear"))
    return out


def _validate_ide(d):
    t = d.get("ide")
    if t is None:
        return []
    if not isinstance(t, dict):
        return [_err("ide", "must be a table")]
    out = _unknown(t, tuple(IDE_DEFAULTS), "ide")
    for k in ("desktop", "web", "workspace_trust"):
        if k in t and not isinstance(t[k], bool):
            out.append(_err("ide." + k, "must be true or false"))
    for k in ("code", "ssh_host"):
        if k in t and not isinstance(t[k], str):
            out.append(_err("ide." + k, "must be a string"))
    if t.get("desktop_link", "auto") not in ("auto", "remote", "local"):
        out.append(_err("ide.desktop_link", "must be auto, remote or local"))
    if t.get("backend", "serve-web") not in IDE_BACKENDS:
        out.append(_err("ide.backend", "must be one of %s" % ", ".join(IDE_BACKENDS)))
    for k, dflt in (("idle_minutes", 60), ("max_servers", 8)):
        m = t.get(k, dflt)
        if not (isinstance(m, int) and not isinstance(m, bool) and m > 0):
            out.append(_err("ide." + k, "must be a positive whole number"))
    return out


def parse_mem(v):
    """``"32G"`` -> megabytes (32768). A bare number is megabytes. Raises ValueError."""
    m = _MEM_RX.match(v.strip().upper()) if isinstance(v, str) else None
    if is_int(v) and v >= 0:
        return v
    if not m:
        raise ValueError("expected a memory size like 512M, 4G or 1T, got %r" % (v,))
    n = int(m.group(1))
    return {"K": n // 1024, "": n, "M": n, "G": n * 1024, "T": n * 1024 * 1024}[m.group(2)]


def _strs(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def validate_size(name, t, where="sched.sizes"):
    f = "%s.%s" % (where, name)
    if not is_name(name):
        return [_err(f, "a size name must match [a-z0-9][a-z0-9_-]*")]
    if not isinstance(t, dict):
        return [_err(f, "must be a table")]
    out = _unknown(t, SIZE_KEYS, f)
    if not (is_int(t.get("cpus")) and t["cpus"] >= 1):
        out.append(_err(f + ".cpus", "required; must be a whole number >= 1"))
    if "mem" in t:
        try:
            parse_mem(t["mem"])
        except ValueError as e:
            out.append(_err(f + ".mem", str(e)))
    if "time" in t:
        try:
            parse_duration(t["time"])
        except ValueError as e:
            out.append(_err(f + ".time", str(e)))
    for k in ("partition", "queue"):
        if k in t and not isinstance(t[k], str):
            out.append(_err("%s.%s" % (f, k), "must be a string"))
    if "extra" in t and not _strs(t["extra"]):
        out.append(_err(f + ".extra", "must be a list of strings"))
    return out


def _validate_budget(t):
    if not isinstance(t, dict):
        return [_err("sched.budget", "must be a table")]
    out = _unknown(t, tuple(SCHED_BUDGET_DEFAULTS), "sched.budget")
    if t.get("measure", "") not in ("", "usd", "tokens", "quota"):
        out.append(_err("sched.budget.measure", "must be usd, tokens or quota"))
    if t.get("period", "week") not in ("day", "week", "month"):
        out.append(_err("sched.budget.period", "must be day, week or month"))
    for k in ("amount", "slack", "hard_cap", "default_step", "cache_read_weight"):
        v = t.get(k, 0)
        if not (isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0):
            out.append(_err("sched.budget." + k, "must be a number >= 0"))
    if "stale_after" in t:
        try:
            parse_duration(t["stale_after"])
        except ValueError as e:
            out.append(_err("sched.budget.stale_after", str(e)))
    if "tz" in t and t["tz"] and not is_zone(t["tz"]):
        out.append(_err("sched.budget.tz", "not a known IANA time zone"))
    sh = t.get("shape", {})
    if not isinstance(sh, dict):
        out.append(_err("sched.budget.shape", "must be a table"))
    else:
        out += _unknown(sh, ("weekday", "hour"), "sched.budget.shape")
        for k, n in (("weekday", 7), ("hour", 24)):
            v = sh.get(k)
            if v is not None and not (isinstance(v, list) and len(v) == n and all(
                    isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0
                    for x in v) and sum(v) > 0):
                out.append(_err("sched.budget.shape." + k,
                                "must be a list of %d numbers >= 0, not all 0" % n))
    return out


def validate_sched(t):
    """``[sched]`` (docs/scheduler.md §10)."""
    if not isinstance(t, dict):
        return [_err("sched", "must be a table")]
    out = _unknown(t, tuple(SCHED_DEFAULTS), "sched")
    if t.get("backend", "local") not in SCHED_BACKENDS:
        out.append(_err("sched.backend", "must be one of %s" % ", ".join(SCHED_BACKENDS)))
    for k in ("cores", "jobs"):
        v = t.get(k, 0)
        if not (is_int(v) and v >= 0):
            out.append(_err("sched." + k, "must be a whole number >= 0 (0: no limit)"))
    if t.get("mem", ""):
        try:
            parse_mem(t["mem"])
        except ValueError as e:
            out.append(_err("sched.mem", str(e)))
    for k in ("backfill_for", "age_after", "max_pending"):
        if k in t:
            try:
                parse_duration(t[k])
            except ValueError as e:
                out.append(_err("sched." + k, str(e)))
    if t.get("poll", ""):
        try:
            parse_duration(t["poll"])
        except ValueError as e:
            out.append(_err("sched.poll", str(e)))
    if t.get("tz") and not is_zone(t["tz"]):
        out.append(_err("sched.tz", "not a known IANA time zone"))
    if t.get("start_mode", "run") not in ("run", "drain"):
        out.append(_err("sched.start_mode", "must be run or drain"))
    if not isinstance(t.get("node_env", ""), str):
        out.append(_err("sched.node_env", "must be a string"))
    sizes = t.get("sizes", {})
    if not isinstance(sizes, dict):
        out.append(_err("sched.sizes", "must be a table of [sched.sizes.<name>] tables"))
        sizes = {}
    for name, st in sizes.items():
        out += validate_size(name, st)
    known = set(sizes) | set(SCHED_DEFAULTS["sizes"])
    for k in ("default_size", "spare_size"):
        v = t.get(k, SCHED_DEFAULTS[k])
        if v not in known:
            out.append(_err("sched." + k, "names no size in [sched.sizes]: %r" % (v,)))
    if "budget" in t:
        out += _validate_budget(t["budget"])
    for sub, keys in SCHED_BACKEND_KEYS.items():
        v = t.get(sub, {})
        if not isinstance(v, dict):
            out.append(_err("sched." + sub, "must be a table"))
            continue
        out += _unknown(v, keys, "sched." + sub)
        for k in keys:
            if k not in v:
                continue
            if k == "slot":
                if not isinstance(v[k], bool):
                    out.append(_err("sched.ide.slot", "must be true or false"))
            elif k == "extra":
                if not _strs(v[k]):
                    out.append(_err("sched.%s.extra" % sub, "must be a list of strings"))
            elif k in ("poll", "run_limit") and v[k]:
                try:
                    parse_duration(v[k])
                except ValueError as e:
                    out.append(_err("sched.%s.%s" % (sub, k), str(e)))
            elif not isinstance(v[k], str):
                out.append(_err("sched.%s.%s" % (sub, k), "must be a string"))
    return out


def validate_config(d):
    out = _unknown(d, tuple(CONFIG_DEFAULTS) + ("profiles", "server", "ide", "sched", "forge")) \
        + _validate_limits(d) + _validate_profiles(d) + _validate_server(d) + _validate_ide(d) \
        + _validate_forges(d.get("forge"))
    if "sched" in d:
        out += validate_sched(d["sched"])
    return out


FORGE_KEYS = (("name", "kind"), ("url", "token_env", "clone"))   # docs/starters-v1.md


def _validate_forges(lst):
    if lst is None:
        return []
    if not (isinstance(lst, list) and all(isinstance(e, dict) for e in lst)):
        return [_err("forge", "must be a list of [[forge]] tables")]
    out, seen = [], set()
    for i, f in enumerate(lst):
        k = "forge[%d]" % i
        out += _unknown(f, FORGE_KEYS[0] + FORGE_KEYS[1], k)
        if not is_name(f.get("name")):
            out.append(_err(k + ".name", "required; must match [a-z0-9][a-z0-9_-]*"))
        elif f["name"] in seen:
            out.append(_err(k + ".name", "%s is named twice" % f["name"]))
        seen.add(f.get("name"))
        if f.get("kind") not in ("github", "forgejo"):
            out.append(_err(k + ".kind", "must be github or forgejo"))
        elif f["kind"] == "forgejo" and not isinstance(f.get("url"), str):
            out.append(_err(k + ".url", "required for forgejo"))
        if f.get("clone", "https") not in ("https", "ssh"):
            out.append(_err(k + ".clone", "must be https or ssh"))
        for x in ("url", "token_env"):
            if x in f and not isinstance(f[x], str):
                out.append(_err(k + "." + x, "must be a string"))
    return out


def _validate_template(d):
    t = d.get("template")
    if t is not None and not (isinstance(t, str) and re.match(r"^[a-z0-9][a-z0-9_-]*@\d+$", t)):
        return [_err("template", "must look like 'blank@1'")]
    return []


SETUP_TABLES = {                        # docs/setup.md §4: (required, optional) keys
    "repo": (("name", "from"), ("branch", "share")),
    "input": (("from",), ("to",)),
    "link": (("from",), ("name",)),
    "smoke": (("run",), ("repo",)),
}


def _validate_setup(t):
    if t is None:
        return []
    if not isinstance(t, dict):
        return [_err("setup", "must be a table")]
    out = _unknown(t, ("smoke_timeout",) + tuple(SETUP_TABLES), "setup")
    if "smoke_timeout" in t:
        try:
            parse_duration(t["smoke_timeout"])
        except ValueError as e:
            out.append(_err("setup.smoke_timeout", str(e)))
    for kind, (req, opt) in SETUP_TABLES.items():
        lst = t.get(kind, [])
        if not (isinstance(lst, list) and all(isinstance(e, dict) for e in lst)):
            out.append(_err("setup." + kind, "must be a list of [[setup.%s]] tables" % kind))
            continue
        for i, e in enumerate(lst):
            f = "setup.%s[%d]" % (kind, i)
            out += _unknown(e, req + opt, f)
            for k in req:
                if not (isinstance(e.get(k), str) and e[k]):
                    out.append(_err("%s.%s" % (f, k), "required; must be a non-empty string"))
            for k in opt:
                if k == "share":
                    v = e.get(k, [])
                    if not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
                        out.append(_err(f + ".share", "must be a list of directory names"))
                elif k in e and not (isinstance(e[k], str) and e[k]):
                    out.append(_err("%s.%s" % (f, k), "must be a non-empty string"))
    return out


PROJECT_SCHED_KEYS = ("sizes", "weight", "max_cores")      # docs/scheduler.md §10


def _validate_project_sched(d):
    out = []
    if "sizes" in d and not (isinstance(d["sizes"], list) and d["sizes"]
                             and all(is_name(x) for x in d["sizes"])):
        out.append(_err("sizes", "must be a non-empty list of size names"))
    if "weight" in d:
        v = d["weight"]
        if not (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0):
            out.append(_err("weight", "must be a number > 0"))
    if "max_cores" in d and not (is_int(d["max_cores"]) and d["max_cores"] >= 0):
        out.append(_err("max_cores", "must be a whole number >= 0 (0: no limit)"))
    return out


def validate_project(d):
    known = ("name", "root", "created", "template", "tz", "model", "harness", "profile",
             "step_timeout", "max_attempts", "step_budget_usd", "step_context_tokens",
             "carry_session", "carry_ttl", "carry_factor", "permissions", "setup",
             "budget_usd_per_day", "budget_quota_per_week", "max_steps_per_hour",
             "origin", "pr") + PROJECT_SCHED_KEYS
    out = _unknown(d, known) + _validate_setup(d.get("setup")) + _validate_project_sched(d)
    if "origin" in d and not (isinstance(d["origin"], dict) and all(
            isinstance(v, (str, int)) for v in d["origin"].values())):
        out.append(_err("origin", "must be a table of strings and numbers (docs/starters-v1.md)"))
    if "pr" in d and not (isinstance(d["pr"], dict) and all(
            isinstance(v, (str, int)) for v in d["pr"].values())):
        out.append(_err("pr", "must be a table of strings and numbers (docs/starters-v1.md)"))
    if not is_name(d.get("name")):
        out.append(_err("name", "required; must match [a-z0-9][a-z0-9_-]*"))
    if not is_wpid(d.get("root")):
        out.append(_err("root", "required; must be a WPID"))
    if not is_timestamp(d.get("created")):
        out.append(_err("created", "required; must be a UTC timestamp"))
    out += _validate_template(d)
    if "tz" in d and not is_zone(d["tz"]):
        out.append(_err("tz", "not a known IANA time zone: %r" % (d["tz"],)))
    out += _validate_limits(d)
    if "profile" in d and not is_name(d["profile"]):
        out.append(_err("profile", "must be a profile name"))
    perm = d.get("permissions")
    if perm is not None:
        if not isinstance(perm, dict):
            out.append(_err("permissions", "must be a table"))
        else:
            out += _unknown(perm, tuple(PERMISSION_DEFAULTS), "permissions")
            at = perm.get("allowed_tools")
            if at is not None and not (isinstance(at, list) and all(isinstance(t, str) and t for t in at)):
                out.append(_err("permissions.allowed_tools", "must be a list of strings"))
            pm = perm.get("permission_mode")
            if pm is not None and pm not in PERMISSION_MODES:
                out.append(_err("permissions.permission_mode",
                                "must be one of %s" % ", ".join(PERMISSION_MODES)))
    return out


PACKET_SCHED_KEYS = ("priority", "size", "next")


def _validate_entry_sched(d):
    """The scheduling keys of a registry entry (docs/scheduler.md §3.2). Size
    names are checked against ``[sched.sizes]`` only as a warning (by the
    scheduler), so a config change never breaks an entry."""
    out = []
    if "priority" in d and d["priority"] not in SCHED_CLASSES:
        out.append(_err("priority", "must be one of %s" % ", ".join(SCHED_CLASSES)))
    if "size" in d and not is_name(d["size"]):
        out.append(_err("size", "must be a size name"))
    if d.get("sched", "run") not in ("run", "hold"):
        out.append(_err("sched", "must be run or hold"))
    for k in ("sched_by", "sched_at", "sched_reason"):
        out += _opt_str(d, k)
    pk = d.get("packets", {})
    if not isinstance(pk, dict):
        return out + [_err("packets", "must be a table of [packets.<wpid>] tables")]
    for w, t in pk.items():
        f = "packets.%s" % w
        if not is_wpid(w):
            out.append(_err(f, "not a WPID"))
        if not isinstance(t, dict):
            out.append(_err(f, "must be a table"))
            continue
        out += _unknown(t, PACKET_SCHED_KEYS, f)
        if "priority" in t and t["priority"] not in SCHED_CLASSES:
            out.append(_err(f + ".priority", "must be one of %s" % ", ".join(SCHED_CLASSES)))
        if "size" in t and not is_name(t["size"]):
            out.append(_err(f + ".size", "must be a size name"))
        if "next" in t and not isinstance(t["next"], bool):
            out.append(_err(f + ".next", "must be true or false"))
    return out


def validate_registry_entry(d, stem=None):
    out = _unknown(d, ("name", "path", "root", "created", "template", "board", "priority",
                       "size", "sched", "sched_by", "sched_at", "sched_reason", "packets"))
    out += _validate_entry_sched(d)
    if not is_name(d.get("name")):
        out.append(_err("name", "required; must match [a-z0-9][a-z0-9_-]*"))
    elif stem is not None and d["name"] != stem:
        out.append(_err("name", "is %r but the file is %s.toml" % (d["name"], stem)))
    if "board" in d and not is_name(d["board"]):
        out.append(_err("board", "must match [a-z0-9][a-z0-9_-]*"))
    p = d.get("path")
    if not (isinstance(p, str) and p.startswith("/")):
        out.append(_err("path", "required; must be an absolute path"))
    if not is_wpid(d.get("root")):
        out.append(_err("root", "required; must be a WPID"))
    if not is_timestamp(d.get("created")):
        out.append(_err("created", "required; must be a UTC timestamp"))
    out += _validate_template(d)
    return out


def validate_board(d, stem=None):
    """``boards/<name>.toml`` (docs/boards.md)."""
    out = _unknown(d, ("name", "created", "title", "watch"))    # watch: validate_watches
    if not is_name(d.get("name")):
        out.append(_err("name", "required; must match [a-z0-9][a-z0-9_-]*"))
    elif stem is not None and d["name"] != stem:
        out.append(_err("name", "is %r but the file is %s.toml" % (d["name"], stem)))
    if not is_timestamp(d.get("created")):
        out.append(_err("created", "required; must be a UTC timestamp"))
    if "title" in d and not isinstance(d["title"], str):
        out.append(_err("title", "must be a string"))
    return out


WATCH_KEYS = ("name", "repos", "dir", "labels", "query", "every", "hold", "from", "model",
              "harness", "max_new", "enabled", "pr")      # docs/starters-v1.md, watchers
WATCH_REPO_RX = re.compile(r"^[a-z0-9][a-z0-9_-]*:[\w.-]+/(\*|[\w.-]+)$")   # owner/*: all


def validate_watches(lst):
    """``[[watch]]`` tables of a board."""
    if lst is None:
        return []
    if not (isinstance(lst, list) and all(isinstance(e, dict) for e in lst)):
        return [_err("watch", "must be a list of [[watch]] tables")]
    out, seen = [], set()
    for i, w in enumerate(lst):
        k = "watch[%d]" % i
        out += _unknown(w, WATCH_KEYS, k)
        if not is_name(w.get("name")):
            out.append(_err(k + ".name", "required; must match [a-z0-9][a-z0-9_-]*"))
        elif w["name"] in seen:
            out.append(_err(k + ".name", "%s is named twice" % w["name"]))
        seen.add(w.get("name"))
        r = w.get("repos")
        if not (isinstance(r, list) and r and all(isinstance(x, str) and WATCH_REPO_RX.match(x)
                                                   for x in r)):
            out.append(_err(k + ".repos", "required; a list of forge:owner/repo or "
                            "forge:owner/* (all the owner's repos)"))
        if not isinstance(w.get("dir"), str) or not w["dir"]:
            out.append(_err(k + ".dir", "required; where the packet folders go"))
        if "labels" in w and not (isinstance(w["labels"], list) and
                                  all(isinstance(x, str) for x in w["labels"])):
            out.append(_err(k + ".labels", "must be a list of strings"))
        for x in ("query", "from", "model", "harness"):
            if x in w and not isinstance(w[x], str):
                out.append(_err(k + "." + x, "must be a string"))
        for x in ("hold", "enabled"):
            if x in w and not isinstance(w[x], bool):
                out.append(_err(k + "." + x, "must be true or false"))
        if "pr" in w and w["pr"] not in ("off", "draft", "ready"):
            out.append(_err(k + ".pr", "off, draft or ready (open a pull request when a "
                            "packet completes)"))
        if "every" in w:
            try:
                if parse_duration(w["every"]) < 60:
                    out.append(_err(k + ".every", "at least 1m"))
            except ValueError as e:
                out.append(_err(k + ".every", str(e)))
        if "max_new" in w and not (is_int(w["max_new"]) and w["max_new"] >= 1):
            out.append(_err(k + ".max_new", "must be an integer >= 1"))
    return out


# --- journal.jsonl --------------------------------------------------------

def validate_journal_record(rec):
    if not isinstance(rec, dict):
        return [_err(None, "record is not a JSON object")]
    t = rec.get("type")
    if t not in JOURNAL_TYPES:
        return [_err("type", "unknown record type %r" % (t,))]
    out = []
    if not is_timestamp(rec.get("t")):
        out.append(_err("t", "required; must be a UTC timestamp"))
    for k in JOURNAL_TYPES[t]:
        if k not in rec:
            out.append(_err(k, "missing in %s record" % t))
    for k in ("step", "attempt"):
        if k in rec and not (is_int(rec[k]) and rec[k] >= 0):
            out.append(_err(k, "must be an integer >= 0"))
    if t == "commit-begin" and "decision" in rec:
        dec = rec["decision"]
        if not isinstance(dec, dict):
            out.append(_err("decision", "must be an object"))
        else:
            for k in DECISION_FIELDS:
                if k not in dec:
                    out.append(_err("decision." + k, "missing"))
            if dec.get("state") is not None and dec.get("state") not in STATES:
                out.append(_err("decision.state", "not a state: %r" % (dec.get("state"),)))
            sp = dec.get("spawn")
            if sp is not None and not isinstance(sp, list):
                out.append(_err("decision.spawn", "must be a list"))
            elif sp:
                for i, ent in enumerate(sp):
                    w = "decision.spawn[%d]" % i
                    if not isinstance(ent, dict):
                        out.append(_err(w, "must be an object"))
                        continue
                    for k in DECISION_SPAWN_FIELDS:
                        if k not in ent:
                            out.append(_err("%s.%s" % (w, k), "missing"))
                    if "wpid" in ent and not is_wpid(ent["wpid"]):
                        out.append(_err(w + ".wpid", "not a WPID"))
    return out
