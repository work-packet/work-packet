"""bsub, bjobs and bkill on fakebatch's engine (docs/scheduler-plan.md Q6.3).

The engine keeps SLURM's state names; ``bjobs`` shows them as LSF does:
PEND, RUN, DONE, EXIT with an ``exit_reason`` (TERM_RUNLIMIT, TERM_PREEMPT,
TERM_OWNER), or UNKWN for a node failure.
"""

import fnmatch
import json
import shlex
import signal
import sys
import time

import fakebatch as fb

VIEW = {"PENDING": ("PEND", ""), "RUNNING": ("RUN", ""), "COMPLETED": ("DONE", ""),
        "FAILED": ("EXIT", ""), "TIMEOUT": ("EXIT", "TERM_RUNLIMIT: job killed after reaching "
                                                     "LSF run time limit"),
        "PREEMPTED": ("EXIT", "TERM_PREEMPT: job killed after preemption"),
        "CANCELLED": ("EXIT", "TERM_OWNER: job killed by owner"), "NODE_FAIL": ("UNKWN", "")}


def _t(t):
    return time.strftime("%b %d %H:%M:%S %Y", time.localtime(t)) if t else "-"


def bsub(args):
    opts = {"-J": "", "-W": "", "-n": "1", "-R": "", "-q": "", "-P": "", "-o": ""}
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] in opts:
        opts[args[i]] = args[i + 1]
        i += 2
    extra = []
    while i < len(args) and args[i].startswith("-"):
        extra.append(args[i])
        i += 1
    cmd = args[i:]
    if not cmd:
        sys.stderr.write("bsub: no command\n")
        return 255
    if fb._fails(opts["-J"]):
        sys.stderr.write("LSF is down. Please wait ...\nRequest from non-LSF host rejected\n")
        return 255
    jid = fb.next_id()
    limit = None
    if opts["-W"]:
        h, _, m = opts["-W"].rpartition(":")
        limit = (int(h) * 60 if h else 0) * 60 + int(m) * 60
    j = {"id": jid, "name": opts["-J"], "cmd": " ".join(shlex.quote(a) for a in cmd),
         "state": "PENDING", "submit_t": time.time(), "cpus": int(opts["-n"]),
         "mem": opts["-R"], "partition": opts["-q"], "account": opts["-P"], "out": opts["-o"],
         "time_s": limit, "extra": extra, "env": dict(__import__("os").environ),
         "cwd": __import__("os").getcwd(), "user": fb.USER, "rule": fb.rule_for(opts["-J"])}
    fb.save(j)
    print("Job <%d> is submitted to queue <%s>." % (jid, opts["-q"] or "normal"))
    return 0


def _cpu(s):
    return "%.1f second(s)" % float(s) if s is not None else "0 second(s)"


def bjobs(args):
    ids, pattern, i = [], None, 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "-J"):
            if a == "-J":
                pattern = args[i + 1]
            i += 2
            continue
        if not a.startswith("-"):
            ids.append(a)
        i += 1
    recs = []
    jobs = {str(j["id"]): j for j in fb.all_jobs()}
    names = ids if ids else list(jobs)
    for jid in names:
        j = jobs.get(jid)
        if j is None:
            recs.append({"JOBID": jid, "ERROR": "Job <%s> is not found" % jid})
            continue
        if pattern and not fnmatch.fnmatch(j["name"], pattern):
            continue
        stat, why = VIEW.get(j["state"], ("UNKWN", ""))
        recs.append({"JOBID": jid, "JOB_NAME": j["name"], "STAT": stat,
                     "EXIT_CODE": str(j.get("exit") or "") if stat == "EXIT" else "",
                     "EXIT_REASON": why, "START_TIME": _t(j.get("start_t")),
                     "FINISH_TIME": _t(j.get("end_t")), "CPU_USED": _cpu(j.get("cpu_s"))})
    print(json.dumps({"COMMAND": "bjobs", "JOBS": len(recs), "RECORDS": recs}))
    return 0


def bkill(args):
    sig, ids = None, []
    i = 0
    while i < len(args):
        if args[i] == "-s":
            sig = args[i + 1]
            i += 2
            continue
        ids.append(args[i])
        i += 1
    code = 0
    for jid in ids:
        try:
            j = fb.load(jid)
        except (OSError, ValueError):
            sys.stderr.write("Job <%s>: No matching job found\n" % jid)
            code = 255
            continue
        if j["state"] == "PENDING":        # a signal to a pending job kills it
            fb._end(j, "CANCELLED", 0)
            print("Job <%s> is being terminated" % jid)
            continue
        if j["state"] != "RUNNING":
            sys.stderr.write("Job <%s>: Job has already finished\n" % jid)
            continue
        j["cancel"] = True
        fb.save(j)
        fb._kill(j, getattr(signal, "SIG" + sig) if sig else signal.SIGKILL)
        print("Job <%s> is being %s" % (jid, "signaled" if sig else "terminated"))
    return code


COMMANDS = {"bsub": bsub, "bjobs": bjobs, "bkill": bkill}
