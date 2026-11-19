"""Every session's tokens in one place (docs/token-ledger.md).

SQLite at ``$WPK_HOME/usage/ledger.db``, kept by wpkd and never inside a packet,
so cost outlives the packets and the transcripts it came from (§2.3):

- ``usage``: tokens by hour, session and model. ``origin`` says where a bucket
  came from: ``transcript`` (the collector, ledger_collect.py) or ``store``
  (``usage/sessions/*.json``, which hosts that share ``$WPK_HOME`` write). For
  one session and hour, transcript rows win.
- ``seen``: the replies already counted, so each is counted once (§5.1).
- ``session``: who and what a session was, and by which rule (§4). Board,
  project and packet names are copied in, so a row reads the same after the
  packet is gone.
- ``step``: one row per runner step attempt, the step's own figures from its
  ``meta.json`` (cost, tokens, quota).
- ``packet``: the packets synced, their names, and whether they are gone.
- ``cursor``: read position per transcript or store file.

Only ids, times, models, cwds and counts: no prompt or reply text.
"""

import json
import os
import socket
import sqlite3

KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
        "cache_creation_1h_input_tokens", "cache_read_input_tokens")
STEP_KEYS = KEYS + ("thinking_tokens",)

_COLS = ", ".join("%s INTEGER NOT NULL DEFAULT 0" % k for k in KEYS)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS usage (
  hour INTEGER NOT NULL, harness TEXT NOT NULL, session TEXT NOT NULL,
  model TEXT NOT NULL, host TEXT NOT NULL, origin TEXT NOT NULL,
  replies INTEGER NOT NULL DEFAULT 0, %(cols)s,
  PRIMARY KEY (hour, harness, session, model, host, origin));
CREATE INDEX IF NOT EXISTS usage_session ON usage(harness, session);
CREATE TABLE IF NOT EXISTS seen (
  harness TEXT NOT NULL, msg TEXT NOT NULL, hour INTEGER, session TEXT, model TEXT,
  host TEXT, %(cols)s, PRIMARY KEY (harness, msg));
CREATE INDEX IF NOT EXISTS seen_hour ON seen(hour);
CREATE TABLE IF NOT EXISTS cursor (path TEXT PRIMARY KEY, dev INTEGER, ino INTEGER,
  size INTEGER, mtime INTEGER, offset INTEGER, session TEXT);
CREATE TABLE IF NOT EXISTS session (
  harness TEXT NOT NULL, session TEXT NOT NULL, source TEXT, client TEXT, how TEXT,
  board TEXT, project TEXT, wpid TEXT, packet_name TEXT, step INTEGER, purpose TEXT,
  cwd TEXT, entrypoint TEXT, user TEXT, host TEXT, first_t REAL, last_t REAL,
  PRIMARY KEY (harness, session));
CREATE TABLE IF NOT EXISTS step (
  project TEXT NOT NULL, wpid TEXT NOT NULL, step INTEGER NOT NULL,
  failed INTEGER NOT NULL, attempt INTEGER NOT NULL, session TEXT,
  board TEXT, packet_name TEXT, harness TEXT, profile TEXT, model TEXT, worker TEXT,
  item TEXT, start TEXT, "end" TEXT, cost_usd REAL, cost_basis TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cache_creation_input_tokens INTEGER,
  cache_creation_1h_input_tokens INTEGER, cache_read_input_tokens INTEGER,
  thinking_tokens INTEGER, duration_s REAL, quota TEXT,
  PRIMARY KEY (project, wpid, step, failed, attempt));
CREATE INDEX IF NOT EXISTS step_end ON step("end");
CREATE TABLE IF NOT EXISTS thread (
  harness TEXT NOT NULL, thread TEXT NOT NULL, session TEXT, model TEXT, src TEXT,
  %(cols)s, PRIMARY KEY (harness, thread));
CREATE TABLE IF NOT EXISTS packet (
  project TEXT NOT NULL, wpid TEXT NOT NULL, board TEXT, name TEXT, sig TEXT,
  gone INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (project, wpid));
