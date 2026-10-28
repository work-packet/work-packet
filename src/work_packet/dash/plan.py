"""A packet's plan as a tree, and the sequence of its versions (docs/plan-tree.md).

The plan is ``state/outline.md``, a Markdown checklist the model edits each step.
``parse`` turns one copy into a tree; ``versions`` recovers the copy after each
step that changed it, from the step folders (the outline the step's prompt
showed, else the step's ``state.diff`` undone) and the outlines that next-batch
hand-offs moved to ``state/history/``.
"""

import os
import re

from .. import frontmatter, schema
from ..packet import Packet

OUTLINE = "state/outline.md"
STATE = {" ": "pending", "x": "done", "X": "done", ">": "active", "+": "added",
         "-": "deferred", "~": "partial"}
MARK = {"done": "✓", "active": "▶", "deferred": "–", "added": "+", "partial": "◐",
        "pending": "○"}

_LIST = re.compile(r"^([ \t]*)(?:[-*+]|\d+[.)])[ \t]+(.*)$")
_BOX = re.compile(r"^\[([ xX>+\-~])\][ \t]*(.*)$")
_HEAD = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_ID = re.compile(r"^(\**)([A-Za-z]?\d+(?:[.\-]?[A-Za-z0-9]+)*)[.:)]?(\1)?(?=[\s,;]|$)")
# a sub-item written into its parent's text: "...; [x] 3b harness ..."
_INLINE = re.compile(r"(?:(?<=^)|(?<=[\s;,(]))\[([ xX>+\-~])\][ \t]+(?=\**[A-Za-z]?\d)")


# --- one outline ----------------------------------------------------------------

def _node(kind, **kw):
    n = {"kind": kind, "id": None, "state": None, "text": "", "details": [], "notes": [],
         "children": []}
    n.update(kw)
    return n


def parse(text):
    """``{"title", "notes", "children"}``: groups for headings, items for
    checkbox lines (nested by indent, or written inline in the parent's text),
    ``details`` for plain bullets under an item, ``notes`` for other text."""
    root = _node("root", title=None)
    heads = [(0, root)]                       # (heading level, group)
    items = []                                # (indent, item) of the open list
    last, blank, seen_item = None, False, False
    for ln in (text or "").splitlines():
        if not ln.strip():
            blank = True
            continue
        h = _HEAD.match(ln)
        if h and not ln[:1].isspace():
            level = len(h.group(1))
            if level == 1 and root["title"] is None and not seen_item and len(heads) == 1:
                root["title"] = h.group(2)
            else:
                while heads[-1][0] >= level:
                    heads.pop()
                g = _node("group", text=h.group(2))
                heads[-1][1]["children"].append(g)
                heads.append((level, g))
            items, last, blank = [], None, False
            continue
        group = heads[-1][1]
        indent = len(re.match(r"[ \t]*", ln).group().expandtabs(4))
        li = _LIST.match(ln)
        if li and ln.lstrip().startswith("+ ") and not blank and last and last[0] == "item":
            li = None                         # "... + more", wrapped: not a bullet
        box = _BOX.match(li.group(2)) if li else None
        if box:
            while items and items[-1][0] >= indent:
                items.pop()
            it = _node("item", state=STATE[box.group(1)], text=box.group(2).strip())
            (items[-1][1] if items else group)["children"].append(it)
            items.append((indent, it))
            last, blank, seen_item = ("item", it), False, True
            continue
        while items and items[-1][0] >= indent and (li or blank or indent == 0):
            items.pop()                       # a bullet or paragraph after the list
        owner = items[-1][1] if items else None
        if li and owner:
            owner["details"].append(li.group(2).strip())
            last = ("detail", owner)
        elif last and not (blank and indent == 0) and (indent > 0 or not blank) \
                and last[0] in ("item", "detail") and owner is not None:
            if last[0] == "item":
                last[1]["text"] += " " + ln.strip()
            else:
                last[1]["details"][-1] += " " + ln.strip()
        elif li:
            group["notes"].append("- " + li.group(2).strip())
            last = ("note", group)
        elif last and last[0] == "note" and not blank and last[1] is group:
            group["notes"][-1] += " " + ln.strip()
        else:
            group["notes"].append(ln.strip())
            last = ("note", group)
        blank = False
    _finish(root)
    return root


