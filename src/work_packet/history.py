"""The history store: ``.wph`` archives and the database built from them
(docs/work-data-design.md §14).

A run (today's packet directory) is harvested in steps that can each be
repeated: every file of the record goes to the blob store, an archive
``history/<yyyy>/<mm>/<id>.wph`` is written, it is loaded into
``history/history.db`` in one transaction, and the database is checked
against the run. Removing the run is a separate, explicit step; nothing
here deletes anything.

The archives are the truth: ``rebuild()`` makes the database again from
them. A run that is still active can be loaded *provisionally* (metrics
only), and is replaced by its archive when it is harvested.

Every statistic ``stats.packet_steps`` computes is kept per step, exactly,
together with the step's raw ``meta.json`` and its tool-cost attribution,
so ``wpk stats`` and the token dashboard give the same figures from the
history store as from the run.
"""

import dataclasses
import io
import json
import os
import re
import sqlite3
import urllib.parse
import zipfile

from . import blobs, clock, fsutil, schema, stats
from .packet import Packet

SCHEMA_VERSION = 1
ARCHIVE_VERSION = 1

TIERS = ("metrics", "narrative", "changes", "transcripts", "logs", "deliverables")
SKIP_TOP = {"work"}                  # the workspaces: not part of the record
SKIP_DIRS = {".git", "__pycache__"}  # at any depth
SKIP_FILES = {".lease"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS packet (
    id TEXT PRIMARY KEY, name TEXT, title TEXT, project TEXT, parent TEXT, root TEXT,
    card_state TEXT, run_state TEXT, created TEXT, updated TEXT, card_sha TEXT,
    archive TEXT, harvested TEXT, provisional INTEGER NOT NULL DEFAULT 0,
    status TEXT);
CREATE TABLE IF NOT EXISTS step (
    packet TEXT NOT NULL, folder TEXT NOT NULL, project TEXT, step INTEGER,
    attempt INTEGER, failed INTEGER, harness TEXT, model TEXT, profile TEXT,
    cost REAL, input_tokens INTEGER, cache_write INTEGER, cache_read INTEGER,
    output_tokens INTEGER, thinking_tokens INTEGER, duration_s REAL, api_s REAL,
    start TEXT, "end" TEXT, stats TEXT NOT NULL, meta TEXT, tools TEXT,
    provisional INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (packet, folder));
CREATE TABLE IF NOT EXISTS file (
    packet TEXT NOT NULL, path TEXT NOT NULL, sha TEXT NOT NULL, size INTEGER,
    tier TEXT, PRIMARY KEY (packet, path));
CREATE TABLE IF NOT EXISTS task (
    packet TEXT NOT NULL, n INTEGER NOT NULL, instruction TEXT, start TEXT, "end" TEXT,
    outcome TEXT, PRIMARY KEY (packet, n));
CREATE TABLE IF NOT EXISTS question (
    packet TEXT NOT NULL, qid TEXT NOT NULL, asked TEXT, answered TEXT, answer TEXT,
    PRIMARY KEY (packet, qid, asked));
CREATE TABLE IF NOT EXISTS edge (parent TEXT, child TEXT, name TEXT,
    PRIMARY KEY (parent, child));
CREATE TABLE IF NOT EXISTS tag (packet TEXT, tag TEXT, PRIMARY KEY (packet, tag));
CREATE TABLE IF NOT EXISTS job (
    packet TEXT, id TEXT, step INTEGER, command TEXT, directory TEXT, start TEXT,
    "end" TEXT, exit INTEGER, batch_id TEXT, scheduler TEXT, log_blob TEXT,
    summary_blob TEXT, PRIMARY KEY (packet, id));
CREATE TABLE IF NOT EXISTS call (
    packet TEXT, t TEXT, kind TEXT, model TEXT, tokens TEXT, cost REAL);
CREATE INDEX IF NOT EXISTS step_project ON step (project);
"""


class HarvestError(Exception):
    pass


# --- places ----------------------------------------------------------------------

def root(h=None):
    from . import registry
    return os.path.join(h or registry.home(), "history")


def db_path(h=None):
    return os.path.join(root(h), "history.db")


def connect(h=None, path=None):
    path = path or db_path(h)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
    con.commit()
    return con


def tier_of(rel):
    base = os.path.basename(rel)
    if base in ("transcript.jsonl", "stderr.log"):
        return "transcripts"
    if base.endswith(".diff"):
        return "changes"
    if base in ("meta.json", "ctxhook.fired", "notes.seen"):
        return "metrics"
    if base in ("log", "progress.jsonl") and "/jobs/" in "/" + rel:
        return "logs"
    return "narrative"


# --- reading a run ---------------------------------------------------------------

def _step_json(s):
    d = dataclasses.asdict(s)
    d.pop("dir", None)
    d.pop("tools", None)
    d["hook"] = list(d["hook"])
    return d


def _step_from(d, tools=None):
    d = dict(d)
    d["hook"] = tuple(d.get("hook") or ())
    return stats.Step(dir=None, tools=tools, **d)


def _files(run_dir):
    out = []
    for dp, dns, fns in os.walk(run_dir):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS
                        and not (dp == run_dir and d in SKIP_TOP)
                        and not os.path.islink(os.path.join(dp, d)))
        for f in sorted(fns):
            p = os.path.join(dp, f)
            if f in SKIP_FILES or os.path.islink(p) or not os.path.isfile(p):
                continue
            out.append(os.path.relpath(p, run_dir))
    return out


LINK = re.compile(r"\]\(\s*<?([^)\s>]+)")
LINKED_MAX = 10 << 20


def _under(run_dir, r):
    p = os.path.join(run_dir, r)
    return (".git" not in r.split(os.sep) and not os.path.islink(p)
            and os.path.realpath(p).startswith(os.path.realpath(run_dir) + os.sep))


def _linked_work(run_dir, rels):
    """Files under ``work/`` that the record's reports list as deliverables
    (the dashboard serves only those), so they can still be opened once the
    workspace is gone: each listed file; a listed folder whole when it holds
    at most ``LINKED_MAX`` bytes, otherwise the files in it that the reports
    link to."""
    from . import report as report_mod
    reps = [r for r in rels if r == report_mod.NAME
            or (r.startswith(os.path.join("state", "history", "report-")) and r.endswith(".md"))]
    tops, texts = set(), []
    for r in reps:
        rep = report_mod.load(os.path.join(run_dir, r))
        if not rep:
            continue
        texts.append(rep[1])
        for d in rep[0].get("deliverables") or ():
            top = os.path.normpath(str((d or {}).get("path") or ""))
            if top.split(os.sep)[0] == "work" and _under(run_dir, top):
                tops.add(top)
    out = set()
    for top in sorted(tops):
        p = os.path.join(run_dir, top)
        if os.path.isfile(p):
            if os.path.getsize(p) <= LINKED_MAX:
                out.add(top)
            continue
        if not os.path.isdir(p):
            continue
        found, total = [], 0
        for dp, dns, fns in os.walk(p):
            dns[:] = sorted(x for x in dns if x not in SKIP_DIRS
                            and not os.path.islink(os.path.join(dp, x)))
            for f in sorted(fns):
                fp = os.path.join(dp, f)
                if os.path.isfile(fp) and not os.path.islink(fp):
                    found.append(os.path.relpath(fp, run_dir))
                    total += os.path.getsize(fp)
            if total > LINKED_MAX:
                break
        if total <= LINKED_MAX:
            out.update(found)
            continue
        for text in texts:
            for target in LINK.findall(text):
                target = urllib.parse.unquote(target.partition("#")[0])
                r = os.path.normpath(target)
                if (r.startswith(top + os.sep) and _under(run_dir, r)
                        and os.path.isfile(os.path.join(run_dir, r))
                        and os.path.getsize(os.path.join(run_dir, r)) <= LINKED_MAX):
                    out.add(r)
    return sorted(out)


def _journal(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fp:
            for ln in fp:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def _tasks_and_questions(recs):
    """Tasks (one per batch) and questions, from the journal."""
    tasks, questions = [], []
    cur = None
    asked_at = None
    for r in recs:
        t = r.get("type")
        if t == "step-start" and cur is None:
            cur = {"n": 1, "instruction": None, "start": r["t"], "end": None, "outcome": None}
        elif t == "handoff" and r.get("instruction"):
            cur = {"n": r.get("batch") or len(tasks) + 1, "instruction": r["instruction"],
                   "start": r["t"], "end": None, "outcome": None}
        elif t == "commit-begin":
            d = r.get("decision") or {}
            if d.get("state") == "NEEDS_INPUT":
                asked_at = r["t"]
            if d.get("state") == "COMPLETED" and cur is not None:
                cur["end"], cur["outcome"] = r["t"], "done"
                tasks.append(cur)
                cur = None
        if t == "handoff" and r.get("questions"):
            ans = r.get("answers") or {}
            for q in r["questions"]:
                qid = q.get("id") or "q"
                questions.append({"qid": qid, "asked": asked_at or r["t"], "answered": r["t"],
                                  "answer": ans.get(qid)})
    if cur is not None:
        tasks.append(cur)
    return tasks, questions


def read_run(project, run_dir, with_files=True, h=None):
    """Everything the history store keeps of one run, as a dict. With
    ``with_files``, every file of the record is put in the blob store."""
    pkt = Packet(run_dir)
    try:
        status, summary = pkt.load_status()
    except Exception:
        status, summary = {}, ""
    steps = []
    for s in stats.packet_steps(project, pkt):
        tools = None
        if s.harness == "claude" and s.dir:
            try:
                from . import toolcost
                tools = toolcost.of_step(s.dir)
            except Exception:
                tools = None
        try:
            with open(os.path.join(s.dir, "meta.json"), encoding="utf-8") as fp:
                meta = json.load(fp)
        except (OSError, ValueError):
            meta = None
        steps.append({"folder": os.path.basename(s.dir), "stats": _step_json(s),
                      "meta": meta, "tools": tools})
    recs = _journal(pkt.journal_path)
    tasks, questions = _tasks_and_questions(recs)
    files = {}
    if with_files:
        rels = _files(run_dir)
        for rel in rels:
            p = os.path.join(run_dir, rel)
            files[rel] = {"sha": blobs.put_file(p, h), "size": os.path.getsize(p),
                          "tier": tier_of(rel)}
        for rel in _linked_work(run_dir, rels):
            p = os.path.join(run_dir, rel)
            files[rel] = {"sha": blobs.put_file(p, h), "size": os.path.getsize(p),
                          "tier": "deliverables"}
    wpid = os.path.basename(os.path.normpath(run_dir))
    return {
        "id": wpid, "project": project, "parent": status.get("parent"),
        "children": list(status.get("children") or []),
        "run_state": status.get("state"), "status": status, "summary": summary,
        "created": recs[0]["t"] if recs else None,
        "updated": status.get("updated"),
        "steps": steps, "tasks": tasks, "questions": questions, "files": files,
    }


# --- archives --------------------------------------------------------------------

def archive_path(rec, h=None):
    t = rec.get("updated") or schema.format_timestamp(clock.now())
    return os.path.join(root(h), t[:4], t[5:7], rec["id"] + ".wph")


def write_archive(rec, card_text=None, h=None, extra=None):
    """Write ``rec``'s archive and return its path. Rewriting gives the same
    content for the same run and card."""
    manifest = {
        "archive": ARCHIVE_VERSION, "id": rec["id"], "project": rec["project"],
        "parent": rec["parent"], "children": rec["children"],
        "run_state": rec["run_state"], "created": rec["created"],
        "updated": rec["updated"],
        "card_sha": (blobs.put_bytes(card_text, h) if card_text else None),
        "files": rec["files"],
    }
    manifest.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def w(name, data):
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
        w("manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
        if card_text:
            w("card.wp.md", card_text)
        w("packet.json", json.dumps({"status": rec["status"], "summary": rec["summary"],
                                     "tasks": rec["tasks"], "questions": rec["questions"]},
                                    indent=1, sort_keys=True))
        # Key order is kept: outputs built from these dicts must match the run's.
        w("metrics.jsonl", "".join(json.dumps(s) + "\n" for s in rec["steps"]))
        w("narrative.jsonl", "".join(
            json.dumps({"path": p, "sha": f["sha"], "tier": f["tier"]}, sort_keys=True) + "\n"
            for p, f in sorted(rec["files"].items()) if f["tier"] == "narrative"))
    path = archive_path(rec, h)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsutil.atomic_write(path, buf.getvalue())
    return path


def read_archive(path):
    """The record (as ``read_run`` returns it) and card text from an archive."""
    with zipfile.ZipFile(path) as z:
        m = json.loads(z.read("manifest.json"))
        p = json.loads(z.read("packet.json"))
        steps = [json.loads(ln) for ln in z.read("metrics.jsonl").decode().splitlines() if ln]
        card_text = z.read("card.wp.md").decode() if "card.wp.md" in z.namelist() else None
    rec = {"id": m["id"], "project": m["project"], "parent": m["parent"],
           "children": m["children"], "run_state": m["run_state"],
           "created": m["created"], "updated": m["updated"], "files": m["files"],
           "status": p["status"], "summary": p["summary"], "tasks": p["tasks"],
           "questions": p["questions"], "steps": steps}
    return rec, card_text, m


# --- the database ----------------------------------------------------------------

def load(con, rec, card_text=None, archive=None, provisional=False):
    """Replace ``rec``'s rows in the database, in one transaction."""
    from . import card as cardmod
    c = cardmod.parse(card_text) if card_text else None
    pid = rec["id"]
    with con:
        for t in ("step", "file", "task", "question", "tag"):
            con.execute("DELETE FROM %s WHERE packet = ?" % t, (pid,))
        con.execute("DELETE FROM edge WHERE parent = ?", (pid,))
        con.execute(
            "INSERT OR REPLACE INTO packet VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, c.name if c else None, c.title if c else None, rec["project"],
             rec["parent"], (c.meta.get("x-wpk") or {}).get("root") if c else None,
             c.state() if c else None, rec["run_state"], rec["created"], rec["updated"],
             cardmod.sha(c) if c else None, archive,
             schema.format_timestamp(clock.now()) if archive and not provisional else None,
             1 if provisional else 0, json.dumps(rec["status"], sort_keys=True)))
        for s in rec["steps"]:
            st = s["stats"]
            con.execute(
                "INSERT INTO step VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, s["folder"], st["project"], st["step"], st["attempt"],
                 1 if st["failed"] else 0, st["harness"], st["model"], st["profile"],
                 st["cost"], st["input_tokens"], st["cache_write"], st["cache_read"],
                 st["output_tokens"], st["thinking_tokens"], st["duration_s"], st["api_s"],
                 (s.get("meta") or {}).get("start"), st["end"],
                 json.dumps(st),
                 json.dumps(s["meta"]) if s.get("meta") is not None else None,
                 json.dumps(s["tools"]) if s.get("tools") is not None else None,
                 1 if provisional else 0))
        for path, f in rec["files"].items():
            con.execute("INSERT INTO file VALUES (?,?,?,?,?)",
                        (pid, path, f["sha"], f["size"], f["tier"]))
        for t in rec["tasks"]:
            con.execute("INSERT OR REPLACE INTO task VALUES (?,?,?,?,?,?)",
                        (pid, t["n"], t["instruction"], t["start"], t["end"], t["outcome"]))
        for q in rec["questions"]:
            con.execute("INSERT OR REPLACE INTO question VALUES (?,?,?,?,?)",
                        (pid, q["qid"], q["asked"], q["answered"], q["answer"]))
        for ch in rec["children"]:
            con.execute("INSERT OR REPLACE INTO edge VALUES (?,?,?)", (pid, ch, None))
        for tg in (c.meta.get("tags") or []) if c else []:
            con.execute("INSERT OR REPLACE INTO tag VALUES (?,?)", (pid, str(tg)))


