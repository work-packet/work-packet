"""Which sessions belong to a launch, and the session store
(docs/vscode-monitor-plan.md S3, §4.3)."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from work_packet import ide_launch
from work_packet import ide_sessions as s

if not os.path.isdir("/proc/self/fd"):
    pytest.skip("needs Linux /proc", allow_module_level=True)

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, "fake_harness.py")
DATA = os.path.join(HERE, "data", "ide_sessions")
KEY = "0123456789ab"
T0 = s.epoch("2026-11-04T09:00:00Z")
SID = ["7f3c1a2e-0b5d-4c6e-9f10-00000000000%d" % i for i in range(10)]
CID = "019a4f2e-1c2d-7e3f-8a9b-0c1d2e3f4a5b"


def _fixture(name, **sub):
    out = []
    for ln in open(os.path.join(DATA, name)):
        d = json.loads(ln)
        if "sessionId" in d and "sid" in sub:
            d["sessionId"] = sub["sid"]
        if "entrypoint" in d and "entry" in sub:
            d["entrypoint"] = sub["entry"]
        if "cwd" in d and "cwd" in sub:
            d["cwd"] = sub["cwd"]
        p = d.get("payload")
        if d.get("type") == "session_meta" and p is not None:
            p.update({k: v for k, v in (("cwd", sub.get("cwd")), ("source", sub.get("source")),
                                         ("id", sub.get("cid"))) if v})
        out.append(json.dumps(d))
    return out


class World:
    def __init__(self, tmp):
        self.tmp = tmp
        self.home = str(tmp / "home")
        self.cfg = str(tmp / "claude")
        self.codex = str(tmp / "codex")
        self.folder = str(tmp / "pkt")
        os.makedirs(self.folder)
        os.makedirs(ide_launch.server_dir(self.home, KEY))
        self.lid = ide_launch.start(self.home, KEY, self.folder, "job", now=T0)
        ide_launch.update(self.home, KEY, self.lid, job_ref="4242", host="exec7")
        ide_launch.record_open(self.home, KEY, "p", "W1", "me", now=T0 - 1)
        self.procs = []
        self.env = {"CLAUDE_CONFIG_DIR": self.cfg, "CODEX_HOME": self.codex}

    def launch(self):
        return ide_launch.current(self.home, KEY)

    def rollout(self, cid):
        day = time.strftime("%Y/%m/%d")
        return os.path.join(self.codex, "sessions", day, "rollout-2026-11-04T11-00-00-%s.jsonl"
                            % cid)

    def claude_path(self, sid, cwd=None):
        return os.path.join(self.cfg, "projects", s.project_dir_name(cwd or self.folder),
                            sid + ".jsonl")

    def write(self, path, lines):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as fp:
            fp.write("".join(ln + "\n" for ln in lines))

    def claude(self, sid, entry="claude-vscode", env=None, start=None):
        argv = [sys.executable, FAKE, "claude", self.cfg, self.folder, sid, entry]
        return {"argv": argv + ([start] if start else []), "env": env or {}}

    def codex_child(self, cid):
        return {"argv": [sys.executable, FAKE, "codex", self.rollout(cid)], "env": {}}

    def server(self, children, launch_id=None):
        spec = self.tmp / ("spec%d.json" % len(self.procs))
        spec.write_text(json.dumps(children))
        env = dict(os.environ, WPK_IDE_LAUNCH=launch_id or self.lid, WPK_IDE_KEY=KEY,
                   SECRET_TOKEN="SENTINEL-ENV", **self.env)
        p = subprocess.Popen([sys.executable, FAKE, "server", str(spec)], env=env,
                             start_new_session=True)
        self.procs.append(p)
        return p

    def standalone(self, child):
        """A harness process that is not under the editor."""
        p = subprocess.Popen(child["argv"], env=dict(os.environ, **self.env, **child["env"]),
                             start_new_session=True)
        self.procs.append(p)
        return p

    def wait_ready(self, n_claude=0, codex=()):
        deadline = time.time() + 10
        while time.time() < deadline:
            d = os.path.join(self.cfg, "sessions")
            have = len(os.listdir(d)) if os.path.isdir(d) else 0
            if have >= n_claude and all(os.path.exists(self.rollout(c) + ".ready")
                                        for c in codex):
                return
            time.sleep(0.05)
        raise AssertionError("fake harnesses never got ready")

    def collector(self, root):
        return s.Collector(self.home, self.launch(), root=root.pid if root else None,
                           env=self.env)

    def close(self):
        # SIGTERM first: ide_job stops its server (in a group of its own) on it, and a
        # SIGKILL would leave that server running.
        for p in self.procs:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    p.wait(5)
                    break
                except subprocess.TimeoutExpired:
                    continue


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


def _recs(w):
    return {r["session_id"]: r for r in s.records(w.home)}


def test_confirmed_sessions_of_both_harnesses(world):
    w = world
    srv = w.server([w.claude(SID[0]), w.codex_child(CID)])
    w.write(w.claude_path(SID[0]), _fixture("claude_vscode.jsonl", sid=SID[0], cwd=w.folder))
    w.wait_ready(1, [CID])
    w.write(w.rollout(CID), _fixture("codex_vscode.jsonl", cid=CID, cwd=w.folder))
    c = w.collector(srv)
    assert c.pass_once() == 2
    r = _recs(w)
    a, b = r[SID[0]], r[CID]
    assert a["attribution"] == b["attribution"] == "confirmed"
    assert a["project"] == "p" and a["wpid"] == "W1" and a["key"] == KEY
    assert a["job_ref"] == "4242" and a["host"] == "exec7" and a["launch_ids"] == [w.lid]
    assert a["model"] == "claude-sonnet-5" and a["last_event"] == s.TURN_END
    assert s.total(a["usage"]) == 686 and a["client"] == "vscode-ext" and a["live"]
    assert a["status"] == "busy"
    assert b["harness"] == "codex" and b["model"] == "gpt-5.5-codex"
    assert s.total(b["usage"]) == 2590 and b["client"] == "vscode-ext"
    # appended while watched: the row moves on, nothing is counted twice
    w.write(w.claude_path(SID[0]), [json.dumps({
        "type": "assistant", "sessionId": SID[0], "timestamp": "2026-11-04T10:05:00Z",
        "message": {"id": "msg_E", "model": "claude-opus-5-5", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "SENTINEL-ARG"}}],
            "usage": {"input_tokens": 1, "output_tokens": 2}}})])
    c.pass_once()
    a = _recs(w)[SID[0]]
    assert a["model"] == "claude-opus-5-5" and a["last_event"] == s.SHELL
    assert s.total(a["usage"]) == 689 and a["turn_state"] == s.BUSY


def test_two_sessions_in_one_editor_are_two_rows(world):
    w = world
    srv = w.server([w.claude(SID[1]), w.claude(SID[2])])
    for sid in SID[1:3]:
        w.write(w.claude_path(sid), _fixture("claude_vscode.jsonl", sid=sid, cwd=w.folder))
    w.wait_ready(2)
    assert w.collector(srv).pass_once() == 2
    assert set(_recs(w)) == {SID[1], SID[2]}


def test_an_unrelated_cli_session_in_the_same_folder_is_not_shown(world):
    w = world
    srv = w.server([])
    w.standalone(w.claude(SID[3], entry="cli"))                 # not under the editor
    w.write(w.claude_path(SID[3]), _fixture("claude_vscode.jsonl", sid=SID[3],
                                            entry="cli", cwd=w.folder))
    w.wait_ready(1)
    w.collector(srv).pass_once()
    assert _recs(w) == {}


def test_a_process_with_another_launch_is_not_this_ones(world):
    w = world
    srv = w.server([w.claude(SID[4])], launch_id="L-ffffffffffff")
    w.write(w.claude_path(SID[4]), _fixture("claude_vscode.jsonl", sid=SID[4],
                                            entry="cli", cwd=w.folder))
    w.wait_ready(1)
    assert w.collector(srv).pass_once() == 0 and _recs(w) == {}


def test_an_extension_session_with_no_process_is_a_workspace_match(world):
    w = world
    w.write(w.claude_path(SID[5]), _fixture("claude_vscode.jsonl", sid=SID[5], cwd=w.folder))
    w.write(w.rollout(CID), _fixture("codex_vscode.jsonl", cid=CID, cwd=w.folder))
    w.write(w.claude_path(SID[6]), _fixture("claude_vscode.jsonl", sid=SID[6], cwd="/elsewhere"))
    c = w.collector(None)
    c.pass_once()
    r = _recs(w)
    assert set(r) == {SID[5], CID}
    assert r[SID[5]]["attribution"] == r[CID]["attribution"] == "workspace"
    assert "job_ref" not in r[SID[5]] and "host" not in r[SID[5]]
    assert r[SID[5]]["wpid"] == "W1"


def test_a_session_outside_the_launch_window_is_not_matched(world):
    w = world
    lines = _fixture("claude_vscode.jsonl", sid=SID[7], cwd=w.folder)
    lines = [ln.replace("2026-11-04T10:", "2026-11-03T10:") for ln in lines]
    w.write(w.claude_path(SID[7]), lines)
    w.collector(None).pass_once()
    assert _recs(w) == {}


def test_a_scheduled_steps_session_is_never_shown(world, monkeypatch):
    w = world
    proj = os.path.join(w.folder, ".work-packet")
    os.makedirs(os.path.join(proj, "runs", "W1", "steps", "1"))
    with open(os.path.join(proj, "runs", "W1", "steps", "1", "meta.json"), "w") as fp:
        json.dump({"session_id": SID[8]}, fp)
    from work_packet import registry
    monkeypatch.setattr(registry, "get", lambda name, h=None: {"name": name, "path": proj})
    srv = w.server([w.claude(SID[8], entry="sdk-cli")])      # `wpk step` in a terminal
    w.write(w.claude_path(SID[8]), _fixture("claude_vscode.jsonl", sid=SID[8], cwd=w.folder))
    w.wait_ready(1)
    w.collector(srv).pass_once()
    assert _recs(w) == {}


def test_a_reused_pid_is_not_believed(world):
    w = world
    srv = w.server([w.claude(SID[9], start="1")])             # procStart that is not its own
    w.write(w.claude_path(SID[9]), _fixture("claude_vscode.jsonl", sid=SID[9], entry="cli",
                                            cwd=w.folder))
    w.wait_ready(1)
    assert w.collector(srv).pass_once() == 0 and _recs(w) == {}


def test_two_packets_sharing_a_folder(world):
    w = world
    ide_launch.record_open(w.home, KEY, "p", "W2", "me", now=T0 - 0.5)
    srv = w.server([w.claude(SID[1]), w.claude(SID[2], env={"WPK_WPID": "W2"})])
    for sid in SID[1:3]:
        w.write(w.claude_path(sid), _fixture("claude_vscode.jsonl", sid=sid, cwd=w.folder))
    w.wait_ready(2)
    w.collector(srv).pass_once()
    r = _recs(w)
    assert r[SID[1]]["project"] == "p" and "wpid" not in r[SID[1]]   # ambiguous: left empty
    assert r[SID[2]]["wpid"] == "W2"                                # its terminal said so


def test_a_restart_keeps_identity_and_counts(world):
    w = world
    srv = w.server([w.claude(SID[0])])
    path = w.claude_path(SID[0])
    w.write(path, _fixture("claude_vscode.jsonl", sid=SID[0], cwd=w.folder))
    w.wait_ready(1)
    w.collector(srv).pass_once()
    before = _recs(w)[SID[0]]
    # the board (or the job's collector) restarts; the session goes on
    w.write(path, [json.dumps({"type": "assistant", "sessionId": SID[0],
                               "timestamp": "2026-11-04T10:09:00Z",
                               "message": {"id": "msg_F", "usage": {"output_tokens": 4}}})])
    w.collector(srv).pass_once()
    after = _recs(w)[SID[0]]
    assert s.total(after["usage"]) == s.total(before["usage"]) + 4
    assert after["first_seen_t"] == before["first_seen_t"]
    # resumed under a new launch of the same editor: one row, both launches
    lid2 = ide_launch.start(w.home, KEY, w.folder, "job", now=T0 + 10)
    srv2 = w.server([w.claude(SID[0])], launch_id=lid2)
    deadline = time.time() + 10
    while len(os.listdir(os.path.join(w.cfg, "sessions"))) < 2 and time.time() < deadline:
        time.sleep(0.05)
    s.Collector(w.home, ide_launch.current(w.home, KEY), root=srv2.pid, env=w.env).pass_once()
    again = _recs(w)[SID[0]]
    assert again["launch_ids"] == [w.lid, lid2]
    assert s.total(again["usage"]) == s.total(after["usage"])


def test_no_sentinel_reaches_the_store(world):
    w = world
    srv = w.server([w.claude(SID[0]), w.codex_child(CID)])
    w.write(w.claude_path(SID[0]), _fixture("claude_vscode.jsonl", sid=SID[0], cwd=w.folder))
    w.wait_ready(1, [CID])
    w.write(w.rollout(CID), _fixture("codex_vscode.jsonl", cid=CID, cwd=w.folder))
    w.collector(srv).pass_once()
    assert len(_recs(w)) == 2
    for root in (s.sessions_dir(w.home), ide_launch.server_dir(w.home, KEY)):
        for d, _, files in os.walk(root):
            for f in files:
                assert b"SENTINEL" not in open(os.path.join(d, f), "rb").read(), f
                assert os.stat(os.path.join(d, f)).st_mode & 0o077 == 0, f


def test_the_store_keeps_only_allowed_fields(tmp_path):
    h = str(tmp_path)
    got = s.write(h, {"harness": "claude", "session_id": SID[0], "prompt": "SENTINEL",
                      "model": "x SENTINEL; rm", "last_event": "SENTINEL", "host": "a b",
                      "usage": {"output_tokens": 3}, "project": "p\nq", "wpid": "W1",
                      "attribution": "guess", "launch_ids": ["L-SENTINEL"]})
    assert got == {"harness": "claude", "session_id": SID[0], "usage": {"output_tokens": 3},
                   "wpid": "W1"}
    assert s.write(h, {"harness": "other", "session_id": SID[0]}) is None
    with open(os.path.join(s.sessions_dir(h), "claude-%s.json" % SID[0]), "w") as fp:
        json.dump({"harness": "claude", "session_id": SID[0], "prompt": "SENTINEL"}, fp)
    assert "prompt" not in s.records(h)[0]                  # cleaned on the way out too


def test_prune(tmp_path):
    h = str(tmp_path)
    now = 1_800_000_000
    for i in range(6):
        s.write(h, {"harness": "claude", "session_id": SID[i],
                    "last_activity_t": now - i * 10 * 86400})
    assert s.prune(h, now, keep_days=30, keep=3) == 3
    assert {r["session_id"] for r in s.records(h)} == set(SID[:3])
    assert s.prune(h, now, keep_days=30, keep=2) == 1


# --- S4: who runs the collector (§4.4) ------------------------------------------

def test_the_boards_pass_watches_a_local_launch_until_it_ends(world):
    w = world
    srv = w.server([w.claude(SID[0])])
    lid = ide_launch.start(w.home, KEY, w.folder, "local", now=T0)
    ide_launch.update(w.home, KEY, lid, pid=srv.pid)
    srv2 = w.server([w.claude(SID[1])], launch_id=lid)      # the real one: its env is lid
    ide_launch.update(w.home, KEY, lid, pid=srv2.pid)
    w.write(w.claude_path(SID[1]), _fixture("claude_vscode.jsonl", sid=SID[1], cwd=w.folder))
    w.wait_ready(2)
    cs = {}
    import unittest.mock as um
    with um.patch.dict(os.environ, w.env):
        assert s.local_pass(w.home, cs) == 1 and list(cs) == [lid]
        r = _recs(w)
        assert set(r) == {SID[1]} and r[SID[1]]["attribution"] == "confirmed"
        assert "job_ref" not in r[SID[1]]                      # a local editor has no job
        os.killpg(srv2.pid, signal.SIGKILL)
        srv2.wait()
        assert s.local_pass(w.home, cs) == 0 and cs == {}       # one last pass, then dropped
    assert _recs(w)[SID[1]]["live"] is False


def test_the_job_watches_its_own_sessions(world):
    """``ide_job --collect``: the monitor beside the editor, on the exec host."""
    w = world
    spec = w.tmp / "jobspec.json"
    spec.write_text(json.dumps([w.claude(SID[2])]))
    sdir = ide_launch.server_dir(w.home, KEY)
    env = dict(os.environ, **w.env)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(os.path.dirname(HERE), "src")] + [env.get("PYTHONPATH", "")])
    w.write(w.claude_path(SID[2]), _fixture("claude_vscode.jsonl", sid=SID[2], cwd=w.folder))
    job = subprocess.Popen([sys.executable, "-m", "work_packet.sched.ide_job", sdir,
                            "--launch", w.lid, "--collect", "0.2", "--",
                            sys.executable, FAKE, "server", str(spec)],
                           env=env, start_new_session=True)
    w.procs.append(job)
    deadline = time.time() + 15
    # the first sweep may see the transcript before the process: a workspace
    # match, upgraded to confirmed on the next pass and never downgraded
    while _recs(w).get(SID[2], {}).get("attribution") != "confirmed" and \
            time.time() < deadline:
        time.sleep(0.1)
    r = _recs(w)[SID[2]]
    assert r["attribution"] == "confirmed" and r["job_ref"] == "4242"
    import socket
    assert ide_launch.current(w.home, KEY)["host"] == socket.gethostname()


def test_the_runner_watches_only_with_web_and_sessions_on(tmp_path, monkeypatch):
    from work_packet.dash.runner import Runner
    calls = []
    monkeypatch.setattr(s, "local_pass", lambda h, cs: calls.append(h) or 0)
    for text, want in (("[ide]\nweb = true\nsessions_poll_s = 1\n", True),
                       ("[ide]\nweb = true\nsessions = false\nsessions_poll_s = 1\n", False),
                       ("", False)):
        (tmp_path / "config.toml").write_text(text)
        calls.clear()
        r = Runner(home=str(tmp_path))
        import threading
        t = threading.Thread(target=r._sessions_loop, daemon=True)
        t.start()
        time.sleep(0.3)
        r._stopping.set()
        t.join(5)
        assert bool(calls) == want, text


def test_codex_turns_reach_presence(world, monkeypatch):
    """A Codex session's turn becomes its presence record, as Claude's hooks make
    Claude's (docs/agent-state-plan.md A1): working, then waiting, then ended."""
    from work_packet import presence, registry
    w = world
    proj = str(w.tmp / "proj")
    monkeypatch.setattr(registry, "get", lambda name, h=None: {"name": name, "path": proj}
                        if name == "p" else None)
    srv = w.server([w.codex_child(CID)])
    w.wait_ready(0, [CID])
    lines = _fixture("codex_vscode.jsonl", cid=CID, cwd=w.folder)
    done = next(i for i, ln in enumerate(lines) if "task_complete" in ln)
    w.write(w.rollout(CID), lines[:done])
    c = w.collector(srv)
    c.pass_once()
    rec = presence.records(proj, ttl=None)[0]
    assert rec["source"] == "codex-" + CID and rec["kind"] == "codex"
    assert rec["turn"] == "working" and rec["wpid"] == "W1" and rec["via"] == "vscode"
    assert isinstance(rec["pid"], int)
    w.write(w.rollout(CID), lines[done:])
    c.pass_once()
    rec = presence.records(proj, ttl=None)[0]
    assert rec["turn"] == "waiting"
    beat = rec["beat"]
    c.pass_once()                               # waiting beats once
    assert presence.records(proj, ttl=None)[0]["beat"] == beat
    w.close()
    c.pass_once()
    assert presence.records(proj, ttl=None) == []
    assert presence.every(proj)[0]["turn"] == "ended"
