"""Streamed commands and the reading of git's and IVPM's plain text
(dash-create-progress-design.md). The IVPM transcripts in data/ivpm-transcript
are real output of `ivpm clone` / `ivpm update` (2.40.2 and 2.42.0) piped,
with the scratch path written as /W."""

import os
import re
import sys

import pytest

from work_packet import progress
from work_packet.progress import IvpmTranscript, git_progress, run_streamed

DATA = os.path.join(os.path.dirname(__file__), "data", "ivpm-transcript")


def fold(name, root=None):
    t = IvpmTranscript(root)
    events = []
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        text = f.read()
    for m in re.finditer(r"([^\r\n]*)(\r|\n)", text):
        events += t.feed(m.group(1), m.group(2) == "\n")
    return t, events


# --- run_streamed ---------------------------------------------------------------

def test_run_streamed_lines_and_cr_updates():
    seen = []
    script = r"""import sys,time
sys.stdout.write("one\n"); sys.stdout.flush()
sys.stderr.write("50%\r"); sys.stderr.flush(); time.sleep(0.05)
sys.stderr.write("100%\r\n"); sys.stderr.write("\x1b[1mbold\x1b[0m\n")
sys.stdout.write("no end"); sys.exit(3)"""
    rc, tail = run_streamed([sys.executable, "-c", script],
                            lambda text, final: seen.append((text, final)))
    assert rc == 3
    assert seen == [("one", True), ("50%", False), ("100%", True), ("bold", True),
                    ("no end", True)]
    assert tail == "one\n100%\nbold\nno end"


def test_run_streamed_keeps_a_tail_and_runs_shell_strings(tmp_path):
    rc, tail = run_streamed("for i in 1 2 3 4 5; do echo $i; done; pwd", cwd=str(tmp_path),
                            tail=3)
    assert rc == 0
    assert tail == "4\n5\n%s" % tmp_path


def test_run_streamed_kills_the_command_when_the_reader_fails():
    def boom(text, final):
        raise RuntimeError("stop")
    with pytest.raises(RuntimeError):
        run_streamed([sys.executable, "-u", "-c", "print('x'); import time; time.sleep(30)"],
                     boom)


# --- git --------------------------------------------------------------------------

def test_git_progress():
    assert git_progress("Receiving objects:  63% (630/1000), 1.2 MiB | 3 MiB/s") == \
        {"phase": "Receiving objects", "pct": 63, "cur": 630, "total": 1000}
    assert git_progress("remote: Counting objects: 100% (3/3), done.")["phase"] == \
        "Counting objects"
    # parallel clones tear lines: the last report wins
    assert git_progress("Receiving objects:  33% (1/3)Resolving deltas:  5% (1/20)")["pct"] == 5
    assert git_progress("Cloning into 'x'...") is None


# --- IVPM's transcript ---------------------------------------------------------------

@pytest.mark.parametrize("ver", ["2.40", "2.42"])
def test_clone_ok(ver):
    t, ev = fold("ivpm-%s-clone-ok.txt" % ver, "/W/c1")
    assert {n: p["state"] for n, p in t.packages.items()} == \
        {"[clone]": "ok", "depa": "ok", "depb": "ok", "six": "ok"}
    assert t.packages["depa"]["type"] == "git" and t.packages["six"]["type"] == "pypi"
    assert t.counts() == {"started": 3, "done": 3, "failed": 0}   # the root is not a dep
    assert {n: x["state"] for n, x in t.tasks.items()} == \
        {"Creating Python virtual environment": "ok", "Installing Python packages": "ok"}
    assert t.summary == {"Total packages": "3", "Cacheable": "0", "Editable": "2"}
    assert [e["name"] for e in ev if e["k"] == "phase"] == ["fetching", "installing",
                                                             "finishing"]
    assert t.diagnostics == []
    # the root clone's progress is the root's: it runs alone
    git = [e for e in ev if e["k"] == "git"]
    assert git[0]["pkg"] == "[clone]" and git[0]["phase"] == "Counting objects"


def test_update_v_has_task_steps():
    t, ev = fold("ivpm-2.40-update-v.txt")
    assert "[clone]" not in t.packages
    steps = [(e["at"], e["total"]) for e in ev
             if e["k"] == "task" and e["name"] == "Installing Python packages" and e["at"]]
    assert steps[0] == (2, 2)
    assert t.tasks["Installing Python packages"]["state"] == "ok"


def test_update_plain_parallel_git_is_not_misattributed():
    t, ev = fold("ivpm-2.40-update-plain.txt")
    assert t.counts() == {"started": 3, "done": 3, "failed": 0}
    for e in ev:
        if e["k"] == "git" and e["pkg"] is not None:
            assert e["pkg"] in ("depa", "depb")


@pytest.mark.parametrize("name", ["ivpm-2.40-clone-fail.txt", "ivpm-2.42-clone-fail.txt",
                                  "ivpm-2.40-update-fail-v.txt"])
