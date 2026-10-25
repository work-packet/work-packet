"""A stand-in for ``code serve-web`` (docs/vscode-plan.md V3 tests).

Usage: fake_ide.py <pids file> <socket path>. Appends its pid and a child's
pid to the pids file, then serves on the socket: ``/ide/`` answers HTML that
echoes the request headers; ``/ide/echo`` echoes a body; a WebSocket on any
``/ide/`` path echoes messages.
"""

import json
import os
import subprocess
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route, WebSocketRoute

pids, sock = sys.argv[1], sys.argv[2]
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
with open(pids, "a") as fp:
    fp.write("%d %d\n" % (os.getpid(), child.pid))


async def page(request):
    seen = json.dumps(dict(request.headers))
    return HTMLResponse('<meta data-settings="{&quot;enableWorkspaceTrust&quot;:true}">'
                        '<pre id="seen">%s</pre>' % seen.replace("<", "&lt;"),
                        headers={"content-security-policy": "default-src 'self' fake",
                                 "set-cookie": "vscode-cli-secret-half=abc; Path=/"})


async def echo(request):
    return Response(await request.body(), media_type="application/octet-stream")


async def ws(websocket):
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


app = Starlette(routes=[Route("/ide/echo", echo, methods=["POST"]),
                        Route("/ide/{rest:path}", page),
                        WebSocketRoute("/ide/{rest:path}", ws)])
uvicorn.run(app, uds=sock, log_level="warning")
