"""The console's agent (docs/console.md, C2): conversations the board keeps.

A line without a leading ``/`` goes to a Claude session run through the
harness (``claude -p --output-format stream-json``), one process per reply,
continued with ``--resume``. The agent starts in the scope's directory, gets
a primer (the scope, its state, a guide, the slash commands) and read-only
tools. It never changes state: it writes slash commands for the person to run.

A conversation belongs to a scope: the server, a project or a packet. It
lives under ``<home>/console/<id>/``: ``meta.json``, ``transcript.jsonl``
(what the drawer shows: commands and their cards, questions, replies, tool
calls), ``stream.jsonl`` (the raw stream-json) and ``primer.md``. Nothing is
written into the project.

Transcript events, each with ``t`` (epoch seconds) and ``k``:
``cmd`` (``line``, ``by``, ``out``: the card), ``ask`` (``text``, ``by``),
``say`` (``text``, ``id``, ``props``?: the slash commands it proposes),
``tool`` (``name``, ``what``), ``end`` (``ok``, ``cost``, ``error``?),
``note`` (``text``), ``decline`` (``ref``: a proposal dismissed). A ``cmd``
run from a proposal has ``ref`` (``<say id>:<i>``), and ``auto`` when it ran
without a click. Sockets also get ``busy``
(``on``).

A conversation's ``mode`` is ``console`` (the above) or ``studio``
(docs/studio-plan.md P0.3): the agent of a packet's studio, which writes. Its
command line is a step's (``harness.get("claude").command``: the project's
tools and Bash allowlist, the step's ``--add-dir`` and hooks, ``acceptEdits``),
with the packet's model and step budget, in the packet folder; the path hook
refuses edits of the run's own files (``WPK_PROTECT``). It runs only for the
person who has taken the packet (``executor.take``).
"""

import json
import os
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid

from .. import layout, registry, schema

TOOLS = ("Read", "Grep", "Glob", "Bash")
# Read-only wpk subcommands and ls; dontAsk refuses everything else.
WPK_RO = ("ps", "show", "log", "report", "stats", "sched", "path", "history list",
          "request list", "board list", "card list", "card show", "watch list", "url",
          "check")
ALLOWED = ("Read", "Grep", "Glob", "Bash(ls *)", "Bash(ls)") + tuple(
    "Bash(wpk %s *)" % c for c in WPK_RO) + tuple("Bash(wpk %s)" % c for c in WPK_RO)
GUIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "prompts", "console.md")
KILL_AFTER_S = 5


# The studio agent's tools, whatever the project allows besides (P0.3).
STUDIO_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep") + tuple(
    "Bash(wpk studio %s *)" % c for c in ("exec", "query", "datasets", "look")) + (
    "Bash(wpk studio datasets)",)               # the kernel (docs/studio-plan.md S2.2)


class Busy(Exception):
    """The conversation is already answering, or too many are."""


class NotTaken(Exception):
    """A studio conversation for a packet the asker has not taken."""


def config(home=None):
    """``[console]`` over ``schema.CONSOLE_DEFAULTS``; the defaults if unreadable."""
    try:
        got = registry.load_config_file(home).get("console") or {}
    except registry.ConfigError:
        got = {}
    return dict(schema.CONSOLE_DEFAULTS, **got)


def scope_key(scope):
    if scope.get("wpid"):
        return "p/%s/%s" % (scope["project"], scope["wpid"])
    if scope.get("project"):
        return "p/%s" % scope["project"]
    return "server"


