"""E2: SIGKILL anywhere, then step again, gives the same tree as a clean run."""

import json
import os
import random
import re
import signal
import subprocess
import sys
import time

import pytest

from conftest import make_project
from work_packet import executor, faults
from work_packet.check import check
from work_packet.packet import Packet

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def wpk(*args, env=None):
    return subprocess.run([sys.executable, "-m", "work_packet"] + list(args),
                          env=env, capture_output=True, text=True)


def run_all(proj):
    """Step every packet until nothing is runnable."""
    for _ in range(40):
        ran = False
        for w in sorted(os.listdir(os.path.join(proj, "packets"))):
            if executor.step(os.path.join(proj, "packets", w)).code == 0:
                ran = True
        if not ran:
            return
    raise AssertionError("did not settle")


def normalised(proj):
    """The project tree minus what legitimately differs after a crash and retry."""
    out = {}
    for d, dirs, files in os.walk(proj):
        dirs[:] = [x for x in dirs if ".failed-" not in x]
        for n in files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, proj)
            data = open(p, "rb").read().decode().replace(proj, "<proj>")
            if n == "meta.json":
                continue
            if n == "journal.jsonl":
                recs = [json.loads(x) for x in data.splitlines()]
                recs = [{k: v for k, v in r.items() if k not in ("t", "duration_s")}
                        for r in recs if r["type"] in ("commit-begin", "commit-end")]
                data = repr(recs)
            if n in ("prompt.md", "transcript.jsonl"):
                data = re.sub(r"attempt \d+ of \d+", "attempt N of M", data)
                data = re.sub(r"## Last attempt\n.*?(?=## Last step's summary)", "", data,
                              flags=re.S)
                data = UUID.sub("<uuid>", data)
            out[rel] = data
    return out


@pytest.fixture
def clean_tree(tmp_path_factory, fake):
    proj, _ = make_project(tmp_path_factory.mktemp("clean"))
    run_all(proj)
    return normalised(proj)


@pytest.mark.parametrize("point", faults.POINTS)
def test_kill_at_fault_point(tmp_path, fake, clean_tree, point):
    proj, root = make_project(tmp_path)
    for _ in range(7):
        assert executor.step(proj).code == 0
    env = dict(os.environ, WPK_FAULT_AT=point + "@8")
    r = wpk("step", proj, env=env)
    assert r.returncode == -signal.SIGKILL, r.stderr
    assert check(proj).errors == [], [str(i) for i in check(proj).errors]
    run_all(proj)
    rep = check(proj)
    assert rep.issues == [], [str(i) for i in rep.issues]
    assert normalised(proj) == clean_tree


def test_external_sigkill(tmp_path, fake, clean_tree):
    """Kill `wpk step` from outside at random moments; the run still ends the same."""
    proj, root = make_project(tmp_path)
    # Each kill can cost an attempt. Whether three land on one step depends on
    # timing, and FAILED after max_attempts is tested elsewhere; this test is
    # about the end state, so give the random kills room.
    os.makedirs(os.environ["WPK_HOME"], exist_ok=True)
    with open(os.path.join(os.environ["WPK_HOME"], "config.toml"), "w") as fp:
        fp.write("max_attempts = 30\n")
    rng = random.Random(1234)
    kills = 0
    for _ in range(30):
        pkt = Packet(root.path)
        if pkt.load_status()[0]["state"] != "RUNNABLE":
            break
        p = subprocess.Popen([sys.executable, "-m", "work_packet", "step", proj],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(rng.uniform(0.0, 0.4))
        if p.poll() is None:
            p.send_signal(signal.SIGKILL)
            kills += 1
        p.wait()
        assert check(proj).errors == []
    assert kills > 0
    run_all(proj)
    assert check(proj).issues == []
    assert normalised(proj) == clean_tree
