"""The desktop (docs/desktop.md): xproxy, its config, the relay's ``vnc.wpk``
route and the board's ``/desk/<key>/``."""

import asyncio
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from work_packet import desktop, schema
from work_packet.sched import xproxy

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_XVNC = os.path.join(HERE, "fake_xvnc.py")


@pytest.fixture
def xdirs(monkeypatch):
    """A private X socket and lock directory (short paths: sun_path)."""
    root = tempfile.mkdtemp(prefix="wpk-x")
    x_dir, lock_dir, priv, state = (os.path.join(root, n) for n in ("u", "l", "p", "s"))
    for d in (x_dir, lock_dir, priv, state):
        os.mkdir(d, 0o700)
    monkeypatch.setenv("FAKE_X_DIR", x_dir)
    yield {"x_dir": x_dir, "lock_dir": lock_dir, "priv": priv, "state": state}
    shutil.rmtree(root, ignore_errors=True)


def conf(**kw):
    c = dict(schema.DESKTOP_DEFAULTS, xvnc=FAKE_XVNC, wm="none", env={"A": "x{display}"},
             unset=["SSH_ASKPASS"])
    c.update(kw)
    return c


# --- the pieces -----------------------------------------------------------------------

def test_xauth_record_is_wild_for_one_display():
    rec = xproxy.xauth_entry(21, b"\x01" * 16)
    fam, = struct.unpack(">H", rec[:2])
    assert fam == xproxy.FAMILY_WILD
    assert rec[2:4] == b"\0\0" and rec[4:8] == b"\0\x0221"
    assert b"MIT-MAGIC-COOKIE-1" in rec and rec.endswith(b"\0\x10" + b"\x01" * 16)


def test_env_sets_display_then_the_table_then_unsets():
    env, applied = xproxy.apply_env({"SSH_ASKPASS": "/bin/x", "KEEP": "1"},
                                    {"env": {"A": "on {display}", "B": 2}, "unset": ["SSH_ASKPASS", "B"]},
                                    23, "/p/xauth", key="abc")
    assert env["DISPLAY"] == ":23" and env["XAUTHORITY"] == "/p/xauth" and env["KEEP"] == "1"
    assert env["A"] == "on :23" and "B" not in env and "SSH_ASKPASS" not in env
    assert env["WPK_DESKTOP"] == "/desk/abc/" and applied == {"A": "on :23"}


def test_shims_go_first_on_path_unless_the_desk_keeps_its_browser(tmp_path):
    shims = xproxy.install_shims(str(tmp_path), {})
    assert shims == str(tmp_path / "bin") and os.access(os.path.join(shims, "xdg-mime"), os.X_OK)
    env, _ = xproxy.apply_env({"PATH": "/usr/bin"}, {}, 23, "/p/xauth", shims=shims)
    assert env["PATH"] == shims + ":/usr/bin"
    assert xproxy.install_shims(str(tmp_path / "d"), {"browser": "desk"}) is None
    assert schema.validate_config({"desktop": {"browser": "laptop"}})


def _fake_open(tmp_path):
    """A PATH whose real ``xdg-mime`` names a desk browser, and stub browsers that log."""
    real, log = tmp_path / "real", tmp_path / "opened"
    real.mkdir()
    def tool(path, body):
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
    tool(real / "xdg-mime", 'echo desk.desktop\n')
    (tmp_path / "applications").mkdir()
    (tmp_path / "applications" / "desk.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Desk\nExec=%s %%u\n" % (real / "deskbrowser"))
    tool(real / "deskbrowser", 'echo desk "$1" >> %s\n' % log)
    tool(real / "client", 'echo client "$1" >> %s\n' % log)
    return real, log


XDG_OPEN = shutil.which("xdg-open")


