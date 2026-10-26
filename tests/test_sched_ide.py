"""An IDE in a slot (docs/scheduler.md §8; plan Q5, T-e)."""

import json
import os
import signal
import sys
import threading
import time
import urllib.request

import pytest
import tomli_w

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402

from work_packet import project, schema  # noqa: E402
from work_packet.packet import Packet  # noqa: E402
from work_packet.sched import authz, events, ide, jobs  # noqa: E402
from work_packet.sched.dispatcher import Dispatcher  # noqa: E402

FAKE_IDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_ide.py")
ME = authz.principal_cli()


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    import tempfile
    h = tempfile.mkdtemp(prefix="wpk-ide-")             # unix sockets want short paths
    monkeypatch.setenv("WPK_HOME", h)
    monkeypatch.chdir(tmp_path)
    yield h
    for r in jobs.all(h):
        if r.ref and r.backend == "local":
            try:
                os.killpg(int(r.ref.split(":")[0]), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, ValueError):
                pass


def config(h, **sched):
    sched.setdefault("ide", {}).setdefault("slot", True)
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "wb") as fp:
        tomli_w.dump({"ide": {"web": True}, "sched": sched}, fp)


def new(name):
    plan = project.new(name, "Read state/count.md (0 if missing), add one.")
    return plan, Packet(os.path.join(plan.path, "packets", plan.root))


def backends(h, tmp_path, poke=None):
    from work_packet.dash.ide import Backends
    cfg = dict(schema.IDE_DEFAULTS, web=True)
    return Backends(h, cfg, argv=[sys.executable, FAKE_IDE, str(tmp_path / "pids")], slot=True,
                    poke=poke)


def kinds(h):
    return sorted(r.kind for r in jobs.all(h))


# --- the queue (FakeLocal) ------------------------------------------------------------

def test_an_ide_jumps_the_queue(home, fakelocal):
    config(home, jobs=1)
    new("aaa")
    ide.request("k1", None, ["true"], ME, "/x", home)
    d = Dispatcher(backend=fakelocal)
    _, subs = d.pass_once()
    assert [s.kind for s in subs] == ["ide"]
    assert d.last_plan[1][[k for k in d.last_plan[1]][0]].code == "room"
    assert fakelocal.tasks()[0].argv == ["true"]


def test_an_ide_waits_without_preempting(home, fakelocal):
    config(home, jobs=1)
    _, a = new("aaa")
    d = Dispatcher(backend=fakelocal)
    _, subs = d.pass_once()
    fakelocal.start(subs[0].ref)
    new("bbb")
    ide.request("k1", None, ["true"], ME, "/x", home)
    assert d.pass_once()[1] == []
    assert fakelocal.cancelled == []                        # the running step goes on
    why = {k[0]: r.code for k, r in d.last_plan[1].items()}
    assert why == {"aaa": "job", "bbb": "ide"}              # bbb waits behind the IDE
    fakelocal.finish(subs[0].ref)
    _, subs = d.pass_once()
    assert [s.kind for s in subs] == ["ide"]


def test_the_reserve_is_kept_from_agents(home, fakelocal):
    config(home, cores=2, jobs=4, ide={"reserve": "look", "slot": True})
    new("aaa")
    new("bbb")
    d = Dispatcher(backend=fakelocal)
    _, subs = d.pass_once()
    assert len(subs) == 1                                   # 2 cores, 1 kept for an IDE
    ide.request("k1", None, ["true"], ME, "/x", home)
    _, subs = d.pass_once()
    assert [s.kind for s in subs] == ["ide"]                # the IDE gets it


def test_ide_jobs_ignore_halt_and_budget(home, fakelocal):
    from work_packet.sched import control
    config(home, budget={"measure": "usd", "amount": 0.0001, "period": "day"})
    new("aaa")
    control.set_mode("drain", ME)
    ide.request("k1", None, ["true"], ME, "/x", home)
    _, subs = Dispatcher(backend=fakelocal).pass_once()
    assert [s.kind for s in subs] == ["ide"]


def test_an_ended_ide_job_withdraws_its_request(home, fakelocal):
    config(home)
    ide.request("k1", None, ["true"], ME, "/x", home)
    d = Dispatcher(backend=fakelocal)
    _, subs = d.pass_once()
    fakelocal.start(subs[0].ref)
    d.pass_once()
    fakelocal.finish(subs[0].ref, 0)
    d.pass_once()
    assert ide.requests(home) == [] and jobs.all(home) == []
    assert d.pass_once()[1] == []                           # not restarted until opened


# --- end to end: the proxy over TCP with the token ------------------------------------

