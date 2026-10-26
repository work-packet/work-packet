#!/usr/bin/env python3
"""A fake batch system for tests (docs/scheduler-plan.md T-d).

Run as ``sbatch``, ``squeue``, ``sacct``, ``scancel`` (SLURM) or ``bsub``,
``bjobs``, ``bkill`` (LSF): the wrappers beside this file call ``main``
with the command's name. State is one JSON file per job in
``$WPK_FAKEBATCH_DIR/jobs/``. There is no daemon: every command first
"schedules", starting pending jobs whose wait is over and noting the end
of finished ones. A started job runs as its own process group with the
environment ``sbatch`` saw (SLURM's ``--export=ALL``).

Knobs, per job-name glob, in ``$WPK_FAKEBATCH_DIR/rules.json`` (a list,
first match wins): ``pend_s`` (wait before starting, default 0),
``preempt_after_s``, ``node_fail`` (true: fails as it starts),
``submit_fails`` (that many submits fail first), ``timeout_s`` (overrides
the time limit), ``exit`` (the job exits with this instead of running).
"""

import fnmatch
import json
import os
import shlex
import signal
import subprocess
import sys
import time

DIR = os.environ.get("WPK_FAKEBATCH_DIR") or os.path.join(os.getcwd(), ".fakebatch")
JOBS = os.path.join(DIR, "jobs")
USER = str(os.getuid())


def _ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) if t else "Unknown"


def rules():
    try:
        with open(os.path.join(DIR, "rules.json")) as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return []


def rule_for(name):
    for r in rules():
        if fnmatch.fnmatch(name, r.get("match", "*")):
            return r
    return {}


def load(jid):
    with open(os.path.join(JOBS, "%s.json" % jid)) as fp:
        return json.load(fp)


def save(j):
    os.makedirs(JOBS, exist_ok=True)
    tmp = os.path.join(JOBS, ".%s.tmp" % j["id"])
    with open(tmp, "w") as fp:
        json.dump(j, fp)
    os.replace(tmp, os.path.join(JOBS, "%s.json" % j["id"]))


def all_jobs():
    try:
        names = sorted(os.listdir(JOBS), key=lambda n: int(n.split(".")[0]) if n[0].isdigit() else 0)
    except OSError:
        return []
    out = []
    for n in names:
        if n.endswith(".json") and n[0].isdigit():
            try:
                out.append(load(n[:-5]))
            except (OSError, ValueError):
                pass
    return out


def next_id():
    os.makedirs(DIR, exist_ok=True)
    p = os.path.join(DIR, "next_id")
    fd = os.open(p + ".lock", os.O_CREAT | os.O_RDWR)
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        try:
            n = int(open(p).read())
        except (OSError, ValueError):
            n = 1000
        open(p, "w").write(str(n + 1))
        return n
    finally:
        os.close(fd)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        st = open("/proc/%d/stat" % pid).read()
        return st[st.rindex(")") + 2] != "Z"
    except OSError:
        return False


def _kill(j, sig):
    if j.get("pid"):
        try:
            os.killpg(j["pid"], sig)
        except (ProcessLookupError, PermissionError):
            pass


def _mins(v):
    """``1m2.500s`` -> 62.5."""
    m, _, sec = v.rstrip("s").partition("m")
    return int(m) * 60 + float(sec)


def _end(j, state, code=None, sig=0):
    j.update(state=state, end_t=time.time(), exit=code if code is not None else j.get("exit"),
             signal=sig)
    rc = os.path.join(JOBS, "%s.rc" % j["id"])
    try:                              # bash ``times``: the children's user and system time
        line = open(rc + ".cpu").read().splitlines()[1]
        j["cpu_s"] = round(sum(_mins(x) for x in line.split()), 3)
    except (OSError, ValueError, IndexError):
        pass
    save(j)