""" % {"cols": _COLS}

# How a session was attributed, strongest first (docs/token-ledger.md §4). A
# weaker rule never overwrites a stronger one.
HOW = ("runner", "model-call", "console", "store", "env", "runner-cwd", "cwd-packet",
       "cwd-project", "none")
SOURCES = ("runner", "interactive", "model-call", "console", "studio")


def db_path(home):
    return os.path.join(home, "usage", "ledger.db")


def connect(home=None, path=None):
    from . import registry
    path = path or db_path(home or registry.home())
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    return con


def reader(home):
    """A read-only connection to the ledger, or None when there is none yet. Page
    handlers read through this: a GET never writes (the collector does)."""
    path = db_path(home)
    if not os.path.isfile(path):
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=30)
    except sqlite3.Error:
        return None


def host():
    return socket.gethostname()


def hour_of(t):
    return int(t) // 3600 * 3600


def clean(u):
    """``u`` with only the ledger's keys, as non-negative ints."""
    return {k: int(u[k]) for k in KEYS if isinstance((u or {}).get(k), int)
            and not isinstance(u[k], bool) and u[k] > 0}


def _bump(con, key, u, replies):
    """Add ``u`` (may be negative) and ``replies`` to the bucket ``key``."""
    vals = [u.get(k, 0) for k in KEYS]
    con.execute(
        "INSERT INTO usage (hour, harness, session, model, host, origin, replies, %s) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, %s) ON CONFLICT DO UPDATE SET replies = replies + "
        "excluded.replies, %s" % (", ".join(KEYS), ", ".join("?" * len(KEYS)),
                                  ", ".join("%s = %s + excluded.%s" % (k, k, k) for k in KEYS)),
        list(key) + [replies] + vals)


def add_reply(con, harness, session, msg, t, model, usage, where=None):
    """Count one reply. A reply already counted (a streamed revision, or a copy in
    a resumed or forked session) replaces its earlier figures in the bucket that
    first counted it. Returns True when it was new."""
    u = clean(usage)
    if not msg or not u:
        return False
    where = where or host()
    old = con.execute("SELECT hour, session, model, host, %s FROM seen WHERE harness = ? "
                      "AND msg = ?" % ", ".join(KEYS), (harness, msg)).fetchone()
    if old is None:
        hour = hour_of(t)
        con.execute("INSERT INTO seen (harness, msg, hour, session, model, host, %s) "
                    "VALUES (?, ?, ?, ?, ?, ?, %s)" % (", ".join(KEYS), ", ".join("?" * len(KEYS))),
                    [harness, msg, hour, session, model, where] + [u.get(k, 0) for k in KEYS])
        _bump(con, (hour, harness, session, model, where, "transcript"), u, 1)
        return True
    was = dict(zip(KEYS, old[4:]))
    delta = {k: u.get(k, 0) - was[k] for k in KEYS}
    if any(delta.values()):
        con.execute("UPDATE seen SET %s WHERE harness = ? AND msg = ?" %
                    ", ".join("%s = ?" % k for k in KEYS),
                    [u.get(k, 0) for k in KEYS] + [harness, msg])
        _bump(con, (old[0], harness, old[1], old[2], old[3], "transcript"), delta, 0)
    return False


def thread(con, harness, tid):
    """A Codex thread's row: ``{"session", "model", "src"}`` and its largest
    cumulative usage so far, or None."""
    row = con.execute("SELECT session, model, src, %s FROM thread WHERE harness = ? AND "
                      "thread = ?" % ", ".join(KEYS), (harness, tid)).fetchone()
    return dict(zip(("session", "model", "src") + KEYS, row)) if row else None


def note_thread(con, harness, tid, **f):
    """Create a thread's row, or set ``f`` (``session``, ``model``) on it."""
    if thread(con, harness, tid) is None:
        con.execute("INSERT INTO thread (harness, thread) VALUES (?, ?)", (harness, tid))
    for k in ("session", "model"):
        if f.get(k):
            con.execute("UPDATE thread SET %s = ? WHERE harness = ? AND thread = ?" % k,
                        (f[k], harness, tid))


def add_snapshot(con, harness, tid, t, usage, src, where=None):
    """Count a cumulative usage snapshot (Codex) of thread ``tid``: what it adds
    above the thread's largest so far goes to this hour, its session and its
    model. A snapshot read again (a re-read, a copied rollout) adds nothing.
    ``src`` is ``thread`` or ``token_count``, two totals of the same thing; once
    a thread has a ``thread`` one, ``token_count`` ones are ignored (as
    ``ide_sessions`` does). Returns True if it added."""
    th = thread(con, harness, tid)
    u = clean(usage)
    if th is None or not u or (src == "token_count" and th["src"] == "thread"):
        return False
    delta = {k: u.get(k, 0) - (th[k] or 0) for k in KEYS}
    delta = {k: v for k, v in delta.items() if v > 0}
    con.execute("UPDATE thread SET src = ?, %s WHERE harness = ? AND thread = ?"
                % ", ".join("%s = MAX(%s, ?)" % (k, k) for k in KEYS),
                [src] + [u.get(k, 0) for k in KEYS] + [harness, tid])
    if not delta:
        return False
    _bump(con, (hour_of(t), harness, th["session"] or tid, th["model"] or "unknown",
                where or host(), "transcript"), delta, 1)
    return True


