"""Migrating v0.2 projects to cards, run links and the history store
(docs/migration-v1.md, stages M1 and M3 without the deletion).

For each registered project:

1. A card ``<project dir>/<name>.wp.md`` is written, its thread rebuilt from
   the root packet's journal and step files. Every rebuilt entry carries a
   ``Migrated-From:`` trailer. Spawned children get cards under
   ``runs/<root>/sub/``. Re-running merges: entries already on the card are
   kept, new ones are added, and front matter someone edited is not touched.
2. ``~/.work-packet/runs/<id>`` is linked to each packet directory.
3. Each packet's run goes to the history store: harvested (archive, load,
   verify) when the project is finished, loaded provisionally when it is
   still active.
4. Every statistic is compared between the runs and the history store.

Nothing is moved or deleted.
"""

import getpass
import json
import os
import re
import subprocess

from . import card as cardmod
from . import clock, frontmatter, history, index, registry, schema, stats
from .card import Card, Entry
from .packet import Packet

MIGRATOR = "wpk-migrate"
RUNNER = "runner"
NO_ANSWER = "_No answer was given; the packet was resumed._"


def runs_dir(h=None):
    return os.path.join(h or registry.home(), "runs")


# --- small readers ---------------------------------------------------------------

def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            return fp.read()
    except OSError:
        return None


def _journal(path):
    out = []
    for i, ln in enumerate((_read(path) or "").splitlines(), 1):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("t"):
            out.append((i, r))
    return out


def _text(s):
    return (s or "").replace("\r\n", "\n").strip()


def _demote(text):
    """Headings in migrated text at level 3 or deeper, as bodies require."""
    out, fenced = [], False
    for ln in _text(text).split("\n"):
        if ln.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        m = None if fenced else re.match(r"^(#{1,2}) (.*)$", ln)
        out.append("### " + m.group(2) if m else ln)
    return "\n".join(out)


def title_of(prompt, fallback):
    """A one-line title: the first sentence of the prompt, at most 90 characters."""
    t = " ".join(_text(prompt).split())
    if not t:
        return fallback
    m = re.match(r"^(.+?[.!?])(\s|$)", t)
    t = m.group(1) if m else t
    if len(t) > 90:
        t = t[:89].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


def _git(d, *args):
    try:
        r = subprocess.run(["git", "-C", d] + list(args), capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def workspaces(run_dir):
    """[(name, url, branch, head)] for the repos in a packet's ``work/``."""
    out = []
    wd = os.path.join(run_dir, "work")
    try:
        names = sorted(os.listdir(wd))
    except OSError:
        return out
    for n in names:
        d = os.path.join(wd, n)
        if not os.path.isdir(d):
            continue
        head = _git(d, "rev-parse", "HEAD")
        if head is None:
            out.append((n, None, None, None))
            continue
        url = _git(d, "remote", "get-url", "origin")
        branch = _git(d, "symbolic-ref", "--short", "-q", "HEAD")
        out.append((n, url, branch, head))
    return out


def _ref(url, rev, path):
    return "git:%s@%s" % (url, rev) if url else "dir:%s" % path


def _report(run_dir, step, batch, last):
    """(outcome, deliverables, where) of the report that finished a batch."""
    pkt = Packet(run_dir)
    cands = [(os.path.join(pkt.steps_dir, schema.step_dir_name(step), "report.md"),
              "steps/%s/report.md" % schema.step_dir_name(step)),
             (os.path.join(pkt.state_dir, "history", "report-%d.md" % batch),
              "state/history/report-%d.md" % batch)]
    if last:
        cands.append((pkt.report_path, "report.md"))
    for p, rel in cands:
        t = _read(p)
        if t is None:
            continue
        try:
            meta, body = frontmatter.parse(t)
        except frontmatter.FrontMatterError:
            meta, body = None, t
        meta = meta or {}
        out = meta.get("outcome") or ""
        if not out:
            paras = [x for x in _text(body).split("\n\n") if x and not x.startswith("#")]
            out = paras[0] if paras else ""
        return _text(out), meta.get("deliverables") or [], rel
    return None, [], None


# --- the thread ------------------------------------------------------------------

def _qid(s, n):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(s or "")).strip("-.")
    return s or "q%d" % n


