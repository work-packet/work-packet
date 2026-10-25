"""The Starlette app behind ``wpk dash``.

GET routes only read. The POST routes are the actions of docs/interaction.md §5,
each one a call into ``work_packet.actions`` or ``project`` and nothing more.
"""

import logging
import os
import urllib.parse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect, WebSocketState

from .. import __about__, clock, registry
from . import data, tokens
from .guard import split_host

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "live.js"), "rb") as _fp:
    LIVE_JS = _fp.read()   # a file, not inline, so the CSP can be script-src 'self'
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pane.js"), "rb") as _fp:
    PANE_JS = _fp.read()   # scroll panes and log buttons, on every page
HERE = os.path.dirname(os.path.abspath(__file__))
# Served from the package: compose.js, shell.js and the vendored xterm.js (no CDN, the CSP
# is script-src 'self'). Name -> media type.
STATIC = {"compose.js": "text/javascript", "ide.js": "text/javascript", "new.js": "text/javascript", "shell.js": "text/javascript",
          "vendor/xterm.js": "text/javascript", "vendor/addon-fit.js": "text/javascript",
          "vendor/xterm.css": "text/css"}
REFRESH_S = 10
LIVE_MS = 3000             # the live view refreshes faster
log = logging.getLogger("wpk.dash")
UPLOAD_MAX = 16 << 20      # bytes of one uploaded input
PROCS_MAX = 60             # rows of the live view's Processes panel (a -j32 build has hundreds)


def _money(v):
    return "" if v is None else "$%.2f" % v if v >= 0.995 else "$%.3f" % v


