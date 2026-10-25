"""procs.of_step: a step's processes from /proc."""

import os
import subprocess
import sys
import time

import pytest

from work_packet import procs

pytestmark = pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="needs /proc")

WPID = "11111111-2222-4333-8444-555555555555"


def _wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = pred()
        if got:
            return got
        time.sleep(0.05)
    return pred()


def test_session_tree_and_tagged_escapee():
    env = dict(os.environ, WPK_WPID=WPID, WPK_STEP="3")
    # The "model": a shell in its own session with a child. The escapee
    # leaves the session but keeps the step's environment.
    root = subprocess.Popen(["sh", "-c", "sleep 30 & wait"], env=env, start_new_session=True)
    escapee = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               env=env, start_new_session=True)
    other = subprocess.Popen(["sleep", "30"], env=dict(env, WPK_STEP="4"),
                             start_new_session=True)
    try:
        got = _wait_for(lambda: (lambda r: r if r["count"] >= 3 else None)(
            procs.of_step(root.pid, WPID, 3)))
        pids = [p["pid"] for p in got["procs"]]
        assert pids[0] == root.pid and got["procs"][0]["depth"] == 0
        kid = got["procs"][1]
        assert kid["ppid"] == root.pid and kid["depth"] == 1 and kid["cmd"] == "sleep 30"
        assert escapee.pid in pids and other.pid not in pids
        assert all(p["rss"] >= 0 and p["age_s"] is not None for p in got["procs"])
        assert got["rss"] == sum(p["rss"] for p in got["procs"])
        # Without the tags only the session is found.
        assert escapee.pid not in [p["pid"] for p in procs.of_step(root.pid)["procs"]]
    finally:
        for p in (root, escapee, other):
            os.killpg(p.pid, 9)
            p.wait()


def test_gone_root_finds_nothing():
    p = subprocess.Popen(["true"], start_new_session=True)
    p.wait()
    assert procs.of_step(p.pid)["count"] == 0


def test_model_run_writes_pid_while_running(tmp_path):
    from work_packet import model
    pid_path = str(tmp_path / "model.pid")
    out = tmp_path / "t.jsonl"
    # The child prints the file's content and its own PID; they must match.
    script = 'for i in $(seq 50); do [ -s "$1" ] && break; sleep 0.05; done; cat "$1"; echo $$'
    model.run(["sh", "-c", script, "sh", pid_path], "", str(tmp_path), dict(os.environ), 10,
              str(out), str(tmp_path / "err.log"), lambda path, res: res, pid_path=pid_path)
    lines = out.read_text().split()
    assert len(lines) == 2 and lines[0] == lines[1]
    assert not os.path.exists(pid_path)


def test_tags_alone_without_root():
    env = dict(os.environ, WPK_WPID=WPID, WPK_STEP="5")
    root = subprocess.Popen(["sh", "-c", "sleep 30 & wait"], env=env, start_new_session=True)
    try:
        got = _wait_for(lambda: (lambda r: r if r["count"] >= 2 else None)(
            procs.of_step(None, WPID, 5)))
        assert [p["depth"] for p in got["procs"]] == [0, 1]
        assert got["procs"][0]["pid"] == root.pid
    finally:
        os.killpg(root.pid, 9)
        root.wait()


def test_bash_tool_wrapper_unwrapped():
    wrapped = ("source /h/.claude/shell-snapshots/snapshot-bash-1.sh 2>/dev/null || true && "
               "eval 'make -j8 > b.log 2>&1; echo '\\''ok'\\''' < /dev/null && pwd -P >| /tmp/c-cwd")
    assert procs._unwrap(["/bin/bash", "-c", wrapped]) == "$ make -j8 > b.log 2>&1; echo 'ok'"
    assert procs._unwrap(["/bin/bash", "-c", "make"]) is None
