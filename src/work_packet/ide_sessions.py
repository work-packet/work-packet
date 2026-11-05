"""Claude Code and Codex sessions in web VS Code (docs/vscode-monitor-plan.md).

This part (S2) reads a harness's own session file a little at a time and
keeps a small, serializable *state*: the model, the last event, the times,
and the usage. It keeps nothing a person wrote or a tool returned. The only
things it ever reads are record types, ids, timestamps, model names, usage
counts, content-block *types* and tool *names*. A tool name only chooses an
event category and is never kept.

Claude Code: ``~/.claude/projects/<cwd>/<session>.jsonl``. An assistant
message can be written more than once as it streams, with the same
``message.id`` and growing usage; each id is counted once, with its last
usage.

Codex: ``~/.codex/sessions/Y/M/D/rollout-*.jsonl``. Usage comes as
cumulative snapshots, either ``token_usage_record`` with
``thread_token_usage`` or ``event_msg/token_count`` with
``info.total_token_usage``. The latest one is the total. Snapshots are never
added together, and once a ``thread_token_usage`` has been seen,
``token_count`` is ignored.

Light imports only (stdlib and ``harness.codex``): ``sched/ide_job.py`` runs this
on the exec host.
"""

import datetime
import json
import os
import re

# -- events ------------------------------------------------------------------

PROMPT = "Prompt submitted"
READ = "Read requested"
SHELL = "Shell command requested"
EDIT = "Edit requested"
WEB = "Web request"
AGENT = "Sub-agent requested"
ASK = "Asked for input"
PLAN = "Planning"
TOOL = "Tool requested"
WORKING = "Working"
TURN_START = "Turn started"
TURN_END = "Turn finished"
TURN_ABORT = "Turn interrupted"
EVENTS = (PROMPT, READ, SHELL, EDIT, WEB, AGENT, ASK, PLAN, TOOL, WORKING, TURN_START,
          TURN_END, TURN_ABORT)

# turn_state: what the harness said last about its turn (None: it has said nothing)
WAITING, BUSY, FINISHED, INTERRUPTED = "waiting", "working", "finished", "interrupted"

CLAUDE_TOOLS = {
    "Read": READ, "Grep": READ, "Glob": READ, "LS": READ, "NotebookRead": READ,
    "Bash": SHELL, "BashOutput": SHELL, "KillShell": SHELL, "PowerShell": SHELL,
    "Edit": EDIT, "Write": EDIT, "MultiEdit": EDIT, "NotebookEdit": EDIT,
    "WebFetch": WEB, "WebSearch": WEB,
    "Task": AGENT, "Agent": AGENT,
    "AskUserQuestion": ASK, "ExitPlanMode": ASK,
    "TodoWrite": PLAN, "TaskCreate": PLAN, "TaskUpdate": PLAN,
}
CODEX_TOOLS = {"shell": SHELL, "exec_command": SHELL, "local_shell": SHELL,
               "container.exec": SHELL, "apply_patch": EDIT, "update_plan": PLAN,
               "web_search": WEB, "view_image": READ}
CODEX_EVENTS = {
    "task_started": TURN_START, "turn_started": TURN_START,
    "task_complete": TURN_END, "turn_complete": TURN_END,
    "turn_aborted": TURN_ABORT, "user_message": PROMPT,
    "exec_command_begin": SHELL, "patch_apply_begin": EDIT,
    "web_search_begin": WEB, "mcp_tool_call_begin": TOOL,
    "request_user_input": ASK, "elicitation_request": ASK,
}
TURN_STATE = {PROMPT: BUSY, READ: BUSY, SHELL: BUSY, EDIT: BUSY, WEB: BUSY, AGENT: BUSY,
              PLAN: BUSY, TOOL: BUSY, WORKING: BUSY, TURN_START: BUSY, ASK: WAITING,
              TURN_END: FINISHED, TURN_ABORT: INTERRUPTED}

USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
              "output_tokens", "thinking_tokens")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,79}\Z")
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{7,63}\Z")
ENTRYPOINT = re.compile(r"[a-z0-9][a-z0-9_.-]{0,31}\Z")
RECENT_IDS = 64             # message ids whose usage may still be revised


def epoch(ts):
    """An ISO 8601 timestamp, or epoch ms or s, as epoch seconds (None if neither)."""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return ts / 1000.0 if ts > 1e11 else float(ts)
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _ok(pattern, v):
    return v if isinstance(v, str) and pattern.match(v) else None


def _ints(u, keys=USAGE_KEYS):
    out = {}
    for k in keys:
        v = u.get(k) if isinstance(u, dict) else None
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            out[k] = v
    return out


def total(usage):
    """All the tokens: input, cache writes and reads, and output (thinking is
    part of the output)."""
    if not usage:
        return None
    return sum(usage.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                         "cache_read_input_tokens", "output_tokens"))


