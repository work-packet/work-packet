"""A stand-in for ``code serve-web`` (docs/vscode-plan.md V3 tests).

Usage: fake_ide.py <pids file> <socket path> <base path>. Appends its pid and a
child's pid to the pids file, then serves on the socket: ``<base>/`` answers
HTML that echoes the request headers; ``<base>/echo`` echoes a body; a
WebSocket on any ``<base>/`` path echoes messages.

With ``-`` for the socket and ``--host H --port P --connection-token-file F``
it serves over TCP, as a server in a job does (docs/scheduler-plan.md T-e),
and refuses (403) any request without the token in the ``vscode-tkn`` cookie
or a ``tkn`` query parameter.

Each start also appends its ``WPK_IDE_*`` environment, as JSON, to ``<pids file>.env``.

It also serves an extension's page on ``127.0.0.1:<random>`` (port-forward
plan), and writes the port to ``<pids file>.port``: ``/`` is HTML with a
relative stylesheet that echoes the Host, ``/redir`` redirects to ``/x`` and
``/abs`` to ``http://localhost:<port>/y``.
"""

import http.server
import json
import os
import subprocess
import sys
import threading

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route, WebSocketRoute

pids, sock, base = sys.argv[1], sys.argv[2], sys.argv[3]
opts = dict(zip(sys.argv[4::2], sys.argv[5::2]))
TOKEN = None
if opts.get("--connection-token-file"):
    with open(opts["--connection-token-file"]) as fp:
        TOKEN = fp.read().strip()


def has_token(conn):
    if TOKEN is None:
        return True
    return conn.cookies.get("vscode-tkn") == TOKEN or conn.query_params.get("tkn") == TOKEN
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
with open(pids, "a") as fp:
    fp.write("%d %d\n" % (os.getpid(), child.pid))
with open(pids + ".env", "a") as fp:           # what an extension or terminal would inherit
    fp.write(json.dumps({k: v for k, v in os.environ.items() if k.startswith("WPK_IDE_")}) + "\n")


class ExtensionPage(http.server.BaseHTTPRequestHandler):
    """What an extension serves on loopback, as vscode-print does."""

    def log_message(self, *a):
        pass

    def answer(self, status, body=b"", ctype="text/plain", **headers):
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        for k, v in headers.items():
            self.send_header(k.replace("_", "-"), v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/s/"):
            body = ('<link rel="stylesheet" href="style.css"><pre id="host">%s</pre>'
                    '<pre id="path">%s</pre><pre id="cookie">%s</pre>'
                    % (self.headers.get("host"), self.path, self.headers.get("cookie")))
            return self.answer(200, body.encode(), "text/html", set_cookie="app=1; Path=/",
                               content_security_policy="img-src 'self'",
                               access_control_allow_credentials="true")
        if path == "/b/":           # vscode-print's page: a <base> on its own origin
            body = ('<base href="http://localhost:%d/b/"><link rel="stylesheet" href="style.css">'
                    '<a href="http://127.0.0.1:%d/x">self</a><a href="http://localhost:%d1/">other</a>'
                    % (EXT_PORT, EXT_PORT, EXT_PORT))
            return self.answer(200, body.encode(), "text/html")
        if path in ("/s/style.css", "/b/style.css"):
            return self.answer(200, b"pre { color: red }", "text/css")
        if path == "/redir":
            return self.answer(302, location="/x")
        if path == "/abs":
            return self.answer(302, location="http://localhost:%d/y#top" % EXT_PORT)
        return self.answer(404, b"no such page")

    do_HEAD = do_GET


ext = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ExtensionPage)
EXT_PORT = ext.server_address[1]
threading.Thread(target=ext.serve_forever, daemon=True).start()
with open(pids + ".port", "w") as fp:
    fp.write("%d\n" % EXT_PORT)


async def page(request):
    if not has_token(request):
        return Response("forbidden: no connection token", status_code=403)
    seen = json.dumps(dict(request.headers))
    return HTMLResponse('<meta data-settings="{&quot;enableWorkspaceTrust&quot;:true}">'
                        '<pre id="seen">%s</pre><script>/* workbench */</script>'
                        % seen.replace("<", "&lt;"),
                        headers={"content-security-policy": "default-src 'self' fake",
                                 "set-cookie": "vscode-cli-secret-half=abc; Path=/"})


async def echo(request):
    return Response(await request.body(), media_type="application/octet-stream")


async def ws(websocket):
    if not has_token(websocket):
        return await websocket.close(1008)
    await websocket.accept()
    await websocket.send_text(json.dumps({"host": websocket.headers.get("host"),
                                          "cookie": websocket.headers.get("cookie")}))
    while True:
        m = await websocket.receive()
        if m["type"] == "websocket.disconnect":
            return
        if m.get("bytes") is not None:
            await websocket.send_bytes(m["bytes"])
        else:
            await websocket.send_text(m["text"])


app = Starlette(routes=[Route(base + "/echo", echo, methods=["POST"]),
                        Route(base + "/{rest:path}", page),
                        WebSocketRoute(base + "/{rest:path}", ws)])
if sock == "-":
    uvicorn.run(app, host=opts.get("--host", "127.0.0.1"), port=int(opts["--port"]),
                log_level="warning")
else:
    uvicorn.run(app, uds=sock, log_level="warning")
