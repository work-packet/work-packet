"""A packet directory: paths, and reading and writing its status."""

import os

from . import frontmatter, fsutil, journal, schema


class Packet:

    def __init__(self, path):
        self.path = os.path.abspath(path)

    @property
    def wpid(self):
        return os.path.basename(self.path)

    def _p(self, *parts):
        return os.path.join(self.path, *parts)

    status_path = property(lambda s: s._p("status.md"))
    memento_path = property(lambda s: s._p("memento.md"))
    report_path = property(lambda s: s._p("report.md"))
    state_dir = property(lambda s: s._p("state"))
    identity_dir = property(lambda s: s._p("identity"))
    children_dir = property(lambda s: s._p("children"))
    journal_path = property(lambda s: s._p("journal.jsonl"))
    steps_dir = property(lambda s: s._p("steps"))
    lease_path = property(lambda s: s._p(".lease"))
    pause_path = property(lambda s: s._p(".pause"))   # a pause asked for while a step runs
    pending_dir = property(lambda s: s._p(".pending"))
    state_old_dir = property(lambda s: s._p(".state.old"))

    def step_dir(self, n, failed_attempt=None):
        name = schema.step_dir_name(n)
        if failed_attempt is not None:
            name += ".failed-%d" % failed_attempt
        return os.path.join(self.steps_dir, name)

    def failed_runs(self, n):
        """The numbers of step ``n``'s failed folders (``NNNN.failed-<run>``), in order."""
        try:
            names = os.listdir(self.steps_dir)
        except OSError:
            return []
        return sorted(f for s, f in filter(None, map(schema.parse_step_dir, names))
                      if s == n and f is not None)

    def next_run(self, n):
        """The number of step ``n``'s next run: one past its last failed folder.
        Unlike the attempt count, it never goes back when the packet is resumed,
        so a run's folder and session ID are never reused."""
        runs = self.failed_runs(n)
        return runs[-1] + 1 if runs else 1

    def load_status(self):
        """(meta, body). Raises FrontMatterError or OSError."""
        return frontmatter.load(self.status_path)

    def save_status(self, meta, body=""):
        """Write status.md atomically, keys in spec order."""
        ordered = {k: meta[k] for k in schema.STATUS_FIELDS if k in meta}
        ordered.update({k: v for k, v in meta.items() if k not in ordered})
        fsutil.atomic_write(self.status_path, frontmatter.dump(ordered, body))

    def load_memento(self):
        return frontmatter.load(self.memento_path)

    def journal(self):
        return journal.read(self.journal_path)

    def child_links(self):
        """{child WPID: link target} for the entries in children/."""
        out = {}
        try:
            names = sorted(os.listdir(self.children_dir))
        except FileNotFoundError:
            return out
        for n in names:
            p = os.path.join(self.children_dir, n)
            out[n] = os.readlink(p) if os.path.islink(p) else None
        return out


def new_status(wpid, project, model, updated, parent=None, spawn_key=None):
    """Status for a packet that has never run."""
    return {
        "wpk": schema.FORMAT_VERSION,
        "wpid": wpid,
        "project": project,
        "state": "RUNNABLE",
        "step": 0,
        "attempts": 0,
        "parent": parent,
        "spawn_key": spawn_key,
        "children": [],
        "resume_expr": None,
        "wake_at": None,
        "model": model,
        "reason": None,
        "updated": updated,
    }