def load_archive(con, path):
    rec, card_text, _ = read_archive(path)
    load(con, rec, card_text, archive=os.path.abspath(path))
    return rec


def rebuild(h=None):
    """Make the database again from the archives. Provisional rows (from
    active runs) are not in archives; ``sync`` adds them back."""
    path = db_path(h)
    tmp = path + ".rebuild"
    for p in (tmp, tmp + "-wal", tmp + "-shm"):
        if os.path.exists(p):
            os.unlink(p)
    con = connect(path=tmp)
    n = 0
    for dp, _, fns in sorted(os.walk(root(h))):
        for f in sorted(fns):
            if f.endswith(".wph"):
                load_archive(con, os.path.join(dp, f))
                n += 1
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    os.replace(tmp, path)
    for p in (path + "-wal", path + "-shm"):
        if os.path.exists(p):
            os.unlink(p)
    return n


# --- harvest ---------------------------------------------------------------------

def harvest(project, run_dir, card_text=None, h=None, con=None):
    """Steps 2-4 of §14.2 for one run: archive, load, verify. Returns the
    archive's path. Raises HarvestError if the database does not match the
    run. The run is left where it is."""
    rec = read_run(project, run_dir, with_files=True, h=h)
    path = write_archive(rec, card_text, h)
    own = con is None
    con = con or connect(h)
    try:
        load_archive(con, path)
        problems = verify_run(con, project, run_dir, h=h)
        if problems:
            raise HarvestError("%s: %s" % (rec["id"], "; ".join(problems[:5])))
    finally:
        if own:
            con.close()
    return path