class Pool:
    """A dispatcher thread with the local backend, as in wpkd."""

    def __init__(self, h):
        self.d = Dispatcher(home=h)
        self.stop, self.poke = threading.Event(), threading.Event()
        self.t = threading.Thread(target=self.d.run, args=(self.stop, self.poke),
                                  kwargs={"max_wait": 2}, daemon=True)
        self.t.start()

    def close(self):
        self.stop.set()
        self.poke.set()
        self.t.join(30)


def get_until_up(c, url, timeout=30):
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        r = c.get(url)
        seen.append(r.status_code)
        if r.status_code == 200:
            return r, seen
        time.sleep(0.2)
    raise AssertionError("never up: %s %s" % (seen[-5:], r.text[:300]))


def test_proxy_to_a_job_with_the_token(home, tmp_path):
    from work_packet.dash.app import create_app
    config(home, jobs=2)
    pool = Pool(home)
    try:
        bs = backends(home, tmp_path, poke=pool.poke.set)
        key = bs.register("/x", size="look")
        c = TestClient(create_app(home, ide_backend=bs), base_url="http://127.0.0.1:7878")
        c.__enter__()
        r, seen = get_until_up(c, "/ide/%s/" % key)
        tok = open(os.path.join(home, "ide", "servers", key, "token")).read().strip()
        assert oct(os.stat(os.path.join(home, "ide", "servers", key, "token")).st_mode
                   & 0o777) == "0o600"
        echoed = json.loads(r.text.split('<pre id="seen">')[1].split("</pre>")[0])
        assert "vscode-tkn=%s" % tok in echoed["cookie"]
        assert "enableWorkspaceTrust&quot;:false" in r.text
        host, port = ide.endpoint(key, home)
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/ide/%s/" % (port, key), timeout=5)
            raise AssertionError("the server answered without its token")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        with c.websocket_connect("ws://127.0.0.1:7878/ide/%s/x" % key,
                                 headers={"origin": "http://127.0.0.1:7878"}) as ws:
            first = json.loads(ws.receive_text())
            assert "vscode-tkn=%s" % tok in first["cookie"]
            ws.send_text("hello")
            assert ws.receive_text() == "hello"
        assert kinds(home) == ["ide"]
        rec = jobs.all(home)[0]
        assert rec.size == "look"
        # A board restart re-attaches to the job through its endpoint file.
        c.__exit__(None, None, None)
        bs2 = backends(home, tmp_path, poke=pool.poke.set)
        c2 = TestClient(create_app(home, ide_backend=bs2), base_url="http://127.0.0.1:7878")
        with c2:
            assert c2.get("/ide/%s/" % key).status_code == 200
            assert [e for e in events.read(home) if e["type"] == "submitted"
                    and e.get("kind") == "ide"].__len__() == 1
            # Idle (or closed): the job is cancelled and its room freed.
            bs2.get(key)._stop_now()
            pool.poke.set()
            deadline = time.time() + 30
            while jobs.all(home) and time.time() < deadline:
                time.sleep(0.1)
            assert jobs.all(home) == [] and ide.endpoint(key, home) is None
    finally:
        pool.close()


def test_the_waiting_page_and_an_agent_taking_the_room(home, tmp_path, fake):
    """No room: the IDE page waits (503, refresh); an idle IDE's room goes to a step."""
    from work_packet.dash.app import create_app
    config(home, jobs=1)
    fake(fault="hang")
    _, a = new("aaa")
    pool = Pool(home)
    try:
        deadline = time.time() + 20
        while kinds(home) != ["step"] and time.time() < deadline:
            pool.poke.set()
            time.sleep(0.1)
        assert kinds(home) == ["step"]
        bs = backends(home, tmp_path, poke=pool.poke.set)
        key = bs.register("/y")
        with TestClient(create_app(home, ide_backend=bs)) as c:
            r = c.get("/ide/%s/" % key)
            assert r.status_code == 503 and "Waiting for room" in r.text
            assert 'http-equiv="refresh"' in r.text and "goes first in line" in r.text
        from work_packet.sched import control
        control.set_mode("stop", ME, "make room")           # the step ends: the IDE starts
        deadline = time.time() + 40
        while kinds(home) != ["ide"] and time.time() < deadline:
            time.sleep(0.2)
        assert kinds(home) == ["ide"]
        control.set_mode("run", ME)
        bs.get(key)._stop_now()                             # idle: the step gets the room
        deadline = time.time() + 40
        while kinds(home) != ["step"] and time.time() < deadline:
            pool.poke.set()
            time.sleep(0.2)
        assert kinds(home) == ["step"]
        control.set_mode("stop", ME, "test over")
    finally:
        pool.close()
