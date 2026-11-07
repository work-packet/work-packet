"""Concurrency and jobs (docs/collaboration.md W7, §7.10; plan C7a, C7b): jobs
as workers on a packet, and a packet's status at a glance."""

import io
import json
import os
import sys
import time

import pytest

from test_dash_tasks import _client, _flash, _new
from work_packet import (jobs, notify, registry, scheduler, sessionhooks, statusline,
                         views)
from work_packet.dash import data


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _parked(name="sim"):
    from work_packet import executor
    e, pkt = _new(name)
    executor.admin(pkt, "pause")
    return e, pkt


# --- C7a: jobs --------------------------------------------------------------------------

def test_a_job_is_recorded_and_its_status_passes_through(fake, tmp_path):
    e, pkt = _parked()
    out = io.BytesIO()
    code = jobs.run([sys.executable, "-c", "print('hello'); raise SystemExit(3)"],
                    cwd=e["path"], out=out, proj=e["path"])
    assert code == 3 and b"hello" in out.getvalue()
    [d] = jobs.all_jobs(e["path"])
    assert d["state"] == "failed" and d["exit"] == 3 and not d["seen"]
    assert "hello" in jobs.tail(e["path"], d["id"])
    types = [r["type"] for r in pkt.journal().records]
    assert "job-start" in types and "job-end" in types
    [it] = jobs.items(e["path"])
    assert it["failed"] and "exit 3" in it["text"]
    jobs.mark_seen(e["path"], d["id"])
    assert jobs.items(e["path"]) == []


def test_outside_a_packet_it_just_runs(tmp_path):
    assert jobs.run([sys.executable, "-c", "raise SystemExit(4)"], cwd=str(tmp_path),
                    out=io.BytesIO()) == 4


def test_a_running_job_holds_the_ball(fake):
    e, pkt = _parked()
    d = jobs.start(e["path"], ["make", "sim"], e["path"], now=time.time() - 4320)
    assert [j["id"] for j in jobs.live(e["path"])] == [d["id"]]   # our pid: alive
    c = data.card(e)
    assert c["ball"]["who"] == "external" and c["column"] == "Waiting"
    assert c["ball"]["text"].startswith("waiting on make sim, 1h12m")
    # a question still comes first
    b = views.ball({"state": "NEEDS_INPUT", "reason": "which?"}, jobs=jobs.live(e["path"]))
    assert b["kind"] == "question"
    jobs.end(e["path"], d, 0)
    c = data.card(e)
    assert c["ball"]["who"] != "external" and c["job_items"][0]["text"] == "make sim finished"


def test_a_lost_job(fake):
    e, _ = _parked()
    d = jobs.start(e["path"], ["make", "sim"], e["path"], pid=2 ** 22 + 12345)
    assert jobs.get(e["path"], d["id"])["state"] == "lost"
    assert jobs.items(e["path"])[0]["failed"]


def test_ended_jobs_on_the_desk_and_in_the_digest(fake):
    e, _ = _parked()
    d = jobs.start(e["path"], ["make", "sim"], e["path"])
    jobs.end(e["path"], d, 2)
    c = _client()
    page = c.get("/").text
    assert "make sim failed (exit 2)" in page and "/p/sim/jobs/%s" % d["id"] in page
    cols, _ = data.board()
    [it] = [i for i in notify.items(cols) if i["project"] == "sim"]
    assert it["type"] == "failure" and it["url"] == "/p/sim/jobs/%s" % d["id"]
    assert not notify.pushable(it, notify.config({}), time.time())   # never a push
    # opening the job page sees it
    r = c.get("/p/sim/jobs/%s" % d["id"])
    assert r.status_code == 200 and "exit 2" in r.text
    assert jobs.items(e["path"]) == []
    assert c.get("/p/sim/jobs/nope").status_code == 404


def test_run_a_command_from_the_board(fake):
    e, _ = _parked()
    c = _client()
    page = c.get("/p/sim").text
    assert 'id="jobs"' in page and "Run a command" in page
    r = c.post("/p/sim/jobs", data={"cmd": "echo from-the-board"}, follow_redirects=False)
    msg, ok = _flash(r)
    assert ok, msg
    for _ in range(100):
        got = [d for d in jobs.all_jobs(e["path"]) if d["state"] != "running"]
        if got:
            break
        time.sleep(0.1)
    [d] = got
    assert d["state"] == "ok" and d["cmd"] == ["sh", "-c", "echo from-the-board"]
    assert "from-the-board" in jobs.tail(e["path"], d["id"])
    assert "echo from-the-board" in c.get("/p/sim").text
    r = c.post("/p/sim/jobs", data={"cmd": "  "}, follow_redirects=False)
    assert not _flash(r)[1]


