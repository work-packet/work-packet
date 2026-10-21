"""Shared fixtures. ``make_project`` builds a project the way the executor will."""

import os
import uuid

import pytest
import tomli_w

from work_packet import frontmatter, journal
from work_packet.packet import Packet, new_status

NOW = "2026-10-21T18:00:00Z"
ROOT = "3f0c9a2e-6d1b-4c61-9a57-0d5e7f1b2c3d"
NS_WPK = uuid.UUID("6f0c3e1a-8b7d-5c2e-9f4a-1d3b5e7a9c0b")
MODEL = "claude-haiku-4-5-20251001"


def child_wpid(parent, step, index):
    return str(uuid.uuid5(NS_WPK, "%s:%d:%d" % (parent, step, index)))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fp:
        fp.write(text)


def _new_packet(pdir, wpid, project, instruction, parent=None, spawn_key=None):
    path = os.path.join(pdir, wpid)
    os.makedirs(os.path.join(path, "state"))
    pkt = Packet(path)
    pkt.save_status(new_status(wpid, project, MODEL, NOW, parent, spawn_key))
    _write(pkt.memento_path, instruction)
    _write(pkt.journal_path, "")
    return pkt


def _commit(pkt, n, spawn=(), resume="now"):
    """Record step ``n`` of ``pkt`` as committed, spawning ``spawn`` (names)."""
    meta, _ = pkt.load_status()
    kids = []
    for i, name in enumerate(spawn):
        w = child_wpid(pkt.wpid, n, i)
        kids.append({"name": name, "wpid": w, "spawn_key": "%s:%d:%d" % (pkt.wpid, n, i),
                     "instruction": "Write Hello World to state/p.md, then finish.\n",
                     "copy": [], "model": None})
    summary = "Did step %d.\n" % n
    journal.append(pkt.journal_path, {"type": "step-start", "t": NOW, "step": n,
                                      "attempt": 1, "model": MODEL,
                                      "session_id": str(uuid.uuid4())})
    journal.append(pkt.journal_path, {"type": "commit-begin", "t": NOW, "step": n,
                                      "decision": {"state": "RUNNABLE", "resume_expr": resume,
                                                   "wake_at": None, "reason": None,
                                                   "model": MODEL, "summary": summary,
                                                   "spawn": kids}})
    pdir = os.path.dirname(pkt.path)
    for k in kids:
        _new_packet(pdir, k["wpid"], meta["project"], k["instruction"],
                    parent=pkt.wpid, spawn_key=k["spawn_key"])
        os.makedirs(pkt.children_dir, exist_ok=True)
        os.symlink(os.path.join("..", "..", k["wpid"]),
                   os.path.join(pkt.children_dir, k["wpid"]))
        meta["children"].append(k["wpid"])
    sd = pkt.step_dir(n)
    os.makedirs(sd)
    for f in ("prompt.md", "result.md", "summary.md", "state.diff"):
        _write(os.path.join(sd, f), "")
    fm = {"resume": resume}
    if spawn:
        fm["spawn"] = [{"name": k["name"], "instruction": k["instruction"]} for k in kids]
    _write(pkt.memento_path, frontmatter.dump(fm, "Read state/count.md and add one.\n"))
    meta.update(step=n, resume_expr=resume, updated=NOW)
    pkt.save_status(meta, summary)
    journal.append(pkt.journal_path, {"type": "commit-end", "t": NOW, "step": n})


def make_project(base, name="demo", steps=0, spawn_at=None):
    """A valid project at ``base/name`` with a root that has committed ``steps`` steps.

    ``spawn_at=k`` makes step k spawn one child named ``hello``.
    Returns (project dir, root Packet).
    """
    proj = os.path.join(str(base), name)
    os.makedirs(os.path.join(proj, "packets"))
    with open(os.path.join(proj, "project.toml"), "wb") as fp:
        tomli_w.dump({"name": name, "root": ROOT, "created": NOW, "template": "blank@1",
                      "tz": "UTC", "permissions": {"allowed_tools": ["Read", "Write"]}}, fp)
    _write(os.path.join(proj, "prompt.md"), "Count to 8.\n")
    root = _new_packet(os.path.join(proj, "packets"), ROOT, name,
                       "Read state/count.md and add one.\n")
    _write(os.path.join(root.state_dir, "count.md"), "0\n")
    for n in range(1, steps + 1):
        _commit(root, n, spawn=["hello"] if n == spawn_at else ())
    return proj, root


@pytest.fixture
def project(tmp_path):
    """A project whose root has run 3 steps and spawned one child at step 2."""
    return make_project(tmp_path, steps=3, spawn_at=2)