def sync(project, run_dir, card_text=None, h=None, con=None, replace=False):
    """Load an active run's metrics provisionally (no archive, no blobs).
    A harvested run is left alone unless ``replace`` (it was resumed: its
    rows become provisional again until it is harvested anew)."""
    rec = read_run(project, run_dir, with_files=False, h=h)
    own = con is None
    con = con or connect(h)
    try:
        row = con.execute("SELECT provisional FROM packet WHERE id = ?", (rec["id"],)).fetchone()
        if row is not None and row[0] == 0 and not replace:
            return False        # harvested: the archive wins
        load(con, rec, card_text, provisional=True)
    finally:
        if own:
            con.close()
    return True


# --- reading back ----------------------------------------------------------------

def steps(con, project=None, packet=None, since=None):
    """``stats.Step`` objects from the database, in the order ``stats.collect``
    produces them (packet id, then step folder)."""
    q, a = "SELECT stats, tools FROM step", []
    w = []
    if project is not None:
        w.append("project = ?")
        a.append(project)
    if packet is not None:
        w.append("packet = ?")
        a.append(packet)
    if w:
        q += " WHERE " + " AND ".join(w)
    q += " ORDER BY packet, folder"
    out = []
    for st, tools in con.execute(q, a):
        s = _step_from(json.loads(st), json.loads(tools) if tools else None)
        if not since or (s.end or "") >= since:
            out.append(s)
    return out


