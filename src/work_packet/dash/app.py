"""The Starlette app behind ``wpk dash``. Read-only: no route changes a file."""

import os

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route

from .. import __about__, clock, registry
from . import data

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
REFRESH_S = 10


def _money(v):
    return "" if v is None else "$%.2f" % v if v >= 0.995 else "$%.3f" % v


def _secs(v):
    if v is None:
        return ""
    v = float(v)
    return "%.1fs" % v if v < 60 else "%dm %02ds" % (v // 60, v % 60)


def _when(dt):
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def create_app(home=None):
    """The app, reading the registry under ``home`` (default: ``WPK_HOME``)."""
    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))
    env.filters.update(money=_money, secs=_secs, when=_when)
    env.globals.update(version=__about__.__version__, refresh_s=REFRESH_S,
                       columns=data.COLUMNS)

    def render(name, status=200, **ctx):
        return HTMLResponse(env.get_template(name).render(**ctx), status_code=status)

    def not_found(what):
        return render("missing.html", status=404, what=what)

    def entry(request):
        try:
            return registry.get(request.path_params["project"], home)
        except (KeyError, OSError, ValueError, registry.ConfigError):
            return None

    async def board(request):
        cols, broken = data.board(home)
        return render("board.html", cols=cols, broken=broken, live=True,
                      home=home or registry.home())

    async def project(request):
        e = entry(request)
        if e is None:
            return not_found("project %s" % request.path_params["project"])
        now = clock.now()
        nodes = data.tree(e, now)
        recent = sorted(((n, s) for n in nodes for s in n["steps"] if s["start"]),
                        key=lambda ns: ns[1]["start"], reverse=True)[:50]
        return render("project.html", e=e, card=data.card(e, now), nodes=nodes,
                      recent=recent, tl=data.timeline(nodes, now), live=True)

    async def packet(request):
        e = entry(request)
        p = data.packet(e, request.path_params["wpid"]) if e else None
        if p is None:
            return not_found("packet %s" % request.path_params["wpid"])
        return render("packet.html", e=e, p=p, live=True)

    async def step(request):
        e = entry(request)
        s = data.step(e, request.path_params["wpid"], request.path_params["step"]) \
            if e else None
        if s is None:
            return not_found("step %s" % request.path_params["step"])
        # A committed or failed step never changes, so only a running one refreshes.
        return render("step.html", e=e, s=s, live=s["info"]["outcome"] == "running")

    async def health(request):
        return PlainTextResponse("ok\n")

    return Starlette(routes=[
        Route("/", board),
        Route("/healthz", health),
        Route("/p/{project}", project),
        Route("/p/{project}/{wpid}", packet),
        Route("/p/{project}/{wpid}/{step}", step),
    ])


def serve(host="127.0.0.1", port=7878, home=None):
    import uvicorn
    uvicorn.run(create_app(home), host=host, port=port, log_level="warning")