def test_wpk_run_cli(fake, capfd):
    from work_packet import cli
    e, _ = _parked()
    os.chdir(e["path"])
    assert cli.main(["run", "--", sys.executable, "-c", "print('x')"]) == 0
    assert [d["state"] for d in jobs.all_jobs(e["path"])] == ["ok"]


# --- C7b: status at a glance ------------------------------------------------------------

def test_status_json(fake):
    e, pkt = _new("glance")
    scheduler.tick([e], until_idle=True)
    d = _client().get("/p/glance/status.json").json()
    assert d["name"] == "glance" and d["ball"]["kind"] == "review" and d["needs"] == 1
    assert d["column"] == "Needs you" and d["url"] == "/p/glance"
    assert _client().get("/p/nope/status.json").status_code == 404


def test_the_status_line(fake):
    e, pkt = _parked("line")
    ev = json.dumps({"workspace": {"current_dir": e["path"]}})
    assert statusline.line(io.StringIO(ev)) == "wpk line · parked"
    d = jobs.start(e["path"], ["make", "sim"], e["path"])
    assert statusline.line(io.StringIO(ev)).startswith("wpk line · job: waiting on make sim")
    jobs.end(e["path"], d, 1)
    assert statusline.line(io.StringIO(ev)) == "wpk line · parked · 1 job ended (1 failed)"
    assert statusline.line(io.StringIO("not json")) == "wpk"
    assert statusline.line(io.StringIO(json.dumps({"cwd": "/"}))) == "wpk"


def test_the_hooks_set_a_status_line_unless_you_have_one(tmp_path):
    f = tmp_path / "folder"
    f.mkdir()
    sessionhooks.install(str(f))
    d = json.loads((f / ".claude" / "settings.local.json").read_text())
    assert sessionhooks.LINE_MARK in d["statusLine"]["command"]
    sessionhooks.uninstall(str(f))
    assert not (f / ".claude" / "settings.local.json").exists()
    # yours, in your home settings: ours stays out
    home = tmp_path / "home" / ".claude"
    home.mkdir(parents=True)
    (home / "settings.json").write_text(json.dumps({"statusLine": {"type": "command",
                                                                   "command": "mine"}}))
    sessionhooks.install(str(f))
    d = json.loads((f / ".claude" / "settings.local.json").read_text())
    assert "statusLine" not in d and d["hooks"]
    # yours, in the folder's own file: kept
    (home / "settings.json").unlink()
    p = f / ".claude" / "settings.local.json"
    p.write_text(json.dumps({"statusLine": {"type": "command", "command": "mine"}}))
    sessionhooks.install(str(f))
    assert json.loads(p.read_text())["statusLine"]["command"] == "mine"


# --- C7c: learn from corrections --------------------------------------------------------

UVM = "Use the uvm_info macro for messages, never $display in the testbench."


def test_recurring_notes_become_a_proposal(fake):
    from work_packet import inbox, learn, notes
    h = registry.home()
    _, a = _parked("alpha")
    _, b = _parked("beta")
    notes.add(a, UVM, "me")
    notes.add(a, "Please run the lint before you commit anything.", "me")
    assert learn.propose(h) == []                     # once, in one project: not yet
    notes.add(b, "Again: use the uvm_info macro for messages, not $display.", "me")
    [it] = learn.propose(h)
    assert it["source"] == "learn" and it["ref"]["projects"] == ["alpha", "beta"]
    assert "2 times" in it["text"] and it["ref"]["times"] == 2
    assert learn.propose(h) == []                     # never twice
    assert [d["id"] for d in inbox.items(h)] == [it["id"]]
    # answers count too, and short ones never do
    from work_packet import executor
    assert [c["kind"] for c in learn.corrections(h)].count("note") == 3
    executor.admin(a, "handoff", note="yes")
    assert len(learn.corrections(h)) == 3


