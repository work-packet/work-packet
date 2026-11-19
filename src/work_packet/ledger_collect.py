"""Fill the token ledger (docs/token-ledger.md §5): read what is new in every
Claude transcript and Codex rollout, bring in the session store, every packet's
steps and the console's conversations, and attribute each session (§4). ``wpk serve`` runs ``pass_once`` every 30 s;
``wpk usage collect`` runs one.

The first pass on a machine reads every transcript Claude Code still keeps
(about 30 days) and every step ``meta.json``. After that only what changed is
read: a transcript by its cursor, a packet when its journal or step folders
change.
"""

import getpass
import json
import os
import time

from . import ledger

# The opening words of wpk's own model calls (scribe.call_model) made before they
# carried a session id (rule 2a), so their sessions are not taken for people's work.
MODEL_CALL_PROMPTS = (("You keep a work packet's status current", "status"),
                      ("You write the daily focus brief", "brief"))
CLIENT_OF = {"cli": "terminal", "sdk-cli": "sdk", "claude-vscode": "vscode-ext",
             "claude-desktop": "desktop", "codex_cli_rs": "terminal", "codex-tui": "terminal",
             "codex_vscode": "vscode-ext",
             "codex_exec": "sdk"}
RUNNER_ENTRYPOINTS = ("sdk-cli", "codex_exec")     # how the runner starts each harness
SEEN_DAYS = 45


def _user():
    try:
        return getpass.getuser()
    except Exception:                   # noqa: BLE001  no name for this uid
        return None


# --- packets and steps ---------------------------------------------------------------

def _sig(pkt):
    parts = []
    for p in (pkt.journal_path, pkt.steps_dir):
        try:
            st = os.stat(p)
            parts.append("%d:%d" % (st.st_size, st.st_mtime_ns))
        except OSError:
            parts.append("-")
    try:
        for n in sorted(os.listdir(pkt.steps_dir)):
            try:
                parts.append("%d" % os.stat(os.path.join(pkt.steps_dir, n, "meta.json"))
                             .st_mtime_ns)
            except OSError:
                pass
    except OSError:
        pass
    return "|".join(parts)


def _names(name, pkts):
    """{wpid: name}: the root packet takes the project's name, a child the name it
    was spawned under (as the board's tree does)."""
    out = {}
    for pkt in pkts:
        try:
            recs = pkt.journal().records
        except Exception:               # noqa: BLE001  an unreadable journal names nothing
            continue
        for r in recs:
            if r.get("type") == "commit-begin":
                for e in (r.get("decision") or {}).get("spawn") or ():
                    if e.get("wpid") and e.get("name"):
                        out[e["wpid"]] = e["name"]
    for pkt in pkts:
        if pkt.wpid not in out:
            try:
                parent = pkt.load_status()[0].get("parent")
            except Exception:           # noqa: BLE001
                parent = None
            if not parent:
                out[pkt.wpid] = name
    return out