def _event(st, ev, t):
    st["last_event"] = ev
    if t is not None:
        st["last_event_t"] = t
    st["turn_state"] = TURN_STATE.get(ev, st.get("turn_state"))


def _touch(st, t):
    if t is not None and t > (st.get("last_activity_t") or 0):
        st["last_activity_t"] = t


def new_state(harness):
    return {"harness": harness, "session_id": None, "model": None, "usage": {},
            "usage_reported": False, "last_event": None, "last_event_t": None,
            "last_activity_t": None, "turn_state": None, "bad_lines": 0,
            # harness-specific; not shown
            "entrypoint": None, "source": None, "cwd": None, "_folded": {}, "_recent": [],
            "_usage_src": None}


# -- Claude Code -------------------------------------------------------------

def _claude_usage(st):
    """The folded usage plus the recent ids' latest."""
    out = dict(st["_folded"])
    for _, u in st["_recent"]:
        for k, v in u.items():
            out[k] = out.get(k, 0) + v
    st["usage"] = out


def _claude_note_usage(st, mid, u):
    """``mid``'s usage, replacing an earlier revision of it."""
    recent = st["_recent"]
    for i, (rid, _) in enumerate(recent):
        if rid == mid:
            recent[i] = [mid, u]
            break
    else:
        recent.append([mid, u])
        while len(recent) > RECENT_IDS:
            _, old = recent.pop(0)
            for k, v in old.items():
                st["_folded"][k] = st["_folded"].get(k, 0) + v
    st["usage_reported"] = True
    _claude_usage(st)


def _content_types(msg):
    """``[(block type, tool name or None)]`` for a message's content; a plain
    string is one ``text`` block."""
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, str):
        return [("text", None)]
    out = []
    for b in c if isinstance(c, list) else ():
        if isinstance(b, dict) and isinstance(b.get("type"), str):
            out.append((b["type"], b.get("name") if b["type"] == "tool_use" else None))
    return out


def claude_feed(st, d):
    """One record of a Claude Code session file."""
    if not isinstance(d, dict):
        return st
    kind = d.get("type")
    if kind not in ("user", "assistant"):
        return st                   # summaries, titles, attachments, prompts kept elsewhere
    st["session_id"] = st["session_id"] or _ok(SESSION, d.get("sessionId"))
    st["entrypoint"] = _ok(ENTRYPOINT, d.get("entrypoint")) or st["entrypoint"]
    if isinstance(d.get("cwd"), str) and st["cwd"] is None:
        st["cwd"] = d["cwd"]
    t = epoch(d.get("timestamp"))
    _touch(st, t)
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    blocks = _content_types(msg)
    if kind == "user":
        if d.get("isMeta") or any(b == "tool_result" for b, _ in blocks):
            return st               # a tool's answer or a harness note, not a prompt
        if blocks:
            _event(st, PROMPT, t)
        return st
    model = _ok(MODEL, msg.get("model"))
    if model and model != "<synthetic>":
        st["model"] = model
    mid = msg.get("id")
    u = _ints(msg.get("usage"))
    if isinstance(mid, str) and u:
        _claude_note_usage(st, mid, u)
    tools = [n for b, n in blocks if b == "tool_use"]
    if tools:
        _event(st, CLAUDE_TOOLS.get(tools[-1], TOOL), t)
    elif msg.get("stop_reason") == "end_turn":
        _event(st, TURN_END, t)
    elif blocks:
        _event(st, WORKING, t)
    return st


# -- Codex -------------------------------------------------------------------

def _codex_usage(u):
    """A cumulative usage snapshot, in Claude's names (None if it is not one)."""
    from .harness.codex import claude_names
    if not isinstance(u, dict):
        return None
    for inner in ("total_token_usage", "total"):
        if isinstance(u.get(inner), dict):
            u = u[inner]
            break
    got = _ints(u, ("input_tokens", "cached_input_tokens", "output_tokens",
                    "reasoning_output_tokens"))
    if "input_tokens" not in got and "output_tokens" not in got:
        return None
    return claude_names(got)


def _codex_set_usage(st, u, src):
    if u is None:
        return
    if src == "token_count" and st["_usage_src"] == "thread":
        return                      # the thread's own total is better: never both
    st["usage"], st["usage_reported"], st["_usage_src"] = u, True, src