class _Thread:
    def __init__(self):
        self.entries = []
        self.n = 0

    def add(self, kind, who, t, body="", trailers=(), arg=None, src=None):
        tr = list(trailers)
        if src:
            tr.append(("Migrated-From", src))
        self.entries.append((cardmod.stamp_iso(t), self.n,
                             Entry(kind=kind, who=who, at=cardmod.stamp_iso(t),
                                   body=body, trailers=tr, arg=arg)))
        self.n += 1

    def sorted(self):
        return [e for _, _, e in sorted(self.entries, key=lambda x: (x[0], x[1]))]


def rebuild_thread(run_dir, project, requester=None, sent=None, name_of_child=None):
    """Card entries for one packet, rebuilt from its journal and step files.

    ``sent`` is (who, t, src) for a packet that was spawned rather than
    handed over by a person. ``name_of_child`` maps child ids to names.
    """
    pkt = Packet(run_dir)
    recs = _journal(pkt.journal_path)
    try:
        status, _ = pkt.load_status()
    except Exception:
        status = {}
    by_step = {}
    for s in stats.packet_steps(project, pkt):
        by_step[s.step] = by_step.get(s.step, 0) + (s.cost or 0)
    th = _Thread()
    ws = workspaces(run_dir)
    ws_tr = [("Workspace", _ref(u, b or h, os.path.join(run_dir, "work", n)))
             for n, u, b, h in ws]
    who_req = requester or getpass.getuser()
    did_sent, did_acc = False, False
    asked_t, asked_reason = None, None
    batch, batch_first = 1, None
    last_t = None
    if sent:
        th.add("sent", sent[0], sent[1], src=sent[2])
        did_sent = True
    for i, r in recs:
        t, typ = r["t"], r.get("type")
        src = "journal.jsonl:%d" % i
        last_t = t
        if typ == "handoff":
            who = r.get("by") or who_req
            if not did_sent:
                th.add("sent", who, t, src=src)
                did_sent = True
            elif r.get("instruction"):
                batch = r.get("batch") or batch + 1
                th.add("request", who, t, _demote(r["instruction"]),
                       [("Batch", str(batch))], src=src)
                did_acc = False
            elif r.get("from") == "FAILED":
                th.add("request", who, t, "Resume after the failure.", src=src)
                did_acc = False
            qs = r.get("questions") or []
            if not qs and r.get("asked") and r.get("from") == "NEEDS_INPUT":
                qs = [{"id": "q1", "q": r["asked"]}]
            ans = r.get("answers") or {}
            for k, q in enumerate(qs, 1):
                qid = _qid(q.get("id"), k)
                tr = []
                if q.get("recommend"):
                    tr.append(("Recommend", str(q["recommend"])))
                if q.get("choices"):
                    tr.append(("Choices", " | ".join(map(str, q["choices"]))))
                if q.get("grants"):
                    tr.append(("Grants", ", ".join(map(str, q["grants"]))))
                th.add("question", RUNNER, asked_t or t, _demote(q.get("q")), tr, arg=qid,
                       src=src)
                a = ans.get(q.get("id")) if isinstance(ans, dict) else None
                th.add("answer", who, t, _demote(a) if a else NO_ANSWER, arg=qid, src=src)
            if r.get("note"):
                th.add("note", who, t, _demote(r["note"]), src=src)
            asked_t = asked_reason = None
        elif typ == "step-start":
            if not did_sent:
                th.add("sent", who_req, t, src=src)
                did_sent = True
            if not did_acc:
                th.add("accepted", RUNNER, t, trailers=ws_tr, src=src)
                did_acc = True
            if batch_first is None:
                batch_first = r.get("step")
        elif typ == "config":
            ch = r.get("changes") or []
            if ch:
                th.add("note", r.get("by") or who_req, t,
                       "Settings changed: %s." % "; ".join(map(str, ch)), src=src)
        elif typ == "commit-begin":
            d = r.get("decision") or {}
            st, step = d.get("state"), r.get("step")
            for sp in d.get("spawn") or []:
                nm = sp.get("name") or (name_of_child or {}).get(sp.get("wpid"))
                th.add("note", RUNNER, t, "Started sub-packet %s: %s" % (
                    nm, _text(sp.get("instruction")).split("\n")[0]),
                    [("Related", "pkt:%s" % sp.get("wpid"))], src=src)
            if st == "NEEDS_INPUT":
                asked_t, asked_reason = t, d.get("reason")
            elif st in ("COMPLETED", "FAILED"):
                last = not any(x.get("type") == "handoff" and x["t"] > t for _, x in recs)
                out, dels, rel = _report(run_dir, step, batch, last)
                body = out or _demote(d.get("summary")) or "(no summary)"
                first = batch_first or step
                tr = [("Outcome", "done" if st == "COMPLETED" else "failed")]
                for dl in dels:
                    if isinstance(dl, dict):
                        tr.append(("Deliverable", " ".join(
                            x for x in (str(dl.get("path") or dl.get("ref") or ""),
                                        " ".join(str(dl.get("what") or "").split())) if x)))
                    else:
                        tr.append(("Deliverable", str(dl)))
                cost = sum(c for s, c in by_step.items() if first <= s <= step)
                tr += [("Steps", "s%d-s%d" % (first, step) if first != step else "s%d" % step),
                       ("Cost", "%.2f USD" % cost)]
                if rel:
                    tr.append(("Report", "run:%s/%s" % (pkt.wpid, rel)))
                tr.append(("Record", "run:%s@s%d" % (pkt.wpid, step)))
                th.add("result", RUNNER, t, body, tr, src=src)
                batch_first = None
    if asked_t and status.get("state") == "NEEDS_INPUT":
        th.add("question", RUNNER, asked_t, _demote(asked_reason) or "(see the step's result)",
               arg="q1", src="status.md")
    return th.sorted(), status, ws


