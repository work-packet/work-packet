"""The board's console (docs/console.md): a drawer on every page.

A line that starts with ``/`` is a slash command. It is parsed here and run
by ``actions.py`` (or ``executor``, as the board's buttons do), with no model.
The page the drawer is on sets the scope: on a packet's page ``/pause``
pauses that packet. A command can name another target: a project, a packet
id (or a unique prefix of one), or ``project/wpid``. Commands that take text
(``/note``, ``/handoff``, ``/answer``) name a target as ``@target``.

``run`` returns ``{ok, cmd, text, lines: [{text, href?}], href?}``. The
drawer renders it with textContent only, so nothing here is HTML.
"""

import os
import shlex
import time
import urllib.parse

from .. import archived, executor, layout, registry

# Pages whose first path parts are not a project's: /p/<project>/<these>.
_PROJECT_TABS = {"tasks", "steps", "cost", "settings", "compose", "board", "doc", "pr",
                 "run", "ide", "markup", "shell", "console"}


class Usage(Exception):
    """A command line that cannot run; the message says why."""


def scope_of(path):
    """What the page at ``path`` is about: ``{kind, project, wpid, step, run}``.
    ``kind`` is ``server``, ``project`` or ``packet``."""
    parts = [urllib.parse.unquote(p) for p in (path or "/").split("?")[0].strip("/").split("/") if p]
    sc = {"kind": "server", "project": None, "wpid": None, "step": None, "run": None}
    if len(parts) >= 2 and parts[0] == "p":
        sc.update(kind="project", project=parts[1])
        if len(parts) >= 3 and parts[2] not in _PROJECT_TABS:
            sc.update(kind="packet", wpid=parts[2])
            if len(parts) >= 4 and parts[3] not in ("live", "file", "plan", "act"):
                sc["step"] = parts[3]
    elif len(parts) >= 2 and parts[0] == "runs":
        sc["run"] = parts[1]
    return sc


class Ctx:
    """What a command may use: ``home``, who is asking (``by``, ``principal``),
    ``poke()`` for the runner after a change, and the conversations
    (``agents``: ``dash.agent.Agents``; None without the agent). ``conv`` is
    the scope's current conversation, set by ``line``."""

    def __init__(self, home=None, by=None, principal=None, poke=None, agents=None):
        self.home, self.by, self.principal = home, by, principal
        self.poke = poke or (lambda: None)
        self.agents = agents
        self.conv = None

    def entry(self, name):
        try:
            return archived.get(name, self.home)
        except (KeyError, OSError, ValueError, registry.ConfigError):
            return None

    def projects(self):
        return list(archived.entries(self.home))

    def allowed(self, action, target=None):
        """None, or why ``principal`` may not ``action``."""
        from ..sched import authz
        try:
            authz.check(self.principal, action, target, self.home)
        except authz.Denied as ex:
            return str(ex)
        return None


# --- targets -----------------------------------------------------------------

def _wpids(e):
    try:
        return sorted(os.listdir(layout.runs_dir(e["path"])))
    except OSError:
        return []


def _match(e, prefix):
    hits = [w for w in _wpids(e) if w.startswith(prefix)]
    if prefix in hits:
        return prefix
    if len(hits) > 1:
        raise Usage("%s matches %d packets in %s" % (prefix, len(hits), e["name"]))
    return hits[0] if hits else None


