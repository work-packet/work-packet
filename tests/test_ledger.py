"""The token ledger (docs/token-ledger.md): every transcript's replies counted
once, sessions attributed, steps kept after their packet is gone."""
import datetime
import json
import os
import shutil

import pytest

from conftest import NOW
from test_dash_tasks import _client, _new
from work_packet import executor, ide_sessions, ledger, ledger_collect, scribe, session_usage
from work_packet.dash import tokens

T = ide_sessions.epoch(NOW)
H = 3600
SID = "7f3c1a2e-0b5d-4c6e-9f10-000000000001"


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _line(mid, t, out, sid=SID, cwd="/nowhere", model="claude-opus-5-5", entry="cli", **kw):
    ts = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
    return json.dumps(dict({"type": "assistant", "sessionId": sid, "timestamp": ts, "cwd": cwd,
                            "entrypoint": entry, "message": {
                                "id": mid, "model": model,
                                "usage": {"input_tokens": 10, "output_tokens": out}}}, **kw))


def _claude(tmp_path, monkeypatch):
    d = tmp_path / "claude"
    (d / "projects" / "-p").mkdir(parents=True)
    monkeypatch.setenv("WPK_LEDGER_CLAUDE_DIR", str(d))
    return d / "projects" / "-p"


def _totals(home, **kw):
    out = {}
    for _, _, u, _ in ledger.buckets(home, runner=True, **kw):
        for k, v in u.items():
            out[k] = out.get(k, 0) + v
    return out


def test_a_reply_is_counted_once_across_revisions_resumes_and_passes(tmp_path, monkeypatch):
    home = str(tmp_path / "h")
    d = _claude(tmp_path, monkeypatch)
    # three content blocks of one reply (the last has the final usage), and a second reply
    (d / "a.jsonl").write_text("\n".join([_line("m1", T, 5), _line("m1", T, 5),
                                          _line("m1", T, 50), _line("m2", T + 2 * H, 7)]) + "\n")
    got = ledger_collect.pass_once(home)
    assert got["replies"] == 2
    assert _totals(home) == {"input_tokens": 20, "output_tokens": 57}
    # a resumed session copies the history into a new file under a new id
    (d / "b.jsonl").write_text("\n".join([_line("m1", T, 50, sid="new-session-0001"),
                                          _line("m3", T + 3 * H, 1, sid="new-session-0001")])
                               + "\n")
    with open(d / "a.jsonl", "a") as fp:      # and the first one grows
        fp.write(_line("m4", T + 4 * H, 2) + "\n")
    got = ledger_collect.pass_once(home)
    assert got["replies"] == 2
    assert _totals(home) == {"input_tokens": 40, "output_tokens": 60}
    hours = {(t, rec["session_id"]) for t, _, _, rec in ledger.buckets(home)}
    assert (ledger.hour_of(T), SID) in hours                 # m1 stays with its first session
    # nothing new: nothing read; reading everything again changes nothing
    assert ledger_collect.pass_once(home)["replies"] == 0
    con = ledger.connect(home)
    con.execute("DELETE FROM cursor")
    con.commit()
    con.close()
    ledger_collect.pass_once(home)
    assert _totals(home) == {"input_tokens": 40, "output_tokens": 60}


def test_the_ledger_keeps_counts_after_the_transcript_is_gone(tmp_path, monkeypatch):
    home = str(tmp_path / "h")
    d = _claude(tmp_path, monkeypatch)
    (d / "a.jsonl").write_text(_line("m1", T, 5) + "\n")
    ledger_collect.pass_once(home)
    os.remove(d / "a.jsonl")
    ledger_collect.pass_once(home)
    assert _totals(home) == {"input_tokens": 10, "output_tokens": 5}


def test_sessions_are_attributed_by_their_folder(fake, tmp_path, monkeypatch):
    e, pkt = _new("a")
    home = os.environ["WPK_HOME"]
    d = _claude(tmp_path, monkeypatch)
    (d / "a.jsonl").write_text("\n".join([
        _line("m1", T, 1, sid="in-the-packet-01", cwd=pkt.path),
        _line("m2", T, 1, sid="in-the-project1", cwd=os.path.join(e["path"], "src")),
        _line("m3", T, 1, sid="somewhere-else1", cwd=str(tmp_path)),
        _line("m4", T, 1, sid="a-runner-in-it1", cwd=pkt.path, entry="sdk-cli")]) + "\n")
    ledger_collect.pass_once(home)
    con = ledger.connect(home)
    got = {sid: ledger.session(con, "claude", sid) for sid in
           ("in-the-packet-01", "in-the-project1", "somewhere-else1", "a-runner-in-it1")}
    con.close()
    assert (got["in-the-packet-01"]["how"], got["in-the-packet-01"]["wpid"],
            got["in-the-packet-01"]["packet_name"]) == ("cwd-packet", pkt.wpid, "a")
    assert (got["in-the-project1"]["how"], got["in-the-project1"]["project"],
            got["in-the-project1"]["wpid"]) == ("cwd-project", "a", None)
    assert got["somewhere-else1"]["how"] == "none" and got["somewhere-else1"]["project"] is None
    assert got["a-runner-in-it1"]["source"] == "runner"
    # your sessions on the Cost tab: the packet's and the project's, not the runner's
    rows = {r["session"] for r in tokens.project(e, home=home)["sessions"]}
    assert rows == {"in-the-packet-01", "in-the-project1"}