def codex_feed(st, d):
    """One record of a Codex rollout."""
    if not isinstance(d, dict):
        return st
    kind = d.get("type")
    p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
    t = epoch(d.get("timestamp"))
    _touch(st, t)
    if kind == "session_meta":
        st["session_id"] = st["session_id"] or _ok(SESSION, p.get("id") or p.get("session_id"))
        src = p.get("source")
        st["source"] = _ok(ENTRYPOINT, src) if isinstance(src, str) else (
            "subagent" if isinstance(src, dict) else None)
        st["entrypoint"] = _ok(ENTRYPOINT, p.get("originator"))
        if isinstance(p.get("cwd"), str):
            st["cwd"] = p["cwd"]
    elif kind == "turn_context":
        st["model"] = _ok(MODEL, p.get("model")) or st["model"]
    elif kind == "token_usage_record" or kind == "event_msg" and \
            p.get("type") == "token_usage_record":
        _codex_set_usage(st, _codex_usage(p.get("thread_token_usage")), "thread")
    elif kind == "event_msg":
        et = p.get("type")
        if et == "token_count":
            _codex_set_usage(st, _codex_usage(p.get("info")), "token_count")
        elif et in CODEX_EVENTS:
            _event(st, CODEX_EVENTS[et], t)
        elif isinstance(et, str) and et.endswith("approval_request"):
            _event(st, ASK, t)
        elif et == "agent_message":
            _event(st, WORKING, t)
    elif kind == "response_item":
        it = p.get("type")
        if it in ("function_call", "custom_tool_call"):
            _event(st, CODEX_TOOLS.get(p.get("name"), TOOL), t)
        elif it == "local_shell_call":
            _event(st, SHELL, t)
        elif it == "web_search_call":
            _event(st, WEB, t)
    return st


FEED = {"claude": claude_feed, "codex": codex_feed}


# -- reading a little at a time --------------------------------------------

MAX_READ = 4 << 20          # bytes per file per pass: a big backlog catches up over passes


def read_new(path, cur, max_bytes=MAX_READ):
    """The complete lines added to ``path`` since ``cur``.

    Returns ``(lines, cur, reset)``. ``reset`` is true when the file is not the
    one ``cur`` was reading (a new inode) or is shorter than ``cur``'s offset
    (truncated): it is read again from the start, and the caller starts its
    state over. A last line without its newline is left for the next pass. A
    line longer than ``max_bytes`` is skipped."""
    st = os.stat(path)
    reset = cur is None or cur.get("ino") != st.st_ino or cur.get("dev") != st.st_dev or \
        st.st_size < cur.get("offset", 0)
    if reset:
        cur = {"dev": st.st_dev, "ino": st.st_ino, "offset": 0, "skip": False}
    else:
        cur = dict(cur)
    if st.st_size == cur["offset"]:
        return [], cur, reset
    with open(path, "rb") as fp:
        fp.seek(cur["offset"])
        data = fp.read(max_bytes)
    end = data.rfind(b"\n")
    if end < 0:
        if len(data) >= max_bytes:              # one huge line: skip to its end
            cur["offset"] += len(data)
            cur["skip"] = True
        return [], cur, reset
    chunk = data[:end]
    cur["offset"] += end + 1
    lines = chunk.split(b"\n")
    if cur.get("skip"):
        lines, cur["skip"] = lines[1:], False   # the rest of the skipped line
    return lines, cur, reset


def scan(path, harness, st=None, cur=None, max_bytes=MAX_READ):
    """Read what is new in one session file into its state: ``(state, cursor)``."""
    lines, cur, reset = read_new(path, cur, max_bytes)
    if reset or st is None:
        st = new_state(harness)
    feed = FEED[harness]
    for raw in lines:
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            st["bad_lines"] += 1
            continue
        feed(st, d)
    return st, cur


# -- S3: which sessions belong to a launch -----------------------------------
#
# A session is *confirmed* when a live harness process is a descendant of the
# editor's server, carries the launch's ``WPK_IDE_LAUNCH``, and names its
# session in a way we can check: Claude's ``sessions/<pid>.json`` (pid-reuse
# guarded by ``procStart``), or the rollout a Codex process holds open. It is
# a *workspace* match when no live process was seen but its file says a VS Code
# client wrote it, its cwd is in the editor's folders, and it was active while
# the launch ran. Anything else is not shown. A scheduled step's session is
# never shown.

CONFIRMED, WORKSPACE = "confirmed", "workspace"
ENV_KEEP = ("WPK_IDE_LAUNCH", "WPK_IDE_KEY", "WPK_PROJECT", "WPK_WPID", "CLAUDE_CONFIG_DIR",
            "CODEX_HOME", "HOME")
VSCODE_MARKERS = {"claude": "claude-vscode", "codex": "vscode"}
CLIENTS = {("claude", "claude-vscode"): "vscode-ext", ("claude", "cli"): "terminal",
           ("codex", "vscode"): "vscode-ext", ("codex", "cli"): "terminal"}
ROLLOUT = re.compile(r"rollout-[^/]*\.jsonl\Z")
PROC = "/proc"


def _proc_stat(pid):
    """``(ppid, starttime)`` from ``/proc/<pid>/stat``, or None."""
    try:
        with open("%s/%d/stat" % (PROC, pid)) as fp:
            f = fp.read().rpartition(")")[2].split()
        return int(f[1]), f[19]
    except (OSError, IndexError, ValueError):
        return None