def test_three_times_in_one_project(fake):
    from work_packet import learn, notes
    _, a = _parked("alpha")
    for t in (UVM, "uvm_info macro for messages please, no $display",
              "Messages: the uvm_info macro, not $display!"):
        notes.add(a, t, "me")
    [g] = [g for g in learn.groups(learn.corrections()) if len(g["items"]) > 1]
    assert len(g["items"]) == 3 and g["projects"] == ["alpha"]
    assert len(learn.proposals()) == 1
    assert len(learn.maybe_propose(now=10 ** 9)) == 1
    assert learn.maybe_propose(now=10 ** 9 + 60) is None          # an hour apart


def test_keep_it_writes_agent_md(fake, tmp_path):
    from work_packet import inbox, learn, notes, project
    h = registry.home()
    e, a = _parked("alpha")
    _, b = _parked("beta")
    open(learn.agent_md(e["path"]), "w").write("# Notes\n\nKeep the seed at 7.\n")
    notes.add(a, UVM, "me")
    notes.add(b, UVM, "me")
    [it] = learn.propose(h)
    c = _client()
    page = c.get("/backlog").text
    assert "Keep it" in page and "/learn/%s" % it["id"] in page
    page = c.get("/learn/%s" % it["id"]).text
    assert "2 times" in page and 'value="alpha" checked' in page
    r = c.post("/learn/%s" % it["id"], data={"rule": "Use uvm_info, never $display.",
                                             "project": ["alpha"]}, follow_redirects=False)
    msg, ok = _flash(r)
    assert ok and "alpha" in msg, msg
    text = open(learn.agent_md(e["path"])).read()
    assert text == "# Notes\n\nKeep the seed at 7.\n\n## Learned\n\n- Use uvm_info, never $display.\n"
    assert inbox.get(h, it["id"]) is None
    learn.add_rule(e["path"], "Run the lint first.")
    assert open(learn.agent_md(e["path"])).read().endswith(
        "- Use uvm_info, never $display.\n- Run the lint first.\n")
    assert learn.add_rule(e["path"], "Run the lint first.") is False
    # the next step reads it
    assert "Run the lint first." in open(project.settings(e["path"]).agent_md).read()
    assert c.get("/learn/nope00000000").status_code == 404
    r = c.post("/learn/%s" % it["id"], data={"rule": "x", "project": ["alpha"]},
               follow_redirects=False)
    assert not _flash(r)[1]


def test_a_kept_rule_reaches_the_step_prompt(fake):
    from work_packet import learn
    e, pkt = _new("ruled")
    learn.add_rule(e["path"], "Always sign your commits.")
    scheduler.tick([e], until_idle=True)
    sd = os.path.join(pkt.path, "steps", "0001")
    assert "Always sign your commits." in open(os.path.join(sd, "prompt.md")).read()


# --- C7d: split -------------------------------------------------------------------------

from test_setup import git, home, source                       # noqa: E402,F401


def _packet(folder, name="dv"):
    from work_packet import project
    project.new(name, "Count in state/count.md.", path=str(folder), packet=True)
    e = registry.get(name)
    scheduler.tick([e], until_idle=True)                       # it ran once: COMPLETED
    return e


def _run(name):
    scheduler.tick([registry.get(name)], until_idle=True)


def test_a_split_leaves_your_folder_alone(home, source):
    from work_packet import split
    e = _packet(source)
    (source / "README.md").write_text("my edit, not committed\n")
    name = split.make(e, "Add a NOTES file.")
    assert name == "dv-split"
    s = registry.get(name)
    tree = os.path.join(home, "splits", "dv-split")
    assert split.info(s)["of"] == "dv" and split.info(s)["branch"] == "wpk/dv-split"
    assert open(os.path.join(tree, "README.md")).read() == "dv-solve\n"     # from HEAD
    assert (source / "README.md").read_text() == "my edit, not committed\n"
    assert git(tree, "status", "--porcelain") == ""             # its .work-packet is hidden
    assert any(r.get("type") == "split" for r in _journal_of(e))
    with pytest.raises(split.SplitError, match="pause it first|running"):
        split.land(s)
    _run(name)
    # the runner's work (as a step would leave it)
    open(os.path.join(tree, "NOTES.md"), "w").write("notes\n")
    d = split.diff(s)
    assert d["untracked"] == ["NOTES.md"] and d["commits"] == []
    msg = split.land(s)
    assert "fast-forwarded" in msg
    assert (source / "NOTES.md").read_text() == "notes\n"
    assert (source / "README.md").read_text() == "my edit, not committed\n"   # still yours
    assert views.lifecycle(_root_meta(s)) == "done"
    assert split.make(e, "Again.") == "dv-split2"


