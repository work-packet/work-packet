"""Children: deterministic WPIDs and idempotent creation (spec §6)."""

import glob
import os
import shutil
import uuid

from . import faults, fsutil, schema
from .packet import Packet, new_status

NS_WPK = uuid.UUID("6f0c3e1a-8b7d-5c2e-9f4a-1d3b5e7a9c0b")


def child_wpid(parent, step, index):
    return str(uuid.uuid5(NS_WPK, "%s:%d:%d" % (parent, step, index)))


def decision_entries(parent, step, spawn):
    """The memento's ``spawn`` list as commit-begin entries, WPIDs computed."""
    out = []
    for i, e in enumerate(spawn or ()):
        out.append({"name": e["name"], "wpid": child_wpid(parent, step, i),
                    "spawn_key": "%s:%d:%d" % (parent, step, i),
                    "instruction": e["instruction"], "copy": list(e.get("copy") or []),
                    "model": e.get("model")})
    return out


def _copy_globs(src, dst, patterns):
    for pat in patterns:
        for rel in sorted(glob.glob(pat, root_dir=src, recursive=True)):
            s, d = os.path.join(src, rel), os.path.join(dst, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if os.path.isdir(s) and not os.path.islink(s):
                shutil.copytree(s, d, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d, follow_symlinks=False)


def create_child(parent, entry, source_state, project, parent_model, now):
    """Create one child unless it exists, then link it from ``parent/children``.

    The child is built in ``packets/.tmp-<WPID>`` and renamed into place, so
    it either exists whole or not at all.
    """
    packets = os.path.dirname(parent.path)
    wpid = entry["wpid"]
    final = os.path.join(packets, wpid)
    if not os.path.exists(final):
        tmp = os.path.join(packets, ".tmp-" + wpid)
        shutil.rmtree(tmp, ignore_errors=True)
        child = Packet(tmp)
        os.makedirs(child.state_dir)
        _copy_globs(source_state, child.state_dir, entry.get("copy") or ())
        if os.path.isdir(parent.identity_dir):
            os.makedirs(child.identity_dir)
            for n in sorted(os.listdir(parent.identity_dir)):
                p = os.path.join(parent.identity_dir, n)
                if os.path.islink(p):
                    os.symlink(os.readlink(p), os.path.join(child.identity_dir, n))
        st = new_status(wpid, project, entry.get("model") or parent_model,
                        schema.format_timestamp(now), parent.wpid, entry["spawn_key"])
        child.save_status(st)
        fsutil.atomic_write(child.memento_path, entry["instruction"])
        fsutil.atomic_write(child.journal_path, "")
        fsutil.rename(tmp, final)
    os.makedirs(parent.children_dir, exist_ok=True)
    link = os.path.join(parent.children_dir, wpid)
    if not os.path.lexists(link):
        os.symlink(os.path.join("..", "..", wpid), link)
        fsutil.fsync_dir(parent.children_dir)


def create_children(parent, entries, source_state, project, parent_model, now):
    for i, e in enumerate(entries):
        create_child(parent, e, source_state, project, parent_model, now)
        if i == 0:
            faults.point("mid-spawn")