def descendants(root):
    """``root``'s descendant pids (not ``root``), from ``/proc``."""
    kids = {}
    try:
        names = os.listdir(PROC)
    except OSError:
        return []
    for n in names:
        if n.isdigit():
            st = _proc_stat(int(n))
            if st is not None:
                kids.setdefault(st[0], []).append(int(n))
    out, todo = [], [root]
    while todo:
        for k in kids.get(todo.pop(), ()):
            out.append(k)
            todo.append(k)
    return out


def proc_env(pid, keep=ENV_KEEP):
    """Only the ``keep`` variables of ``pid``'s environment: the rest is never kept."""
    try:
        with open("%s/%d/environ" % (PROC, pid), "rb") as fp:
            raw = fp.read()
    except OSError:
        return {}
    out = {}
    for item in raw.split(b"\0"):
        k, sep, v = item.partition(b"=")
        if sep and k.decode("ascii", "replace") in keep:
            out[k.decode()] = v.decode("utf-8", "replace")
    return out


def open_rollouts(pid):
    """The Codex rollouts ``pid`` holds open."""
    out = []
    d = "%s/%d/fd" % (PROC, pid)
    try:
        fds = os.listdir(d)
    except OSError:
        return out
    for fd in fds:
        try:
            p = os.readlink(os.path.join(d, fd))
        except OSError:
            continue
        if ROLLOUT.search(p) and os.path.isfile(p):
            out.append(p)
    return sorted(set(out))


def claude_dir(env):
    return env.get("CLAUDE_CONFIG_DIR") or os.path.join(
        env.get("HOME") or os.path.expanduser("~"), ".claude")


def codex_dir(env):
    return env.get("CODEX_HOME") or os.path.join(
        env.get("HOME") or os.path.expanduser("~"), ".codex")


def project_dir_name(cwd):
    """Claude Code's folder for a cwd under ``projects/``: each character that
    is not a letter or digit becomes ``-``."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def claude_pid_session(pid, env):
    """``{session_id, entrypoint, status, cwd}`` from ``sessions/<pid>.json``
    when it is this process's (its ``procStart`` matches), else None."""
    path = os.path.join(claude_dir(env), "sessions", "%d.json" % pid)
    try:
        with open(path) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        return None
    st = _proc_stat(pid)
    if not isinstance(d, dict) or st is None or str(d.get("procStart")) != st[1]:
        return None
    sid = _ok(SESSION, d.get("sessionId"))
    if sid is None:
        return None
    return {"session_id": sid, "entrypoint": _ok(ENTRYPOINT, d.get("entrypoint")),
            "status": _ok(ENTRYPOINT, d.get("status")),
            "cwd": d.get("cwd") if isinstance(d.get("cwd"), str) else None}


def claude_transcript(env, sid, cwd):
    base = os.path.join(claude_dir(env), "projects")
    if cwd:
        p = os.path.join(base, project_dir_name(cwd), sid + ".jsonl")
        if os.path.isfile(p):
            return p
    try:
        for d in os.listdir(base):
            p = os.path.join(base, d, sid + ".jsonl")
            if os.path.isfile(p):
                return p
    except OSError:
        pass
    return None


def live_sessions(root, launch_id):
    """The harness sessions of processes under ``root`` with this launch:
    ``[{harness, session_id?, path, env, status?}]``. Codex's session id
    comes from its file."""
    out = []
    for pid in descendants(root):
        env = proc_env(pid)
        if env.get("WPK_IDE_LAUNCH") != launch_id:
            continue
        c = claude_pid_session(pid, env)
        if c is not None:
            path = claude_transcript(env, c["session_id"], c["cwd"])
            if path:
                out.append(dict(c, harness="claude", path=path, env=env, pid=pid))
            continue
        for path in open_rollouts(pid):
            out.append({"harness": "codex", "path": path, "env": env, "pid": pid})
    return out


# -- the store ---------------------------------------------------------------
#
# ``ide/sessions/<harness>-<session>.json``: what the board shows, built field
# by field from an allowlist. ``.../<harness>-<session>.cur``: where the
# reader got to in each file, so a restart neither re-counts nor loses counts.
# Both 0600 in a 0700 directory.

