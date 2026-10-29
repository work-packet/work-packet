"""The DFM event collector (docs/dfm-events.md §2, §5).

The board listens on ``$WPK_HOME/events/events.sock`` and exports
``DFM_EVENT_SINK=unix:<that>`` and ``DFM_EVENT_CTX=WPK_*`` into its own
environment, so every ``dfm run`` started under it (by a step, a shell, a
terminal) connects and streams JSON lines. Each line is appended, as received,
to ``$WPK_HOME/runs/dfm/<sid>.jsonl``; the pages fold those journals
(``dash/dfmrun.py``). The collector adds two lines of its own (``src: "wpk"``):
``conn.open`` with the peer's pid, and ``conn.close`` when a connection ends
before the run's ``run.end``, which is what marks a run lost.

Nothing is ever sent back: a producer that misbehaves loses its connection.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import socket
import struct
import time

log = logging.getLogger("wpk.dash")

ENV_SINK = "DFM_EVENT_SINK"
ENV_CTX = "DFM_EVENT_CTX"
CTX = "WPK_*"
LINE_MAX = 1 << 20          # bytes in one line; DFM truncates long fields well below this
SIDS_PER_CONN = 64          # runs one connection may name (a relay, a shared file sink)
KEEP_RUNS = 200             # journals kept, newest first ...
KEEP_DAYS = 30              # ... and none older than this
SUN_PATH_MAX = 107
SID_RE = re.compile(r"^[0-9A-Za-z_-]{8,64}$")


def journal_dir(home):
    return os.path.join(home, "runs", "dfm")


def journal(home, sid):
    """The journal of run ``sid``, or None when ``sid`` is not a stream id."""
    return os.path.join(journal_dir(home), sid + ".jsonl") if SID_RE.match(sid or "") else None


def sock_path(home, env=None):
    """``$WPK_HOME/events/events.sock`` when it fits in ``sun_path``, else a short
    private directory named after the home (as ``dash.ide.socket_path``)."""
    env = os.environ if env is None else env
    p = os.path.join(home, "events", "events.sock")
    if len(os.fsencode(p)) <= SUN_PATH_MAX:
        return p
    tag = hashlib.sha256(os.fsencode(os.path.abspath(home))).hexdigest()[:8]
    run = env.get("XDG_RUNTIME_DIR")
    if run and os.path.isdir(run):
        return os.path.join(run, "wpk-ev-" + tag, "events.sock")
    return os.path.join("/tmp", "wpk-ev-%d-%s" % (os.getuid(), tag), "events.sock")


def _append(env, name, item):
    """Add ``item`` to the comma-separated list in ``env[name]``, once."""
    have = [x for x in (env.get(name) or "").split(",") if x.strip()]
    if item not in have:
        env[name] = ",".join(have + [item])


def export_env(path, env=None):
    """Point every child of this process at the collector (§2): collectors append."""
    env = os.environ if env is None else env
    _append(env, ENV_SINK, "unix:" + path)
    _append(env, ENV_CTX, CTX)


def unexport_env(path, env=None):
    env = os.environ if env is None else env
    for name, item in ((ENV_SINK, "unix:" + path), (ENV_CTX, CTX)):
        rest = [x for x in (env.get(name) or "").split(",") if x.strip() and x != item]
        if rest:
            env[name] = ",".join(rest)
        else:
            env.pop(name, None)


def prune(home, keep=KEEP_RUNS, days=KEEP_DAYS, now=None):
    """Remove all but the newest ``keep`` journals, and any older than ``days``."""
    d = journal_dir(home)
    now = time.time() if now is None else now
    try:
        names = [n for n in os.listdir(d) if n.endswith(".jsonl")]
    except OSError:
        return 0
    aged = []
    for n in names:
        with contextlib.suppress(OSError):
            aged.append((os.path.getmtime(os.path.join(d, n)), n))
    aged.sort(reverse=True)
    gone = 0
    for i, (mt, n) in enumerate(aged):
        if i >= keep or now - mt > days * 86400:
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(d, n))
                gone += 1
    return gone


def _peer_pid(writer):
    sock = writer.get_extra_info("socket")
    try:
        cred = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", cred)[0]
    except (OSError, AttributeError, struct.error):
        return None


class Collector:
    """The board's end of ``DFM_EVENT_SINK``: one Unix server on the board's loop."""

    def __init__(self, home, path=None):
        self.home = home
        self.path = path or sock_path(home)
        self.server = None
        self.owner = {}             # sid -> the peer pid that first named it
        self.conns = set()

    async def start(self, export=True):
        d = os.path.dirname(self.path)
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
        os.makedirs(journal_dir(self.home), exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.path)            # one board per home: a leftover file
        self.server = await asyncio.start_unix_server(self._serve, path=self.path,
                                                      limit=LINE_MAX)
        os.chmod(self.path, 0o600)
        prune(self.home)
        if export:
            export_env(self.path)
        return self

    async def stop(self):
        if self.server is None:
            return
        unexport_env(self.path)
        self.server.close()
        for t in list(self.conns):
            t.cancel()
        await asyncio.gather(*self.conns, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self.server.wait_closed()
        with contextlib.suppress(OSError):
            os.unlink(self.path)
        self.server = None

    async def _serve(self, reader, writer):
        task = asyncio.current_task()
        self.conns.add(task)
        conn = _Conn(self, _peer_pid(writer))
        why = "eof"
        try:
            while True:
                try:
                    line = await reader.readline()
                except (asyncio.LimitOverrunError, ValueError):
                    why = "line too long"
                    break
                if not line:
                    break
                if not conn.take(line):
                    why = "rejected"
                    break
        except asyncio.CancelledError:
            why = "board stopped"
        except (ConnectionError, OSError):
            why = "reset"
        finally:
            conn.close(why)
            writer.close()
            self.conns.discard(task)


class _Conn:
    """One producer connection: the journals it writes and the runs it has open."""

    def __init__(self, coll, peer):
        self.coll = coll
        self.peer = peer
        self.files = {}             # sid -> open journal
        self.ended = set()

    def take(self, raw):
        """Journal one line. False drops the connection."""
        try:
            ev = json.loads(raw)
        except ValueError:
            return True                 # one bad line is ignored, not fatal
        if not isinstance(ev, dict) or ev.get("v") != 1 or not isinstance(ev.get("src"), str):
            return True
        sid = ev.get("sid")
        if not isinstance(sid, str) or not SID_RE.match(sid):
            return True
        owner = self.coll.owner.setdefault(sid, self.peer)
        if owner != self.peer:
            log.debug("dfm events: %s claimed by pid %s, owned by %s", sid, self.peer, owner)
            return True
        fp = self.files.get(sid)
        if fp is None:
            if len(self.files) >= SIDS_PER_CONN:
                return False
            path = journal(self.coll.home, sid)
            try:
                fp = open(path, "a")
            except OSError as e:
                log.warning("dfm events: cannot write %s: %s", path, e)
                return False
            self.files[sid] = fp
            self._own(fp, sid, "conn.open", peer=self.peer)
        fp.write(raw.decode("utf-8", "replace").rstrip("\n") + "\n")
        fp.flush()
        if ev.get("ev") == "run.end":
            self.ended.add(sid)
        return True

    def _own(self, fp, sid, ev, **kw):
        rec = dict(v=1, src="wpk", sid=sid, t=round(time.time(), 3), ev=ev, **kw)
        fp.write(json.dumps(rec) + "\n")
        fp.flush()

    def close(self, why):
        for sid, fp in self.files.items():
            with contextlib.suppress(OSError, ValueError):
                if sid not in self.ended:
                    self._own(fp, sid, "conn.close", why=why)
                fp.close()
            self.coll.owner.pop(sid, None)      # the run is over as far as we can see
        self.files = {}