def source_repo():
    """The wpk source tree when wpk runs from one (an editable install), else None."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.basename(root) == "src":
        root = os.path.dirname(root)
    return root if os.path.exists(os.path.join(root, "pyproject.toml")) else None


class Agents:
    """The conversations under ``<home>/console/`` and the replies running now.
    Thread-safe; replies run on threads of their own."""

    def __init__(self, home=None, max_running=None, timeout_s=None):
        self.home = home or registry.home()
        cfg = config(self.home)
        self.max_running = max_running or cfg["max_running"]
        self.timeout_s = timeout_s or cfg["timeout_s"]
        self.lock = threading.RLock()
        self.running = {}          # conversation id -> Popen
        self.subs = {}             # conversation id -> [(loop, asyncio.Queue)]
        self.threads = {}

    # -- the store ----------------------------------------------------------------

    def root(self):
        return os.path.join(self.home, "console")

    def _dir(self, cid):
        if not cid or "/" in cid or cid.startswith("."):
            raise KeyError(cid)
        return os.path.join(self.root(), cid)

    def get(self, cid):
        try:
            with open(os.path.join(self._dir(cid), "meta.json")) as fp:
                return json.load(fp)
        except (KeyError, OSError, ValueError):
            return None

    def _save(self, meta):
        from .. import fsutil
        fsutil.atomic_write(os.path.join(self._dir(meta["id"]), "meta.json"),
                            json.dumps(meta, indent=1, sort_keys=True))

    def list(self, key=None):
        """Conversations, the latest first; only ``key``'s when given."""
        out = []
        try:
            names = os.listdir(self.root())
        except OSError:
            return out
        for n in names:
            m = self.get(n)
            if m is not None and (key is None or m.get("scope") == key):
                out.append(m)
        out.sort(key=lambda m: (m.get("updated", 0), m["id"]), reverse=True)
        return out

    def latest(self, key):
        got = self.list(key)
        return got[0] if got else None

    def new(self, scope, cwd, by, model=None, project_dir=None, mode="console"):
        cid = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
        os.makedirs(self._dir(cid), exist_ok=True)
        now = time.time()
        meta = {"id": cid, "scope": scope_key(scope), "kind": scope["kind"],
                "project": scope.get("project"), "wpid": scope.get("wpid"),
                "cwd": cwd, "project_dir": project_dir, "by": by,
                "model": model or config(self.home)["model"],
                "session": str(uuid.uuid4()), "started": False, "created": now,
                "updated": now, "title": "", "turns": 0, "cost": 0.0, "mode": mode}
        self._save(meta)
        return meta

    def update(self, cid, **kw):
        with self.lock:
            m = self.get(cid)
            if m is None:
                raise KeyError(cid)
            m.update(kw, updated=time.time())
            self._save(m)
            return m

    def transcript(self, cid, last=200):
        try:
            with open(os.path.join(self._dir(cid), "transcript.jsonl")) as fp:
                lines = fp.readlines()
        except (KeyError, OSError):
            return []
        out = []
        for ln in lines[-last:]:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out

    def append(self, cid, ev):
        """Record ``ev`` in the transcript and send it to the open sockets."""
        ev = dict(ev, t=ev.get("t") or time.time())
        with self.lock:
            with open(os.path.join(self._dir(cid), "transcript.jsonl"), "a") as fp:
                fp.write(json.dumps(ev) + "\n")
        self.publish(cid, ev)
        return ev

    # -- sockets ------------------------------------------------------------------

    def subscribe(self, cid, loop, queue):
        with self.lock:
            self.subs.setdefault(cid, []).append((loop, queue))

    def unsubscribe(self, cid, queue):
        with self.lock:
            self.subs[cid] = [s for s in self.subs.get(cid, []) if s[1] is not queue]

    def publish(self, cid, ev):
        with self.lock:
            subs = list(self.subs.get(cid, []))
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
            except RuntimeError:          # that loop has closed
                pass

    # -- replies ------------------------------------------------------------------

    def busy(self, cid):
        return cid in self.running

    def ask(self, cid, text, by, primer, propose=None, auto=None):
        """Start the reply to ``text``; it streams to the transcript. Raises Busy.
        ``propose(text)``: the slash commands a reply proposes (C3), kept with
        it as ``props``; ``auto(line)``: runs the ones marked ``auto`` at once,
        and their cards go in the transcript after the reply's text."""
        with self.lock:
            if cid in self.running:
                raise Busy("still answering the last question: wait, or /cancel")
            if len(self.running) >= self.max_running:
                raise Busy("%d conversations are answering already; try again shortly"
                           % len(self.running))
            meta = self.get(cid)
            if meta is None:
                raise KeyError(cid)
            if meta.get("mode") == "studio":
                _check_taken(meta, by)
            self.running[cid] = None      # held until the process starts
        try:
            d = self._dir(cid)
            with open(os.path.join(d, "primer.md"), "w") as fp:
                fp.write(primer)
            self.append(cid, {"k": "ask", "text": text, "by": by})
            if not meta.get("title"):
                meta = self.update(cid, title=text.strip().splitlines()[0][:80])
            argv = self.command(meta, os.path.join(d, "primer.md"))
            env = dict(os.environ, WPK_HOME=self.home, WPK_CONSOLE=cid,
                       PATH=os.path.dirname(sys.executable) + os.pathsep
                       + os.environ.get("PATH", ""))
            env.pop("CLAUDECODE", None)
            if meta.get("mode") == "studio":
                env.update(self._studio_env(meta))
            from .. import hooks
            hooks.prepare_env("claude", meta.get("mode") or "console", env,
                              wpid=meta.get("wpid"), project_dir=meta.get("project_dir"),
                              cwd=meta["cwd"])
            err = open(os.path.join(d, "stderr.log"), "a")
            p = subprocess.Popen(argv, cwd=meta["cwd"], env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=err, text=True,
                                 start_new_session=True)
            err.close()
        except Exception as ex:                       # noqa: BLE001: tell the drawer
            with self.lock:
                self.running.pop(cid, None)
            self.append(cid, {"k": "end", "ok": False, "cost": 0.0,
                              "error": "could not start the agent: %s" % ex})
            return
        with self.lock:
            self.running[cid] = p
        self.publish(cid, {"k": "busy", "on": True})
        t = threading.Thread(target=self._reply, args=(cid, p, text, propose, auto),
                             daemon=True, name="console-" + cid)
        self.threads[cid] = t
        t.start()

    def command(self, meta, primer_path):
        if meta.get("mode") == "studio":
            return self._studio_command(meta, primer_path)
        cfg = config(self.home)
        exe = shlex.split(os.environ.get("WPK_CLAUDE") or "claude")
        argv = exe + ["-p", "--output-format", "stream-json", "--verbose",
                      "--model", meta["model"], "--permission-mode", "dontAsk",
                      "--max-budget-usd", "%.2f" % cfg["budget_usd"],
                      "--tools", ",".join(TOOLS), "--allowedTools", ",".join(ALLOWED),
                      "--strict-mcp-config", "--setting-sources", "",
                      "--disable-slash-commands",
                      "--append-system-prompt-file", primer_path]
        for extra in (self.home, meta.get("project_dir")):
            if extra and extra != meta["cwd"]:
                argv += ["--add-dir", extra]
        if meta.get("started"):
            argv += ["--resume", meta["session"]]
        else:
            argv += ["--session-id", meta["session"]]
        return argv

    def _studio_spec(self, meta, primer_path):
        from .. import executor, harness, notes, project
        pkt = _packet(meta)
        st = project.settings(meta["project_dir"])
        tools = list(STUDIO_TOOLS) + [t for t in st.allowed_tools if t not in STUDIO_TOOLS]
        return harness.StepSpec(
            model=meta["model"], session_id=meta["session"], permission_mode="acceptEdits",
            allowed_tools=tools, budget_usd=st.step_budget_usd,
            add_dirs=[x for x in executor.step_dirs(pkt) if x != meta["cwd"]],
            system_file=primer_path,
            notes=(notes.inbox(pkt), os.path.join(self._dir(meta["id"]), notes.SEEN)),
            resume_same=bool(meta.get("started")))

    def _studio_command(self, meta, primer_path):
        from .. import harness
        return harness.get("claude").command(self._studio_spec(meta, primer_path))

    def _studio_env(self, meta):
        from .. import harness
        out = harness.get("claude").env(self._studio_spec(meta, os.devnull))
        out.update(WPK_PROTECT=protected(meta["project_dir"]), WPK_STUDIO=meta["id"])
        pkt = _packet(meta)
        allow = [pkt.state_dir]                         # the plan (docs/studio-v2.md §3)
        if os.path.normpath(meta["cwd"]) != os.path.normpath(pkt.path):
            allow.append(meta["cwd"])                   # a child's work/, not its run dir
        out["WPK_PROTECT_ALLOW"] = os.pathsep.join(allow)
        return out

    def _say(self, cid, text, propose, auto):
        ev = {"k": "say", "text": text, "id": secrets.token_hex(4)}
        props = propose(text) if propose else []
        if props:
            ev["props"] = props
        self.append(cid, ev)
        for pr in props:
            if pr["auto"] and auto is not None:
                try:
                    out = auto(pr["line"])
                except Exception as ex:               # noqa: BLE001: a card, not a crash
                    out = {"ok": False, "cmd": None, "text": str(ex), "lines": []}
                self.append(cid, {"k": "cmd", "line": pr["line"], "by": "agent", "out": out,
                                  "ref": "%s:%d" % (ev["id"], pr["i"]), "auto": True})

    def _reply(self, cid, p, text, propose=None, auto=None):
        timer = threading.Timer(self.timeout_s, self._kill, args=(p, "timed out"))
        timer.daemon = True
        timer.start()
        end = {"k": "end", "ok": False, "cost": 0.0}
        started = False
        try:
            p.stdin.write(text)
            p.stdin.close()
        except OSError:
            pass
        try:
            with open(os.path.join(self._dir(cid), "stream.jsonl"), "a") as raw:
                for ln in p.stdout:
                    raw.write(ln)
                    raw.flush()
                    try:
                        ev = json.loads(ln)
                    except ValueError:
                        continue
                    typ = ev.get("type")
                    if typ == "system" and ev.get("subtype") == "init":
                        started = True
                    elif typ == "assistant":
                        for b in (ev.get("message") or {}).get("content") or []:
                            if b.get("type") == "text" and b.get("text", "").strip():
                                self._say(cid, b["text"], propose, auto)
                            elif b.get("type") == "tool_use":
                                self.append(cid, {"k": "tool", "name": b.get("name"),
                                                  "what": _what(b.get("input") or {})})
                    elif typ == "result":
                        end.update(ok=not ev.get("is_error"),
                                   cost=float(ev.get("total_cost_usd") or 0.0))
                        if ev.get("is_error"):
                            end["error"] = ev.get("result") or ev.get("subtype") or "error"
            code = p.wait()
        finally:
            timer.cancel()
        if getattr(p, "wpk_why", None):
            end.update(ok=False, error=p.wpk_why)
        elif code != 0 and end["ok"]:
            end.update(ok=False, error="the agent exited with %d" % code)
        elif code != 0 and "error" not in end:
            end["error"] = "the agent exited with %d (stderr.log has more)" % code
        with self.lock:
            m = self.get(cid)
            if m is not None:
                # A resumed reply's cost is the chain's total so far (harness Caps).
                self.update(cid, started=m.get("started") or started,
                            turns=m.get("turns", 0) + 1,
                            cost=max(m.get("cost", 0.0), end["cost"]))
            self.running.pop(cid, None)
            self.threads.pop(cid, None)
        self.append(cid, end)
        self.publish(cid, {"k": "busy", "on": False})

    def _kill(self, p, why):
        p.wpk_why = why
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            return
        def hard():
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        threading.Timer(KILL_AFTER_S, hard).start()

    def cancel(self, cid):
        """Stop the reply that is running; False if none is."""
        with self.lock:
            p = self.running.get(cid)
        if p is None:
            return False
        self._kill(p, "cancelled")
        return True

    def wait(self, cid, timeout=30):
        """Until the reply that is running ends (for tests and shutdown)."""
        t = self.threads.get(cid)
        if t is not None:
            t.join(timeout)

    def shutdown(self):
        with self.lock:
            procs = [p for p in self.running.values() if p is not None]
        for p in procs:
            self._kill(p, "the server stopped")


