"""``python -m work_packet.hookcmd <event>``: Claude Code's hooks in a packet folder
(docs/collaboration.md §4.3; spike: docs/collaboration-spike.md).

Claude Code runs this on its session and turn events wherever it works in a
packet: web or desktop VS Code, a terminal, a job. It keeps the presence record
of the session (``presence.py``) and writes the coarse ``session-start`` and
``session-end`` journal records. The board reads both to say who is on a packet
and whether Claude is waiting for you.

The event's JSON carries what was asked and said (``prompt``,
``last_assistant_message``, ``tool_input``). Only the fields in ``KEEP`` are
read; nothing else reaches a file. It never fails the session: every error is
logged to ``$WPK_HOME/logs/hook.log`` and the exit status is 0. It imports
little (``presence``, ``layout``; ``briefing`` at session start and on a prompt),
so it starts in tens of milliseconds.

At SessionStart it tells the session about its packet, and on each prompt it
passes on notes left on the board that the session has not seen
(``briefing``, docs/collaboration.md §7.1, §7.2).
"""

import getpass
import json
import os
import socket
import sys
import time

from . import layout, presence

EVENTS = ("SessionStart", "UserPromptSubmit", "PermissionRequest", "PostToolUse",
          "Notification", "Stop", "PreCompact", "SessionEnd")
KEEP = ("session_id", "cwd", "hook_event_name", "source", "reason", "tool_name",
        "notification_type", "transcript_path")
STDIN_MAX = 4 << 20
VIA = {"claude-vscode": "vscode", "cli": "terminal"}


def _ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _log(msg):
    home = os.environ.get("WPK_HOME") or os.path.expanduser("~/.work-packet")
    try:
        d = os.path.join(home, "logs")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "hook.log")
        if os.path.exists(p) and os.path.getsize(p) > 1 << 20:
            os.replace(p, p + ".1")
        with open(p, "a") as fp:
            fp.write("%s %s\n" % (_ts(time.time()), msg))
    except OSError:
        pass


def _root(proj):
    """The project's root WPID, from its ``project.toml``."""
    try:
        import tomllib
    except ImportError:             # Python 3.10
        import tomli as tomllib
    try:
        with open(os.path.join(proj, "project.toml"), "rb") as fp:
            return tomllib.load(fp).get("root")
    except (OSError, ValueError):
        return None


def _journal(proj, wpid, rec):
    """Append one record to the packet's journal: one ``write`` on an
    ``O_APPEND`` file, so it never tears a line a running step writes."""
    if not wpid:
        return
    p = os.path.join(layout.runs_dir(proj), wpid, "journal.jsonl")
    if not os.path.isfile(p):
        return
    line = (json.dumps(rec, sort_keys=True) + "\n").encode()
    fd = os.open(p, os.O_WRONLY | os.O_APPEND)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def _project(ev, env):
    """The project directory the session works in: ``WPK_PROJECT_DIR`` when it
    names one, else found from the session's cwd."""
    proj = env.get("WPK_PROJECT_DIR")
    if proj and os.path.isfile(os.path.join(proj, "project.toml")):
        return proj
    return presence.find_project(ev.get("cwd") or os.getcwd())


def via(env):
    """Where the session runs: ``ide-web`` (the board's web VS Code), ``ide-desktop``,
    ``terminal`` or the entrypoint as Claude names it."""
    ep = env.get("CLAUDE_CODE_ENTRYPOINT") or ""
    if ep == "claude-vscode":
        return "ide-web" if env.get("WPK_IDE_LAUNCH") else "ide-desktop"
    return VIA.get(ep, ep or "unknown")


def background(tasks):
    """What Claude still runs in the background (the ``background_tasks`` of a
    Stop: subagents, shells), as the record's ``background``: "2 background agents";
    "" when nothing runs. Its turn has ended, but it is not your move yet: it
    takes a turn of its own when they finish."""
    run = [t for t in tasks if isinstance(t, dict) and t.get("status") == "running"]
    if not run:
        return ""
    what = "agent" if all(t.get("type") == "subagent" for t in run) else "task"
    return "%d background %s%s" % (len(run), what, "s" if len(run) > 1 else "")


def handle(event, ev, env, now=None):
    """Apply one hook event (``ev``: its JSON, already cut to ``KEEP``). Returns
    ``(presence record or None, text for the session or "")``: the briefing at
    SessionStart, notes not yet shown at UserPromptSubmit (docs/collaboration.md §7)."""
    rec = _apply(event, ev, env, now)
    if rec is None or event not in ("SessionStart", "UserPromptSubmit"):
        return rec, ""
    proj, wpid = _project(ev, env), rec.get("wpid")
    from . import briefing
    if event == "SessionStart":
        if ev.get("source") == "compact":
            return rec, compact_nudge(proj, wpid, rec)  # it keeps the briefing in the summary
        return rec, briefing.briefing(proj, wpid)
    return rec, briefing.new_notes(proj, wpid, ev.get("session_id"), now)


