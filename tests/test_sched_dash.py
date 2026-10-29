"""The scheduler on the board (docs/scheduler.md §9; plan Q3)."""

import json
import os
import socket

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402

from work_packet import project, registry  # noqa: E402
from work_packet.cli import main  # noqa: E402
from work_packet.dash.app import create_app  # noqa: E402
from work_packet.packet import Packet  # noqa: E402
from work_packet.sched import authz, control, events, jobs  # noqa: E402
from work_packet.tomlio import load_toml  # noqa: E402

WHO = "tailscale:alice@example.com"


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return os.environ["WPK_HOME"]


def new(name):
    plan = project.new(name, "Read state/count.md (0 if missing), add one.")
    return plan, Packet(os.path.join(plan.path, "packets", plan.root))


def as_user(app, user="alice@example.com", listener="tailnet"):
    """What the Guard does: put the caller's identity in the scope."""
    async def wrapped(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope.setdefault("state", {}).update(user=user, listener=listener)
        await app(scope, receive, send)
    return wrapped


def client(home, **kw):
    return TestClient(as_user(create_app(home), **kw))


def post(c, url, **data):
    return c.post(url, data=data, follow_redirects=False)


def flash(r):
    from urllib.parse import parse_qs, urlsplit
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return q.get("msg", [""])[0], q.get("ok", ["0"])[0] == "1"


def last(home, type):
    return [e for e in events.read(home) if e["type"] == type][-1]


def test_sched_page_and_json_match_the_cli(home, capsys):
    _, a = new("aaa")
    new("bbb")
    control.set_prio("bbb", "high", authz.principal_cli())
    c = client(home)
    r = c.get("/sched")
    assert r.status_code == 200
    assert "Queue" in r.text and "starts next" in r.text and "Halt" in r.text
    got = c.get("/sched.json").json()
    assert main(["sched", "--json"]) == 0
    cli = json.loads(capsys.readouterr().out)
    assert [(q["project"], q["class"], q["why"]) for q in got["queue"]] == \
        [(q["project"], q["class"], q["why"]) for q in cli["queue"]]
    assert got["queue"][0]["project"] == "bbb"
    assert "Scheduler" in c.get("/").text                         # the side tab


def test_halt_resume_and_the_banner(home):
    new("aaa")
    c = client(home)
    r = post(c, "/sched/mode", mode="halt", reason="lunch")
    assert r.status_code == 303 and flash(r)[1]
    d = load_toml(control.control_path(home))
    assert (d["mode"], d["by"], d["reason"]) == ("drain", WHO, "lunch")
    assert last(home, "mode")["by"] == WHO
    for url in ("/", "/packets", "/p/aaa", "/sched"):
        page = c.get(url).text
        assert "Pool halted" in page and "lunch" in page, url
    assert "Resume" in c.get("/sched").text
    post(c, "/sched/mode", mode="resume")
    assert control.read_mode(home)["mode"] == "run"
    assert "Pool halted" not in c.get("/").text


def test_stop_needs_a_reason(home):
    c = client(home)
    msg, ok = flash(post(c, "/sched/mode", mode="stop"))
    assert not ok and "needs a reason" in msg
    assert control.read_mode(home)["mode"] == "run"
    msg, ok = flash(post(c, "/sched/mode", mode="stop", reason="bill"))
    assert ok and control.read_mode(home)["mode"] == "stop"
    assert "Pool stopped" in c.get("/").text


def test_posts_do_what_the_cli_does(home):
    _, a = new("aaa")
    c = client(home)
    assert flash(post(c, "/p/aaa/prio", value="high"))[1]
    assert flash(post(c, "/p/aaa/size", value="look"))[1]
    assert flash(post(c, "/p/aaa/%s/prio" % a.wpid, value="urgent"))[1]
    assert flash(post(c, "/p/aaa/%s/next" % a.wpid))[1]
    e = registry.get("aaa")
    assert (e["priority"], e["size"]) == ("high", "look")
    assert e["packets"][a.wpid] == {"priority": "urgent", "next": True}
    for t in ("prio", "size", "next"):
        assert last(home, t)["by"] == WHO
    assert flash(post(c, "/p/aaa/hold", reason="not this week"))[1]
    assert registry.get("aaa")["sched"] == "hold" and registry.get("aaa")["sched_by"] == WHO
    assert flash(post(c, "/p/aaa/hold", value="release"))[1]
    assert "sched" not in registry.get("aaa")
    assert flash(post(c, "/p/aaa/%s/prio" % a.wpid))[1]                # empty value clears
    msg, ok = flash(post(c, "/p/aaa/prio", value="asap"))
    assert not ok and "class must be one of" in msg
    assert post(c, "/p/nope/prio", value="high").status_code == 404
    assert post(c, "/p/aaa/%s/hold" % a.wpid).status_code == 405       # no packet hold


def test_pages_show_class_size_and_why(home):
    _, a = new("aaa")
    c = client(home)
    control.set_prio(a.wpid, "low", authz.principal_cli())
    page = c.get("/p/aaa/%s" % a.wpid).text
    assert "Scheduling" in page and "low" in page and "Starts next" in page
    page = c.get("/p/aaa/settings").text
    assert "Scheduling" in page and "Hold" in page
    control.hold("aaa", authz.principal_cli())
    page = c.get("/p/aaa/%s" % a.wpid).text
    assert "project on hold by" in page
    page = c.get("/packets").text
    assert "project on hold by" in page and 'name="pick"' in page
    ov = c.get("/").text
    assert "cores in use" in ov or "jobs" in ov


def test_a_denied_principal_gets_403(home, monkeypatch):
    new("aaa")

    def deny(principal, action, target=None, h=None):
        raise authz.Denied("%s may not %s" % (principal, action))
    monkeypatch.setattr(authz, "check", deny)
    c = client(home)
    assert post(c, "/sched/mode", mode="halt").status_code == 403
    assert post(c, "/p/aaa/prio", value="high").status_code == 403
    assert control.read_mode(home)["mode"] == "run"
    assert "priority" not in registry.get("aaa")


def test_guard_refuses_without_token_or_from_another_origin(home):
    from work_packet.dash.guard import Guard, csrf_token
    new("aaa")
    secret = b"k" * 32
    import getpass
    me = getpass.getuser()                       # the loopback user is this home's owner
    g = Guard(create_app(home), "loopback", secret, local_user=me)
    c = TestClient(g, base_url="http://127.0.0.1:7878")
    ok_origin = {"origin": "http://127.0.0.1:7878"}
    r = c.post("/sched/mode", data={"mode": "halt"}, headers=ok_origin, follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/sched/mode", data={"mode": "halt", "csrf": csrf_token(secret)},
               headers={"origin": "http://evil.example"}, follow_redirects=False)
    assert r.status_code == 403
    assert control.read_mode(home)["mode"] == "run"
    r = c.post("/sched/mode", data={"mode": "halt", "csrf": csrf_token(secret)},
               headers=ok_origin, follow_redirects=False)
    assert r.status_code == 303
    d = load_toml(control.control_path(home))
    assert d["mode"] == "drain" and d["by"] == "unix:" + me
    g = Guard(create_app(home), "loopback", secret, local_user="mallory")
    r = TestClient(g, base_url="http://127.0.0.1:7878").post(
        "/sched/mode", data={"mode": "resume", "csrf": csrf_token(secret)}, headers=ok_origin,
        follow_redirects=False)
    assert r.status_code == 403                  # not the home's user: authz says no


def test_bulk_over_three_packets_one_leased(home):
    _, a = new("aaa")
    _, b = new("bbb")
    _, cc = new("ccc")
    with open(b.lease_path, "w") as fp:
        json.dump({"host": socket.gethostname(), "pid": os.getpid(), "step": 1,
                   "attempt": 1, "expires": "2999-01-01T00:00:00Z"}, fp)
    c = client(home)
    picks = ["aaa/%s" % a.wpid, "bbb/%s" % b.wpid, "ccc/%s" % cc.wpid]
    r = c.post("/packets/bulk", data={"op": "pause", "pick": picks}, follow_redirects=False)
    msg, ok = flash(r)
    lines = msg.splitlines()
    assert len(lines) == 3 and ok
    # bbb's step runs: it pauses when that step ends (docs/pause-v1.md).
    assert "RUNNABLE -> PAUSED" in lines[0] and "pause requested" in lines[1]
    assert a.load_status()[0]["state"] == "PAUSED" and b.load_status()[0]["state"] == "RUNNABLE"
    r = c.post("/packets/bulk", data={"op": "prio", "value": "low", "pick": picks},
               follow_redirects=False)
    assert flash(r)[1] and len(flash(r)[0].splitlines()) == 3
    assert registry.get("ccc")["packets"][cc.wpid]["priority"] == "low"
    r = c.post("/packets/bulk", data={"op": "hold", "pick": picks[:1] * 2},
               follow_redirects=False)
    assert len(flash(r)[0].splitlines()) == 1                 # one project, held once
    assert registry.get("aaa")["sched"] == "hold"
    r = c.post("/packets/bulk", data={"op": "pause"}, follow_redirects=False)
    assert "tick some packets" in flash(r)[0]


def test_budget_chart_renders(home, fake, monkeypatch):
    import tomli_w
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "config.toml"), "wb") as fp:
        tomli_w.dump({"sched": {"budget": {"measure": "usd", "amount": 10.0, "period": "day",
                                           "tz": "UTC"}}}, fp)
    _, a = new("aaa")
    monkeypatch.setenv("WPK_FAKE_COST", "0.5")
    from work_packet.sched.dispatcher import Dispatcher
    d = Dispatcher()
    d.pass_once()
    while jobs.all(home):
        d.reap()
    page = client(home).get("/sched").text
    assert '<svg class="bud"' in page and "c-normal" in page and "spent $0.50 of $10.00" in page
    ov = client(home).get("/").text
    assert "$0.50 of $10.00" in ov