def sync_packets(con, home, stop=None):
    """Bring in the steps of every packet whose journal or steps changed, note
    the session id of each step it started (rule 1), and mark packets that are
    gone. Returns the number of packets read."""
    from . import fsutil, layout, registry, schema, stats
    from .packet import Packet
    n = 0
    for e in registry.entries(home):
        if stop and stop():
            break
        name, board = e["name"], registry.board_of(e)
        pdir = layout.runs_dir(e["path"])
        try:
            wpids = sorted(w for w in os.listdir(pdir) if schema.is_wpid(w))
        except OSError:
            continue                    # archived or unreachable: leave its rows alone
        have = {r[0]: r[1] for r in con.execute(
            "SELECT wpid, sig FROM packet WHERE project = ?", (name,))}
        pkts = {w: Packet(os.path.join(pdir, w)) for w in wpids}
        sigs = {w: _sig(p) for w, p in pkts.items()}
        changed = [w for w in wpids if have.get(w) != sigs[w]]
        gone = set(have) - set(wpids)
        if gone:
            con.executemany("UPDATE packet SET gone = 1 WHERE project = ? AND wpid = ?",
                            [(name, w) for w in gone])
        if not changed:
            con.commit()
            continue
        names = _names(name, list(pkts.values()))
        for w in changed:
            pkt, pname = pkts[w], names.get(w)
            for r in _journal(pkt):
                if r.get("type") == "step-start" and r.get("session_id"):
                    ledger.note_session(con, "claude", r["session_id"], how="runner",
                                        t=_t(r.get("t")), source="runner", board=board,
                                        project=name, wpid=w, packet_name=pname,
                                        step=r.get("step"), client="runner")
            for s in stats.packet_steps(name, pkt):
                try:
                    meta = fsutil.load_json(os.path.join(s.dir, "meta.json"))
                except (OSError, ValueError):
                    meta = {}
                sid = meta.get("session_id")
                ledger.put_step(con, s, board=board, packet_name=pname, session_id=sid,
                                start=meta.get("start"))
                if sid:
                    ledger.note_session(con, meta.get("harness") or "claude", sid,
                                        how="runner", source="runner", board=board,
                                        project=name, wpid=w, packet_name=pname, step=s.step,
                                        client="runner")
            con.execute("INSERT OR REPLACE INTO packet (project, wpid, board, name, sig, gone) "
                        "VALUES (?, ?, ?, ?, ?, 0)", (name, w, board, pname, sigs[w]))
            n += 1
        con.commit()
    return n


def sync_console(con, home):
    """Rule 2: the board console's and the studio's conversations
    (``<home>/console/<id>/meta.json``) each name the session they run in.
    Read when a meta file changes. Returns the number read."""
    from . import registry
    root = os.path.join(home, "console")
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    boards = {e["name"]: registry.board_of(e) for e in registry.entries(home)}
    n = 0
    for name in names:
        path = os.path.join(root, name, "meta.json")
        try:
            st = os.stat(path)
        except OSError:
            continue
        row = con.execute("SELECT mtime FROM cursor WHERE path = ?", (path,)).fetchone()
        if row and row[0] == st.st_mtime_ns:
            continue
        try:
            with open(path) as fp:
                m = json.load(fp)
        except (OSError, ValueError):
            continue
        sid = m.get("session") if isinstance(m, dict) else None
        if isinstance(sid, str) and sid:
            studio = m.get("mode") == "studio"
            got = con.execute("SELECT name FROM packet WHERE wpid = ?",
                              (m.get("wpid"),)).fetchone() if m.get("wpid") else None
            ledger.note_session(con, "claude", sid, how="console",
                                source="studio" if studio else "console", client="wpk",
                                purpose=m.get("mode") or "console", project=m.get("project"),
                                wpid=m.get("wpid"), packet_name=got[0] if got else None,
                                board=boards.get(m.get("project")), cwd=m.get("cwd"))
            n += 1
        con.execute("INSERT OR REPLACE INTO cursor (path, dev, ino, size, mtime, offset) "
                    "VALUES (?, ?, ?, ?, ?, 0)", (path, st.st_dev, st.st_ino, st.st_size,
                                                  st.st_mtime_ns))
    con.commit()
    return n


def _journal(pkt):
    try:
        return pkt.journal().records
    except Exception:                   # noqa: BLE001
        return []


def _t(ts):
    from .ide_sessions import epoch
    return epoch(ts)


# --- transcripts ---------------------------------------------------------------------

