"""Attention delivery and triage (docs/collaboration.md §4.3, §7.6, W8; plan C6):
pushes to ntfy, the digest, the review budget, Settings, and the Inbox's sources
and actions."""

import http.server
import os
import threading
import time

import pytest

from test_dash_tasks import _client, _flash, _new
from work_packet import (executor, inbox, notify, presence, registry, scheduler,
                         settings)
from work_packet.dash import data


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # project.new puts projects in the cwd


def _home():
    return registry.home()


class _Sent:
    def __init__(self):
        self.calls = []

    def __call__(self, cfg, title, body, click=None, priority=None, tags=None):
        self.calls.append({"title": title, "body": body, "click": click})


CFG = {"ntfy_url": "https://ntfy.example/t", "question_after_s": 0}


def _asking(fake, name="asking"):
    fake("asker")
    e, pkt = _new(name)
    scheduler.tick([e], until_idle=True)
    fake("add_one")
    return e, pkt


def test_a_question_pushes_once(fake):
    _asking(fake)
    sent = _Sent()
    cols, _ = data.board()
    r = notify.tick(_home(), cols, dict(CFG, link="https://board.example"), send=sent)
    assert len(r["pushed"]) == 1 and sent.calls[0]["title"] == "asking asks you"
    assert "colour" in sent.calls[0]["body"]
    assert sent.calls[0]["click"] == "https://board.example/p/asking"
    assert notify.tick(_home(), cols, CFG, send=sent)["pushed"] == []      # once
    assert len(sent.calls) == 1


def test_nothing_without_a_topic_or_when_snoozed_or_seen(fake):
    _asking(fake)
    sent = _Sent()
    cols, _ = data.board()
    assert notify.tick(_home(), cols, {}, send=sent)["pushed"] == []
    [it] = notify.items(cols)
    assert notify.tick(_home(), cols, CFG, snoozed={it["key"]}, send=sent)["pushed"] == []
    assert not notify.pushable(it, notify.config({"question_after_s": 10 ** 10}), time.time())
    assert not notify.pushable(dict(it, seen=True), notify.config(CFG), time.time())
    assert sent.calls == []


def test_a_visible_tab_holds_the_push(fake):
    e, _ = _asking(fake)
    presence.beat(e["path"], "ide-web-k-t1", time.time(), kind="ide-web", visible=True)
    cols, _ = data.board()
    assert not [it for it in notify.items(cols) if notify.pushable(it, notify.config(CFG),
                                                                   time.time())]


def test_rate_limit_then_digest(fake):
    for n in ("q1", "q2", "q3"):
        _asking(fake, n)
    sent = _Sent()
    cols, _ = data.board()
    r = notify.tick(_home(), cols, dict(CFG, max_per_hour=2, digest="hourly"), send=sent)
    assert len(r["pushed"]) == 2 and len(r["queued"]) == 1
    # the digest goes out (hourly, first time) with the one held back
    assert r["digest"] == 1 and "wpk: 1 waiting" in sent.calls[-1]["title"]
    s = notify.load_state(_home())
    assert s["digest"] == [] and len(s["log"]) == 2


def test_review_goes_to_the_digest_only(fake):
    e, pkt = _new("finished")
    scheduler.tick([e], until_idle=True)
    cols, _ = data.board()
    its = notify.items(cols)
    assert [i["type"] for i in its if i["project"] == "finished"] == ["review"]
    sent = _Sent()
    t = time.time()
    r = notify.tick(_home(), cols, dict(CFG, digest="daily", digest_at="00:00"), send=sent,
                    now=t)
    assert r["pushed"] == []
    assert r["digest"] == 1 and "finished (review)" in sent.calls[0]["body"]


def test_post_to_a_fake_ntfy():
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            got.append((self.path, dict(self.headers), self.rfile.read(n).decode()))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        url = "http://127.0.0.1:%d/mytopic" % srv.server_port
        notify.post({"ntfy_url": url, "ntfy_token": "tk"}, "a: Claude is blocked", "Bash",
                    click="https://b/p/a", priority=4, tags=["bell"])
        path, h, body = got[0]
        assert path == "/mytopic" and body == "Bash" and h["Title"] == "a: Claude is blocked"
        assert h["Authorization"] == "Bearer tk" and h["Click"] == "https://b/p/a"
        with pytest.raises(notify.NotifyError):
            notify.post({"ntfy_url": "http://127.0.0.1:1/x"}, "t", "b")
    finally:
        srv.shutdown()


# --- Settings ---------------------------------------------------------------------------

def test_settings_edit_keeps_your_comments(tmp_path):
    text = "# mine\nmodel = \"m\"  # keep\n\n[ide]\n# the TTL\npresence_ttl = 300\n\n[sched]\nx = 1\n"
    got = settings.edit(text, {("ide", "presence_ttl"): 120, ("ide", "idle_escalate"): 60,
                               ("notify", "ntfy_url"): "https://n/t"})
    assert "# mine" in got and "# the TTL" in got and "model = \"m\"  # keep" in got
    assert "presence_ttl = 120\nidle_escalate = 60\n\n[sched]" in got
    assert got.rstrip().endswith('[notify]\nntfy_url = "https://n/t"')
    assert "presence_ttl" not in settings.edit(got, {("ide", "presence_ttl"): None})


def test_settings_save_validates(fake):
    p = settings.path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("# my config\n")
    assert settings.save({("focus", "time"): "07:45", ("plan", "review_wip"): 5}) == \
        ["focus.time"]                                       # 5 is the default: not written
    assert "# my config" in open(p).read() and 'time = "07:45"' in open(p).read()
    with pytest.raises(settings.SettingsError, match="HH:MM"):
        settings.save({("focus", "time"): "soon"})
    with pytest.raises(settings.SettingsError, match="http"):
        settings.save({("notify", "ntfy_url"): "ntfy.sh/x"})
    assert settings.save({("focus", "time"): "08:30"}) == ["focus.time"]   # back to default
    assert "time" not in open(p).read()


