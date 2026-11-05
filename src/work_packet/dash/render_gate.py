"""The render listener's gate (docs/studio-plan.md S3.1, S3.4).

The headless browser cannot sign in to the board, and the board's own
listeners differ (loopback, tailnet, a network sign-in). So the dash also
listens on a loopback port of its own for the renderer, and wraps the app in
this gate instead of ``Guard``:

- every request carries ``x-wpk-render: <secret>`` (the browser sends it
  with each request of the page; ``wpk studio look`` reads it from
  ``$WPK_HOME/run/render.json``, mode 0600);
- only GET/HEAD of the studio's frame, data and file routes and the static
  files, as the user ``x-wpk-render-user`` names (the studio's routes still
  check that user has the studio open);
- ``POST /_render/look``: ``wpk studio look``, answered here.

Responses get the studio frames' CSP.
"""

import hmac
import json
import re

import anyio

from . import guard

ALLOWED = re.compile(r"^/p/[^/]+/[^/]+/studio/(frame/(doc|chart|table)|data|table|file)$"
                     r"|^/static/")
LOOK = "/_render/look"


async def _reply(send, status, body, ctype=b"application/json"):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", ctype),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class RenderGate:
    def __init__(self, app, service):
        self.app = app
        self.service = service

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        hdr = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        got = hdr.get("x-wpk-render", "")
        if not (got and hmac.compare_digest(got, self.service.secret)):
            return await _reply(send, 403, {"error": "not for this listener"})
        path, method = scope.get("path", ""), scope.get("method", "GET")
        if path == LOOK and method == "POST":
            return await self._look(receive, send)
        if method not in ("GET", "HEAD") or not ALLOWED.match(path):
            return await _reply(send, 403, {"error": "not served to the renderer"})
        st = scope.setdefault("state", {})
        st["user"] = hdr.get("x-wpk-render-user") or None
        st["csrf"] = ""
        st["listener"] = "render"

        async def send_with_headers(msg):
            if msg["type"] == "http.response.start":
                have = {k.lower() for k, _ in msg.get("headers", [])}
                msg = dict(msg, headers=list(msg.get("headers", [])) +
                           [(k, v) for k, v in guard.FRAME_HEADERS if k not in have])
            await send(msg)
        await self.app(scope, receive, send_with_headers)

    async def _look(self, receive, send):
        body = b""
        while True:
            m = await receive()
            body += m.get("body", b"")
            if not m.get("more_body"):
                break
        try:
            req = json.loads(body or b"{}")
            project, wpid, rel = str(req["project"]), str(req["wpid"]), str(req["path"])
            part = int(req["part"]) if req.get("part") is not None else None
        except (ValueError, KeyError, TypeError):
            return await _reply(send, 400, {"error": "project, wpid and path, please"})
        from ..studio import model, renders
        try:
            out = await anyio.to_thread.run_sync(
                lambda: self.service.look(project, wpid, rel, part))
        except (renders.RenderUnavailable, model.StudioError, KeyError, OSError) as ex:
            return await _reply(send, 400, {"error": str(ex)})
        return await _reply(send, 200, out)
