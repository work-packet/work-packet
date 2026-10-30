"""The studio's kernel process (docs/studio-plan.md S2.1).

One per open studio, started by ``kernel.py`` in the studio's folder (its
cwd), in the packet's Python when that has DuckDB, else wpk's. It listens on
a unix socket: one JSON request per connection, one JSON reply.

Requests (``op``):

- ``ping``
- ``exec {code}``: Python in a namespace that lasts between calls, with
  ``con`` (the agent's DuckDB connection) and ``sql(q)``; stdout, stderr
  and the value of a last expression come back as text.
- ``query {sql, limit}``: SQL on the agent's connection (so tables made by
  ``exec`` are there), as columns and rows.
- ``page``, ``stats``, ``records``, ``selected``, ``tables``, ``datasets``:
  for the viewers, on the sandboxed connection (``data.py``).
- ``reset``: a new namespace and connections. ``shutdown``.

It exits by itself after ``--idle`` seconds with no request.
"""

import argparse
import ast
import contextlib
import io
import json
import os
import socketserver
import sys
import threading
import time
import traceback

OUT_MAX = 20000


class Kernel:
    def __init__(self, folder):
        from work_packet.studio import data
        self.data = data
        self.folder = folder
        self.lock = threading.Lock()          # exec and query: the agent's connection
        self.vlock = threading.Lock()         # the viewers' connection
        self.last = time.time()
        self.reset()

    def reset(self):
        with self.lock, self.vlock:
            self.con = None
            self.view = None
            self.ns = {"__name__": "__studio__"}
        return {"ok": True}

    def agent_con(self):
        if self.con is None:
            self.con = self.data.connect(sandbox=False)
            self.ns.update(con=self.con, sql=lambda q, *a: self.con.sql(q, *a))
        return self.con

    def view_con(self):
        if self.view is None:
            self.view = self.data.connect(sandbox=True)
        return self.view

    # -- requests --------------------------------------------------------------------

    def handle(self, req):
        op = req.get("op")
        if op != "ping":                    # "is it up?" is not use: it does not keep it up
            self.last = time.time()
        fn = getattr(self, "op_" + str(op), None)
        if fn is None:
            return {"ok": False, "error": "no op %s" % op}
        try:
            return fn(req)
        except self.data.DataError as ex:
            return {"ok": False, "error": str(ex)}
        except Exception as ex:  # noqa: BLE001  (a bad request: say so, keep serving)
            return {"ok": False, "error": "%s: %s" % (type(ex).__name__, self.data._short(ex))}

    def op_ping(self, req):
        """Up, and in which folder: ``here`` is the cwd's (device, inode), or
        None when it was removed (a stale kernel: wpk replaces it)."""
        try:
            st = os.stat(".")
            here = [st.st_dev, st.st_ino]
        except OSError:
            here = None
        return {"ok": True, "pid": os.getpid(), "python": sys.executable, "folder": self.folder,
                "here": here}

    def op_reset(self, req):
        return self.reset()

    def op_exec(self, req):
        code = str(req.get("code") or "")
        out, err = io.StringIO(), io.StringIO()
        value, ok = None, True
        with self.lock:
            try:
                self.agent_con()
            except self.data.DataError as ex:
                err.write(str(ex) + "\n")       # Python still works without DuckDB
            try:
                tree = ast.parse(code, "<studio>", "exec")
                last = None
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    last = ast.Expression(tree.body.pop().value)
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    exec(compile(tree, "<studio>", "exec"), self.ns)
                    if last is not None:
                        v = eval(compile(last, "<studio>", "eval"), self.ns)
                        if v is not None:
                            value = str(v) if type(v).__name__ == "DuckDBPyRelation" else repr(v)
            except BaseException as ex:  # noqa: BLE001  (SystemExit too: the kernel stays up)
                ok = False
                err.write(_trace(ex))
            finally:
                try:
                    os.chdir(self.folder)       # the viewers' paths are the folder's
                except OSError:
                    pass
        return {"ok": ok, "stdout": _cap(out.getvalue()), "stderr": _cap(err.getvalue()),
                "value": _cap(value) if value is not None else None}

    def op_query(self, req):
        limit = max(1, min(int(req.get("limit") or 100), 10000))
        with self.lock:
            con = self.agent_con()
            try:
                cur = con.execute(str(req.get("sql") or ""))
            except Exception as ex:  # noqa: BLE001
                return {"ok": False, "error": self.data._short(ex)}
            if cur.description is None:
                return {"ok": True, "columns": [], "rows": [], "total": 0}
            names = [d[0] for d in cur.description]
            rows = cur.fetchmany(limit + 1)
        more = len(rows) > limit
        return {"ok": True, "columns": names,
                "rows": [[self.data.jsonable(v) for v in r] for r in rows[:limit]],
                "more": more}

    def _view(self, fn, *a, **kw):
        with self.vlock:
            return fn(self.view_con(), *a, **kw)

    def op_page(self, req):
        return dict(ok=True, **self._view(self.data.page, req["src"], req.get("offset", 0),
                                          req.get("limit", 100), req.get("sort"),
                                          bool(req.get("desc")), req.get("filters")))

    def op_stats(self, req):
        return {"ok": True, "columns": self._view(self.data.stats, req["src"])}

    def op_records(self, req):
        rows, cut = self._view(self.data.records, req["src"],
                               int(req.get("cap") or self.data.CHART_ROWS))
        return {"ok": True, "rows": rows, "truncated": cut}

    def op_selected(self, req):
        return dict(ok=True, **self._view(self.data.selected, req["src"], req["selection"],
                                          int(req.get("cap") or 50)))

    def op_tables(self, req):
        return {"ok": True, "tables": self._view(self.data.tables, req["src"])}

    def op_datasets(self, req):
        return {"ok": True, "datasets": self._view(self.data.datasets, req.get("files") or [])}


