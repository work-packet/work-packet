"""Plugin panels and routes on the board (design E7).

A ``work_packet.dash`` plugin is an object (a class is made once) with any of:

- ``panels(slot, ctx)``: for a slot (``SLOTS``) a ``(title, template, data)``,
  a list of them, or None. ``ctx`` has ``home``, ``request``, ``principal`` and,
  on ``settings``, ``project`` (the registry entry).
- ``routes()``: Starlette routes, served under ``/x/<name>/``.
- ``templates``: a Jinja loader or a directory; default: the ``templates``
  folder of the plugin's package. The board's own templates come after it, so a
  panel can ``{% extends "base.html" %}`` or import a board macro.
- ``public = True``: show the panels and serve the routes to anyone the board
  lets in; by default only the home's owner sees them (budget data is often
  personal).

All of it sits behind the board's ``Guard`` (Host check, CSRF on POST); the
CSP is unchanged, so a panel has no scripts of its own. A panel that fails is
shown as its error; it never breaks the page.
"""
import logging
import os

from jinja2 import BaseLoader, ChoiceLoader, FileSystemLoader, PackageLoader
from markupsafe import Markup
from starlette.requests import HTTPConnection
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Router

from .. import plugins

log = logging.getLogger("wpk.dash")

GROUP = "work_packet.dash"
SLOTS = ("overview", "sched", "settings")

_made = {}          # plugin name -> (obj, the object made from it)


def _obj(p):
    got = _made.get(p.name)
    if got is None or got[0] is not p.obj:
        try:
            o = p.obj() if isinstance(p.obj, type) else p.obj
        except Exception as e:            # noqa: BLE001  a plugin's failure stays its own
            log.warning("dash plugin %s: %s", p.name, e)
            o = None
        got = _made[p.name] = (p.obj, o)
    return got[1]


def active():
    """[(name, object)] of the dash plugins that loaded."""
    out = []
    for p in plugins.load(GROUP):
        o = _obj(p) if p.ok else None
        if o is not None:
            out.append((p, o))
    return out


def is_owner(request, home=None):
    from ..sched import authz
    return authz.principal_of(request) == "unix:%s" % authz.home_owner(home)


def loader(p, o):
    """The plugin's own template loader, or None."""
    t = getattr(o, "templates", None)
    if isinstance(t, BaseLoader):
        return t
    if isinstance(t, (str, os.PathLike)):
        return FileSystemLoader(os.fspath(t))
    try:
        return PackageLoader(p.module.split(":")[0].split(".")[0], "templates")
    except (ValueError, ImportError, ModuleNotFoundError):
        return None


def _items(got):
    if not got:
        return []
    if isinstance(got, tuple):
        return [got]
    return list(got)


def render(env, slot, request, home=None, **ctx):
    """[{plugin, title, html, error}] for ``slot``, rendered with an overlay of
    the board's ``env`` (its filters and globals) on the plugin's loader."""
    from ..sched import authz
    out = []
    owner = None
    for p, o in active():
        fn = getattr(o, "panels", None)
        if not callable(fn):
            continue
        if not getattr(o, "public", False):
            if owner is None:
                owner = is_owner(request, home)
            if not owner:
                continue
        c = dict(ctx, home=home, request=request, principal=authz.principal_of(request))
        try:
            items = _items(fn(slot, c))
        except Exception as e:            # noqa: BLE001
            out.append({"plugin": p.name, "title": p.name, "html": "", "error": str(e) or type(e).__name__})
            continue
        own = loader(p, o)
        penv = env.overlay(loader=ChoiceLoader([own, env.loader]) if own else env.loader)
        for it in items:
            title, name, data = (tuple(it) + (None, None, None))[:3]
            d = {"plugin": p.name, "title": title or p.name, "html": "", "error": None}
            try:
                d["html"] = Markup(penv.get_template(name).render(
                    data=data, slot=slot, plugin=p.name, csrf=request.scope.get("state", {}).get("csrf"),
                    **{k: v for k, v in ctx.items() if k != "request"}))
            except Exception as e:        # noqa: BLE001
                d["error"] = "%s: %s" % (type(e).__name__, e)
            out.append(d)
    return out


class OwnerOnly:
    """Serve ``app`` to the home's owner only (unless ``public``)."""

    def __init__(self, app, name, home=None, public=False):
        self.app, self.name, self.home, self.public = app, name, home, public

    async def __call__(self, scope, receive, send):
        if not self.public and scope["type"] in ("http", "websocket") and \
                not is_owner(HTTPConnection(scope), self.home):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            resp = PlainTextResponse("/x/%s is the home owner's only\n" % self.name, status_code=403)
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


def mounts(home=None):
    """A ``Mount("/x/<name>")`` for each dash plugin with routes."""
    out = []
    for p, o in active():
        fn = getattr(o, "routes", None)
        if not callable(fn):
            continue
        try:
            routes = list(fn() or [])
        except Exception as e:            # noqa: BLE001
            log.warning("dash plugin %s: routes: %s", p.name, e)
            continue
        if routes:
            app = OwnerOnly(Router(routes=routes), p.name, home, bool(getattr(o, "public", False)))
            out.append(Mount("/x/%s" % p.name, app=app))
    return out
