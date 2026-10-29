"""Requests: a packet hands work to another project's agent (docs/delegation.md).

The step writes a brief, ``state/requests/<id>.md``. Sending it (``send``)
gives it to the root packet of another project, a new one or a stopped one, or
records that the owner took it elsewhere. ``sync`` brings the result back:
when the delegate finishes, its outcome goes to the requester as a note.

The index, ``$WPK_HOME/requests/<requester wpid>--<id>.json``, says where
each request is: ``sending``, ``open``, ``delivering`` (the note is written, the
requester's ``request`` record is not), ``delivered``.
"""

import json
import os

from . import clock, executor, frontmatter, fsutil, journal, layout, notes, registry, schema
from .lease import Lease, LeaseHeld
from .packet import Packet
from .project import ProjectError, load_project, project_of

DIR = "requests"                    # under state/, and under the runner home
BRIEF_FIELDS = ("title", "to", "repo")
REPO_FIELDS = ("name", "from", "branch", "share")
FINISHED = ("COMPLETED", "FAILED")


class RequestError(Exception):
    pass


def _ts():
    return schema.format_timestamp(clock.now())


# --- the brief ------------------------------------------------------------------------

def brief_path(state_dir, rid):
    return os.path.join(state_dir, DIR, rid + ".md")


def validate(meta, body):
    """Problem messages for a brief."""
    out = []
    if not isinstance(meta, dict) or not meta:
        return ["no front matter: title and to are required"]
    for k in meta:
        if k not in BRIEF_FIELDS:
            out.append("%s: unknown key" % k)
    if not isinstance(meta.get("title"), str) or not meta["title"].strip():
        out.append("title: required, a one-line string")
    if not schema.is_name(meta.get("to")):
        out.append("to: required, a project name ([a-z0-9][a-z0-9_-]*)")
    repos = meta.get("repo")
    if repos is not None:
        if not isinstance(repos, list) or not repos:
            out.append("repo: must be a list of {name, from}")
        else:
            for i, r in enumerate(repos):
                if not isinstance(r, dict) or not schema.is_name(r.get("name")) or \
                        not isinstance(r.get("from"), str) or not r["from"].strip():
                    out.append("repo[%d]: needs name and from" % i)
                    continue
                for k in r:
                    if k not in REPO_FIELDS:
                        out.append("repo[%d].%s: unknown key" % (i, k))
    if not (body or "").strip():
        out.append("the body is empty: it is the brief the other agent works from")
    return out


def load_brief(state_dir, rid):
    """(meta, body) of a valid brief; raises RequestError."""
    if not schema.is_name(rid):
        raise RequestError("%r is not a request id ([a-z0-9][a-z0-9_-]*)" % rid)
    path = brief_path(state_dir, rid)
    try:
        meta, body = frontmatter.load(path)
    except FileNotFoundError:
        raise RequestError("no brief state/%s/%s.md" % (DIR, rid)) from None
    except (OSError, frontmatter.FrontMatterError) as e:
        raise RequestError("state/%s/%s.md: %s" % (DIR, rid, e)) from None
    probs = validate(meta, body)
    if probs:
        raise RequestError("state/%s/%s.md: %s" % (DIR, rid, probs[0]))
    return meta, body


def instruction(meta, body, project, wpid):
    """The delegate's instruction: the brief, under a header that says who asked."""
    return ("# %s\n\nThis task is a request from packet %s of project %s. When it is "
            "finished, your completion report goes back to them, and they work from "
            "it without seeing anything else you did. So make the report's outcome and "
            "deliverables say exactly what changed and where: the repo, the branch and "
            "the commit, and how to check it.\n\n%s\n" % (
                meta["title"].strip(), wpid[:8], project, body.strip()))


# --- the index ------------------------------------------------------------------------

def index_dir(h=None):
    return os.path.join(h or registry.home(), DIR)


def _key(wpid, rid):
    return "%s--%s" % (wpid, rid)


def _ipath(wpid, rid, h=None):
    return os.path.join(index_dir(h), _key(wpid, rid) + ".json")


def get(wpid, rid, h=None):
    try:
        with open(_ipath(wpid, rid, h), encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return None


def _save(e, h=None):
    os.makedirs(index_dir(h), exist_ok=True)
    fsutil.atomic_write(_ipath(e["from"]["wpid"], e["id"], h), json.dumps(e, indent=1) + "\n")


def entries(h=None, wpid=None):
    """Every request in the index, oldest first; ``wpid``: one requester's
    (or one delegate's)."""
    out = []
    try:
        names = sorted(os.listdir(index_dir(h)))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(index_dir(h), n), encoding="utf-8") as fp:
                e = json.load(fp)
        except (OSError, ValueError):
            continue
        if wpid is None or e["from"]["wpid"] == wpid or e["to"].get("wpid") == wpid:
            out.append(e)
    out.sort(key=lambda e: e.get("sent") or "")
    return out