def _finish(n):
    for c in n["children"]:
        _finish(c)
    if n["kind"] != "item":
        return
    parts = list(_INLINE.finditer(n["text"]))
    if parts:
        kids = []
        for i, mo in enumerate(parts):
            end = parts[i + 1].start() if i + 1 < len(parts) else len(n["text"])
            t = n["text"][mo.end():end].strip().rstrip(";,").strip()
            kid = _node("item", state=STATE[mo.group(1)], text=t)
            _finish(kid)
            kids.append(kid)
        n["text"] = n["text"][:parts[0].start()].strip().rstrip(";,").strip()
        n["children"] = kids + n["children"]
    mo = _ID.match(n["text"])
    if mo:
        n["id"] = mo.group(2)
        n["text"] = n["text"][mo.end():].strip()
        if mo.group(1) and not mo.group(3) and n["text"].endswith(mo.group(1)):  # **4 Title**
            n["text"] = mo.group(1) + n["text"]


def walk(n, depth=0):
    """(depth, node) for every node under ``n``, in order."""
    for c in n["children"]:
        yield depth, c
        yield from walk(c, depth + 1)


def key(n):
    return n["id"] or " ".join(n["text"].lower().split())[:80]


def count(n):
    """(done, total) over the items under ``n``; deferred items are not counted."""
    done = total = 0
    for _, c in walk(n):
        if c["kind"] == "item" and c["state"] != "deferred":
            total += 1
            done += c["state"] == "done"
    return done, total


def current(tree):
    """The item being worked on: the first active one with no active item under
    it, else the first leaf to do."""
    items = [c for _, c in walk(tree) if c["kind"] == "item"]
    return next((c for c in items if c["state"] == "active" and not any(
        k["state"] == "active" for _, k in walk(c))), None) or \
        next((c for c in items if c["state"] in ("pending", "added", "partial")
              and not c["children"]), None)


# --- the copies over time -----------------------------------------------------------

def _read(path):
    try:
        with open(path, encoding="utf-8") as fp:
            return fp.read()
    except (OSError, UnicodeDecodeError):
        return None


def from_prompt(text):
    """The outline as a step's prompt showed it (prompt.state_files), or None."""
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "- `%s`:" % OUTLINE:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            fence = lines[j].strip() if j < len(lines) else ""
            if not re.fullmatch(r"`{3,}", fence):
                return None
            body = []
            for ln2 in lines[j + 1:]:
                if ln2.strip() == fence:
                    return "\n".join(body) + "\n" if body else ""
                body.append(ln2)
            return None
    return None


def _hunks(diff, name=OUTLINE):
    """The hunks of ``diff`` for the file ``name``: [(new start, new count, lines)]."""
    out, lines, i = [], diff.splitlines(), 0
    while i < len(lines):
        if lines[i] == "--- a/" + name and i + 1 < len(lines) and lines[i + 1] == "+++ b/" + name:
            i += 2
            while i < len(lines):
                h = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
                if not h:
                    break
                old_n = 1 if h.group(2) is None else int(h.group(2))
                new_n = 1 if h.group(4) is None else int(h.group(4))
                i += 1
                body, a, b = [], 0, 0
                while i < len(lines) and (a < old_n or b < new_n or lines[i].startswith("\\")):
                    ln = lines[i]
                    i += 1
                    if ln.startswith("\\"):
                        continue
                    tag, rest = (ln[:1] or " "), ln[1:]
                    body.append((tag, rest))
                    a += tag in " -"
                    b += tag in " +"
                out.append((int(h.group(3)), new_n, body))
            return out
        i += 1
    return out


def undo(text, diff):
    """``text`` (the outline after a step) with the step's ``diff`` undone: the
    outline before it. ``text`` itself if the diff does not touch the outline;
    None if it does not apply."""
    hunks = _hunks(diff or "")
    if not hunks:
        return text
    cur = (text or "").splitlines()
    for start, n, body in reversed(hunks):
        new = [r for t, r in body if t in " +"]
        old = [r for t, r in body if t in " -"]
        at = start - 1 if n else start
        if not new and start == 0 and cur:
            return None                       # the step deleted it, yet here it is
        if cur[at:at + len(new)] != new:
            near = [k for k in range(len(cur) - len(new) + 1) if cur[k:k + len(new)] == new]
            if not near:
                return None
            at = min(near, key=lambda k: abs(k - at))
        cur[at:at + len(new)] = old
    return "\n".join(cur) + "\n" if cur else ""


