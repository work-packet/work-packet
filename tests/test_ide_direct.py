"""One VS Code server per desk, found or started by wpkd (docs/ide-direct-server-plan.md)."""

import socket

import pytest

from work_packet import ide_launch, ide_stranded, schema
from work_packet.dash import ide as dide

from test_ide import short_home  # noqa: E402,F401
from test_setup import source  # noqa: E402,F401

KEY = "0123456789ab"
C1, C2 = "1" * 40, "2" * 40


@pytest.fixture
def home():
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="wpk-d")       # short: sockets must fit in sun_path
    yield d
    shutil.rmtree(d, ignore_errors=True)


def backend(home):
    be = dide.Backend(home, dict(schema.IDE_DEFAULTS, web=True), KEY)
    dide.private_dirs(home, KEY)
    return be


def listener(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path)
    s.listen(4)
    return s


def live(monkeypatch, servers, agents=None):
    monkeypatch.setattr(ide_stranded, "servers", lambda key: [dict(s) for s in servers])
    monkeypatch.setattr(ide_stranded, "agents_under",
                        lambda pid, kids=None: (agents or {}).get(pid, 0))


def test_takes_the_server_with_agents_past_serve_web(home, monkeypatch):
    be = backend(home)
    old = listener(home + "/old.sock")
    new = listener(home + "/new.sock")
    try:
        lid = ide_launch.start(home, KEY, "/w/x", "local")
        live(monkeypatch, [
            {"pid": 10, "commit": C1, "start": 1, "launch": lid, "socket": home + "/old.sock"},
            {"pid": 20, "commit": C2, "start": 2, "launch": lid, "socket": home + "/new.sock"},
            {"pid": 30, "commit": C2, "start": 3, "launch": lid, "socket": home + "/gone.sock"},
        ], agents={10: 1})
        assert be._adopt()
        assert be.sock == home + "/old.sock" and be.proc == 10 and be.server_pid == 10
        cur = ide_launch.current(home, KEY)
        assert cur["launch_id"] == lid and cur["server_pid"] == 10
        assert cur["release"] == "stable-" + C1
    finally:
        old.close()
        new.close()


def test_a_server_of_no_launch_gets_one(home, monkeypatch):
    be = backend(home)
    srv = listener(home + "/s.sock")
    try:
        live(monkeypatch, [{"pid": 10, "commit": C1, "start": 1, "launch": "L-old",
                            "socket": home + "/s.sock"}])
        assert be._adopt()
        cur = ide_launch.current(home, KEY)
        assert cur["adopted"] and cur["server_pid"] == 10 and cur["release"] == "stable-" + C1
    finally:
        srv.close()


def test_a_server_that_does_not_answer_is_never_doubled(home, monkeypatch):
    be = backend(home)
    live(monkeypatch, [{"pid": 10, "commit": C1, "start": 1, "launch": None,
                        "socket": home + "/none.sock"}])
    started = []
    monkeypatch.setattr(be, "_start", lambda: started.append(1))
    with pytest.raises(dide.IdeStuck) as e:
        be._start_one()
    assert e.value.pids == [10] and started == []


def test_none_running_starts_one(home, monkeypatch):
    be = backend(home)
    live(monkeypatch, [])
    started = []
    monkeypatch.setattr(be, "_start", lambda: started.append(1))
    be._start_one()
    assert started == [1]


def test_stranded_keeps_the_server_in_use(monkeypatch):
    srv = [{"pid": 10, "commit": C1, "start": 1, "launch": "L-a"},
           {"pid": 20, "commit": C2, "start": 2, "launch": "L-a"}]
    monkeypatch.setattr(ide_stranded, "servers", lambda key: [dict(s) for s in srv])
    got = ide_stranded.stranded(KEY, "stable-" + C2, kids={}, keep_pid=10)
    assert [s["pid"] for s in got] == [20]


