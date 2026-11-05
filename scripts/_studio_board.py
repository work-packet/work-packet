"""A board on a scratch home for the studio's exit checks (scripts/studio_s*_check.py).

``Board(dir, model)`` sets ``WPK_HOME`` under ``dir``, makes project
``name`` with ``prompt``, serves the board on loopback (uvicorn, the real
``claude`` for the studio's agent) and gives the calls the studio page makes:
``open()``, ``post()``, ``get()``, ``ask()`` (waits for the turn), ``shot()``,
``close()``. ``check(ok, what)`` prints a line and counts failures.
"""

import json
import os
import socket
import threading
import time


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Board:
    def __init__(self, d, model, name, prompt):
        d = os.path.abspath(d)
        os.makedirs(d, exist_ok=True)
        os.environ["WPK_HOME"] = os.path.join(d, "home")
        os.chdir(d)
        import httpx
        import uvicorn
        from work_packet import layout, project, registry
        from work_packet.dash.agent import Agents
        from work_packet.dash.app import create_app
        from work_packet.dash.guard import Guard, csrf_token
        from work_packet.packet import Packet
        self.dir, self.fails = d, []
        plan = project.new(name, prompt, model=model)
        self.e = registry.get(name)
        self.pkt = Packet(os.path.join(plan.path, "packets", plan.root))
        self.folder = layout.packet_folder(self.e["path"])
        secret = os.urandom(32)
        self.agents = Agents(os.environ["WPK_HOME"])
        app = Guard(create_app(agents=self.agents), "loopback", secret, local_user="me")
        self.port = _port()
        self.srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                                 log_level="warning", lifespan="off"))
        threading.Thread(target=self.srv.run, daemon=True).start()
        while not self.srv.started:
            time.sleep(0.05)
        # The studio's render listener, as wpk dash starts it (dash/render_gate.py).
        from work_packet.dash.render_gate import RenderGate
        from work_packet.studio import renders
        self.renders = renders.install(renders.Service(os.environ["WPK_HOME"]))
        rport = _port()
        self.rsrv = uvicorn.Server(uvicorn.Config(RenderGate(app.app, self.renders),
                                                  host="127.0.0.1", port=rport,
                                                  log_level="warning", lifespan="off"))
        threading.Thread(target=self.rsrv.run, daemon=True).start()
        while not self.rsrv.started:
            time.sleep(0.05)
        self.renders.base_url = "http://127.0.0.1:%d" % rport
        renders.write_listener(os.environ["WPK_HOME"], self.renders.base_url,
                               self.renders.secret)
        self.url = "http://127.0.0.1:%d" % self.port
        self.tok = csrf_token(secret)
        self.base = "/p/%s/%s/studio" % (name, self.pkt.wpid)
        self.c = httpx.Client(base_url=self.url, headers={"origin": self.url}, timeout=120)
        self.events = []
        self.stop = threading.Event()
        print("scratch:", d, "\nfolder:", self.folder, flush=True)

    def check(self, ok, what):
        print(("  ok   " if ok else "  FAIL ") + what, flush=True)
        if not ok:
            self.fails.append(what)
        return ok

    def write(self, rel, text):
        p = os.path.join(self.folder, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fp:
            fp.write(text)

    def post(self, path, body):
        r = self.c.post(self.base + path, json=body, headers={"x-csrf-token": self.tok})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"text": r.text}

    def get(self, route, **params):
        return self.c.get(self.base + route, params=params)

    def _listen(self):
        from websockets.sync.client import connect
        with connect("ws://127.0.0.1:%d%s/ws" % (self.port, self.base),
                     additional_headers={"origin": self.url}) as ws:
            ws.send(json.dumps({"token": self.tok}))
            while not self.stop.is_set():
                try:
                    self.events.append(json.loads(ws.recv(timeout=0.5)))
                except TimeoutError:
                    pass

    def open(self):
        r = self.c.post(self.base + "/open", data={"csrf": self.tok}, follow_redirects=False)
        self.check(r.status_code == 303, "open the studio")
        threading.Thread(target=self._listen, daemon=True).start()
        time.sleep(1)

    def ask(self, text, timeout=600, path="/ask", body=None):
        """Ask (or post ``body`` to ``path``), then wait for the turn to end;
        the events of the turn (tool lines printed)."""
        n = len(self.events)
        st, j = self.post(path, body if body is not None else {"text": text})
        if not self.check(st == 200, "asked: %r" % (text or path)[:60]):
            print("   ", j)
            return []
        end = time.time() + timeout
        got = []
        while time.time() < end:
            got = self.events[n:]
            if any(x.get("k") == "end" for x in got) and any(
                    x.get("k") == "busy" and not x.get("on") for x in got):
                time.sleep(1.0)              # the output card follows the end
                got = self.events[n:]
                break
            time.sleep(0.5)
        else:
            self.check(False, "the turn ended within %ds" % timeout)
        for x in got:
            if x.get("k") == "tool":
                print("    · %s %s" % (x.get("name", ""), (x.get("what") or "")[:110]))
            elif x.get("k") == "end":
                print("    end ok=%s cost=%s %s" % (x.get("ok"), x.get("cost"),
                                                   x.get("error") or ""))
        return got

    def shot(self, png, wait_ms=3000):
        from work_packet.studio import render
        b = render.Browser(home=os.path.join(self.dir, "chrome"))
        try:
            r = b.render(self.url + self.base, png=png, width=1400, height=900,
                         ready_timeout_s=10,
                         script="new Promise(r => setTimeout(() => r(1), %d))" % wait_ms)
            self.check(not r["errors"], "the studio page loads with no console errors %s"
                       % (r["errors"] or ""))
        finally:
            b.stop()

    def close(self):
        """Close with the drafted summary; check the recorded step."""
        from work_packet import check as wcheck
        dr = self.get("/draft").json()
        print("    draft (%s): %s" % (dr.get("how"), (dr.get("text") or "")[:300].replace("\n", " ")))
        self.check(bool(dr.get("text")), "a summary is drafted")
        r = self.c.post(self.base + "/close", data={"csrf": self.tok, "summary": dr["text"],
                                                    "how": "hold"}, follow_redirects=False)
        self.check(r.status_code == 303, "close")
        meta, body = self.pkt.load_status()
        self.check("taken_by" not in meta and meta.get("reason") == "held", "released, held")
        steps = sorted(os.listdir(os.path.join(self.pkt.path, "steps")))
        sm = json.load(open(os.path.join(self.pkt.path, "steps", steps[-1], "meta.json")))
        print("    step %s: worker=%s cost=$%.4f duration=%ss" % (
            steps[-1], sm.get("worker"), sm.get("cost_usd") or 0, sm.get("duration_s")))
        self.check(sm.get("worker") == "studio", "a studio step is recorded")
        html = self.c.get("/p/%s/%s" % (self.e["name"], self.pkt.wpid)).text
        self.check("studio</span>" in html, "the Steps tab shows it")
        res = wcheck.check_project(self.e["path"])
        self.check(not res.errors, "wpk check is clean %s" % (res.errors or ""))

    def versions(self):
        return self.get("/versions").json()["versions"]

    def tools(self, got):
        """The tool lines of a turn's events, as one string."""
        return " ".join((x.get("what") or "") for x in got if x.get("k") == "tool")

    def says(self, got):
        return " ".join(x.get("text") or "" for x in got if x.get("k") == "say")

    def finish(self):
        self.stop.set()
        self.srv.should_exit = True
        self.rsrv.should_exit = True
        self.renders.stop()
        print("\n%s" % ("all checks passed" if not self.fails else "%d failed: %s" % (
            len(self.fails), "; ".join(self.fails))))
        return 1 if self.fails else 0
