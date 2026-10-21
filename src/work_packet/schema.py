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

STATES = ("RUNNABLE", "SLEEPING", "PAUSED", "COMPLETED", "FAILED")
RESERVED_STATES = {"WAITING": "Stage 3", "NEEDS_INPUT": "Stage 3"}

STATUS_FIELDS = (
    "wpk", "wpid", "project", "state", "step", "attempts", "parent",
    "spawn_key", "children", "resume_expr", "wake_at", "model", "reason",
    "updated",
)

MEMENTO_FIELDS = ("resume", "reason", "spawn")
MEMENTO_LATER = {"every": "Stage 2", "wait": "Stage 3", "ask": "Stage 3"}
SPAWN_FIELDS = ("name", "instruction", "copy", "model")

PERMISSION_MODES = ("acceptEdits", "auto", "bypassPermissions", "dontAsk",
                    "manual", "plan")

CONFIG_DEFAULTS = {
    "model": "claude-haiku-4-5-20251001",
    "max_concurrent": 1,
    "step_timeout": "20m",
    "max_attempts": 3,
    "step_budget_usd": 1.00,
}
PERMISSION_DEFAULTS = {
    "allowed_tools": ["Read", "Write", "Edit", "Glob", "Grep"],
    "permission_mode": "acceptEdits",
}

JOURNAL_TYPES = {
    "step-start": ("step", "attempt", "model", "session_id"),
    "step-failed": ("step", "attempt", "why"),
    "commit-begin": ("step", "decision"),
    "commit-end": ("step",),
    "admin": ("op", "by"),
    "note": ("msg",),
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
        if k not in meta:
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
    if st in ("PAUSED", "FAILED") and not meta.get("reason"):
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
    if "spawn" in meta and meta["spawn"] is not None:
        out += validate_spawn(meta["spawn"])
    if r is not None and r.kind not in ("done", "fail") and not body.strip():
        out.append(_err(None, "body is empty; the next step needs an instruction"))
    return out


# --- TOML files -----------------------------------------------------------

def _validate_limits(d):
    out = []
    if "model" in d and not (isinstance(d["model"], str) and d["model"]):
        out.append(_err("model", "must be a non-empty string"))
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
    return out


def validate_config(d):
    return _unknown(d, tuple(CONFIG_DEFAULTS)) + _validate_limits(d)


def _validate_template(d):
    t = d.get("template")
    if t is not None and not (isinstance(t, str) and re.match(r"^[a-z0-9][a-z0-9_-]*@\d+$", t)):
        return [_err("template", "must look like 'blank@1'")]
    return []


def validate_project(d):
    known = ("name", "root", "created", "template", "tz", "model",
             "step_timeout", "max_attempts", "step_budget_usd", "permissions")
    out = _unknown(d, known)
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


def validate_registry_entry(d, stem=None):
    out = _unknown(d, ("name", "path", "root", "created", "template"))
    if not is_name(d.get("name")):
        out.append(_err("name", "required; must match [a-z0-9][a-z0-9_-]*"))
    elif stem is not None and d["name"] != stem:
        out.append(_err("name", "is %r but the file is %s.toml" % (d["name"], stem)))
    p = d.get("path")
    if not (isinstance(p, str) and p.startswith("/")):
        out.append(_err("path", "required; must be an absolute path"))
    if not is_wpid(d.get("root")):
        out.append(_err("root", "required; must be a WPID"))
    if not is_timestamp(d.get("created")):
        out.append(_err("created", "required; must be a UTC timestamp"))
    out += _validate_template(d)
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
