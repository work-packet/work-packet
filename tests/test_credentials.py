"""The credential store (design E3): put/get/status/mark/watch, modes."""
import datetime
import json
import os
import stat

import pytest

from work_packet import credentials as creds


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path))
    creds._reset()
    yield str(tmp_path)
    creds._reset()


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_put_get_modes(home):
    creds.put("gateway", {"token": "t1"}, subject="alice", expires=4102444800)
    d = os.path.join(home, "credentials")
    assert _mode(d) == 0o700
    assert _mode(os.path.join(d, "gateway.json")) == 0o600
    c = creds.get("gateway")
    assert c.data == {"token": "t1"} and c.subject == "alice"
    assert c.expires.startswith("2100-01-01T00:00:00")
    assert c.updated and c.mark is None
    assert creds.status("gateway") == "ok"
    assert creds.names() == ["gateway"]


def test_missing_and_bad_names(home):
    assert creds.get("nope") is None
    assert creds.status("nope") == "missing"
    assert creds.mark("nope", "invalid") is False
    for bad in ("../x", ".hidden", "a/b", ""):
        with pytest.raises(ValueError):
            creds.put(bad, {})
    with pytest.raises(TypeError):
        creds.put("x", "not a dict")


def test_dir_mode_repaired(home):
    d = os.path.join(home, "credentials")
    os.makedirs(d)
    os.chmod(d, 0o755)
    creds.put("g", {})
    assert _mode(d) == 0o700


def test_loose_file_invalid(home):
    creds.put("g", {"token": "t"})
    p = os.path.join(home, "credentials", "g.json")
    os.chmod(p, 0o644)
    assert creds.get("g") is None
    st, note = creds.check("g")
    assert st == "invalid" and "0600" in note


def test_garbage_invalid(home):
    creds.put("g", {})
    p = os.path.join(home, "credentials", "g.json")
    with open(p, "w") as fp:
        fp.write("{not json")
    assert creds.status("g") == "invalid"


def test_expired(home):
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    creds.put("g", {}, expires=past)
    assert creds.status("g") == "expired"
    creds.put("g", {}, expires="2100-01-01T00:00:00Z")
    assert creds.status("g") == "ok"


def test_mark_until_put(home):
    creds.put("g", {"token": "t"})
    assert creds.mark("g", "invalid", note="401 from portal")
    assert creds.check("g") == ("invalid", "401 from portal")
    assert creds.get("g").mark["status"] == "invalid"
    assert creds.mark("g", "ok")
    assert creds.status("g") == "ok"
    creds.mark("g", "expired")
    creds.put("g", {"token": "t2"})
    assert creds.status("g") == "ok"
    with pytest.raises(ValueError):
        creds.mark("g", "missing")


def test_rows(home):
    creds.put("a", {}, subject="alice")
    creds.put("b", {})
    creds.mark("b", "invalid", "401")
    rows = {r["name"]: r for r in creds.rows()}
    assert rows["a"]["status"] == "ok" and rows["a"]["subject"] == "alice"
    assert rows["b"]["status"] == "invalid" and rows["b"]["note"] == "401"
    assert "data" not in rows["a"]


def test_watch(home):
    seen = []
    creds.watch(seen.append)
    w = creds.watcher()
    assert w.poll() == []           # first poll: snapshot only
    creds.put("g", {"token": "t"})
    assert w.poll() == ["g"]
    assert w.poll() == []
    p = os.path.join(home, "credentials", "g.json")
    rec = json.load(open(p))
    rec["data"]["token"] = "t2"
    creds._write("g", rec)
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert w.poll() == ["g"]
    os.unlink(p)
    assert w.poll() == ["g"]
    assert seen == [["g"], ["g"], ["g"]]


def test_plugin_group_exists():
    from work_packet import plugins
    assert "work_packet.credentials" in plugins.GROUPS


class _P:
    def __init__(self, name, obj, ok=True):
        self.name, self.obj, self.ok = name, obj, ok


class _User:
    def __init__(self, uses=None, boom=False):
        self.got, self.boom = [], boom
        if uses is not None:
            self.credentials = uses

    def credentials_changed(self, names, h):
        if self.boom:
            raise RuntimeError("boom")
        self.got.append((names, h))


class _Kind:
    names = ("portal",)
    renew = "wpk gateway login"


@pytest.fixture
def plugged(home, monkeypatch):
    from work_packet import plugins
    a, b, c, d = _User(uses=["gateway"]), _User(), _User(uses=["other"]), _User(boom=True)
    ps = [_P("a", a), _P("b", b), _P("c", c), _P("d", d), _P("off", _User(), ok=False)]
    monkeypatch.setattr(plugins, "everything", lambda: ps)
    monkeypatch.setattr(plugins, "loaded", lambda g: {"gateway": _Kind()} if g == creds.GROUP else {})
    return a, b, c, d


def test_notify(plugged, home):
    a, b, c, d = plugged
    assert creds.notify(["gateway", "x"], home) == ["a", "b"]
    assert a.got == [(["gateway"], home)] and b.got == [(["gateway", "x"], home)]
    assert c.got == []


def test_renew_and_rows(plugged, home):
    creds.put("gateway", {}, subject="alice")
    creds.put("portal", {})
    creds.mark("portal", "expired", "token aged out")
    assert creds.renew_command("gateway") == "wpk gateway login"
    assert creds.renew_command("portal") == "wpk gateway login"
    assert creds.renew_command("none") == ""
    from work_packet.sched import doctor
    rows = doctor.credential_checks(home)
    assert [r.level for r in rows] == ["ok", "warn"]
    assert "signed in as alice" in rows[0].title and rows[0].fix == []
    assert rows[1].detail == "token aged out" and rows[1].fix == ["wpk gateway login"]


def test_dispatcher_callback(plugged, home):
    from work_packet.sched.dispatcher import Dispatcher
    a = plugged[0]
    dsp = Dispatcher.__new__(Dispatcher)
    dsp.h = home
    w = creds.Watcher(home)
    w.add(dsp._creds_changed)
    w.poll()
    creds.put("gateway", {"token": "new"})
    w.poll()
    assert a.got == [(["gateway"], home)]


def test_sched_page_owner_only(home):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash import sched as dsched

    class Req:
        def __init__(self, user=None, listener=None):
            self.scope = {"state": {"user": user, "listener": listener}} if user else {}

    creds.put("gateway", {"token": "secret"}, subject="alice")
    rows = dsched.credential_rows(Req(), home)
    assert [r["name"] for r in rows] == ["gateway"] and "data" not in rows[0]
    assert dsched.credential_rows(Req("bob@example.com", "tailnet"), home) == []
    from work_packet.dash.app import create_app
    text = TestClient(create_app(home)).get("/sched").text
    assert "Credentials" in text and "secret" not in text
