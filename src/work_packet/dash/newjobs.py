"""Packets being made in the background, so the Create page can show the
clone and the dependencies as they go (dash-create-progress-design.md).

A job runs ``starters.make`` in a thread. Its events (``starters._Report``,
plus a last ``{"k": "done", ok, url | error}``) are numbered ``n``, kept,
journaled to ``$WPK_HOME/runs/create/<id>.jsonl`` (which outlives the clone a
failure removes) and sent to the open sockets."""

import json
import os
import secrets
import threading
import time

KEEP = 20                             # finished jobs kept in memory
GIT_EVERY = 0.2                       # seconds between two git reports of a package


def journal_dir(home=None):
    from .. import registry
    return os.path.join(home or registry.home(), "runs", "create")


class CreateJobs:
    def __init__(self, home):
        self.home = home
        self.lock = threading.Lock()
        self.jobs = {}                # id -> job dict
        self.subs = {}                # id -> [(loop, queue)]

    def start(self, recipe, folder, finish, h=None):
        """Make ``recipe`` in a thread; ``finish(plan)`` gives the page to go to
        once it is made. Returns the job id. Raises ValueError while another job
        makes the same folder."""
        from .. import starters
        with self.lock:
            for j in self.jobs.values():
                if j["state"] == "run" and j["folder"] == folder:
                    raise ValueError("%s is being made already (job %s)" % (folder, j["id"]))
            jid = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), secrets.token_hex(3))
            job = {"id": jid, "name": recipe["name"], "folder": folder, "state": "run",
                   "t": time.time(), "events": [], "url": None, "error": None,
                   "_git": {}}
            self.jobs[jid] = job
            self._prune()
        os.makedirs(journal_dir(self.home), exist_ok=True)

        def run():
            try:
                plan = starters.make(recipe, h, progress=lambda ev: self.emit(jid, ev))
                url = finish(plan)
                self.emit(jid, {"k": "done", "ok": True, "url": url, "name": plan.name})
            except Exception as e:    # noqa: BLE001  shown on the page, not lost in a thread
                msg = str(e) if isinstance(e, (starters.StartError, OSError, ValueError)) \
                    else "%s: %s" % (type(e).__name__, e)
                self.emit(jid, {"k": "done", "ok": False, "error": msg})

        threading.Thread(target=run, name="new-%s" % jid, daemon=True).start()
        return jid

    def _prune(self):
        done = sorted((j for j in self.jobs.values() if j["state"] != "run"),
                      key=lambda j: j["t"])
        for j in done[:max(0, len(done) - KEEP)]:
            self.jobs.pop(j["id"], None)

    def emit(self, jid, ev):
        with self.lock:
            job = self.jobs.get(jid)
            if job is None:
                return
            now = time.time()
            if ev.get("k") == "git" and ev.get("pct") != 100:
                key = (ev.get("step"), ev.get("pkg"))
                if now - job["_git"].get(key, 0) < GIT_EVERY:
                    return            # often many a second: the page needs a few
                job["_git"][key] = now
            ev = dict(ev, n=len(job["events"]) + 1, t=round(now, 3))
            job["events"].append(ev)
            if ev["k"] == "done":
                job["state"] = "ok" if ev["ok"] else "fail"
                job["url"], job["error"] = ev.get("url"), ev.get("error")
            try:
                with open(os.path.join(journal_dir(self.home), jid + ".jsonl"), "a") as fp:
                    fp.write(json.dumps(ev) + "\n")
            except OSError:
                pass                  # the page still has it
            subs = list(self.subs.get(jid, []))
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
            except RuntimeError:      # that loop has closed
                pass

    def get(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            return None if job is None else {k: v for k, v in job.items()
                                             if not k.startswith("_") and k != "events"}

    def subscribe(self, jid, loop, queue, since=0):
        """The events after ``since``, and later ones into ``queue`` (no gap)."""
        with self.lock:
            self.subs.setdefault(jid, []).append((loop, queue))
            job = self.jobs.get(jid)
            return [e for e in (job["events"] if job else []) if e["n"] > since]

    def unsubscribe(self, jid, queue):
        with self.lock:
            self.subs[jid] = [s for s in self.subs.get(jid, []) if s[1] is not queue]
            if not self.subs[jid]:
                del self.subs[jid]

    def log(self, jid):
        """The job's journal as text: its steps and what the commands printed;
        None if there is none."""
        if not jid.replace("-", "").isalnum():
            return None
        try:
            with open(os.path.join(journal_dir(self.home), jid + ".jsonl")) as fp:
                evs = [json.loads(ln) for ln in fp if ln.strip()]
        except (OSError, ValueError):
            return None
        out, label = [], {}
        for e in evs:
            k = e.get("k")
            if k == "line":
                out.append(e.get("text", ""))
            elif k == "step":
                label[e.get("id")] = e.get("label") or label.get(e.get("id")) or e.get("id")
                out.append("== %s %s%s%s" % (label[e.get("id")], e.get("state"),
                                             " (%ss)" % e["secs"] if e.get("secs") is not None
                                             else "", ": " + e["note"] if e.get("note") else ""))
            elif k == "tool":
                out.append("== %s %s" % (e.get("name"), e.get("version") or "(version unknown)"))
            elif k in ("note", "undo", "done"):
                out.append("== " + json.dumps({x: y for x, y in e.items()
                                               if x not in ("n", "t")}))
        return "\n".join(out) + "\n"