def _packet(meta):
    from ..packet import Packet
    return Packet(layout.run_dir(meta["project_dir"], meta["wpid"]))


def _check_taken(meta, by):
    """Raise NotTaken unless ``by`` has taken the conversation's packet."""
    from .. import executor, frontmatter
    try:
        st, _ = _packet(meta).load_status()
    except (OSError, frontmatter.FrontMatterError) as ex:
        raise NotTaken("cannot read the packet: %s" % ex) from None
    owner = executor.taken_by(st)
    if owner != by:
        raise NotTaken("%s is %s; the studio's agent works only for whoever has taken it" % (
            meta["wpid"][:8], "taken by %s" % owner if owner else "not taken"))


def protected(project_dir):
    """``WPK_PROTECT`` for the path hook: what wpk keeps of the project."""
    if layout.is_packet_layout(project_dir):
        return project_dir
    return os.pathsep.join((layout.runs_dir(project_dir),
                            os.path.join(project_dir, "project.toml")))


def studio_place(entry, wpid):
    """The studio agent's cwd for packet ``wpid`` of ``entry``: the packet
    folder for the root, a child's ``work/`` (or its run directory)."""
    if wpid == entry.get("root"):
        return layout.packet_folder(entry["path"])
    rd = layout.run_dir(entry["path"], wpid)
    w = os.path.join(rd, "work")
    return w if os.path.isdir(w) else rd