def resolve(arg, scope, ctx):
    """``(entry, wpid or None)`` for a target ``arg``, or the scope's when None."""
    if not arg:
        if scope["project"] is None:
            raise Usage("name a project or packet: this page is not about one")
        e = ctx.entry(scope["project"])
        if e is None:
            raise Usage("no project %s" % scope["project"])
        return e, scope["wpid"]
    arg = arg.lstrip("@")
    if "/" in arg:
        name, _, w = arg.partition("/")
        e = ctx.entry(name)
        if e is None:
            raise Usage("no project %s" % name)
        wpid = _match(e, w) if w else None
        if w and wpid is None:
            raise Usage("no packet %s in %s" % (w, name))
        return e, wpid
    here = ctx.entry(scope["project"]) if scope["project"] else None
    if here is not None:
        w = _match(here, arg)
        if w:
            return here, w
    e = ctx.entry(arg)
    if e is not None:
        return e, None
    found = []
    for e in ctx.projects():
        w = _match(e, arg)
        if w:
            found.append((e, w))
    if len(found) == 1:
        return found[0]
    if found:
        raise Usage("%s matches packets in %s" % (arg, ", ".join(e["name"] for e, _ in found)))
    raise Usage("no project or packet %s" % arg)


def _href(e, wpid=None):
    url = "/p/%s" % urllib.parse.quote(e["name"])
    return url + "/%s" % wpid if wpid else url


def _pkt(e, wpid):
    from ..packet import Packet
    return Packet(layout.run_dir(e["path"], wpid))


def _need_packet(e, wpid, cmd):
    if wpid is None:
        raise Usage("/%s works on a packet: name one, or open its page" % cmd)
    return _pkt(e, wpid)


def _writable(e):
    if archived.is_archived(e):
        raise Usage("%s is archived: its runs were removed and it is shown from the"
                    " history store, read-only" % e["name"])


def _split_at(args):
    """``(target or None, the other args)``: a target is written ``@target``."""
    at = [a for a in args if a.startswith("@") and len(a) > 1]
    if len(at) > 1:
        raise Usage("one @target at a time")
    return (at[0][1:] if at else None), [a for a in args if a not in at]


def _out(out, cmd, href=None):
    return {"ok": out.code == 0, "cmd": cmd, "text": out.msg, "lines": [], "href": href}


# --- commands ----------------------------------------------------------------

def c_help(args, scope, ctx):
    if args:
        c = COMMANDS.get(args[0].lstrip("/"))
        if c is None:
            raise Usage("no command /%s" % args[0].lstrip("/"))
        return {"ok": True, "cmd": "help", "text": "/%s %s" % (c.name, c.usage),
                "lines": [{"text": c.help}]}
    here = {"server": "this page is not about a project",
            "project": "here: project %s" % scope["project"],
            "packet": "here: packet %s in %s" % ((scope["wpid"] or "")[:8], scope["project"])}
    return {"ok": True, "cmd": "help", "text": "Commands (%s)" % here[scope["kind"]],
            "lines": [{"text": "/%s %s  —  %s" % (c.name, c.usage, c.help)}
                      for c in COMMANDS.values()]}


def c_show(args, scope, ctx):
    from . import data
    from .. import questions
    e, wpid = resolve(args[0] if args else None, scope, ctx)
    if wpid:
        p = data.packet(e, wpid)
        if p is None:
            raise Usage("no packet %s in %s" % (wpid, e["name"]))
        m = p["meta"]
        lines = [{"text": "%s: %s" % (k, v)} for k, v in p["fields"]]
        if p["pausing"]:
            lines.append({"text": "pause requested: it pauses when its step ends"})
        qs = questions.of_packet(_pkt(e, wpid))
        if qs:
            lines.append({"text": "%d open question(s): /questions" % len(qs)})
        for k in p["children"]:
            lines.append({"text": "child %s %s %s" % (k["short"], k["state"], k["name"] or ""),
                          "href": _href(e, k["wpid"])})
        title = (p["summary"].splitlines() or [""])[0]
        return {"ok": True, "cmd": "show", "href": _href(e, wpid),
                "text": "%s %s · %s%s" % (e["name"], wpid[:8], m.get("state"),
                                          " · " + title if title else ""), "lines": lines}
    c = data.card(e)
    lines = [{"text": "%s: %d" % (s, n)} for s, n in c["counts"]]
    if c["running"]:
        r = c["running"]
        lines.insert(0, {"text": "running %s step %s for %s%s" % (
            r["short"], r["step"], r["for"], ": " + r["now"] if r.get("now") else ""),
            "href": _href(e, r["wpid"])})
    lines.append({"text": "cost $%.2f (today $%.2f) · last step %s" % (
        c["spend_total"], c["spend_today"], c["last_step"])})
    return {"ok": True, "cmd": "show", "href": _href(e),
            "text": "%s · %s · %d packet(s)" % (e["name"], c["column"], c["packets"]),
            "lines": lines}