def prune_seen(con, before):
    """Forget replies older than ``before`` (§5.1: one that old is not resumed)."""
    con.execute("DELETE FROM seen WHERE hour < ?", (hour_of(before),))


# --- sessions ------------------------------------------------------------------------

_SESSION_FIELDS = ("source", "client", "how", "board", "project", "wpid", "packet_name",
                   "step", "purpose", "cwd", "entrypoint", "user", "host")


def session(con, harness, sid):
    row = con.execute("SELECT %s, first_t, last_t FROM session WHERE harness = ? AND "
                      "session = ?" % ", ".join(_SESSION_FIELDS), (harness, sid)).fetchone()
    return dict(zip(_SESSION_FIELDS + ("first_t", "last_t"), row)) if row else None


def _rank(how):
    return HOW.index(how) if how in HOW else len(HOW)


def note_session(con, harness, sid, how=None, t=None, **f):
    """Create or update a session's row. Attribution fields (``how`` and the
    ones that come with it) are taken only when ``how`` is as strong as what the
    row has; the rest (cwd, entrypoint, times) fill in what is missing."""
    cur = session(con, harness, sid)
    if cur is None:
        row = dict.fromkeys(_SESSION_FIELDS)
        row.update(how="none", source="interactive", host=host())
        row.update({k: v for k, v in f.items() if k in _SESSION_FIELDS and v is not None})
        if how:
            row["how"] = how
        con.execute("INSERT INTO session (harness, session, %s, first_t, last_t) VALUES "
                    "(?, ?, %s, ?, ?)" % (", ".join(_SESSION_FIELDS),
                                         ", ".join("?" * len(_SESSION_FIELDS))),
                    [harness, sid] + [row[k] for k in _SESSION_FIELDS] + [t, t])
        return True
    upd = {}
    if how and _rank(how) <= _rank(cur["how"]):
        upd = {k: f.get(k) for k in ("source", "client", "board", "project", "wpid",
                                     "packet_name", "step", "purpose") if k in f}
        upd["how"] = how
    for k in ("cwd", "entrypoint", "user", "client", "purpose"):
        if cur.get(k) is None and f.get(k) is not None and k not in upd:
            upd[k] = f[k]
    sets, args = [], []
    for k, v in upd.items():
        if cur.get(k) != v:
            sets.append("%s = ?" % k)
            args.append(v)
    if t is not None:
        sets.append("first_t = MIN(COALESCE(first_t, ?), ?)")
        sets.append("last_t = MAX(COALESCE(last_t, ?), ?)")
        args += [t, t, t, t]
    if sets:
        con.execute("UPDATE session SET %s WHERE harness = ? AND session = ?" % ", ".join(sets),
                    args + [harness, sid])
    return bool(upd)


# --- steps and packets ----------------------------------------------------------------

def put_step(con, s, board=None, packet_name=None, session_id=None, start=None):
    """Store one runner step (a ``stats.Step``)."""
    con.execute(
        "INSERT OR REPLACE INTO step (project, wpid, step, failed, attempt, session, board, "
        "packet_name, harness, profile, model, worker, item, start, \"end\", cost_usd, "
        "cost_basis, input_tokens, output_tokens, cache_creation_input_tokens, "
        "cache_creation_1h_input_tokens, cache_read_input_tokens, thinking_tokens, "
        "duration_s, quota) VALUES (%s)" % ", ".join("?" * 25),
        (s.project, s.wpid, s.step, int(bool(s.failed)), s.attempt or 0, session_id, board,
         packet_name, s.harness, s.profile, s.model, s.worker, s.item, start, s.end, s.cost,
         s.basis, s.input_tokens, s.output_tokens, s.cache_write, None, s.cache_read,
         s.thinking_tokens, s.duration_s, json.dumps(s.quota) if s.quota else None))