# --- journals ---------------------------------------------------------------------------

def _record_locked(pkt, rec):
    """Append ``rec`` to the packet's journal under its lease. False if a step holds it."""
    try:
        meta, _ = pkt.load_status()
        lz = Lease(pkt.lease_path, meta["step"] + 1, 0, 60).acquire()
    except LeaseHeld:
        return False
    try:
        journal.append(pkt.journal_path, rec)
    finally:
        lz.release()
    return True


# --- sending ----------------------------------------------------------------------------

def send(pkt, rid, to=None, path=None, external=None, by=None, h=None):
    """Send request ``rid`` of the requester ``pkt`` (§4). Returns the index entry."""
    from . import actions, project
    by = by or executor._who()
    meta, body = load_brief(pkt.state_dir, rid)
    old = get(pkt.wpid, rid, h)
    if old and old["state"] != "sending":
        raise RequestError("request %s was already sent (%s, %s)" % (
            rid, old["state"], _where(old)))
    proj = project_of(pkt.path)
    if proj is None:
        raise RequestError("%s is not in a project" % pkt.path)
    pname = load_project(proj)["name"]
    to = to or meta["to"]
    if not external and not schema.is_name(to):
        raise RequestError("%r is not a project name" % to)
    e = {"id": rid, "title": meta["title"].strip(),
         "from": {"project": pname, "wpid": pkt.wpid, "path": pkt.path},
         "to": {"external": external} if external else {"project": to},
         "sent": _ts(), "by": by, "state": "sending"}
    _save(e, h)
    if not external:
        text = instruction(meta, body, pname, pkt.wpid)
        ent = registry.get(to, h)
        if ent is not None:
            root = Packet(layout.run_dir(ent["path"], ent["root"]))
            try:
                st, _ = root.load_status()
            except (OSError, frontmatter.FrontMatterError) as ex:
                raise RequestError("%s: %s" % (to, ex)) from None
            if st["state"] not in executor.CONTINUE_FROM:
                raise RequestError("project %s is %s: send the request when it stops, or "
                                   "name a new project with --to" % (to, st["state"]))
            out = actions.continue_(root, text, note="A request from %s (%s)." % (
                pname, pkt.wpid[:8]), by=by)
            if out.code != executor.OK:
                raise RequestError("project %s: %s" % (to, out.msg))
            created = False
        else:
            # beside the requester's folder, never inside it (its repo, for a packet folder)
            dest = os.path.abspath(path) if path else os.path.join(
                os.path.dirname(layout.packet_folder(proj)), to)
            extra = {"setup": {"repo": [dict(r) for r in meta["repo"]]}} if meta.get("repo") \
                else None
            try:
                plan = project.new(to, text, path=dest, paused=True, h=h, extra=extra)
            except (ProjectError, OSError) as ex:
                raise RequestError("new project %s: %s" % (to, ex)) from None
            root = Packet(layout.run_dir(plan.path, plan.root))
            _start(plan.path, root, pname, by)
            created = True
        batch = executor.batch_of(journal.read(root.journal_path).records)
        e["to"].update(wpid=root.wpid, path=root.path, batch=batch, created=created)
        journal.append(root.journal_path, {
            "type": "request", "t": _ts(), "op": "received", "id": rid, "by": by,
            "from": {"project": pname, "wpid": pkt.wpid}, "title": e["title"]})
    if not _record_locked(pkt, {"type": "request", "t": _ts(), "op": "sent", "id": rid,
                                "by": by, "title": e["title"],
                                "to": {k: v for k, v in e["to"].items() if k != "path"}}):
        raise RequestError("a step of %s is running; send the request when it ends"
                           % pkt.wpid[:8])
    e["state"] = "open"
    _save(e, h)
    return e


def _start(proj, root, pname, by):
    """Set up a new delegate project and start it (docs/waiting-v1.md §5.1): the
    owner read the brief to say yes. Runs the safe setup fixes (the clones
    ``wpk doctor --fix`` would run); it stays PAUSED, naming what is missing,
    only when they leave something missing."""
    from . import setup
    name = proj
    try:
        tg = setup.target(proj)
        name = tg.name
        checks = setup.readiness(tg, tools=False)
        for c in setup.missing(checks):
            if c.safe:
                for f in c.fix:
                    if setup.run_fix(f).returncode:
                        break
        left = setup.missing(setup.readiness(tg, tools=False))
    except setup.SetupError as ex:
        left = [setup.Check("setup", "project", "missing", str(ex))]
    st, sbody = root.load_status()
    if left:
        st["reason"] = "a request from %s, not started: %s; fix with `wpk doctor %s " \
            "--fix`, then hand it off" % (pname, "; ".join(c.title for c in left), name)
        root.save_status(st, sbody)
        return False
    st["reason"] = "a request from %s" % pname    # PAUSED needs one until the resume
    root.save_status(st, sbody)
    out = executor.admin(root, "resume", by=by)
    return out.code == executor.OK