def c_questions(args, scope, ctx):
    from .. import questions
    e, wpid = resolve(args[0] if args else None, scope, ctx)
    pkt = _need_packet(e, wpid, "questions")
    qs = questions.of_packet(pkt)
    if not qs:
        return {"ok": True, "cmd": "questions", "text": "%s has no open questions" % wpid[:8],
                "lines": [], "href": _href(e, wpid)}
    lines = []
    for q in qs:
        lines.append({"text": "%s: %s" % (q["id"], q["q"])})
        if q["choices"]:
            lines.append({"text": "    choices: %s" % ", ".join(map(str, q["choices"]))})
        if q["recommend"]:
            lines.append({"text": "    recommended: %s" % q["recommend"]})
    lines.append({"text": "answer with /answer id=text …, or /answer -r to take the"
                          " recommendations"})
    return {"ok": True, "cmd": "questions", "href": _href(e, wpid),
            "text": "%s: %d open question(s)" % (wpid[:8], len(qs)), "lines": lines}


def _pause_resume(op):
    def c(args, scope, ctx):
        from .. import actions
        e, wpid = resolve(args[0] if args else None, scope, ctx)
        _writable(e)
        if wpid is None:
            fn = actions.pause_project if op == "pause" else actions.resume_project
            out = fn(e, ctx.by)
        else:
            out = executor.admin(_pkt(e, wpid), op, None, None, ctx.by)
            if op == "pause" and out.code == 0:
                from ..sched import control
                control.cancel_pending(wpid, ctx.principal, ctx.home)
        if out.code == 0 and op == "resume":
            ctx.poke()
        return _out(out, op, _href(e, wpid))
    return c


def c_keep(args, scope, ctx):
    e, wpid = resolve(args[0] if args else None, scope, ctx)
    _writable(e)
    return _out(executor.withdraw_pause(_need_packet(e, wpid, "keep")), "keep", _href(e, wpid))


def c_stop(args, scope, ctx):
    from .. import actions
    e, wpid = resolve(args[0] if args else None, scope, ctx)
    if wpid is not None and args:
        raise Usage("/stop works on a project: name one")
    _writable(e)
    why = ctx.allowed("cancel")
    if why:
        raise Usage(why)
    return _out(actions.stop_project(e, ctx.principal, ctx.home), "stop", _href(e))


def c_note(args, scope, ctx):
    from .. import actions
    t, rest = _split_at(args)
    wake = "--wake" in rest
    text = " ".join(a for a in rest if a != "--wake").strip()
    if not text:
        raise Usage("/note needs some text")
    e, wpid = resolve(t, scope, ctx)
    _writable(e)
    out = actions.note(_need_packet(e, wpid, "note"), text, ctx.by, wake)
    if out.code == 0 and wake:
        ctx.poke()
    return _out(out, "note", _href(e, wpid))


def c_handoff(args, scope, ctx):
    t, rest = _split_at(args)
    e, wpid = resolve(t, scope, ctx)
    _writable(e)
    out = executor.admin(_need_packet(e, wpid, "handoff"), "handoff",
                         " ".join(rest).strip() or None, None, ctx.by)
    if out.code == 0:
        ctx.poke()
    return _out(out, "handoff", _href(e, wpid))


