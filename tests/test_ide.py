"""VS Code on a packet or a work folder (docs/vscode-plan.md V1)."""

import json
import os

import pytest

from work_packet import executor, ide, schema
from work_packet.check import check
from work_packet.cli import main

from test_setup import home, source                       # noqa: F401
from test_workspace import setup_root


def load(path):
    with open(path) as fp:
        return ide.parse_jsonc(fp.read())


def names(op):
    return [n for n, _ in op.folders]


# --- what to open ------------------------------------------------------------------

def test_before_the_seed_the_packet_opens_the_project_root(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    op = ide.resolve("dvs")
    assert op.kind == "root"
    assert op.path == os.path.join(proj, ".vscode", "project.code-workspace")
    assert names(op) == ["data (shared, no rollback)", "dv-solve (your clone)", "state",
                         "project"]
    ws = load(op.path)
    assert [f["path"] for f in ws["folders"]] == ["../work/data", "../work/dv-solve",
                                                  "../state", ".."]
    hide = load(os.path.join(proj, ".vscode", "settings.json"))["files.exclude"]
    assert {"work", "state", "packets", ".setup", ".vscode"} <= set(hide)
    assert not os.path.exists(os.path.join(pkt.path, ".vscode"))


def test_after_the_seed_the_packet_opens_its_worktrees(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0
    op = ide.resolve("dvs")
    assert op.kind == "packet"
    assert op.path == os.path.join(pkt.path, ".vscode", "packet.code-workspace")
    assert names(op) == ["data (shared, no rollback)", "dv-solve (packet: wpk/dvs)",
                         "state", "packet"]
    ws = load(op.path)
    assert [f["path"] for f in ws["folders"]] == ["../work/data", "../work/dv-solve",
                                                  "../state", ".."]
    # your clone is never in the packet's workspace
    assert all(os.path.realpath(p) != os.path.join(proj, "work", "dv-solve")
               for _, p in op.folders)
    st = ws["settings"]
    assert st["terminal.integrated.env.linux"]["WPK_WPID"] == pkt.wpid
    assert "**/packages/**" in st["files.watcherExclude"]
    assert [t["label"] for t in ws["tasks"]["tasks"]] == ["wpk: show", "wpk: log",
                                                         "wpk: check"]
    hide = load(os.path.join(pkt.path, ".vscode", "settings.json"))["files.exclude"]
    assert {"work", "state", "steps", ".pending"} <= set(hide)
    # .vscode/ is not part of the packet format, and check says nothing about it
    assert check(proj).issues == []


def test_a_packet_without_work_gets_state_and_the_packet(home, tmp_path):
    from work_packet import project
    plan = project.new("bare")
    open(os.path.join(plan.path, "prompt.md"), "w").write("Count.\n")
    assert executor.admin(executor.Packet(plan.packet), "resume").code == 0
    assert executor.step(plan.path).code == 0
    op = ide.resolve("bare")
    assert names(op) == ["state", "packet"]


def test_folder_targets(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    op = ide.resolve("dvs", "dv-solve")
    assert (op.kind, op.path) == ("clone", os.path.join(proj, "work", "dv-solve"))
    assert not op.is_workspace
    with pytest.raises(ide.IdeError, match="no worktree"):
        ide.resolve("dvs", "dv-solve", packet=True)
    assert executor.step(proj).code == 0
    op = ide.resolve("dvs", "dv-solve", packet=True)
    assert (op.kind, op.path) == ("worktree", os.path.join(pkt.path, "work", "dv-solve"))
    assert "wpk/dvs" in op.label
    op = ide.resolve("dvs", "data", packet=True)
    assert (op.kind, op.path) == ("plain", os.path.join(proj, "work", "data"))
    assert "shared" in op.note
    with pytest.raises(ide.IdeError, match="there is: data, dv-solve"):
        ide.resolve("dvs", "nope")


# --- merging with VS Code's edits -------------------------------------------------------

def test_your_edits_survive_and_nothing_is_written_when_nothing_changed(home, source,
                                                                        tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0
    op = ide.resolve("dvs")
    ws = load(op.path)
    ws["folders"].append({"path": "/elsewhere"})
    ws["settings"]["editor.tabSize"] = 3
    ws["settings"]["search.exclude"]["**/mine/**"] = True
    ws["tasks"]["tasks"].append({"label": "build", "type": "shell", "command": "make"})
    text = "// my comment\n" + json.dumps(ws, indent=4).replace("\n}", ",\n}")  # JSONC
    open(op.path, "w").write(text)
    ide.resolve("dvs")
    got = load(op.path)
    assert got["folders"][-1] == {"path": "/elsewhere"}
    assert got["settings"]["editor.tabSize"] == 3
    assert got["settings"]["search.exclude"]["**/mine/**"] is True
    assert "**/packages/**" in got["settings"]["search.exclude"]
    assert [t["label"] for t in got["tasks"]["tasks"]][-1] == "build"
    # unchanged: no write at all
    m = os.stat(op.path).st_mtime_ns
    ide.resolve("dvs")
    assert os.stat(op.path).st_mtime_ns == m


def test_a_folder_wpk_no_longer_lists_goes_away(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0
    op = ide.resolve("dvs")
    os.unlink(os.path.join(pkt.path, "work", "data"))
    ide.resolve("dvs")
    assert [f["path"] for f in load(op.path)["folders"]] == ["../work/dv-solve", "../state",
                                                             ".."]


def test_a_workspace_that_does_not_parse_is_left_alone(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    op = ide.resolve("dvs")
    open(op.path, "w").write("{ not json")
    with pytest.raises(ide.IdeError, match="does not parse"):
        ide.resolve("dvs")
    assert open(op.path).read() == "{ not json"


def test_parse_jsonc_keeps_slashes_in_strings():
    assert ide.parse_jsonc('{"a": "http://x/*y*/", // c\n "b": [1,2,],}') == \
        {"a": "http://x/*y*/", "b": [1, 2]}


# --- links -------------------------------------------------------------------------

class FakeTs:
    def __init__(self, dns):
        self.dns = dns

    def status(self):
        return {"Self": {"DNSName": self.dns}}


def test_links():
    op = ide.Open("packet", "/h/p q/.vscode/packet.code-workspace", "x", "p", "w")
    assert ide.desktop_url(op) == "vscode://file/h/p%20q/.vscode/packet.code-workspace"
    assert ide.desktop_url(op, "a9550") == \
        "vscode://vscode-remote/ssh-remote+a9550/h/p%20q/.vscode/packet.code-workspace" \
        "?windowId=_blank"
    assert ide.web_path(op) == "/ide/?workspace=/h/p%20q/.vscode/packet.code-workspace"
    f = ide.Open("clone", "/h/w/dv-solve", "x", "p", "w")
    assert ide.web_path(f) == "/ide/?folder=/h/w/dv-solve"
    cfg = dict(schema.IDE_DEFAULTS)
    me = __import__("getpass").getuser()
    assert ide.ssh_host(cfg, FakeTs("a9550.perch-char.ts.net.")) == me + "@a9550"
    assert ide.ssh_host(cfg, name="a9550.perch-char.ts.net") == me + "@a9550.perch-char.ts.net"
    assert ide.ssh_host(dict(cfg, ssh_host="box"), FakeTs("a9550.x.")) == "box"   # an alias
    assert ide.ssh_host(cfg, FakeTs("")) == me + "@" + __import__("socket").gethostname()
    assert ide.desktop_url(op, "me@a9550").startswith("vscode://vscode-remote/ssh-remote+me@a9550/")


WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"
LINUX = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"
MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"


def test_same_machine_needs_loopback_and_the_same_os():
    assert ide.same_machine("loopback", LINUX, "linux")
    assert not ide.same_machine("loopback", WIN, "linux")      # a forwarded port from Windows
    assert not ide.same_machine("loopback", MAC, "linux")
    assert not ide.same_machine("tailnet", LINUX, "linux")
    assert not ide.same_machine("loopback", None, "linux")
    assert ide.same_machine("loopback", MAC, "darwin")
    cfg = dict(schema.IDE_DEFAULTS)
    assert ide.desktop_choice(cfg, "loopback", WIN) == "remote"
    assert ide.desktop_choice(dict(cfg, desktop_link="local"), "loopback", WIN) == "local"
    assert ide.desktop_choice(dict(cfg, desktop_link="remote"), "loopback", LINUX) == "remote"


def test_open_command():
    op = ide.Open("clone", "/w/x", "x", "p", "w")
    which = lambda n: "/usr/bin/code"                      # noqa: E731
    assert ide.open_command(op, {"VSCODE_IPC_HOOK_CLI": "/s"}, which) == ["/usr/bin/code", "/w/x"]
    assert ide.open_command(op, {"DISPLAY": ":0"}, which) == ["/usr/bin/code", "/w/x"]
    assert ide.open_command(op, {}, which) is None
    assert ide.open_command(op, {"DISPLAY": ":0"}, lambda n: None) is None


def test_ide_config_is_validated():
    v = schema.validate_config
    assert v({"ide": {"web": True, "ssh_host": "a"}}) == []
    assert v({"ide": {"web": "yes"}})
    assert v({"ide": {"backend": "code-server"}})
    assert v({"ide": {"idle_minutes": 0}})
    assert v({"ide": {"nope": 1}})
    assert v({"ide": {"desktop_link": "remote"}}) == []
    assert v({"ide": {"desktop_link": "ssh"}})


def test_cli(home, source, tmp_path, capsys):
    proj, pkt = setup_root(tmp_path, source)
    assert main(["ide", "dvs", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["kind"] == "root" and got["workspace"] is True
    assert got["links"]["local"].startswith("vscode://file/")
    assert got["links"]["web"] is None
    assert main(["ide", "dvs", "dv-solve"]) == 0
    out = capsys.readouterr().out
    assert "your clone" in out and "vscode-remote/ssh-remote+" in out
    assert main(["ide", "dvs", "nope"]) != 0


# --- the board (V2) ------------------------------------------------------------------

def _board_client(kind, ts=None):
    from test_server import SECRET, _client
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import csrf_token
    host = "127.0.0.1:7878" if kind == "loopback" else "a9550:7878"
    peer = "127.0.0.1" if kind == "loopback" else "100.64.0.9"
    c = _client(create_app(), kind, ts, peer=peer, host=host)
    return c, {"origin": "http://" + host}, csrf_token(SECRET)


def test_board_opens_the_project_on_loopback(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    c, origin, tok = _board_client("loopback")
    page = c.get("/p/dvs").text
    assert "Open the project" in page and "Your clone" in page and "Open (shared)" in page
    assert "Packet worktree" not in page                     # none before a step
    ws = os.path.join(proj, ".vscode", "project.code-workspace")
    # a browser on this machine: VS Code here first
    r = c.post("/p/dvs/ide", headers=dict(origin, **{"user-agent": LINUX}),
               data={"csrf": tok, "go": "desktop"})
    assert r.status_code == 200
    assert 'id="ide-go" class="go primary ide-link" data-kind="local" href="vscode://file%s"' \
        % ws in r.text
    assert 'data-kind="remote" href="vscode://vscode-remote/ssh-remote+' in r.text
    # Windows through a forwarded port: also loopback, but Remote-SSH first
    r = c.post("/p/dvs/ide", headers=dict(origin, **{"user-agent": WIN}),
               data={"csrf": tok, "go": "desktop"})
    me = __import__("getpass").getuser()
    assert 'id="ide-go" class="go primary ide-link" data-kind="remote" ' \
        'href="vscode://vscode-remote/ssh-remote+%s@' % me in r.text
    assert 'data-kind="local" href="vscode://file%s"' % ws in r.text
    assert "/static/ide.js" in r.text
    assert os.path.isfile(ws)
    assert c.get("/static/ide.js").status_code == 200


def test_board_opens_a_worktree_over_the_tailnet(home, source, tmp_path):
    from test_server import FakeTailscaled, OWNER
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0
    f = FakeTailscaled(whois={"100.64.0.9": (OWNER, None)})
    try:
        c, origin, tok = _board_client("tailnet", f)
        assert "Packet worktree" in c.get("/p/dvs").text
        assert "Open in VS Code" in c.get("/p/dvs/" + pkt.wpid).text
        r = c.post("/p/dvs/ide", headers=origin,
                   data={"csrf": tok, "repo": "dv-solve", "packet": "1"})
        tree = os.path.join(pkt.path, "work", "dv-solve")
        # the host the browser used is one the laptop can reach
        me = __import__("getpass").getuser()
        assert 'href="vscode://vscode-remote/ssh-remote+%s@a9550%s?windowId=_blank"' \
            % (me, tree) in r.text
        r = c.post("/p/dvs/ide", headers=origin, data={"csrf": tok, "wpid": pkt.wpid})
        assert "ssh-remote+%s@a9550%s/.vscode/packet.code-workspace" % (me, pkt.path) in r.text
        # an error goes back to the page with a message
        r = c.post("/p/dvs/ide", headers=origin, data={"csrf": tok, "repo": "nope"},
                   follow_redirects=False)
        assert r.status_code == 303 and "msg=no+%27nope%27" in r.headers["location"]
        # no token, no write
        assert c.post("/p/dvs/ide", headers=origin, data={}).status_code == 403
    finally:
        f.close()


def test_board_without_desktop_buttons(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    open(os.path.join(home, "config.toml"), "w").write("[ide]\ndesktop = false\n")
    c, origin, tok = _board_client("loopback")
    assert "Open the project" not in c.get("/p/dvs").text


# --- web VS Code (V3) ----------------------------------------------------------------

import asyncio                                                   # noqa: E402
import signal                                                    # noqa: E402
import sys                                                       # noqa: E402
import time                                                      # noqa: E402

FAKE_IDE = os.path.join(os.path.dirname(__file__), "fake_ide.py")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:        # a zombie of ours is gone for this purpose
        with open("/proc/%d/stat" % pid) as fp:
            return fp.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def _pids(path):
    if not os.path.exists(path):
        return []
    return [tuple(int(x) for x in ln.split()) for ln in open(path).read().splitlines()]


@pytest.fixture
def short_home(tmp_path, monkeypatch):
    """pytest's tmp paths are long; the socket must fit in sun_path."""
    import tempfile
    d = tempfile.mkdtemp(prefix="wpk-ide")
    monkeypatch.setenv("WPK_HOME", d)
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def _backend(home, tmp_path, **cfg):
    from work_packet.dash.ide import Backend
    c = dict(schema.IDE_DEFAULTS, web=True, **cfg)
    return Backend(home, c, argv=[sys.executable, FAKE_IDE, str(tmp_path / "pids")])


def _web_client(home, tmp_path, kind="loopback", ts=None, **cfg):
    from test_server import SECRET, _client
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import csrf_token
    open(os.path.join(home, "config.toml"), "w").write("[ide]\nweb = true\n")
    be = _backend(home, tmp_path, **cfg)
    host = "127.0.0.1:7878" if kind == "loopback" else "a9550:7878"
    peer = "127.0.0.1" if kind == "loopback" else "100.64.0.9"
    c = _client(create_app(ide_backend=be), kind, ts, peer=peer, host=host)
    c.__enter__()               # one event loop, as under uvicorn
    return c, be, {"origin": "http://" + host}, csrf_token(SECRET)


def test_socket_path_fits_sun_path(tmp_path):
    from work_packet.dash import ide as dide
    assert dide.socket_path("/h") == "/h/ide/serve.sock"
    long = "/" + "x" * 120
    p = dide.socket_path(long, {"XDG_RUNTIME_DIR": str(tmp_path)})
    assert p.startswith(str(tmp_path) + "/wpk-ide-") and len(p) < 100
    p = dide.socket_path(long, {})
    assert p.startswith("/tmp/wpk-ide-%d-" % os.getuid())
    assert p == dide.socket_path(long, {})                  # the same home, the same place


def test_private_dir_refuses_a_shared_directory(tmp_path):
    from work_packet.dash import ide as dide
    d = tmp_path / "ide"
    dide.private_dir(str(d))
    assert (os.stat(d).st_mode & 0o777) == 0o700
    os.chmod(d, 0o755)
    with pytest.raises(dide.IdeUnavailable, match="0700"):
        dide.private_dir(str(d))


def test_web_proxy_http(short_home, tmp_path):
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        r = c.get("/ide/?folder=/x", headers={"cookie": "vscode-tkn=1; other=secret"})
        assert r.status_code == 200
        assert "enableWorkspaceTrust&quot;:false" in r.text          # trust prompt off
        seen = json.loads(r.text.split('<pre id="seen">')[1].split("</pre>")[0]
                          .replace("&lt;", "<"))
        assert seen["host"] == "127.0.0.1:7878"                      # Host as the browser sent
        assert seen["cookie"] == "vscode-tkn=1"                      # only VS Code's cookies
        # the backend's CSP and cookies, not the board's
        assert r.headers["content-security-policy"] == "default-src 'self' fake"
        assert "x-frame-options" not in r.headers
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.cookies.get("vscode-cli-secret-half") == "abc"
        # POST: no CSRF token needed under /ide/, but the Origin must match
        r = c.post("/ide/echo", headers=origin, content=b"hello")
        assert (r.status_code, r.content) == (200, b"hello")
        assert c.post("/ide/echo", content=b"x").status_code == 403
        assert c.post("/ide/echo", headers={"origin": "http://evil"}, content=b"x") \
            .status_code == 403
        # the board's own POSTs still need the token
        assert c.post("/p/x/ide", headers=origin, data={}).status_code == 403
        [(pid, kid)] = _pids(tmp_path / "pids")                      # started once
    finally:
        be.stop()
        c.__exit__(None, None, None)
    assert not _alive(pid) and not _alive(kid)                       # the whole group
    assert not os.path.exists(be.sock)


def test_web_proxy_websocket(short_home, tmp_path):
    from starlette.websockets import WebSocketDisconnect
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        with c.websocket_connect("ws://127.0.0.1:7878/ide/stable-x/remote?reconnectionToken=t",
                                 headers=dict(origin, cookie="vscode-k=v; board=b")) as ws:
            first = json.loads(ws.receive_text())
            assert first == {"host": "127.0.0.1:7878", "cookie": "vscode-k=v"}
            assert be.clients == 1
            ws.send_bytes(b"\x00\x01binary")
            assert ws.receive_bytes() == b"\x00\x01binary"
            ws.send_text("text")
            assert ws.receive_text() == "text"
        deadline = time.time() + 5
        while be.clients and time.time() < deadline:
            time.sleep(0.05)
        assert be.clients == 0
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("ws://127.0.0.1:7878/ide/x", headers={"origin": "http://evil"}) as ws:
                ws.receive_text()
    finally:
        be.stop()
        c.__exit__(None, None, None)


def test_web_proxy_refuses_another_login_without_starting(short_home, tmp_path):
    from test_server import FakeTailscaled, OWNER
    f = FakeTailscaled(whois={"100.64.0.9": (OWNER, None),
                              "100.64.0.10": ("other@example.com", None)})
    try:
        from test_server import SECRET, Guard, TestClient, Tailnet
        from work_packet.dash.app import create_app
        open(os.path.join(short_home, "config.toml"), "w").write("[ide]\nweb = true\n")
        be = _backend(short_home, tmp_path)
        g = Guard(create_app(ide_backend=be), "tailnet", SECRET, tailnet=Tailnet(f.path))
        c = TestClient(g, base_url="http://a9550:7878", client=("100.64.0.10", 50000))
        assert c.get("/ide/?folder=/x").status_code == 403
        assert be.proc is None and not os.path.exists(tmp_path / "pids")
    finally:
        f.close()


def test_web_off_is_404_and_starts_nothing(short_home, tmp_path):
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        open(os.path.join(short_home, "config.toml"), "w").write("[ide]\nweb = false\n")
        assert c.get("/ide/?folder=/x").status_code == 404
        assert be.proc is None
    finally:
        c.__exit__(None, None, None)


def test_two_first_requests_start_one_backend(short_home, tmp_path):
    be = _backend(short_home, tmp_path)

    async def both():
        await asyncio.gather(be.ensure(), be.ensure(), be.ensure())
    try:
        asyncio.run(both())
        assert len(_pids(tmp_path / "pids")) == 1
    finally:
        be.stop()


def test_idle_backend_stops(short_home, tmp_path):
    be = _backend(short_home, tmp_path, idle_minutes=0.01)          # 0.6 s

    async def run():
        await be.ensure()
        pid = be.proc.pid
        for _ in range(100):
            if be.proc is None:
                return pid
            await asyncio.sleep(0.05)
        return pid
    try:
        pid = asyncio.run(run())
        assert be.proc is None and not _alive(pid)
    finally:
        be.stop()


def test_a_backend_that_dies_at_once_says_so(short_home, tmp_path):
    from work_packet.dash.ide import Backend, IdeUnavailable
    be = Backend(short_home, dict(schema.IDE_DEFAULTS), argv=[sys.executable, "-c", "pass"])
    with pytest.raises(IdeUnavailable, match="exited"):
        asyncio.run(be.ensure())


def test_board_web_buttons(short_home, tmp_path, monkeypatch, source):
    from test_server import FakeTailscaled, OWNER
    monkeypatch.chdir(tmp_path)
    proj, pkt = setup_root(tmp_path, source)
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        page = c.get("/p/dvs").text
        assert 'value="web"' in page and "needs HTTPS" not in page
        r = c.post("/p/dvs/ide", headers=origin, data={"csrf": tok, "go": "web"},
                   follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/ide/?workspace=%s/.vscode/project.code-workspace" \
            % proj
        r = c.post("/p/dvs/ide", headers=origin, data={"csrf": tok, "go": "web",
                                                       "repo": "dv-solve"},
                   follow_redirects=False)
        assert r.headers["location"] == "/ide/?folder=%s/work/dv-solve" % proj
    finally:
        c.__exit__(None, None, None)
    # over the tailnet on plain http: shown, disabled, and the POST is refused
    f = FakeTailscaled(whois={"100.64.0.9": (OWNER, None)})
    try:
        c, be, origin, tok = _web_client(short_home, tmp_path, "tailnet", f)
        page = c.get("/p/dvs").text
        assert "disabled title=\"needs HTTPS" in page
        r = c.post("/p/dvs/ide", headers=origin, data={"csrf": tok, "go": "web"},
                   follow_redirects=False)
        assert r.status_code == 404
        c.__exit__(None, None, None)
    finally:
        f.close()


def test_a_server_left_by_a_crashed_board_is_adopted_and_stopped(short_home, tmp_path):
    a = _backend(short_home, tmp_path)
    asyncio.run(a.ensure())
    [(pid, kid)] = _pids(tmp_path / "pids")
    a.proc = None                               # the board died without stopping it
    b = _backend(short_home, tmp_path)
    try:
        asyncio.run(b.ensure())
        assert b.proc == pid                    # adopted, not a second server
        assert len(_pids(tmp_path / "pids")) == 1
    finally:
        b.stop()
    deadline = time.time() + 5
    while (_alive(pid) or _alive(kid)) and time.time() < deadline:
        time.sleep(0.05)
    assert not _alive(pid) and not _alive(kid)


def test_web_button_says_when_code_is_missing(short_home, tmp_path, monkeypatch, source):
    monkeypatch.chdir(tmp_path)
    setup_root(tmp_path, source)
    c, be, origin, tok = _web_client(short_home, tmp_path)
    try:
        open(os.path.join(short_home, "config.toml"), "w").write(
            '[ide]\nweb = true\ncode = "no-such-vscode"\n')
        assert "is not on PATH" in c.get("/p/dvs").text
    finally:
        c.__exit__(None, None, None)


def test_doctor_reports_the_vscode_cli_only_when_web_is_on(home, monkeypatch):
    from work_packet import setup
    assert [c for c in setup._tools() if c.id == "tools.code"] == []
    os.makedirs(home, exist_ok=True)
    open(os.path.join(home, "config.toml"), "w").write('[ide]\nweb = true\ncode = "nope-vs"\n')
    [c] = [c for c in setup._tools() if c.id == "tools.code"]
    assert c.level == "warn" and "nope-vs" in c.title


# --- while the runner owns it (V5) -----------------------------------------------------

def test_guard_settings_follow_the_owner(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0                    # RUNNABLE again: the runner's
    op = ide.resolve("dvs")
    assert op.owner == "runner"
    st = load(op.path)["settings"]
    assert st["files.readonlyInclude"] == {"**": True}
    assert st["git.autofetch"] is False and st["editor.formatOnSave"] is False
    # your own setting, changed while it was guarded, comes back as it was before
    ws = load(op.path)
    ws["settings"]["editor.tabSize"] = 2
    open(op.path, "w").write(json.dumps(ws))
    assert executor.admin(pkt, "pause").code == 0          # yours: guard off
    st = load(op.path)["settings"]
    for k in ide.GUARD:
        assert k not in st, k
    assert st["editor.tabSize"] == 2
    assert executor.admin(pkt, "resume").code == 0         # the runner's again
    assert load(op.path)["settings"]["files.readonlyInclude"] == {"**": True}


def test_guard_restores_what_you_had(home, source, tmp_path):
    ws = {"settings": {"git.autofetch": True, "files.readonlyInclude": {"*.lock": True}}}
    on = ide.guard(ws, True)
    assert on["settings"]["files.readonlyInclude"] == {"*.lock": True, "**": True}
    assert on["settings"]["git.autofetch"] is False
    assert ide.guard(on, True) == on                       # idempotent
    off = ide.guard(on, False)
    assert off["settings"] == ws["settings"]
    assert ide.guard(off, False) == off


def test_set_owner_without_a_workspace_writes_nothing(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0
    assert not os.path.exists(ide.workspace_path(pkt))     # nobody opened it


def test_a_broken_workspace_never_fails_a_step(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0
    ide.resolve("dvs")
    open(ide.workspace_path(pkt), "w").write("{ broken")
    assert executor.step(proj).code == 0
    assert open(ide.workspace_path(pkt)).read() == "{ broken"


def test_git_waits_once_for_index_lock(tmp_path, monkeypatch):
    import subprocess as sp
    import threading
    from work_packet import workspace
    from test_setup import git
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a").write_text("a")
    lock = repo / ".git" / "index.lock"
    lock.write_text("")
    monkeypatch.setattr(workspace, "LOCK_RETRY_S", 0.5)
    threading.Timer(0.2, lock.unlink).start()               # VS Code lets go
    workspace._git(str(repo), "add", "a")
    assert "a" in sp.run(["git", "-C", str(repo), "diff", "--cached", "--name-only"],
                         capture_output=True, text=True).stdout
    lock.write_text("")                                     # held for good: fails
    with pytest.raises(workspace.WorkspaceError, match="index.lock"):
        workspace._git(str(repo), "add", "a")


def test_board_pause_and_open(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    assert executor.step(proj).code == 0
    c, origin, tok = _board_client("loopback")
    page = c.get("/p/dvs/" + pkt.wpid).text
    assert "Pause and open" in page and "read-only" in page
    r = c.post("/p/dvs/ide", headers=origin,
               data={"csrf": tok, "wpid": pkt.wpid, "pause": "1"})
    assert r.status_code == 200 and "Paused" in r.text
    assert pkt.load_status()[0]["state"] == "PAUSED"
    assert "files.readonlyInclude" not in load(ide.workspace_path(pkt))["settings"]
    # paused already: the action is refused and nothing opens
    r = c.post("/p/dvs/ide", headers=origin, data={"csrf": tok, "wpid": pkt.wpid, "pause": "1"},
               follow_redirects=False)
    assert r.status_code == 303 and "nothing+to+pause" in r.headers["location"]


def test_the_window_is_titled_after_the_packet(home, source, tmp_path):
    proj, pkt = setup_root(tmp_path, source)
    op = ide.resolve("dvs")                                   # before the seed: the root
    assert load(op.path)["settings"]["window.title"] == "wpk: dvs${dirty}"
    assert executor.step(proj).code == 0
    op = ide.resolve("dvs")
    assert load(op.path)["settings"]["window.title"] == "wpk: dvs${dirty}"
    ws = load(op.path)
    ws["settings"]["window.title"] = "mine ${activeEditorShort}"
    open(op.path, "w").write(json.dumps(ws))
    ide.resolve("dvs")
    assert load(op.path)["settings"]["window.title"] == "mine ${activeEditorShort}"


def test_a_child_is_titled_with_its_spawn_name(home, tmp_path):
    from conftest import child_wpid, make_project
    proj, root = make_project(tmp_path, steps=1, spawn_at=1)
    kid = os.path.join(proj, "packets", child_wpid(root.wpid, 1, 0))
    op = ide.resolve(kid)
    assert op.kind == "packet" and op.path.startswith(kid)
    assert load(op.path)["settings"]["window.title"] == "wpk: demo/hello${dirty}"