@pytest.mark.skipif(XDG_OPEN is None, reason="no xdg-open")
@pytest.mark.parametrize("browser,want", [("client", "client"), ("", "desk")])
def test_xdg_open_on_the_desk_uses_browser_when_set(tmp_path, browser, want):
    real, log = _fake_open(tmp_path)
    shims = xproxy.install_shims(str(tmp_path / "priv"), {})
    env = {"HOME": str(tmp_path), "PATH": "%s:%s:/usr/bin:/bin" % (shims, real), "DISPLAY": ":99",
           "XDG_DATA_HOME": str(tmp_path), "XDG_DATA_DIRS": str(tmp_path / "none"),
           "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_CONFIG_DIRS": str(tmp_path / "none")}
    if browser:
        env["BROWSER"] = str(real / browser)
    subprocess.run([XDG_OPEN, "http://127.0.0.1:5500/a.html"], env=env, timeout=30,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert log.read_text().split() == [want, "http://127.0.0.1:5500/a.html"]
    out = subprocess.run([os.path.join(shims, "xdg-mime"), "query", "default", "text/html"],
                         env=env, capture_output=True, text=True).stdout
    assert out.strip() == "desk.desktop"


def test_window_manager_choice():
    have = lambda *names: (lambda n: n in names)   # noqa: E731
    assert xproxy.pick_wm({"wm": "auto"}, have("fvwm", "xfwm4")) == "fvwm"
    assert xproxy.pick_wm({"wm": "auto"}, have("xfwm4")) == "xfwm4"
    assert xproxy.pick_wm({"wm": "auto"}, have()) == "none"
    assert xproxy.pick_wm({"wm": "xfce"}, have("xfce4-session")) == "xfce"
    assert xproxy.pick_wm({"wm": "fvwm"}, have("xfwm4")) == "none"


def test_allocate_skips_taken_displays_and_cleans_up(xdirs):
    open(os.path.join(xdirs["lock_dir"], ".X20-lock"), "w").close()
    socket.socket(socket.AF_UNIX).bind(os.path.join(xdirs["x_dir"], "X21"))
    n, socks, lock = xproxy.allocate(xdirs["x_dir"], xdirs["lock_dir"], abstract=False)
    try:
        assert n == 22 and lock.endswith(".X22-lock")
        assert int(open(lock).read()) == os.getpid()
        assert os.path.exists(os.path.join(xdirs["x_dir"], "X22"))
    finally:
        for s in socks:
            s.close()


def test_config_layers_wpk_defaults_under_yours(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[desktop]\nenabled = true\nwm = "xfwm4"\n[desktop.env]\nNO_AT_BRIDGE = "0"\nFOO = "bar"\n')
    c = desktop.load_config(str(tmp_path))
    assert c["enabled"] and c["wm"] == "xfwm4" and c["idle_min"] == 20
    assert c["env"] == {"SSH_ASKPASS_REQUIRE": "never", "NO_AT_BRIDGE": "0",
                        "QT_XCB_NO_MITSHM": "1", "FOO": "bar"}
    assert c["unset"] == ["SSH_ASKPASS"]
    assert c["apps"] == {"terminal": {"cmd": "xterm", "label": "Terminal"}}


def test_apps_table_adds_renames_and_removes(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[desktop.apps]\nterminal = ""\ngtkwave = "gtkwave"\n'
        'verdi = { cmd = "verdi -ssf x.fsdb", label = "Verdi" }\n')
    c = desktop.load_config(str(tmp_path))
    assert c["apps"] == {"gtkwave": {"cmd": "gtkwave", "label": "gtkwave"},
                         "verdi": {"cmd": "verdi -ssf x.fsdb", "label": "Verdi"}}
    bad = schema.validate_config({"desktop": {"apps": {"x": 3, "y": {"cmd": "a", "zzz": 1}}}})
    assert {p.field for p in bad} == {"desktop.apps.x", "desktop.apps.y"}
    assert desktop.workdir("/p/demo/.vscode/project.code-workspace") == "/p/demo"
    assert desktop.workdir("/p/demo/work/repo") == "/p/demo/work/repo"


def test_config_is_validated():
    bad = schema.validate_config({"desktop": {"wm": "kde", "idle_min": 0, "geometry": "big",
                                              "env": {"X": True}, "unset": "A", "nope": 1}})
    fields = {p.field for p in bad}
    assert {"desktop.wm", "desktop.idle_min", "desktop.geometry", "desktop.env",
            "desktop.unset"} <= fields
    assert not schema.validate_config({"desktop": {"enabled": True, "env": {"A": "1"}}})


# --- xproxy with a stand-in Xvnc ----------------------------------------------------------

async def _talk(path, data, want):
    r, w = await asyncio.open_unix_connection(path)
    w.write(data)
    await w.drain()
    got = b""
    while len(got) < want:
        chunk = await asyncio.wait_for(r.read(100), 5)
        if not chunk:
            break
        got += chunk
    return r, w, got


def test_x_starts_on_the_first_client_and_stops_when_idle(xdirs):
    now = [0.0]

    async def go():
        p = xproxy.Proxy(conf(idle_min=1), xdirs["state"], xdirs["priv"], key="k",
                         x_dir=xdirs["x_dir"], lock_dir=xdirs["lock_dir"], abstract=False,
                         clock=lambda: now[0])
        await p.serve()
        st = json.load(open(os.path.join(xdirs["state"], "desktop.json")))
        assert st["x"] == "stopped" and st["display"] == ":%d" % p.n and st["vnc"] == p.vnc
        assert os.stat(p.vnc).st_mode & 0o077 == 0          # ours alone
        # an X client: Xvnc starts, the bytes go through
        r, w, got = await _talk(os.path.join(xdirs["x_dir"], "X%d" % p.n), b"hello", 7)
        assert got == b"X:hello" and p.running()
        st = json.load(open(os.path.join(xdirs["state"], "desktop.json")))
        assert st["x"] == "running" and st["clients"] == 1 and st["apps"]
        # a viewer joins the same X server
        r2, w2, got2 = await _talk(p.vnc, b"", 12)
        assert got2 == b"RFB 003.008\n" and p.started == 1
        for wr in (w, w2):
            wr.close()
        await asyncio.sleep(0.2)
        assert not p.clients and p.viewers == 0
        idle = asyncio.ensure_future(p.idle_loop(every=0.02))
        await asyncio.sleep(0.1)
        assert p.running()                       # not idle long enough yet
        now[0] += 61
        for _ in range(100):
            if not p.running():
                break
            await asyncio.sleep(0.02)
        assert not p.running() and p.x == "stopped"
        # and the next client starts it again
        r, w, got = await _talk(os.path.join(xdirs["x_dir"], "X%d" % p.n), b"again", 7)
        assert got == b"X:again" and p.started == 2
        w.close()
        idle.cancel()
        p.close()
        assert not os.path.exists(p.lock) and not os.path.exists(p.vnc)
        assert json.load(open(os.path.join(xdirs["state"], "desktop.json")))["x"] == "ended"
    asyncio.run(go())
    argv = open(xdirs["x_dir"] + ".argv").read()
    assert "-SecurityTypes None" in argv and "-rfbport -1" in argv and "-nolisten tcp" in argv
    assert "-extension MIT-SHM" in argv            # xproxy can't carry SCM_RIGHTS


def test_the_apps_menu_starts_apps_in_the_servers_environment(xdirs, tmp_path):
    out = tmp_path / "app.json"
    work = tmp_path / "work"
    work.mkdir()
    apps = {"dump": {"cmd": "%s -c 'import json,os; json.dump([os.getcwd(), os.environ[\"DISPLAY\"], "
                             "os.environ[\"A\"]], open(\"%s\", \"w\"))'" % (sys.executable, out),
                     "label": "Dump"},
            "nope": {"cmd": "no-such-program --x", "label": "Nope"}}

    async def go():
        p = xproxy.Proxy(conf(apps=apps, cwd=str(work)), xdirs["state"], xdirs["priv"], key="k",
                         x_dir=xdirs["x_dir"], lock_dir=xdirs["lock_dir"], abstract=False)
        p.env, _ = xproxy.apply_env(os.environ, p.conf, p.n, p.xauth, "k")
        await p.serve()
        st = json.load(open(os.path.join(xdirs["state"], "desktop.json")))
        assert st["launchers"] == [{"name": "dump", "label": "Dump"}]   # nope isn't installed
        desktop.request_run(xdirs["state"], "nope")
        desktop.request_run(xdirs["state"], "dump")
        p.take_requests()
        assert len(p.launched) == 1 and p.launched[0].wait(10) == 0
        assert not os.listdir(os.path.join(xdirs["state"], desktop.RUN))   # each taken once
        p.close()
        return p.n
    n = asyncio.run(go())
    assert json.load(open(out)) == [str(work), ":%d" % n, "x:%d" % n]


def test_the_server_runs_under_the_display(xdirs, tmp_path):
    out = tmp_path / "env.json"
    child = [sys.executable, "-c", "import json,os,sys; json.dump(dict(os.environ), open(sys.argv[1], 'w'))",
             str(out)]

    async def go():
        return await xproxy.run(conf(), xdirs["state"], "k", child, priv=xdirs["priv"],
                                x_dir=xdirs["x_dir"], lock_dir=xdirs["lock_dir"], abstract=False)
    os.environ["SSH_ASKPASS"] = "/usr/bin/ask"
    try:
        assert asyncio.run(go()) == 0
    finally:
        del os.environ["SSH_ASKPASS"]
    env = json.load(open(out))
    assert env["DISPLAY"].startswith(":") and env["A"] == "x" + env["DISPLAY"]
    assert "SSH_ASKPASS" not in env and env["WPK_DESKTOP"] == "/desk/k/"
    applied = json.load(open(os.path.join(xdirs["state"], "desktop.env.json")))
    assert applied["env"] == {"A": "x" + env["DISPLAY"]} and applied["unset"] == ["SSH_ASKPASS"]
    assert json.load(open(os.path.join(xdirs["state"], "desktop.json")))["x"] == "ended"


def test_without_xvnc_the_server_still_runs(xdirs, tmp_path):
    out = tmp_path / "ran"
    child = [sys.executable, "-c", "import os,sys; open(sys.argv[1], 'w').write(os.environ.get('DISPLAY', '-'))",
             str(out)]
    code = asyncio.run(xproxy.run(conf(xvnc="no-such-xvnc"), xdirs["state"], "k", child))
    assert code == 0 and out.read_text() == os.environ.get("DISPLAY", "-")
    st = json.load(open(os.path.join(xdirs["state"], "desktop.json")))
    assert st["x"] == "unavailable" and "no-such-xvnc" in st["why"]
    assert desktop.live(xdirs["state"]) is None


@pytest.mark.skipif(not (shutil.which("Xvnc") and shutil.which("xdpyinfo")),
                    reason="TigerVNC's Xvnc and xdpyinfo are not installed")
def test_real_xvnc_through_the_proxy(xdirs, tmp_path):
    """The real thing, where installed: an X client through the proxy, with the cookie."""
    out = tmp_path / "out"
    child = ["sh", "-c", "xdpyinfo > %s 2>&1; echo rc=$? >> %s" % (out, out)]
    code = asyncio.run(xproxy.run(conf(xvnc="Xvnc"), xdirs["state"], "k", child))
    text = out.read_text()
    assert code == 0 and "rc=0" in text and "dimensions:    1600x1000" in text, text
    assert "MIT-SHM" not in text, text             # off: its fds can't cross the splice


# --- the IDE server under xproxy -------------------------------------------------------------

def _backend(home, cls_slot=False, transport="tcp-token"):
    from work_packet.dash.ide import Backends
    bs = Backends(home, dict(schema.IDE_DEFAULTS, web=True), argv=["fake-ide"], slot=cls_slot,
                  transport=transport)
    return bs.get(bs.register("/w/proj.code-workspace"))


def test_the_board_wraps_its_server_when_the_desktop_is_on(tmp_path):
    h = str(tmp_path)
    be = _backend(h)
    assert be.with_desktop(["srv"]) == ["srv"]          # off by default
    (tmp_path / "config.toml").write_text("[desktop]\nenabled = true\n")
    argv = be.with_desktop(["srv", "--x"])
    assert argv[:3] == [sys.executable, "-m", "work_packet.sched.xproxy"]
    assert argv[-3:] == ["--", "srv", "--x"] and argv[argv.index("--key") + 1] == be.key
    c = json.load(open(os.path.join(be.dir, desktop.CONF)))
    assert c["enabled"] and c["title"] == "proj"
    assert desktop.title("/p/demo/.vscode/project.code-workspace") == "demo"
    assert desktop.title("/p/demo/work/repo/") == "repo" and desktop.title("", "k") == "k"
    assert oct(os.stat(os.path.join(be.dir, desktop.CONF)).st_mode & 0o777) == "0o600"


def test_jobs_get_a_desktop_only_over_mtls(tmp_path):
    h = str(tmp_path)
    (tmp_path / "config.toml").write_text("[desktop]\nenabled = true\n")
    tcp = _backend(h, True, "tcp-token")
    assert "work_packet.sched.xproxy" not in tcp.job_argv()
    m = _backend(h, True, "mtls")
    argv = m.job_argv()
    i = argv.index("work_packet.sched.ide_job")
    assert "work_packet.sched.xproxy" in argv[i:]
    assert argv.index("work_packet.sched.xproxy") > argv.index("--")   # inside the job's server argv


# --- the relay's vnc.wpk route -------------------------------------------------------------------

def _rfb_server(path):
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)
    s.listen(4)

    def run():
        while True:
            try:
                c, _ = s.accept()
            except OSError:
                return
            c.sendall(b"RFB 003.008\n")
            d = c.recv(100)
            c.sendall(b"got:" + d)
            c.close()
    threading.Thread(target=run, daemon=True).start()
    return s


def test_the_relay_sends_vnc_wpk_to_the_desktop(tmp_path):
    from work_packet.sched import ide_tls
    pytest.importorskip("starlette")
    srv_dir = tempfile.mkdtemp(prefix="wpk-r")
    os.chmod(srv_dir, 0o700)
    home_ = tempfile.mkdtemp(prefix="wpk-h")
    vnc = os.path.join(srv_dir, "v")
    s = _rfb_server(vnc)
    try:
        key, crt = ide_tls.client_cert(home_)
        shutil.copy(crt, os.path.join(srv_dir, "client.crt"))
        sock = os.path.join(srv_dir, "ide")
        ide = socket.socket(socket.AF_UNIX)
        ide.bind(sock)
        ide.listen(4)
        p = subprocess.Popen([sys.executable, "-m", "work_packet.sched.ide_relay", "--sock", sock,
                              "--client-cert", crt, "--key-dir", os.path.join(srv_dir, "key"),
                              "--publish-dir", srv_dir, "--host", "127.0.0.1"])
        try:
            ep = os.path.join(srv_dir, "endpoint")
            t = time.time()
            while not os.path.exists(ep) and time.time() - t < 20:
                time.sleep(0.05)
            port = int(open(ep).read().strip().rpartition(":")[2])
            ctx = ide_tls.pinned_client_context(crt, key, os.path.join(srv_dir, "server.crt"))

            def through():
                t = ctx.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=5),
                                    server_hostname="vnc.wpk")
                try:
                    got = t.recv(12)
                    if got:
                        t.sendall(b"hi")
                        got += t.recv(100)
                    return got
                except (ConnectionError, OSError):
                    return b""
                finally:
                    t.close()
            assert through() == b""                      # no desktop.json: closed
            json.dump({"x": "stopped", "vnc": vnc}, open(os.path.join(srv_dir, "desktop.json"), "w"))
            assert through() == b"RFB 003.008\ngot:hi"
            json.dump({"x": "ended", "vnc": vnc}, open(os.path.join(srv_dir, "desktop.json"), "w"))
            assert through() == b""
        finally:
            p.terminate()
            p.wait(10)
            ide.close()
    finally:
        s.close()
        shutil.rmtree(srv_dir, ignore_errors=True)
        shutil.rmtree(home_, ignore_errors=True)