ATTRIBUTIONS = (CONFIRMED, WORKSPACE)
NAME = re.compile(r"[^\x00-\x1f\x7f]{1,200}\Z")
WPID = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
LAUNCH = re.compile(r"L-[0-9a-f]{12}\Z")
KEY = re.compile(r"[0-9a-f]{12}\Z")
REF = re.compile(r"[A-Za-z0-9._:@-]{1,64}\Z")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}\Z")
STATUS = re.compile(r"[a-z_]{1,16}\Z")
FIELDS = {
    "harness": lambda v: v in FEED,
    "session_id": lambda v: bool(_ok(SESSION, v)),
    "attribution": lambda v: v in ATTRIBUTIONS,
    "project": lambda v: bool(_ok(NAME, v)),
    "wpid": lambda v: bool(_ok(WPID, v)),
    "launch_ids": lambda v: isinstance(v, list) and all(_ok(LAUNCH, x) for x in v),
    "key": lambda v: bool(_ok(KEY, v)),
    "job_ref": lambda v: bool(_ok(REF, v)),
    "host": lambda v: bool(_ok(HOST, v)),
    "client": lambda v: v in ("vscode-ext", "terminal", "unknown"),
    "model": lambda v: bool(_ok(MODEL, v)),
    "last_event": lambda v: v in EVENTS,
    "last_event_t": lambda v: isinstance(v, (int, float)),
    "last_activity_t": lambda v: isinstance(v, (int, float)),
    "first_seen_t": lambda v: isinstance(v, (int, float)),
    "turn_state": lambda v: v in (WAITING, BUSY, FINISHED, INTERRUPTED),
    "status": lambda v: bool(_ok(STATUS, v)),
    "live": lambda v: isinstance(v, bool),
    "usage": lambda v: isinstance(v, dict) and all(
        k in USAGE_KEYS and isinstance(n, int) and not isinstance(n, bool)
        for k, n in v.items()),
    "usage_reported": lambda v: isinstance(v, bool),
}


def sessions_dir(home):
    return os.path.join(home, "ide", "sessions")


def _private_dir(d):
    os.makedirs(d, mode=0o700, exist_ok=True)


def clean(rec):
    """The record with only allowed fields and values: anything else is dropped."""
    return {k: v for k, v in rec.items() if k in FIELDS and v is not None and FIELDS[k](v)}


def _name(harness, sid):
    return "%s-%s" % (harness, sid)


def _put(path, obj):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fp:
        json.dump(obj, fp, sort_keys=True)
    os.replace(tmp, path)


def _get(path):
    try:
        with open(path) as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def write(home, rec):
    """Store one session's record (cleaned). Returns what was stored, or None
    when it has no harness or session id."""
    rec = clean(rec)
    if "harness" not in rec or "session_id" not in rec:
        return None
    d = sessions_dir(home)
    _private_dir(d)
    _put(os.path.join(d, _name(rec["harness"], rec["session_id"]) + ".json"), rec)
    return rec


def read(home, harness, sid):
    rec = _get(os.path.join(sessions_dir(home), _name(harness, sid) + ".json"))
    return clean(rec) if rec else None


def records(home):
    """Every stored session record, cleaned again on the way out."""
    d = sessions_dir(home)
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if n.endswith(".json"):
            rec = _get(os.path.join(d, n))
            rec = clean(rec) if rec else None
            if rec and "harness" in rec and "session_id" in rec:
                out.append(rec)
    return out


def _load_cur(home, harness, sid):
    return _get(os.path.join(sessions_dir(home), _name(harness, sid) + ".cur")) or {}


def _save_cur(home, harness, sid, cur):
    _private_dir(sessions_dir(home))
    _put(os.path.join(sessions_dir(home), _name(harness, sid) + ".cur"), cur)


def prune(home, now, keep_days=30, keep=500):
    """Drop records idle longer than ``keep_days``, then the oldest beyond ``keep``."""
    recs = sorted(records(home), key=lambda r: r.get("last_activity_t") or 0, reverse=True)
    drop = [r for r in recs if (r.get("last_activity_t") or 0) < now - keep_days * 86400]
    drop += [r for r in recs[keep:] if r not in drop]
    for r in drop:
        for ext in (".json", ".cur"):
            try:
                os.unlink(os.path.join(sessions_dir(home), _name(r["harness"],
                                                                 r["session_id"]) + ext))
            except OSError:
                pass
    return len(drop)


# -- one launch's collector ------------------------------------------------

def step_sessions(home, projects):
    """Session ids that scheduled steps of ``projects`` (board names) recorded."""
    from . import layout, registry
    out = set()
    for name in projects:
        e = registry.get(name, home) if name else None
        if not e or not e.get("path"):
            continue
        runs = layout.runs_dir(e["path"])
        try:
            wpids = os.listdir(runs)
        except OSError:
            continue
        for w in wpids:
            sd = os.path.join(runs, w, "steps")
            try:
                steps = os.listdir(sd)
            except OSError:
                continue
            for n in steps:
                m = _get(os.path.join(sd, n, "meta.json"))
                if m and isinstance(m.get("session_id"), str):
                    out.add(m["session_id"])
    return out


