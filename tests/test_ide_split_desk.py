"""A desk keeps the VS Code release it started with; stranded servers and
second sessions are found (docs/ide-split-desk-plan.md)."""

from work_packet import hookcmd, ide_launch, ide_stranded, presence, schema
from work_packet.dash import ide as dide

C1 = "stable-" + "1" * 40
C2 = "stable-" + "2" * 40
KEY = "0123456789ab"


def backend(home, **cfg):
    be = dide.Backend(str(home), dict(schema.IDE_DEFAULTS, **cfg), KEY)
    dide.private_dirs(str(home), KEY)
    return be


def test_requests_go_to_the_release_the_launch_first_served(tmp_path):
    be = backend(tmp_path)
    lid = ide_launch.start(str(tmp_path), KEY, "/w/x", "local")
    base = "/ide/" + KEY
    assert be.route(base + "/") == base + "/"                     # nothing pinned yet
    assert be.route(base + "/%s/static/x.js" % C1) == base + "/%s/static/x.js" % C1
    assert ide_launch.current(str(tmp_path), KEY)["release"] == C1
    assert be.route(base + "/") == "%s/%s/" % (base, C1)
    assert be.route(base) == "%s/%s/" % (base, C1)
    assert be.route(base + "/?reconnectionToken=t") == "%s/%s/?reconnectionToken=t" % (base, C1)
    # a client that names its release gets it; the pin stays
    assert be.route(base + "/%s/static/y.js" % C2) == base + "/%s/static/y.js" % C2
    assert be.release() == C1
    # serve-web's own paths and ours are left alone
    assert be.route(base + "/_vscode-cli/mint-key") == base + "/_vscode-cli/mint-key"
    assert be.route(base + dide.VIS) == base + dide.VIS
    # a board that restarts reads the pin back
    again = backend(tmp_path)
    assert again.route(base + "/") == "%s/%s/" % (base, C1)
    # a new launch is pinned to nothing
    ide_launch.start(str(tmp_path), KEY, "/w/x", "local")
    again._pin = None
    assert again.route(base + "/") == base + "/"
    assert lid != ide_launch.current(str(tmp_path), KEY)["launch_id"]


def test_openvscode_server_is_not_routed(tmp_path):
    be = backend(tmp_path, backend="openvscode-server")
    ide_launch.start(str(tmp_path), KEY, "/w/x", "local")
    base = "/ide/" + KEY
    be.route(base + "/%s/static/x.js" % C1)
    assert be.route(base + "/") == base + "/"


def test_the_page_names_its_release():
    page = b'<link href="/ide/k/%s/static/out/w.css">' % C1.encode()
    assert dide.PAGE_RELEASE.search(page).group(1).decode() == C1


def test_stranded_keeps_the_pinned_server_and_lists_its_agents(monkeypatch):
    srv = [{"pid": 10, "commit": "1" * 40, "start": 1, "launch": "L-a"},
           {"pid": 20, "commit": "2" * 40, "start": 2, "launch": "L-a"}]
    argv = {11: ["bash"], 12: ["claude", "--x"], 13: ["node", "/x/codex"], 21: ["claude"]}
    kids = {10: [11], 11: [12, 13], 20: [21]}
    monkeypatch.setattr(ide_stranded, "servers", lambda key: [dict(s) for s in srv])
    monkeypatch.setattr(ide_stranded, "_argv", lambda p: argv.get(p, []))
    got = ide_stranded.stranded(KEY, None, kids)               # unpinned: the newest stays
    assert [s["pid"] for s in got] == [10]
    assert sorted(a["pid"] for a in got[0]["agents"]) == [12, 13]
    got = ide_stranded.stranded(KEY, C1, kids)                 # pinned: that one stays
    assert [s["pid"] for s in got] == [20]
    assert sorted(ide_stranded.targets([10], kids)) == [10, 12, 13]   # the shell is left
    monkeypatch.setattr(ide_stranded, "servers", lambda key: srv[:1])
    assert ide_stranded.stranded(KEY, None, kids) == []


def test_session_start_names_the_other_live_session(tmp_path):
    proj = str(tmp_path)
    presence.beat(proj, "claude-old", 100.0, kind="claude", via="ide-web", host="h",
                  pid=111, session="old-session", launch="L-1", wpid="w", turn="waiting")
    me = presence.beat(proj, "claude-new", 200.0, kind="claude", via="ide-web", host="h",
                       pid=222, session="new-session", launch="L-1", wpid="w", turn="waiting")
    alive = {111, 222}.__contains__
    note = hookcmd.others_note(proj, me, 300.0, alive)
    assert "pid 111" in note and "same VS Code launch" in note and "pid 222" not in note
    assert hookcmd.others_note(proj, me, 300.0, {222}.__contains__) == ""      # it died
    assert hookcmd.others_note(proj, dict(me, wpid="other"), 300.0, alive) == ""
    # the same process before a /clear is not another session
    assert hookcmd.others_note(proj, dict(me, pid=111), 300.0, alive) == ""
    # elsewhere: counted only while it beats
    presence.beat(proj, "claude-old", 290.0, host="far")
    assert "on far" in hookcmd.others_note(proj, me, 300.0, alive)
    assert hookcmd.others_note(proj, me, 290.0 + presence.TTL_S + 1, alive) == ""
