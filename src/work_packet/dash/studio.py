"""The studio on the board (docs/studio-plan.md S1.4-S1.6): its page, routes and socket.

The logic is in ``studio/``; this is the web side. Every route is under
``/p/<project>/<wpid>/studio``. Opening takes the packet and starts a
``studio``-mode conversation (``dash/agent.py``); everything else, but the
page itself, is only for whoever has the packet taken (403 for anyone else).

While a studio socket is open, the folder is polled (``studio/watch.py``)
and changes go out as ``{"k": "changed", ...}`` events; at the end of a turn
the files the agent made or changed of a known kind become an ``output``
event in the conversation (a card with Pin and Open). Comments and "Ask" on
a document go into the studio conversation instead of a note.
"""

import asyncio
import hmac
import json
import os
import threading
import time
import urllib.parse

from starlette.concurrency import run_in_threadpool
from starlette.responses import (FileResponse, JSONResponse, PlainTextResponse,
                                 RedirectResponse)
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect, WebSocketState

from .. import fsutil, schema
from ..studio import chart, kernel, kinds, model, primer, record, watch
from ..studio import data as sdata
from ..studio import render as studio_render
from . import data, markup

FILE_MAX = 16 << 20
# Raw files for the viewers are served on the board's origin: never as a page
# that could run (an SVG's scripts, an HTML file).
RAW_CSP = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def selection_ask(rel, src, sel, got, question):
    """The question for the agent about a chart selection: the chart, the
    selection, and the rows it picks (a few, as a table)."""
    def one(k, v):
        if sel.get("kind") == "point":
            return "%s in %s" % (k, v)
        if isinstance(v, list) and len(v) == 2:
            return "%s from %s to %s" % (k, v[0], v[1])
        return "%s = %s" % (k, v)
    where = ", ".join(one(k, v) for k, v in sel.items() if k != "kind")
    rows = got.get("rows") or []
    out = ["About a selection on the chart %s (data: %s; %s): %d row%s." % (
        rel, src, where, got.get("total", len(rows)), "" if got.get("total") == 1 else "s"),
        "", "SQL filter: %s, with %s" % (got.get("where") or "(none)", got.get("params")), ""]
    if rows:
        out.append(sdata.text_table(got["columns"], rows, got.get("total")))
        out.append("")
    out.append(question)
    return "\n".join(out)


class Live:
    """What the server keeps in memory for one open studio: the watcher, the
    changes the person made since the agent's last turn, the agent's changes
    in this turn, and when the last output card was made."""

    def __init__(self, root):
        self.watcher = watch.Watcher(root)
        self.yours = []
        self.turn = []
        self.carded = 0.0
        self.lock = threading.Lock()

    def poll(self):
        with self.lock:
            got = self.watcher.poll()
            for c in got:
                if c["by"] == "agent":
                    self.turn.append(c)
                else:
                    self.yours.append(c)
            return got


