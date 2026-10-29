"""The ``lsf`` backend: one ``bsub`` job per step (docs/scheduler.md §5.1, §5.5).

One ``bjobs -a`` call for every job per poll. A step may start its own jobs
through DFM; those are not the pool's and are not counted here.
"""

import json
import os
import re
import shlex
import subprocess
from datetime import datetime

from ... import schema
from . import DONE, LOST, PENDING, RUNNING, Backend, BackendError, JobState
from .slurm import MARGIN_S, TIMEOUT_S, node_command

QUEUED = {"PEND": PENDING, "PSUSP": PENDING, "WAIT": PENDING, "PROV": PENDING,
          "RUN": RUNNING, "USUSP": RUNNING, "SSUSP": RUNNING}
# EXIT reasons that are the farm's doing: retried, not counted (§5.5).
FARM = {"TERM_PREEMPT": "preempted", "TERM_ADMIN": "killed by an admin",
        "TERM_LOAD": "host overloaded", "TERM_HOST": "host failure",
        "TERM_REQUEUE_ADMIN": "requeued by an admin", "TERM_ZOMBIE": "zombie job",
        "TERM_UNKNOWN": "unknown", "TERM_OWNER": "killed by its owner"}
FIELDS = "jobid job_name stat exit_code exit_reason start_time finish_time cpu_used"
_SUBMITTED = re.compile(r"Job <(\d+)>")


