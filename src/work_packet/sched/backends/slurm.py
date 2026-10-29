"""The ``slurm`` backend: one ``sbatch`` job per step (docs/scheduler.md §5.1, §5.5).

Polite to the controller: one ``squeue`` for every live job per poll, and
``sacct`` only for jobs that have left the queue.
"""

import os
import shlex
import subprocess

from ... import schema
from . import DONE, LOST, PENDING, RUNNING, Backend, BackendError, JobState

TIMEOUT_S = 30                  # a command slower than this counts as the controller down
MARGIN_S = 300                  # run limit beyond the step timeout: the step ends itself first

QUEUED = {"PENDING": PENDING, "CONFIGURING": PENDING, "REQUEUED": PENDING,
          "REQUEUE_HOLD": PENDING, "RESV_DEL_HOLD": PENDING, "SUSPENDED": RUNNING,
          "RUNNING": RUNNING, "COMPLETING": RUNNING, "STAGE_OUT": RUNNING, "SIGNALING": RUNNING,
          "RESIZING": RUNNING}
# Ended by the farm, not the work: retried without counting the attempt (§5.5).
FARM = {"PREEMPTED": "preempted", "NODE_FAIL": "node failure", "BOOT_FAIL": "node boot failure",
        "DEADLINE": "deadline", "REVOKED": "revoked", "LAUNCH_FAILED": "launch failed"}


def hhmmss(s):
    s = int(s)
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)


def cpu_seconds(v):
    """sacct ``TotalCPU``: ``MM:SS.mmm``, ``HH:MM:SS`` or ``D-HH:MM:SS``."""
    if not v:
        return None
    days = 0
    if "-" in v:
        d, v = v.split("-", 1)
        days = int(d)
    try:
        parts = [float(x) for x in v.split(":")]
    except ValueError:
        return None
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, sec = parts
    return days * 86400 + h * 3600 + m * 60 + sec


def utc(v):
    """sacct's ``Start`` (the controller's local time, no zone) as ``...Z``, or None."""
    from datetime import datetime
    try:
        return schema.format_timestamp(datetime.strptime(v, "%Y-%m-%dT%H:%M:%S").astimezone())
    except (TypeError, ValueError):
        return None


def node_command(cfg, path, lost=None):
    """What a job runs: ``node_env`` and ``wpk step``."""
    cmd = "wpk step %s" % shlex.quote(path)
    if lost:
        cmd += " --lost %s" % shlex.quote(lost)
    env = (cfg.get("node_env") or "").strip()
    return "%s && exec %s" % (env, cmd) if env else "exec " + cmd


class Slurm(Backend):
    name = "slurm"
    poll_s = 15.0
    holds_room_while_pending = True

    def __init__(self, cfg, h=None):
        self.cfg = cfg
        self.h = h
        s = cfg.get("slurm") or {}
        self.bin = s.get("bin", "")
        self.common = {"partition": s.get("partition", ""), "account": s.get("account", ""),
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
        argv = ["--parsable", "-J", task.name, "-t", hhmmss(limit), "-c", str(z.cpus)]
        if z.mem_mb:
            argv += ["--mem", "%dM" % z.mem_mb]
        part = z.partition or self.common["partition"]
        if part:
            argv += ["-p", part]
        if self.common["account"]:
            argv += ["--account", self.common["account"]]
        if z.constraint:
            argv += ["--constraint", z.constraint]
        argv += self.common["extra"] + list(z.extra)
        argv += ["-o", task.log]
        cmd = " ".join(shlex.quote(a) for a in task.argv) if task.argv else \
            node_command(self.cfg, task.path, task.lost)
        return argv + ["--wrap", cmd]

    def submit(self, task):
        os.makedirs(os.path.dirname(task.log), exist_ok=True)
        p = self._run("sbatch", self.submit_argv(task))
        out = p.stdout.strip().splitlines()
        jid = out[-1].split(";")[0].strip() if out else ""
        if not jid.isdigit():
            raise BackendError("sbatch printed no job ID: %r" % p.stdout[:200])
        return jid

    def _queue(self):
        """{job id: (state, name)} of this user's jobs in the queue."""
        p = self._run("squeue", ["--me", "-h", "-o", "%i|%T|%j"])
        out = {}
        for line in p.stdout.splitlines():
            parts = line.strip().split("|", 2)
            if len(parts) == 3:
                out[parts[0]] = (parts[1], parts[2])
        return out

    def _acct(self, ids):
        p = self._run("sacct", ["-j", ",".join(ids), "-X", "-n", "-P", "-o",
                                "JobID,State,ExitCode,Start,End,TotalCPU"])
        out = {}
        for line in p.stdout.splitlines():
            f = line.strip().split("|")
            if len(f) >= 6 and f[0] in ids:
                out[f[0]] = f
        return out

    def poll(self, refs):
        refs = [r for r in refs if r]
        if not refs:
            return {}
        q = self._queue()
        out, gone = {}, []
        for r in refs:
            if r in q:
                state = q[r][0]
                out[r] = JobState(QUEUED.get(state, RUNNING))
            else:
                gone.append(r)
        if gone:
            acct = self._acct(gone)
            for r in gone:
                f = acct.get(r)
                out[r] = self._ended(f) if f else JobState(
                    LOST, reason="unknown to the batch system", counted=False)
        return out

    @staticmethod
    def _ended(f):
        _, state, exitcode, start, end, cpu = f[:6]
        word = state.split()[0] if state else ""
        try:
            code = int(exitcode.split(":")[0])
        except ValueError:
            code = None
        cpu_s = cpu_seconds(cpu)
        started, ended = utc(start), utc(end)
        if word in QUEUED:               # sacct can be ahead of squeue for a moment
            return JobState(QUEUED[word])
        if word in FARM:
            return JobState(LOST, reason=FARM[word], counted=False, started=started,
                            ended=ended, cpu_s=cpu_s)
        if word == "CANCELLED":
            return JobState(LOST, code=code, reason="cancelled (%s)" % state, counted=False,
                            started=started, ended=ended, cpu_s=cpu_s)
        # COMPLETED, FAILED, TIMEOUT (the step ran out of time: counted, as a step
        # timeout is), OUT_OF_MEMORY (the work's own doing): the executor decides.
        return JobState(DONE, code=code, started=started, ended=ended, cpu_s=cpu_s,
                        reason=word.lower() if word != "COMPLETED" else None)

    def cancel(self, ref, hard=False):
        if hard:
            self._run("scancel", [ref], ok_codes=(0, 1))
            return
        try:
            self._run("scancel", ["--signal=TERM", "--full", ref])
        except BackendError:             # still pending: withdraw it
            self._run("scancel", [ref], ok_codes=(0, 1))

    def list_ours(self):
        from ... import registry
        from ..dispatcher import home_id
        prefix = "wpk:%s:" % home_id(self.h or registry.home())
        return {jid: name for jid, (_, name) in self._queue().items() if name.startswith(prefix)}

    def running(self):
        return []