def c_answer(args, scope, ctx):
    from .. import actions
    t, rest = _split_at(args)
    take, note, answers, i = False, None, {}, 0
    while i < len(rest):
        a = rest[i]
        if a in ("-r", "--recommended"):
            take = True
        elif a in ("-m", "--note"):
            if i + 1 >= len(rest):
                raise Usage("-m needs a note")
            note, i = rest[i + 1], i + 1
        elif "=" in a:
            k, _, v = a.partition("=")
            if v.strip():
                answers[k.strip()] = v
        else:
            raise Usage("%r: answers are id=text (quote text with spaces)" % a)
        i += 1
    if not answers and not take:
        raise Usage("/answer id=text …, or -r to take the recommendations")
    e, wpid = resolve(t, scope, ctx)
    _writable(e)
    out = actions.answer(_need_packet(e, wpid, "answer"), answers, note, take, ctx.by)
    if out.code == 0:
        ctx.poke()
    return _out(out, "answer", _href(e, wpid))


def c_open(args, scope, ctx):
    if not args:
        raise Usage("/open <project | packet | project/wpid>")
    e, wpid = resolve(args[0], scope, ctx)
    href = _href(e, wpid)
    return {"ok": True, "cmd": "open", "text": "opening %s" % href, "lines": [],
            "href": href, "go": True}


# --- the conversation (C2) ----------------------------------------------------

def _agents(ctx):
    if ctx.agents is None:
        raise Usage("the agent is not on in this board")
    return ctx.agents


def _conv(scope, ctx):
    """The scope's current conversation, made if there is none."""
    from . import agent
    ag = _agents(ctx)
    if ctx.conv is None:
        ctx.conv = ag.latest(agent.scope_key(scope))
    if ctx.conv is None:
        cwd, pdir = agent.place(scope, ctx)
        ctx.conv = ag.new(scope, cwd, ctx.by, project_dir=pdir)
    return ctx.conv


def c_model(args, scope, ctx):
    from . import agent
    m = _conv(scope, ctx)
    if not args:
        return {"ok": True, "cmd": "model", "text": "model: %s" % m["model"], "model": m["model"],
                "lines": [{"text": "the default is %s ([console] model in config.toml)"
                           % agent.config(ctx.home)["model"]}]}
    name = args[0]
    if not all(ch.isalnum() or ch in "-_.[]" for ch in name):
        raise Usage("%r is not a model name" % name)
    ctx.conv = _agents(ctx).update(m["id"], model=name)
    return {"ok": True, "cmd": "model", "lines": [], "model": name,
            "text": "model: %s from the next reply on" % name}


def c_new(args, scope, ctx):
    from . import agent
    ag = _agents(ctx)
    old = ctx.conv or ag.latest(agent.scope_key(scope))
    cwd, pdir = agent.place(scope, ctx)
    ctx.conv = ag.new(scope, cwd, ctx.by, model=old["model"] if old else None,
                      project_dir=pdir)
    return {"ok": True, "cmd": "new", "lines": [], "conv": ctx.conv["id"],
            "text": "a new conversation (%s, in %s)" % (ctx.conv["model"], cwd)}