# --- the board's /desk/ -----------------------------------------------------------------------

def test_desk_page_state_and_bridge(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    from test_ide import _web_client
    from starlette.websockets import WebSocketDisconnect
    h = tempfile.mkdtemp(prefix="wpk-d")
    monkeypatch.setenv("WPK_HOME", h)
    s = None
    try:
        c, be, origin, tok = _web_client(h, tmp_path)
        try:
            r = c.get("/desk/%s/" % be.key)
            assert r.status_code == 200 and 'data-key="%s"' % be.key in r.text
            assert "/static/desk.js" in r.text and tok in r.text
            assert "<title>x — Desktop</title>" in r.text          # no open recorded: the folder
            from work_packet import ide_launch
            ide_launch.record_open(h, be.key, "demo", "1a2b3c4d5e6f", "me")
            r = c.get("/desk/%s/" % be.key)
            assert "<title>demo · 1a2b3c4d — Desktop</title>" in r.text
            assert 'href="/p/demo/1a2b3c4d5e6f"' in r.text
            assert c.get("/desk/000000000000/").status_code == 404
            st = c.get("/desk/%s/state" % be.key).json()
            assert st["desktop"] is False and "open the IDE" in st["why"]
            # a running server with a desktop: the bridge reaches its VNC socket
            be.running = lambda: True
            vnc = os.path.join(h, "v")
            s = _rfb_server(vnc)
            json.dump({"x": "stopped", "vnc": vnc, "display": ":20", "apps": [], "clients": 0,
                       "viewers": 0}, open(os.path.join(be.dir, "desktop.json"), "w"))
            st = c.get("/desk/%s/state" % be.key).json()
            assert st["desktop"] is True and st["display"] == ":20"
            # the Apps menu: only what xproxy says it can start, with the token
            hdr = dict(origin, **{"x-csrf-token": tok})
            assert c.post("/desk/%s/run" % be.key, data={"app": "terminal"},
                          headers=origin).status_code == 403
            r = c.post("/desk/%s/run" % be.key, data={"app": "terminal"}, headers=hdr)
            assert r.status_code == 404 and "terminal" in r.json()["why"]
            st_path = os.path.join(be.dir, "desktop.json")
            rec = json.load(open(st_path))
            rec["launchers"] = [{"name": "terminal", "label": "Terminal"}]
            json.dump(rec, open(st_path, "w"))
            r = c.post("/desk/%s/run" % be.key, data={"app": "terminal"}, headers=hdr)
            assert r.status_code == 202
            reqs = os.listdir(os.path.join(be.dir, desktop.RUN))
            assert len(reqs) == 1 and json.load(open(os.path.join(be.dir, desktop.RUN, reqs[0]))) == \
                {"app": "terminal"}
            with pytest.raises(WebSocketDisconnect):          # no token
                with c.websocket_connect("ws://127.0.0.1:7878/desk/%s/ws" % be.key, headers=origin) as ws:
                    ws.receive_bytes()
            with c.websocket_connect("ws://127.0.0.1:7878/desk/%s/ws?t=%s" % (be.key, tok), headers=origin,
                                     subprotocols=["binary"]) as ws:
                assert ws.receive_bytes() == b"RFB 003.008\n"
                assert be.clients == 1
                ws.send_bytes(b"hi")
                assert ws.receive_bytes() == b"got:hi"
        finally:
            c.__exit__(None, None, None)
    finally:
        if s is not None:
            s.close()
        shutil.rmtree(h, ignore_errors=True)