def _batches(records):
    """({step: batch}, {last step of a batch: (archived outline, next batch, instruction)},
    {batch: instruction})."""
    batch, last, of, ends, why = 1, 0, {}, {}, {}
    for r in records:
        t = r.get("type")
        if t == "step-start" and isinstance(r.get("step"), int):
            of[r["step"]] = batch
        elif t == "commit-end" and isinstance(r.get("step"), int):
            last = r["step"]
        elif t == "handoff" and "instruction" in r:
            batch += 1
            ends[last] = (r.get("outline"), batch, r.get("instruction"))
            why[batch] = r.get("instruction")
    return of, ends, why


def sd_of(pkt, s):
    return os.path.join(pkt.steps_dir, s["dir"])


def _summary(sd):
    """The first line of the step's summary that is not a heading."""
    for ln in (_read(os.path.join(sd, "summary.md")) or "").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            return ln
    return None


def versions(pkt, steps):
    """The outline after each step that changed it, oldest first: dicts of
    ``key`` (``s<n>``, ``b<batch>`` for a batch's starting outline, or ``run``
    for a running step), ``label``, ``batch``, ``step``, ``item``, ``summary`` and
    ``text``. ``steps`` is data.steps(pkt)."""
    records = pkt.journal().records
    of, ends, why = _batches(records)
    done = [s for s in steps if s["outcome"] == "committed"]
    cur = _read(os.path.join(pkt.state_dir, "outline.md")) or ""
    walked = []                                   # (step, before, after), newest first
    for s in reversed(done):
        if s["n"] in ends and ends[s["n"]][0]:
            arch = _read(os.path.join(pkt.path, ends[s["n"]][0]))
            if arch is not None:
                cur = arch
        sd = os.path.join(pkt.steps_dir, s["dir"])
        before = from_prompt(_read(os.path.join(sd, "prompt.md")))
        if before is None:
            before = undo(cur, _read(os.path.join(sd, "state.diff")))
        if before is None:
            before = cur
        walked.append((s, before, cur))
        cur = before
    out, prev, prev_batch = [], None, None
    for s, before, after in reversed(walked):
        b = of.get(s["n"], prev_batch or 1)
        if b != prev_batch and before.strip() and before != prev:
            out.append({"key": "b%d" % b, "label": "start of batch %d" % b, "batch": b,
                        "step": None, "item": None, "summary": None, "text": before})
            prev = before
        prev_batch = b
        if after != prev and after.strip():
            out.append({"key": "s%d" % s["n"], "label": "after step %d" % s["n"], "batch": b,
                        "step": s["n"], "dir": s["dir"], "item": s["item"],
                        "summary": _summary(sd_of(pkt, s)), "text": after})
            prev = after
    run = steps[-1] if steps and steps[-1]["outcome"] == "running" else None
    if run:
        text = _read(os.path.join(pkt.pending_dir, "state", "outline.md"))
        if text and text != prev and text.strip():
            out.append({"key": "run", "label": "step %d (running)" % run["n"],
                        "batch": of.get(run["n"], prev_batch or 1), "step": run["n"],
                        "dir": run["dir"], "item": run["item"], "summary": None, "text": text})
    elif not out and cur.strip():
        out.append({"key": "now", "label": "now", "batch": prev_batch or 1, "step": None,
                    "item": None, "summary": None, "text": cur})
    for b in sorted({v["batch"] for v in out}):
        for v in out:
            if v["batch"] == b:
                v["instruction"] = why.get(b)
                break
    return out


# --- comparing two copies ---------------------------------------------------------------

