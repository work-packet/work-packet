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
