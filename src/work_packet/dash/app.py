"""The Starlette app behind ``wpk dash``.

GET routes only read. The POST routes are the actions of docs/interaction.md §5,
each one a call into ``work_packet.actions`` or ``project`` and nothing more.
"""

import asyncio
import copy
import datetime
import json
import logging
import os
import pickle
import shutil
import threading
import time
import urllib.parse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import (FileResponse, HTMLResponse, JSONResponse,
                                 PlainTextResponse, RedirectResponse, Response)
from starlette.middleware import Middleware
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect, WebSocketState

from .. import __about__, archived, clock, ide_sessions, layout, livecard, registry, views
from . import data, dfmrun, markup, newjobs, panels, plan, tokens, vendored
from . import sched as dsched
from ..sched.classes import CLASSES
from .guard import split_host

FILE_MAX = 4 * 1024 * 1024    # bytes of a deliverable the page serves
# Images a file view serves as themselves, for <img> in a Markdown file it shows;
# an SVG under a sandbox CSP, so one opened on its own runs no script.
IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "live.js"), "rb") as _fp:
    LIVE_JS = _fp.read()   # a file, not inline, so the CSP can be script-src 'self'
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pane.js"), "rb") as _fp:
    PANE_JS = _fp.read()   # scroll panes and log buttons, on every page
HERE = os.path.dirname(os.path.abspath(__file__))
# Served from the package: compose.js, shell.js and the other scripts (no CDN, the CSP
# is script-src 'self'); vendored libraries go through dash/vendored.py. Name -> media type.
STATIC = {"board.js": "text/javascript", "packets.js": "text/javascript", "sched.js": "text/javascript", "compose.js": "text/javascript", "ide.js": "text/javascript", "new.js": "text/javascript", "shell.js": "text/javascript", "markup.js": "text/javascript", "console.js": "text/javascript", "studio.js": "text/javascript", "studio_chart.js": "text/javascript", "studio_wait.js": "text/javascript", "studio_files.js": "text/javascript", "studio_edit.js": "text/javascript", "ide_forward.js": "text/javascript", "ide_presence.js": "text/javascript", "desk.js": "text/javascript", "ide_desk.js": "text/javascript", "page.js": "text/javascript", "notify.js": "text/javascript"}
REFRESH_S = 10
STARTS = ("ide-web", "ide-desktop", "studio", "handoff", "none")   # collaboration.md W1
LIVE_MS = 3000             # the live view refreshes faster
log = logging.getLogger("wpk.dash")
UPLOAD_MAX = 16 << 20      # bytes of one uploaded input
PROCS_MAX = 60             # rows of the live view's Processes panel (a -j32 build has hundreds)