def test_wpk_model_calls_are_their_own(tmp_path, monkeypatch):
    home = str(tmp_path / "h")
    d = _claude(tmp_path, monkeypatch)
    # an old call, from before calls carried an id: known by its prompt
    user = json.dumps({"type": "user", "sessionId": "old-status-call", "entrypoint": "sdk-cli",
                       "message": {"content": "You keep a work packet's status current. A"}})
    (d / "a.jsonl").write_text(user + "\n" + _line("m1", T, 1, sid="old-status-call",
                                                   entry="sdk-cli") + "\n")
    ledger_collect.pass_once(home)
    con = ledger.connect(home)
    s = ledger.session(con, "claude", "old-status-call")
    assert (s["source"], s["purpose"]) == ("model-call", "status")
    con.close()
    # a call now: its id is in the ledger before claude starts
    seen = []
    monkeypatch.setattr(scribe.subprocess, "run", lambda argv, **kw: seen.append(argv) or
                        type("P", (), {"stdout": '{"result": "ok"}', "returncode": 0,
                                       "stderr": ""})())
    scribe.call_model("hi", home, purpose="brief", wpid="w1")
    sid = seen[0][seen[0].index("--session-id") + 1]
    con = ledger.connect(home)
    s = ledger.session(con, "claude", sid)
    con.close()
    assert (s["how"], s["source"], s["purpose"], s["wpid"]) == ("model-call", "model-call",
                                                                 "brief", "w1")


def test_the_store_fills_in_and_the_transcript_wins(tmp_path, monkeypatch):
    home = str(tmp_path / "h")
    d = _claude(tmp_path, monkeypatch)
    rec = {"harness": "claude", "session_id": SID, "project": "p", "wpid": "w",
           "client": "vscode-ext"}
    session_usage.put(home, rec, {str(ledger.hour_of(T)): {"claude-opus-5-5": {"output_tokens": 3}},
                                  str(ledger.hour_of(T - 5 * H)): {"claude-opus-5-5": {
                                      "output_tokens": 9}}})
    assert _totals(home) == {"output_tokens": 12}       # store only (another host, say)
    (d / "a.jsonl").write_text(_line("m1", T, 5) + "\n")
    ledger_collect.pass_once(home)
    # the hour the transcript has comes from it; the other stays the store's
    assert _totals(home) == {"input_tokens": 10, "output_tokens": 14}
    b = ledger.buckets(home)
    assert {r["project"] for _, _, _, r in b} == {"p"} and b[0][3]["client"] == "vscode-ext"


def test_a_removed_packet_keeps_its_cost(fake):
    e, pkt = _new("g")
    assert executor.step(e["path"]).code == 0
    home = os.environ["WPK_HOME"]
    before = tokens.project(e, home=home)
    runner = sum(r["cost_usd"] or 0 for r in before["packets"])
    assert runner > 0
    ledger_collect.pass_once(home)
    con = ledger.connect(home)
    (n, sid), = con.execute("SELECT count(*), session FROM step").fetchall()
    assert n == 1 and ledger.session(con, "claude", sid)["how"] == "runner"
    con.close()
    shutil.rmtree(pkt.path)
    ledger_collect.pass_once(home)
    after = tokens.project(e, home=home)
    assert sum(r["cost_usd"] or 0 for r in after["packets"]) == pytest.approx(runner)
    assert after["packets"][0]["label"] == "g"              # by its name, not its id
    page = _client().get("/").text
    tile = page[page.index("Spend today"):][:400]
    assert "$%.2f" % runner in tile or ("%.3f" % runner) in tile


