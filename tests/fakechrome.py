#!/usr/bin/env python3
"""Stands in for headless Chrome in tests (docs/studio-plan.md P0.4).

Prints the "DevTools listening" line on stderr, as Chrome does, and answers
the CDP calls the render service makes with canned results: a 1x1 PNG, a
small PDF, a load event after ``Page.navigate`` and a console error.

``FAKECHROME_LOG``: a file each call's method (and URL, for navigations) is
appended to. ``FAKECHROME_NOT_READY=1``: ``window.__studioReady`` never
becomes true. ``FAKECHROME_SLOW``: seconds each screenshot takes.
``FAKECHROME_NO_START=1``: exit without listening. ``FAKECHROME_CHECKS``: the
JSON the page's checks (``__studioChecks``) return.
"""

import base64
import json
import os
import sys
import time

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")
PDF = b"%PDF-1.4\n% fake\n%%EOF\n"


def log(line):
    if os.environ.get("FAKECHROME_LOG"):
        with open(os.environ["FAKECHROME_LOG"], "a") as fp:
            fp.write(line + "\n")


def handler(ws):
    targets = 0
    for raw in ws:
        m = json.loads(raw)
        meth, p, sid = m["method"], m.get("params") or {}, m.get("sessionId")
        log(meth + (" " + p["url"] if meth == "Page.navigate" else "") +
            (" " + json.dumps(p["headers"], sort_keys=True)
             if meth == "Network.setExtraHTTPHeaders" else ""))
        res = {}
        events = []
        if meth == "Target.createTarget":
            targets += 1
            res = {"targetId": "T%d" % targets}
        elif meth == "Target.attachToTarget":
            res = {"sessionId": "S" + p["targetId"]}
        elif meth == "Page.navigate":
            res = {"frameId": "F"}
            if "missing" in p["url"]:
                res["errorText"] = "net::ERR_FILE_NOT_FOUND"
            else:
                events = [{"method": "Runtime.consoleAPICalled", "sessionId": sid,
                           "params": {"type": "error", "args": [{"value": "fake error"}]}},
                          {"method": "Page.loadEventFired", "sessionId": sid,
                           "params": {"timestamp": 1}}]
        elif meth == "Runtime.evaluate":
            expr = p["expression"]
            if "__studioChecks" in expr:
                val = json.loads(os.environ.get("FAKECHROME_CHECKS") or "[]")
            elif "__studioReady" in expr:
                val = os.environ.get("FAKECHROME_NOT_READY") != "1"
            elif "querySelector" in expr:
                val = None if "#none" in expr else [10, 20, 30, 40]
            elif "throw" in expr:
                res = {"result": {"type": "object"}, "exceptionDetails": {
                    "text": "Uncaught", "exception": {"description": "Error: thrown"}}}
                val = None
            else:
                val = "value of " + expr
            res = res or {"result": {"type": "string", "value": val}}
        elif meth == "Page.getLayoutMetrics":
            res = {"cssContentSize": {"x": 0, "y": 0, "width": 1200, "height": 1600}}
        elif meth == "Page.captureScreenshot":
            log("clip %s" % json.dumps(p.get("clip")))
            time.sleep(float(os.environ.get("FAKECHROME_SLOW") or 0))
            res = {"data": base64.b64encode(PNG).decode()}
        elif meth == "Page.printToPDF":
            res = {"data": base64.b64encode(PDF).decode()}
        for ev in events:
            ws.send(json.dumps(ev))
        ws.send(json.dumps({"id": m["id"], "result": res}))
        if meth == "Browser.close":
            os._exit(0)


def main():
    if os.environ.get("FAKECHROME_NO_START") == "1":
        sys.stderr.write("fakechrome: not starting\n")
        return 1
    from websockets.sync.server import serve
    with serve(handler, "127.0.0.1", 0, max_size=None) as server:
        port = server.socket.getsockname()[1]
        log("argv " + json.dumps(sys.argv[1:]))
        sys.stderr.write("\nDevTools listening on ws://127.0.0.1:%d/devtools/browser/fake\n" % port)
        sys.stderr.flush()
        server.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