def transcript_files(claude_dir):
    root = os.path.join(claude_dir, "projects")
    try:
        dirs = [e.path for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return []
    out = []
    for d in dirs:
        try:
            for e in os.scandir(d):
                if e.name.endswith(".jsonl") and e.is_file():
                    out.append(e.path)
                elif e.is_dir():
                    sub = os.path.join(e.path, "subagents")
                    if os.path.isdir(sub):
                        out += [os.path.join(sub, n) for n in os.listdir(sub)
                                if n.endswith(".jsonl")]
        except OSError:
            continue
    return out


def _usage(msg):
    u = msg.get("usage")
    if not isinstance(u, dict):
        return None
    out = dict(u)
    cc = u.get("cache_creation")
    if isinstance(cc, dict) and isinstance(cc.get("ephemeral_1h_input_tokens"), int):
        out["cache_creation_1h_input_tokens"] = cc["ephemeral_1h_input_tokens"]
    return out


def _purpose(d):
    """A known wpk model-call prompt in a user line, or None."""
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list):
        c = next((b.get("text") for b in c if isinstance(b, dict) and b.get("type") == "text"),
                 None)
    if isinstance(c, str):
        for prefix, purpose in MODEL_CALL_PROMPTS:
            if c.startswith(prefix):
                return purpose
    return None


def read_file(con, path, touched, user=None, stop=None):
    """Count the replies added to one transcript since its cursor. Returns the
    number of new replies."""
    from .ide_sessions import epoch, read_new
    row = con.execute("SELECT dev, ino, size, mtime, offset FROM cursor WHERE path = ?",
                      (path,)).fetchone()
    try:
        st = os.stat(path)
    except OSError:
        return 0
    if row and (row[0], row[1], row[2], row[3]) == (st.st_dev, st.st_ino, st.st_size,
                                                    st.st_mtime_ns):
        return 0
    cur = {"dev": row[0], "ino": row[1], "offset": row[4], "skip": False} if row else None
    n, seen = 0, {}
    while not (stop and stop()):
        try:
            lines, cur, _ = read_new(path, cur)
        except OSError:
            break
        for raw in lines:
            if b'"sessionId"' not in raw:
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            sid = d.get("sessionId")
            if not isinstance(sid, str) or not sid:
                continue
            kind = d.get("type")
            t = epoch(d.get("timestamp"))
            if kind == "user" and sid not in seen:
                p = _purpose(d) if d.get("entrypoint") == "sdk-cli" else None
                if p:
                    ledger.note_session(con, "claude", sid, how="model-call", t=t,
                                        source="model-call", client="wpk", purpose=p)
            if kind != "assistant":
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            model = msg.get("model")
            if not isinstance(model, str) or model == "<synthetic>" or t is None:
                continue
            mid = msg.get("id") or d.get("requestId")
            if not isinstance(mid, str):
                continue
            if ledger.add_reply(con, "claude", sid, mid, t, model, _usage(msg)):
                n += 1
            got = seen.get(sid)
            if got is None:
                seen[sid] = [t, t, d.get("cwd"), d.get("entrypoint")]
            else:
                got[0], got[1] = min(got[0], t), max(got[1], t)
        if cur["offset"] >= os.path.getsize(path) or not lines:
            break
    for sid, (t0, t1, cwd, ent) in seen.items():
        for t in (t0, t1):
            ledger.note_session(con, "claude", sid, t=t, cwd=cwd, entrypoint=ent,
                                client=CLIENT_OF.get(ent, ent), user=user)
        touched.add(("claude", sid))
    con.execute("INSERT OR REPLACE INTO cursor (path, dev, ino, size, mtime, offset) VALUES "
                "(?, ?, ?, ?, ?, ?)", (path, cur["dev"], cur["ino"], st.st_size,
                                       st.st_mtime_ns, cur["offset"]))
    con.commit()
    return n


def codex_files(codex_dir):
    """Every Codex rollout: ``<codex_dir>/sessions/Y/M/D/rollout-*.jsonl``."""
    out = []
    for top, _, names in os.walk(os.path.join(codex_dir, "sessions")):
        out += [os.path.join(top, n) for n in names
                if n.startswith("rollout-") and n.endswith(".jsonl")]
    return out