def target_folders(target):
    """The folders an editor on ``target`` works in: the folder, or a
    workspace file's folders."""
    if not target:
        return []
    if not target.endswith(".code-workspace"):
        return [os.path.abspath(target)]
    ws = _get(target) or {}
    base = os.path.dirname(target)
    out = []
    for f in ws.get("folders") or ():
        p = f.get("path") if isinstance(f, dict) else None
        if isinstance(p, str):
            out.append(os.path.abspath(os.path.join(base, p)))
    return out or [os.path.dirname(base)]


def _under(path, roots):
    if not path:
        return False
    path = os.path.abspath(path)
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


class Collector:
    """Watches one launch's sessions and keeps their records (``pass_once``).

    ``home``: the board's home. ``launch``: its record (``ide_launch``).
    ``root``: the editor server's pid on this host (None: nothing to scan, so
    only workspace matches). ``env``: whose harness folders to sweep for
    workspace matches (HOME, CLAUDE_CONFIG_DIR, CODEX_HOME), by default ours."""

    SWEEP_S = 60

    def __init__(self, home, launch, root=None, env=None, clock=None):
        import time
        self.home = home
        self.launch = launch
        self.root = root
        self.env = dict(os.environ if env is None else env)
        self.clock = clock or time.time
        self.files = {}         # (harness, sid) -> {path: {"st", "cur"}}
        self.meta = {}          # (harness, sid) -> binding
        self._steps, self._steps_t = set(), None
        self._swept = None

    # -- packet and job of this launch
    def _packet(self, env):
        from . import ide_launch
        key = self.launch["key"]
        prev_end = None
        for r in ide_launch.history(self.home, key):
            if r.get("launch_id") == self.launch["launch_id"]:
                break
            prev_end = r.get("ended") or prev_end
        until = self.launch.get("ended")
        project, wpid = ide_launch.packet_of(self.home, key, since=prev_end, until=until)
        want = env.get("WPK_WPID")           # a terminal in a packet's workspace says so
        if want:
            names = {(o.get("project"), o.get("wpid")) for o in ide_launch.opens(self.home, key)
                     if o.get("wpid") == want}
            if len(names) == 1:
                project, wpid = next(iter(names))
        return project, wpid

    def _job(self):
        from . import ide_launch
        cur = ide_launch.find(self.home, self.launch["launch_id"]) or self.launch
        return cur.get("job_ref"), cur.get("host")

    def _step_ids(self, now):
        if self._steps_t is None or now - self._steps_t > self.SWEEP_S:
            from . import ide_launch
            names = {o.get("project") for o in ide_launch.opens(self.home, self.launch["key"])}
            try:
                self._steps = step_sessions(self.home, names - {None})
            except Exception:       # a broken registry entry must not stop the collector
                self._steps = set()
            self._steps_t = now
        return self._steps

    # -- reading
    def _read(self, harness, sid, path):
        """Read what is new in ``path`` for session ``sid`` (None: not known yet);
        returns ``(sid, state)``, the state combined over the session's files."""
        k = (harness, sid) if sid else None
        files = self.files.get(k) if k else None
        if files is None and sid:
            files = _load_cur(self.home, harness, sid).get("files") or {}
            self.files[k] = files
        f = (files or {}).get(path) or {}
        st, cur = scan(path, harness, f.get("st"), f.get("cur"))
        sid = sid or st.get("session_id")
        if not sid:
            return None, st
        k = (harness, sid)
        if k not in self.files:
            self.files[k] = _load_cur(self.home, harness, sid).get("files") or {}
        self.files[k][path] = {"st": st, "cur": cur}
        return sid, self._combined(k)

    def _combined(self, k):
        """One session over its files (a resumed Codex thread may start a new one):
        the latest file's model and event, the usage summed over the files."""
        sts = sorted((f["st"] for f in self.files[k].values()),
                     key=lambda s: s.get("last_activity_t") or 0)
        out = dict(sts[-1])
        usage = {}
        for s in sts:
            for kk, v in (s.get("usage") or {}).items():
                usage[kk] = usage.get(kk, 0) + v
        out["usage"] = usage
        out["usage_reported"] = any(s.get("usage_reported") for s in sts)
        out["model"] = next((s["model"] for s in reversed(sts) if s.get("model")), None)
        return out

    # -- one pass
    def pass_once(self):
        now = self.clock()
        live = live_sessions(self.root, self.launch["launch_id"]) if self.root else []
        seen = set()
        for s in live:
            sid, st = self._read(s["harness"], s.get("session_id"), s["path"])
            if not sid or sid in self._step_ids(now):
                continue
            seen.add((s["harness"], sid))
            self._store(s["harness"], sid, st, CONFIRMED, s["env"], s.get("status"), True)
        if self._swept is None or now - self._swept >= self.SWEEP_S:
            self._swept = now
            self._sweep(now, seen)
        # bound sessions whose process is gone: read what they wrote last
        for (h, sid), files in list(self.files.items()):
            if (h, sid) in seen or (h, sid) not in self.meta:
                continue
            for path in list(files):
                if os.path.isfile(path):
                    _, st = self._read(h, sid, path)
            m = self.meta[(h, sid)]
            self._store(h, sid, self._combined((h, sid)), m["attribution"], m["env"],
                        None, False)
        return len(seen)

    def _store(self, harness, sid, st, attribution, env, status, live):
        prev = read(self.home, harness, sid) or {}
        if prev.get("attribution") == CONFIRMED:
            attribution = CONFIRMED
        b = self.meta.setdefault((harness, sid), {"attribution": attribution, "env": env})
        b["attribution"] = attribution
        project, wpid = self._packet(env)
        job_ref, host = self._job() if attribution == CONFIRMED else (None, None)
        marker = st.get("entrypoint") if harness == "claude" else st.get("source")
        lids = list(prev.get("launch_ids") or [])
        if self.launch["launch_id"] not in lids:
            lids.append(self.launch["launch_id"])
        write(self.home, {
            "harness": harness, "session_id": sid, "attribution": attribution,
            "project": project or prev.get("project"), "wpid": wpid or prev.get("wpid"),
            "launch_ids": lids[-20:], "key": self.launch["key"],
            "job_ref": job_ref, "host": host,
            "client": CLIENTS.get((harness, marker), "unknown"),
            "model": st.get("model"), "last_event": st.get("last_event"),
            "last_event_t": st.get("last_event_t"),
            "last_activity_t": st.get("last_activity_t"),
            "first_seen_t": prev.get("first_seen_t") or self.clock(),
            "turn_state": st.get("turn_state"), "status": status if live else None,
            "live": live, "usage": st.get("usage") or {},
            "usage_reported": bool(st.get("usage_reported"))})
        _save_cur(self.home, harness, sid, {"files": self.files.get((harness, sid)) or {}})

    # -- workspace matches
    def _window(self, now):
        start = self.launch.get("started") or 0
        return start, self.launch.get("ended") or now

    def _sweep(self, now, seen):
        roots = target_folders(self.launch.get("target"))
        if not roots:
            return
        start, end = self._window(now)
        for harness, path in self._candidates(roots, start):
            try:
                if os.path.getmtime(path) < start:
                    continue
            except OSError:
                continue
            known = next((k for k, files in self.files.items() if path in files), None)
            if known in seen or known in self.meta:
                continue
            first = _first_meta(harness, path)
            if first is None or first.get("marker") != VSCODE_MARKERS[harness] or \
                    not _under(first.get("cwd"), roots):
                continue
            sid, st = self._read(harness, first.get("session_id"), path)
            if not sid or sid in self._step_ids(now):
                continue
            t = st.get("last_activity_t") or 0
            if not start <= t <= end + self.SWEEP_S:
                continue
            self._store(harness, sid, st, WORKSPACE, {}, None, False)

    def _candidates(self, roots, start):
        out = []
        base = os.path.join(claude_dir(self.env), "projects")
        for r in roots:
            d = os.path.join(base, project_dir_name(r))
            try:
                out += [("claude", os.path.join(d, n)) for n in os.listdir(d)
                        if n.endswith(".jsonl")]
            except OSError:
                pass
        import datetime as dt
        day = dt.date.fromtimestamp(start) if start else dt.date.today()
        today = dt.date.fromtimestamp(self.clock())
        cbase = os.path.join(codex_dir(self.env), "sessions")
        n = 0
        while day <= today and n < 62:
            d = os.path.join(cbase, "%04d" % day.year, "%02d" % day.month, "%02d" % day.day)
            try:
                out += [("codex", os.path.join(d, x)) for x in os.listdir(d) if ROLLOUT.match(x)]
            except OSError:
                pass
            day += dt.timedelta(days=1)
            n += 1
        return out