def schedule():
    now = time.time()
    for j in all_jobs():
        r = j.get("rule") or {}
        if j["state"] == "PENDING" and now - j["submit_t"] >= r.get("pend_s", 0):
            if r.get("node_fail"):
                j["start_t"] = now
                _end(j, "NODE_FAIL", 0)
                continue
            out = j.get("out") or os.devnull
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            rc = os.path.join(JOBS, "%s.rc" % j["id"])
            if "exit" in r:
                script = "exit %d" % r["exit"]
            else:
                script = j["cmd"]
            wrapped = ("trap 'kill -TERM $child 2>/dev/null; wait $child; echo 143 > %s; exit 143' TERM; "
                       "(%s) & child=$!; wait $child; rc=$?; "
                       "times > %s; echo $rc > %s"
                       % (shlex.quote(rc), script, shlex.quote(rc + ".cpu"), shlex.quote(rc)))
            with open(out, "ab") as fp:
                p = subprocess.Popen(["bash", "-c", wrapped], stdin=subprocess.DEVNULL, stdout=fp,
                                     stderr=subprocess.STDOUT, start_new_session=True,
                                     env=j.get("env") or None, cwd=j.get("cwd") or None)
            j.update(state="RUNNING", start_t=now, pid=p.pid)
            save(j)
        elif j["state"] in ("RUNNING", "COMPLETING"):
            limit = r.get("timeout_s", j.get("time_s"))
            rc = os.path.join(JOBS, "%s.rc" % j["id"])
            if os.path.exists(rc) or not alive(j["pid"]):
                try:
                    code = int(open(rc).read().strip())
                except (OSError, ValueError):
                    code = None
                if j.get("cancel"):
                    _end(j, "CANCELLED", code if code is not None else 0, 15)
                elif code is None:
                    _end(j, "FAILED", 1, 9)
                else:
                    _end(j, "COMPLETED" if code == 0 else "FAILED", code)
                continue
            if r.get("preempt_after_s") is not None and now - j["start_t"] >= r["preempt_after_s"]:
                _kill(j, signal.SIGKILL)
                _end(j, "PREEMPTED", 0, 9)
            elif limit and now - j["start_t"] >= limit:
                _kill(j, signal.SIGKILL)
                _end(j, "TIMEOUT", 0, 9)


def _secs(v):
    """``-t``: minutes, MM:SS, HH:MM:SS or D-HH:MM:SS."""
    days = 0
    if "-" in v:
        d, v = v.split("-", 1)
        days = int(d)
    parts = [int(x) for x in v.split(":")]
    if len(parts) == 1:
        return days * 86400 + parts[0] * 60
    if len(parts) == 2:
        return days * 86400 + parts[0] * 60 + parts[1]
    return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def _fails(name):
    """Count down a rule's ``submit_fails``; True while it has some left."""
    r = rule_for(name)
    n = r.get("submit_fails", 0)
    if not n:
        return False
    import hashlib
    p = os.path.join(DIR, "fails-%s" % hashlib.sha1(r.get("match", "*").encode()).hexdigest()[:10])
    used = int(open(p).read()) if os.path.exists(p) else 0
    if used >= n:
        return False
    open(p, "w").write(str(used + 1))
    return True


def _log(argv):
    with open(os.path.join(DIR, "calls.log"), "a") as fp:
        fp.write(json.dumps(argv) + "\n")


# --- SLURM -------------------------------------------------------------------------

def sbatch(args):
    opts = {"-J": "", "-t": "", "-c": "1", "--mem": "", "-p": "", "--account": "", "-o": "",
            "--wrap": ""}
    i = 0
    extra = []
    while i < len(args):
        a = args[i]
        if a in opts and i + 1 < len(args):
            opts[a] = args[i + 1]
            i += 2
            continue
        if "=" in a and a.split("=", 1)[0] in ("--job-name", "--time", "--mem", "--partition",
                                               "--account", "--output", "--wrap",
                                               "--cpus-per-task"):
            k, v = a.split("=", 1)
            opts[{"--job-name": "-J", "--time": "-t", "--partition": "-p", "--output": "-o",
                  "--cpus-per-task": "-c"}.get(k, k)] = v
        else:
            extra.append(a)
        i += 1
    if not opts["--wrap"]:
        sys.stderr.write("sbatch: error: this fake needs --wrap\n")
        return 1
    if _fails(opts["-J"]):
        sys.stderr.write("sbatch: error: Batch job submission failed: Socket timed out\n")
        return 1
    jid = next_id()
    j = {"id": jid, "name": opts["-J"], "cmd": opts["--wrap"], "state": "PENDING",
         "submit_t": time.time(), "cpus": int(opts["-c"]), "mem": opts["--mem"],
         "partition": opts["-p"], "account": opts["--account"], "out": opts["-o"],
         "time_s": _secs(opts["-t"]) if opts["-t"] else None, "extra": extra,
         "env": dict(os.environ), "cwd": os.getcwd(), "user": USER,
         "rule": rule_for(opts["-J"])}
    save(j)
    print(jid if "--parsable" in extra else "Submitted batch job %d" % jid)
    return 0


SQ_STATE = {"PENDING": "PENDING", "RUNNING": "RUNNING"}