def collect(names, since=None, h=None, con=None):
    """``stats.collect`` from the history store, for projects ``names``."""
    own = con is None
    con = con or connect(h)
    try:
        all_steps, finished = [], []
        for name in names:
            ids = [r[0] for r in con.execute(
                "SELECT id FROM packet WHERE project = ? ORDER BY id", (name,))]
            for pid in ids:
                ss = steps(con, packet=pid, since=since)
                all_steps += ss
                st = con.execute("SELECT run_state FROM packet WHERE id = ?", (pid,)).fetchone()[0]
                done = [s for s in ss if not s.failed]
                if st == "COMPLETED" and done:
                    finished.append((done[-1].key, len(done), sum(s.cost or 0 for s in done)))
        return all_steps, finished
    finally:
        if own:
            con.close()


def projects(con):
    return [r[0] for r in con.execute("SELECT DISTINCT project FROM packet ORDER BY project")]


# --- restoring a record ----------------------------------------------------------

def harvested(con, project):
    """The ids of ``project``'s harvested packets, in order."""
    return [r[0] for r in con.execute(
        "SELECT id FROM packet WHERE project = ? AND harvested IS NOT NULL"
        " AND provisional = 0 ORDER BY id", (project,))]


def restore_packet(con, pid, dest, h=None):
    """Write packet ``pid``'s record (every file but ``work/``) to the run
    directory ``dest``, from the blob store, read-only. Symlinks (the
    ``children/`` links of older runs) are not kept; the edges record the
    same thing. Returns the number of files written."""
    n = 0
    for rel, sha, size in con.execute(
            "SELECT path, sha, size FROM file WHERE packet = ? ORDER BY path", (pid,)):
        data = blobs.get_bytes(sha, h)
        if len(data) != size:
            raise IOError("blob %s of %s/%s has %d bytes, expected %d"
                          % (sha, pid, rel, len(data), size))
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fp:
            fp.write(data)
        os.chmod(p, 0o444)
        n += 1
    return n


