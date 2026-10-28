"""The Starlette app behind ``wpk dash``.

GET routes only read. The POST routes are the actions of docs/interaction.md §5,
each one a call into ``work_packet.actions`` or ``project`` and nothing more.
"""

import logging
import os
import shutil
import threading
import urllib.parse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                                 RedirectResponse, Response)
from starlette.middleware import Middleware
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect, WebSocketState

from .. import __about__, archived, clock, layout, livecard, registry
from . import data, markup, plan, tokens
from . import sched as dsched
from ..sched.classes import CLASSES
from .guard import split_host

FILE_MAX = 4 * 1024 * 1024    # bytes of a deliverable the page serves

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "live.js"), "rb") as _fp:
    LIVE_JS = _fp.read()   # a file, not inline, so the CSP can be script-src 'self'
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pane.js"), "rb") as _fp:
    PANE_JS = _fp.read()   # scroll panes and log buttons, on every page
HERE = os.path.dirname(os.path.abspath(__file__))
# Served from the package: compose.js, shell.js and the vendored xterm.js (no CDN, the CSP
# is script-src 'self'). Name -> media type.
STATIC = {"board.js": "text/javascript", "packets.js": "text/javascript", "sched.js": "text/javascript", "compose.js": "text/javascript", "ide.js": "text/javascript", "new.js": "text/javascript", "shell.js": "text/javascript", "markup.js": "text/javascript",
          "vendor/xterm.js": "text/javascript", "vendor/addon-fit.js": "text/javascript",
          "vendor/xterm.css": "text/css"}
REFRESH_S = 10
LIVE_MS = 3000             # the live view refreshes faster
log = logging.getLogger("wpk.dash")
UPLOAD_MAX = 16 << 20      # bytes of one uploaded input
PROCS_MAX = 60             # rows of the live view's Processes panel (a -j32 build has hundreds)


def _inline(text):
    """One line of Markdown as HTML (the text as it is without markdown-it)."""
    h = data.md_inline(text)
    return Markup(h) if h is not None else text


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


def ask_text(rel):
    """The note or instruction that asks for the markup in ``rel`` to be resolved."""
    return ("Resolve the CriticMarkup in %s: make each change it suggests "
            "({++ insert ++}, {-- delete --}, {~~ old ~> new ~~}) or say why not, answer "
            "each comment ({== text ==}{>> comment <<}), then remove the markup." % rel)


