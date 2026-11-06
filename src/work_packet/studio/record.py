"""A studio session as one step (docs/studio-plan.md S1.8; the design §5.1).

At close, the session becomes the packet's next step with ``worker: studio``
(``checkpoint.record``, worker ``studio``): the agent's raw stream as ``transcript.jsonl``
(so stats read its tokens like any step's), the conversation as the board
showed it (``studio-transcript.jsonl``), the cost, the time it was open, the
files it changed, and a summary. A session that neither talked nor changed
anything records nothing.

The summary is the person's, when they give one; else a draft:
``draft_summary`` asks a cheap model (the console's) for two or three
sentences from the conversation's opening and the files changed, and falls
back to a plain account of the facts when there is no model or it fails.
"""

import json
import os
import shlex
import subprocess
import time

from .. import checkpoint, harness, model, registry, schema

DRAFT_TIMEOUT_S = 60
DRAFT_CHARS = 6000


def _conv_dir(home, cid):
    return os.path.join(home or registry.home(), "console", cid) if cid else None


def _conv(home, cid):
    d = _conv_dir(home, cid)
    if not d:
        return {}, []
    try:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as fp:
            meta = json.load(fp)
    except (OSError, ValueError):
        meta = {}
    events = []
    try:
        with open(os.path.join(d, "transcript.jsonl"), encoding="utf-8") as fp:
            for ln in fp:
                try:
                    events.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        pass
    return meta, events


def facts(entry, wpid, session, home=None, now=None):
    """What the session did: ``{turns, cost, minutes, asks, created, modified,
    deleted, conv}``."""
    from . import model as studio
    meta, events = _conv(home, session.get("conv"))
    created, modified, deleted = studio.changed(entry, wpid)
    end = now or time.time()
    return {"turns": meta.get("turns", 0), "cost": float(meta.get("cost") or 0.0),
            "minutes": max(0, int(round((end - session["opened"]) / 60.0))),
            "asks": [e.get("text", "") for e in events if e.get("k") == "ask"],
            "created": created, "modified": modified, "deleted": deleted,
            "conv": meta, "events": events}


def plain_summary(f, by):
    """The facts as a summary, when no model drafts one."""
    parts = ["Studio session by %s: %d minute%s, %d turn%s." % (
        by, f["minutes"], "" if f["minutes"] == 1 else "s", f["turns"],
        "" if f["turns"] == 1 else "s")]
    if f["asks"]:
        first = " ".join(f["asks"][0].split())
        parts.append("Started with: \"%s\"." % (first[:200] + ("…" if len(first) > 200 else "")))
    for word, paths in (("Created", f["created"]), ("Changed", f["modified"]),
                        ("Deleted", f["deleted"])):
        if paths:
            more = len(paths) - 8
            parts.append("%s %s%s." % (word, ", ".join(paths[:8]),
                                       " and %d more" % more if more > 0 else ""))
    if not (f["created"] or f["modified"] or f["deleted"]):
        parts.append("No files changed.")
    return "\n\n".join(parts)


def draft_summary(entry, wpid, session, home=None, now=None):
    """A drafted summary for the close dialog: (text, how), ``how`` "model" or
    "facts"."""
    f = facts(entry, wpid, session, home, now)
    plain = plain_summary(f, session["by"])
    if not f["events"]:
        return plain, "facts"
    convo = []
    for e in f["events"]:
        if e.get("k") == "ask":
            convo.append("Person: " + e.get("text", ""))
        elif e.get("k") == "say":
            convo.append("Agent: " + e.get("text", ""))
        elif e.get("k") == "tool":
            convo.append("(tool %s %s)" % (e.get("name"), e.get("what", "")))
    text = "\n".join(convo)[:DRAFT_CHARS]
    prompt = ("Write the summary of this studio session for the packet's step log: two "
              "or three plain sentences saying what was asked, what was made or "
              "changed, and what is left open. No heading, no list.\n\nFiles: created "
              "%s; changed %s; deleted %s.\n\nThe conversation (its start):\n\n%s\n" % (
                  ", ".join(f["created"]) or "none", ", ".join(f["modified"]) or "none",
                  ", ".join(f["deleted"]) or "none", text))
    from ..dash import agent as agentmod
    exe = shlex.split(os.environ.get("WPK_CLAUDE") or "claude")
    argv = exe + ["-p", "--output-format", "json", "--model",
                  agentmod.config(home)["model"], "--tools", "", "--strict-mcp-config",
                  "--setting-sources", "", "--disable-slash-commands",
                  "--max-budget-usd", "0.05"]
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    try:
        p = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                           timeout=DRAFT_TIMEOUT_S, env=env)
        out = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
        got = (out.get("result") or "").strip() if isinstance(out, dict) else ""
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        got = ""
    if not got:
        return plain, "facts"
    return got, "model"


def record(entry, wpid, session, summary=None, home=None, now=None, next_action=None):
    """Record the session as a step, a checkpoint by worker ``studio``
    (docs/session-checkpoint.md §3). Returns the step number, or None when the
    session did nothing."""
    from . import model as studio
    f = facts(entry, wpid, session, home, now)
    if not f["turns"] and not (f["created"] or f["modified"] or f["deleted"]):
        return None
    text = (summary or "").strip() or plain_summary(f, session["by"])
    end = now or time.time()
    cd = _conv_dir(home, session.get("conv"))
    files = {}
    if cd:
        for src, name in (("stream.jsonl", "transcript.jsonl"),
                          ("transcript.jsonl", "studio-transcript.jsonl")):
            if os.path.isfile(os.path.join(cd, src)):
                files[name] = os.path.join(cd, src)
    res = model.StepResult()
    if "transcript.jsonl" in files:
        harness.get("claude").parse(files["transcript.jsonl"], res)
    meta = {
        "start": schema.format_timestamp(_utc(session["opened"])),
        "end": schema.format_timestamp(_utc(end)),
        "duration_s": round(end - session["opened"], 3),
        "harness": "claude", "model": f["conv"].get("model"),
        "session_id": f["conv"].get("session"),
        "cost_usd": round(f["cost"], 6) if f["turns"] else 0.0,
        "tokens": res.tokens or {}, "api_s": res.api_s,
        "studio": {"by": session["by"], "turns": f["turns"], "conversation": session.get("conv"),
                   "created": f["created"], "modified": f["modified"], "deleted": f["deleted"],
                   "versions": _versions(entry, wpid, session), "comments": 0},
    }
    if res.context:
        meta["context"] = model.context_summary(res.context)
    status, _, rest = text.partition("\n")
    out, n = checkpoint.record(studio.packet(entry, wpid), status, body=rest,
                               next_action=next_action, worker="studio", by=session["by"],
                               meta=meta, files=files)
    if out.code != 0:
        raise studio.StudioError("could not record the session: %s" % out.msg)
    return n


def _utc(t):
    import datetime
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc)


def _versions(entry, wpid, session):
    """The versions made in this session (docs/studio-plan.md S3.2)."""
    from . import versions
    return versions.since(entry, wpid, session["opened"])