def read_codex_file(con, path, touched, user=None, stop=None):
    """Count what one Codex rollout added since its cursor. Usage comes as
    cumulative snapshots (``ide_sessions`` module notes); ``ledger.add_snapshot``
    counts the growth. A sub-agent's rollout is its own thread in its root's
    session. Returns the number of snapshots that added."""
    from .ide_sessions import _codex_usage, codex_root, epoch, read_new
    row = con.execute("SELECT dev, ino, size, mtime, offset, session FROM cursor WHERE "
                      "path = ?", (path,)).fetchone()
    try:
        st = os.stat(path)
    except OSError:
        return 0
    if row and (row[0], row[1], row[2], row[3]) == (st.st_dev, st.st_ino, st.st_size,
                                                    st.st_mtime_ns):
        return 0
    cur = {"dev": row[0], "ino": row[1], "offset": row[4], "skip": False} if row else None
    tid = row[5] if row else None
    root = ((ledger.thread(con, "codex", tid) or {}).get("session") or tid) if tid else None
    n, seen = 0, {}
    while not (stop and stop()):
        try:
            lines, cur, _ = read_new(path, cur)
        except OSError:
            break
        for raw in lines:
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            kind, t = d.get("type"), epoch(d.get("timestamp"))
            p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            if kind == "session_meta":
                own = p.get("id") or p.get("session_id")
                if not isinstance(own, str) or not own:
                    continue
                tid, root = own, codex_root(p) or own
                ledger.note_thread(con, "codex", tid, session=root)
                ent = p.get("originator") if isinstance(p.get("originator"), str) else None
                seen.setdefault(root, [t, t, p.get("cwd"), ent])
            elif tid is None:
                continue
            elif kind == "turn_context" and isinstance(p.get("model"), str):
                ledger.note_thread(con, "codex", tid, model=p["model"])
            elif t is not None and (kind == "token_usage_record" or kind == "event_msg" and
                                    p.get("type") == "token_usage_record"):
                n += ledger.add_snapshot(con, "codex", tid, t,
                                         _codex_usage(p.get("thread_token_usage")), "thread")
            elif t is not None and kind == "event_msg" and p.get("type") == "token_count":
                n += ledger.add_snapshot(con, "codex", tid, t, _codex_usage(p.get("info")),
                                         "token_count")
            if root and t is not None:
                got = seen.setdefault(root, [t, t, None, None])
                got[0], got[1] = min(got[0] or t, t), max(got[1] or t, t)
        if cur["offset"] >= os.path.getsize(path) or not lines:
            break
    for sid, (t0, t1, cwd, ent) in seen.items():
        for t in (t0, t1):
            ledger.note_session(con, "codex", sid, t=t, cwd=cwd, entrypoint=ent,
                                client=CLIENT_OF.get(ent, ent), user=user)
        touched.add(("codex", sid))
    con.execute("INSERT OR REPLACE INTO cursor (path, dev, ino, size, mtime, offset, session) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (path, cur["dev"], cur["ino"], st.st_size,
                                                 st.st_mtime_ns, cur["offset"], tid))
    con.commit()
    return n


# --- attribution ---------------------------------------------------------------------

def _roots(home):
    """[(root, kind, entry)]: each project's run folders and checkout, longest
    first, for rules 5 and 6. The checkout is the packet folder for the packet
    layout (``<folder>/.work-packet`` is the project), the project otherwise."""
    from . import layout, registry
    out = []
    for e in registry.entries(home):
        out.append((os.path.realpath(layout.runs_dir(e["path"])), "runs", e))
        out.append((os.path.realpath(layout.packet_folder(e["path"])), "project", e))
    out.sort(key=lambda r: -len(r[0]))
    return out


