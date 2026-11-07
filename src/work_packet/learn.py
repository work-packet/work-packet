"""Learn from corrections (docs/collaboration.md §7.7, plan C7c).

When you tell the runner the same thing again and again ("use the uvm_info
macro, not $display"), the board offers to make it a rule: a line under
``## Learned`` in each project's ``agent.md``, which every later step reads.

What counts as a correction: your notes (queued, or committed with a step) and
your answers to the runner's questions, and the note on a hand-off, across the
board's projects. Each has to say something: at least ``MIN_WORDS`` content
words. Near-duplicates are grouped (shared words, as the Inbox's duplicate hint,
but stricter). A group said ``TIMES`` times, or in two projects or more, is
proposed once, as an Inbox item (source ``learn``). **Keep it** writes the rule,
which you can edit first; **Drop** is the Inbox's own. A group is never
proposed twice, though it grows: what was proposed is kept in
``$WPK_HOME/learn/state.json``.

Deterministic: no model reads your notes. The board's loop proposes at most
once an hour (``maybe_propose``).
"""

import hashlib
import json
import os
import time

from . import fsutil, inbox, layout, registry

MIN_WORDS = 3
TIMES = 3
OVERLAP = 0.6
EVERY_S = 3600
HEADING = "## Learned"


def _path(h):
    return os.path.join(h, "learn", "state.json")


def load_state(h):
    try:
        with open(_path(h)) as fp:
            d = json.load(fp)
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    d.setdefault("proposed", {})        # group key -> inbox item id
    d.setdefault("kept", {})            # group key -> [projects]
    d.setdefault("t", 0)
    return d


def _save(h, d):
    os.makedirs(os.path.dirname(_path(h)), exist_ok=True)
    fsutil.atomic_write(_path(h), json.dumps(d, sort_keys=True) + "\n")


def _journal(p):
    try:
        with open(p, encoding="utf-8") as fp:
            for ln in fp:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    yield r
    except OSError:
        return


def corrections(h=None):
    """Every correction on the board: ``[{"id", "text", "project", "wpid", "t",
    "kind"}]`` (kind: note or answer), oldest first."""
    from . import notes
    from .packet import Packet
    out, seen = [], set()

    def put(cid, text, project, wpid, t, kind):
        if cid in seen or not isinstance(text, str) or \
                len(inbox._words(text)) < MIN_WORDS:
            return
        seen.add(cid)
        out.append({"id": cid, "text": " ".join(text.split()), "project": project,
                    "wpid": wpid, "t": t or "", "kind": kind})

    for e in registry.entries(h):
        try:
            wpids = sorted(os.listdir(layout.runs_dir(e["path"])))
        except OSError:
            continue
        for w in wpids:
            pkt = Packet(layout.run_dir(e["path"], w))
            for n in notes.queued(pkt):
                put("note:" + n["id"], n.get("text"), e["name"], w, n.get("t"), "note")
            for r in _journal(pkt.journal_path):
                typ = r.get("type")
                if typ == "commit-begin":
                    for n in (r.get("decision") or {}).get("notes") or ():
                        if isinstance(n, dict) and n.get("id"):
                            put("note:" + n["id"], n.get("text"), e["name"], w, n.get("t"),
                                "note")
                elif typ in ("admin", "handoff"):
                    if r.get("note"):
                        put("%s:%s:%s:note" % (typ, w, r.get("t")), r["note"], e["name"], w,
                            r.get("t"), "note")
                    for q, a in sorted((r.get("answers") or {}).items()):
                        put("answer:%s:%s:%s" % (w, r.get("t"), q), a, e["name"], w,
                            r.get("t"), "answer")
    out.sort(key=lambda c: (c["t"], c["id"]))
    return out


def _close(a, b):
    both = a & b
    return len(both) >= MIN_WORDS and len(both) / float(min(len(a), len(b))) >= OVERLAP