def _secs(v):
    if v is None:
        return ""
    v = float(v)
    return "%.1fs" % v if v < 60 else "%dm %02ds" % (v // 60, v % 60)


def _bytes(n):
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0


def _tok(n):
    if n is None:
        return "-"
    return "%.1fM" % (n / 1e6) if n >= 10 ** 6 else "%.1fk" % (n / 1e3) if n >= 1000 else str(n)


def _pct(x):
    return "-" if x is None else "%.0f%%" % (100 * x)


def _when(dt):
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _view(request, default):
    """The transcript view asked for: ``?view=log``, or ``default``."""
    return "log" if request.query_params.get("view") == "log" else default


def create_app(home=None, runner=None, shells=None, ide_backend=None):
    """The app, reading the registry under ``home`` (default: ``WPK_HOME``).

    ``runner`` (``dash.runner.Runner``) is poked after every action that can
    make a packet due (dash-tasks.md §7). ``shells`` (``dash.shells.Shells``)
    serves the browser shell (§5); without it Compose has no shell pane.
    ``ide_backend`` (``dash.ide.Backend``) serves web VS Code under ``/ide/``
    when ``[ide] web`` is on (docs/vscode-plan.md §4)."""
    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))
    env.filters.update(money=_money, secs=_secs, when=_when, bytes=_bytes, tok=_tok, pct=_pct)
    stamp = max(os.path.getmtime(os.path.join(HERE, n)) for n in STATIC)
    env.globals.update(version=__about__.__version__, refresh_s=REFRESH_S,
                       asset_v="%s-%d" % (__about__.__version__, stamp),
                       columns=data.COLUMNS)

    def render(request, name, status=200, **ctx):
        ctx["user"] = request.scope.get("state", {}).get("user")
        ctx["csrf"] = request.scope.get("state", {}).get("csrf")
        ctx["flash"] = request.query_params.get("msg")
        ctx["flash_ok"] = request.query_params.get("ok") == "1"
        ctx["runner"] = runner is not None
        ctx.setdefault("ide", ide_config())
        ctx["ide_web"] = web_state(request, ctx["ide"])
        return HTMLResponse(env.get_template(name).render(**ctx), status_code=status)

    def ide_config():
        from .. import ide
        try:
            return ide.load_config(home)
        except registry.ConfigError:
            return {}

    def web_state(request, cfg):
        """``None`` (no web VS Code), ``"ok"``, or why the button is disabled."""
        from . import ide as dide
        if ide_backend is None or not cfg.get("web"):
            return None
        why = dide.available(cfg.get("code") or "code")
        if why:
            return why
        host = split_host(request.headers.get("host", ""))[0] or ""
        if request.url.scheme != "https" and host not in ("localhost", "127.0.0.1", "::1"):
            return "needs HTTPS: open the board as localhost (ssh -L) or turn on TLS"
        return "ok"

    def work_rows(e):
        """``[(name, is git, has a packet worktree)]`` for the project page's VS Code panel."""
        from .. import setup, workspace
        try:
            tg = setup.target(e["path"])
        except setup.SetupError:
            return []
        return [(n, workspace.is_git(os.path.join(tg.work, n)),
                 workspace.is_git(os.path.join(tg.packet_work, n))) for n in tg.entries()]

    def not_found(request, what):
        return render(request, "missing.html", status=404, what=what)

    def entry(request):
        try:
            return registry.get(request.path_params["project"], home)
        except (KeyError, OSError, ValueError, registry.ConfigError):
            return None

    async def board(request):
        cols, broken = data.board(home)
        return render(request, "board.html", cols=cols, broken=broken, live=True,
                      home=home or registry.home(),
                      burn=tokens.board(registry.entries(home)))

    async def project(request):
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        now = clock.now()
        nodes = data.tree(e, now)
        recent = sorted(((n, s) for n in nodes for s in n["steps"] if s["start"]),
                        key=lambda ns: ns[1]["start"], reverse=True)[:50]
        return render(request, "project.html", e=e, card=data.card(e, now), nodes=nodes,
                      recent=recent, tl=data.timeline(nodes, now), live=True,
                      settings=data.settings(e), tk=tokens.project(e, now),
                      work=work_rows(e))

    async def packet(request):
        e = entry(request)
        p = data.packet(e, request.path_params["wpid"]) if e else None
        if p is None:
            return not_found(request, "packet %s" % request.path_params["wpid"])
        return render(request, "packet.html", e=e, p=p, live=True,
                      tk=tokens.packet(e, request.path_params["wpid"]))

    async def step(request):
        e = entry(request)
        view = _view(request, "blocks")
        s = data.step(e, request.path_params["wpid"], request.path_params["step"], view) \
            if e else None
        if s is None:
            return not_found(request, "step %s" % request.path_params["step"])
        # A committed or failed step never changes, so only a running one refreshes.
        sd = os.path.join(e["path"], "packets", request.path_params["wpid"], "steps",
                          request.path_params["step"])
        return render(request, "step.html", e=e, s=s, view=view, tk=tokens.step(sd, s["meta"]),
                      live=s["info"]["outcome"] == "running")

    # --- actions (POST) ---------------------------------------------------------

    async def form(request):
        body = (await request.body()).decode("utf-8", "replace")
        return urllib.parse.parse_qs(body, keep_blank_values=True)

    def poke():
        if runner is not None:
            runner.poke()

    def back(url, out, poke_runner=True):
        if out.code == 0 and poke_runner:
            poke()
        q = urllib.parse.urlencode({"msg": out.msg, "ok": "1" if out.code == 0 else "0"})
        url, _, frag = url.partition("#")
        return RedirectResponse("%s?%s%s" % (url, q, "#" + frag if frag else ""), status_code=303)

    def who(request):
        from .. import executor
        return request.scope.get("state", {}).get("user") or executor._who()

    async def act(request):
        from .. import actions, executor
        from ..packet import Packet
        e = entry(request)
        wpid = request.path_params["wpid"]
        if e is None or data.packet(e, wpid) is None:
            return not_found(request, "packet %s" % wpid)
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0]
        pkt = Packet(os.path.join(e["path"], "packets", wpid))
        by, op, note = who(request), one("action"), one("note")
        if op in ("answer", "recommend"):
            answers = {k[2:]: v[0] for k, v in f.items() if k.startswith("a.") and v[0].strip()}
            out = await run_in_threadpool(actions.answer, pkt, answers, note,
                                          op == "recommend", by)
        elif op == "note":
            out = await run_in_threadpool(actions.note, pkt, note, by, one("wake") == "1")
        elif op in ("handoff", "pause", "resume"):
            out = await run_in_threadpool(executor.admin, pkt, op, note or None, None, by)
        else:
            out = executor.Outcome(executor.USAGE, "unknown action %r" % op)
        url = "/p/%s/%s" % (urllib.parse.quote(e["name"]), wpid)
        return back(url + "/live" if one("back") == "live" else url, out)

    async def ide_open(request):
        """Open a packet or a work folder in VS Code (docs/vscode-plan.md V2).

        A POST, because it writes the packet's workspace file. The answer is a
        page that follows the ``vscode://`` link: the CSP's form-action does not
        allow redirecting a form to another scheme."""
        from .. import ide
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        wpid, repo = one("wpid"), one("repo") or None
        go = one("go") or "desktop"                  # desktop | web, -packet: the worktree
        how, packet = go.split("-")[0], go.endswith("-packet") or one("packet") == "1"
        t = os.path.join(e["path"], "packets", wpid) if wpid else e["path"]
        paused = None
        if one("pause") == "1" and wpid:
            from .. import executor
            from ..packet import Packet
            paused = await run_in_threadpool(executor.admin, Packet(t), "pause", None, None,
                                             who(request))
            if paused.code != 0:
                url = "/p/%s/%s" % (urllib.parse.quote(e["name"]), wpid)
                return back(url, paused, poke_runner=False)
        try:
            cfg = ide.load_config(home)
            op = await run_in_threadpool(ide.resolve, t, repo, packet)
        except (ide.IdeError, registry.ConfigError) as ex:
            from .. import executor
            url = "/p/%s" % urllib.parse.quote(e["name"]) + ("/%s" % wpid if wpid else "")
            return back(url, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        if how == "web":
            if web_state(request, cfg) != "ok":
                return not_found(request, "web VS Code here (%s)" % (
                    web_state(request, cfg) or "[ide] web is off"))
            return RedirectResponse(ide.web_path(op, "/ide/"), status_code=303)
        st = request.scope.get("state", {})
        name = None
        if st.get("listener") == "tailnet":     # the name the browser used: it resolves there
            name = split_host(request.headers.get("host", ""))[0]
        host = ide.ssh_host(cfg, name=name)
        links = {"remote": ide.desktop_url(op, host), "local": ide.desktop_url(op)}
        first = ide.desktop_choice(cfg, st.get("listener"), request.headers.get("user-agent"))
        return render(request, "ide_open.html", e=e, op=op, wpid=wpid, paused=paused,
                      links=links, first=first, host=host)

    async def configure(request):
        from .. import executor, project as project_mod
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        op, by = one("action"), who(request)
        try:
            if op == "allow" and one("tool"):
                ch = await run_in_threadpool(project_mod.allow, e["path"], [one("tool")], by)
            elif op == "deny" and one("tool"):
                ch = await run_in_threadpool(project_mod.deny, e["path"], [one("tool")], by)
            elif op == "set" and one("key"):
                ch = await run_in_threadpool(project_mod.set_values, e["path"],
                                             [(one("key"), one("value"))], by)
            else:
                raise project_mod.ProjectError("nothing to do")
            out = executor.Outcome(executor.OK, "; ".join(ch) or "nothing to change")
        except project_mod.ProjectError as ex:
            out = executor.Outcome(executor.USAGE, str(ex))
        url = compose_url(e, "#settings") if one("back") == "compose" else \
            "/p/%s" % urllib.parse.quote(e["name"])
        return back(url, out, poke_runner=False)

    # --- new task and Compose (docs/dash-tasks.md §3, §4) ---------------------------

    def compose_url(e, frag=""):
        return "/p/%s/compose%s" % (urllib.parse.quote(e["name"]), frag)

    async def new_form(request):
        es = registry.entries(home)
        recent = sorted(es, key=lambda x: x.get("created") or "", reverse=True)
        base = os.path.dirname(recent[0]["path"]) if recent else os.path.expanduser("~")
        try:
            cfg = registry.load_config(home)
        except registry.ConfigError:
            cfg = {"model": "", "harness": "claude"}
        return render(request, "new.html", projects=es, base=base, model=cfg["model"],
                      harness=cfg["harness"], choices=data.model_choices(home),
                      new_name=request.query_params.get("name", ""))

    async def new_create(request):
        from .. import executor, project as project_mod, setup
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        name, where, src = one("name"), one("dir"), one("from")
        hn = one("harness")

        def make():
            from .. import harness as harness_mod
            copy = None
            if src:
                se = registry.get(src, home)
                if se is None:
                    raise project_mod.ProjectError("no registered project named %r" % src)
                copy = setup.copy_setup(project_mod.load_project(se["path"]), name, se["path"])
            if hn and hn not in harness_mod.names():
                raise project_mod.ProjectError("no harness %r; there are: %s" % (
                    hn, ", ".join(harness_mod.names())))
            if hn and hn != registry.load_config(home)["harness"]:
                copy = dict(copy or {}, harness=hn)
            path = os.path.join(os.path.expanduser(where), name) if where else None
            return project_mod.new(name, None, path=path, model=one("model") or None,
                                   extra=copy, h=home)
        try:
            plan = await run_in_threadpool(make)
        except (project_mod.ProjectError, setup.SetupError, registry.ConfigError, ValueError,
                OSError) as ex:
            q = urllib.parse.urlencode({"msg": str(ex), "ok": "0", "name": name})
            return RedirectResponse("/new?" + q, status_code=303)
        e = {"name": plan.name}
        return back(compose_url(e), executor.Outcome(
            executor.OK, "created %s at %s; held for setup" % (plan.name, plan.path)))

    async def compose(request):
        from .. import setup
        e = entry(request)
        c = await run_in_threadpool(data.compose, e) if e else None
        if c is None:
            return not_found(request, "project %s" % request.path_params["project"])
        tpl = request.query_params.get("template")
        if tpl:
            try:
                c["instruction"] = setup.template_text(c["tg"], tpl)
                c["from_template"] = tpl
            except setup.SetupError:
                pass
        elif request.query_params.get("last") == "1":
            c["instruction"] = c["last_instruction"]
        return render(request, "compose.html", e=e, c=c, settings=data.settings(e),
                      shells=shells.of_project(e["name"]) if shells else [],
                      shell_ok=shells is not None)

    async def compose_post(request):
        from .. import actions, executor, setup
        e = entry(request)
        c = await run_in_threadpool(data.compose, e) if e else None
        if c is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0]
        op, by, tg = one("action"), who(request), c["tg"]
        text, note = one("instruction"), one("note").strip()
        archive = one("archive") == "1" if c["mode"] == "next" else None
        carry, force = one("carry") == "1", one("force") == "1"
        if not c["owned"]:
            return back(compose_url(e), executor.Outcome(executor.NOT_RUNNABLE, (
                "the runner has it (%s%s); pause it first" % (
                    c["state"], ", step running" if c["running"] else ""))))

        def save():
            if c["mode"] == "setup":
                if text.strip() and text != c["instruction"]:
                    return "; ".join(setup.instruct(tg, text))
                return "instruction unchanged"
            actions.save_draft(tg.packet, text, note, archive, carry)
            return "draft saved"
        try:
            if op == "save":
                out = executor.Outcome(executor.OK, await run_in_threadpool(save))
                return back(compose_url(e), out, poke_runner=False)
            if op == "fix":
                cid = one("check")
                hit = [ch for g in c["groups"] for ch in g["checks"] if ch.id == cid]
                if not hit or not hit[0].safe or not hit[0].fix:
                    raise setup.SetupError("no safe fix for %r; type it in the shell" % cid)
                r = await run_in_threadpool(setup.run_fix, hit[0].fix[0], tg.proj)
                tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or [""]
                out = executor.Outcome(executor.OK if r.returncode == 0 else executor.USAGE,
                                       "%s: %s" % (hit[0].fix[0], tail[0] or "exit %d"
                                                   % r.returncode))
                return back(compose_url(e), out, poke_runner=False)
            if op == "rm-input":
                rel = os.path.normpath(one("path"))
                p = os.path.join(tg.state, rel)
                if rel.startswith("..") or os.path.isabs(rel) or not os.path.isfile(p):
                    raise setup.SetupError("no input %r" % one("path"))
                os.unlink(p)
                return back(compose_url(e, "#inputs"), executor.Outcome(
                    executor.OK, "removed state/%s" % rel), poke_runner=False)
            if op == "handoff":
                await run_in_threadpool(save)
                if c["mode"] == "setup":
                    if c["missing"] and not force:
                        raise setup.SetupError("%d check%s missing; fix them or hand off "
                                               "anyway" % (c["missing"], "" if c["missing"]
                                                           == 1 else "s"))
                    out = await run_in_threadpool(executor.admin, tg.packet, "handoff",
                                                  note or None, None, by)
                else:
                    out = await run_in_threadpool(
                        actions.continue_, tg.packet, text, note or None, archive, carry,
                        force, by)
                if out.code == 0 and shells is not None:
                    n = shells.close_project(e["name"])
                    if n:
                        out = executor.Outcome(out.code, "%s; closed %d shell%s" % (
                            out.msg, n, "" if n == 1 else "s"))
                url = "/p/%s/%s/live" % (urllib.parse.quote(e["name"]), tg.packet.wpid) \
                    if out.code == 0 else compose_url(e)
                return back(url, out)
            raise setup.SetupError("unknown action %r" % op)
        except (setup.SetupError, OSError) as ex:
            return back(compose_url(e), executor.Outcome(executor.USAGE, str(ex)))

    async def compose_upload(request):
        import tempfile
        from .. import executor, setup
        e = entry(request)
        c = await run_in_threadpool(data.compose, e) if e else None
        if c is None:
            return not_found(request, "project %s" % request.path_params["project"])
        if not c["owned"]:
            return back(compose_url(e, "#inputs"), executor.Outcome(
                executor.NOT_RUNNABLE, "the runner has it; pause it first"))
        msgs = []
        async with request.form(max_files=50, max_part_size=UPLOAD_MAX) as fm:
            ups = [u for u in fm.getlist("files") if getattr(u, "filename", None)]
            with tempfile.TemporaryDirectory() as td:
                paths = []
                for u in ups:
                    nm = os.path.basename(u.filename.replace("\\", "/"))
                    if not nm or nm.startswith("."):
                        continue
                    p = os.path.join(td, nm)
                    with open(p, "wb") as fp:
                        fp.write(await u.read())
                    paths.append(p)
                try:
                    msgs = await run_in_threadpool(setup.add_input, c["tg"], paths, False,
                                                   fm.get("force") == "1")
                    out = executor.Outcome(executor.OK, "; ".join(msgs) or "no files")
                except setup.SetupError as ex:
                    out = executor.Outcome(executor.USAGE, str(ex))
        return back(compose_url(e, "#inputs"), out, poke_runner=False)

    # --- the shell (docs/dash-tasks.md §5) ------------------------------------------

    async def shell_ws(ws):
        import asyncio
        import hmac
        import json
        from .. import setup
        from . import shells as shells_mod
        await ws.accept()
        st = ws.scope.get("state", {})
        try:
            first = await asyncio.wait_for(ws.receive_text(), 5)
            token = (json.loads(first) or {}).get("token") or ""
        except (asyncio.TimeoutError, ValueError, KeyError, TypeError, WebSocketDisconnect):
            token = ""
        want = st.get("csrf") or ""
        if shells is None or not want or not hmac.compare_digest(token, want):
            log.warning("refused a shell for %s: %s", ws.path_params.get("project"),
                        "no shells here" if shells is None else "wrong or missing token")
            return await ws.close(1008)
        e = entry(ws)
        sid = ws.path_params["sid"]
        if e is None:
            return await ws.close(1008)
        if sid == "new":
            c = await run_in_threadpool(data.compose, e)
            if c is None or not c["owned"]:
                await ws.send_text(json.dumps({"error": "the runner has this task; "
                                               "no shell until it is yours again"}))
                return await ws.close(1000)
            tg = c["tg"]
            env = setup.shell_env(tg, {"TERM": "xterm-256color", "WPK_SHELL": "web"})
            env.pop("COLUMNS", None), env.pop("LINES", None)
            try:
                sess = shells.open(e["name"], setup.shell_argv(tg, shells_mod.HOOK),
                                   c["shell_dir"], env, st.get("user") or "?",
                                   os.path.join(tg.setup_dir, "shells.log"))
            except (shells_mod.ShellError, OSError) as ex:
                await ws.send_text(json.dumps({"error": str(ex)}))
                return await ws.close(1000)
        else:
            sess = shells.get(sid)
            if sess is None or sess.project != e["name"]:
                await ws.send_text(json.dumps({"gone": True}))
                return await ws.close(1000)
        queue, replay = shells.attach(sess)
        await ws.send_text(json.dumps({"sid": sess.sid, "cwd": sess.cwd}))
        if replay:
            await ws.send_bytes(replay)

        async def pump():
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        return
                    kind, val = item
                    if kind == "data":
                        await ws.send_bytes(val)
                    else:
                        await ws.send_text(json.dumps(val))
            except (WebSocketDisconnect, RuntimeError, OSError):
                return                  # the page went away; the session stays
        out = asyncio.ensure_future(pump())
        try:
            while not out.done():
                rx = asyncio.ensure_future(ws.receive())
                done, _ = await asyncio.wait({rx, out}, return_when=asyncio.FIRST_COMPLETED)
                if rx not in done:
                    rx.cancel()
                    break
                msg = rx.result()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    shells.write(sess, msg["bytes"])
                elif msg.get("text"):
                    try:
                        ctl = json.loads(msg["text"])
                    except ValueError:
                        continue
                    if "resize" in ctl:
                        cols, rows = ctl["resize"]
                        shells.resize(sess, int(cols), int(rows))
                    elif "input" in ctl:
                        shells.write(sess, str(ctl["input"]).encode("utf-8"))
                    elif ctl.get("close"):
                        shells.close(sess.sid)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            shells.detach(sess, queue)
            out.cancel()
            if ws.client_state == WebSocketState.CONNECTED and \
                    ws.application_state == WebSocketState.CONNECTED:
                try:
                    await ws.close()
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass

    async def shell_close(request):
        from .. import executor
        e = entry(request)
        if e is None or shells is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        sid = (f.get("sid") or [""])[0]
        sess = shells.get(sid)
        ok = sess is not None and sess.project == e["name"] and shells.close(sid)
        return back(compose_url(e), executor.Outcome(
            executor.OK if ok else executor.USAGE, "shell closed" if ok else "no such shell"),
            poke_runner=False)

    async def live_view(request):
        e = entry(request)
        view = _view(request, "feed")
        lv = data.live(e, request.path_params["wpid"], view=view) if e else None
        if lv is None:
            return not_found(request, "packet %s" % request.path_params["wpid"])
        return render(request, "live.html", e=e, l=lv, view=view, live=True,
                      refresh_ms=LIVE_MS, procs_max=PROCS_MAX)

    async def raw(request):
        e = entry(request)
        wpid, d = request.path_params["wpid"], request.path_params["step"]
        if e is None or not data.schema.is_wpid(wpid) or data.schema.parse_step_dir(d) is None:
            return not_found(request, "step %s" % d)
        p = os.path.join(e["path"], "packets", wpid, "steps", d, "transcript.jsonl")
        text = data._read(p)
        if text is None:
            return not_found(request, "transcript of step %s" % d)
        return PlainTextResponse(text, media_type="application/x-ndjson; charset=utf-8",
                                 headers={"content-disposition": 'inline; filename="%s-%s.jsonl"'
                                          % (wpid[:8], d)})

    async def log_txt(request):
        e = entry(request)
        wpid, d = request.path_params["wpid"], request.path_params["step"]
        if e is None or not data.schema.is_wpid(wpid) or data.schema.parse_step_dir(d) is None:
            return not_found(request, "step %s" % d)
        p = os.path.join(e["path"], "packets", wpid, "steps", d, "transcript.jsonl")
        if not os.path.isfile(p):
            return not_found(request, "transcript of step %s" % d)
        return PlainTextResponse(data.log_text(data.log(p, limit=None)),
                                 headers={"content-disposition": 'inline; filename="%s-%s.log"'
                                          % (wpid[:8], d)})

    async def pane_js(request):
        return Response(PANE_JS, media_type="text/javascript",
                        headers={"cache-control": "max-age=300"})

    async def health(request):
        return PlainTextResponse("ok\n")

    async def static(request):
        name = request.path_params["name"]
        if name not in STATIC:
            return PlainTextResponse("not found\n", status_code=404)
        try:
            with open(os.path.join(HERE, name), "rb") as fp:
                body = fp.read()
        except OSError:
            return PlainTextResponse("not found\n", status_code=404)
        return Response(body, media_type=STATIC[name], headers={"cache-control": "max-age=300"})

    async def live_js(request):
        return Response(LIVE_JS, media_type="text/javascript",
                        headers={"cache-control": "max-age=300"})

    async def ide_http(request):
        from . import ide as dide
        if ide_backend is None or not ide_config().get("web"):
            return PlainTextResponse("not found\n", status_code=404)
        return await dide.proxy_http(ide_backend, request)

    async def ide_ws(websocket):
        from . import ide as dide
        if ide_backend is None or not ide_config().get("web"):
            return await websocket.close(1008)
        return await dide.proxy_ws(ide_backend, websocket)

    return Starlette(routes=[
        Route("/ide/{rest:path}", ide_http,
              methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
        WebSocketRoute("/ide/{rest:path}", ide_ws),
        Route("/", board),
        Route("/healthz", health),
        Route("/static/live.js", live_js),
        Route("/static/pane.js", pane_js),
        Route("/static/{name:path}", static),
        Route("/new", new_form),
        Route("/new", new_create, methods=["POST"]),
        Route("/p/{project}/compose", compose),
        Route("/p/{project}/compose", compose_post, methods=["POST"]),
        Route("/p/{project}/compose/upload", compose_upload, methods=["POST"]),
        Route("/p/{project}/shell/close", shell_close, methods=["POST"]),
        WebSocketRoute("/p/{project}/shell/{sid}", shell_ws),
        Route("/p/{project}/settings", configure, methods=["POST"]),
        Route("/p/{project}/ide", ide_open, methods=["POST"]),
        Route("/p/{project}/{wpid}/act", act, methods=["POST"]),
        Route("/p/{project}/{wpid}/live", live_view),
        Route("/p/{project}/{wpid}/{step}/raw", raw),
        Route("/p/{project}/{wpid}/{step}/log.txt", log_txt),
        Route("/p/{project}", project),
        Route("/p/{project}/{wpid}", packet),
        Route("/p/{project}/{wpid}/{step}", step),
    ])