def test_a_packet_folder_is_its_projects(tmp_path, monkeypatch):
    # the packet layout: the project is <folder>/.work-packet, people work in <folder>
    from work_packet import registry
    folder = tmp_path / "fw-thing"
    (folder / ".work-packet" / "runs").mkdir(parents=True)
    entries = []
    monkeypatch.setattr(registry, "entries", lambda home=None: entries)
    home = str(tmp_path / "h")
    d = _claude(tmp_path, monkeypatch)
    (d / "a.jsonl").write_text(_line("m1", T, 1, cwd=str(folder / "src")) + "\n")
    ledger_collect.pass_once(home)
    con = ledger.connect(home)
    assert ledger.session(con, "claude", SID)["how"] == "none"
    con.close()
    # registered later: its earlier sessions are claimed on the next pass
    entries.append({"name": "fw-thing", "path": str(folder / ".work-packet")})
    ledger_collect.pass_once(home)
    con = ledger.connect(home)
    s = ledger.session(con, "claude", SID)
    con.close()
    assert (s["how"], s["project"], s["wpid"]) == ("cwd-project", "fw-thing", None)


def _proc(root, pid, cwd, argv, **env):
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (d / "environ").write_bytes(b"\0".join(("%s=%s" % kv).encode() for kv in env.items()))
    os.symlink(cwd, d / "cwd")


def test_a_live_terminal_names_its_packet(fake, tmp_path, monkeypatch):
    # rule 4: a claude started in a terminal wpk opened carries WPK_WPID; its folder
    # alone would say only the project
    e, pkt = _new("a")
    home = os.environ["WPK_HOME"]
    d = _claude(tmp_path, monkeypatch)
    src = os.path.join(e["path"], "src")
    os.makedirs(src, exist_ok=True)
    proc = tmp_path / "proc"
    _proc(proc, 101, src, ["claude"], WPK_WPID=pkt.wpid, WPK_PROJECT="a")
    _proc(proc, 102, src, ["claude", "--resume", "by-its-id-00001"], WPK_WPID=pkt.wpid)
    _proc(proc, 103, src, ["claude", "-p"], WPK_WPID=pkt.wpid, WPK_STEP="1")   # a runner's
    _proc(proc, 104, str(tmp_path), ["claude"])                                 # untagged
    monkeypatch.setenv("WPK_LEDGER_PROC", str(proc))
    (d / "a.jsonl").write_text("\n".join([
        _line("m1", T, 1, sid="by-its-folder-01", cwd=src),
        _line("m2", T, 1, sid="by-its-id-00001", cwd=str(tmp_path))]) + "\n")
    ledger_collect.pass_once(home)
    con = ledger.connect(home)
    got = [ledger.session(con, "claude", s) for s in ("by-its-folder-01", "by-its-id-00001")]
    con.close()
    assert [(s["how"], s["project"], s["wpid"], s["source"]) for s in got] == \
        [("env", "a", pkt.wpid, "interactive")] * 2


def test_console_and_studio_sessions_are_theirs(tmp_path, monkeypatch):
    home = str(tmp_path / "h")
    d = _claude(tmp_path, monkeypatch)
    for cid, mode, sid in (("c1", "console", "console-session1"), ("c2", "studio", SID)):
        p = tmp_path / "h" / "console" / cid
        p.mkdir(parents=True)
        (p / "meta.json").write_text(json.dumps({"id": cid, "mode": mode, "session": sid,
                                                 "project": "p", "wpid": "w", "cwd": "/x"}))
    # the studio's session runs in the packet's folder: the folder rule must not win
    (d / "a.jsonl").write_text(_line("m1", T, 3, entry="sdk-cli") + "\n")
    got = ledger_collect.pass_once(home)
    assert got["console"] == 2
    assert ledger_collect.pass_once(home)["console"] == 0      # unchanged: not read again
    con = ledger.connect(home)
    a, b = (ledger.session(con, "claude", s) for s in ("console-session1", SID))
    con.close()
    assert (a["how"], a["source"], a["project"]) == ("console", "console", "p")
    assert (b["how"], b["source"], b["purpose"]) == ("console", "studio", "studio")
    assert {r["source"] for _, _, _, r in ledger.buckets(home)} == {"studio"}


def test_verify(fake, tmp_path, monkeypatch):
    e, pkt = _new("v")
    assert executor.step(e["path"]).code == 0
    home = os.environ["WPK_HOME"]
    d = _claude(tmp_path, monkeypatch)
    ledger_collect.pass_once(home)
    con = ledger.connect(home)
    (sid, out), = con.execute("SELECT session, output_tokens FROM step").fetchall()
    con.close()
    assert ledger_collect.check_steps(home)["none"] == 1         # no transcript read
    (d / "a.jsonl").write_text(_line("m1", T, out, sid=sid) + "\n")
    ledger_collect.pass_once(home)
    assert ledger_collect.check_steps(home)["same"] == 1
    (d / "b.jsonl").write_text(_line("m2", T, 1, sid=sid) + "\n")    # a sub-agent, say
    ledger_collect.pass_once(home)
    got = ledger_collect.check_steps(home)
    assert (got["more"], got["less"]) == (1, 0)
    got = ledger_collect.check_reread(home, quiet_s=-1e12)
    assert got["files"] == 2 and got["rows"] >= 1 and got["changed"] == []
    # a reply counted wrongly shows up
    con = ledger.connect(home)
    con.execute("UPDATE usage SET output_tokens = output_tokens + 5")
    con.commit()
    con.close()
    assert ledger_collect.check_reread(home, quiet_s=-1e12)["changed"]


