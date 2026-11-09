"""The desktop tab: ``/desk/<key>/`` (docs/desktop.md D1, D4, D6).

The page is noVNC (``vendor/novnc``). Its WebSocket, ``/desk/<key>/ws``,
is converted to the VNC byte stream of the IDE server's xproxy: straight to
its socket for a server the board runs, through the job's relay (TLS server
name ``vnc.wpk``) for a job's. ``/desk/<key>/state`` is xproxy's report.
Owner only, like ``/ide/`` (the guard); the WebSocket also checks the
Origin (the guard) and the CSRF token (``?t=``, as noVNC can't send a first
message of ours).
"""

import asyncio
import contextlib
import hmac
import logging

log = logging.getLogger("wpk.desk")
CHUNK = 65536


def backend_for(backends, key):
    """The IDE server for ``key`` if the board knows it, else None."""
    return backends.get(key) if backends is not None else None


def state(backends, key):
    """What the page and the IDE's toast show: ``{"desktop": bool, ...}``."""
    be = backend_for(backends, key)
    if be is None:
        return {"desktop": False, "why": "no such IDE server"}
    st = be.desk_state()
    if st is None and not be.running():
        return {"desktop": False, "why": "the IDE server isn't running: open the IDE first "
                                         "(its desktop lives in the same server)"}
    if st is None:
        from .. import desktop
        raw = desktop.state(be.dir) or {}
        why = raw.get("why") or ("the IDE's job carries no desktop ([sched.ide] transport "
                                 "must be \"mtls\")" if not be.desk_ok else
                                 "the IDE server isn't running with a desktop: turn on "
                                 "[desktop] enabled, then close the IDE and open it again")
        return {"desktop": False, "why": why}
    out = {k: st.get(k) for k in ("display", "x", "clients", "viewers", "apps", "wm", "since",
                                  "why", "launchers")}
    out["desktop"] = True
    return out


def run(backends, key, name):
    """Ask the desktop's xproxy to start ``[desktop.apps]`` entry ``name``.
    Returns ``(status, message)``."""
    from .. import desktop
    be = backend_for(backends, key)
    st = be.desk_state() if be is not None else None
    if st is None:
        return 409, "no desktop: open the IDE first"
    if name not in {a.get("name") for a in st.get("launchers") or ()}:
        return 404, "no app %r on this desktop ([desktop.apps])" % name
    desktop.request_run(be.dir, name)
    return 202, "starting %s" % name


async def bridge(backends, ws, key, token):
    """The browser's WebSocket ⇄ the desktop's VNC stream."""
    want = ws.scope.get("state", {}).get("csrf") or ""
    if not (token and want and hmac.compare_digest(token, want)):
        return await ws.close(1008)
    be = backend_for(backends, key)
    if be is None:
        return await ws.close(1008)
    try:
        reader, writer = await be.desk_connect()
    except Exception as e:                  # noqa: BLE001 — say why in the log, close
        log.warning("desktop %s: %s", key, e)
        return await ws.close(1011)
    sub = ws.headers.get("sec-websocket-protocol", "")
    await ws.accept(subprotocol="binary" if "binary" in [s.strip() for s in sub.split(",")]
                    else None)
    be.clients += 1                         # a viewer keeps the IDE server from idling out

    async def down():
        while True:
            data = await reader.read(CHUNK)
            if not data:
                return
            await ws.send_bytes(data)

    async def up():
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                return
            be.last = be._clock()
            data = m.get("bytes")
            if data is None and m.get("text") is not None:
                data = m["text"].encode("latin-1", "replace")
            if data:
                writer.write(data)
                await writer.drain()

    tasks = [asyncio.ensure_future(down()), asyncio.ensure_future(up())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        be.clients -= 1
        be.last = be._clock()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            writer.close()
        with contextlib.suppress(Exception):
            await ws.close()