NUDGE = ("The conversation was just compacted, and nobody has recorded a checkpoint "
         "for this packet since this session started. If you have changed things, "
         "suggest /wpk-checkpoint to the user, so the board knows where it stands.")


def compact_nudge(proj, wpid, rec):
    """After a compaction (docs/collaboration-plan.md G3): a short nudge when the
    packet has no checkpoint since the session started, else "". PreCompact can't
    talk to the session; the SessionStart that follows it can."""
    from . import checkpoint
    from .packet import Packet
    try:
        got = checkpoint.last(Packet(layout.run_dir(proj, wpid)))
    except Exception:                   # noqa: BLE001: no packet, no nudge
        return ""
    since = (rec or {}).get("since")
    if since is None or (got and got["t"] and got["t"] >= since):
        return ""
    return NUDGE


def _apply(event, ev, env, now=None):
    """The presence record and journal lines for one event (see ``handle``)."""
    now = time.time() if now is None else now
    if env.get("WPK_STEP"):
        return None                     # a runner step: the runner records itself
    sid = ev.get("session_id")
    if not sid:
        return None
    proj = _project(ev, env)
    if proj is None:
        return None
    wpid = env.get("WPK_WPID") or _root(proj)
    src = "claude-" + sid
    try:
        pid = int(env.get("CLAUDE_PID") or 0) or None
    except ValueError:
        pid = None
    try:
        by = getpass.getuser()
    except (KeyError, OSError):
        by = None
    tp = ev.get("transcript_path")
    tp = tp if isinstance(tp, str) and os.path.isabs(tp) and tp.endswith(".jsonl") else None
    base = dict(kind="claude", via=via(env), host=socket.gethostname(), pid=pid,
                session=sid, launch=env.get("WPK_IDE_LAUNCH"), wpid=wpid, by=by,
                transcript=tp)
    actor = {"kind": "claude", "via": base["via"], "session": sid}
    if event == "SessionStart":
        rec = presence.beat(proj, src, now, turn="waiting", **base)
        _journal(proj, wpid, {"type": "session-start", "t": _ts(now), "by": by,
                              "session": sid, "actor": actor,
                              "source": ev.get("source") or None})
        return rec
    if event == "SessionEnd":
        rec = presence.end(proj, src, now)
        _journal(proj, wpid, {"type": "session-end", "t": _ts(now), "by": by,
                              "session": sid, "actor": actor,
                              "reason": ev.get("reason") or None})
        return rec
    if event == "UserPromptSubmit":
        return presence.beat(proj, src, now, turn="working", tool="", **base)
    if event == "PermissionRequest":
        return presence.beat(proj, src, now, turn="blocked", tool=ev.get("tool_name") or "",
                             **base)
    if event == "PostToolUse":         # after an approval, it works again
        return presence.beat(proj, src, now, turn="working", tool="", **base)
    if event == "Notification":
        kind = ev.get("notification_type")
        if kind == "permission_prompt":
            return presence.beat(proj, src, now, turn="blocked", **base)
        if kind == "idle_prompt":
            if (presence.get(proj, src) or {}).get("background"):
                return presence.beat(proj, src, now, **base)    # still its work
            return presence.beat(proj, src, now, turn="waiting", idle_since=now, **base)
        return presence.beat(proj, src, now, **base)
    if event == "Stop":
        bg = ev.get("background") or ""
        return presence.beat(proj, src, now, turn="working" if bg else "waiting", tool="",
                             background=bg, **base)
    return presence.beat(proj, src, now, **base)       # PreCompact: still here


def main(argv=None, stdin=None, env=None):
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    stdin = sys.stdin if stdin is None else stdin
    try:
        event = argv[0] if argv else ""
        if event not in EVENTS:
            _log("unknown hook event %r" % event)
            return 0
        raw = stdin.read(STDIN_MAX)
        try:
            got = json.loads(raw) if raw.strip() else {}
        except ValueError:
            _log("%s: the event's JSON did not parse" % event)
            return 0
        ev = {k: got[k] for k in KEEP if isinstance(got, dict) and isinstance(
            got.get(k), (str, int))}
        if isinstance(got, dict) and isinstance(got.get("background_tasks"), list):
            ev["background"] = background(got["background_tasks"])
        _, say = handle(event, ev, env)
        if say:
            from .briefing import hook_output
            sys.stdout.write(hook_output(event, say) + "\n")
    except Exception as e:          # noqa: BLE001: a hook never breaks the session
        _log("%s: %s: %s" % (argv[:1], type(e).__name__, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
