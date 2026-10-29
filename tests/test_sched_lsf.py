"""The lsf backend's command line and bjobs parsing (plan Q6.2). The behaviour
it shares with slurm is in test_sched_batch.py, run for both."""

import sys

from work_packet.sched import config as sconfig
from work_packet.sched.backends import DONE, LOST, PENDING, RUNNING, Task
from work_packet.sched.backends.lsf import Lsf, cpu_seconds, resource_string, utc


def cfg(**lsf):
    return sconfig.load(raw={"sched": {
        "backend": "lsf", "node_env": "module load wpk",
        "lsf": dict({"queue": "normal", "project": "dv-agents", "extra": ["-G", "dv"]}, **lsf),
        "sizes": {"sim": {"cpus": 8, "mem": "32G", "time": "4h", "queue": "big"}}}})


def test_bsub_argv_per_size():
    c = cfg()
    b = Lsf(c)
    t = Task("j", "step", "p", "w", "/proj/packets/w", sconfig.size(c, "look"), "/h/j.log",
             step=2, name="wpk:abcd:w:2")
    assert b.submit_argv(t) == [
        "-J", "wpk:abcd:w:2", "-W", "2:05", "-n", "1", "-R", "rusage[mem=4096] span[hosts=1]",
        "-q", "normal", "-P", "dv-agents", "-G", "dv", "-o", "/h/j.log",
        "bash", "-c", "module load wpk && exec wpk step /proj/packets/w"]
    t.size, t.lost = sconfig.size(c, "sim"), "preempted"
    a = b.submit_argv(t)
    assert a[a.index("-W") + 1] == "4:00" and a[a.index("-n") + 1] == "8"
    assert a[a.index("-R") + 1] == "rusage[mem=32768] span[hosts=1]"
    assert a[a.index("-q") + 1] == "big" and a[-1].endswith("--lost preempted")


def test_size_resources_merged_into_one_R():
    def r(res, mem=None):
        t = {"cpus": 1, "resources": res}
        if mem:
            t["mem"] = mem
        return resource_string(sconfig._size("x", t))
    assert r("") == "span[hosts=1]"
    assert r("type==X86_64", "4G") == "select[type==X86_64] rusage[mem=4096] span[hosts=1]"
    assert r("select[osrel==8] type==X86_64") == \
        "select[(osrel==8) && (type==X86_64)] span[hosts=1]"
    assert r("rusage[lic=1:duration=5] span[ptile=4]", "1G") == \
        "rusage[mem=1024, lic=1:duration=5] span[ptile=4]"
    assert r("same[model] select[defined(x)]") == \
        "select[defined(x)] same[model] span[hosts=1]"
    c = sconfig.load(raw={"sched": {"backend": "lsf", "sizes": {
        "big": {"cpus": 4, "mem": "8G", "resources": "select[type==X86_64 && osrel==8]"}}}})
    t = Task("j", "step", "p", "w", "/w", sconfig.size(c, "big"), "/h/j.log", step=1, name="n")
    a = Lsf(c).submit_argv(t)
    assert a.count("-R") == 1
    assert a[a.index("-R") + 1] == \
        "select[type==X86_64 && osrel==8] rusage[mem=8192] span[hosts=1]"


def test_size_resources_schema():
    from work_packet import schema
    ok = schema.validate_config({"sched": {"sizes": {"a": {
        "cpus": 1, "resources": "select[a==1]", "constraint": "avx512"}}}})
    assert ok == []
    bad = schema.validate_config({"sched": {"sizes": {"a": {
        "cpus": 1, "resources": "select[a==1", "constraint": 3}}}})
    msgs = " ".join(str(e) for e in bad)
    assert "resources" in msgs and "unclosed" in msgs and "constraint" in msgs
    bad = schema.validate_config({"sched": {"sizes": {"a": {"cpus": 1, "resources": "foo[x]"}}}})
    assert "cannot read" in " ".join(str(e) for e in bad)


def test_bjobs_states():
    assert Lsf._state({"STAT": "PEND"}).state == PENDING
    assert Lsf._state({"STAT": "RUN"}).state == RUNNING
    assert Lsf._state({"STAT": "SSUSP"}).state == RUNNING
    d = Lsf._state({"STAT": "DONE", "START_TIME": "Oct 26 10:00:00 2026",
                    "FINISH_TIME": "Oct 26 10:05:00 2026", "CPU_USED": "12.5 second(s)"})
    assert (d.state, d.code, d.cpu_s) == (DONE, 0, 12.5) and d.started.endswith("Z")
    e = Lsf._state({"STAT": "EXIT", "EXIT_CODE": "1", "EXIT_REASON": ""})
    assert (e.state, e.code, e.counted) == (DONE, 1, True)
    t = Lsf._state({"STAT": "EXIT", "EXIT_CODE": "140",
                    "EXIT_REASON": "TERM_RUNLIMIT: job killed after reaching LSF run time limit"})
    assert (t.state, t.counted, t.reason) == (DONE, True, "timeout")
    for why, says in (("TERM_PREEMPT: job killed after preemption", "preempted"),
                      ("TERM_ADMIN: job killed by root or LSF administrator", "killed by an admin"),
                      ("TERM_OWNER: job killed by owner", "killed by its owner")):
        s = Lsf._state({"STAT": "EXIT", "EXIT_CODE": "130", "EXIT_REASON": why})
        assert (s.state, s.counted, s.reason) == (LOST, False, says)
    for stat in ("UNKWN", "ZOMBI"):
        s = Lsf._state({"STAT": stat})
        assert s.state == LOST and not s.counted


def test_lsf_formats():
    assert cpu_seconds("00:01:02") == 62
    assert cpu_seconds("1.5 second(s)") == 1.5
    assert utc("Oct 26 10:00") is not None and utc("Oct 26 10:00:05 2026").endswith("Z")
    assert utc("-") is None
    assert utc("Oct 26 10:00 L") == utc("Oct 26 10:00")       # an estimate's marker


def test_bjobs_missing_job_is_lost(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("WPK_FAKEBATCH_DIR", str(tmp_path))
    b = Lsf(cfg(bin=os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebatch")))
    st = b.poll(["4242"])["4242"]
    assert st.state == LOST and st.reason == "unknown to the batch system"
    assert sys.executable