def _first_meta(harness, path, limit=64 << 10):
    """``{session_id, marker, cwd}`` from the start of a session file: Codex's
    ``session_meta``, or Claude's first user or assistant record."""
    try:
        with open(path, "rb") as fp:
            head = fp.read(limit)
    except OSError:
        return None
    for raw in head.split(b"\n")[:50]:
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if harness == "codex" and d.get("type") == "session_meta":
            p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            src = p.get("source")
            return {"session_id": _ok(SESSION, p.get("id") or p.get("session_id")),
                    "marker": src if isinstance(src, str) else None,
                    "cwd": p.get("cwd") if isinstance(p.get("cwd"), str) else None}
        if harness == "claude" and d.get("type") in ("user", "assistant"):
            return {"session_id": _ok(SESSION, d.get("sessionId")),
                    "marker": d.get("entrypoint"),
                    "cwd": d.get("cwd") if isinstance(d.get("cwd"), str) else None}
    return None


# -- S4: the board's side --------------------------------------------------

def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def local_pass(home, collectors):
    """One pass over the board's local launches (a job's launch is watched by
    its own job, on its host). ``collectors``: ``{launch_id: Collector}``, kept
    by the caller between passes; a launch that ended gets one last pass."""
    from . import ide_launch
    root = os.path.join(home, "ide", "servers")
    try:
        keys = os.listdir(root)
    except OSError:
        keys = []
    live = set()
    for key in keys:
        cur = ide_launch.current(home, key)
        if not cur or cur.get("backend") != "local" or not isinstance(cur.get("pid"), int):
            continue
        lid = cur["launch_id"]
        alive = not cur.get("ended") and _alive(cur["pid"])
        c = collectors.get(lid)
        if c is None:
            if not alive:
                continue
            c = collectors[lid] = Collector(home, cur, root=cur["pid"])
        c.launch, c.root = cur, cur["pid"] if alive else None
        c.pass_once()
        if alive:
            live.add(lid)
    for lid in [x for x in collectors if x not in live]:
        del collectors[lid]                     # its last pass is done
    return len(live)