def test_settings_page(fake):
    c = _client()
    page = c.get("/settings").text
    assert "Pushes (ntfy)" in page and 'name="notify.ntfy_url"' in page and "Turn on" in page
    form = {"focus.time": "09:00", "plan.review_wip": "2", "notify.digest": "daily",
            "notify.ntfy_token": ""}
    r = c.post("/settings", data=form, follow_redirects=False)
    msg, ok = _flash(r)
    assert ok and "focus.time" in msg and "plan.review_wip" in msg
    cfg = registry.load_config_file()
    assert cfg["focus"]["time"] == "09:00" and cfg["notify"]["digest"] == "daily"
    assert "ntfy_token" not in cfg.get("notify", {})
    r = c.post("/settings", data={"ide.presence_ttl": "x"}, follow_redirects=False)
    assert not _flash(r)[1]
    r = c.post("/settings/test-push", follow_redirects=False)
    assert not _flash(r)[1] and "ntfy_url" in _flash(r)[0]


def test_attention_json_and_the_review_budget(fake):
    _asking(fake)
    c = _client()
    open(settings.path(), "a").write("\n[notify]\nquestion_after_s = 0\n")
    d = c.get("/attention.json").json()
    assert [i["title"] for i in d["items"]] == ["asking asks you"]
    # two finished, unread: over a limit of 2, the hand-off form says so
    for n in ("r1", "r2"):
        e, _ = _new(n)
        scheduler.tick([e], until_idle=True)
    assert data.review_load()["n"] == 2
    e, pkt = _new("more")
    executor.admin(pkt, "pause")
    assert "for your review" not in c.get("/p/more/compose").text
    settings.save({("plan", "review_wip"): 2})
    assert "2 finished projects wait for your review" in c.get("/p/more/compose").text
    assert "over your limit of 2" in c.get("/").text


# --- the Inbox --------------------------------------------------------------------------

def test_follow_ups_from_a_memento(fake):
    fake("proposer")
    e, pkt = _new("finder")
    scheduler.tick([e], until_idle=True)
    its = [d for d in inbox.items(_home()) if d.get("source") == "agent"]
    assert sorted(d["text"] for d in its) == ["Remove the unused seed table",
                                              "The DMA wrap test also fails on 32-bit bursts"]
    assert all(d["project"] == "finder" and d["ref"]["wpid"] == pkt.wpid for d in its)
    # the same step again (a redone commit) writes the same items
    inbox.follow_ups(_home(), pkt, {"follow_ups": ["x"]}, "finder", step=1)
    inbox.follow_ups(_home(), pkt, {"follow_ups": ["x"]}, "finder", step=1)
    assert len([d for d in inbox.items(_home()) if d["text"] == "x"]) == 1


def test_bad_follow_ups_are_refused():
    from work_packet import schema
    bad = [p.field for p in schema.validate_memento({"resume": "done", "follow_ups": "x" * 9}, "")
           if p.level == "error"]
    assert bad == ["follow_ups"]
    assert not [p for p in schema.validate_memento(
        {"resume": "done", "follow_ups": ["a", "b"]}, "") if p.level == "error"]


def test_snooze_merge_and_duplicates(fake):
    e, pkt = _new("dma-wrap-fix", prompt="Fix the DMA wrap bug in burst transfers")
    executor.admin(pkt, "pause")
    h = _home()
    a = inbox.add(h, "DMA wrap bug also in burst transfers of 32 bits", source="board")
    b = inbox.add(h, "tidy the seed table", source="board")
    c = _client()
    page = c.get("/backlog").text
    assert "looks like" in page and "dma-wrap-fix" in page
    r = c.post("/inbox/%s/snooze" % b["id"], data={"until": "tomorrow", "back": "/backlog"},
               follow_redirects=False)
    assert _flash(r)[1] and [d["id"] for d in inbox.items(h)] == [a["id"]]
    assert inbox.get(h, b["id"])["until"] > time.time()
    r = c.post("/inbox/%s/merge" % a["id"], data={"project": "dma-wrap-fix"},
               follow_redirects=False)
    msg, ok = _flash(r)
    assert ok and "note" in msg and inbox.get(h, a["id"]) is None
    from work_packet import notes
    assert any("32 bits" in n["text"] for n in notes.queued(pkt))
    r = c.post("/inbox/%s/merge" % b["id"], data={"project": "nope"}, follow_redirects=False)
    assert not _flash(r)[1]


def test_a_proposing_watcher(fake, tmp_path, monkeypatch):
    from work_packet import watch
    w = {"board": "main", "name": "w", "repos": ["home:o/r"], "dir": str(tmp_path / "pk"),
         "propose": True}

    class F:
        def issues(self, repo, query, limit=50, labels=()):
            return [{"number": 7, "title": "Flaky seed", "url": "https://f/o/r/7",
                     "labels": []}]
    from work_packet import forges
    monkeypatch.setattr(forges, "get", lambda name, h=None: F())
    r = watch.poll(w)
    assert r["proposed"] == ["home:o/r#7"] and r["made"] == []
    [d] = [d for d in inbox.items(_home()) if d.get("source") == "watch"]
    assert d["text"] == "Flaky seed (home:o/r#7)" and d["ref"]["key"] == "home:o/r#7"
    assert watch.poll(w)["proposed"] == []                 # seen: not again
    page = _client().get("/b/main").text
    assert "Flaky seed" in page and "from a watcher" in page