def routes(home, agents, render, entry, who, not_found):
    lives = {}
    lives_lock = threading.Lock()

    def base(e, wpid):
        return "/p/%s/%s/studio" % (urllib.parse.quote(e["name"]), wpid)

    def live(e, wpid):
        key = (e["name"], wpid)
        with lives_lock:
            if key not in lives:
                lives[key] = Live(model.folder(e, wpid))
            return lives[key]

    def drop(e, wpid):
        with lives_lock:
            lives.pop((e["name"], wpid), None)

    def lookup(request):
        """(entry, wpid, state) or a response to return."""
        e = entry(request)
        wpid = request.path_params["wpid"]
        if e is None or not schema.is_wpid(wpid):
            return None, None, not_found(request, "packet %s" % wpid)
        try:
            st = model.state(e, wpid)
        except model.StudioError as ex:
            return None, None, not_found(request, str(ex))
        return e, wpid, st

    def mine(request, st):
        """None if the caller has the packet taken, else the 403 to return."""
        if st.get("taken_by") and st["taken_by"] == who(request) and st["open"]:
            return None
        return JSONResponse({"error": "the studio is open only for whoever has taken the "
                             "packet (%s)" % (st.get("taken_by") or "nobody")},
                            status_code=403)

    async def body_json(request):
        try:
            b = await request.json()
            return b if isinstance(b, dict) else {}
        except ValueError:
            return {}

    def flash(to, msg, ok=True):
        sep = "&" if "?" in to else "?"
        return RedirectResponse("%s%smsg=%s&ok=%s" % (to, sep, urllib.parse.quote(msg),
                                                      "1" if ok else "0"), status_code=303)

    # -- the page ---------------------------------------------------------------

    async def page(request):
        e, wpid, st = lookup(request)
        if e is None:
            return st
        me = who(request)
        conv = None
        s = st["session"]
        if s and s.get("conv") and agents is not None:
            conv = agents.get(s["conv"])
        return render(request, "studio.html", e=e, wpid=wpid, short=wpid[:8], st=st,
                      mine=bool(s and s["by"] == me and st.get("taken_by") == me),
                      conv=conv, base=base(e, wpid), agent_on=agents is not None,
                      kinds=[k.name for k in kinds.REGISTRY])

    async def open_(request):
        e, wpid, st = lookup(request)
        if e is None:
            return st
        me = who(request)
        try:
            st = await run_in_threadpool(model.open_studio, e, wpid, me)
            s = st["session"]
            if agents is not None and not (s.get("conv") and agents.get(s["conv"])):
                pkt = model.packet(e, wpid)
                scope = {"kind": "packet", "project": e["name"], "wpid": wpid}
                conv = agents.new(scope, st["folder"], me,
                                  model=pkt.load_status()[0].get("model"),
                                  project_dir=e["path"], mode="studio")
                model.set_conv(e, wpid, conv["id"])
        except model.StudioError as ex:
            return flash("/p/%s/%s" % (urllib.parse.quote(e["name"]), wpid), str(ex), False)
        live(e, wpid)
        return RedirectResponse(base(e, wpid), status_code=303)

    async def close(request):
        e, wpid, st = lookup(request)
        if e is None:
            return st
        form = await request.form()
        how = "hold" if form.get("how") == "hold" else "resume"
        try:
            out = await run_in_threadpool(model.close_studio, e, wpid, who(request), how,
                                          form.get("summary") or None, False, home)
        except model.StudioError as ex:
            return flash(base(e, wpid), str(ex), False)
        drop(e, wpid)
        return flash("/p/%s/%s" % (urllib.parse.quote(e["name"]), wpid), out["msg"])

    async def draft(request):
        e, wpid, st = lookup(request)
        if e is None:
            return st
        bad = mine(request, st)
        if bad:
            return bad
        text, how = await run_in_threadpool(record.draft_summary, e, wpid, st["session"], home)
        return JSONResponse({"text": text, "how": how})

    # -- the canvas ---------------------------------------------------------------

    def canvas_json(e, wpid, st):
        out = []
        for a in st["canvas"]:
            p = os.path.join(st["folder"], a["path"])
            try:
                m = os.stat(p).st_mtime
            except OSError:
                m = None
            out.append(dict(a, missing=m is None, mtime=m))
        return {"canvas": out, "layout": st["layout"], "open": st["open"],
                "taken_by": st["taken_by"], "session": st["session"]}

    async def canvas(request):
        e, wpid, st = lookup(request)
        if e is None:
            return st
        bad = mine(request, st)
        if bad:
            return bad
        return JSONResponse(canvas_json(e, wpid, st))

    def changer(fn):
        async def handler(request):
            e, wpid, st = lookup(request)
            if e is None:
                return st
            bad = mine(request, st)
            if bad:
                return bad
            b = await body_json(request)
            try:
                await run_in_threadpool(fn, e, wpid, b, who(request))
            except model.StudioError as ex:
                return JSONResponse({"error": str(ex)}, status_code=400)
            return JSONResponse(canvas_json(e, wpid, model.state(e, wpid)))
        return handler

    pin = changer(lambda e, w, b, me: model.pin(e, w, str(b.get("path") or ""), me))
    unpin = changer(lambda e, w, b, me: model.unpin(e, w, str(b.get("path") or "")))
    lay = changer(lambda e, w, b, me: model.set_layout(
        e, w, b.get("mode"), b.get("open") if isinstance(b.get("open"), list) else None))

    def artifact_path(st, rel):
        """The file ``rel`` names in the folder, or None."""
        try:
            rel = model._artifact(st["folder"], rel)
        except model.StudioError:
            return None, None
        p = os.path.join(st["folder"], rel)
        return (p, rel) if os.path.isfile(p) else (None, None)

    async def raw(request):
        e, wpid, st = lookup(request)
        if e is None:
            return st
        bad = mine(request, st)
        if bad:
            return bad
        p, rel = artifact_path(st, request.query_params.get("path") or "")
        if p is None:
            return PlainTextResponse("not found\n", status_code=404)
        if os.path.getsize(p) > FILE_MAX:
            return PlainTextResponse("too large to show\n", status_code=413)
        from ..studio import content
        mt = content.media_type(p)
        if mt.startswith("text/html") or mt.startswith("application/xhtml"):
            mt = "text/plain; charset=utf-8"
        return FileResponse(p, media_type=mt, headers={
            "content-security-policy": RAW_CSP, "cache-control": "no-store",
            "content-disposition": "inline"})

    async def frame_doc(request):
        """A document for the canvas, in a frame: the doc-markup page's article,
        whose comments and Ask go to the studio."""
        e, wpid, st = lookup(request)
        if e is None:
            return st
        bad = mine(request, st)
        if bad:
            return bad
        p, rel = artifact_path(st, request.query_params.get("path") or "")
        if p is None or not p.lower().endswith((".md", ".markdown")):
            return PlainTextResponse("not a document of this studio\n", status_code=404)
        if os.path.getsize(p) > FILE_MAX:
            return PlainTextResponse("too large to show\n", status_code=413)
        text = fsutil.read_text(p)
        rel_dir = os.path.dirname(rel)

        def link(href):
            path, _, frag = href.partition("#")
            path = os.path.normpath(os.path.join(rel_dir, path)) if path else rel
            return "%s/frame/doc?path=%s%s" % (base(e, wpid), urllib.parse.quote(path),
                                               "#" + frag if frag else "")
        html = data.md(text, link, lines=True)
        return render(request, "studio_frame.html", frame=True, e=e, wpid=wpid, rel=rel,
                      html=html,
                      text=text if html is None else None, sha=markup.sha(text),
                      writable=os.access(p, os.W_OK), base=base(e, wpid),
                      items=sum(text.count(t) for t in ("{++", "{--", "{~~", "{>>", "{==")))

    async def markup_post(request):
        """Doc markup on a studio document; ``op: ask`` sends the file's markup to
        the studio's agent."""
        e, wpid, st = lookup(request)
        if e is None:
            return st
        bad = mine(request, st)
        if bad:
            return bad
        f = await body_json(request)
        p, rel = artifact_path(st, str(f.get("path") or ""))
        if p is None or not p.lower().endswith((".md", ".markdown")):
            return JSONResponse({"error": "not a document of this studio"}, status_code=404)
        op = f.get("op")
        if op == "ask":
            return await ask_agent(request, e, wpid, st,
                                   "Deal with the markup in %s: make the change each item "
                                   "asks for and remove the item (doc markup)." % rel)
        try:
            if op in ("accept", "reject"):
                fn = lambda t: markup.resolve(t, str(f.get("raw") or ""), int(f.get("n") or 0),  # noqa: E731
                                              op == "accept")
            else:
                lines = tuple(int(x) for x in str(f.get("lines") or "").split("-"))
                if len(lines) != 2:
                    raise markup.MarkupError("no block to mark up")
                fn = lambda t: markup.mark(t, lines, str(f.get("sel") or ""),  # noqa: E731
                                           int(f.get("at") or 0), op, str(f.get("text") or ""))
            w = live(e, wpid).watcher
            w.saved(rel)                    # before the write: a poll may come between
            try:
                sha = await run_in_threadpool(markup.edit, p, str(f.get("sha") or ""), fn)
            except BaseException:
                w.forget(rel)
                raise
        except markup.Stale as ex:
            return JSONResponse({"error": str(ex), "stale": True}, status_code=409)
        except (markup.MarkupError, ValueError) as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        except OSError as ex:
            return JSONResponse({"error": "cannot write %s: %s" % (rel, ex.strerror)},
                                status_code=500)
        return JSONResponse({"sha": sha})

    # -- data and charts (S2) -----------------------------------------------------

    def guarded(request):
        """(entry, wpid, state, None), or (..., the response to return)."""
        e, wpid, st = lookup(request)
        if e is None:
            return None, None, None, st
        return e, wpid, st, mine(request, st)

    def kcall(e, st, op, **kw):
        """A kernel call for the studio (in a thread): the reply, or KernelError."""
        cfg = studio_render.config(home)
        try:
            kernel.export_history(e, st["folder"])
        except Exception:                       # noqa: BLE001  (history is a nicety)
            pass
        return kernel.call(st["folder"], op, timeout=float(cfg["kernel_timeout_s"]),
                           idle_s=60.0 * cfg["kernel_idle_minutes"], **kw)

    async def kernel_json(e, st, op, **kw):
        try:
            r = await run_in_threadpool(kcall, e, st, op, **kw)
        except kernel.KernelError as ex:
            return JSONResponse({"error": str(ex)}, status_code=503)
        if not r.get("ok"):
            return JSONResponse({"error": r.get("error") or "failed"}, status_code=400)
        r.pop("ok", None)
        return JSONResponse(r)

    def table_src(st, q):
        """``{path, table?}`` for a table file named in ``q``, or None."""
        p, rel = artifact_path(st, q.get("path") or "")
        if p is None or not sdata.is_table(rel):
            return None
        src = {"path": rel}
        if q.get("table"):
            src["table"] = str(q["table"])
        return src

    async def table(request):
        """One page of a table: ``?path= [&table=] &offset= &limit= &sort= &desc=1
        &f.<column>=<text>``."""
        e, wpid, st, bad = guarded(request)
        if bad:
            return bad
        q = request.query_params
        src = table_src(st, q)
        if src is None:
            return JSONResponse({"error": "not a table of this studio"}, status_code=404)
        filters = {k[2:]: v for k, v in q.items() if k.startswith("f.") and v}
        return await kernel_json(e, st, "page", src=src, offset=_int(q.get("offset"), 0),
                                 limit=_int(q.get("limit"), 100), sort=q.get("sort") or None,
                                 desc=q.get("desc") == "1", filters=filters)

    async def table_stats(request):
        e, wpid, st, bad = guarded(request)
        if bad:
            return bad
        src = table_src(st, request.query_params)
        if src is None:
            return JSONResponse({"error": "not a table of this studio"}, status_code=404)
        return await kernel_json(e, st, "stats", src=src)

    async def table_tables(request):
        e, wpid, st, bad = guarded(request)
        if bad:
            return bad
        src = table_src(st, request.query_params)
        if src is None:
            return JSONResponse({"error": "not a table of this studio"}, status_code=404)
        return await kernel_json(e, st, "tables", src=src)

    async def sql_run(request):
        """The SQL box: one SELECT, read-only, over the folder's files."""
        e, wpid, st, bad = guarded(request)
        if bad:
            return bad
        b = await body_json(request)
        sql = str(b.get("sql") or "")
        if not sql.strip():
            return JSONResponse({"error": "no SQL"}, status_code=400)
        filters = b.get("filters") if isinstance(b.get("filters"), dict) else {}
        return await kernel_json(e, st, "page", src={"sql": sql}, offset=_int(b.get("offset"), 0),
                                 limit=_int(b.get("limit"), 100), sort=b.get("sort") or None,
                                 desc=bool(b.get("desc")), filters=filters)

    async def sql_save(request):
        """Save the SQL box as a ``.sql`` file (a table on the canvas)."""
        e, wpid, st, bad = guarded(request)
        if bad:
            return bad
        b = await body_json(request)
        sql = str(b.get("sql") or "").strip()
        rel = str(b.get("path") or "").strip()
        if not rel.lower().endswith(".sql"):
            return JSONResponse({"error": "save it as a .sql file"}, status_code=400)
        try:
            rel = model._artifact(st["folder"], rel)
        except model.StudioError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        check = await kernel_json(e, st, "page", src={"sql": sql}, limit=1)
        if check.status_code != 200:
            return check
        p = os.path.join(st["folder"], rel)
        w = live(e, wpid).watcher
        w.saved(rel)
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            fsutil.atomic_write(p, sql.rstrip().rstrip(";") + ";\n")
        except OSError as ex:
            w.forget(rel)
            return JSONResponse({"error": "cannot write %s: %s" % (rel, ex.strerror)},
                                status_code=500)
        return JSONResponse({"path": rel})

    async def chart_data(request):
        """A chart's rows, as JSON (from a table file or a saved query)."""
        e, wpid, st, bad = guarded(request)
        if bad:
            return bad
        src = table_src(st, request.query_params)
        if src is None:
            return JSONResponse({"error": "not a table of this studio"}, status_code=404)
        try:
            r = await run_in_threadpool(kcall, e, st, "records", src=src)
        except kernel.KernelError as ex:
            return JSONResponse({"error": str(ex)}, status_code=503)
        if not r.get("ok"):
            return JSONResponse({"error": r.get("error")}, status_code=400)
        return JSONResponse(r["rows"], headers={
            "x-studio-truncated": "1" if r.get("truncated") else "0",
            "cache-control": "no-store"})

    def chart_of(st, rel_q):
        p, rel = artifact_path(st, rel_q or "")
        if p is None or not rel.lower().endswith(".vl.json"):
            return None, None
        return p, rel

    async def frame_chart(request):
        """A chart for the canvas, in a frame: Vega-Lite with the studio's
        theme, the spec panel, and Ask about a selection."""
        e, wpid, st, bad = guarded(request)
        if bad:
            return PlainTextResponse("not open for you\n", status_code=403)
        p, rel = chart_of(st, request.query_params.get("path"))
        if p is None:
            return PlainTextResponse("not a chart of this studio\n", status_code=404)
        b = base(e, wpid)
        problems, spec, board = [], None, None
        try:
            spec = chart.load(p)
            problems = chart.check(spec, rel, st["folder"])
            if not problems:
                board = chart.for_board(spec, rel, lambda x: chart.data_url(b, x))
        except chart.ChartError as ex:
            problems = [str(ex)]
        src = chart.first_source(spec, rel) if spec and not problems else None
        return render(request, "studio_chart.html", frame=True, e=e, wpid=wpid, rel=rel,
                      base=b, problems=problems, board=board,
                      panel=chart.summary(spec) if spec and not problems else None,
                      source=src, marks=chart.MARKS,
                      themes={"light": chart.theme("light"), "dark": chart.theme("dark")},
                      text=fsutil.read_text(p) if problems else None)

    async def chart_save(request):
        """The spec panel's change, written into the spec (by you)."""
        e, wpid, st, bad = guarded(request)
        if bad:
            return bad
        b = await body_json(request)
        p, rel = chart_of(st, str(b.get("path") or ""))
        if p is None:
            return JSONResponse({"error": "not a chart of this studio"}, status_code=404)
        try:
            spec = chart.apply(chart.load(p), b.get("panel") or {})
        except chart.ChartError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        problems = chart.check(spec, rel, st["folder"])
        if problems:
            return JSONResponse({"error": "; ".join(problems)}, status_code=400)
        w = live(e, wpid).watcher
        w.saved(rel)
        try:
            fsutil.atomic_write(p, json.dumps(spec, indent=2) + "\n")
        except OSError as ex:
            w.forget(rel)
            return JSONResponse({"error": "cannot write %s: %s" % (rel, ex.strerror)},
                                status_code=500)
        return JSONResponse({"ok": True})

    async def chart_select(request):
        """Ask the agent about the rows a chart selection picks: the rows go
        with the question (the selection is the anchor)."""
        e, wpid, st, bad = guarded(request)
        if bad:
            return bad
        b = await body_json(request)
        p, rel = chart_of(st, str(b.get("path") or ""))
        if p is None:
            return JSONResponse({"error": "not a chart of this studio"}, status_code=404)
        sel = b.get("selection")
        if not isinstance(sel, dict) or not sel:
            return JSONResponse({"error": "select something on the chart first"},
                                status_code=400)
        try:
            src = chart.first_source(chart.load(p), rel)
        except chart.ChartError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        if src is None:
            return JSONResponse({"error": "the chart names no data file"}, status_code=400)
        try:
            r = await run_in_threadpool(kcall, e, st, "selected", src={"path": src},
                                        selection=sel, cap=50)
        except kernel.KernelError as ex:
            return JSONResponse({"error": str(ex)}, status_code=503)
        if not r.get("ok"):
            return JSONResponse({"error": r.get("error")}, status_code=400)
        q = str(b.get("text") or "").strip() or "What stands out about these rows?"
        text = selection_ask(rel, src, sel, r, q)
        return await ask_agent(request, e, wpid, st, text)

    # -- the conversation -------------------------------------------------------

    async def ask_agent(request, e, wpid, st, text):
        from . import agent
        if agents is None:
            return JSONResponse({"error": "the agent is off on this board"}, status_code=503)
        s = st["session"]
        cid = s.get("conv") if s else None
        if not cid or agents.get(cid) is None:
            return JSONResponse({"error": "the studio has no conversation; reopen it"},
                                status_code=409)
        lv = live(e, wpid)
        await run_in_threadpool(lv.poll)
        with lv.lock:
            yours, lv.yours, lv.turn = list(lv.yours), [], []
        files = sorted(lv.watcher.stats)
        try:
            memento = model.packet(e, wpid).load_memento()[1]
        except Exception:                       # noqa: BLE001  (context only)
            memento = None
        sets = None
        if any(sdata.is_table(f) for f in files):
            try:
                r = await run_in_threadpool(kcall, e, st, "datasets", files=files)
                sets = r.get("datasets") if r.get("ok") else None
            except kernel.KernelError:
                pass                                # the primer goes without
        text_p = primer.build(e, wpid, st, files=files, yours=yours, memento=memento,
                              datasets=sets)
        try:
            await run_in_threadpool(agents.ask, cid, text, who(request), text_p)
        except agent.Busy as ex:
            with lv.lock:
                lv.yours = yours + lv.yours
            return JSONResponse({"error": str(ex)}, status_code=409)
        except agent.NotTaken as ex:
            return JSONResponse({"error": str(ex)}, status_code=403)
        return JSONResponse({"asked": True, "conv": cid})

    async def ask(request):
        e, wpid, st = lookup(request)
        if e is None:
            return st
        bad = mine(request, st)
        if bad:
            return bad
        b = await body_json(request)
        text = str(b.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "say something"}, status_code=400)
        return await ask_agent(request, e, wpid, st, text)

    async def cancel(request):
        e, wpid, st = lookup(request)
        if e is None:
            return st
        bad = mine(request, st)
        if bad:
            return bad
        cid = (st["session"] or {}).get("conv")
        if agents is not None and cid:
            await run_in_threadpool(agents.cancel, cid)
        return JSONResponse({"ok": True})

    def output_card(e, wpid, lv, cid, end_t):
        """At a turn's end: the files of a known kind the agent made or changed,
        as one ``output`` event (once per turn, however many sockets)."""
        lv.poll()
        with lv.lock:
            if end_t <= lv.carded:
                return
            lv.carded = end_t
            seen, files = set(), []
            for c in lv.turn:
                if c["change"] == "deleted" or c["path"] in seen:
                    continue
                seen.add(c["path"])
                k = kinds.kind_of(c["path"])
                files.append({"path": c["path"], "change": c["change"],
                              "kind": k.name if k else None})
            lv.turn = []
        if files:
            agents.append(cid, {"k": "output", "files": files})

    async def ws(sock):
        await sock.accept()
        try:
            first = await asyncio.wait_for(sock.receive_text(), 5)
            token = (json.loads(first) or {}).get("token") or ""
        except (asyncio.TimeoutError, ValueError, KeyError, TypeError, AttributeError,
                WebSocketDisconnect):
            token = ""
        want = sock.scope.get("state", {}).get("csrf") or ""
        e = entry(sock)
        wpid = sock.path_params["wpid"]
        st = None
        if e is not None and schema.is_wpid(wpid):
            try:
                st = model.state(e, wpid)
            except model.StudioError:
                st = None
        me = sock.scope.get("state", {}).get("user") or who(sock)
        ok = (want and hmac.compare_digest(token, want) and st is not None and st["open"]
              and st.get("taken_by") == me and agents is not None)
        cid = (st or {}).get("session", {}) and st["session"].get("conv")
        if not ok or not cid or agents.get(cid) is None:
            return await sock.close(1008)
        lv = live(e, wpid)
        queue = asyncio.Queue()
        agents.subscribe(cid, asyncio.get_running_loop(), queue)
        try:
            since = float(sock.query_params.get("since") or 0)
        except ValueError:
            since = 0.0
        try:
            await sock.send_text(json.dumps({"k": "busy", "on": agents.busy(cid)}))
            for ev in await run_in_threadpool(agents.transcript, cid, 100000):
                if ev.get("t", 0) > since:
                    await sock.send_text(json.dumps(ev))
            rx = asyncio.ensure_future(sock.receive())
            while True:
                get = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({rx, get}, timeout=watch.INTERVAL_S,
                                             return_when=asyncio.FIRST_COMPLETED)
                if rx in done:
                    get.cancel()
                    if rx.result()["type"] == "websocket.disconnect":
                        break
                    rx = asyncio.ensure_future(sock.receive())
                    continue
                if get in done:
                    ev = get.result()
                    if ev.get("k") == "tool" and ev.get("name") in ("Write", "Edit",
                                                                   "MultiEdit"):
                        lv.watcher.agent_wrote(ev.get("what") or "")
                    await sock.send_text(json.dumps(ev))
                    if ev.get("k") == "end":
                        await run_in_threadpool(output_card, e, wpid, lv, cid,
                                                ev.get("t") or time.time())
                    continue
                get.cancel()
                for c in await run_in_threadpool(lv.poll):
                    await sock.send_text(json.dumps(dict(c, k="changed")))
            rx.cancel()
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            agents.unsubscribe(cid, queue)
            if sock.client_state == WebSocketState.CONNECTED and \
                    sock.application_state == WebSocketState.CONNECTED:
                try:
                    await sock.close()
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass

    p = "/p/{project}/{wpid}/studio"
    return [
        Route(p, page),
        Route(p + "/open", open_, methods=["POST"]),
        Route(p + "/close", close, methods=["POST"]),
        Route(p + "/draft", draft),
        Route(p + "/canvas", canvas),
        Route(p + "/pin", pin, methods=["POST"]),
        Route(p + "/unpin", unpin, methods=["POST"]),
        Route(p + "/layout", lay, methods=["POST"]),
        Route(p + "/ask", ask, methods=["POST"]),
        Route(p + "/cancel", cancel, methods=["POST"]),
        Route(p + "/markup", markup_post, methods=["POST"]),
        Route(p + "/file", raw),
        Route(p + "/frame/doc", frame_doc),
        Route(p + "/table", table),
        Route(p + "/table/stats", table_stats),
        Route(p + "/table/tables", table_tables),
        Route(p + "/sql", sql_run, methods=["POST"]),
        Route(p + "/sql/save", sql_save, methods=["POST"]),
        Route(p + "/data", chart_data),
        Route(p + "/frame/chart", frame_chart),
        Route(p + "/chart", chart_save, methods=["POST"]),
        Route(p + "/select", chart_select, methods=["POST"]),
        WebSocketRoute(p + "/ws", ws),
    ]
