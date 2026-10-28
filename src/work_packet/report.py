"""The completion report (docs/completion-report.md).

The step that says ``resume: done`` or ``resume: fail`` writes
``.pending/report.md``: what the whole packet did, the decisions it made and
where its results are. The executor keeps it as ``steps/NNNN/report.md`` and
``report.md``. Children's reports are rolled up when it is shown, since a
parent often finishes in the step that spawns them. The files it lists are
copied to ``steps/NNNN/deliverables/`` as they were when it was written
(``snapshot``), so a task's results can be looked at after later tasks change them.
"""

import json
import os
import re
import shutil

from . import frontmatter

NAME = "report.md"
SNAP = "deliverables"           # the step's copy of what the report lists
SNAP_INDEX = "deliverables.json"
SNAP_MAX = 64 * 1024 * 1024     # bytes copied per report; past it, only what fits
SNAP_SKIP = (".git",)           # a repo's history is not a result
SECTIONS = ("Outcome", "Decisions", "Deliverables", "Open items")
ROOTS = ("state", "work")       # where a deliverable may be
_HEAD = re.compile(r"^##\s+(.+?)\s*$", re.M)


def sections(body):
    """{heading: text} for the body's ``##`` sections, in order."""
    out = {}
    marks = list(_HEAD.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[m.group(1)] = body[m.end():end].strip()
    return out


def _resolve(rel, pkt_path, state_dir):
    """The file a deliverable path names, or a problem message."""
    if not isinstance(rel, str) or not rel.strip():
        return None, "must be a non-empty string"
    if os.path.isabs(rel):
        return None, "%s: must be relative to the packet (state/... or work/...)" % rel
    parts = os.path.normpath(rel).split(os.sep)
    if ".." in parts or parts[0] not in ROOTS:
        return None, "%s: must be under state/ or work/" % rel
    base = state_dir if parts[0] == "state" else os.path.join(pkt_path, "work")
    return os.path.join(base, *parts[1:]), None


def validate(meta, body, pkt_path, state_dir):
    """Problem messages for a report. ``state_dir``: where ``state/`` paths are
    checked; the step's ``.pending/state/`` before the commit."""
    if meta is None:
        return ["has no front matter (outcome: and deliverables: are required)"]
    out = []
    oc = meta.get("outcome")
    if not isinstance(oc, str) or not oc.strip():
        out.append("outcome: missing")
    elif "\n" in oc.strip():
        out.append("outcome: must be one line")
    dl = meta.get("deliverables")
    if dl is None:
        dl = []
    if not isinstance(dl, list):
        out.append("deliverables: must be a list of {path, what}")
        dl = []
    for i, d in enumerate(dl):
        w = "deliverables[%d]" % i
        if not isinstance(d, dict):
            out.append("%s: must be {path, what}" % w)
            continue
        p, why = _resolve(d.get("path"), pkt_path, state_dir)
        if why:
            out.append("%s.path: %s" % (w, why))
        elif not os.path.exists(p):
            out.append("%s.path: %s does not exist" % (w, d["path"]))
        if not isinstance(d.get("what"), str) or not d["what"].strip():
            out.append("%s.what: missing" % w)
        extra = sorted(set(d) - {"path", "what", "commit"})
        if extra:
            out.append("%s: unknown field %s" % (w, extra[0]))
    extra = sorted(set(meta) - {"outcome", "deliverables"})
    if extra:
        out.append("%s: unknown field" % extra[0])
    have = sections(body)
    missing = [s for s in SECTIONS if s not in have]
    if missing:
        out.append("body: missing section%s %s (need ## %s)" % (
            "s" if len(missing) > 1 else "", ", ".join(missing), ", ## ".join(SECTIONS)))
    return out


def _size(p):
    if os.path.islink(p) or not os.path.isdir(p):
        return os.lstat(p).st_size
    total = 0
    for top, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d not in SNAP_SKIP]
        total += sum(os.lstat(os.path.join(top, f)).st_size for f in files)
    return total


def snapshot(meta, pkt_path, state_dir, step_dir, limit=SNAP_MAX):
    """Copy each deliverable of ``meta`` to ``step_dir/deliverables/<path>`` and write
    ``deliverables.json``: ``{path: "copied" | "too large" | "missing"}``.
    ``state_dir`` as for ``validate``. One that would take the copy past ``limit``
    bytes is left out (the report still lists it; its commit, if any, still finds it)."""
    dst_top = os.path.join(step_dir, SNAP)
    if os.path.isdir(dst_top):      # a retried commit: start again
        shutil.rmtree(dst_top)
    index, used = {}, 0
    for d in meta.get("deliverables") or ():
        rel = os.path.normpath(d["path"])
        src, why = _resolve(rel, pkt_path, state_dir)
        if why or not os.path.lexists(src):
            index[rel] = "missing"
            continue
        n = _size(src)
        if used + n > limit:
            index[rel] = "too large"
            continue
        dst = os.path.join(dst_top, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*SNAP_SKIP))
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
        used += n
        index[rel] = "copied"
    with open(os.path.join(step_dir, SNAP_INDEX), "w") as fp:
        json.dump(index, fp, indent=1, sort_keys=True)
    return index