def _where(e):
    t = e["to"]
    if "external" in t:
        return "outside wpk: %s" % t["external"]
    return "project %s%s" % (t["project"], ", packet %s" % t["wpid"][:8] if t.get("wpid") else "")


# --- the result -------------------------------------------------------------------------

def _consumed(pkt, nid):
    """Whether a committed step already took the note ``nid`` out of the mailbox."""
    for r in journal.read(pkt.journal_path).records:
        if r.get("type") == "commit-begin":
            if any(isinstance(n, dict) and n.get("id") == nid
                   for n in (r.get("decision") or {}).get("notes") or ()):
                return True
    return False


def _result_text(e, state, rep):
    t = e["to"]
    lines = ["Request `%s` (%s) came back from project %s (packet %s): %s." % (
        e["id"], e["title"], t["project"], t["wpid"][:8], state)]
    if rep is None:
        lines.append("It wrote no completion report.")
    else:
        rm, _ = rep
        lines.append("Outcome: %s" % " ".join(str(rm.get("outcome") or "").split()))
        ds = rm.get("deliverables") or ()
        if ds:
            lines.append("Deliverables:")
            lines += ["- %s: %s" % (os.path.join(t["path"], d.get("path", "")), d.get("what", ""))
                      for d in ds if isinstance(d, dict)]
        lines.append("The whole report: %s" % os.path.join(t["path"], "report.md"))
    work = os.path.join(t["path"], "work")
    if os.path.isdir(work):
        lines.append("Its work repos: %s" % ", ".join(
            os.path.join(work, n) for n in sorted(os.listdir(work))))
    lines.append("Before relying on it, run the check under \"Done when\" in "
                 "state/requests/%s.md." % e["id"])
    return "\n".join(lines)


def deliver(e, text, outcome, by, h=None):
    """Bring a result back to the requester (§5). True once the request is delivered;
    False if its journal record must wait for a running step to end."""
    pkt = Packet(e["from"]["path"])
    if not os.path.isfile(pkt.status_path):
        raise RequestError("the requester %s is gone" % pkt.path)
    if not e.get("note"):
        e.update(note="%s-req-%s" % (clock.now().strftime("%Y%m%dT%H%M%S"), e["id"]),
                 state="delivering", outcome=outcome, result=text)
        _save(e, h)
    nid = e["note"]
    if not os.path.exists(os.path.join(notes.inbox(pkt), nid + ".json")) and \
            not _consumed(pkt, nid):
        notes.add(pkt, e.get("result") or text, by, nid=nid)
    try:
        if pkt.load_status()[0]["state"] == "SLEEPING":
            executor.admin(pkt, "wake", by=by)
    except (OSError, frontmatter.FrontMatterError):
        pass
    done = any(r.get("type") == "request" and r.get("op") == "done" and r.get("id") == e["id"]
               and r.get("note") == nid for r in journal.read(pkt.journal_path).records)
    if not done and not _record_locked(pkt, {
            "type": "request", "t": _ts(), "op": "done", "id": e["id"], "by": by,
            "outcome": e.get("outcome") or outcome, "note": nid}):
        return False
    e.update(state="delivered", delivered=_ts())
    _save(e, h)
    return True


def finished(e):
    """(state, report) when the delegate packet finished the request's batch, else None."""
    t = e["to"]
    if "wpid" not in t:
        return None
    pkt = Packet(t["path"])
    try:
        st, _ = pkt.load_status()
    except (OSError, frontmatter.FrontMatterError):
        return None
    if st["state"] not in FINISHED:
        return None
    if executor.batch_of(journal.read(pkt.journal_path).records) != t.get("batch", 1):
        return None
    from . import report
    return st["state"], report.of_packet(pkt)


def sync(h=None, by="wpk"):
    """Deliver every finished request; returns [(entry, message)] for what moved."""
    out = []
    for e in entries(h):
        if e["state"] not in ("open", "delivering"):
            continue
        try:
            if e["state"] == "open":
                f = finished(e)
                if f is None:
                    continue
                state, rep = f
                ok = deliver(e, _result_text(e, state, rep), state.lower(), by, h)
            else:
                ok = deliver(e, None, None, by, h)
        except (RequestError, OSError) as ex:
            out.append((e, "not delivered: %s" % ex))
            continue
        out.append((e, "delivered to %s" % e["from"]["wpid"][:8] if ok else
                    "note sent; the record waits for %s's step to end" % e["from"]["wpid"][:8]))
    return out