def steps(con, project=None, since=None, gone_only=False, wpids=None):
    """``stats.Step``s from the ledger, of ``project`` and ending at or after
    ``since`` (a timestamp string). ``gone_only``: only packets that are gone.
    Each carries ``packet_name`` and ``board`` as attributes."""
    from .stats import Step
    q = ["SELECT s.project, s.wpid, s.step, s.failed, s.attempt, s.harness, s.model, "
         "s.profile, s.worker, s.item, s.\"end\", s.cost_usd, s.cost_basis, s.input_tokens, "
         "s.output_tokens, s.cache_creation_input_tokens, s.cache_read_input_tokens, "
         "s.thinking_tokens, s.duration_s, s.quota, COALESCE(s.packet_name, p.name), "
         "COALESCE(s.board, p.board) FROM step s LEFT JOIN packet p "
         "ON p.project = s.project AND p.wpid = s.wpid WHERE 1"]
    args = []
    if project is not None:
        q.append("AND s.project = ?")
        args.append(project)
    if since:
        q.append("AND s.\"end\" >= ?")
        args.append(since)
    if gone_only:
        q.append("AND p.gone = 1")
    out = []
    for r in con.execute(" ".join(q), args):
        if wpids is not None and r[1] not in wpids:
            continue
        s = Step(project=r[0], wpid=r[1], step=r[2], failed=bool(r[3]), attempt=r[4] or None,
                 harness=r[5] or "claude", model=r[6] or "?", profile=r[7] or "-",
                 worker=r[8] or "agent", item=r[9], end=r[10], cost=r[11], basis=r[12],
                 input_tokens=r[13], output_tokens=r[14], cache_write=r[15], cache_read=r[16],
                 thinking_tokens=r[17], duration_s=r[18],
                 quota=json.loads(r[19]) if r[19] else None)
        s.packet_name, s.board = r[20], r[21]
        out.append(s)
    return out


def gone_steps(home, project=None, since=None):
    """``steps`` of packets that are gone; [] without a ledger."""
    con = reader(home)
    if con is None:
        return []
    try:
        return steps(con, project, since, gone_only=True)
    finally:
        con.close()


def packet_names(home, project):
    """{wpid: name} of the project's packets the ledger knows; {} without one."""
    con = reader(home)
    if con is None:
        return {}
    try:
        return {w: n for w, n in con.execute(
            "SELECT wpid, name FROM packet WHERE project = ? AND name IS NOT NULL", (project,))}
    finally:
        con.close()


# --- the session store (usage/sessions/*.json) ----------------------------------------

def sync_store(con, home):
    """Bring changed ``usage/sessions/*.json`` files in: their hours as ``store``
    buckets, their binding as the session's attribution (rule 3)."""
    from . import session_usage
    d = session_usage.usage_dir(home)
    try:
        ents = [e for e in os.scandir(d) if e.name.endswith(".json")]
    except OSError:
        return 0
    have = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT path, size, mtime FROM cursor WHERE path LIKE 'store:%'")}
    n = 0
    for e in ents:
        try:
            st = e.stat()
        except OSError:
            continue
        key = "store:" + e.path
        if have.get(key) == (st.st_size, st.st_mtime_ns):
            continue
        r = session_usage._load(e.path)
        if r is None:
            continue
        h, sid = r["harness"], r["session_id"]
        con.execute("DELETE FROM usage WHERE harness = ? AND session = ? AND origin = 'store'",
                    (h, sid))
        where = host()
        for hour, models in r["hours"].items():
            if not int(hour):
                continue
            for m, u in models.items():
                _bump(con, (int(hour), h, sid, m, where, "store"), clean(u), 0)
        ts = [int(x) for x in r["hours"] if int(x)]
        note_session(con, h, sid, how="store" if r.get("project") or r.get("wpid") else None,
                     t=max(ts) if ts else r.get("last_activity_t"), source="interactive",
                     client=r.get("client"), project=r.get("project"), wpid=r.get("wpid"))
        if ts:
            note_session(con, h, sid, t=min(ts))
        con.execute("INSERT OR REPLACE INTO cursor (path, size, mtime) VALUES (?, ?, ?)",
                    (key, st.st_size, st.st_mtime_ns))
        n += 1
    con.commit()
    return n


# --- reading ---------------------------------------------------------------------------