def create_app(home=None, runner=None, shells=None, ide_backend=None):
    """The app, reading the registry under ``home`` (default: ``WPK_HOME``).

    ``runner`` (``dash.runner.Runner``) is poked after every action that can
    make a packet due (dash-tasks.md §7). ``shells`` (``dash.shells.Shells``)
    serves the browser shell (§5); without it Compose has no shell pane.
    ``ide_backend`` (``dash.ide.Backends``) serves web VS Code under ``/ide/<key>/``
    when ``[ide] web`` is on (docs/vscode-plan.md §4)."""
    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))
    env.filters.update(inline=_inline, money=_money, secs=_secs, when=_when, bytes=_bytes, tok=_tok, pct=_pct)
    stamp = max(os.path.getmtime(os.path.join(HERE, n)) for n in STATIC)
    env.globals.update(origin_of=data.origin, version=__about__.__version__, refresh_s=REFRESH_S,
                       asset_v="%s-%d" % (__about__.__version__, stamp),
                       columns=data.COLUMNS, ask_text=ask_text)

    def render(request, name, status=200, **ctx):
        ctx["user"] = request.scope.get("state", {}).get("user")
        ctx["csrf"] = request.scope.get("state", {}).get("csrf")
        ctx["signout"] = request.scope.get("state", {}).get("listener") == "network"
        ctx["flash"] = request.query_params.get("msg")
        ctx["flash_ok"] = request.query_params.get("ok") == "1"
        ctx["runner"] = runner is not None
        try:
            ctx["sched_mode"] = dsched.mode(home)
        except Exception:                 # noqa: BLE001: a banner never breaks a page
            ctx["sched_mode"] = None
        ctx.setdefault("ide", ide_config())
        ctx["ide_sizes"] = ide_sizes() if getattr(ide_backend, "slot", False) else []
        ctx["ide_web"] = web_state(request, ctx["ide"])
        return HTMLResponse(env.get_template(name).render(**ctx), status_code=status)

    def ide_sizes():
        from ..sched import config as sconfig
        try:
            return list(sconfig.sizes(sconfig.load(home)))
        except registry.ConfigError:
            return []

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
        # A server in a job runs on a node: its program is checked there (wpk sched doctor).
        why = None if getattr(ide_backend, "slot", False) else dide.available(cfg)
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
            return archived.get(request.path_params["project"], home)
        except (KeyError, OSError, ValueError, registry.ConfigError):
            return None

    async def overview(request):
        """The Overview (``/``): how every board is doing, what needs you, token use
        over ``?days=`` 1, 7 or 30 (docs/overview.md)."""
        try:
            days = int(request.query_params.get("days", 7))
        except ValueError:
            days = 7
        days = days if days in tokens.WINDOWS else 7
        cols, broken = data.board(home)
        side = data.side(home, cols, broken)
        burn = tokens.board(archived.entries(home), days=days, on=[b["name"] for b in side])
        ov = data.overview(cols, broken, side, burn)
        snap = await run_in_threadpool(dsched.snapshot, home)
        return render(request, "overview.html", ov=ov, burn=burn, broken=broken, live=True,
                      sch=dsched.tiles(snap),
                      home=home or registry.home(), side=side, here=None,
                      windows=tokens.WINDOWS, main_board=registry.DEFAULT_BOARD)

    async def board(request):
        """One board (``/b/{board}``; docs/boards.md): its cards."""
        name = request.path_params["board"]
        cols, broken = data.board(home)
        side = data.side(home, cols, broken)
        here = next((b for b in side if b["name"] == name), None)
        if here is None:
            return not_found(request, "board %s" % name)
        cols, broken = data.only(cols, broken, name)
        snap = await run_in_threadpool(dsched.snapshot, home)
        watchers = await run_in_threadpool(data.watchers, home, name)
        return render(request, "board.html", cols=cols, broken=broken, live=True,
                      waiting=dsched.waiting(snap), watchers=watchers,
                      side=side, here=here, main_board=registry.DEFAULT_BOARD)

    async def all_packets(request):
        """Every packet on every board, to sort and search (docs/boards.md)."""
        rows = []
        cols, broken = data.board(home, rows=rows)
        states = sorted({r["state"] for r in rows}, key=str)
        snap = await run_in_threadpool(dsched.snapshot, home)
        cls = {}
        for e in archived.entries(home):
            for r in rows:
                if r["project"] == e["name"]:
                    cls[r["wpid"]] = dsched.packet_info(snap, e, r["wpid"])
        return render(request, "packets.html", rows=rows, broken=broken, states=states,
                      sch=cls, classes=CLASSES, sizes=list((snap or {}).get("sizes", {})),
                      boards=registry.boards(home),
                      side=data.side(home, cols, broken), live=True)

    def local(url, default="/"):
        """A page of this board to go back to: a path, without its query (the flash)."""
        url = (url or "").split("?")[0].split("#")[0]
        ok = url.startswith("/") and not url.startswith("//") and "\\" not in url
        return url if ok else default

    async def board_new(request):
        from .. import executor
        f = await form(request)
        name = (f.get("name") or [""])[0].strip()
        try:
            await run_in_threadpool(registry.new_board, name, None, home)
        except (registry.BoardError, OSError) as ex:
            return back(local((f.get("back") or [""])[0]),
                        executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        return back("/b/%s" % urllib.parse.quote(name),
                    executor.Outcome(executor.OK, "made board %s" % name), poke_runner=False)

    async def board_delete(request):
        from .. import executor
        name = request.path_params["board"]
        try:
            moved = await run_in_threadpool(registry.delete_board, name, home)
        except (registry.BoardError, OSError) as ex:
            return back("/b/%s" % urllib.parse.quote(name),
                        executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        msg = "deleted board %s" % name
        if moved:
            msg += "; %s moved to %s" % (", ".join(moved), registry.DEFAULT_BOARD)
        return back("/", executor.Outcome(executor.OK, msg), poke_runner=False)

    async def watch_poll(request):
        """Poll a board's watcher now (docs/starters-v1.md)."""
        from .. import executor, watch
        board, name = request.path_params["board"], request.path_params["name"]
        url = "/b/%s#watchers" % urllib.parse.quote(board)
        try:
            [w] = await run_in_threadpool(watch.find, "%s/%s" % (board, name), home)
            r = await run_in_threadpool(watch.poll, w, home)
        except (watch.WatchError, ValueError, OSError) as ex:
            return back(url, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        said = ["made %s" % ", ".join(n for _, n in r["made"])] if r["made"] else []
        said += ["%s: %s" % kv for kv in r["failed"].items()] + r["errors"]
        ok = not (r["failed"] or r["errors"])
        return back(url, executor.Outcome(executor.OK if ok else executor.USAGE,
                                          "; ".join(said) or "nothing new"),
                    poke_runner=bool(r["made"]))

    async def board_move(request):
        """Put a project on another board: a drop on the side tab, or the project page's select."""
        from .. import executor
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        to = (f.get("board") or [""])[0].strip()
        url = local((f.get("back") or [""])[0], "/p/%s" % urllib.parse.quote(e["name"]))
        try:
            was = await run_in_threadpool(registry.move, e["name"], to, home)
        except (registry.BoardError, OSError) as ex:
            return back(url, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        msg = "%s is on %s already" % (e["name"], to) if was == to else \
            "moved %s from %s to %s" % (e["name"], was, to)
        return back(url, executor.Outcome(executor.OK, msg), poke_runner=False)

    async def pr_open(request):
        """Hand the packet back to its forge: push, open (or find) the pull request."""
        from .. import executor, pr
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        url = "/p/%s" % urllib.parse.quote(e["name"])
        try:
            r = await run_in_threadpool(pr.open_pr, e["name"], home,
                                        draft=(f.get("draft") or [""])[0] == "1", by=who(request))
        except pr.PRError as ex:
            return back(url, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        await run_in_threadpool(pr.forget_failure, e["name"], home)
        return back(url, executor.Outcome(executor.OK, "%s %s" % (
            "opened" if r["new"] else "pushed; already open:", r["url"])), poke_runner=False)

    # --- the scheduler (docs/scheduler.md §9) ------------------------------------

    async def sched_page(request):
        snap = await run_in_threadpool(dsched.snapshot, home)
        ch = await run_in_threadpool(dsched.chart, snap, home) if snap else None
        cols, broken = data.board(home)
        return render(request, "sched.html", snap=snap, chart=ch, live=True,
                      lines=None if snap else ["the config cannot be read"],
                      events=dsched.recent(home), modes=dsched.MODES,
                      side=data.side(home, cols, broken))

    async def sched_json(request):
        snap = await run_in_threadpool(dsched.snapshot, home)
        if snap is None:
            return JSONResponse({"error": "the config cannot be read"}, status_code=500)
        return JSONResponse(snap)

    def denied(request, action, target=None):
        """A 403 page if the requester may not ``action``, else None."""
        from ..sched import authz
        try:
            authz.check(authz.principal_of(request), action, target, home)
        except authz.Denied as ex:
            return render(request, "missing.html", status=403, what=None, why=str(ex))
        return None

    async def sched_mode(request):
        from ..sched import authz, control
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        no = denied(request, "mode")
        if no:
            return no
        m = {"halt": "drain", "drain": "drain", "stop": "stop", "resume": "run",
             "run": "run"}.get(one("mode"))
        if m is None:
            from .. import executor
            return back("/sched", executor.Outcome(executor.USAGE, "unknown mode"),
                        poke_runner=False)
        out = await run_in_threadpool(control.set_mode, m, authz.principal_of(request),
                                      one("reason") or None, home)
        return back(local(one("back"), "/sched"), out)

    def setter(what):
        async def handle(request):
            return await sched_set(request, what)
        return handle

    async def sched_set(request, what):
        """``/p/<project>/{prio,size,hold}`` and ``/p/<project>/<wpid>/{prio,size,next}``."""
        from ..sched import authz, control
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        wpid = request.path_params.get("wpid")
        if wpid is not None and data.packet(e, wpid) is None:
            return not_found(request, "packet %s" % wpid)
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        action = {"prio": "prio", "size": "size", "hold": "hold", "next": "next"}.get(what)
        if action is None or (what == "hold" and wpid) or (what == "next" and not wpid):
            return not_found(request, "%s here" % what)
        no = denied(request, action, wpid or e["name"])
        if no:
            return no
        by = authz.principal_of(request)
        target, value = wpid or e["name"], one("value") or None
        if what == "prio":
            fn = (control.set_prio, target, value, by, home)
        elif what == "size":
            fn = (control.set_size, target, value, by, home)
        elif what == "next":
            fn = (control.run_next, target, by, home, value != "off")
        elif value == "release":
            fn = (control.release, target, by, home)
        else:
            fn = (control.hold, target, by, one("reason") or None, home)
        out = await run_in_threadpool(*fn)
        url = "/p/%s" % urllib.parse.quote(e["name"]) + ("/%s" % wpid if wpid else "")
        return back(local(one("back"), url), out)

    async def bulk(request):
        """All packets: one action on the ticked packets (docs/boards.md B8)."""
        from .. import executor
        from ..packet import Packet
        from ..sched import authz, control
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        op, value = one("op"), one("value") or None
        picks = [p for p in f.get("pick") or () if "/" in p]
        if not picks:
            return back("/packets", executor.Outcome(executor.USAGE, "tick some packets first"),
                        poke_runner=False)
        to = one("board")
        if op == "board" and not to:
            return back("/packets", executor.Outcome(executor.USAGE, "pick a board to move to"),
                        poke_runner=False)
        action = {"prio": "prio", "size": "size", "hold": "hold"}.get(op)
        if action:
            no = denied(request, action)
            if no:
                return no
        by = authz.principal_of(request)
        lines, worst, held = [], 0, set()

        def run_one(project, wpid):
            e = archived.get(project, home)
            if e is None or data.packet(e, wpid) is None:
                return executor.Outcome(executor.USAGE, "%s/%s: not found" % (project, wpid[:8]))
            if op == "prio":
                return control.set_prio(wpid, value, by, home)
            if op == "size":
                return control.set_size(wpid, value, by, home)
            if op in ("pause", "resume"):
                pkt = Packet(layout.run_dir(e["path"], wpid))
                got = executor.admin(pkt, op, by=by)
                if op == "pause" and got.code == 0:
                    control.cancel_pending(wpid, by, home)
                return executor.Outcome(got.code, "%s %s" % (project, got.msg))
            if op == "hold":
                if project in held:
                    return None
                held.add(project)
                return control.hold(project, by, None, home)
            if op == "board":
                if project in held:             # a board holds projects: move each once
                    return None
                held.add(project)
                try:
                    was = registry.move(project, to, home)
                except (registry.BoardError, OSError) as ex:
                    return executor.Outcome(executor.USAGE, "%s: %s" % (project, ex))
                return executor.Outcome(executor.OK, "%s is on %s already" % (project, to)
                                        if was == to else "moved project %s from %s to %s"
                                        % (project, was, to))
            return executor.Outcome(executor.USAGE, "unknown action %r" % op)
        for p in picks:
            project, _, wpid = p.partition("/")
            out = await run_in_threadpool(run_one, project, wpid)
            if out is None:
                continue
            lines.append(out.msg)
            worst = max(worst, out.code)
        return back("/packets", executor.Outcome(worst, "\n".join(lines)), poke_runner=op != "board")

    def packet_top(e, now, nodes):
        """What every tab of the packet page needs: the card, with its counts by task."""
        ts = data.tasks(e, nodes)
        card = data.card(e, now, nodes)
        counts = {}
        for t in ts:
            counts[t["state"]] = counts.get(t["state"], 0) + 1
        card.update(tasks=len(ts), counts=sorted(counts.items(), key=lambda kv: str(kv[0])))
        return card, ts

    def project_page(tab):
        async def handle(request):
            e = entry(request)
            if e is None:
                return not_found(request, "project %s" % request.path_params["project"])
            now = clock.now()
            nodes = data.tree(e, now)
            card, ts = packet_top(e, now, nodes)
            kw = dict(e=e, card=card, nodes=nodes, tasks=ts, work=work_rows(e))
            return await tab(request, e, now, kw)
        return handle

    async def project_overview(request, e, now, kw):
        nodes = kw["nodes"]
        root = nodes[0] if nodes else None
        # A finished project leads with its root packet's completion report.
        rp = (data.packet(e, root["wpid"])
              if root and root["state"] in ("COMPLETED", "FAILED") else None)
        bs = registry.boards(home)
        from .. import questions
        from ..packet import Packet
        # Whatever in the tree is waiting on an answer leads the page, form and all.
        asks = [(n, qs) for n in nodes if n["state"] == "NEEDS_INPUT" and not n["running"]
                for qs in [questions.of_packet(Packet(n["path"]))] if qs]
        return render(request, "project.html", rp=rp, live=True, asks=asks,
                      on=registry.board_of(e, [b["name"] for b in bs]),
                      tl=data.timeline(kw["tasks"], now), **kw)

    async def project_tasks(request, e, now, kw):
        state = request.query_params.get("state", "")
        states = sorted({t["state"] for t in kw["tasks"]}, key=str)
        if state:
            kw["tasks"] = [t for t in kw["tasks"] if t["state"] == state]
        return render(request, "project_tasks.html", state=state, states=states, **kw)

    async def project_task(request, e, now, kw):
        try:
            n = int(request.path_params["n"])
        except ValueError:
            n = 0
        t = data.task(e, kw["tasks"], n)
        if t is None:
            return not_found(request, "task %s" % request.path_params["n"])
        return render(request, "task.html", t=t, live=bool(t["task"]["running"]), **kw)

    STEPS_PAGE = 50

    async def project_steps(request, e, now, kw):
        # Task keys: "<n>" for the root's tasks, a wpid for a child's.
        opts = [dict(t, key=str(t["n"]) if t["kind"] == "task" else t["wpid"],
                     label=t["name"] or t["short"]) for t in kw["tasks"]]
        task = request.query_params.get("task", "")
        match = [t for t in opts if t["key"] == task]
        task = task if match else ""
        pick = match or opts
        rows = sorted(((t, s) for t in pick for s in t["steps"] if s["start"]),
                      key=lambda ts: ts[1]["start"], reverse=True)
        pages = max(1, -(-len(rows) // STEPS_PAGE))
        try:
            page = min(max(1, int(request.query_params.get("page", "1"))), pages)
        except ValueError:
            page = 1
        kw["tasks"] = opts
        return render(request, "project_steps.html", task=task, total=len(rows), page=page,
                      pages=pages, steps=rows[(page - 1) * STEPS_PAGE:page * STEPS_PAGE], **kw)

    async def project_cost(request, e, now, kw):
        return render(request, "project_cost.html", tk=tokens.project(e, now), **kw)

    async def project_settings(request, e, now, kw):
        bs = registry.boards(home)
        snap = await run_in_threadpool(dsched.snapshot, home)
        return render(request, "project_settings.html", settings=data.settings(e),
                      sch=dsched.project_info(snap, e), classes=CLASSES, boards=bs,
                      on=registry.board_of(e, [b["name"] for b in bs]), **kw)

    async def packet(request):
        e = entry(request)
        p = data.packet(e, request.path_params["wpid"]) if e else None
        if p is None:
            return not_found(request, "packet %s" % request.path_params["wpid"])
        snap = await run_in_threadpool(dsched.snapshot, home)
        return render(request, "packet.html", e=e, p=p, live=True, classes=CLASSES,
                      sch=dsched.packet_info(snap, e, request.path_params["wpid"]),
                      tk=tokens.packet(e, request.path_params["wpid"]))

    async def step(request):
        e = entry(request)
        view = _view(request, "blocks")
        s = data.step(e, request.path_params["wpid"], request.path_params["step"], view) \
            if e else None
        if s is None:
            return not_found(request, "step %s" % request.path_params["step"])
        # A committed or failed step never changes, so only a running one refreshes.
        sd = os.path.join(layout.run_dir(e["path"], request.path_params["wpid"]), "steps",
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
        pkt = Packet(layout.run_dir(e["path"], wpid))
        by, op, note = who(request), one("action"), one("note")
        if op in ("answer", "recommend"):
            answers = {k[2:]: v[0] for k, v in f.items() if k.startswith("a.") and v[0].strip()}
            out = await run_in_threadpool(actions.answer, pkt, answers, note,
                                          op == "recommend", by)
        elif op == "note":
            out = await run_in_threadpool(actions.note, pkt, note, by, one("wake") == "1")
        elif op in ("handoff", "pause", "resume"):
            out = await run_in_threadpool(executor.admin, pkt, op, note or None, None, by)
            if op == "pause" and out.code == 0:
                from ..sched import authz, control
                await run_in_threadpool(control.cancel_pending, wpid,
                                        authz.principal_of(request), home)
        else:
            out = executor.Outcome(executor.USAGE, "unknown action %r" % op)
        url = "/p/%s/%s" % (urllib.parse.quote(e["name"]), wpid)
        if one("back") == "project":
            url = "/p/%s" % urllib.parse.quote(e["name"])
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
        t = layout.run_dir(e["path"], wpid) if wpid else e["path"]
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
            from . import ide as dide
            try:
                key = await run_in_threadpool(ide_backend.register, op.path,
                                              one("size") or None)
            except dide.IdeUnavailable as ex:
                return not_found(request, "web VS Code here (%s)" % ex)
            return RedirectResponse(ide.web_path(op, "/ide/%s/" % key), status_code=303)
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
            local(one("back"), "/p/%s/settings" % urllib.parse.quote(e["name"]))
        return back(url, out, poke_runner=False)

    # --- new task and Compose (docs/dash-tasks.md §3, §4) ---------------------------

    def compose_url(e, frag=""):
        return "/p/%s/compose%s" % (urllib.parse.quote(e["name"]), frag)

    def new_page(request, starter, values, preview=None, recipe=None, error=None, status=200):
        from .. import starters
        es = archived.entries(home)
        recent = sorted(es, key=lambda x: x.get("created") or "", reverse=True)
        base = os.path.dirname(layout.packet_folder(recent[0]["path"])) if recent \
            else os.path.expanduser("~")
        try:
            cfg = registry.load_config(home)
        except registry.ConfigError:
            cfg = {"model": "", "harness": "claude"}
        vals = dict(values)
        vals.setdefault("dir", base)
        st = starters.get(starter)
        return render(request, "new.html", status=status, projects=es, model=cfg["model"],
                      harness=cfg["harness"], choices=data.model_choices(home),
                      starters=[starters.get(n) for n in starters.names()], starter=st,
                      fields=st.all_fields(), values=vals, preview=preview,
                      recipe=starters.dumps(recipe) if recipe else "", error=error,
                      broken=starters.broken())

    def _starter_of(vals):
        from .. import starters
        n = vals.get("starter") or ("clone" if vals.get("clone") else "folder")
        return n if n in starters.names() else "folder"

    async def new_form(request):
        q = dict(request.query_params)
        q.pop("msg", None), q.pop("ok", None)
        return new_page(request, _starter_of(q), q)

    async def new_search(request):
        from .. import starters
        q = dict(request.query_params)
        try:
            st = starters.get(q.pop("starter", ""))
            got = await run_in_threadpool(st.search, q.pop("field", ""), q.pop("q", ""), q, home)
        except starters.StartError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        return JSONResponse({"choices": got})

    async def new_create(request):
        """New task (docs/starters-v1.md): a starter's values, previewed, then made."""
        from .. import executor, starters
        f = await form(request)
        vals = {k: v[0] for k, v in f.items() if k != "csrf"}
        action = vals.pop("action", "create")
        starter = _starter_of(vals)
        go = vals.pop("go", "") == "1"
        rtext = vals.pop("recipe", "")

        def recipe_of():
            if rtext:                 # the previewed recipe, with your edits
                import json
                r = json.loads(rtext)
                for k in ("name", "objective"):
                    if k in vals:
                        r[k] = vals[k].strip() if k == "name" else vals[k]
                r = starters.check(r)
            else:
                r = starters.from_values(starter, vals, home)
            r["hold"] = not go
            return r
        try:
            r = await run_in_threadpool(recipe_of)
            if action == "preview":
                lines = await run_in_threadpool(starters.preview, r, home)
                return new_page(request, starter, dict(vals, name=r["name"],
                                                       objective=r.get("objective", "")),
                                preview=lines, recipe=r)
            plan = await run_in_threadpool(starters.make, r, home)
        except (starters.StartError, registry.ConfigError, ValueError, OSError) as ex:
            if action == "preview" or rtext:
                return new_page(request, starter, vals, error=str(ex))
            q = urllib.parse.urlencode({"msg": str(ex), "ok": "0", "name": vals.get("name", ""),
                                        "starter": starter})
            return RedirectResponse("/new?" + q, status_code=303)
        e = {"name": plan.name}
        if go:
            return back("/p/%s" % urllib.parse.quote(plan.name), executor.Outcome(
                executor.OK, "created %s at %s; the runner has it" % (plan.name, plan.path)))
        return back(compose_url(e), executor.Outcome(
            executor.OK, "created %s at %s; held for setup" % (plan.name, plan.path)),
            poke_runner=False)

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
        elif request.query_params.get("instruction"):
            c["instruction"] = request.query_params["instruction"]
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
        p = os.path.join(layout.run_dir(e["path"], wpid), "steps", d, "transcript.jsonl")
        text = data._read(p)
        if text is None:
            return not_found(request, "transcript of step %s" % d)
        return PlainTextResponse(text, media_type="application/x-ndjson; charset=utf-8",
                                 headers={"content-disposition": 'inline; filename="%s-%s.jsonl"'
                                          % (wpid[:8], d)})

    def file_page(request, e, p, rel, link, wpid=None, listing=None, editable=True):
        """A Markdown file formatted, with markup (docs/doc-markup.md); ?raw=1 for
        its source; other text as it is; a binary file as a download."""
        if os.path.getsize(p) > FILE_MAX:
            return PlainTextResponse("%s: %d bytes, too large to show here; it is at %s\n"
                                     % (rel, os.path.getsize(p), p))
        with open(p, "rb") as fp:
            raw = fp.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return Response(raw, media_type="application/octet-stream", headers={
                "content-disposition": 'attachment; filename="%s"' % os.path.basename(p)})
        html = (data.md(text, link(os.path.dirname(os.path.normpath(rel))), lines=True)
                if p.lower().endswith((".md", ".markdown"))
                and not request.query_params.get("raw") else None)
        if html is None:
            return PlainTextResponse(text)
        return render(request, "doc.html", e=e, wpid=wpid, rel=rel, html=html,
                      sha=markup.sha(text), writable=editable and os.access(p, os.W_OK),
                      items=text.count("{++") + text.count("{--") + text.count("{~~")
                      + text.count("{>>") + text.count("{=="))

    async def deliverable(request):
        """A file or folder the packet's completion report lists, or one in its
        ``state/`` (docs/plan-tree.md)."""
        e = entry(request)
        wpid, rel = request.path_params["wpid"], request.query_params.get("path", "")
        step = request.query_params.get("step") or None      # its copy, as it was then
        hit = data.deliverable(e, wpid, rel, step) if e is not None else None
        editable = step is None
        if hit is None and e is not None and step is None:
            hit = data.state_file(e, wpid, rel)
            if hit is not None:
                hit, editable = hit[:2], hit[2]
        if hit is None:
            return not_found(request, "deliverable %s" % rel)
        p, is_dir = hit
        if is_dir:
            names = sorted(n + ("/" if os.path.isdir(os.path.join(p, n)) else "")
                           for n in os.listdir(p))
            return PlainTextResponse("%s/\n\n%s\n" % (rel.rstrip("/"), "\n".join(names)))
        return file_page(request, e, p, rel, lambda d: data.file_link(e, wpid, d, step),
                         wpid=wpid, editable=editable)

    async def plan_view(request):
        """The packet's plan as a tree, and its versions (docs/plan-tree.md)."""
        e = entry(request)
        wpid = request.path_params["wpid"]
        q = request.query_params
        pl = None
        if e is not None and data.schema.is_wpid(wpid):
            pkt = data.Packet(layout.run_dir(e["path"], wpid))
            if os.path.isdir(pkt.path):
                pl = await run_in_threadpool(
                    plan.page, e, wpid, data.steps(pkt), q.get("v"), q.get("changes") == "1",
                    q.get("open") if q.get("open") in ("all", "none") else None)
        if pl is None:
            return not_found(request, "packet %s" % wpid)
        return render(request, "plan.html", e=e, pl=pl, MARK=plan.MARK)

    async def doc(request):
        """A file or folder in the project's ``work/`` (docs/doc-markup.md)."""
        e = entry(request)
        rel = os.path.normpath(request.query_params.get("path") or "work")
        rel = data.work_rel(e, rel) if e is not None else rel
        hit = data.work_doc(e, rel) if e is not None else None
        if hit is None:
            return not_found(request, "file %s" % rel)
        p, is_dir = hit
        if is_dir:
            return render(request, "doc.html", e=e, wpid=None, rel=rel, html=None,
                          listing=data.doc_listing(p, rel))
        return file_page(request, e, p, rel, lambda d: data.doc_link(e, d))

    async def markup_post(request):
        """Mark up, or resolve an item in, a Markdown file shown by deliverable() or
        doc(). JSON in, JSON out: ``{"sha"}`` or ``{"error"}``."""
        from .. import actions
        from ..packet import Packet
        e = entry(request)
        if e is None:
            return JSONResponse({"error": "no such project"}, status_code=404)
        try:
            f = await request.json()
            assert isinstance(f, dict)
        except (ValueError, AssertionError):
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)
        wpid, rel, op = f.get("wpid"), str(f.get("path") or ""), f.get("op")
        hit = data.deliverable(e, wpid, rel) if wpid else data.work_doc(e, rel)
        if hit is None and wpid:
            hit = data.state_file(e, wpid, rel)
            if hit is not None and not hit[2] and op != "ask":
                return JSONResponse({"error": "the runner owns this packet's state/ now; "
                                     "pause it first"}, status_code=409)
            hit = hit[:2] if hit else None
        if hit is None or hit[1] or not hit[0].lower().endswith((".md", ".markdown")):
            return JSONResponse({"error": "not a Markdown file this board shows"},
                                status_code=404)
        if op == "ask":
            if not wpid:
                return JSONResponse({"error": "ask is for a packet's file"}, status_code=400)
            pkt = Packet(layout.run_dir(e["path"], wpid))
            out = await run_in_threadpool(actions.note, pkt, ask_text(rel), who(request))
            if out.code == 0:
                poke()
            return JSONResponse({"msg": out.msg} if out.code == 0 else {"error": out.msg},
                                status_code=200 if out.code == 0 else 400)
        try:
            if op in ("accept", "reject"):
                fn = lambda t: markup.resolve(t, str(f.get("raw") or ""), int(f.get("n") or 0),
                                              op == "accept")
            else:
                lines = tuple(int(x) for x in str(f.get("lines") or "").split("-"))
                if len(lines) != 2:
                    raise markup.MarkupError("no block to mark up")
                fn = lambda t: markup.mark(t, lines, str(f.get("sel") or ""),
                                           int(f.get("at") or 0), op, str(f.get("text") or ""))
            sha = await run_in_threadpool(markup.edit, hit[0], str(f.get("sha") or ""), fn)
        except markup.Stale as ex:
            return JSONResponse({"error": str(ex), "stale": True}, status_code=409)
        except (markup.MarkupError, ValueError) as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        except OSError as ex:
            return JSONResponse({"error": "cannot write %s: %s" % (rel, ex.strerror)},
                                status_code=500)
        return JSONResponse({"sha": sha})

    async def log_txt(request):
        e = entry(request)
        wpid, d = request.path_params["wpid"], request.path_params["step"]
        if e is None or not data.schema.is_wpid(wpid) or data.schema.parse_step_dir(d) is None:
            return not_found(request, "step %s" % d)
        p = os.path.join(layout.run_dir(e["path"], wpid), "steps", d, "transcript.jsonl")
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

    return Starlette(middleware=[Middleware(ArchivedReadOnly, home=home)], routes=[
        Route("/ide/{rest:path}", ide_http,
              methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
        WebSocketRoute("/ide/{rest:path}", ide_ws),
        Route("/", overview),
        Route("/sched", sched_page),
        Route("/sched.json", sched_json),
        Route("/sched/mode", sched_mode, methods=["POST"]),
        Route("/packets/bulk", bulk, methods=["POST"]),
        *[Route("/p/{project}/%s" % w, setter(w), methods=["POST"])
          for w in ("prio", "size", "hold")],
        *[Route("/p/{project}/{wpid}/%s" % w, setter(w), methods=["POST"])
          for w in ("prio", "size", "next")],
        Route("/boards", board_new, methods=["POST"]),
        Route("/packets", all_packets),
        Route("/b/{board}", board),
        Route("/b/{board}/delete", board_delete, methods=["POST"]),
        Route("/b/{board}/watch/{name}/poll", watch_poll, methods=["POST"]),
        Route("/p/{project}/board", board_move, methods=["POST"]),
        Route("/p/{project}/pr", pr_open, methods=["POST"]),
        Route("/healthz", health),
        Route("/static/live.js", live_js),
        Route("/static/pane.js", pane_js),
        Route("/static/{name:path}", static),
        Route("/new", new_form),
        Route("/new/search", new_search),
        Route("/new", new_create, methods=["POST"]),
        Route("/p/{project}/compose", compose),
        Route("/p/{project}/compose", compose_post, methods=["POST"]),
        Route("/p/{project}/compose/upload", compose_upload, methods=["POST"]),
        Route("/p/{project}/shell/close", shell_close, methods=["POST"]),
        WebSocketRoute("/p/{project}/shell/{sid}", shell_ws),
        Route("/p/{project}/settings", configure, methods=["POST"]),
        Route("/p/{project}/ide", ide_open, methods=["POST"]),
        Route("/p/{project}/doc", doc),
        Route("/p/{project}/markup", markup_post, methods=["POST"]),
        Route("/p/{project}/{wpid}/act", act, methods=["POST"]),
        Route("/p/{project}/{wpid}/live", live_view),
        Route("/p/{project}/{wpid}/file", deliverable),
        Route("/p/{project}/{wpid}/plan", plan_view),
        Route("/p/{project}/{wpid}/{step}/raw", raw),
        Route("/p/{project}/{wpid}/{step}/log.txt", log_txt),
        Route("/p/{project}", project_page(project_overview)),
        Route("/p/{project}/tasks", project_page(project_tasks)),
        Route("/p/{project}/tasks/{n}", project_page(project_task)),
        Route("/p/{project}/steps", project_page(project_steps)),
        Route("/p/{project}/cost", project_page(project_cost)),
        Route("/p/{project}/settings", project_page(project_settings)),
        Route("/p/{project}/{wpid}", packet),
        Route("/p/{project}/{wpid}/{step}", step),
    ])


class ArchivedReadOnly:
    """Refuse changes to a project whose runs have been removed and that is
    shown from the history store (``archived``); moving it between boards
    is still allowed. After any other POST, bring the cards of the packets
    it changed up to date (livecard), in the background."""

    def __init__(self, app, home=None):
        self.app = app
        self.home = home

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST":
            parts = scope["path"].strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "p" and parts[2] != "board":
                name = urllib.parse.unquote(parts[1])
                try:
                    e = await run_in_threadpool(archived.get, name, self.home)
                except (KeyError, OSError, ValueError, registry.ConfigError):
                    e = None
                if e is not None and archived.is_archived(e):
                    resp = PlainTextResponse(
                        "%s is archived: its runs were removed and it is shown from"
                        " the history store, read-only\n" % name, status_code=409)
                    return await resp(scope, receive, send)
            try:
                return await self.app(scope, receive, send)
            finally:
                threading.Thread(target=livecard.flush, daemon=True).start()
        return await self.app(scope, receive, send)