def done(pkt, rid, text, by=None, h=None):
    """Deliver a result by hand: an external request's, or an override."""
    by = by or executor._who()
    e = get(pkt.wpid, rid, h)
    if e is None:
        raise RequestError("%s has no request %s" % (pkt.wpid[:8], rid))
    if e["state"] == "delivered":
        raise RequestError("request %s was already delivered (%s)" % (rid, e.get("delivered")))
    text = (text or "").strip()
    if not text:
        raise RequestError("give the result with -m or --note-file")
    if e.get("note") and e["state"] == "delivering":
        return deliver(e, None, None, by, h)
    return deliver(e, "Request `%s` (%s), %s, came back from %s:\n%s" % (
        rid, e["title"], _where(e), by, text), "by hand", by, h)


def cancel(pkt, rid, reason=None, by=None, h=None):
    """Withdraw request ``rid`` (docs/waiting-v1.md §5.4): the entry becomes
    ``cancelled``. A delegate that never ran a step is paused with the reason, so
    it never starts; one that has run is left to its owner. Returns
    (entry, what happened to the delegate)."""
    by = by or executor._who()
    e = get(pkt.wpid, rid, h)
    if e is None:
        raise RequestError("%s has no request %s" % (pkt.wpid[:8], rid))
    if e["state"] not in ("sending", "open"):
        raise RequestError("request %s is %s; nothing to cancel" % (rid, e["state"]))
    why = (reason or "").strip() or "no reason given"
    if not _record_locked(pkt, {"type": "request", "t": _ts(), "op": "cancelled", "id": rid,
                                "by": by, "reason": why}):
        raise RequestError("a step of %s is running; cancel when it ends" % pkt.wpid[:8])
    e.update(state="cancelled", cancelled=_ts(), reason=why)
    _save(e, h)
    t = e["to"]
    if "path" not in t:
        return e, "no delegate packet"
    dpkt = Packet(t["path"])
    try:
        dm, dbody = dpkt.load_status()
    except (OSError, frontmatter.FrontMatterError) as ex:
        return e, "delegate unreadable: %s" % ex
    if t.get("batch", 1) != executor.batch_of(journal.read(dpkt.journal_path).records):
        return e, "delegate has moved on to other work; left alone"
    _record_locked(dpkt, {"type": "request", "t": _ts(), "op": "cancelled", "id": rid,
                          "by": by, "reason": why,
                          "from": {"project": e["from"]["project"], "wpid": pkt.wpid}})
    if dm["step"] > 0 or dm["state"] not in ("RUNNABLE", "PAUSED"):
        return e, "delegate %s is %s at step %s; left alone (`wpk pause` stops it)" % (
            dpkt.wpid[:8], dm["state"], dm["step"])
    reason_text = "request %s cancelled by %s: %s" % (rid, by, why)
    if dm["state"] == "PAUSED":
        dm["reason"] = reason_text
        dpkt.save_status(dm, dbody)
    else:
        out = executor.admin(dpkt, "pause", by=by, reason=reason_text)
        if out.code != executor.OK:
            return e, "delegate not paused: %s" % out.msg
    return e, "delegate %s paused; it never ran" % dpkt.wpid[:8]


# --- what a step and a person see ---------------------------------------------------------

# Delegate states in which nobody works on the request until someone acts.
STALLED = ("PAUSED", "NEEDS_INPUT", "FAILED")


def delegate_state(e):
    """The delegate packet's live (state, step, reason), or None (external, unreadable)."""
    t = e["to"]
    if "path" not in t:
        return None
    try:
        st, _ = Packet(t["path"]).load_status()
    except (OSError, frontmatter.FrontMatterError):
        return None
    return st.get("state"), st.get("step"), st.get("reason")


def _live(e):
    """What the delegate is doing, for a request that is out (docs/waiting-v1.md §5.2)."""
    d = delegate_state(e) if e["state"] == "open" else None
    if d is None:
        return ""
    state, step, reason = d
    out = "; delegate %s at step %s" % (state, step)
    if state in STALLED:
        out += " (%s): nobody is working on it until the owner acts" % (reason or "no reason")
    return out


def describe(e):
    s = {"sending": "not sent yet (sending stopped part-way)", "open": "out",
         "delivering": "back; recording it", "delivered": "back",
         "cancelled": "cancelled by the owner (%s): do not wait for it" % e.get("reason"),
         }.get(e["state"], e["state"])
    return "`%s` (%s): %s, sent %s; %s%s" % (e["id"], e["title"], _where(e), e.get("sent"), s,
                                            _live(e))


def section(wpid, h=None):
    """The step prompt's "Requests", or ""."""
    es = [e for e in entries(h, wpid) if e["from"]["wpid"] == wpid]
    if not es:
        return ""
    out = ["## Requests", "",
           "Work this task handed to another agent (state/requests/). A result comes "
           "back as a note from the owner.", ""]
    out += ["- " + describe(e) for e in es]
    return "\n".join(out) + "\n\n"