def buckets(home, since=None, until=None, project=None, runner=False):
    """``[(hour_t, model, usage, rec)]``: the sessions' tokens by hour and model in
    ``[since, until)``, optionally of one project. ``rec`` is the session's row
    (``harness``, ``session_id``, ``source``, ``client``, ``project``, ``wpid``,
    ``packet_name``, ``board``, ``attribution``, ``purpose``, ``cwd``). Runner sessions only with
    ``runner`` (their cost is the step's). For a session and hour, the
    transcript's figures win over the store's."""
    con = reader(home)
    stale = _stale_store(con, home)
    rows = []
    try:
        q = ["SELECT u.hour, u.model, u.harness, u.session, u.origin, %s, s.source, s.client, "
             "s.project, s.wpid, s.packet_name, s.board, s.how, s.purpose, s.cwd FROM usage u LEFT "
             "JOIN session s ON s.harness = u.harness AND s.session = u.session WHERE u.hour "
             "> 0" % ", ".join("u." + k for k in KEYS)]
        args = []
        if since is not None:
            q.append("AND u.hour >= ?")
            args.append(hour_of(since))
        if until is not None:
            q.append("AND u.hour < ?")
            args.append(until)
        if project is not None:
            q.append("AND s.project = ?")
            args.append(project)
        if not runner:
            q.append("AND COALESCE(s.source, 'interactive') != 'runner'")
        if con is not None:
            rows = [r for r in con.execute(" ".join(q), args).fetchall()
                    if not (r[4] == "store" and (r[2], r[3]) in stale)]
        for (h, sid), rec in stale.items():
            rows += _store_rows(con, rec, since, until, project, runner)
    finally:
        if con is not None:
            con.close()
    nk = len(KEYS)
    by_transcript = {(r[0], r[2], r[3]) for r in rows if r[4] == "transcript"}
    recs, out = {}, {}
    for r in rows:
        if r[4] == "store" and (r[0], r[2], r[3]) in by_transcript:
            continue
        u = {k: v for k, v in zip(KEYS, r[5:5 + nk]) if v}
        if not u:
            continue
        src, client, proj, wpid, pname, board, how, purpose, cwd = r[5 + nk:]
        key = (r[2], r[3])
        rec = recs.get(key)
        if rec is None:
            rec = recs[key] = {"harness": r[2], "session_id": r[3],
                               "source": src or "interactive", "client": client,
                               "project": proj, "wpid": wpid, "packet_name": pname,
                               "board": board, "attribution": how, "purpose": purpose,
                               "cwd": cwd}
        k = (r[0], r[1], key)
        if k in out:                    # the same hour on two hosts
            got = out[k][2]
            for kk, v in u.items():
                got[kk] = got.get(kk, 0) + v
        else:
            out[k] = (r[0], r[1], u, rec)
    return list(out.values())


def _stale_store(con, home):
    """{(harness, session): record} for store files the collector has not read
    since they last changed (all of them without a ledger)."""
    from . import session_usage
    d = session_usage.usage_dir(home)
    try:
        ents = [e for e in os.scandir(d) if e.name.endswith(".json")]
    except OSError:
        return {}
    have = {} if con is None else {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT path, size, mtime FROM cursor WHERE path LIKE 'store:%'")}
    out = {}
    for e in ents:
        try:
            st = e.stat()
        except OSError:
            continue
        if have.get("store:" + e.path) == (st.st_size, st.st_mtime_ns):
            continue
        r = session_usage._load(e.path)
        if r is not None:
            out[(r["harness"], r["session_id"])] = r
    return out


def _store_rows(con, rec, since, until, project, runner):
    """Rows shaped like ``buckets``' query for one store record not yet in the
    ledger, attributed as the ledger has it or else as the store does."""
    h, sid = rec["harness"], rec["session_id"]
    s = session(con, h, sid) if con is not None else None
    if s is None or (_rank(s["how"]) > _rank("store") and (rec.get("project") or rec.get("wpid"))):
        s = {"source": (s or {}).get("source") or "interactive", "client": rec.get("client"),
             "project": rec.get("project"), "wpid": rec.get("wpid"), "packet_name": None,
             "board": None, "how": "store", "purpose": None, "cwd": (s or {}).get("cwd")}
    if not runner and s["source"] == "runner" or project is not None and s["project"] != project:
        return []
    out = []
    for hour, models in rec["hours"].items():
        t = int(hour)
        if not t or since is not None and t < hour_of(since) or until is not None and t >= until:
            continue
        for m, u in models.items():
            u = clean(u)
            out.append((t, m, h, sid, "store") + tuple(u.get(k, 0) for k in KEYS) +
                       (s["source"], s["client"], s["project"], s["wpid"], s["packet_name"],
                        s["board"], s["how"], s["purpose"], s["cwd"]))
    return out