def snapshot_index(step_dir):
    """``deliverables.json`` of a step, or None if it took no snapshot."""
    try:
        with open(os.path.join(step_dir, SNAP_INDEX)) as fp:
            got = json.load(fp)
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def stamp(meta, heads):
    """``meta`` with ``commit:`` on each deliverable in a git work repo.
    ``heads``: ``{repo: sha}`` from ``workspace.heads``."""
    out = dict(meta)
    dl = []
    for d in meta.get("deliverables") or ():
        parts = os.path.normpath(d["path"]).split(os.sep)
        d = dict(d)
        if parts[0] == "work" and len(parts) > 1 and parts[1] in heads:
            d["commit"] = heads[parts[1]]
        dl.append(d)
    out["deliverables"] = dl
    return out


def load(path):
    """(meta, body) of a report file, or None if there is none or it is unreadable."""
    try:
        return frontmatter.load(path)
    except (OSError, frontmatter.FrontMatterError):
        return None


def of_packet(pkt):
    return load(os.path.join(pkt.path, NAME))


def _deliverable_lines(pkt, meta, indent=""):
    out = []
    for d in meta.get("deliverables") or ():
        at = " @ %s" % d["commit"][:12] if d.get("commit") else ""
        out.append("%s- %s%s: %s" % (indent, os.path.join(pkt.path, d["path"]), at,
                                     d.get("what", "")))
    return out


def _demote(text, by=1):
    """Markdown headings in ``text`` pushed down ``by`` levels."""
    return re.sub(r"^(#+ )", lambda m: "#" * by + m.group(1), text, flags=re.M)


def render(pkt, _depth=0, _seen=None):
    """The report as Markdown lines: deliverable paths made absolute, and the
    children's reports rolled up under ``## Children`` (recursively). None if
    the packet has no report."""
    from .packet import Packet
    rep = of_packet(pkt)
    if rep is None:
        return None
    meta, body = rep
    seen = _seen if _seen is not None else set()
    seen.add(pkt.wpid)
    secs = sections(body)
    out = []
    if _depth == 0:
        out += ["# Report: %s" % pkt.wpid, "", "**Outcome:** %s" % meta.get("outcome", ""), ""]
    for s, text in secs.items():
        if s == "Outcome" and _depth == 0:
            if text and text != (meta.get("outcome") or "").strip():
                out += [text, ""]
            continue
        if s == "Deliverables" and meta.get("deliverables"):
            out += ["## Deliverables", ""] + _deliverable_lines(pkt, meta)
            if text and _depth == 0:
                out += ["", text]
            out.append("")
            continue
        out += ["## %s" % s, "", text, ""] if text else ["## %s" % s, "", "(none)", ""]
    kids = _kids(pkt)
    if kids:
        out += ["## Children", ""]
        for wpid, state in kids:
            child = Packet(os.path.join(os.path.dirname(pkt.path), wpid))
            sub = None if wpid in seen else render(child, _depth + 1, seen)
            crep = of_packet(child) if sub is not None else None
            if crep is None:
                out += ["### %s (%s)" % (wpid, state or "unreadable"), "",
                        "No report yet." if state not in ("COMPLETED", "FAILED")
                        else "Finished without a report.", ""]
                continue
            out += ["### %s (%s): %s" % (wpid, state, crep[0].get("outcome", "")), "",
                    "Report: %s" % os.path.join(child.path, NAME), ""]
            out += [_demote(x, 2) for x in sub]
    while out and out[-1] == "":
        out.pop()
    return out


def _kids(pkt):
    """[(child wpid, state or None)] in spawn order."""
    from .packet import Packet
    try:
        meta, _ = pkt.load_status()
    except (OSError, frontmatter.FrontMatterError):
        return []
    out = []
    for w in meta.get("children") or ():
        try:
            m, _ = Packet(os.path.join(os.path.dirname(pkt.path), w)).load_status()
            out.append((w, m.get("state")))
        except (OSError, frontmatter.FrontMatterError):
            out.append((w, None))
    return out