def restore_project(con, project, dest, h=None):
    """Write the records of ``project``'s harvested packets under
    ``dest/packets/<id>/``. Returns the ids restored."""
    ids = harvested(con, project)
    for pid in ids:
        restore_packet(con, pid, os.path.join(dest, "packets", pid), h)
    return ids


# --- verification ----------------------------------------------------------------

def _cmp_steps(a, b, where):
    probs = []
    if len(a) != len(b):
        probs.append("%s: %d steps in the run, %d in history" % (where, len(a), len(b)))
    for x, y in zip(a, b):
        dx, dy = _step_json(x), _step_json(y)
        if dx != dy:
            diff = sorted(k for k in dx if dx.get(k) != dy.get(k))
            probs.append("%s step %s: %s differ" % (where, x.step, ", ".join(diff)))
    return probs


def verify_run(con, project, run_dir, h=None, files=True):
    """Differences between a run and its rows (and blobs) in the database."""
    pkt = Packet(run_dir)
    pid = os.path.basename(os.path.normpath(run_dir))
    probs = _cmp_steps(stats.packet_steps(project, pkt), steps(con, packet=pid), pid)
    if files:
        have = dict(con.execute("SELECT path, sha FROM file WHERE packet = ?", (pid,)))
        if have:
            for rel in _files(run_dir):
                if rel not in have:
                    probs.append("%s: %s not in history" % (pid, rel))
                elif not blobs.has(have[rel], h):
                    probs.append("%s: blob of %s missing" % (pid, rel))
    return probs