# -- S5: what the board shows ----------------------------------------------

HARNESS_LABEL = {"claude": "Claude Code", "codex": "Codex"}
CLIENT_LABEL = {"vscode-ext": "extension", "terminal": "terminal", "unknown": ""}
TURN_LABEL = {WAITING: "waiting for input", BUSY: "working", FINISHED: "turn finished",
              INTERRUPTED: "interrupted"}
_CACHE = {}


def cached_records(home):
    """``records`` again only when the store changed: page handlers read this,
    never a transcript."""
    d = sessions_dir(home)
    try:
        sig = os.stat(d).st_mtime_ns
    except OSError:
        return []
    got = _CACHE.get(d)
    if got is None or got[0] != sig:
        got = _CACHE[d] = (sig, records(home))
    return got[1]


def ago(t, now):
    if not isinstance(t, (int, float)):
        return ""
    s = max(0, int(now - t))
    if s < 60:
        return "%ds ago" % s
    if s < 3600:
        return "%dm ago" % (s // 60)
    if s < 86400:
        return "%dh ago" % (s // 3600)
    return "%dd ago" % (s // 86400)


def row(r, now):
    """One record as the board's table shows it."""
    u = r.get("usage") or {}
    reported = bool(r.get("usage_reported"))
    if r.get("attribution") == CONFIRMED:
        proc = (r.get("status") or "running") if r.get("live") else "ended"
    else:
        proc = ""
    return {
        "harness": HARNESS_LABEL.get(r["harness"], r["harness"]),
        "session": r["session_id"], "short": r["session_id"][:8],
        "model": r.get("model") or "unreported",
        "event": r.get("last_event") or "",
        "event_ago": ago(r.get("last_event_t"), now),
        "activity_t": r.get("last_activity_t"),
        "activity_ago": ago(r.get("last_activity_t"), now),
        "turn": TURN_LABEL.get(r.get("turn_state"), ""),
        "process": proc,
        "tokens": total(u) if reported else None,
        "usage": ", ".join("%s %d" % (k.replace("_tokens", "").replace("_", " "), v)
                           for k, v in sorted(u.items())) if reported else "",
        "workspace": r.get("attribution") == WORKSPACE,
        "job_ref": r.get("job_ref") if r.get("attribution") == CONFIRMED else None,
        "host": r.get("host") if r.get("attribution") == CONFIRMED else None,
        "client": CLIENT_LABEL.get(r.get("client") or "unknown", ""),
        "project": r.get("project"), "wpid": r.get("wpid"),
    }


def _newest(recs):
    return sorted(recs, key=lambda r: r.get("last_activity_t") or 0, reverse=True)


def packet_view(home, project, wpid, now=None):
    """``(rows, shared)`` for a packet's page: its sessions, and those in an
    editor it opened whose packet could not be told apart."""
    import time
    from . import ide_launch
    now = time.time() if now is None else now
    mine, shared = [], []
    keys = {}
    for r in _newest(cached_records(home)):
        if r.get("project") != project:
            continue
        if r.get("wpid") == wpid:
            mine.append(row(r, now))
        elif not r.get("wpid") and r.get("key"):
            k = r["key"]
            if k not in keys:
                keys[k] = any(o.get("wpid") == wpid for o in ide_launch.opens(home, k))
            if keys[k]:
                shared.append(row(r, now))
    return mine, shared


def recent_view(home, limit=8, now=None):
    """The most recently active sessions across packets, for the Overview."""
    import time
    now = time.time() if now is None else now
    return [row(r, now) for r in _newest(cached_records(home))[:limit]]


def project_view(home, project, now=None):
    """Every session of a project, newest first, for its tabbed page."""
    import time
    now = time.time() if now is None else now
    return [row(r, now) for r in _newest(cached_records(home)) if r.get("project") == project]
