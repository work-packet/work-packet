"""VS Code sessions on the packet page and the Overview, for the owner only
(docs/vscode-monitor-plan.md S5, §4.5)."""

import os
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402

from test_ide import short_home  # noqa: E402,F401
from test_setup import source  # noqa: E402,F401
from test_workspace import setup_root  # noqa: E402
from work_packet import ide_launch  # noqa: E402
from work_packet import ide_sessions as s  # noqa: E402

KEY = "0123456789ab"
SID = ["%d7f3c1a2-0b5d-4c6e-9f10-000000000000" % i for i in range(6)]


def _setup(home, tmp_path, monkeypatch, source):
    monkeypatch.chdir(tmp_path)
    proj, pkt = setup_root(tmp_path, source)
    now = time.time()
    os.makedirs(ide_launch.server_dir(home, KEY), exist_ok=True)
    ide_launch.record_open(home, KEY, "dvs", pkt.wpid, "me")
    ide_launch.record_open(home, KEY, "dvs", "OTHER1", "me")
    base = {"harness": "claude", "project": "dvs", "key": KEY, "launch_ids": ["L-0123456789ab"]}
    s.write(home, dict(base, session_id=SID[0], wpid=pkt.wpid, attribution="confirmed",
                       job_ref="4242", host="exec7", model="claude-sonnet-5",
                       last_event=s.SHELL, last_event_t=now - 30, last_activity_t=now - 30,
                       turn_state=s.BUSY, live=True, status="busy", client="vscode-ext",
                       usage={"input_tokens": 10, "output_tokens": 1500},
                       usage_reported=True))
    s.write(home, dict(base, harness="codex", session_id=SID[1], wpid=pkt.wpid,
                       attribution="workspace", last_event=s.TURN_END,
                       last_activity_t=now - 600, turn_state=s.FINISHED, client="vscode-ext",
                       usage={}, usage_reported=False))
    s.write(home, dict(base, session_id=SID[2], attribution="confirmed",      # shared editor
                       last_event=s.ASK, last_activity_t=now - 60, turn_state=s.WAITING,
                       usage={"output_tokens": 5}, usage_reported=True))
    s.write(home, dict(base, session_id=SID[3], wpid="OTHER1", attribution="confirmed",
                       last_event=s.READ, last_activity_t=now - 5, usage_reported=False))
    return pkt


def _row(html, sid):
    """The rest of a session's row, from its short id on."""
    return html.split(">%s</code>" % sid[:8])[1].split("</tr>")[0]


def _owner(home):
    from work_packet.dash.app import create_app
    return TestClient(create_app(home), base_url="http://127.0.0.1:7878")


def test_the_packet_page_lists_its_sessions(short_home, tmp_path, monkeypatch, source):
    pkt = _setup(short_home, tmp_path, monkeypatch, source)
    with _owner(short_home) as c:
        page = c.get("/p/dvs/%s" % pkt.wpid).text
    sec = page.split('id="vscode-sessions"')[1]
    mine, shared = sec.split("Shared editor")
    assert mine.index(SID[0][:8]) < mine.index(SID[1][:8])           # newest first
    assert "claude-sonnet-5" in mine and "Shell command requested" in mine
    assert "job <code>4242</code> on exec7" in mine and "1.5k" in mine
    codex = _row(mine, SID[1])
    assert codex.count("unreported") == 2 and "workspace match" in codex   # model and tokens
    assert SID[2][:8] in shared and "Asked for input" in shared and "waiting for input" in shared
    assert SID[3][:8] not in page                                    # another packet's


def test_the_overview_shows_recent_sessions_across_packets(short_home, tmp_path, monkeypatch,
                                                           source):
    pkt = _setup(short_home, tmp_path, monkeypatch, source)
    with _owner(short_home) as c:
        page = c.get("/").text
    sec = page.split('id="vscode-sessions"')[1]
    order = [sec.index(x[:8]) for x in (SID[3], SID[0], SID[2], SID[1])]
    assert order == sorted(order)
    assert '/p/dvs/%s#vscode-sessions' % pkt.wpid in sec
    shared = _row(sec, SID[2])
    assert 'href="/p/dvs">dvs</a>' in shared                 # no packet: the project


def test_an_update_shows_on_the_next_refresh(short_home, tmp_path, monkeypatch, source):
    pkt = _setup(short_home, tmp_path, monkeypatch, source)
    with _owner(short_home) as c:
        assert "claude-fable-5-1" not in c.get("/p/dvs/%s" % pkt.wpid).text
        rec = s.read(short_home, "claude", SID[0])
        time.sleep(0.01)                    # a new directory mtime
        s.write(short_home, dict(rec, model="claude-fable-5-1", last_event=s.TURN_END,
                                 usage={"input_tokens": 10, "output_tokens": 2500}))
        page = c.get("/p/dvs/%s" % pkt.wpid).text
    row = _row(page, SID[0])
    assert "claude-fable-5-1" in row and "Turn finished" in row and "2.5k" in row


def test_no_sessions_no_section(short_home, tmp_path, monkeypatch, source):
    monkeypatch.chdir(tmp_path)
    proj, pkt = setup_root(tmp_path, source)
    with _owner(short_home) as c:
        assert "vscode-sessions" not in c.get("/p/dvs/%s" % pkt.wpid).text
        assert "vscode-sessions" not in c.get("/").text


def test_pages_never_open_a_transcript(short_home, tmp_path, monkeypatch, source):
    pkt = _setup(short_home, tmp_path, monkeypatch, source)
    import builtins
    real = builtins.open

    def spy(path, *a, **kw):
        if str(path).endswith(".cur") or "rollout-" in str(path) or \
                "/.claude/projects/" in str(path):
            raise AssertionError("a page opened %s" % path)
        return real(path, *a, **kw)
    with _owner(short_home) as c:
        monkeypatch.setattr(builtins, "open", spy)
        c.get("/p/dvs/%s" % pkt.wpid)
        c.get("/")


def test_another_signed_in_user_never_sees_them(short_home, tmp_path, monkeypatch, source):
    from work_packet.dash import login
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard
    pkt = _setup(short_home, tmp_path, monkeypatch, source)
    secret = b"k" * 32
    login.ensure_drop_dir(short_home)
    gate = login.Gate(short_home, secret, 7878, "matt", ["bob"])
    g = Guard(create_app(short_home), "network", secret, gate=gate, names=["board.example"])
    base = "https://board.example:7878"
    with TestClient(g, base_url=base, follow_redirects=False) as c:
        c.cookies.set(gate.session_cookie, login.sign(gate.key, "bob", 1))
        for url in ("/p/dvs/%s" % pkt.wpid, "/", "/p/dvs"):
            r = c.get(url)
            assert r.status_code == 200, url
            assert "vscode-sessions" not in r.text and SID[0][:8] not in r.text, url
            assert "exec7" not in r.text and "4242" not in r.text, url
        c.cookies.set(gate.session_cookie, login.sign(gate.key, "matt", 1))
        assert SID[0][:8] in c.get("/p/dvs/%s" % pkt.wpid).text           # the owner does


def test_the_project_page_lists_the_projects_sessions(short_home, tmp_path, monkeypatch,
                                                      source):
    pkt = _setup(short_home, tmp_path, monkeypatch, source)
    with _owner(short_home) as c:
        sec = c.get("/p/dvs").text.split('id="vscode-sessions"')[1].split("<h2")[0]
    for sid in SID[:4]:
        assert ">%s</code>" % sid[:8] in sec
    assert '/p/dvs/%s#vscode-sessions' % pkt.wpid in sec
