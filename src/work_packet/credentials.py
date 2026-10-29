"""The credential store (design E3): one JSON file per credential under
``$WPK_HOME/credentials/`` (directory 0700, files 0600), for plugins that
sign in to something (``wpk gateway login``) and for wpkd, which watches the
directory so a new login is picked up without a restart.

The store keeps what it is given; checking ``subject`` against the home's
owner is the plugin's job."""
import datetime
import json
import os
import re
import stat

from . import fsutil

STATUSES = ("ok", "expired", "missing", "invalid")
_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


class Credential:
    """What ``get`` returns. ``mark`` is the last ``mark()`` since the last
    ``put`` ({status, note, at}), or None."""

    def __init__(self, name, data, subject=None, expires=None, updated=None, mark=None):
        self.name, self.data, self.subject = name, data, subject
        self.expires, self.updated, self.mark = expires, updated, mark

    def __repr__(self):
        return "Credential(%r, subject=%r, expires=%r)" % (self.name, self.subject, self.expires)


def directory(h=None):
    from . import registry
    return os.path.join(h or registry.home(), "credentials")


def _path(name, h=None):
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError("bad credential name %r" % (name,))
    return os.path.join(directory(h), name + ".json")


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(t):
    """An expiry as given (datetime, epoch seconds or ISO text) -> ISO UTC text."""
    if t is None:
        return None
    if isinstance(t, (int, float)):
        t = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    elif isinstance(t, str):
        t = datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def _mkdir(h=None):
    d = directory(h)
    os.makedirs(d, mode=0o700, exist_ok=True)
    if stat.S_IMODE(os.stat(d).st_mode) != 0o700:
        os.chmod(d, 0o700)          # repair: it holds secrets
    return d


def _write(name, rec, h=None):
    _mkdir(h)
    path = _path(name, h)
    fsutil.atomic_write(path, json.dumps(rec, indent=1, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def put(name, data, subject=None, expires=None, h=None):
    """Store ``data`` (a JSON-able dict) as credential ``name``, atomically and
    0600. Clears any mark."""
    if not isinstance(data, dict):
        raise TypeError("credential data must be a dict")
    rec = {"data": data, "subject": subject, "expires": _iso(expires),
           "updated": _now().isoformat(timespec="seconds")}
    _write(name, rec, h)


def _read(name, h=None):
    """-> (record or None, why-invalid or None)."""
    path = _path(name, h)
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        return None, None
    if mode & 0o077:
        return None, "mode %o; it must be 0600" % mode
    try:
        with open(path, encoding="utf-8") as fp:
            rec = json.load(fp)
    except (OSError, ValueError) as e:
        return None, str(e)
    if not isinstance(rec, dict) or not isinstance(rec.get("data"), dict):
        return None, "not a credential record"
    return rec, None


def get(name, h=None):
    """The credential, or None when it is missing or unreadable (see status)."""
    rec, _ = _read(name, h)
    if rec is None:
        return None
    return Credential(name, rec["data"], rec.get("subject"), rec.get("expires"),
                      rec.get("updated"), rec.get("mark"))


def check(name, h=None):
    """-> (status, note): status as ``status()``; note says why when not ok."""
    if not os.path.exists(_path(name, h)):
        return "missing", ""
    rec, why = _read(name, h)
    if rec is None:
        return "invalid", why
    m = rec.get("mark")
    if m and m.get("status") in ("expired", "invalid"):
        return m["status"], m.get("note") or ""
    exp = rec.get("expires")
    if exp:
        try:
            if datetime.datetime.fromisoformat(exp) <= _now():
                return "expired", "expired %s" % exp
        except (TypeError, ValueError):
            return "invalid", "bad expires %r" % (exp,)
    return "ok", ""


def status(name, h=None):
    """"ok" | "expired" | "missing" | "invalid"."""
    return check(name, h)[0]


def mark(name, status, note="", h=None):
    """Record what a user of the credential saw (a 401 -> "invalid"), until the
    next ``put``. "ok" clears a mark. Returns False when there is nothing to mark."""
    if status not in ("ok", "expired", "invalid"):
        raise ValueError("bad credential status %r" % (status,))
    rec, _ = _read(name, h)
    if rec is None:
        return False
    if status == "ok":
        rec.pop("mark", None)
    else:
        rec["mark"] = {"status": status, "note": note,
                       "at": _now().isoformat(timespec="seconds")}
    _write(name, rec, h)
    return True


def names(h=None):
    try:
        files = os.listdir(directory(h))
    except FileNotFoundError:
        return []
    return sorted(f[:-5] for f in files if f.endswith(".json") and _NAME.match(f[:-5]))


def rows(h=None):
    """One dict per credential for /sched and doctor: name, subject, status,
    note, expires. Owner-only: the caller shows them only to the home's owner."""
    out = []
    for n in names(h):
        st, note = check(n, h)
        c = get(n, h)
        out.append({"name": n, "status": st, "note": note,
                    "subject": c.subject if c else None,
                    "expires": c.expires if c else None})
    return out


class Watcher:
    """An mtime poll of the credentials directory. ``poll()`` calls each
    callback with the sorted names that were added, changed or removed since
    the last poll, and returns them. The first poll only takes a snapshot."""

    def __init__(self, h=None):
        self.h, self.callbacks, self._seen = h, [], None

    def add(self, callback):
        self.callbacks.append(callback)
        return callback

    def _snapshot(self):
        snap = {}
        for n in names(self.h):
            try:
                st = os.stat(_path(n, self.h))
            except OSError:
                continue
            snap[n] = (st.st_mtime_ns, st.st_size, st.st_ino)
        return snap

    def poll(self):
        snap, old = self._snapshot(), self._seen
        self._seen = snap
        if old is None:
            return []
        changed = sorted(n for n in set(snap) | set(old) if snap.get(n) != old.get(n))
        if changed:
            for cb in list(self.callbacks):
                cb(changed)
        return changed


_watcher = None


def watcher(h=None):
    """The process's watcher for home ``h`` (wpkd polls it)."""
    global _watcher
    from . import registry
    h = h or registry.home()
    if _watcher is None or _watcher.h != h:
        _watcher = Watcher(h)
    return _watcher


def watch(callback, h=None):
    """Call ``callback(names)`` when credentials change (wpkd polls)."""
    return watcher(h).add(callback)


def _reset():
    global _watcher
    _watcher = None


__all__ = ["Credential", "STATUSES", "put", "get", "status", "check", "mark", "names",
           "rows", "watch", "watcher", "Watcher", "directory"]