def _when(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def c_sessions(args, scope, ctx):
    from . import agent
    ag = _agents(ctx)
    got = ag.list(agent.scope_key(scope))
    if args:
        hits = [m for m in got if m["id"].startswith(args[0]) or
                m["id"].split("-")[-1].startswith(args[0])]
        if len(hits) != 1:
            raise Usage("%s matches %d conversations here" % (args[0], len(hits)))
        ctx.conv = ag.update(hits[0]["id"])            # the latest is the current one
        return {"ok": True, "cmd": "sessions", "lines": [], "conv": ctx.conv["id"],
                "text": "back to %s: %s" % (ctx.conv["id"], ctx.conv["title"] or "(untitled)")}
    if not got:
        return {"ok": True, "cmd": "sessions", "text": "no conversations here yet",
                "lines": []}
    cur = ctx.conv["id"] if ctx.conv else got[0]["id"]
    lines = [{"text": "%s %s  %s · %s · %d repl%s · $%.2f  %s" % (
        "*" if m["id"] == cur else " ", m["id"], _when(m["updated"]), m["model"],
        m["turns"], "y" if m["turns"] == 1 else "ies", m["cost"],
        m["title"] or "(untitled)")} for m in got[:30]]
    return {"ok": True, "cmd": "sessions", "lines": lines,
            "text": "%d conversation(s) here; /sessions <id> goes back to one" % len(got)}


def c_cancel(args, scope, ctx):
    m = _conv(scope, ctx)
    if not _agents(ctx).cancel(m["id"]):
        raise Usage("the agent is not answering")
    return {"ok": True, "cmd": "cancel", "text": "stopping the reply", "lines": []}


def _draft(m, ag, head):
    """An instruction drafted from a conversation: ``head`` (or its first
    question), then its last exchanges as context."""
    ev = ag.transcript(m["id"])
    pairs, cur = [], None
    for x in ev:
        if x["k"] == "ask":
            cur = [x["text"], []]
            pairs.append(cur)
        elif x["k"] == "say" and cur is not None:
            cur[1].append(x["text"])
    if not head and not pairs:
        raise Usage("nothing to make a packet from: ask something first, or /packet <text>")
    out = [head or pairs[0][0], "",
           "Context, from the board's console (conversation %s, %s):" % (
               m["id"], os.path.join(ag.root(), m["id"], "transcript.jsonl")), ""]
    for q, says in pairs[-3:]:
        a = "\n".join(says).strip()
        if len(a) > 1500:
            a = a[:1500] + " …"
        out += ["> Q: " + q.replace("\n", "\n> "), ">", "> A: " + (a or "(no reply)").replace(
            "\n", "\n> "), ""]
    return "\n".join(out).strip() + "\n"


def c_packet(args, scope, ctx):
    ag = _agents(ctx)
    m = _conv(scope, ctx)
    text = _draft(m, ag, " ".join(args).strip())[:6000]
    if scope.get("project") and ctx.entry(scope["project"]) is not None:
        e = ctx.entry(scope["project"])
        _writable(e)
        href = "%s/compose?%s" % (_href(e), urllib.parse.urlencode({"instruction": text}))
        where = "Compose for %s" % e["name"]
    else:
        href = "/new?" + urllib.parse.urlencode({"objective": text})
        where = "New packet"
    return {"ok": True, "cmd": "packet", "text": "drafted; opening %s to edit it" % where,
            "lines": [], "href": href, "go": True}


class Cmd:
    def __init__(self, name, fn, usage, help, changes):
        self.name, self.fn, self.usage, self.help, self.changes = name, fn, usage, help, changes


COMMANDS = {c.name: c for c in [
    Cmd("help", c_help, "[command]", "list the commands, or explain one", False),
    Cmd("show", c_show, "[target]", "state of a packet or project", False),
    Cmd("questions", c_questions, "[packet]", "a packet's open questions", False),
    Cmd("open", c_open, "<target>", "go to a project's or packet's page", False),
    Cmd("pause", _pause_resume("pause"), "[target]",
        "pause a packet (after its step, if one runs) or a whole project", True),
    Cmd("resume", _pause_resume("resume"), "[target]",
        "resume a packet, or what was paused by hand in a project", True),
    Cmd("keep", c_keep, "[packet]", "take back a pause that has not happened yet", True),
    Cmd("stop", c_stop, "[project]", "pause a project and end its running steps", True),
    Cmd("note", c_note, "[@packet] [--wake] <text>", "leave a note for a packet's next step",
        True),
    Cmd("handoff", c_handoff, "[@packet] [note]", "hand a packet back to the runner", True),
    Cmd("answer", c_answer, "[@packet] id=text … [-r] [-m note]",
        "answer a packet's questions; -r takes the recommendations", True),
    Cmd("model", c_model, "[name]", "the agent's model for this conversation (e.g. haiku,"
        " sonnet, opus)", False),
    Cmd("new", c_new, "", "start a new conversation with the agent", False),
    Cmd("sessions", c_sessions, "[id]", "this page's conversations; go back to one", False),
    Cmd("cancel", c_cancel, "", "stop the agent's reply", False),
    Cmd("packet", c_packet, "[instruction]", "draft a packet from this conversation and open"
        " it in Compose (or New packet) to edit", False),
]}

# The agent may propose these (C3); the first ones run at once, the rest wait for a click.
AUTO = ("show", "questions", "help")
NOT_PROPOSED = ("model", "new", "sessions", "cancel")


def proposed(text):
    """The slash commands an agent's ``text`` proposes, one per line of its
    own: ``[{i, at, line, auto}]``; ``at`` is the line's index in ``text``."""
    out = []
    for at, raw in enumerate((text or "").split("\n")):
        ln = raw.strip().strip("`").strip()
        if ln.startswith("$ "):
            ln = ln[2:].strip()
        if not ln.startswith("/") or ln.startswith("//"):
            continue
        try:
            parts = shlex.split(ln[1:])
        except ValueError:
            continue
        if not parts or parts[0] not in COMMANDS or parts[0] in NOT_PROPOSED:
            continue
        out.append({"i": len(out), "at": at, "line": ln, "auto": parts[0] in AUTO})
    return out


def complete():
    """The command table for the drawer's completion and help."""
    return [{"name": c.name, "usage": c.usage, "help": c.help, "changes": c.changes}
            for c in COMMANDS.values()]


def line(text, scope, ctx, ref=None, decline=None):
    """One line from the drawer: a slash command, or a question for the agent.
    Both go in the scope's current conversation, which is made if needed; the
    result has its id as ``conv`` and the recorded event's time as ``t``.
    ``ref``: the proposal (``<say id>:<i>``) a command was run from;
    ``decline``: a proposal dismissed instead. Without ``ctx.agents``, slash
    commands only."""
    from . import agent
    text = (text or "").strip()
    if ctx.agents is None:
        return run(text, scope, ctx)
    if decline:
        m = _conv(scope, ctx)
        ev = ctx.agents.append(m["id"], {"k": "decline", "ref": str(decline), "by": ctx.by})
        return {"ok": True, "cmd": None, "declined": True, "text": "", "lines": [],
                "conv": m["id"], "t": ev["t"]}
    if not text:
        return {"ok": False, "cmd": None, "text": "nothing to send", "lines": []}
    if not text.startswith("/"):
        m = _conv(scope, ctx)
        try:
            ctx.agents.ask(m["id"], text, ctx.by, agent.primer(scope, ctx, m),
                           propose=proposed, auto=lambda ln: run(ln, scope, ctx))
        except agent.Busy as ex:
            return {"ok": False, "cmd": None, "text": str(ex), "lines": [], "conv": m["id"]}
        return {"ok": True, "cmd": None, "asked": True, "text": "", "lines": [],
                "conv": m["id"]}
    out = run(text, scope, ctx)
    m = _conv(scope, ctx)
    ev = {"k": "cmd", "line": text, "by": ctx.by, "out": out}
    if ref:
        ev["ref"] = str(ref)
    ev = ctx.agents.append(m["id"], ev)
    return dict(out, conv=m["id"], t=ev["t"])


def run(line, scope, ctx):
    """Run one slash-command ``line`` in ``scope``."""
    line = (line or "").strip()
    if not line.startswith("/"):
        return {"ok": False, "cmd": None, "lines": [],
                "text": "the agent is not on in this board; slash commands only: /help"}
    try:
        parts = shlex.split(line[1:])
    except ValueError as ex:
        return {"ok": False, "cmd": None, "text": "can't parse: %s" % ex, "lines": []}
    if not parts:
        parts = ["help"]
    c = COMMANDS.get(parts[0])
    if c is None:
        return {"ok": False, "cmd": parts[0], "lines": [],
                "text": "no command /%s: /help lists them" % parts[0]}
    try:
        return c.fn(parts[1:], scope, ctx)
    except Usage as ex:
        return {"ok": False, "cmd": c.name, "text": str(ex), "lines": []}