def test_failed_dependency(name):
    t, ev = fold(name, "/W/c3")
    p = t.packages["nosuch"]
    assert p["state"] == "fail"
    assert p["error"].startswith("Failed to clone file:///W/nosuch")
    assert p["loc"].endswith("ivpm.yaml:6:7")
    assert t.counts()["failed"] == 1
    err = [d for d in t.diagnostics if d["severity"] == "error"]
    assert err and err[-1]["loc"].endswith("ivpm.yaml:6:7")


def test_failed_root_clone():
    t, ev = fold("ivpm-2.40-clone-nosrc.txt", "/W/c4")
    assert t.packages["[clone]"]["state"] == "fail"
    assert "Git clone failed" in t.packages["[clone]"]["error"]
    assert t.counts()["started"] == 0


def test_bare_repo():
    t, ev = fold("ivpm-2.40-clone-bare.txt", "/W/c2")
    assert t.packages == {"[clone]": dict(t.packages["[clone]"], state="ok")}
    assert t.tasks == {} and t.summary == {}


def test_unknown_lines_make_no_events():
    t = IvpmTranscript()
    assert t.feed("Resolved 17 packages in 191ms") == []
    assert t.feed(" + six==1.17.0") == []


def test_other_transcript_forms():
    t = IvpmTranscript()
    assert t.feed(">> [venv] - Creating Python virtual environment")[-1]["state"] == "run"
    assert t.feed("<< [venv] (2.5s)")[-1] == dict(t.tasks["venv"], k="task", name="venv")
    assert t.tasks["venv"]["secs"] == 2.5
    t.feed(">> pyvsc (git)")
    assert t.feed("   https://github.com/x/pyvsc.git") == \
        [{"k": "detail", "pkg": "pyvsc", "text": "https://github.com/x/pyvsc.git"}]
    assert t.feed("   → git@github.com:x/pyvsc.git")[0]["text"].startswith("→ git@")
    assert t.feed(">> [build] (pyvsc)")[0]["pkg"] == "pyvsc"
    ev = t.feed("<< [build] [pyvsc] ERROR: no compiler")
    assert ev[0]["state"] == "fail" and ev[0]["msg"] == "no compiler"
    t.feed("  >> [sub]")
    assert t.tasks["sub"]["sub"] is True
    assert t.feed("warning: something odd")[0]["severity"] == "warning"
    t.feed("Errors encountered:")
    assert t.feed("  pyvsc(ivpm.yaml:3): broke")[0]["k"] == "detail"
    assert t.feed("note: done")[0]["k"] == "diag"
    assert progress.ROOT not in t.packages


def test_build_heartbeat_lines():
    """ivpm (after 2.42) names the build step and says "still running" during a
    long compile: both become the running task's message."""
    t = IvpmTranscript()
    t.feed(">> [Installing Python packages]")
    ev = t.feed("   Building pssparser: building Lexer.cpp (26/152)")
    assert (ev[0]["at"], ev[0]["total"], ev[0]["msg"]) == (26, 152, "Building pssparser: building Lexer.cpp")
    ev = t.feed("   Building pssparser: compiling ast.cpp (still running, 1m 16s)")
    assert ev[0]["k"] == "task" and ev[0]["msg"].endswith("(still running, 1m 16s)")
    assert t.feed("<< [Installing Python packages] (137.2s)")[0]["state"] == "ok"


def test_run_streamed_gives_the_command_no_terminal_input():
    # wpkd run as a background job: a clone's ssh touching the terminal stopped
    # wpkd's whole process group, the board with it. The command reads nothing.
    rc, said = progress.run_streamed([sys.executable, "-c",
                                      "import sys; print(repr(sys.stdin.read()))"])
    assert rc == 0 and said == "''"


def test_run_streamed_leaves_out_another_projects_ivpm_settings(monkeypatch):
    monkeypatch.setenv("IVPM_PROJECT", "/elsewhere")
    monkeypatch.setenv("IVPM_PACKAGES", "/elsewhere/packages")
    monkeypatch.setenv("IVPM_CACHE", "/cache")
    rc, said = run_streamed([sys.executable, "-c", "import os; print(sorted(k for k in "
                             "os.environ if k.startswith('IVPM_')))"])
    assert rc == 0 and said == "['IVPM_CACHE']"


def test_a_cancel_kills_the_command_and_its_children():
    import threading
    import time
    c = progress.Canceller()
    out = {}

    def run():
        with c.on():
            try:
                run_streamed(["sh", "-c", "sleep 300 & echo $!; wait"],
                             lambda t, f: out.setdefault("kid", int(t)))
            except progress.Cancelled as e:
                out["e"] = e
    t = threading.Thread(target=run)
    t.start()
    deadline = time.time() + 10
    while "kid" not in out and time.time() < deadline:
        time.sleep(0.02)
    c.cancel()
    t.join(10)
    assert not t.is_alive() and isinstance(out.get("e"), progress.Cancelled)
    deadline = time.time() + 5
    while os.path.exists("/proc/%d" % out["kid"]) and time.time() < deadline:
        time.sleep(0.02)
    assert not os.path.exists("/proc/%d" % out["kid"])
    with c.on(), pytest.raises(progress.Cancelled):     # and nothing more starts
        run_streamed(["true"])