def _fmt(j, code):
    st = j["state"]
    return {"i": str(j["id"]), "j": j["name"], "T": st, "t": {"PENDING": "PD", "RUNNING": "R"}
            .get(st, st[:2]), "S": _ts(j.get("start_t")), "V": _ts(j["submit_t"]),
            "r": "None" if st == "RUNNING" else "Priority", "C": str(j["cpus"]),
            "u": j["user"]}.get(code, "")


def squeue(args):
    fmt, ids, me, header = "%i %j %T", None, False, True
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "--format"):
            fmt = args[i + 1]
            i += 1
        elif a.startswith("--format="):
            fmt = a.split("=", 1)[1]
        elif a in ("-j", "--jobs"):
            ids = set(args[i + 1].split(","))
            i += 1
        elif a == "--me":
            me = True
        elif a in ("-h", "--noheader"):
            header = False
        i += 1
    import re
    rows = [j for j in all_jobs() if j["state"] in SQ_STATE]
    if ids is not None:
        known = {str(j["id"]) for j in all_jobs()}
        if not ids & known:
            sys.stderr.write("slurm_load_jobs error: Invalid job id specified\n")
            return 1
        rows = [j for j in rows if str(j["id"]) in ids]
    if me:
        rows = [j for j in rows if j["user"] == USER]
    if header:
        print(re.sub(r"%(\w)", lambda m: m.group(1).upper(), fmt))
    for j in rows:
        print(re.sub(r"%\.?\d*(\w)", lambda m: _fmt(j, m.group(1)), fmt))
    return 0


def _cpu(s):
    if s is None:
        return "00:00:00"
    m, sec = divmod(float(s), 60)
    h, m = divmod(int(m), 60)
    return "%02d:%02d:%06.3f" % (h, m, sec) if h else "%02d:%06.3f" % (m, sec)


def sacct(args):
    fields, ids, parsable, header = ["JobID", "JobName", "State", "ExitCode"], None, False, True
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "--format"):
            fields = args[i + 1].split(",")
            i += 1
        elif a.startswith("--format="):
            fields = a.split("=", 1)[1].split(",")
        elif a in ("-j", "--jobs"):
            ids = set(args[i + 1].split(","))
            i += 1
        elif a in ("-P", "--parsable2"):
            parsable = True
        elif a in ("-n", "--noheader"):
            header = False
        i += 1
    rows = [j for j in all_jobs() if ids is None or str(j["id"]) in ids]
    sep = "|" if parsable else " "
    if header:
        print(sep.join(fields))
    for j in rows:
        st = j["state"]
        if st == "CANCELLED":
            st = "CANCELLED by %s" % (j.get("cancel_by") or USER)
        vals = {"JobID": str(j["id"]), "JobName": j["name"], "State": st,
                "ExitCode": "%d:%d" % (j.get("exit") or 0, j.get("signal") or 0),
                "Start": _ts(j.get("start_t")), "End": _ts(j.get("end_t")),
                "TotalCPU": _cpu(j.get("cpu_s")), "AllocCPUS": str(j["cpus"]),
                "Elapsed": _cpu((j.get("end_t") or time.time()) - (j.get("start_t") or time.time()))}
        print(sep.join(vals.get(f, "") for f in fields))
    return 0


def scancel(args):
    sig = None
    ids = []
    for a in args:
        if a.startswith("--signal="):
            sig = a.split("=", 1)[1]
        elif a.startswith("-"):
            continue
        else:
            ids.append(a)
    code = 0
    for jid in ids:
        try:
            j = load(jid)
        except (OSError, ValueError):
            sys.stderr.write("scancel: error: Invalid job id %s\n" % jid)
            code = 1
            continue
        if j["state"] == "PENDING":
            if sig:
                sys.stderr.write("scancel: error: Kill job error on job id %s: "
                                 "Job is pending execution\n" % jid)
                code = 1
                continue
            j["start_t"] = None
            _end(j, "CANCELLED", 0)
            continue
        if j["state"] != "RUNNING":
            continue
        j["cancel"] = True
        save(j)
        _kill(j, getattr(signal, "SIG" + sig) if sig else signal.SIGKILL)
    return code


COMMANDS = {"sbatch": sbatch, "squeue": squeue, "sacct": sacct, "scancel": scancel}


def main(name, args):
    os.makedirs(JOBS, exist_ok=True)
    _log([name] + args)
    schedule()
    if name in COMMANDS:
        return COMMANDS[name](args)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import lsf
    return lsf.COMMANDS[name](args)


if __name__ == "__main__":
    sys.exit(main(os.path.basename(sys.argv[1]), sys.argv[2:]))
