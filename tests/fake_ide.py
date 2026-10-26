"""A stand-in for ``code serve-web`` (docs/vscode-plan.md V3 tests).

Usage: fake_ide.py <pids file> <socket path> <base path>. Appends its pid and a
child's pid to the pids file, then serves on the socket: ``<base>/`` answers
HTML that echoes the request headers; ``<base>/echo`` echoes a body; a
WebSocket on any ``<base>/`` path echoes messages.

With ``-`` for the socket and ``--host H --port P --connection-token-file F``
it serves over TCP, as a server in a job does (docs/scheduler-plan.md T-e),
and refuses (403) any request without the token in the ``vscode-tkn`` cookie
or a ``tkn`` query parameter.
"""

import json
import os
import subprocess
import sys

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


async def page(request):
    if not has_token(request):
        return Response("forbidden: no connection token", status_code=403)
    seen = json.dumps(dict(request.headers))
    return HTMLResponse('<meta data-settings="{&quot;enableWorkspaceTrust&quot;:true}">'
                        '<pre id="seen">%s</pre>' % seen.replace("<", "&lt;"),
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
