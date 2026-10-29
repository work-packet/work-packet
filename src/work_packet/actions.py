"""What a front end can do to a packet or a project (docs/interaction.md §4).

The CLI, the web board and the TUI call these and add no logic of their own.
Each returns an ``executor.Outcome``.
"""

import json
import os

from . import clock, executor, fsutil, lease, notes, questions
from .project import ProjectError, allow, project_of

DRAFTS = os.path.join(".setup", "next")    # <project>/.setup/next/<wpid>.{md,json}


def answer(pkt, answers=None, note=None, take_recommendations=False, by=None):
    """Answer a ``NEEDS_INPUT`` packet: grant what yes-answers grant, then hand it off.

    ``answers`` maps question ids to text. With ``take_recommendations``,
    every unanswered question gets its ``recommend``.
    """
    by = by or executor._who()
    qs = questions.of_packet(pkt)
    if not qs:
        return executor.Outcome(executor.NOT_RUNNABLE,
                                "%s has no open questions" % pkt.wpid[:8])
    ids = {q["id"] for q in qs}
    unknown = sorted(set(answers or {}) - ids)
    if unknown:
        return executor.Outcome(executor.USAGE, "no question %s; the questions are %s" % (
            ", ".join(unknown), ", ".join(q["id"] for q in qs)))
    got = questions.fill(qs, answers, take_recommendations)
    if not got and not (note and note.strip()):
        return executor.Outcome(executor.USAGE, "nothing to send: give answers, a note, "
                                "or take the recommendations")
    done = []
    tools = questions.grants(qs, got)
    if tools:
        proj = project_of(pkt.path)
        try:
            ch = allow(proj, tools, by) if proj else []
        except ProjectError as e:
            return executor.Outcome(executor.LEASED, str(e))
        if ch:
            done.append("granted " + ", ".join(t.split(" ", 1)[1] for t in ch))
    for rid in questions.requests(qs, got):
        from . import requests
        try:
            e = requests.send(pkt, rid, by=by)
        except requests.RequestError as ex:
            return executor.Outcome(executor.USAGE, "request %s: %s" % (rid, ex))
        done.append("sent request %s to %s" % (rid, requests._where(e)))
    out = executor.admin(pkt, "handoff", note=note, answers=got, by=by)
    if out.code != executor.OK:
        return out
    n = len(got)
    msg = "answered %d of %d question%s" % (n, len(qs), "" if len(qs) == 1 else "s")
    return executor.Outcome(executor.OK, "; ".join([msg] + done) + "; " + out.msg)


def note(pkt, text, by=None, wake=False):
    """Queue a note from the owner (docs/interaction.md §6a). A running step gets it
    after its next tool call; otherwise the next step's prompt shows it. With
    ``wake``, a SLEEPING packet becomes RUNNABLE now."""
    by = by or executor._who()
    try:
        meta, _ = pkt.load_status()
    except (OSError, executor.frontmatter.FrontMatterError) as e:
        return executor.Outcome(executor.USAGE, str(e))
    try:
        notes.add(pkt, text, by)
    except (ValueError, OSError) as e:
        return executor.Outcome(executor.USAGE, str(e))
    state, short = meta["state"], pkt.wpid[:8]
    if wake and state == "SLEEPING":
        out = executor.admin(pkt, "wake", by=by)
        if out.code != executor.OK:
            return out
        return executor.Outcome(executor.OK, "note queued; %s; the next step shows it" % out.msg)
    lz = lease.read(pkt.lease_path)
    if lz and lz.get("attempt") and not lease.is_stale(lz, clock.now()):
        how = "the running step gets it after its next tool call"
    elif state in ("RUNNABLE", "SLEEPING"):
        how = "the next step shows it" + (" (%s until %s)" % (state, meta.get("wake_at"))
                                          if state == "SLEEPING" else "")
    elif state in ("NEEDS_INPUT", "PAUSED", "FAILED"):
        how = "it waits: %s is %s until it is handed off" % (short, state)
    else:
        how = "but %s is %s, so no step will see it" % (short, state)
    return executor.Outcome(executor.OK, "note queued for %s; %s" % (short, how))


# --- the next batch of work (docs/dash-tasks.md §6) ---------------------------------

def _draft_paths(pkt):
    proj = project_of(pkt.path)
    if proj is None:
        raise ValueError("%s is not in a project" % pkt.path)
    base = os.path.join(proj, DRAFTS, pkt.wpid)
    return base + ".md", base + ".json"


def load_draft(pkt):
    """The saved draft: ``{"instruction", "note", "archive_outline", "carry_session",
    "saved"}``, or None. Nothing in the packet changes until the hand-off."""
    md, js = _draft_paths(pkt)
    try:
        text = fsutil.read_text(md)
    except FileNotFoundError:
        return None
    try:
        with open(js, encoding="utf-8") as fp:
            opts = json.load(fp)
    except (OSError, ValueError):
        opts = {}
    opts["instruction"] = text
    return opts