def verify_project(con, name, path, h=None):
    """Compare every statistic of a project as ``stats`` computes it from its
    runs with the same from the history store. [] when they are identical."""
    a_steps, a_fin = stats.collect([(name, path)])
    b_steps, b_fin = collect([name], con=con)
    probs = _cmp_steps(a_steps, b_steps, name)
    if sorted(a_fin) != sorted(b_fin):
        probs.append("%s: finished packets differ: %r vs %r" % (name, a_fin, b_fin))
    from . import toolcost
    for x, y in zip(a_steps, b_steps):
        tx = toolcost.of_step(x.dir) if x.dir and x.harness == "claude" else None
        if tx != y.tools:
            probs.append("%s step %s: tool cost differs" % (name, x.step))
    return probs


def figures(steps_):
    """Totals people check: steps, tokens by kind, cost, time."""
    def tot(k):
        return sum(getattr(s, k) or 0 for s in steps_)
    return {"steps": len(steps_), "committed": sum(1 for s in steps_ if not s.failed),
            "cost_usd": round(tot("cost"), 6), "input": tot("input_tokens"),
            "cache_write": tot("cache_write"), "cache_read": tot("cache_read"),
            "output": tot("output_tokens"), "thinking": tot("thinking_tokens"),
            "duration_s": round(tot("duration_s"), 3)}