def _rec(kind, t, **payload):
    ts = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
    return json.dumps({"type": kind, "timestamp": ts, "payload": payload})


def test_codex_counts_what_each_snapshot_adds(tmp_path, monkeypatch):
    home = str(tmp_path / "h")
    x = tmp_path / "codex"
    day = x / "sessions" / "2026" / "10" / "21"
    day.mkdir(parents=True)
    monkeypatch.setenv("WPK_LEDGER_CODEX_DIR", str(x))
    root = "019e0000-0000-7000-8000-000000000001"

    def tc(t, inp, cached, out):
        return _rec("event_msg", t, type="token_count", info={"total_token_usage": {
            "input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out}})
    a = day / "rollout-a.jsonl"
    a.write_text("\n".join([
        _rec("session_meta", T, id=root, cwd="/nowhere", originator="codex_cli_rs",
             source="cli"),
        _rec("turn_context", T, model="gpt-5.5"),
        tc(T, 100, 40, 10), tc(T, 100, 40, 10),            # the same total twice
        tc(T + 2 * H, 300, 140, 25)]) + "\n")
    got = ledger_collect.pass_once(home)
    assert got["replies"] == 2
    assert _totals(home) == {"input_tokens": 160, "cache_read_input_tokens": 140,
                             "output_tokens": 25}
    hours = sorted(t for t, _, _, _ in ledger.buckets(home))
    assert hours == [ledger.hour_of(T), ledger.hour_of(T + 2 * H)]
    # a sub-agent's rollout: its own thread, counted in its root's session
    (day / "rollout-b.jsonl").write_text("\n".join([
        _rec("session_meta", T, id="019e0000-0000-7000-8000-000000000002", session_id=root,
             cwd="/nowhere", source={"subagent": {"thread_spawn": {"parent_thread_id": root}}}),
        tc(T + H, 50, 0, 5)]) + "\n")
    # a copy of the first rollout adds nothing; nor does reading everything again
    (day / "rollout-c.jsonl").write_text(a.read_text())
    ledger_collect.pass_once(home)
    con = ledger.connect(home)
    con.execute("DELETE FROM cursor")
    con.commit()
    con.close()
    ledger_collect.pass_once(home)
    assert _totals(home) == {"input_tokens": 210, "cache_read_input_tokens": 140,
                             "output_tokens": 30}
    b = ledger.buckets(home)
    assert {(r["harness"], r["session_id"], r["client"]) for _, _, _, r in b} == \
        {("codex", root, "terminal")}
    assert {m for _, m, _, _ in b} == {"gpt-5.5", "unknown"}


def test_statistics_shows_activity_and_what_no_project_claimed(fake, tmp_path, monkeypatch):
    from work_packet import clock
    e, pkt = _new("s")
    assert executor.step(e["path"]).code == 0
    home = os.environ["WPK_HOME"]
    d = _claude(tmp_path, monkeypatch)
    now = clock.now().timestamp()
    stray = str(tmp_path / "scratch-work")
    ledger_collect.pass_once(home)                  # learns the runner's session id
    con = ledger.connect(home)
    (runner,), = con.execute("SELECT session FROM step").fetchall()
    con.close()
    (d / "a.jsonl").write_text("\n".join([
        _line("m1", now - 60, 400, sid="stray-session-01", cwd=stray),
        _line("m2", now - 60, 200, sid="in-the-project1", cwd=e["path"]),
        _line("m3", now - 60, 300, sid=runner, entry="sdk-cli")]) + "\n")
    ledger_collect.pass_once(home)
    chart = tokens.activity(home, days=1)
    last, = [b for b in chart["bars"] if b["segs"]]
    assert [g["cls"] for g in last["segs"]] == ["sp0", "sp1"]       # runner, your sessions
    assert "runner 310" in last["title"] and "your sessions 620" in last["title"]
    page = _client().get("/stats?days=1").text
    assert 'id="activity"' in page
    tail = page[page.index('id="elsewhere"'):]
    assert "Not in a project" in tail and "scratch-work" in tail
    assert "1 session," in tail[:400]