def _journal_of(e):
    from work_packet.hookcmd import _root
    from work_packet.packet import Packet
    from work_packet import layout
    return Packet(layout.run_dir(e["path"], _root(e["path"]))).journal().records


def _root_meta(e):
    from work_packet.hookcmd import _root
    from work_packet.packet import Packet
    from work_packet import layout
    return Packet(layout.run_dir(e["path"], _root(e["path"]))).load_status()[0]


def test_land_merges_and_refuses_over_your_edits(home, source):
    from work_packet import split
    e = _packet(source)
    s = registry.get(split.make(e, "Change the README."))
    _run(s["name"])
    tree = os.path.join(home, "splits", s["name"])
    open(os.path.join(tree, "README.md"), "w").write("the runner's README\n")
    # you edit the same file, uncommitted: git refuses, nothing changes
    (source / "README.md").write_text("mine\n")
    (source / "other.txt").write_text("x\n")
    git(source, "add", "other.txt")
    git(source, "commit", "-q", "-m", "mine")
    with pytest.raises(split.SplitError, match="would not merge"):
        split.land(s)
    assert (source / "README.md").read_text() == "mine\n"
    assert views.lifecycle(_root_meta(s)) == "open"
    # commit yours elsewhere, drop the edit: a merge commit
    git(source, "checkout", "--", "README.md")
    assert "merged wpk/dv-split" in split.land(s)
    assert (source / "README.md").read_text() == "the runner's README\n"
    assert len(git(source, "log", "-1", "--format=%P").split()) == 2


def test_split_from_the_board(home, source):
    from work_packet import executor, split
    e = _packet(source)
    c = _client()
    page = c.get("/p/dv/compose").text
    assert "Split: the runner works in a copy" in page
    r = c.post("/p/dv/compose", data={"action": "split", "instruction": "Write NOTES.md",
                                      "note": ""}, follow_redirects=False)
    msg, ok = _flash(r)
    assert ok and "dv-split" in msg, msg
    _run("dv-split")
    tree = os.path.join(home, "splits", "dv-split")
    open(os.path.join(tree, "NOTES.md"), "w").write("n\n")
    page = c.get("/p/dv-split").text
    assert 'id="split"' in page and "NOTES.md" in page and "Bring it into dv" in page
    assert "dv-split" in c.get("/p/dv").text
    r = c.post("/p/dv-split/split", data={"op": "land"}, follow_redirects=False)
    msg, ok = _flash(r)
    assert ok and "fast-forwarded" in msg, msg
    assert (source / "NOTES.md").exists()
    r = c.post("/p/dv-split/split", data={"op": "land"}, follow_redirects=False)
    msg, ok = _flash(r)
    assert not ok and "done already" in msg


def test_what_cannot_be_split(fake):
    from work_packet import split
    e, _ = _parked("legacy")
    assert "work/" in split.allowed(e)
    assert "Split: the runner" not in _client().get("/p/legacy/compose").text


def test_the_new_journal_records_validate(home, source):
    from work_packet import schema, split
    e = _packet(source)
    d = jobs.start(e["path"], ["make", "sim"], e["path"])
    jobs.end(e["path"], d, 1)
    split.make(e, "Do it in a copy.")
    recs = [r for r in _journal_of(e) if r["type"] in ("job-start", "job-end", "split")]
    assert sorted(r["type"] for r in recs) == ["job-end", "job-start", "split"]
    assert not [p for r in recs for p in schema.validate_journal_record(r) if p.level == "error"]
    texts = [ev["text"] for ev in views.timeline(_pkt_of(e))]
    assert "make sim failed (exit 1)" in texts and "started make sim" in texts
    assert any(t.startswith("split it: dv-split") for t in texts)


def _pkt_of(e):
    from work_packet.hookcmd import _root
    from work_packet.packet import Packet
    from work_packet import layout
    return Packet(layout.run_dir(e["path"], _root(e["path"])))