def _under(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


SESSION_FLAGS = ("--resume", "-r", "--session-id")


def live_tags(proc="/proc"):
    """Rule 4: ``[{"cwd", "start", "session", "project", "wpid"}]`` for this
    user's live ``claude`` processes whose environment names a packet
    (``WPK_WPID``, set in terminals and editors wpk opens). ``session`` is the
    id on the command line (``--resume``, ``--session-id``), else None. A
    runner's process (``WPK_STEP`` set) is rule 1's and left out."""
    from . import procs
    try:
        pids = [int(d) for d in os.listdir(proc) if d.isdigit()]
        boot = procs._boot_time() if proc == procs.PROC else 0
        tick = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError):
        return []
    uid, out = os.getuid(), []
    for pid in pids:
        d = os.path.join(proc, str(pid))
        try:
            if os.stat(d).st_uid != uid:
                continue
            with open(os.path.join(d, "environ"), "rb") as fp:
                env = dict(kv.split(b"=", 1) for kv in fp.read().split(b"\0") if b"=" in kv)
            if not env.get(b"WPK_WPID") or env.get(b"WPK_STEP"):
                continue
            with open(os.path.join(d, "cmdline"), "rb") as fp:
                argv = [a.decode("utf-8", "replace") for a in fp.read().split(b"\0") if a]
            if not argv or os.path.basename(argv[0]) != "claude":
                continue
            cwd = os.readlink(os.path.join(d, "cwd"))
        except (OSError, ValueError):
            continue
        st = procs._stat(pid) if proc == procs.PROC else None
        sid = next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a in SESSION_FLAGS), None)
        out.append({"cwd": os.path.realpath(cwd), "session": sid,
                    "start": boot + st["start"] / tick if st and boot else 0,
                    "wpid": env[b"WPK_WPID"].decode(),
                    "project": (env.get(b"WPK_PROJECT") or b"").decode() or None})
    return out


def _tag_of(s, sid, tags):
    """The live process tag that ``sid`` (session row ``s``) belongs to: by the id
    on its command line, else by folder and start time (a ``/clear`` starts a new
    session in the same process)."""
    for g in tags:
        if g["session"] == sid:
            return g
    cwd = os.path.realpath(s["cwd"]) if s["cwd"] else None
    hits = [g for g in tags if not g["session"] and g["cwd"] == cwd and
            (s["first_t"] or 0) >= g["start"] - 60]
    return hits[0] if len(hits) == 1 else None


def attribute(con, home, keys, tags=()):
    """Rules 4, 5 and 6 (and the runner's run folder) for the sessions ``keys``
    that no stronger rule has claimed."""
    from . import registry
    roots = None
    for h, sid in keys:
        s = ledger.session(con, h, sid)
        if not s or ledger._rank(s["how"]) < ledger._rank("env"):
            continue
        g = _tag_of(s, sid, tags) if tags and s["how"] != "env" else None
        if g:
            e = next((e for e in registry.entries(home) if e["name"] == g["project"]), None) \
                if g["project"] else None
            row = con.execute("SELECT project, name FROM packet WHERE wpid = ?",
                              (g["wpid"],)).fetchone()
            project = g["project"] or (row[0] if row else None)
            ledger.note_session(con, h, sid, how="env", source="interactive", project=project,
                                wpid=g["wpid"], packet_name=row[1] if row else None,
                                board=registry.board_of(e) if e else None)
            continue
        if ledger._rank(s["how"]) < ledger._rank("runner-cwd") or not s["cwd"]:
            continue
        if roots is None:
            roots = _roots(home)
        cwd = os.path.realpath(s["cwd"])
        for root, kind, e in roots:
            if not _under(cwd, root):
                continue
            f = {"project": e["name"], "board": registry.board_of(e)}
            if kind == "runs":
                rest = os.path.relpath(cwd, root).split(os.sep)[0]
                if rest in ("", "."):
                    continue
                f["wpid"] = rest
                row = con.execute("SELECT name FROM packet WHERE project = ? AND wpid = ?",
                                  (e["name"], rest)).fetchone()
                f["packet_name"] = row[0] if row else None
                runner = s["entrypoint"] in RUNNER_ENTRYPOINTS
                ledger.note_session(con, h, sid, how="runner-cwd" if runner else "cwd-packet",
                                    source="runner" if runner else "interactive", **f)
            else:
                ledger.note_session(con, h, sid, how="cwd-project", source="interactive",
                                    wpid=None, packet_name=None, **f)
            break
    con.commit()