# --- cards -----------------------------------------------------------------------

def _work_field(ws, run_dir):
    refs = [_ref(u, b or h, os.path.join(run_dir, "work", n)) for n, u, b, h in ws]
    return refs[0] if len(refs) == 1 else (refs or "none")


def _pinned(status, ws, run_dir, entries, steps_n, cost):
    tr = [("Pin", _ref(u, h, os.path.join(run_dir, "work", n))) for n, u, b, h in ws if h]
    tr += [("Steps", str(steps_n)), ("Cost", "%.2f USD" % cost),
           ("Record", "run:%s" % os.path.basename(run_dir))]
    t = status.get("updated") or (entries[-1].at if entries else schema.format_timestamp(clock.now()))
    return Entry("pinned", MIGRATOR, cardmod.stamp_iso(t),
                 "Frozen at migration: the run is complete and its record is in the "
                 "history store.", tr)


def _totals(project, run_dir):
    ss = stats.packet_steps(project, Packet(run_dir))
    return sum(1 for s in ss if not s.failed), sum(s.cost or 0 for s in ss)


def build_card(entry, run_dir, prompt, name, title, parent=None, sent=None, child_names=None,
               requester=None):
    """A Card for the packet at ``run_dir``."""
    entries, status, ws = rebuild_thread(run_dir, entry["name"], requester, sent, child_names)
    wpid = os.path.basename(run_dir)
    meta = {"packet": cardmod.FORMAT, "id": wpid, "name": name, "title": title,
            "by": (sent[0] if sent else next((e.who for e in entries if e.kind == "sent"),
                                             requester or getpass.getuser())),
            "to": RUNNER}
    if parent:
        meta["parent"] = parent
    meta["work"] = _work_field(ws, run_dir)
    if entry.get("board") and not parent:
        meta["tags"] = [entry["board"]]
    meta["x-wpk"] = {"project": entry["name"], "path": entry["path"], "root": entry["root"],
                     "run": wpid, "migrated": schema.format_timestamp(clock.now())[:10]}
    if status.get("state") == "COMPLETED" and entries:
        n, cost = _totals(entry["name"], run_dir)
        entries.append(_pinned(status, ws, run_dir, entries, n, cost))
    return cardmod.refresh(Card(meta=meta, brief=_text(prompt), entries=entries))


