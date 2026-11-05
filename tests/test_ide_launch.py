"""Launch identity for web VS Code (docs/vscode-monitor-plan.md S1)."""

import asyncio
import json
import os
import time

import pytest

from work_packet import ide_launch

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from test_ide import _backend, _backends, _pids, setup_root, short_home  # noqa: E402,F401
from test_setup import source  # noqa: E402,F401


def _envs(tmp_path):
    p = tmp_path / "pids.env"
    return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


def test_launch_records_fold(tmp_path):
    h = str(tmp_path)
    os.makedirs(ide_launch.server_dir(h, "k1"))
    a = ide_launch.start(h, "k1", "/x", "job", now=10)
    ide_launch.update(h, "k1", a, now=11, job_ref="123")
    ide_launch.update(h, "k1", a, now=12, host="exec7")
    assert ide_launch.current(h, "k1") == {"launch_id": a, "key": "k1", "target": "/x",
                                           "backend": "job", "started": 10,
                                           "job_ref": "123", "host": "exec7"}
    ide_launch.update(h, "k1", a, now=20, ended=20)
    b = ide_launch.start(h, "k1", "/x", "job", now=30)
    ide_launch.update(h, "k1", a, now=31, host="late")      # an old launch: history only
    assert ide_launch.current(h, "k1")["launch_id"] == b
    hist = ide_launch.history(h, "k1")
    assert [r["launch_id"] for r in hist] == [a, b]
    assert hist[0]["job_ref"] == "123" and hist[0]["ended"] == 20 and hist[0]["host"] == "late"
    assert ide_launch.find(h, a)["job_ref"] == "123"
    assert ide_launch.find(h, b)["launch_id"] == b
    assert ide_launch.find(h, "L-nope") is None
    assert a.startswith("L-") and len(a) == 14 and a != b
    st = os.stat(os.path.join(ide_launch.server_dir(h, "k1"), "launches.jsonl"))
    assert st.st_mode & 0o077 == 0


def test_torn_history_lines_are_skipped(tmp_path):
    h = str(tmp_path)
    d = ide_launch.server_dir(h, "k1")
    os.makedirs(d)
    a = ide_launch.start(h, "k1", "/x", "local", now=1)
    with open(os.path.join(d, "launches.jsonl"), "a") as fp:
        fp.write('{"launch_id": "L-torn", "t"\n')
    assert [r["launch_id"] for r in ide_launch.history(h, "k1")] == [a]


def test_packet_of_never_guesses(tmp_path):
    h = str(tmp_path)
    os.makedirs(ide_launch.server_dir(h, "k1"))
    assert ide_launch.packet_of(h, "k1") == (None, None)
    ide_launch.record_open(h, "k1", "p", "W1", "me", now=1)
    ide_launch.record_open(h, "k1", "p", "W1", "me", now=2)
    assert ide_launch.packet_of(h, "k1") == ("p", "W1")
    ide_launch.record_open(h, "k1", "p", "W2", "me", now=3)        # a second packet, same folder
    assert ide_launch.packet_of(h, "k1") == ("p", None)
    assert ide_launch.packet_of(h, "k1", until=2) == ("p", "W1")
    assert ide_launch.packet_of(h, "k1", since=3) == ("p", "W2")
    ide_launch.record_open(h, "k1", "q", "W3", "me", now=4)
    assert ide_launch.packet_of(h, "k1") == (None, None)


def test_a_local_server_gets_its_launch(short_home, tmp_path):
    be = _backend(short_home, tmp_path)
    asyncio.run(be.ensure())
    [(pid, _)] = _pids(tmp_path / "pids")
    cur = ide_launch.current(short_home, be.key)
    try:
        assert cur["backend"] == "local" and cur["pid"] == pid and cur["target"] == "/x"
        assert _envs(tmp_path) == [{"WPK_IDE_LAUNCH": cur["launch_id"], "WPK_IDE_KEY": be.key}]
        # a board restart adopts the server: the launch is the same
        be.proc = None
        b = _backends(short_home, tmp_path).get(be.key)
        asyncio.run(b.ensure())
        assert ide_launch.current(short_home, be.key)["launch_id"] == cur["launch_id"]
    finally:
        b.stop()
    ended = ide_launch.current(short_home, be.key)
    assert ended["launch_id"] == cur["launch_id"] and ended["ended"]
    # the next start is a new launch, and the history keeps both
    c = _backends(short_home, tmp_path).get(be.key)
    try:
        asyncio.run(c.ensure())
        again = ide_launch.current(short_home, be.key)
        assert again["launch_id"] != cur["launch_id"] and not again.get("ended")
        assert [e["WPK_IDE_LAUNCH"] for e in _envs(tmp_path)] == [cur["launch_id"],
                                                                  again["launch_id"]]
        assert len(ide_launch.history(short_home, be.key)) == 2
    finally:
        c.stop()


def test_open_in_vs_code_records_who_opened_it(short_home, tmp_path, monkeypatch, source):
    from test_ide import _web_client
    from work_packet.dash.ide import key_for
    monkeypatch.chdir(tmp_path)
    proj, pkt = setup_root(tmp_path, source)
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        r = c.post("/p/dvs/ide", headers=origin, data={"csrf": tok, "go": "web"},
                   follow_redirects=False)
        assert r.status_code == 303
        key = key_for("%s/.vscode/project.code-workspace" % proj)
        [o] = ide_launch.opens(short_home, key)
        assert o["project"] == "dvs" and o["wpid"] and o["by"] and o["t"] <= time.time()
        assert ide_launch.packet_of(short_home, key) == ("dvs", o["wpid"])
    finally:
        c.__exit__(None, None, None)