def _vendored(request, rel):
    """A file of the studio's vendored libraries (``dash/vendored.py``)."""
    got = vendored.lookup(rel)
    if got is None:
        return PlainTextResponse("not found\n", status_code=404)
    path, mt, sha = got
    etag = '"%s"' % sha[:32]
    hdrs = {"cache-control": vendored.CACHE, "etag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=hdrs)
    if not os.path.isfile(path):
        return PlainTextResponse("not found\n", status_code=404)
    return FileResponse(path, media_type=mt, headers=hdrs)


def _inline(text):
    """One line of Markdown as HTML (the text as it is without markdown-it)."""
    h = data.md_inline(text)
    return Markup(h) if h is not None else text


WORKER_TITLE = {"studio": "done by a person in the studio, not by a model's step",
                "session": "a checkpoint by a person, on the board or from their Claude or Codex session",
                "scribe": "a checkpoint drafted from a session's transcript when it ended"}


def _worker_title(w):
    return WORKER_TITLE.get(w, "done by a person in the %s, not by a model's step" % w)


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


def _epoch(t):
    """A Unix time as local ``YYYY-MM-DD HH:MM``."""
    if not isinstance(t, (int, float)):
        return ""
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def is_owner(request):
    """The board's owner, or someone the Guard lets act as them: the local user,
    an allowed tailnet user. Only they see their VS Code sessions
    (docs/vscode-monitor-plan.md §2.6). No Guard (tests): the local user."""
    return bool((request.scope.get("state") or {}).get("owner", True))


def _view(request, default):
    """The transcript view asked for: ``?view=log``, or ``default``."""
    return "log" if request.query_params.get("view") == "log" else default


def ask_text(rel):
    """The note or instruction that asks for the markup in ``rel`` to be resolved."""
    return ("Resolve the CriticMarkup in %s: make each change it suggests "
            "({++ insert ++}, {-- delete --}, {~~ old ~> new ~~}) or say why not, answer "
            "each comment ({== text ==}{>> comment <<}), then remove the markup." % rel)


def _scope_href(m):
    """The page a conversation belongs to: where the drawer continues it."""
    if m.get("wpid"):
        return "/p/%s/%s" % (urllib.parse.quote(m["project"]), m["wpid"])
    if m.get("project"):
        return "/p/%s" % urllib.parse.quote(m["project"])
    return "/"


def create_app(home=None, runner=None, shells=None, ide_backend=None, agents=None):
    """The app, reading the registry under ``home`` (default: ``WPK_HOME``).

    ``runner`` (``dash.runner.Runner``) is poked after every action that can
    make a packet due (dash-tasks.md §7). ``shells`` (``dash.shells.Shells``)
    serves the browser shell (§5); without it Compose has no shell pane.
    ``ide_backend`` (``dash.ide.Backends``) serves web VS Code under ``/ide/<key>/``
    when ``[ide] web`` is on (docs/vscode-plan.md §4). ``agents``
    (``dash.agent.Agents``) answers the console's questions (docs/console.md);
    without it the console runs slash commands only."""
    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))
    env.filters.update(epoch=_epoch, inline=_inline, money=_money, secs=_secs, when=_when, bytes=_bytes, tok=_tok, pct=_pct,
                       worker_title=_worker_title)
    stamp = max(os.path.getmtime(os.path.join(HERE, n)) for n in STATIC)
    env.globals.update(origin_of=data.origin, version=__about__.__version__, refresh_s=REFRESH_S,
                       asset_v="%s-%d" % (__about__.__version__, stamp),
                       columns=data.COLUMNS, column_colour=data.COLUMN_COLOUR, ask_text=ask_text,
                       packet_layout=layout.is_packet_layout, packet_folder=layout.packet_folder)

    jobs = newjobs.CreateJobs(home)       # New task's Create, in the background

    # One board build at a time, off the event loop, shared by every page that
    # asks while it runs (docs/cpu-plan.md P1.4): every open tab polls it. Not kept
    # after: a change from the CLI or a step shows on the next load.
    bcache = {"gen": 0, "task": None, "tgen": -1}

    def board_build():
        rows = []
        cols, broken = data.board(home, rows=rows)
        return cols, broken, rows

    def board_done(f):
        if bcache["task"] is f:
            bcache["task"] = None

    def board_copy(v):
        try:
            return pickle.loads(pickle.dumps(v))         # about 4x faster than deepcopy
        except (pickle.PicklingError, TypeError, AttributeError):
            return copy.deepcopy(v)

    async def board_of(rows=None):
        """``data.board(home)``: (cols, broken), a copy the caller may change;
        ``rows``, given a list, gets every packet row."""
        t = bcache["task"]
        if t is None or bcache["tgen"] != bcache["gen"]:   # an action since: build anew
            t = asyncio.ensure_future(run_in_threadpool(board_build))
            bcache.update(task=t, tgen=bcache["gen"])
            t.add_done_callback(board_done)
        v = await asyncio.shield(t)                      # a closed tab doesn't cancel it
        cols, broken, rs = await run_in_threadpool(board_copy, v)
        if rows is not None:
            rows.extend(rs)
        return cols, broken

    def board_changed():
        bcache["gen"] += 1

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
        e = ctx.get("e")                  # a packet's pages lead with its board's crumb
        if isinstance(e, dict) and e.get("name") and e.get("path") and "crumb_board" not in ctx:
            try:
                ctx["crumb_board"] = registry.board_of(
                    e, [b["name"] for b in registry.boards(home)])
            except Exception:             # noqa: BLE001: a crumb never breaks a page
                ctx["crumb_board"] = None
        if "vsc" in ctx:                  # the sessions tables carry the scribe's switch
            from .. import scribe, sessionhooks
            ctx["scribe_on"] = scribe.enabled(home or registry.home(), ctx["ide"])
            ctx["hooks_on"] = sessionhooks.enabled(ctx["ide"], home or registry.home())
        ctx["ide_sizes"] = ide_sizes() if getattr(ide_backend, "slot", False) else []
        ctx["ide_web"] = web_state(request, ctx["ide"])
        return HTMLResponse(env.get_template(name).render(**ctx), status_code=status)

    async def arender(request, name, status=200, **ctx):
        """``render`` off the event loop: templates and the banner's reads take time."""
        return await run_in_threadpool(lambda: render(request, name, status, **ctx))

    def xpanels(request, slot, **ctx):
        """The plugins' panels for ``slot`` (design E7)."""
        return panels.render(env, slot, request, home, **ctx)

    def ide_sizes():
        from ..sched import config as sconfig
        try:
            return list(sconfig.sizes(sconfig.load(home)).values())
        except registry.ConfigError:
            return []

    def picker_sizes(names):
        """Size objects for a picker, in ``names`` order; a name the config
        no longer has is shown bare."""
        from ..sched import config as sconfig
        try:
            known = sconfig.sizes(sconfig.load(home))
        except registry.ConfigError:
            known = {}
        return [known.get(n) or sconfig.Size(name=n, cpus=1) for n in names]

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
            if request.scope.get("state", {}).get("listener") == "tailnet":
                return ('needs HTTPS: set tls = "tailscale" under [server] in config.toml '
                        "and restart wpk serve (docs/server.md §2.3)")
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
        """The Overview (``/``): how every board is doing, what needs you (and what
        finished), the boards' cost over ``?days=`` 1, 7 or 30 (docs/overview.md)."""
        from .. import attention
        days = days_of(request)
        cols, broken = await board_of()
        side = data.side(home, cols, broken)
        board = request.query_params.get("board")      # the Desk for one board (§8.1)
        if board not in [b["name"] for b in side]:
            board = None
        if board:
            cols, broken = data.only(cols, broken, board)
        burn = await run_in_threadpool(tokens.board, archived.entries(home), days=days,
                                       on=[b["name"] for b in side])
        ov = data.overview(cols, broken, [b for b in side if not board or b["name"] == board],
                           burn)
        h, me = home or registry.home(), who(request)
        snz = attention.snoozes(h, me)
        ov["snoozed"] = sum(1 for a in ov["attention"] if a["key"] in snz)
        ov["attention"] = [a for a in ov["attention"] if a["key"] not in snz]
        since = attention.since(h, me)          # the page's beacon records the visit
        cards = [c for v in cols.values() for c in v]
        last = await run_in_threadpool(data.since_last, cards, since) if since else []
        ov["tiles"]["sessions"] = await run_in_threadpool(data.session_spend, h) \
            if is_owner(request) else None
        from .. import brief, inbox
        ov["cols"], ov["captured"] = cols, len(inbox.items(h)) + len(inbox.requests(h))
        ov["brief"] = brief.load(h, time.strftime("%Y-%m-%d"))
        ov["shutdown"] = brief.shutdown_hint()
        try:
            ov["tiles"]["review_wip"] = int((registry.load_config_file(home).get("plan") or {})
                                            .get("review_wip") or 5)
        except (registry.ConfigError, ValueError, TypeError):
            ov["tiles"]["review_wip"] = 5
        snap = await run_in_threadpool(dsched.snapshot, home)
        vsc = await run_in_threadpool(ide_sessions.recent_view, home or registry.home()) \
            if is_owner(request) else None
        return await arender(request, "overview.html", ov=ov, burn=burn, broken=broken, live=True,
                      vsc=vsc, board=board, since=since, last=last,
                      sch=dsched.tiles(snap), xpanels=xpanels(request, "overview"),
                      home=home or registry.home(), side=side, here=None,
                      windows=tokens.WINDOWS, main_board=registry.DEFAULT_BOARD)

    def days_of(request):
        try:
            days = int(request.query_params.get("days", 7))
        except ValueError:
            days = 7
        return days if days in tokens.WINDOWS else 7

    async def stats_page(request):
        """Statistics (``/stats``): token use over ``?days=`` 1, 7 or 30, which the
        Overview showed at its foot (docs/overview-recent.md §3)."""
        cols, broken = await board_of()
        side = data.side(home, cols, broken)
        burn = await run_in_threadpool(
            lambda: tokens.board(archived.entries(home), days=days_of(request),
                                 on=[b["name"] for b in side], home=home or registry.home(),
                                 sessions=is_owner(request)))
        return await arender(request, "stats.html", burn=burn, side=side, here=None,
                      windows=tokens.WINDOWS)

    def run_links(vs):
        """Name each run's project from its packet: a step's env carries only the wpid."""
        need = [v for v in vs if v["wpid"] and not v["project"] and data.schema.is_wpid(v["wpid"])]
        if need:
            ents = archived.entries(home)
            for v in need:
                v["project"] = next((e["name"] for e in ents if os.path.isdir(
                    layout.run_dir(e["path"], v["wpid"]))), None)
        return vs

    def dfm_home():
        return home or registry.home()

    async def runs_page(request):
        """DFM runs (``/runs``; docs/dfm-events.md §5): live first, then newest."""
        wpid = request.query_params.get("wpid") or None
        vs = await run_in_threadpool(lambda: run_links(dfmrun.runs(dfm_home(), wpid=wpid)))
        cols, broken = await board_of()
        return await arender(request, "runs.html", runs=vs, wpid=wpid, live=any(v["live"] for v in vs),
                      refresh_ms=LIVE_MS, side=data.side(home, cols, broken))

    async def run_page(request):
        """One DFM run (``/runs/{sid}``): Running, Pending and Done (§6)."""
        sid = request.path_params["sid"]
        run = await run_in_threadpool(dfmrun.load, dfm_home(), sid)
        if run is None:
            return not_found(request, "DFM run %s" % sid)
        r = run_links([dfmrun.view(run)])[0]
        kids = [k for k in await run_in_threadpool(dfmrun.runs, dfm_home()) if k["parent"] == sid]
        return await arender(request, "run.html", r=r, kids=kids, live=r["live"], refresh_ms=LIVE_MS)

    async def run_log(request):
        """The tail of one task's log, if the run's journal names it inside its rundir."""
        run = await run_in_threadpool(dfmrun.load, dfm_home(), request.path_params["sid"])
        nid = request.query_params.get("id", "")
        p = dfmrun.log_path(run, nid) if run else None
        if p is None:
            return not_found(request, "log of %s" % nid)
        text, cut = await run_in_threadpool(dfmrun.log_tail, p)
        head = "[... the first part of %s is not shown]\n" % p if cut else ""
        return PlainTextResponse(head + text)

    async def board(request):
        """One board (``/b/{board}``; docs/boards.md): its cards."""
        name = request.path_params["board"]
        cols, broken = await board_of()
        side = data.side(home, cols, broken)
        here = next((b for b in side if b["name"] == name), None)
        if here is None:
            return not_found(request, "board %s" % name)
        cols, broken = data.only(cols, broken, name)
        batch = request.query_params.get("batch", "")
        if batch:               # one dispatch's packets (docs/agent-dispatch.md §5.2)
            cols = {k: [c for c in v if c.get("batch") == batch] for k, v in cols.items()}
        bset = await run_in_threadpool(board_settings, name)
        snap = await run_in_threadpool(dsched.snapshot, home)
        watchers = await run_in_threadpool(data.watchers, home, name)
        ib = await run_in_threadpool(data.inbox_view, home, cols, name)
        msv = await run_in_threadpool(data.milestones_view, home, cols, name)
        return await arender(request, "board.html", cols=cols, broken=broken, live=True,
                      milestones=msv,
                      waiting=dsched.waiting(snap), watchers=watchers, captures=ib["entries"],
                      inbox_requests=ib["requests"], inbox_projects=ib["projects"],
                      side=side, here=here, main_board=registry.DEFAULT_BOARD,
                      batch=batch, bset=bset)

    def starters_dispatched(wpids):
        from .. import starters
        return starters.dispatched(wpids, home)

    def board_settings(name):
        """The board's packet directory, notes and repos (docs/agent-dispatch.md §3-4)."""
        try:
            b = registry.board(name, home) or {}
        except registry.BoardError:
            b = {}
        return {"dir": b.get("dir") or "", "packet_dir": registry.packet_dir(name, None, home),
                "notes": registry.notes(name, home), "repos": registry.repos(name, home)}

    async def board_settings_post(request):
        """Save a board's packet directory and its notes for agents."""
        from .. import executor, fsutil
        name = request.path_params["board"]
        to = "/b/%s#board-settings" % urllib.parse.quote(name)
        if name not in [b["name"] for b in registry.boards(home)]:
            return not_found(request, "board %s" % name)
        if not is_owner(request):
            return back(to, executor.Outcome(executor.USAGE, "only the board's owner can "
                                             "change it"), poke_runner=False)
        f = await form(request)
        d = (f.get("dir") or [""])[0].strip()
        notes = (f.get("notes") or [""])[0].replace("\r\n", "\n")
        try:
            got = await run_in_threadpool(registry.set_board, name, {"dir": d or None}, home)
            path = registry.notes_path(name, home)
            if notes.strip() != registry.notes(name, home).strip():
                if notes.strip():
                    await run_in_threadpool(fsutil.atomic_write, path,
                                            notes.rstrip("\n") + "\n")
                elif os.path.exists(path):
                    os.unlink(path)
                got.append("notes")
        except (registry.BoardError, OSError) as ex:
            return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        return back(to, executor.Outcome(executor.OK, "saved: %s" % ", ".join(got) if got
                                         else "nothing changed"), poke_runner=False)

    async def milestones_post(request):
        """Add or remove a board milestone (plan F3d): ``op`` add (``name``,
        ``date``, ``title``) or remove (``name``)."""
        from .. import executor, milestones
        name = request.path_params["board"]
        if name not in [b["name"] for b in registry.boards(home)]:
            return not_found(request, "board %s" % name)
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        to = "/b/%s#milestones" % urllib.parse.quote(name)
        try:
            if one("op") == "remove":
                milestones.remove(name, one("name"), home)
                msg = "removed %s" % one("name")
            else:
                m = milestones.add(name, one("name"), one("date"), one("title"), home)
                msg = "%s: milestone %s on %s" % (name, m["name"], m["date"])
        except milestones.MilestoneError as ex:
            return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        return back(to, executor.Outcome(executor.OK, msg), poke_runner=False)

    async def watch_post(request):
        """Add, change or remove a board's watcher (plan G4): ``op`` save (``was``:
        the name it had, empty for a new one) or remove (``name``)."""
        from .. import executor, watch
        name = request.path_params["board"]
        if name not in [b["name"] for b in registry.boards(home)]:
            return not_found(request, "board %s" % name)
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        words = lambda k: [x for x in one(k).replace(",", " ").split() if x]
        to = "/b/%s#watchers" % urllib.parse.quote(name)
        try:
            if one("op") == "remove":
                await run_in_threadpool(watch.remove, name, one("name"), home)
                msg = "removed the watcher %s" % one("name")
            else:
                w = {"name": one("name"), "repos": words("repos"), "dir": one("dir"),
                     "labels": words("labels"), "every": one("every"),
                     "on": one("on") if one("on") == "ci" else None,
                     "branches": words("branches"),
                     "propose": one("propose") == "1", "hold": one("hold") == "1",
                     "enabled": one("enabled") == "1", "pr": one("pr")}
                await run_in_threadpool(watch.save, name, w, one("was") or None, home)
                msg = "%s the watcher %s" % ("saved" if one("was") else "added", w["name"])
        except watch.WatchError as ex:
            return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        return back(to, executor.Outcome(executor.OK, msg), poke_runner=False)

    async def all_packets(request):
        """Every packet on every board, to sort and search (docs/boards.md)."""
        rows = []
        cols, broken = await board_of(rows=rows)
        states = sorted({r["state"] for r in rows}, key=str)
        snap = await run_in_threadpool(dsched.snapshot, home)
        cls = {}
        for e in archived.entries(home):
            for r in rows:
                if r["project"] == e["name"]:
                    cls[r["wpid"]] = dsched.packet_info(snap, e, r["wpid"])
        return await arender(request, "packets.html", rows=rows, broken=broken, states=states,
                      sch=cls, classes=CLASSES, sizes=picker_sizes((snap or {}).get("sizes", {})),
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

    async def deliver_post(request):
        """Push now / Cancel delivery (docs/agent-dispatch.md §5.4)."""
        from .. import deliver, executor
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        url = "/p/%s" % urllib.parse.quote(e["name"])
        op = (f.get("op") or [""])[0]
        try:
            if op == "off":
                await run_in_threadpool(deliver.off, e["name"], home, who(request))
                out = executor.Outcome(executor.OK, "%s will not push on completion" % e["name"])
            elif op == "now":
                r = await run_in_threadpool(deliver.run, e["name"], home, who(request))
                out = executor.Outcome(executor.OK if r["ok"] else executor.USAGE,
                                       r["msg"].splitlines()[0])
            else:
                out = executor.Outcome(executor.USAGE, "op: now or off")
        except deliver.DeliverError as ex:
            out = executor.Outcome(executor.USAGE, str(ex))
        return back(url, out, poke_runner=False)

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

    # --- built Sphinx docs (docs/sphinx-docs-v1.md) ----------------------------------

    def docs_rows(e, card):
        """The project's docsets as the Docs menu shows them; [] if it has none."""
        from .. import docs
        run = card.get("running") or {}
        try:
            return [docs.state(ds) for ds in docs.detect(e["path"], run.get("wpid"), home=home)]
        except OSError:
            return []

    def docs_of_run(e, wpid):
        """The newest docs build from run ``wpid``'s tree, per docset, for its page."""
        from .. import docs
        out = []
        for ds in docs.detect(e["path"], wpid, home=home):
            rec = next((h for h in docs.history(ds, 50) if h.get("wpid") == wpid), None)
            if rec:
                out.append({"entry": ds.entry, "name": ds.name, "rec": rec,
                            "newest": rec.get("end") == (docs.last(ds) or {}).get("end")})
        return out

    def docs_out(e, request):
        """The build folder the URL names, or None for a name that is not one."""
        from .. import docs
        ent, name = request.path_params["entry"], request.path_params["docset"]
        if any(x in ("", ".", "..") or "/" in x or "\0" in x for x in (ent, name)):
            return None
        return docs.out_dir(docs.project_name(e["path"]), ent, name, home)

    async def docs_file(request):
        """A file of the newest build; the folder itself is its ``index.html``. The
        page is shown as Sphinx built it: its own scripts and styles, no sandbox
        (D-Q4)."""
        from .. import docs
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        out = docs_out(e, request)
        if out is None:
            return not_found(request, "docs %s" % request.path_params["docset"])
        rel = request.path_params.get("path")
        if rel is None:     # relative links need the trailing slash
            return RedirectResponse(request.url.path + "/", status_code=307)
        root = os.path.realpath(os.path.join(out, "html"))
        if not os.path.isfile(os.path.join(root, "index.html")):
            return await docs_wait(request, e, out)
        p = os.path.realpath(os.path.join(root, rel))
        if os.path.isdir(p):
            p = os.path.join(p, "index.html")
        if not (p.startswith(root + os.sep)) or not os.path.isfile(p):
            return not_found(request, "page %s in these docs" % rel)
        return FileResponse(p, headers={"content-security-policy": docs.CSP,
                                        "cache-control": "no-cache"})

    async def docs_wait(request, e, out):
        """No build yet: start one, and say so until it is there."""
        from .. import docs
        ent, name = request.path_params["entry"], request.path_params["docset"]
        sets = await run_in_threadpool(docs.detect, e["path"], None, None, home)
        ds = next((d for d in sets if (d.entry, d.name) == (ent, name)), None)
        if ds is None:
            return not_found(request, "docs %s/%s" % (ent, name))
        rec = docs.last(ds)
        if docs.building(ds) is None and rec is None:
            await run_in_threadpool(docs.kick, e["path"], None, False, (ent, name),
                                    who(request), home, 2)
        return await arender(request, "docs_wait.html", e=e, ds=ds, rec=rec,
                      building=docs.building(ds) is not None or rec is None)

    async def docs_log(request):
        e = entry(request)
        out = docs_out(e, request) if e is not None else None
        p = os.path.join(out, "build.log") if out else None
        if not p or not os.path.isfile(p):
            return not_found(request, "build log")
        with open(p, encoding="utf-8", errors="replace") as f:
            return PlainTextResponse(f.read()[-FILE_MAX:])

    async def docs_build(request):
        """Build (or rebuild) one docset now, in the background."""
        from .. import docs, executor
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0]
        url = local(one("back"), "/p/%s" % urllib.parse.quote(e["name"]))
        card = (await run_in_threadpool(lambda: packet_top(e, clock.now(),
                                                           data.tree(e, clock.now()))))[0]
        wpid = (card.get("running") or {}).get("wpid")
        got = await run_in_threadpool(docs.kick, e["path"], wpid, False,
                                      (one("entry"), one("name")), who(request), home, 2)
        if not got:
            return back(url, executor.Outcome(executor.USAGE, "no docs %s/%s to build, or a "
                                              "build of them is under way"
                                              % (one("entry"), one("name"))), poke_runner=False)
        return back(url, executor.Outcome(executor.OK, "building the docs in %s/%s"
                                          % (got[0].entry, got[0].name)), poke_runner=False)

    # --- the scheduler (docs/scheduler.md §9) ------------------------------------

    async def sched_page(request):
        snap = await run_in_threadpool(dsched.snapshot, home)
        ch = await run_in_threadpool(dsched.chart, snap, home) if snap else None
        cols, broken = await board_of()
        creds = await run_in_threadpool(dsched.credential_rows, request, home)
        xp = await run_in_threadpool(xpanels, request, "sched")
        return await arender(request, "sched.html", snap=snap, chart=ch, live=True, creds=creds, xpanels=xp,
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

    def mark_seen(request, e, nodes=None):
        """Opening a stopped project marks it seen (docs/overview-recent.md §1).
        A held lease (someone started it again) is no failure: it is not stopped."""
        from .. import executor
        from ..packet import Packet
        if archived.is_archived(e):
            return None                 # read-only: from the history store
        if nodes is None:
            try:
                meta, _ = Packet(layout.run_dir(e["path"], e["root"])).load_status()
            except (OSError, ValueError):
                return None
            if not executor.stopped(meta):
                return None             # the cheap check: most pages stop here
            nodes = data.tree(e)
        if not nodes or not data.card(e, nodes=nodes)["unread"]:
            return None
        return executor.mark_seen(Packet(nodes[0]["path"]), by=who(request))

    async def seen(request):
        """Recently finished rows on the Overview: mark the picked projects (or
        ``all``) seen without opening them."""
        from .. import executor
        f = await form(request)
        names = [n for n in f.get("project") or () if n]
        if (f.get("all") or [""])[0]:
            cols, _ = await board_of()
            names = [c["name"] for v in cols.values() for c in v if c["unread"]]
        if not names:
            return back("/#attention", executor.Outcome(executor.USAGE, "tick some first"),
                        poke_runner=False)
        n, bad = 0, []
        for name in names:
            e = archived.get(name, home)
            out = await run_in_threadpool(mark_seen, request, e) if e else None
            if out is not None and out.code:
                bad.append("%s: %s" % (name, out.msg))
            else:
                n += 1
        msg = "marked %d seen" % n + ("; " + "; ".join(bad) if bad else "")
        return back("/#attention", executor.Outcome(1 if bad else 0, msg), poke_runner=False)

    def project_page(tab):
        async def handle(request):
            e = entry(request)
            if e is None:
                return not_found(request, "project %s" % request.path_params["project"])
            now = clock.now()
            nodes = await run_in_threadpool(data.tree, e, now)
            card, ts = await run_in_threadpool(packet_top, e, now, nodes)
            if card["unread"]:
                await run_in_threadpool(mark_seen, request, e, nodes)
            kw = dict(e=e, card=card, nodes=nodes, tasks=ts, work=work_rows(e),
                      docs=await run_in_threadpool(docs_rows, e, card),
                      dispatched=await run_in_threadpool(
                          starters_dispatched, [n["wpid"] for n in nodes]))
            return await tab(request, e, now, kw)
        return handle

    async def project_overview(request, e, now, kw):
        nodes = kw["nodes"]
        root = nodes[0] if nodes else None
        # A finished project leads with its root packet's completion report.
        rp = (await run_in_threadpool(data.packet, e, root["wpid"])
              if root and root["state"] in ("COMPLETED", "FAILED") else None)
        bs = registry.boards(home)
        from .. import questions
        from ..packet import Packet
        # Whatever in the tree is waiting on an answer leads the page, form and all.
        asks = [(n, qs) for n in nodes if n["state"] == "NEEDS_INPUT" and not n["running"]
                for qs in [questions.of_packet(Packet(n["path"]))] if qs]
        vsc = await run_in_threadpool(ide_sessions.project_view, home or registry.home(),
                                      e["name"]) if is_owner(request) else None
        from .. import jobs, split as split_mod
        jl = await run_in_threadpool(jobs.all_jobs, e["path"])
        sv = await run_in_threadpool(split_mod.view, e, home)
        auto = request.query_params.get("open")    # just made: open it (collaboration.md W1)
        return await arender(request, "project.html", rp=rp, live=True, asks=asks, vsc=vsc,
                      autoopen=auto if auto in ("ide-web", "ide-desktop", "studio") else None,
                      jobs=jl[:10], more_jobs=max(len(jl) - 10, 0), now_t=time.time(),
                      is_owner=is_owner(request), sv=sv,
                      span=views.span, jobs_label=jobs.label,
                      on=registry.board_of(e, [b["name"] for b in bs]),
                      tl=data.timeline(kw["tasks"], now), **kw)

    async def project_tasks(request, e, now, kw):
        state = request.query_params.get("state", "")
        states = sorted({t["state"] for t in kw["tasks"]}, key=str)
        if state:
            kw["tasks"] = [t for t in kw["tasks"] if t["state"] == state]
        return await arender(request, "project_tasks.html", state=state, states=states, **kw)

    async def project_task(request, e, now, kw):
        try:
            n = int(request.path_params["n"])
        except ValueError:
            n = 0
        t = data.task(e, kw["tasks"], n)
        if t is None:
            return not_found(request, "task %s" % request.path_params["n"])
        return await arender(request, "task.html", t=t, live=bool(t["task"]["running"]), **kw)

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
        return await arender(request, "project_steps.html", task=task, total=len(rows), page=page,
                      pages=pages, steps=rows[(page - 1) * STEPS_PAGE:page * STEPS_PAGE], **kw)

    async def project_cost(request, e, now, kw):
        # the sessions people drove, as the VS Code sessions tables: the owner only
        tk = await run_in_threadpool(tokens.project, e, now, 14, home or registry.home(),
                                     is_owner(request))
        return await arender(request, "project_cost.html", tk=tk, **kw)

    async def project_settings(request, e, now, kw):
        bs = registry.boards(home)
        snap = await run_in_threadpool(dsched.snapshot, home)
        return await arender(request, "project_settings.html", settings=data.settings(e),
                      sch=dsched.project_info(snap, e), classes=CLASSES, boards=bs,
                      xpanels=xpanels(request, "settings", project=e),
                      on=registry.board_of(e, [b["name"] for b in bs]), **kw)

    async def packet(request):
        e = entry(request)
        p = await run_in_threadpool(data.packet, e, request.path_params["wpid"]) if e else None
        if p is None:
            return not_found(request, "packet %s" % request.path_params["wpid"])
        await run_in_threadpool(mark_seen, request, e)
        snap = await run_in_threadpool(dsched.snapshot, home)
        dfm = await run_in_threadpool(dfmrun.runs, dfm_home(), wpid=request.path_params["wpid"])
        convs = await run_in_threadpool(conv_rows, lambda m: m.get("project") == e["name"] and
                                        m.get("wpid") == request.path_params["wpid"])
        built = await run_in_threadpool(docs_of_run, e, request.path_params["wpid"])
        vsc = await run_in_threadpool(ide_sessions.packet_view, home or registry.home(),
                                      e["name"], request.path_params["wpid"]) \
            if is_owner(request) else None
        from .. import ide_stranded
        strand = await run_in_threadpool(ide_stranded.for_packet, home or registry.home(),
                                         request.path_params["wpid"]) \
            if is_owner(request) else None
        auto = request.query_params.get("open")    # just made: open it (collaboration.md W1)
        rl = await run_in_threadpool(data.review_load, home) \
            if p["meta"].get("state") in ("PAUSED", "FAILED", "COMPLETED", "NEEDS_INPUT") else None
        return await arender(request, "packet.html", e=e, p=p, live=True, classes=CLASSES, dfm=dfm,
                      convs=convs, docs_built=built, vsc=vsc, rl=rl, strand=strand,
                      autoopen=auto if auto in ("ide-web", "ide-desktop", "studio") else None,
                      sch=dsched.packet_info(snap, e, request.path_params["wpid"]),
                      tk=await run_in_threadpool(tokens.packet, e, request.path_params["wpid"]))

    async def step(request):
        e = entry(request)
        view = _view(request, "blocks")
        s = data.step(e, request.path_params["wpid"], request.path_params["step"], view) \
            if e else None
        if s is None:
            return not_found(request, "step %s" % request.path_params["step"])
        await run_in_threadpool(mark_seen, request, e)
        # A committed or failed step never changes, so only a running one refreshes.
        sd = os.path.join(layout.run_dir(e["path"], request.path_params["wpid"]), "steps",
                          request.path_params["step"])
        n = data.schema.parse_step_dir(request.path_params["step"])
        dfm = await run_in_threadpool(dfmrun.runs, dfm_home(), wpid=request.path_params["wpid"],
                                      step=n[0] if n else None) if n else []
        return await arender(request, "step.html", e=e, s=s, view=view, tk=tokens.step(sd, s["meta"]),
                      dfm=dfm, live=s["info"]["outcome"] == "running" or any(r["live"] for r in dfm))

    # --- actions (POST) ---------------------------------------------------------

    async def form(request):
        body = (await request.body()).decode("utf-8", "replace")
        return urllib.parse.parse_qs(body, keep_blank_values=True)

    def poke():
        if runner is not None:
            runner.poke()

    def back(url, out, poke_runner=True):
        board_changed()
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
        elif op == "checkpoint":        # where it stands (docs/session-checkpoint.md §3)
            from .. import checkpoint
            try:
                out, _ = await run_in_threadpool(
                    checkpoint.record, pkt, one("status"), one("body") or None,
                    one("next").strip() or None, (), "session", by)
            except checkpoint.CheckpointError as ex:
                out = executor.Outcome(executor.USAGE, str(ex))
        elif op == "accept-draft":      # the scribe's draft becomes yours (plan G3)
            from .. import checkpoint
            out, _ = await run_in_threadpool(checkpoint.accept_draft, pkt, by)
        elif op == "keep":              # take back a pause that has not happened yet
            out = await run_in_threadpool(executor.withdraw_pause, pkt)
        elif op in ("done", "drop", "reopen"):     # docs/collaboration.md §4.1
            out = await run_in_threadpool(executor.mark, pkt, op, by, note or None)
        elif op == "hooks":                         # install or repair them (§4.3)
            from .. import ide, sessionhooks
            folder = sessionhooks.packet_folder(e)
            if folder is None:
                folders = ide.hook_folders(await run_in_threadpool(ide.resolve, e["path"]))
            else:
                folders = [folder]
            got = await run_in_threadpool(sessionhooks.ensure, folders, {"hooks": True})
            bad = [v for v in got.values() if v not in ("installed", "unchanged", "removed")]
            out = executor.Outcome(executor.USAGE if bad else executor.OK,
                                   "; ".join(bad) if bad else "Claude Code hooks: %s" % (
                                       ", ".join(sorted(set(got.values()))) or "nothing to do"))
        elif op == "end-stranded" and is_owner(request):   # docs/ide-split-desk-plan.md
            from .. import ide_stranded
            key = one("key")
            try:
                pid = int(one("pid"))
            except ValueError:
                pid = 0
            ok = any(s["pid"] == pid and s["key"] == key for s in await run_in_threadpool(
                ide_stranded.for_packet, home or registry.home(), wpid))
            if ok:
                await run_in_threadpool(ide_stranded.end_server, key, pid)
            out = executor.Outcome(executor.OK if ok else executor.USAGE,
                                   "ended the stranded VS Code server %d" % pid if ok else
                                   "%d is not a stranded VS Code server of this packet" % pid)
        elif op == "autonomy":                      # §4.4
            out = await run_in_threadpool(executor.mark, pkt, op, by, None,
                                          one("autonomy"), one("review") or None)
        elif op in ("handoff", "pause", "resume", "wake"):
            defer = one("after") == "1" and op != "pause"     # "after I leave" (§5.2)
            out = await run_in_threadpool(lambda: executor.admin(
                pkt, op, note or None, None, by, defer=defer))
        else:
            out = executor.Outcome(executor.USAGE, "unknown action %r" % op)
        if op in ("pause", "done", "drop") and out.code == 0:
            from ..sched import authz, control
            await run_in_threadpool(control.cancel_pending, wpid,
                                    authz.principal_of(request), home)
        url = "/p/%s/%s" % (urllib.parse.quote(e["name"]), wpid)
        if one("back") == "project":
            url = "/p/%s" % urllib.parse.quote(e["name"])
        elif one("back") == "overview":
            url = "/#attention"
        elif one("back").startswith("/"):           # a board's page, for instance
            url = local(one("back"), url)
        return back(url + "/live" if one("back") == "live" else url, out)

    async def scribe_switch(request):
        """Turn the scribe on or off for the board (docs/session-checkpoint.md D2)."""
        from .. import executor, scribe
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        on = one("on") == "1"
        if not is_owner(request):         # it reads the owner's sessions
            return back(local(one("back"), "/"), executor.Outcome(
                executor.USAGE, "only the board's owner can turn this on or off"),
                poke_runner=False)
        await run_in_threadpool(scribe.set_enabled, home or registry.home(), on, who(request))
        return back(local(one("back"), "/"), executor.Outcome(
            executor.OK, "status drafts when sessions end: %s" % ("on" if on else "off")),
            poke_runner=False)

    async def plan_post(request):
        """Your planning fields for a project (docs/collaboration.md §9.2): any of
        ``planning.KEYS`` ("" unsets), ``force`` (past the now limit), ``back``."""
        from .. import executor, planning
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        changes = {k: one(k) for k in planning.KEYS if k in f}
        if "due" in f and "due_kind" not in f:
            changes["due_kind"] = ""        # the form's box was left unticked
        to = local(one("back"), "/p/%s" % urllib.parse.quote(e["name"]))
        try:
            wip = int((registry.load_config_file(home).get("plan") or {}).get(
                "focus_wip") or planning.FOCUS_WIP)
        except (registry.ConfigError, ValueError, TypeError):
            wip = planning.FOCUS_WIP
        try:
            got = await run_in_threadpool(lambda: planning.set_(
                e, changes, who(request), archived.entries(home), wip, one("force") == "1"))
        except planning.PlanError as ex:
            return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        return back(to, executor.Outcome(executor.OK, "%s: %s%s" % (
            e["name"], got["priority"], ", " + planning.due_text(got) if got["due"] else "")),
            poke_runner=False)

    async def backlog_page(request):
        """The Backlog (docs/collaboration.md §9): your projects by priority, what
        you captured, and what has gone untouched."""
        from .. import inbox
        cols, broken = await board_of()
        side = data.side(home, cols, broken)
        return await arender(request, "backlog.html", bl=data.backlog(cols), side=side, here=None,
                      inbox=data.inbox_view(home, cols))

    async def capture(request):
        """Quick capture into the Inbox (docs/collaboration.md §9.6)."""
        from .. import executor, inbox
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        try:
            d = await run_in_threadpool(inbox.add, home or registry.home(), one("text"),
                                        who(request), "board", one("project") or None,
                                        one("board") or None)
            out = executor.Outcome(executor.OK, "captured: %s" % d["text"][:60])
        except ValueError as ex:
            out = executor.Outcome(executor.USAGE, str(ex))
        return back(local(one("back"), "/"), out, poke_runner=False)

    async def learn_page(request):
        """**Keep it** for a recurring correction (docs/collaboration.md §7.7): the
        rule to write, editable, and the projects whose ``agent.md`` gets it."""
        from .. import inbox
        h = home or registry.home()
        d = inbox.get(h, request.path_params["iid"])
        if d is None or (d.get("ref") or {}).get("learn") is None:
            return not_found(request, "proposal %s" % request.path_params["iid"])
        names = [e["name"] for e in registry.entries(home)]
        return await arender(request, "learn.html", d=d, ref=d["ref"], names=names,
                      owner=is_owner(request))

    async def learn_post(request):
        from .. import executor, learn
        iid = request.path_params["iid"]
        if not is_owner(request):
            return back("/learn/%s" % iid, executor.Outcome(
                executor.USAGE, "only the board's owner can keep a rule"), poke_runner=False)
        f = await form(request)
        rule = (f.get("rule") or [""])[0].strip()
        projects = [p for p in f.get("project") or () if p]
        try:
            done = await run_in_threadpool(learn.keep, home or registry.home(), iid, rule,
                                           projects)
        except (ValueError, OSError) as ex:
            return back("/learn/%s" % iid, executor.Outcome(executor.USAGE, str(ex)),
                        poke_runner=False)
        return back("/backlog", executor.Outcome(
            0, "kept: every later step in %s reads it (agent.md)" % ", ".join(done)),
            poke_runner=False)

    async def inbox_decline(request):
        """Decline a request that hasn't started (plan G6): ``from`` (the
        requester's wpid), ``id``, ``reason``."""
        from .. import executor, inbox
        from .. import requests as reqs
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        to = local(one("back"), "/backlog#inbox")
        try:
            msg = await run_in_threadpool(inbox.decline_request, one("from"), one("id"),
                                          one("reason"), who(request), home)
        except reqs.RequestError as ex:
            return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        return back(to, executor.Outcome(executor.OK, msg), poke_runner=False)

    async def inbox_item(request):
        """Triage an Inbox item (docs/collaboration.md W8): ``accept`` (a watcher's
        issue is made with its recipe; anything else goes to New with the text as
        its objective), ``drop`` (decline), ``merge`` (``project``: a note to that
        project's root), ``snooze`` (``until``: 1h or tomorrow)."""
        from .. import actions, attention, executor, inbox
        from ..packet import Packet
        h = home or registry.home()
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        to = local(one("back"), "/backlog#inbox")
        iid, op = request.path_params["iid"], request.path_params["op"]
        d = inbox.get(h, iid) if op in ("accept", "drop", "merge", "snooze") else None
        if d is None:
            return back(to, executor.Outcome(executor.USAGE, "no such item"), poke_runner=False)
        if op == "snooze":
            u = one("until") or "tomorrow"
            inbox.snooze(h, iid, attention.until_of(u), change=u == "change")
            return back(to, executor.Outcome(executor.OK, "snoozed"), poke_runner=False)
        if op == "merge":
            e = registry.get(one("project"), home)
            if e is None:
                return back(to, executor.Outcome(executor.USAGE, "no project %r" % one("project")),
                            poke_runner=False)
            text = "From the Inbox%s: %s" % (" (%s)" % d["source"] if d.get("source") else "",
                                             d["text"])
            out = await run_in_threadpool(actions.note, Packet(layout.run_dir(e["path"], e["root"])),
                                          text, who(request))
            if out.code == executor.OK:
                inbox.drop(h, iid)
                out = executor.Outcome(executor.OK, "added to %s as a note" % e["name"])
            return back(to, out, poke_runner=False)
        if op == "drop":
            inbox.drop(h, iid)
            return back(to, executor.Outcome(executor.OK, "dropped"), poke_runner=False)
        ref = d.get("ref") or {}
        if d.get("source") == "date" and ref.get("date"):   # plan F3c: use the forge's date
            from .. import planning
            e = registry.get(ref.get("project") or "", home)
            if e is None:
                return back(to, executor.Outcome(executor.USAGE, "no project %r"
                                                 % ref.get("project")), poke_runner=False)
            try:
                await run_in_threadpool(lambda: planning.set_(
                    e, {"due": ref["date"], "due_kind": "soft"}, who(request)))
            except planning.PlanError as ex:
                return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
            inbox.drop(h, iid)
            return back(to, executor.Outcome(executor.OK, "%s: due %s (from %s)" % (
                e["name"], ref["date"], ref.get("from") or "the forge")), poke_runner=False)
        if d.get("source") == "watch" and ref.get("watch"):
            from .. import starters, watch
            try:
                w = next(w for w in watch.find(d.get("board"), home) if w["name"] == ref["watch"])
                plan = await run_in_threadpool(starters.make, watch.recipe(w, ref["key"], home), home)
            except (StopIteration, watch.WatchError):
                return back(to, executor.Outcome(executor.USAGE, "its watcher %s is gone"
                                                 % ref["watch"]), poke_runner=False)
            except (starters.StartError, OSError) as ex:
                return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
            inbox.drop(h, iid)
            await run_in_threadpool(watch.update_state, w, home,
                                    lambda st: st["seen"].__setitem__(ref["key"], plan.name))
            return back("/p/%s" % urllib.parse.quote(plan.name), executor.Outcome(
                executor.OK, "made %s from %s" % (plan.name, ref["key"])))
        inbox.drop(h, iid)
        from .. import card as cardmod
        name = cardmod.name_from(d["text"].splitlines()[0])[:40].strip("-") or "todo"
        q = {"objective": d["text"], "name": name}
        if d.get("board"):
            q["board"] = d["board"]
        return RedirectResponse("/new?" + urllib.parse.urlencode(q), status_code=303)

    async def brief_page(request):
        """A day's focus brief (docs/collaboration.md §9.4), and the days before."""
        from .. import brief
        h = home or registry.home()
        day = request.path_params.get("day") or time.strftime("%Y-%m-%d")
        b = await run_in_threadpool(brief.load, h, day)
        if b is None and "day" in request.path_params:
            return not_found(request, "a brief for %s" % day)
        cols, broken = await board_of()
        cards = [c for cs in cols.values() for c in cs]
        rows = await run_in_threadpool(brief.live_rows, h, b, cards) if b else None
        w = brief.writing() if day == time.strftime("%Y-%m-%d") else None
        return await arender(request, "brief.html", b=b, day=day, days=brief.days(h), rows=rows,
                      writing=w, now_s=time.time(),
                      html=data.md(brief.render(b, ("head", "decide", "close_out", "runs") if rows else ()))
                      if b else None, side=data.side(home, cols, broken), here=None)

    async def brief_build(request):
        """Build today's brief again now."""
        from .. import brief, executor
        f = await form(request)
        started = await run_in_threadpool(brief.build_soon, home or registry.home())
        msg = ("today's brief rebuilt; the model is writing its version, which replaces it "
               "in about 3 minutes" if started else "today's brief is already being rebuilt")
        return back(local((f.get("back") or [""])[0], "/brief"),
                    executor.Outcome(executor.OK, msg), poke_runner=False)

    async def brief_run(request):
        """Go: hand the ticked proposed runs of a day's brief to the runner."""
        from .. import brief, executor
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0]
        day = one("day") or time.strftime("%Y-%m-%d")
        picks = {}
        for v in f.get("run") or ():
            if v.isdigit():
                picks[int(v)] = one("text.%s" % v)
        if not picks:
            return back("/brief/%s" % day, executor.Outcome(executor.USAGE,
                                                            "tick the runs to start"),
                        poke_runner=False)
        got = await run_in_threadpool(brief.launch, home or registry.home(), day, picks,
                                      who(request))
        bad = ["%s: %s" % (p, o.msg) for p, o in got if o.code != executor.OK]
        ok = [p for p, o in got if o.code == executor.OK]
        msg = "; ".join((["handed off: " + ", ".join(ok)] if ok else []) + bad)
        return back("/brief/%s" % day, executor.Outcome(
            executor.USAGE if bad and not ok else executor.OK, msg))

    async def brief_feedback(request):
        """"Not today" or "done already" on a suggestion; the brief is rebuilt."""
        from .. import brief, executor
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        h = home or registry.home()
        try:
            brief.say(h, time.strftime("%Y-%m-%d"), one("project"), one("kind"))
        except ValueError:
            return back("/", executor.Outcome(executor.USAGE, "say not today or done already"),
                        poke_runner=False)
        await run_in_threadpool(brief.apply_feedback, h)
        return back(local(one("back"), "/"), executor.Outcome(executor.OK, "%s: %s" % (
            one("project"), one("kind"))), poke_runner=False)

    async def _rhythm(request, **kw):
        from .. import reviews
        cols, broken = await board_of()
        return await arender(request, "rhythm.html", side=data.side(home, cols, broken), here=None,
                      boards=registry.boards(home), kept=reviews.kept(home or registry.home()),
                      **kw)

    async def review_page(request):
        """The weekly review (docs/collaboration.md §9.5, plan F3e): a week's, else
        this week's so far (a draft, not written)."""
        from .. import reviews
        h = home or registry.home()
        week = request.path_params.get("week")
        r = await run_in_threadpool(reviews.load_review, h, week) if week else None
        note = None
        if week and r is None:
            return not_found(request, "a review for %s" % week)
        if r is None:
            got = reviews.reviews(h, 1)
            this = reviews._week(clock.now().timestamp())[0]
            r = await run_in_threadpool(reviews.load_review, h, got[0]) \
                if got and got[0] == this else None
            if r is None:
                r = await run_in_threadpool(lambda: reviews.weekly(h, write=False))
                note = ("This week so far, not kept yet: the board writes the review on "
                        "[focus] review_day after review_time (Friday 16:00 unless set).")
        text = reviews.render_weekly(r)
        return await _rhythm(request, kind="review", title="Week %s · Review" % r["week"], r=r,
                       back_to="/review",
                       md=text, html=data.md(text), weeks=reviews.reviews(h), note=note,
                       keep_name=None)

    async def review_build(request):
        from .. import executor, reviews
        r = await run_in_threadpool(reviews.weekly, home or registry.home())
        return back("/review", executor.Outcome(executor.OK, "week %s's review written"
                                                % r["week"]), poke_runner=False)

    async def review_tidy(request):
        """**Tidy the backlog**: each project keep, someday or drop."""
        from .. import executor, reviews
        if not is_owner(request):
            return back("/review", executor.Outcome(executor.USAGE, "only the board's owner "
                                                    "can tidy it"), poke_runner=False)
        f = await form(request)
        choices = {k: v[0] for k, v in f.items() if k not in ("csrf", "back") and v
                   and v[0] in ("keep", "someday", "drop")}
        try:
            got = await run_in_threadpool(reviews.tidy, home or registry.home(), choices,
                                          who(request))
        except Exception as ex:         # noqa: BLE001: say what failed
            return back("/review#tidy", executor.Outcome(executor.USAGE, str(ex)),
                        poke_runner=False)
        return back("/review#tidy", executor.Outcome(executor.OK, "; ".join(got) or
                                                     "nothing changed"), poke_runner=False)

    async def standup_page(request):
        from .. import reviews
        s = await run_in_threadpool(reviews.standup, home or registry.home())
        text = reviews.render_standup(s)
        return await _rhythm(request, kind="standup", title="Standup %s" % s["day"], md=text,
                       back_to="/standup",
                       html=data.md(text), keep_name=None)

    async def status_page(request):
        from .. import milestones, reviews
        h = home or registry.home()
        b = request.path_params["board"]
        m = request.path_params.get("milestone")
        if b not in [x["name"] for x in registry.boards(h)]:
            return not_found(request, "board %s" % b)
        if m and milestones.get(b, m, h) is None:
            return not_found(request, "milestone %s on %s" % (m, b))
        s = await run_in_threadpool(lambda: reviews.status(h, b, m))
        text = reviews.render_status(s)
        return await _rhythm(request, kind="status", title="Status: %s%s" % (b, " · " + m if m else ""),
                       back_to="/status/%s%s" % (urllib.parse.quote(b),
                                                 "/" + urllib.parse.quote(m) if m else ""),
                       md=text, html=data.md(text), keep_name=b + ("-" + m if m else ""))

    async def report_keep(request):
        """**Keep a copy** of a draft: written to ``reports/``."""
        from .. import executor, milestones, reviews
        h = home or registry.home()
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        kind, name = one("kind"), one("name")
        if kind == "review":
            text = reviews.render_weekly(await run_in_threadpool(
                lambda: reviews.weekly(h, write=False)))
        elif kind == "standup":
            text = reviews.render_standup(await run_in_threadpool(reviews.standup, h))
        elif kind == "status":
            boards = [x["name"] for x in registry.boards(h)]
            # "<board>" or "<board>-<milestone>"; a board's name may hold "-" too
            b = name if name in boards else max(
                (x for x in boards if name.startswith(x + "-")), key=len, default="")
            m = name[len(b) + 1:]
            if b not in boards or (m and milestones.get(b, m, h) is None):
                return back("/", executor.Outcome(executor.USAGE, "no such status"),
                            poke_runner=False)
            text = reviews.render_status(await run_in_threadpool(
                lambda: reviews.status(h, b, m or None)))
        else:
            return back("/", executor.Outcome(executor.USAGE, "nothing to keep"),
                        poke_runner=False)
        p = await run_in_threadpool(reviews.keep, h, kind, name, text)
        return back(local(one("back"), "/review"), executor.Outcome(
            executor.OK, "kept as reports/%s" % os.path.basename(p)), poke_runner=False)

    async def shutdown_page(request):
        """The end of the day (docs/collaboration.md §9.5)."""
        from .. import brief
        s = await run_in_threadpool(brief.shutdown, home or registry.home())
        cols, broken = await board_of()
        return await arender(request, "shutdown.html", s=s, side=data.side(home, cols, broken),
                      here=None)

    async def shutdown_handoff(request):
        """Load the night shift: hand each ticked project to the runner, to start
        when you leave (``defer``)."""
        from .. import executor
        from ..packet import Packet
        f = await form(request)
        done, bad = [], []
        for name in f.get("project") or ():
            e = registry.get(name, home)
            if e is None:
                continue
            out = await run_in_threadpool(lambda: executor.admin(
                Packet(layout.run_dir(e["path"], e["root"])), "handoff", None, None,
                who(request), defer=True))
            (done if out.code == 0 else bad).append("%s%s" % (name, "" if out.code == 0
                                                              else " (%s)" % out.msg))
        msg = "handed off for tonight: %s" % (", ".join(done) or "nothing")
        if bad:
            msg += "; not: %s" % "; ".join(bad)
        return back("/shutdown", executor.Outcome(executor.USAGE if bad else executor.OK, msg))

    async def visited(request):
        """The Desk's beacon: you are looking at it now (docs/collaboration.md §8.1)."""
        from starlette.responses import Response
        from .. import attention
        await run_in_threadpool(attention.visit, home or registry.home(), who(request))
        return Response(status_code=204)

    async def snooze(request):
        """Snooze a Needs-you row (docs/collaboration.md §4.3): ``key``, ``until``
        (1h, tomorrow or change), ``back``."""
        from .. import attention, executor
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        k, until = one("key"), one("until")
        if one("item"):                 # a row's button: "<key>@@<until>"
            k, _, until = one("item").rpartition("@@")
        if not k or len(k) > 400:
            return back(local(one("back"), "/"), executor.Outcome(executor.USAGE, "no item"),
                        poke_runner=False)
        await run_in_threadpool(attention.snooze, home or registry.home(), who(request), k,
                                attention.until_of(until or "1h"))
        what = {"1h": "for an hour", "tomorrow": "until tomorrow"}.get(
            until, "until something changes")
        return back(local(one("back"), "/"), executor.Outcome(executor.OK, "snoozed " + what),
                    poke_runner=False)

    async def hooks_switch(request):
        """Claude Code hooks in packet folders on or off for the board
        (docs/collaboration.md §10): every registered packet folder follows."""
        from .. import executor, ide, sessionhooks
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        on = one("on") == "1"
        if not is_owner(request):
            return back(local(one("back"), "/"), executor.Outcome(
                executor.USAGE, "only the board's owner can turn this on or off"),
                poke_runner=False)
        h = home or registry.home()
        await run_in_threadpool(sessionhooks.set_enabled, h, on, who(request))
        got = await run_in_threadpool(sessionhooks.apply_all, h, ide.load_config(h))
        bad = sorted(k for k, v in got.items()
                     if v not in ("installed", "unchanged", "removed"))
        msg = "Claude Code hooks in packet folders: %s" % ("on" if on else "off")
        if bad:
            msg += "; could not change %s (see the packet page)" % ", ".join(bad)
        return back(local(one("back"), "/"), executor.Outcome(
            executor.USAGE if bad else executor.OK, msg), poke_runner=False)

    async def settings_page(request):
        """The board's Settings (plan C6, §2a): the config.toml keys you change day to
        day, the hooks switch, pushes and browser notifications."""
        from .. import ide, sessionhooks, settings
        h = home or registry.home()
        cols, broken = await board_of()
        cur = await run_in_threadpool(settings.current, home)
        rows = [{"name": "%s.%s" % (t, k), "type": typ.__name__, "label": lb,
                 "value": "" if (t, k) in settings.SECRET else cur[(t, k)],
                 "set": bool(cur[(t, k)]), "secret": (t, k) in settings.SECRET,
                 "default": d, "table": t} for t, k, typ, d, lb in settings.KEYS]
        return await arender(request, "settings.html", rows=rows, owner=is_owner(request),
                      notes=registry.notes(None, home), notes_path=registry.notes_path(None, home),
                      hooks=sessionhooks.enabled(ide.load_config(h), h),
                      side=data.side(home, cols, broken), here=None)

    async def settings_notes_post(request):
        """Your notes for agents, ``$WPK_HOME/agent.md`` (docs/agent-dispatch.md §4)."""
        from .. import executor, fsutil
        to = "/settings#agent-notes"
        if not is_owner(request):
            return back(to, executor.Outcome(executor.USAGE, "only the board's owner can "
                                             "change them"), poke_runner=False)
        f = await form(request)
        notes = (f.get("notes") or [""])[0].replace("\r\n", "\n")
        path = registry.notes_path(None, home)
        if notes.strip() == registry.notes(None, home).strip():
            return back(to, executor.Outcome(executor.OK, "nothing changed"), poke_runner=False)
        try:
            if notes.strip():
                await run_in_threadpool(fsutil.atomic_write, path, notes.rstrip("\n") + "\n")
            elif os.path.exists(path):
                os.unlink(path)
        except OSError as ex:
            return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        return back(to, executor.Outcome(executor.OK, "saved your notes"), poke_runner=False)

    async def settings_post(request):
        from .. import executor, settings
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        if not is_owner(request):
            return back("/settings", executor.Outcome(
                executor.USAGE, "only the board's owner can change its settings"),
                poke_runner=False)
        try:
            changes = settings.parse({k: v[0] for k, v in f.items() if v})
            got = await run_in_threadpool(settings.save, changes, home)
        except settings.SettingsError as ex:
            return back("/settings", executor.Outcome(executor.USAGE, str(ex)),
                        poke_runner=False)
        return back("/settings", executor.Outcome(executor.OK, "saved: %s" % ", ".join(got)
                                                  if got else "nothing changed"),
                    poke_runner=False)

    async def settings_test_push(request):
        """Send a test push to the ntfy topic in Settings."""
        from .. import executor, notify
        await form(request)
        if not is_owner(request):
            return back("/settings", executor.Outcome(executor.USAGE, "only the board's owner"),
                        poke_runner=False)
        try:
            cfg = registry.load_config_file(home).get("notify") or {}
            await run_in_threadpool(notify.test, cfg)
            out = executor.Outcome(executor.OK, "test push sent: check your phone")
        except (notify.NotifyError, registry.ConfigError) as ex:
            out = executor.Outcome(executor.USAGE, "no push: %s" % ex)
        return back("/settings#notify", out, poke_runner=False)

    async def attention_json(request):
        """What a board tab should notify about (``dash/notify.js``): questions and
        blocked sessions past their threshold, not snoozed, not in a visible tab.
        Reads only."""
        from .. import attention, notify
        h = home or registry.home()
        cols, _ = await board_of()
        cfg = notify.config(registry.load_config_file(home).get("notify"))
        now = time.time()
        snz = attention.snoozes(h, who(request), now)
        its = [it for it in notify.items(cols, now)
               if notify.pushable(it, cfg, now, browser=True) and it["key"] not in snz]
        return JSONResponse({"items": [{"key": it["key"], "title": notify._title(it),
                                        "text": it["text"], "url": it["url"]} for it in its]})

    async def split_post(request):
        """**Bring it in** or **Drop the split** (docs/collaboration.md §5.4)."""
        from .. import executor, split as split_mod
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        to = "/p/%s#split" % urllib.parse.quote(e["name"])
        if not is_owner(request):
            return back(to, executor.Outcome(executor.USAGE,
                                             "only the board's owner can do that"),
                        poke_runner=False)
        f = await form(request)
        op = (f.get("op") or [""])[0]
        try:
            if op == "land":
                msg = await run_in_threadpool(split_mod.land, e, who(request))
                info = split_mod.info(e)
                to = "/p/%s" % urllib.parse.quote(info["of"]) if info else to
            elif op == "drop":
                msg = await run_in_threadpool(split_mod.drop, e, who(request))
            elif op == "remove":            # its folder, once done or dropped (plan G7)
                info = split_mod.info(e)
                msg = await run_in_threadpool(split_mod.remove, e, who(request), home)
                to = "/p/%s#split" % urllib.parse.quote(info["of"]) if info else "/"
            else:
                raise split_mod.SplitError("unknown action %r" % op)
        except split_mod.SplitError as ex:
            return back(to, executor.Outcome(executor.USAGE, str(ex)), poke_runner=False)
        return back(to, executor.Outcome(0, msg), poke_runner=False)

    async def job_page(request):
        """One job (docs/collaboration.md W7): its command, times, exit and the
        log's tail. Opening an ended job is seeing it, as opening a finished
        project is reviewing it."""
        from .. import jobs
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        d = await run_in_threadpool(jobs.get, e["path"], request.path_params["job"])
        if d is None:
            return not_found(request, "job %s" % request.path_params["job"])
        if not d["seen"] and d["state"] != "running" and is_owner(request):
            await run_in_threadpool(jobs.mark_seen, e["path"], d["id"])
        log = await run_in_threadpool(jobs.tail, e["path"], d["id"])
        return await arender(request, "job.html", e=e, j=d, log=log, cmd=jobs.quote(d["cmd"]),
                      live=d["state"] == "running",
                      took=views.span((d["end"] or time.time()) - d["start"]))

    async def job_post(request):
        """**Run a command** for the project: ``wpk run`` in its folder, detached."""
        from .. import executor, jobs
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        to = "/p/%s#jobs" % urllib.parse.quote(e["name"])
        if not is_owner(request):
            return back(to, executor.Outcome(executor.USAGE,
                                             "only the board's owner can run commands"),
                        poke_runner=False)
        f = await form(request)
        cmd = (f.get("cmd") or [""])[0].strip()
        try:
            await run_in_threadpool(jobs.run_detached, e["path"], cmd, jobs.folder(e["path"]))
        except (jobs.JobError, OSError) as ex:
            return back(to, executor.Outcome(executor.USAGE, "could not run it: %s" % ex),
                        poke_runner=False)
        return back(to, executor.Outcome(0, "started: %s" % cmd), poke_runner=False)

    async def status_json(request):
        """A project at a glance (docs/collaboration.md §7.10), for a status bar
        or a status line to poll. Reads only."""
        e = entry(request)
        if e is None:
            return JSONResponse({"error": "no such project"}, status_code=404)
        c = await run_in_threadpool(data.card, e)
        return JSONResponse(data.glance(c))

    async def checkpoint_draft(request):
        """A status drafted from the packet's latest session (docs/session-checkpoint.md
        §4.2), for the Update status form to fill in: JSON ``{status, body, next}``
        or ``{error}``. Asked for by the person, so it does not wait for
        ``[ide] sessions_scribe``; nothing is recorded."""
        from .. import ide_sessions, scribe
        from ..packet import Packet
        e = entry(request)
        wpid = request.path_params["wpid"]
        if e is None or data.packet(e, wpid) is None:
            return JSONResponse({"error": "no packet %s" % wpid}, status_code=404)
        pkt = Packet(layout.run_dir(e["path"], wpid))
        h = home or registry.home()
        recs = [r for r in ide_sessions.cached_records(h)
                if r.get("project") == e["name"] and r.get("wpid") == wpid]
        recs.sort(key=lambda r: r.get("last_activity_t") or 0, reverse=True)
        for r in recs:
            paths = scribe.transcripts(h, r)
            if paths:
                got, _ = await run_in_threadpool(scribe.draft, pkt, r["harness"], paths, h)
                if got is None:
                    return JSONResponse({"error": "the model gave no draft; try again"})
                return JSONResponse(got)
        return JSONResponse({"error": "no session of this packet whose transcript this "
                                      "board can read"})

    async def project_run(request):
        """Pause, Resume or Stop now a whole project (docs/pause-v1.md): from its
        page, the Overview and the boards. ``back``: the page to return to."""
        from .. import actions, executor
        from ..sched import authz
        e = entry(request)
        if e is None:
            return not_found(request, "project %s" % request.path_params["project"])
        if archived.is_archived(e):
            return back("/p/%s" % urllib.parse.quote(e["name"]),
                        executor.Outcome(executor.USAGE, "%s is archived" % e["name"]))
        f = await form(request)
        one = lambda k: (f.get(k) or [""])[0].strip()
        op, by = one("op"), who(request)
        if op == "pause":
            out = await run_in_threadpool(actions.pause_project, e, by)
        elif op == "resume":
            out = await run_in_threadpool(actions.resume_project, e, by)
        elif op == "stop":
            no = denied(request, "cancel")
            if no:
                return no
            out = await run_in_threadpool(actions.stop_project, e, authz.principal_of(request),
                                          home)
        else:
            out = executor.Outcome(executor.USAGE, "unknown action %r" % op)
        to = one("back")
        if not to.startswith("/") or to.startswith("//"):
            to = "/p/%s" % urllib.parse.quote(e["name"])
        return back(to, out, poke_runner=op == "resume")

    async def console_cmd(request):
        """One line from the console drawer (docs/console.md): a slash command,
        or a question for the agent, whose reply streams on /console/ws.
        JSON in (``line``, ``path``: the page it was typed on), JSON out."""
        from . import console
        from ..sched import authz
        try:
            body = json.loads((await request.body()) or b"{}")
        except ValueError:
            body = {}
        ctx = console.Ctx(home, who(request), authz.principal_of(request), poke, agents)
        out = await run_in_threadpool(console.line, str(body.get("line") or ""),
                                      console.scope_of(str(body.get("path") or "/")), ctx,
                                      body.get("ref"), body.get("decline"))
        return JSONResponse(out)

    def conv_rows(pred):
        """Conversations ``pred(meta)`` keeps, for the history pages."""
        if agents is None:
            return []
        return [dict(m, href="/console/c/%s" % m["id"],
                     page=_scope_href(m), busy=agents.busy(m["id"]))
                for m in agents.list() if pred(m)]

    async def console_list(request):
        """Every conversation the console has had (docs/console.md §5)."""
        rows = await run_in_threadpool(conv_rows, lambda m: True)
        cols, broken = await run_in_threadpool(data.board, home)
        return await arender(request, "console_list.html", rows=rows, agent_on=agents is not None,
                      side=data.side(home, cols, broken))

    async def console_view(request):
        """One conversation's transcript, read-only."""
        from . import console
        m = agents.get(request.path_params["cid"]) if agents is not None else None
        if m is None:
            return not_found(request, "conversation %s" % request.path_params["cid"])
        ev = await run_in_threadpool(agents.transcript, m["id"], 100000)
        acted = {}
        for x in ev:
            if x.get("ref"):
                acted[x["ref"]] = "declined" if x["k"] == "decline" else (
                    "ran" if not x.get("auto") else "ran at once")
        for x in ev:
            if x["k"] == "say":
                lines = x["text"].split("\n")
                props = {p["at"]: p for p in x.get("props") or []}
                x["parts"] = [(ln, props.get(i), acted.get("%s:%d" % (x.get("id"), props[i]["i"]))
                               if i in props else None) for i, ln in enumerate(lines)]
        return await arender(request, "console_view.html", m=dict(m, page=_scope_href(m)), ev=ev,
                      scope=console.scope_of(_scope_href(m)), busy=agents.busy(m["id"]))

    async def project_console(request, e, now, kw):
        rows = await run_in_threadpool(conv_rows, lambda m: m.get("project") == e["name"])
        return await arender(request, "project_console.html", rows=rows, agent_on=agents is not None,
                      **kw)

    async def console_commands(request):
        from . import console
        return JSONResponse(console.complete())

    async def console_conv(request):
        """The page's current conversation and its transcript (``?path=``)."""
        from . import agent, console
        if agents is None:
            return JSONResponse({"conv": None, "events": [], "agent": False})
        sc = console.scope_of(request.query_params.get("path") or "/")
        m = await run_in_threadpool(agents.latest, agent.scope_key(sc))
        if m is None:
            return JSONResponse({"conv": None, "events": [], "agent": True})
        ev = await run_in_threadpool(agents.transcript, m["id"])
        return JSONResponse({"conv": {k: m[k] for k in ("id", "model", "title", "cwd")},
                             "events": ev, "busy": agents.busy(m["id"]), "agent": True})

    async def console_ws(ws):
        """A conversation's events as they happen. The first message carries
        the CSRF token, as the shell's does; ``?since=`` replays what came after."""
        import asyncio
        import hmac
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive_text(), 5)
            token = (json.loads(first) or {}).get("token") or ""
        except (asyncio.TimeoutError, ValueError, KeyError, TypeError, AttributeError,
                WebSocketDisconnect):
            token = ""
        want = ws.scope.get("state", {}).get("csrf") or ""
        cid = ws.path_params["cid"]
        if agents is None or not want or not hmac.compare_digest(token, want) \
                or agents.get(cid) is None:
            return await ws.close(1008)
        queue = asyncio.Queue()
        agents.subscribe(cid, asyncio.get_running_loop(), queue)
        try:
            since = float(ws.query_params.get("since") or 0)
        except ValueError:
            since = 0.0
        try:
            await ws.send_text(json.dumps({"k": "busy", "on": agents.busy(cid)}))
            for ev in await run_in_threadpool(agents.transcript, cid):
                if ev.get("t", 0) > since:
                    await ws.send_text(json.dumps(ev))
            rx = asyncio.ensure_future(ws.receive())
            while True:
                get = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({rx, get}, return_when=asyncio.FIRST_COMPLETED)
                if rx in done:
                    get.cancel()
                    if rx.result()["type"] == "websocket.disconnect":
                        break
                    rx = asyncio.ensure_future(ws.receive())
                    continue
                await ws.send_text(json.dumps(get.result()))
            rx.cancel()
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            agents.unsubscribe(cid, queue)
            if ws.client_state == WebSocketState.CONNECTED and \
                    ws.application_state == WebSocketState.CONNECTED:
                try:
                    await ws.close()
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass

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
        # Opening it to work on it takes it from the runner until you hand it back
        # (docs/collaboration.md §5.1): you, not the runner, work in it now.
        from .. import actions
        paused = await run_in_threadpool(actions.claim, e, who(request))
        if paused.code != 0:
            url = "/p/%s" % urllib.parse.quote(e["name"]) + ("/%s" % wpid if wpid else "")
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
                                              one("size") or None, e["name"],
                                              op.wpid, who(request))
            except dide.IdeUnavailable as ex:
                return not_found(request, "web VS Code here (%s)" % ex)
            return RedirectResponse(ide.web_path(op, "/ide/%s/" % key), status_code=303)
        # Desktop VS Code: the board hears from it only through Claude's hooks, so the
        # open itself counts as presence for a while (docs/collaboration.md §4.2).
        from .. import presence
        await run_in_threadpool(presence.beat, e["path"], "ide-desktop-%s" % (who(request) or "you"),
                                None, kind="ide-desktop", via="ide-desktop", wpid=op.wpid,
                                by=who(request))
        st = request.scope.get("state", {})
        name = None
        if st.get("listener") == "tailnet":     # the name the browser used: it resolves there
            name = split_host(request.headers.get("host", ""))[0]
        host = ide.ssh_host(cfg, name=name)
        links = {"remote": ide.desktop_url(op, host), "local": ide.desktop_url(op)}
        first = ide.desktop_choice(cfg, st.get("listener"), request.headers.get("user-agent"))
        return await arender(request, "ide_open.html", e=e, op=op, wpid=wpid, paused=paused,
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

    def new_page(request, starter, values, preview=None, recipe=None, error=None, status=200,
                 job=None):
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
        # With a packet directory set, an empty dir means "the board's" (folder_of).
        if registry.packet_dir(vals.get("board"), None, home) is None:
            vals.setdefault("dir", base)
        st = starters.get(starter)
        return render(request, "new.html", status=status, projects=es, model=cfg["model"],
                      boards=[b["name"] for b in registry.boards(home)],
                      harness=cfg["harness"], choices=data.model_choices(home),
                      starters=[starters.get(n) for n in starters.names()], starter=st,
                      fields=st.all_fields(), values=vals, preview=preview,
                      recipe=starters.dumps(recipe) if recipe else "", error=error,
                      broken=starters.broken(), job=job,
                      clone=(recipe or {}).get("clone"), clone_tools=starters.CLONE_TOOLS,
                      clone_tool=cfg.get("clone_tool") or "ivpm")

    def _starter_of(vals):
        from .. import starters
        n = vals.get("starter") or ("clone" if vals.get("clone") else "folder")
        return n if n in starters.names() else "folder"

    async def new_form(request):
        q = dict(request.query_params)
        q.pop("msg", None), q.pop("ok", None)
        job = jobs.get(q.pop("job", ""))      # a Create still going (or just gone): its panel
        return new_page(request, _starter_of(q), q, job=job)

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
        # How to start (docs/collaboration.md W1): ide, studio, handoff or none.
        # ``go=1`` is the old form's "hand it to the runner at once".
        start = vals.pop("start", "") or ("handoff" if vals.pop("go", "") == "1" else "none")
        vals.pop("go", None)
        how = vals.pop("ide", "") or "web"
        if start == "ide":
            start = "ide-desktop" if how == "desktop" else "ide-web"
        if start not in STARTS:
            start = "none"
        go = start == "handoff"
        rtext = vals.pop("recipe", "")
        tool = vals.pop("clone_tool", "")
        bg = "application/json" in request.headers.get("accept", "")   # new.js: a job

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
            if tool and r.get("clone"):
                r["clone"]["tool"] = tool
                r = starters.check(r)
            r["hold"] = not go
            if go and not (r.get("objective") or "").strip():
                raise starters.StartError("write the objective first: it is what the runner "
                                          "is told to do (or start it another way)")
            return r
        try:
            r = await run_in_threadpool(recipe_of)
            if action == "preview":
                lines = await run_in_threadpool(starters.preview, r, home)
                return new_page(request, starter, dict(vals, name=r["name"],
                                                       objective=r.get("objective", "")),
                                preview=lines, recipe=r)
            if bg:
                await run_in_threadpool(starters.preview, r, home)   # refusals, at once
                jid = jobs.start(r, starters.folder_of(r, home), lambda plan: made(plan, start), home)
                return JSONResponse({"job": jid, "ws": "/new/job/%s/ws" % jid,
                                     "log": "/new/job/%s/log" % jid})
            plan = await run_in_threadpool(starters.make, r, home)
        except (starters.StartError, registry.ConfigError, ValueError, OSError) as ex:
            if bg:
                return JSONResponse({"error": str(ex)}, status_code=400)
            if action == "preview" or rtext:
                return new_page(request, starter, vals, error=str(ex))
            q = urllib.parse.urlencode({"msg": str(ex), "ok": "0", "name": vals.get("name", ""),
                                        "starter": starter})
            return RedirectResponse("/new?" + q, status_code=303)
        return RedirectResponse(made(plan, start), status_code=303)

    def made(plan, start):
        """The page to go to once ``plan`` is made (``start``: one of ``STARTS``): its
        overview, which for VS Code or the studio opens it (``open=``)."""
        q = {"ok": "1"}
        url = "/p/%s" % urllib.parse.quote(plan.name)     # its overview, however it starts
        if start == "handoff":
            poke()
            q["msg"] = "created %s at %s; the runner has it" % (plan.name, plan.path)
        elif start == "none":
            q["msg"] = "created %s at %s" % (plan.name, plan.path)
        else:
            q.update(open=start, msg="created %s at %s; opening it" % (plan.name, plan.path))
        return "%s?%s" % (url, urllib.parse.urlencode(q))

    async def new_job_ws(ws):
        """A Create job's events (dash-create-progress-design.md): the CSRF token
        first, as the console's; ``?since=`` (an event's ``n``) replays what came
        after. Closes after the last (``done``)."""
        import asyncio
        import hmac
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive_text(), 5)
            token = (json.loads(first) or {}).get("token") or ""
        except (asyncio.TimeoutError, ValueError, KeyError, TypeError, AttributeError,
                WebSocketDisconnect):
            token = ""
        want = ws.scope.get("state", {}).get("csrf") or ""
        jid = ws.path_params["jid"]
        if not want or not hmac.compare_digest(token, want) or jobs.get(jid) is None:
            return await ws.close(1008)
        try:
            since = int(ws.query_params.get("since") or 0)
        except ValueError:
            since = 0
        queue = asyncio.Queue()
        try:
            for ev in jobs.subscribe(jid, asyncio.get_running_loop(), queue, since):
                await ws.send_text(json.dumps(ev))
                if ev["k"] == "done":
                    return
            rx = asyncio.ensure_future(ws.receive())
            while True:
                get = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({rx, get}, return_when=asyncio.FIRST_COMPLETED)
                if rx in done:
                    get.cancel()
                    if rx.result()["type"] == "websocket.disconnect":
                        break
                    rx = asyncio.ensure_future(ws.receive())
                    continue
                ev = get.result()
                await ws.send_text(json.dumps(ev))
                if ev["k"] == "done":
                    break
            rx.cancel()
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            jobs.unsubscribe(jid, queue)
            if ws.client_state == WebSocketState.CONNECTED and \
                    ws.application_state == WebSocketState.CONNECTED:
                try:
                    await ws.close()
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass

    async def new_job_log(request):
        text = await run_in_threadpool(jobs.log, request.path_params["jid"])
        if text is None:
            return not_found(request, "job %s" % request.path_params["jid"])
        return PlainTextResponse(text)

    async def new_job_cancel(request):
        """Cancel a Create job: its clone is stopped and removed (JSON out)."""
        if not jobs.cancel(request.path_params["jid"]):
            return JSONResponse({"error": "no such job running"}, status_code=404)
        return JSONResponse({"ok": True})

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
        rl = await run_in_threadpool(data.review_load, home)
        from .. import split as split_mod
        return await arender(request, "compose.html", e=e, c=c, settings=data.settings(e), rl=rl,
                      split_ok=c["mode"] == "next" and split_mod.allowed(e) is None,
                      shells=shells.of_project(e["name"]) if shells else [],
                      shell_ok=shells is not None and vendored.built("term"))

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
        after = one("after") == "1"             # wait until nobody works on it (§5.2)
        if op == "requeue":             # queued: change what it starts from (plan G5)
            out = await run_in_threadpool(executor.requeue, tg.packet, text, by)
            return back(compose_url(e), out, poke_runner=False)
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
            if op == "split":
                # The runner works beside you, in a copy (W4, W6, §5.4)
                from .. import split as split_mod
                await run_in_threadpool(save)
                try:
                    name = await run_in_threadpool(split_mod.make, e, text, note, by, home)
                except split_mod.SplitError as ex:
                    raise setup.SetupError(str(ex)) from None
                return back("/p/%s" % urllib.parse.quote(name), executor.Outcome(
                    executor.OK, "split: %s works on it in its own copy; your folder is "
                    "left alone" % name))
            if op == "handoff":
                await run_in_threadpool(save)
                if c["mode"] == "setup":
                    if c["missing"] and not force:
                        raise setup.SetupError("%d check%s missing; fix them or hand off "
                                               "anyway" % (c["missing"], "" if c["missing"]
                                                           == 1 else "s"))
                    out = await run_in_threadpool(lambda: executor.admin(
                        tg.packet, "handoff", note or None, None, by, defer=after))
                else:
                    out = await run_in_threadpool(
                        actions.continue_, tg.packet, text, note or None, archive, carry,
                        force, by, after)
                # Your shells stay open: you may go on working beside the runner (§5.2).
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
        lv = await run_in_threadpool(lambda: data.live(e, request.path_params["wpid"], view=view)) \
            if e else None
        if lv is None:
            return not_found(request, "packet %s" % request.path_params["wpid"])
        await run_in_threadpool(mark_seen, request, e)
        dfm = await run_in_threadpool(dfmrun.runs, dfm_home(), wpid=request.path_params["wpid"],
                                      step=lv["step"]["n"]) if lv["step"] else []
        return await arender(request, "live.html", e=e, l=lv, view=view, live=True, dfm=dfm,
                      dfm_pids={r["pid"]: r for r in dfm if r["live"] and r["pid"]},
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
        its source; an image as itself; other text as it is; a binary file as a
        download."""
        if os.path.getsize(p) > FILE_MAX:
            return PlainTextResponse("%s: %d bytes, too large to show here; it is at %s\n"
                                     % (rel, os.path.getsize(p), p))
        with open(p, "rb") as fp:
            raw = fp.read()
        image = IMAGES.get(os.path.splitext(p)[1].lower())
        if image is not None:       # inline, so a Markdown file's ![](...) shows it
            return Response(raw, media_type=image, headers={
                "content-security-policy": "sandbox; default-src 'none'; "
                                           "style-src 'unsafe-inline'"})
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
        return await arender(request, "plan.html", e=e, pl=pl, MARK=plan.MARK)

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
            return await arender(request, "doc.html", e=e, wpid=None, rel=rel, html=None,
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
        if name not in STATIC and name.startswith("vendor/"):
            return _vendored(request, name[len("vendor/"):])
        if name not in STATIC:
            return PlainTextResponse("not found\n", status_code=404)
        try:
            with open(os.path.join(HERE, name), "rb") as fp:
                body = fp.read()
        except OSError:
            return PlainTextResponse("not found\n", status_code=404)
        return Response(body, media_type=STATIC[name], headers={"cache-control": "max-age=300"})

    async def content_file(request):
        """``/sc/<token>/<path>``: a file of a studio's folder, on the sandboxed
        content origin (``studio/content.py``; the guard checked the token)."""
        from ..studio import content
        root = request.scope.get("state", {}).get("content_root")
        if root is None:            # not through the guard: no token was checked
            token = request.path_params["token"]
            root = content.TOKENS.resolve(token)
            if root is None:
                return PlainTextResponse("no such content\n", status_code=403)
        path = content.file_for(root, request.path_params.get("path", ""))
        if path is None:
            return PlainTextResponse("not found\n", status_code=404)
        return FileResponse(path, media_type=content.media_type(path))

    async def live_js(request):
        return Response(LIVE_JS, media_type="text/javascript",
                        headers={"cache-control": "max-age=300"})

    async def ide_http(request):
        from . import ide as dide
        if ide_backend is None or not ide_config().get("web"):
            return PlainTextResponse("not found\n", status_code=404)
        return await dide.proxy_http(ide_backend, request)

    async def fwd_http(request):
        """``/fwd/<token>/<path>``: a localhost page of web VS Code's host, on the
        sandboxed content origin (``dash/ide_forward.py``; the guard checked the token)."""
        from . import ide_forward
        if ide_backend is None or not ide_config().get("web") or \
                not ide_backend.cfg.get("forward", True):
            return PlainTextResponse("not found\n", status_code=404)
        return await ide_forward.proxy_forward(ide_backend, request)

    async def ide_ws(websocket):
        from . import ide as dide
        if ide_backend is None or not ide_config().get("web"):
            return await websocket.close(1008)
        return await dide.proxy_ws(ide_backend, websocket)

    # The desktop tab (docs/desktop.md): owner only, like /ide/ (the guard).
    def desk_key(request):
        from . import ide as dide
        k = request.path_params["key"]
        return k if dide.KEY.match(k) and ide_backend is not None and \
            ide_backend.get(k) is not None else None

    async def desk_page(request):
        k = desk_key(request)
        if k is None:
            return not_found(request, "desktop %s" % request.path_params["key"])
        from .. import desktop, ide_launch
        h = ide_backend.home
        last = (await run_in_threadpool(ide_launch.opens, h, k) or [{}])[-1]
        back = None
        if last.get("project"):
            back = "/p/%s" % urllib.parse.quote(last["project"]) + \
                ("/%s" % last["wpid"] if last.get("wpid") else "")
        return await arender(request, "desk.html", key=k, back=back,
                      title=desktop.label(h, k, ide_backend.target(k)))

    async def desk_state(request):
        from . import desk
        k = desk_key(request)
        if k is None:
            return JSONResponse({"desktop": False, "why": "no such IDE server"}, status_code=404)
        return JSONResponse(await run_in_threadpool(desk.state, ide_backend, k),
                            headers={"cache-control": "no-store"})

    async def desk_run(request):
        """Start an app of the Apps menu on the desktop (the guard checked the token)."""
        from . import desk
        k = desk_key(request)
        if k is None:
            return JSONResponse({"ok": False, "why": "no such IDE server"}, status_code=404)
        f = await form(request)
        name = (f.get("app") or [""])[0].strip()
        code, why = await run_in_threadpool(desk.run, ide_backend, k, name)
        return JSONResponse({"ok": code == 202, "why": why}, status_code=code)

    async def desk_ws(websocket):
        from . import desk
        k = desk_key(websocket)
        if k is None:
            return await websocket.close(1008)
        return await desk.bridge(ide_backend, websocket, k, websocket.query_params.get("t"))

    from . import studio as studiomod
    studio_routes = studiomod.routes(home, agents, render, entry, who, not_found)
    return Starlette(middleware=[Middleware(ArchivedReadOnly, home=home)], routes=[
        Route("/ide/{rest:path}", ide_http,
              methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
        WebSocketRoute("/ide/{rest:path}", ide_ws),
        Route("/desk/{key}/", desk_page),
        Route("/desk/{key}/state", desk_state),
        Route("/desk/{key}/run", desk_run, methods=["POST"]),
        WebSocketRoute("/desk/{key}/ws", desk_ws),
        Route("/", overview),
        Route("/stats", stats_page),
        Route("/runs", runs_page),
        Route("/runs/{sid}", run_page),
        Route("/runs/{sid}/log.txt", run_log),
        Route("/sched", sched_page),
        Route("/sched.json", sched_json),
        Route("/sched/mode", sched_mode, methods=["POST"]),
        Route("/packets/bulk", bulk, methods=["POST"]),
        Route("/seen", seen, methods=["POST"]),
        *[Route("/p/{project}/%s" % w, setter(w), methods=["POST"])
          for w in ("prio", "size", "hold")],
        *[Route("/p/{project}/{wpid}/%s" % w, setter(w), methods=["POST"])
          for w in ("prio", "size", "next")],
        Route("/boards", board_new, methods=["POST"]),
        Route("/packets", all_packets),
        Route("/b/{board}", board),
        Route("/b/{board}/delete", board_delete, methods=["POST"]),
        Route("/b/{board}/watch/{name}/poll", watch_poll, methods=["POST"]),
        Route("/b/{board}/watch", watch_post, methods=["POST"]),
        Route("/b/{board}/milestones", milestones_post, methods=["POST"]),
        Route("/b/{board}/settings", board_settings_post, methods=["POST"]),
        Route("/review", review_page),
        Route("/review/build", review_build, methods=["POST"]),
        Route("/review/tidy", review_tidy, methods=["POST"]),
        Route("/review/{week}", review_page),
        Route("/standup", standup_page),
        Route("/status/{board}", status_page),
        Route("/status/{board}/{milestone}", status_page),
        Route("/reports/keep", report_keep, methods=["POST"]),
        Route("/p/{project}/board", board_move, methods=["POST"]),
        Route("/p/{project}/pr", pr_open, methods=["POST"]),
        Route("/p/{project}/deliver", deliver_post, methods=["POST"]),
        Route("/p/{project}/run", project_run, methods=["POST"]),
        Route("/healthz", health),
        *panels.mounts(home),
        Route("/console/cmd", console_cmd, methods=["POST"]),
        Route("/console/commands", console_commands),
        Route("/console/conv", console_conv),
        Route("/console", console_list),
        Route("/console/c/{cid}", console_view),
        WebSocketRoute("/console/ws/{cid}", console_ws),
        Route("/static/live.js", live_js),
        Route("/static/pane.js", pane_js),
        Route("/static/{name:path}", static),
        Route("/sc/{token}/{path:path}", content_file),
        Route("/fwd/{token}/{path:path}", fwd_http, methods=["GET", "HEAD"]),
        Route("/new", new_form),
        Route("/new/search", new_search),
        Route("/new", new_create, methods=["POST"]),
        Route("/new/job/{jid}/log", new_job_log),
        Route("/new/job/{jid}/cancel", new_job_cancel, methods=["POST"]),
        WebSocketRoute("/new/job/{jid}/ws", new_job_ws),
        Route("/p/{project}/compose", compose),
        Route("/p/{project}/compose", compose_post, methods=["POST"]),
        Route("/p/{project}/compose/upload", compose_upload, methods=["POST"]),
        Route("/p/{project}/shell/close", shell_close, methods=["POST"]),
        WebSocketRoute("/p/{project}/shell/{sid}", shell_ws),
        Route("/p/{project}/settings", configure, methods=["POST"]),
        Route("/p/{project}/ide", ide_open, methods=["POST"]),
        Route("/p/{project}/doc", doc),
        Route("/p/{project}/docs", docs_build, methods=["POST"]),
        Route("/p/{project}/docs/{entry}/{docset}", docs_file),
        Route("/p/{project}/docs/{entry}/{docset}/{path:path}", docs_file),
        Route("/p/{project}/docslog/{entry}/{docset}", docs_log),
        Route("/p/{project}/markup", markup_post, methods=["POST"]),
        *studio_routes,
        Route("/p/{project}/{wpid}/act", act, methods=["POST"]),
        Route("/p/{project}/{wpid}/checkpoint/draft", checkpoint_draft, methods=["POST"]),
        Route("/sessions/scribe", scribe_switch, methods=["POST"]),
        Route("/sessions/hooks", hooks_switch, methods=["POST"]),
        Route("/attention/snooze", snooze, methods=["POST"]),
        Route("/attention/visit", visited, methods=["POST"]),
        Route("/attention.json", attention_json),
        Route("/settings", settings_page),
        Route("/settings", settings_post, methods=["POST"]),
        Route("/settings/test-push", settings_test_push, methods=["POST"]),
        Route("/settings/notes", settings_notes_post, methods=["POST"]),
        Route("/p/{project}/plan", plan_post, methods=["POST"]),
        Route("/backlog", backlog_page),
        Route("/brief", brief_page),
        Route("/brief/build", brief_build, methods=["POST"]),
        Route("/brief/feedback", brief_feedback, methods=["POST"]),
        Route("/brief/run", brief_run, methods=["POST"]),
        Route("/brief/{day}", brief_page),
        Route("/shutdown", shutdown_page),
        Route("/shutdown/handoff", shutdown_handoff, methods=["POST"]),
        Route("/inbox", capture, methods=["POST"]),
        Route("/inbox/request/decline", inbox_decline, methods=["POST"]),
        Route("/inbox/{iid}/{op}", inbox_item, methods=["POST"]),
        Route("/learn/{iid}", learn_page),
        Route("/learn/{iid}", learn_post, methods=["POST"]),
        Route("/p/{project}/split", split_post, methods=["POST"]),
        Route("/p/{project}/jobs", job_post, methods=["POST"]),
        Route("/p/{project}/jobs/{job}", job_page),
        Route("/p/{project}/status.json", status_json),
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
        Route("/p/{project}/console", project_page(project_console)),
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