def merge_into(path, fresh):
    """Write ``fresh`` to ``path``, keeping what an existing card there holds:
    its front matter wins key by key, and its entries are kept."""
    if not os.path.exists(path):
        return fresh
    old = cardmod.load(path)
    meta = dict(fresh.meta)
    meta.update({k: v for k, v in old.meta.items() if k not in cardmod.CACHE_KEYS})
    xo, xf = old.meta.get("x-wpk") or {}, fresh.meta.get("x-wpk") or {}
    meta["x-wpk"] = dict(xf, **xo)
    m = cardmod.merge(Card(meta=meta, brief=old.brief or fresh.brief, entries=old.entries),
                      fresh)
    return m


# --- a project -------------------------------------------------------------------

def plan(entry, h=None):
    """What migrating ``entry`` involves: a dict, nothing written."""
    root_dir = os.path.join(entry["path"], "packets", entry["root"])
    p = {"name": entry["name"], "path": entry["path"], "root": entry["root"],
         "exists": os.path.isdir(root_dir), "card": os.path.join(
             entry["path"], entry["name"] + cardmod.SUFFIX), "packets": [], "state": None}
    if not p["exists"]:
        return p
    try:
        st, _ = Packet(root_dir).load_status()
        p["state"] = st.get("state")
    except Exception:
        pass
    pdir = os.path.join(entry["path"], "packets")
    for w in sorted(os.listdir(pdir)):
        if schema.is_wpid(w):
            try:
                s, _ = Packet(os.path.join(pdir, w)).load_status()
            except Exception:
                s = {}
            p["packets"].append({"id": w, "state": s.get("state"), "parent": s.get("parent"),
                                 "updated": s.get("updated"), "dir": os.path.join(pdir, w)})
    p["finished"] = all(x["state"] == "COMPLETED" for x in p["packets"]) and bool(p["packets"])
    return p


def _children(root_dir):
    """{child id: (name, instruction, t, src)} from a packet's spawn records."""
    out = {}
    for i, r in _journal(Packet(root_dir).journal_path):
        if r.get("type") == "commit-begin":
            for sp in (r.get("decision") or {}).get("spawn") or []:
                if sp.get("wpid"):
                    out[sp["wpid"]] = (sp.get("name"), sp.get("instruction"), r["t"],
                                       "journal.jsonl:%d" % i)
    return out


def cards_for(entry, p, h=None):
    """[(path, Card)] for a project: the root's card, then each child's."""
    root_dir = os.path.join(entry["path"], "packets", entry["root"])
    prompt = _read(os.path.join(entry["path"], "prompt.md")) or _read(
        Packet(root_dir).memento_path) or ""
    kids = {}
    for x in p["packets"]:
        if x["parent"]:
            kids.update(_children(os.path.join(entry["path"], "packets", x["parent"])))
    names = {w: (v[0] or "child-%d" % k) for k, (w, v) in enumerate(sorted(kids.items()), 1)}
    out = [(p["card"], build_card(entry, root_dir, prompt, entry["name"],
                                  title_of(prompt, entry["name"]), child_names=names))]
    for x in p["packets"]:
        if x["id"] == entry["root"]:
            continue
        nm, instr, t, src = kids.get(x["id"], (None, None, None, None))
        nm = names.get(x["id"]) or "child-%s" % x["id"][:8]
        par = x["parent"]
        par_name = entry["name"] if par == entry["root"] else names.get(par, par)
        sent = ("pkt:%s" % par_name, t, src) if t else None
        brief = instr or _read(Packet(x["dir"]).memento_path) or ""
        c = build_card(entry, x["dir"], brief, nm, title_of(brief, nm),
                       parent="pkt:%s" % par_name, sent=sent, child_names=names)
        path = os.path.join(runs_dir(h), entry["root"], "sub", nm + cardmod.SUFFIX)
        out.append((path, c))
    return out