def compare(tree, old):
    """Mark each node of ``tree`` against the earlier tree ``old``: ``change`` is
    "new", "state" (with ``was``) or "edited"; ``changed`` on nodes with a changed
    node under them. Returns the items of ``old`` that are gone."""
    had = {key(n): n for _, n in walk(old)}
    keys = set()
    for _, n in walk(tree):
        k = key(n)
        keys.add(k)
        o = had.get(k)
        if o is None:
            n["change"] = "new"
        elif o["state"] != n["state"]:
            n["change"], n["was"] = "state", o["state"]
        elif o["text"] != n["text"] or o["details"] != n["details"]:
            n["change"] = "edited"
    _flag(tree)
    return [n for _, n in walk(old) if n["kind"] == "item" and key(n) not in keys]


def _flag(n):
    hit = False
    for c in n["children"]:
        hit = _flag(c) or hit
    n["changed"] = hit
    return hit or bool(n.get("change"))


def ids_of(item):
    """Plan item ids named by a step's memento ``item`` ("4a", "6a, 6b", "[5b, 5c]")."""
    return [t for t in re.split(r"[,\s\[\]]+", item or "") if t]


# --- the page ------------------------------------------------------------------------------

def page(entry, wpid, steps, v=None, changes=False, opened=None):
    """What /p/<project>/<wpid>/plan shows; None if there is no such packet.
    ``v``: a version key (default the newest); ``changes``: only what changed in
    it; ``opened``: "all" or "none" to open or close every node."""
    if not schema.is_wpid(wpid):
        return None
    pkt = Packet(os.path.join(entry["path"], "packets", wpid))
    if not os.path.isdir(pkt.path):
        return None
    vs = versions(pkt, steps)
    i = next((k for k, x in enumerate(vs) if x["key"] == v), len(vs) - 1)
    out = {"wpid": wpid, "short": wpid[:8], "versions": vs, "v": vs[i] if vs else None,
           "latest": i == len(vs) - 1, "changes": changes, "tree": None, "gone": [],
           "children": []}
    if not vs:
        return out
    tree = parse(vs[i]["text"])
    if i > 0:
        out["gone"] = compare(tree, parse(vs[i - 1]["text"]))
    by_id = {}
    for s in steps:
        ids = ids_of(s["item"])
        for t in ids:
            by_id.setdefault(t, []).append(dict(s, share=(s["cost_usd"] or 0) / len(ids)))
    cur = current(tree)
    _decorate(tree, by_id, cur, opened, vs[i]["step"])
    try:
        notes = {n[:-3] for n in os.listdir(os.path.join(pkt.state_dir, "notes"))
                 if n.endswith(".md")}
    except OSError:
        notes = set()
    out.update(tree=tree, done=count(tree), current=cur, notes=notes)
    if out["latest"]:
        out["children"] = _children(entry, pkt)
    return out


def _decorate(n, by_id, cur, opened, upto):
    """Steps, cost and whether it starts open, on each node; returns (has the
    current item, cost of the subtree)."""
    has, cost = n is cur, 0.0
    if n["kind"] == "item" and n["id"]:
        n["steps"] = [s for s in by_id.get(n["id"], ()) if upto is None or s["n"] <= upto]
        cost += sum(s["share"] for s in n["steps"])
    for c in n["children"]:
        h, k = _decorate(c, by_id, cur, opened, upto)
        has, cost = has or h, cost + k
    n["cost"] = cost
    n["count"] = count(n)
    n["current"] = n is cur
    d, t = n["count"]
    if opened == "all":
        n["open"] = True
    elif opened == "none":
        n["open"] = False
    else:
        n["open"] = has or n.get("changed") or (t > d and n["state"] != "done") \
            or n["kind"] == "group" and t > d
    return has, cost


def _children(entry, pkt):
    try:
        meta, _ = pkt.load_status()
    except (OSError, frontmatter.FrontMatterError):
        return []
    out = []
    for c in meta.get("children") or ():
        if not schema.is_wpid(c):
            continue
        kid = Packet(os.path.join(entry["path"], "packets", c))
        text = _read(os.path.join(kid.state_dir, "outline.md"))
        tree = parse(text) if text else None
        if tree:
            _decorate(tree, {}, current(tree), None, None)
        try:
            st = kid.load_status()[0].get("state")
        except (OSError, frontmatter.FrontMatterError):
            st = "?"
        out.append({"wpid": c, "short": c[:8], "state": st, "tree": tree,
                    "done": count(tree) if tree else (0, 0)})
    return out