# Bumped when the folder rules change, so sessions already in the ledger are
# attributed again by the new ones.
RULES = "2"
HOW_FOLDER = ("env", "runner-cwd", "cwd-packet", "cwd-project", "none")


def _reattribute(con, home):
    """Every session the folder rules decide, when the rules or the registered
    projects changed since the last pass (a project registered today claims its
    earlier sessions); else nothing."""
    from . import registry
    sig = json.dumps([RULES] + sorted([e["name"], e["path"]] for e in registry.entries(home)))
    row = con.execute("SELECT value FROM meta WHERE key = 'roots'").fetchone()
    if row and row[0] == sig:
        return set()
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('roots', ?)", (sig,))
    return {(h, sid) for h, sid in con.execute(
        "SELECT harness, session FROM session WHERE how IN (%s)"
        % ", ".join("?" * len(HOW_FOLDER)), HOW_FOLDER)}


# --- one pass --------------------------------------------------------------------------

def pass_once(home, env=None, stop=None):
    """One collection pass. Returns ``{store, packets, console, files, replies}``."""
    from .ide_sessions import claude_dir, codex_dir
    env = os.environ if env is None else env
    con = ledger.connect(home)
    try:
        out = {"store": ledger.sync_store(con, home)}
        out["packets"] = sync_packets(con, home, stop)
        out["console"] = sync_console(con, home)
        touched, files, replies, user = set(), 0, 0, _user()
        cdir = env.get("WPK_LEDGER_CLAUDE_DIR")     # "": read no transcripts (the tests)
        for path in transcript_files(claude_dir(env) if cdir is None else cdir) if cdir != "" \
                else ():
            if stop and stop():
                break
            got = read_file(con, path, touched, user, stop)
            files += 1 if got else 0
            replies += got
        proc = env.get("WPK_LEDGER_PROC", "/proc")    # "": no live processes (the tests)
        xdir = env.get("WPK_LEDGER_CODEX_DIR")      # "": read no rollouts (the tests)
        for path in codex_files(codex_dir(env) if xdir is None else xdir) if xdir != "" \
                else ():
            if stop and stop():
                break
            got = read_codex_file(con, path, touched, user, stop)
            files += 1 if got else 0
            replies += got
        attribute(con, home, touched | _reattribute(con, home), live_tags(proc) if proc else ())
        ledger.prune_seen(con, time.time() - SEEN_DAYS * 86400)
        con.commit()
        out.update(files=files, replies=replies)
        return out
    finally:
        con.close()


# --- checks (§7) ---------------------------------------------------------------------