def link_runs(p, h=None):
    """``runs/<id>`` -> each packet directory. Returns the links made."""
    d = runs_dir(h)
    os.makedirs(d, exist_ok=True)
    made = []
    for x in p["packets"]:
        link = os.path.join(d, x["id"])
        if os.path.islink(link) and os.path.realpath(link) == os.path.realpath(x["dir"]):
            continue
        if os.path.lexists(link):
            raise FileExistsError("%s exists and is not a link to %s" % (link, x["dir"]))
        os.symlink(x["dir"], link)
        made.append(link)
    return made


def _write_cards(cards, h=None):
    """Merge each card into the one on disk and save it; {id: card text}."""
    texts = {}
    for path, c in cards:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        c = merge_into(path, c)
        if not os.path.isfile(path) or cardmod.render(c) != _read(path):
            cardmod.save(path, c)
        texts[c.id] = cardmod.render(c)
        index.upsert(c, path, h=h)
    return texts


def keep_project(entry, h=None, con=None):
    """Bring ``entry``'s cards and history rows up to date while it runs
    (livecard): cards rebuilt from the journals and merged; metrics synced
    provisionally, replacing a harvest if a finished packet was resumed;
    once every packet is COMPLETED, each is harvested (archive, load,
    verify) unless its harvest is already current. Returns a summary dict,
    or None when there is nothing to do."""
    p = plan(entry, h)
    if not p["exists"] or not p["packets"]:
        return None
    cards = cards_for(entry, p, h)
    link_runs(p, h)
    texts = _write_cards(cards, h)
    res = {"name": entry["name"], "cards": len(cards), "harvested": [], "synced": []}
    own = con is None
    con = con or history.connect(h)
    try:
        for x in p["packets"]:
            row = con.execute("SELECT provisional, updated FROM packet WHERE id = ?",
                              (x["id"],)).fetchone()
            if p["finished"]:
                if row is not None and row[0] == 0 and row[1] == x["updated"]:
                    continue
                history.harvest(entry["name"], x["dir"], texts.get(x["id"]), h=h, con=con)
                res["harvested"].append(x["id"])
            else:
                history.sync(entry["name"], x["dir"], texts.get(x["id"]), h=h, con=con,
                             replace=True)
                res["synced"].append(x["id"])
    finally:
        if own:
            con.close()
    return res


def migrate_project(entry, dry_run=False, h=None, con=None, log=print):
    """Migrate one registered project. Returns a summary dict."""
    p = plan(entry, h)
    res = {"name": entry["name"], "state": p["state"], "cards": [], "harvested": [],
           "provisional": [], "problems": [], "skipped": None}
    if not p["exists"]:
        res["skipped"] = "its directory %s no longer exists" % entry["path"]
        return res
    if not p["packets"]:
        res["skipped"] = "no packets"
        return res
    cards = cards_for(entry, p, h)
    for path, c in cards:
        res["cards"].append({"path": path, "entries": len(c.entries), "state": c.state(),
                             "name": c.name})
    if dry_run:
        res["preview"] = cards
        return res
    link_runs(p, h)
    texts = _write_cards(cards, h)
    for x in p["packets"]:
        if p["finished"]:
            history.harvest(entry["name"], x["dir"], texts.get(x["id"]), h=h, con=con)
            res["harvested"].append(x["id"])
        else:
            history.sync(entry["name"], x["dir"], texts.get(x["id"]), h=h, con=con)
            res["provisional"].append(x["id"])
    res["problems"] = history.verify_project(con, entry["name"], entry["path"], h=h)
    return res


def migrate(names=None, dry_run=False, h=None, log=print):
    """Migrate the registered projects ``names`` (all when None)."""
    es = registry.entries(h)
    if names:
        missing = set(names) - {e["name"] for e in es}
        if missing:
            raise KeyError(", ".join(sorted(missing)))
        es = [e for e in es if e["name"] in names]
    con = None if dry_run else history.connect(h)
    out = []
    try:
        for e in es:
            out.append(migrate_project(e, dry_run=dry_run, h=h, con=con, log=log))
    finally:
        if con is not None:
            con.close()
    return out