def _trace(ex):
    """The traceback of the agent's code only (not the kernel's frames)."""
    te = traceback.TracebackException.from_exception(ex)
    te.stack = traceback.StackSummary.from_list(
        [f for f in te.stack if f.filename == "<studio>" or "work_packet" not in f.filename])
    return "".join(te.format())


def _cap(s):
    if s is None or len(s) <= OUT_MAX:
        return s
    return s[:OUT_MAX] + "\n… (%d more characters)" % (len(s) - OUT_MAX)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        try:
            req = json.loads(line)
        except ValueError:
            rep = {"ok": False, "error": "not JSON"}
        else:
            if req.get("op") == "shutdown":
                self.wfile.write(b'{"ok": true}\n')
                self.wfile.flush()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            rep = self.server.kernel.handle(req)
        self.wfile.write((json.dumps(rep) + "\n").encode())


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", required=True)
    ap.add_argument("--idle", type=float, default=1800.0)
    a = ap.parse_args(argv)
    folder = os.getcwd()
    k = Kernel(folder)
    if os.path.exists(a.sock):
        os.unlink(a.sock)
    old = os.umask(0o077)
    try:
        srv = _Server(a.sock, _Handler)
    finally:
        os.umask(old)
    srv.kernel = k

    def reaper():
        while True:
            time.sleep(min(5.0, a.idle / 4))
            if time.time() - k.last > a.idle:
                srv.shutdown()
                return
    threading.Thread(target=reaper, daemon=True).start()
    print("kernel %d up in %s (%s)" % (os.getpid(), folder, sys.executable), flush=True)
    try:
        srv.serve_forever(poll_interval=0.2)
    finally:
        try:
            os.unlink(a.sock)
        except OSError:
            pass
    sys.stdout.flush()
    os._exit(0)             # skip DuckDB's teardown: it prints leak warnings at exit


if __name__ == "__main__":
    sys.exit(main())