def groups(cs):
    """Near-duplicate corrections together: ``[{"key", "text", "items",
    "projects"}]``. A group's key comes from its oldest correction, so it stays
    the same as the group grows; its text is the newest wording."""
    out = []
    for c in cs:
        w = inbox._words(c["text"])
        g = next((g for g in out if _close(w, g["words"])), None)
        if g is None:
            g = {"key": hashlib.sha1(c["id"].encode()).hexdigest()[:12], "words": w,
                 "items": []}
            out.append(g)
        g["items"].append(c)
    for g in out:
        g["text"] = g["items"][-1]["text"]
        g["projects"] = sorted({c["project"] for c in g["items"]})
        del g["words"]
    return out


def proposals(h=None):
    """Groups worth a rule that were not proposed before."""
    h = h or registry.home()
    st = load_state(h)
    return [g for g in groups(corrections(h))
            if (len(g["items"]) >= TIMES or len(g["projects"]) >= 2)
            and g["key"] not in st["proposed"]]


def propose(h=None, now=None):
    """Put each new proposal in the Inbox. Returns the items added."""
    h = h or registry.home()
    st = load_state(h)
    added = []
    for g in proposals(h):
        n = len(g["items"])
        where = ", ".join(g["projects"])
        text = "You have said this %d time%s (%s): %s" % (n, "s" if n != 1 else "", where,
                                                          g["text"])
        it = inbox.add(h, text[:inbox.TEXT_MAX], source="learn",
                       project=g["projects"][0] if len(g["projects"]) == 1 else None,
                       now=now, iid=g["key"],
                       ref={"learn": g["key"], "rule": g["text"], "projects": g["projects"],
                            "times": n})
        st["proposed"][g["key"]] = it["id"]
        added.append(it)
    _save(h, st)
    return added


def maybe_propose(h=None, now=None):
    """The board's loop: ``propose`` at most once every ``EVERY_S``."""
    h = h or registry.home()
    now = time.time() if now is None else now
    st = load_state(h)
    if now - st["t"] < EVERY_S:
        return None
    st["t"] = now
    _save(h, st)
    return propose(h, now)


# --- keeping one --------------------------------------------------------------------

def agent_md(proj):
    return os.path.join(proj, "agent.md")


def add_rule(proj, rule):
    """Append ``rule`` as a bullet under ``## Learned`` in the project's
    ``agent.md`` (made if missing). The rest of the file stays as it is."""
    rule = " ".join((rule or "").split())
    if not rule:
        raise ValueError("the rule is empty")
    p = agent_md(proj)
    text = fsutil.read_text(p) if os.path.exists(p) else ""
    lines = text.splitlines()
    try:
        at = next(i for i, ln in enumerate(lines) if ln.strip() == HEADING)
    except StopIteration:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ([""] if lines else []) + [HEADING, "", "- " + rule]
    else:
        end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith("#")),
                   len(lines))
        last = max([i for i in range(at + 1, end) if lines[i].strip()] or [at])
        if "- " + rule in lines[at:end]:
            return False
        lines.insert(last + 1, "- " + rule)
        if last == at:
            lines.insert(last + 1, "")
    fsutil.atomic_write(p, "\n".join(lines) + "\n")
    return True


def keep(h, iid, rule, projects):
    """**Keep it**: the rule into each project's ``agent.md``, then the Inbox
    item goes. Returns the projects written."""
    h = h or registry.home()
    item = inbox.get(h, iid)
    if item is None or (item.get("ref") or {}).get("learn") is None:
        raise ValueError("no such proposal")
    if not projects:
        raise ValueError("pick a project")
    done = []
    for name in projects:
        e = registry.get(name, h)
        if e is None:
            raise ValueError("no project %s" % name)
        add_rule(e["path"], rule)
        done.append(name)
    st = load_state(h)
    st["kept"][item["ref"]["learn"]] = done
    _save(h, st)
    inbox.drop(h, iid)
    return done
