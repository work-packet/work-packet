"""When the sessions people drive spent their tokens (docs/session-cost-plan.md S2).

One file per session, ``$WPK_HOME/usage/sessions/<harness>-<sid>.json``: who and
where (harness, client, project, wpid, attribution) and ``hours``, the tokens by
hour and model (``{"<hour epoch>": {"<model>": {usage}}}``). It is rewritten with
the session's record (``ide_sessions.write``) and, unlike that record, never
pruned, so the Cost tab and Statistics keep their history.

Only ids, times, models and counts: no prompt or reply text. Light imports only:
the IDE job on an exec host writes here through a shared ``$WPK_HOME``.
"""

import json
import os
import re

KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
        "output_tokens", "thinking_tokens", "cache_creation_1h_input_tokens")
WHO = ("harness", "session_id", "client", "project", "wpid", "attribution", "model",
       "first_seen_t", "last_activity_t")
_HOUR = re.compile(r"\d{1,11}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,79}\Z")


def usage_dir(home):
    return os.path.join(home, "usage", "sessions")


def clean_hours(hours):
    """``hours`` with only well-formed buckets and non-negative integer counts."""
    out = {}
    for h, models in (hours or {}).items() if isinstance(hours, dict) else ():
        if not (isinstance(h, str) and _HOUR.match(h)) or not isinstance(models, dict):
            continue
        for m, u in models.items():
            if not (isinstance(m, str) and _MODEL.match(m)) or not isinstance(u, dict):
                continue
            got = {k: v for k, v in u.items() if k in KEYS and isinstance(v, int)
                   and not isinstance(v, bool) and v > 0}
            if got:
                out.setdefault(h, {})[m] = got
    return out


def put(home, rec, hours):
    """Store one session's hours beside who and where (``rec``: a session record)."""
    d = usage_dir(home)
    os.makedirs(d, mode=0o700, exist_ok=True)
    out = {k: rec[k] for k in WHO if rec.get(k) is not None}
    out["hours"] = clean_hours(hours)
    path = os.path.join(d, "%s-%s.json" % (rec["harness"], rec["session_id"]))
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fp:
        json.dump(out, fp, sort_keys=True)
    os.replace(tmp, path)
    return out


def _load(path):
    try:
        with open(path) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("harness"), str) or \
            not isinstance(d.get("session_id"), str):
        return None
    d["hours"] = clean_hours(d.get("hours"))
    return d


def records(home):
    """Every session's usage record."""
    d = usage_dir(home)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [r for r in (_load(os.path.join(d, n)) for n in names if n.endswith(".json"))
            if r is not None]


_CACHE = {}


def cached(home):
    """``records`` again only when a file changed (page handlers read this)."""
    d = usage_dir(home)
    try:
        sig = max([os.stat(d).st_mtime_ns] + [e.stat().st_mtime_ns for e in os.scandir(d)])
    except OSError:
        return []
    got = _CACHE.get(d)
    if got is None or got[0] != sig:
        got = _CACHE[d] = (sig, records(home))
    return got[1]


def rows(home, since=None, until=None, project=None):
    """``[(hour_t, model, usage, record)]`` for every bucket in ``[since, until)``,
    optionally of one project. Buckets with no time ("0") are left out."""
    out = []
    for r in cached(home):
        if project is not None and r.get("project") != project:
            continue
        for h, models in r["hours"].items():
            t = int(h)
            if not t or (since is not None and t < since) or (until is not None and t >= until):
                continue
            for m, u in models.items():
                out.append((t, m, u, r))
    return out