def test_a_packets_old_desk_keeps_serving_until_it_stops(home, monkeypatch):
    w = "1234abcd-0000-4000-8000-000000000000"
    old = dide.key_for("/p/.vscode/packet.code-workspace")
    dide.private_dirs(home, old)
    ide_launch.record_open(home, old, "p", w, "me")
    running = {old: [{"pid": 10, "commit": C1, "start": 1, "launch": "L-a", "socket": "/s"}]}
    monkeypatch.setattr(ide_stranded, "servers", lambda key: running.get(key, []))
    monkeypatch.setattr(ide_stranded, "agents_under", lambda pid, kids=None: 1)
    bs = dide.Backends(home, dict(schema.IDE_DEFAULTS, web=True))
    assert bs.register("/p/work/repo", None, "p", w) == old
    running.clear()                                         # it stopped
    assert bs.register("/p/work/repo", None, "p", w) == dide.key_for_packet(w)


def test_a_stuck_server_gets_a_page_that_ends_it(tmp_path, monkeypatch):
    import tempfile
    from test_ide import _web_client
    h = tempfile.mkdtemp(prefix="wpk-d")
    monkeypatch.setenv("WPK_HOME", h)
    c, be, origin, tok = _web_client(h, tmp_path)
    try:
        async def stuck():
            raise dide.IdeStuck("VS Code's server for this desk (pid 10) is running but "
                                "does not answer", [10])
        monkeypatch.setattr(be, "ensure", stuck)
        ended = []
        monkeypatch.setattr(be, "end", lambda: ended.append(1))
        r = c.get("/ide/%s/?folder=/x" % be.key)
        assert r.status_code == 503 and "does not answer" in r.text
        assert 'action="/ide/%s/__wpk/restart"' % be.key in r.text
        r = c.post("/ide/%s/__wpk/restart" % be.key, headers=origin,
                   data={"back": "/ide/%s/?folder=/x" % be.key}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/ide/%s/?folder=/x" % be.key
        assert ended == [1]
        # never a way off the desk
        r = c.post("/ide/%s/__wpk/restart" % be.key, headers=origin,
                   data={"back": "https://evil/"}, follow_redirects=False)
        assert r.headers["location"] == "/ide/%s/" % be.key
        assert c.post("/ide/%s/__wpk/restart" % be.key, data={}).status_code == 403   # Origin
    finally:
        c.__exit__(None, None, None)
        import shutil
        shutil.rmtree(h, ignore_errors=True)


def test_getting_a_release_shows_its_own_page(home, monkeypatch):
    from work_packet import ide_releases
    be = backend(home)
    monkeypatch.setattr(ide_releases, "seed", lambda *a, **k: None)
    got = []
    monkeypatch.setattr(ide_releases, "start_get", lambda *a, **k: got.append(1))
    with pytest.raises(dide.IdeGetting, match="getting VS Code's server"):
        be._release()
    assert got == [1]


def test_desk_view_names_the_update_and_what_a_restart_ends(home, monkeypatch):
    from test_ide_releases import unpacked
    from work_packet import ide_releases
    w = "1234abcd-0000-4000-8000-000000000000"
    key = dide.key_for_packet(w)
    unpacked(ide_releases.path(home, C1), C1, "1.146.0")
    cfg = dict(schema.IDE_DEFAULTS, web=True)
    monkeypatch.setattr(ide_stranded, "servers", lambda k: [
        {"pid": 10, "commit": C1, "start": 1, "launch": "L-a", "socket": "/s"}] if k == key else [])
    monkeypatch.setattr(ide_stranded, "desk_keys", lambda h, wpid: [])
    monkeypatch.setattr(ide_stranded, "inside", lambda pid, kids=None: {
        "agents": [{"pid": 11, "argv": "claude", "since": 1.0}], "terminals": 2})
    monkeypatch.setattr(ide_stranded, "started_at", lambda pid: 5.0)
    v = dide.desk_view(home, cfg, w)
    assert (v["key"], v["pid"], v["version"], v["newer"], v["terminals"]) == \
        (key, 10, "1.146.0", None, 2)
    unpacked(ide_releases.path(home, C2), C2, "1.147.0")
    assert dide.desk_view(home, cfg, w)["newer"] == "1.147.0"
    assert dide.desk_view(home, dict(cfg, backend="openvscode-server"), w) is None


def test_releases_kept_are_the_current_and_the_running(home, monkeypatch):
    from work_packet import ide_releases
    bs = dide.Backends(home, dict(schema.IDE_DEFAULTS, web=True, release="1.146.0"))
    monkeypatch.setattr(ide_releases, "check", lambda h: pytest.fail("held: no check"))
    monkeypatch.setattr(ide_releases, "current", lambda h, cfg: {"commit": C2})
    monkeypatch.setattr(ide_stranded, "all_servers", lambda: [{"pid": 1, "commit": C1,
                                                                 "key": KEY}])
    kept = []
    monkeypatch.setattr(ide_releases, "gc", lambda h, keep: kept.append(keep) or [])
    bs.update_releases()
    assert kept == [{C1, C2}]


def test_packet_page_shows_the_desk_and_restarts_it(short_home, tmp_path, monkeypatch, source):
    from test_ide import _web_client
    from test_workspace import setup_root
    monkeypatch.chdir(tmp_path)
    proj, pkt = setup_root(tmp_path, source)
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        view = {"key": be.key, "pid": 10, "commit": C1, "version": "1.146.0",
                "newer": "1.147.0", "started": None, "terminals": 2,
                "agents": [{"pid": 11, "argv": "claude --x", "since": None}]}
        monkeypatch.setattr(dide, "desk_view", lambda h, cfg, wpid: dict(view))
        page = c.get("/p/dvs/%s" % pkt.wpid).text
        assert "VS Code 1.146.0" in page and "VS Code 1.147.0 is ready" in page
        assert "Restarting now ends 2 terminals, <span" in page and "claude (pid 11)" in page
        assert 'data-confirm="Restarting VS Code ends 1 agent session' in page
        done = []

        async def restart(key):
            done.append(key)
            view["version"], view["newer"] = "1.147.0", None
        monkeypatch.setattr(be.mgr, "restart", restart)
        r = c.post("/p/dvs/%s/act" % pkt.wpid, headers=origin,
                   data={"csrf": tok, "action": "ide-restart", "key": be.key})
        assert r.status_code == 200 and done == [be.key]
        assert "restarted VS Code on 1.147.0" in r.text
        r = c.post("/p/dvs/%s/act" % pkt.wpid, headers=origin,
                   data={"csrf": tok, "action": "ide-restart", "key": "ffffffffffff"})
        assert done == [be.key]                                  # not this packet's
    finally:
        c.__exit__(None, None, None)


def test_idle_stop_spares_a_desk_with_agents(home, monkeypatch):
    be = backend(home)
    monkeypatch.setattr(ide_stranded, "servers", lambda key: [{"pid": 10}])
    monkeypatch.setattr(ide_stranded, "agents_under", lambda pid, kids=None: 1)
    assert be._busy()
    monkeypatch.setattr(ide_stranded, "agents_under", lambda pid, kids=None: 0)
    assert not be._busy()
    fake = dide.Backend(home, dict(schema.IDE_DEFAULTS), KEY, argv=["x"])
    assert not fake._busy()                     # not VS Code's own server: not scanned


def test_a_job_host_runs_its_own_platforms_build(tmp_path, monkeypatch):
    from work_packet import ide_releases
    from work_packet.sched import ide_job
    home = str(tmp_path)
    prog = ide_releases.binary(home, C1, dide.PLATFORM)
    assert "/releases/{platform}/" in prog
    got = []
    monkeypatch.setattr(ide_releases, "install", lambda h, c, p: got.append((h, c, p)))
    out = ide_job.for_this_host(home, ["xproxy", "--", prog, "--port", "1"])
    assert out[2] == ide_releases.binary(home, C1, ide_releases.platform())
    assert got == [(home, C1, ide_releases.platform())]
    assert ide_job.for_this_host(home, ["a", "b"]) == ["a", "b"]