def _what(inp):
    for k in ("command", "file_path", "pattern", "path"):
        if inp.get(k):
            return str(inp[k])[:200]
    return json.dumps(inp)[:200]


# --- where an agent starts, and what it is told --------------------------------

def place(scope, ctx):
    """``(cwd, project_dir)`` for a conversation in ``scope`` (C-Q1)."""
    if scope.get("project"):
        e = ctx.entry(scope["project"])
        if e is not None:
            return layout.packet_folder(e["path"]), e["path"]
    return source_repo() or ctx.home or registry.home(), None


def primer(scope, ctx, meta):
    """The system prompt's addition for one reply: the guide, the scope and its
    state now, and the slash commands."""
    from . import console
    try:
        with open(GUIDE, encoding="utf-8") as fp:
            out = [fp.read().rstrip(), ""]
    except OSError:
        out = []
    out += ["## Scope", ""]
    if scope.get("wpid"):
        out.append("A packet: %s in project %s%s." % (
            scope["wpid"], scope["project"],
            ", looking at step %s" % scope["step"] if scope.get("step") else ""))
    elif scope.get("project"):
        out.append("A project: %s." % scope["project"])
    else:
        out.append("The server as a whole%s." % (
            ", looking at scheduler run %s" % scope["run"] if scope.get("run") else ""))
    out += ["", "- cwd: %s" % meta["cwd"], "- WPK_HOME: %s" % (ctx.home or registry.home())]
    if meta.get("project_dir"):
        out.append("- project directory: %s" % meta["project_dir"])
        if scope.get("wpid"):
            out.append("- packet directory: %s" % layout.run_dir(meta["project_dir"],
                                                                 scope["wpid"]))
    out.append("")
    if scope.get("project"):
        card = console.run("/show", scope, ctx)
        out += ["## State now (/show)", "", card["text"]]
        out += ["  " + ln["text"] for ln in card["lines"]]
    else:
        out += ["## Projects", ""]
        for e in ctx.projects()[:40]:
            out.append("- %s: %s" % (e["name"], e["path"]))
    out += ["", "## Slash commands (the person runs these)", ""]
    for c in console.complete():
        out.append("- /%s %s: %s%s" % (c["name"], c["usage"], c["help"],
                                        "" if c["changes"] else " (read-only)"))
    return "\n".join(out) + "\n"