def check_steps(home):
    """The runner steps' output tokens against the ledger's for their sessions.
    A step can run in two sessions (the journal's ``step-start`` id and
    ``meta.json``'s differ) and a session can hold several steps (resumed), so
    steps and sessions are compared in linked groups. Returns ``{"same", "more",
    "less", "none", "less_steps": [...]}`` counting groups: ``more`` is expected
    (the ledger also counts sub-agents and turns after a step), ``none`` is a
    group whose transcripts were gone before the ledger read them, and ``less``
    is a reply the ledger missed."""
    con = ledger.reader(home)
    out = {"same": 0, "more": 0, "less": 0, "none": 0, "less_steps": []}
    if con is None:
        return out
    try:
        up = {}

        def find(x):
            while up.setdefault(x, x) != x:
                up[x] = up[up[x]]
                x = up[x]
            return x

        def join(a, b):
            up[find(a)] = find(b)

        tokens = {}
        for sid, project, wpid, step, o in con.execute(
                "SELECT session, project, wpid, step, output_tokens FROM step "
                "WHERE session IS NOT NULL"):
            k = ("step", project, wpid, step)
            tokens[k] = tokens.get(k, 0) + (o or 0)
            join(k, ("session", sid))
        steps = {(k[2], k[3]): k for k in tokens}
        for wpid, step, sid in con.execute(
                "SELECT wpid, step, session FROM session WHERE how = 'runner'"):
            if (wpid, step) in steps:
                join(steps[(wpid, step)], ("session", sid))
        groups = {}
        for x in list(up):
            groups.setdefault(find(x), []).append(x)
        for members in groups.values():
            sids = sorted(m[1] for m in members if m[0] == "session")
            o = sum(tokens.get(m, 0) for m in members if m[0] == "step")
            if not any(m[0] == "step" for m in members):
                continue
            n, lo = con.execute(
                "SELECT count(*), COALESCE(SUM(output_tokens), 0) FROM usage WHERE origin = "
                "'transcript' AND session IN (%s)" % ", ".join("?" * len(sids)),
                sids).fetchone()
            k = "none" if not n else "same" if lo == o else "more" if lo > o else "less"
            out[k] += 1
            if k == "less":
                first = min(m for m in members if m[0] == "step")
                out["less_steps"].append({"session": sids[0], "project": first[1],
                                          "wpid": first[2], "step": first[3],
                                          "step_output": o, "ledger_output": lo})
    finally:
        con.close()
    return out


def check_reread(home, env=None, quiet_s=600):
    """Read every transcript from the start into an empty ledger and compare it
    with this one (§7): what the 30 s passes built bit by bit must equal one read
    of the whole. Only sessions the transcripts still hold are compared, and
    sessions written to in the last ``quiet_s`` seconds are left out, since they
    may grow while this runs. Returns ``{"files", "rows", "changed": [...]}``."""
    import shutil
    import tempfile
    from .ide_sessions import claude_dir
    env = os.environ if env is None else env
    pass_once(home, env)                    # catch up first, so only a difference shows
    cdir = env.get("WPK_LEDGER_CLAUDE_DIR")
    files = transcript_files(claude_dir(env) if cdir is None else cdir) if cdir != "" else []
    q = ("SELECT hour, harness, session, model, %s FROM usage WHERE origin = 'transcript'"
         % ", ".join(ledger.KEYS))
    tmp = tempfile.mkdtemp(prefix="wpk-ledger-")
    try:
        fresh = ledger.connect(path=os.path.join(tmp, "ledger.db"))
        for path in files:
            read_file(fresh, path, set())
        after = {}
        for r in fresh.execute(q):
            _add(after, r)
        fresh.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    con = ledger.reader(home)
    before = {}
    try:
        cut = time.time() - quiet_s
        busy = {r[0] for r in con.execute("SELECT session FROM session WHERE last_t > ?",
                                          (cut,))}
        keep = {k[2] for k in after} - busy
        for r in con.execute(q):
            if r[2] in keep:
                _add(before, r)
    finally:
        con.close()
    after = {k: v for k, v in after.items() if k[2] in keep}
    changed = [{"hour": k[0], "session": k[2], "model": k[3], "ledger": before.get(k),
                "transcripts": after.get(k)} for k in sorted(set(before) | set(after))
               if before.get(k) != after.get(k)]
    return {"files": len(files), "rows": len(before), "changed": changed}


def _add(acc, r):
    """Sum a usage row into ``acc`` by (hour, harness, session, model): the hosts'
    rows of one hour are one figure here."""
    got = acc.get(r[:4])
    acc[r[:4]] = tuple(r[4:]) if got is None else tuple(a + b for a, b in zip(got, r[4:]))