def save_draft(pkt, instruction, note="", archive_outline=None, carry_session=False):
    md, js = _draft_paths(pkt)
    os.makedirs(os.path.dirname(md), exist_ok=True)
    fsutil.atomic_write(md, instruction or "")
    fsutil.atomic_write(js, json.dumps({
        "note": note or "", "archive_outline": archive_outline,
        "carry_session": bool(carry_session),
        "saved": executor._ts()}, indent=1) + "\n")
    return executor.Outcome(executor.OK, "draft saved")


def drop_draft(pkt):
    for p in _draft_paths(pkt):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def continue_(pkt, instruction, note=None, archive_outline=None, carry_session=False,
              force=False, by=None):
    """Give a stopped packet (``COMPLETED`` too) a new instruction and hand it to the
    runner. The draft, if any, is removed once the hand-off is recorded."""
    out = executor.admin(pkt, "continue", note=note, by=by or executor._who(),
                         instruction=instruction, archive_outline=archive_outline,
                         carry_session=carry_session, force=force)
    if out.code == executor.OK:
        try:
            drop_draft(pkt)
        except ValueError:
            pass
        n = executor.batch_of(executor.journal.read(pkt.journal_path).records)
        out = executor.Outcome(executor.OK, "batch %d handed off; %s" % (n, out.msg))
    return out


# --- a whole project: pause to re-prioritise (docs/pause-v1.md) ----------------------

def resumable(meta):
    """PAUSED by hand (or by a pause request), not for setup and not by a limit:
    what Resume on a project gives back to the runner."""
    from .project import SETUP_REASON
    return meta.get("state") == "PAUSED" and meta.get("reason") != SETUP_REASON and \
        not meta.get("stopped")


def _tree(entry):
    from .views import packets
    return [(p, m) for _, p, m, _ in packets(entry["path"], entry["root"]) if m is not None]


def pause_project(entry, by=None, reason=None):
    """Pause every packet of ``entry`` that the runner would run: at once, or,
    while its step runs, after that step."""
    now, later, bad = 0, 0, []
    for pkt, meta in _tree(entry):
        if meta["state"] not in ("RUNNABLE", "SLEEPING"):
            continue
        out = executor.admin(pkt, "pause", by=by, reason=reason)
        if out.code:
            bad.append(out.msg)
        elif executor.pause_request(pkt) is not None:
            later += 1
        else:
            now += 1
            _withdraw_job(pkt, by)
    return _summary(entry, "paused", now, later, bad)


def resume_project(entry, by=None):
    """Give back to the runner what was paused by hand, and take back pauses
    that have not happened yet. Setup, limits and questions are left alone."""
    n, kept, bad = 0, 0, []
    for pkt, meta in _tree(entry):
        if executor.pause_request(pkt) is not None:
            executor.withdraw_pause(pkt)
            kept += 1
        elif resumable(meta):
            out = executor.admin(pkt, "resume", by=by)
            if out.code:
                bad.append(out.msg)
            else:
                n += 1
    if not (n or kept or bad):
        return executor.Outcome(executor.NOT_RUNNABLE, "%s: nothing paused by hand" % entry["name"])
    msg = "%s: resumed %d packet%s" % (entry["name"], n, "" if n == 1 else "s")
    if kept:
        msg += "; %d will not pause after all" % kept
    return executor.Outcome(1 if bad else 0, "; ".join([msg] + bad))


def stop_project(entry, by=None, h=None):
    """Pause the project, and end its running steps now: they are not counted as
    failed attempts, and what they had not committed is redone later."""
    from .sched import control
    out = pause_project(entry, by=by, reason="stopped now")
    gone = control.cancel_jobs(lambda r: r.project == entry["name"] and r.kind == "step",
                               by or executor._who(), "stopped by %s" % (by or "hand"), h=h)
    if not gone:
        return out
    return executor.Outcome(out.code, "%s; ended %d running step%s" % (
        out.msg, len(gone), "" if len(gone) == 1 else "s"))


def _withdraw_job(pkt, by):
    from .sched import control
    try:
        control.cancel_pending(pkt.wpid, by or executor._who())
    except Exception:               # noqa: BLE001: the dispatcher drops it at its next pass
        pass


def _summary(entry, verb, now, later, bad):
    if not (now or later or bad):
        return executor.Outcome(executor.NOT_RUNNABLE, "%s: nothing to pause" % entry["name"])
    parts = []
    if now:
        parts.append("%s %d packet%s" % (verb, now, "" if now == 1 else "s"))
    if later:
        parts.append("%d after the running step" % later)
    return executor.Outcome(1 if bad else 0, "%s: %s" % (entry["name"], "; ".join(parts + bad)))