def hhmm(s):
    m = (int(s) + 59) // 60
    return "%d:%02d" % (m // 60, m % 60)


def resource_string(z):
    """The one ``-R`` for a size: its ``resources`` merged with ``rusage[mem]``
    and ``span[hosts=1]``. Several selects are and-ed; the size's own span
    replaces the default; its rusage is added after the memory."""
    parts = {"select": [], "rusage": ["mem=%d" % z.mem_mb] if z.mem_mb else []}
    order = ["select", "rusage"]
    for name, body in schema.lsf_sections(z.resources):
        if name in ("select", "rusage"):
            parts[name].append(body)
        else:
            parts[name] = [body]
            if name not in order:
                order.append(name)
    if "span" not in parts:
        parts["span"], order = ["hosts=1"], order + ["span"]
    sel = parts["select"]
    parts["select"] = [" && ".join("(%s)" % b for b in sel) if len(sel) > 1 else sel[0]] if sel else []
    parts["rusage"] = [", ".join(parts["rusage"])] if parts["rusage"] else []
    return " ".join("%s[%s]" % (n, parts[n][0]) for n in order if parts[n])


def cpu_seconds(v):
    """bjobs ``cpu_used``: ``HH:MM:SS`` or ``1.5 second(s)``."""
    if not v:
        return None
    v = v.strip()
    m = re.match(r"([\d.]+)\s*second", v)
    if m:
        return float(m.group(1))
    try:
        parts = [float(x) for x in v.split(":")]
    except ValueError:
        return None
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def utc(v, now=None):
    """bjobs times (``Oct 26 10:00``, ``Oct 26 10:00:05 2026``, local) as ``...Z``."""
    if not v or v.strip() in ("-", ""):
        return None
    v = " ".join(v.replace(" L", "").replace(" E", "").split())
    now = now or datetime.now()
    for fmt in ("%b %d %H:%M:%S %Y", "%b %d %H:%M %Y", "%Y/%m/%d-%H:%M:%S"):
        try:
            return schema.format_timestamp(datetime.strptime(v, fmt).astimezone())
        except ValueError:
            pass
    for fmt in ("%b %d %H:%M:%S", "%b %d %H:%M"):
        try:
            t = datetime.strptime("%s %d" % (v, now.year), fmt + " %Y")
            return schema.format_timestamp(t.astimezone())
        except ValueError:
            pass
    return None


class Lsf(Backend):
    name = "lsf"
    poll_s = 15.0
    holds_room_while_pending = True

    def __init__(self, cfg, h=None):
        self.cfg = cfg
        self.h = h
        s = cfg.get("lsf") or {}
        self.bin = s.get("bin", "")
        self.common = {"queue": s.get("queue", ""), "project": s.get("project", ""),
                       "extra": list(s.get("extra") or ())}
        if s.get("poll"):
            self.poll_s = float(schema.parse_duration(s["poll"]))
        self.step_timeout_s = schema.parse_duration(cfg.get("step_timeout", "120m"))

    def _run(self, name, args, ok_codes=(0,)):
        argv = [os.path.join(self.bin, name) if self.bin else name] + list(args)
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BackendError("%s: %s" % (name, e)) from None
        if p.returncode not in ok_codes:
            raise BackendError("%s: %s" % (name, (p.stderr or p.stdout).strip().splitlines()[-1:]
                                           or "exit %d" % p.returncode))
        return p

    def submit_argv(self, task):
        z = task.size
        limit = z.time_s or (self.step_timeout_s + MARGIN_S)
        argv = ["-J", task.name, "-W", hhmm(limit), "-n", str(z.cpus),
                "-R", resource_string(z)]
        q = z.queue or self.common["queue"]
        if q:
            argv += ["-q", q]
        if self.common["project"]:
            argv += ["-P", self.common["project"]]
        argv += self.common["extra"] + list(z.extra) + ["-o", task.log]
        cmd = " ".join(shlex.quote(a) for a in task.argv) if task.argv else \
            node_command(self.cfg, task.path, task.lost)
        return argv + ["bash", "-c", cmd]

    def submit(self, task):
        os.makedirs(os.path.dirname(task.log), exist_ok=True)
        p = self._run("bsub", self.submit_argv(task))
        m = _SUBMITTED.search(p.stdout)
        if not m:
            raise BackendError("bsub printed no job ID: %r" % p.stdout[:200])
        return m.group(1)

    def _bjobs(self, args):
        p = self._run("bjobs", ["-a", "-o", FIELDS, "-json"] + list(args), ok_codes=(0, 255))
        try:
            d = json.loads(p.stdout or "{}")
        except ValueError:
            raise BackendError("bjobs printed no JSON: %r" % p.stdout[:200]) from None
        out = {}
        for r in d.get("RECORDS") or ():
            if r.get("JOBID") and not r.get("ERROR"):
                out[str(r["JOBID"])] = r
        return out

    def poll(self, refs):
        refs = [r for r in refs if r]
        if not refs:
            return {}
        recs = self._bjobs(refs)
        return {r: self._state(recs[r]) if r in recs else
                JobState(LOST, reason="unknown to the batch system", counted=False)
                for r in refs}

    @staticmethod
    def _state(r):
        stat = r.get("STAT", "")
        if stat in QUEUED:
            return JobState(QUEUED[stat])
        try:
            code = int(r.get("EXIT_CODE") or 0)
        except ValueError:
            code = None
        why = (r.get("EXIT_REASON") or "").strip()
        term = next((t for t in FARM if t in why), None)
        started, ended = utc(r.get("START_TIME")), utc(r.get("FINISH_TIME"))
        cpu = cpu_seconds(r.get("CPU_USED"))
        if stat in ("UNKWN", "ZOMBI"):
            return JobState(LOST, reason="job state %s" % stat, counted=False,
                            started=started, ended=ended, cpu_s=cpu)
        if stat == "DONE":
            return JobState(DONE, code=0, started=started, ended=ended, cpu_s=cpu)
        if term:
            return JobState(LOST, code=code, reason=FARM[term], counted=False, started=started,
                            ended=ended, cpu_s=cpu)
        # EXIT: the step's own failure, or TERM_RUNLIMIT (counted, as a step timeout).
        return JobState(DONE, code=code, started=started, ended=ended, cpu_s=cpu,
                        reason="timeout" if "TERM_RUNLIMIT" in why else (why or None))

    def cancel(self, ref, hard=False):
        if hard:
            self._run("bkill", [ref], ok_codes=(0, 255))
        else:
            self._run("bkill", ["-s", "TERM", ref], ok_codes=(0, 255))

    def list_ours(self):
        from ... import registry
        from ..dispatcher import home_id
        prefix = "wpk:%s:" % home_id(self.h or registry.home())
        recs = self._bjobs(["-J", prefix + "*"])
        return {jid: r.get("JOB_NAME", "") for jid, r in recs.items()
                if r.get("STAT") in QUEUED and r.get("JOB_NAME", "").startswith(prefix)}

    def running(self):
        return []
