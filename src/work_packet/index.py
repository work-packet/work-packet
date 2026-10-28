"""``index.db``: every card this host knows, by name, id and path
(docs/work-data-design.md §5). It is a cache: ``rebuild`` makes it again
from the cards it lists and any found under the task-folder root."""

import os
import sqlite3

from . import card as cardmod

_SCHEMA = """
CREATE TABLE IF NOT EXISTS card (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, title TEXT,
    state TEXT, updated TEXT, parent TEXT, project TEXT, tags TEXT);
CREATE INDEX IF NOT EXISTS card_name ON card (name);
"""


def path(h=None):
    from . import registry
    return os.path.join(h or registry.home(), "index.db")


def connect(h=None):
    p = path(h)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p)
    con.executescript(_SCHEMA)
    return con


def _address(c):
    """A sub-packet is addressed as ``<root name>.<name>``."""
    par = c.meta.get("parent")
    if isinstance(par, str) and par.startswith("pkt:"):
        return "%s.%s" % (par[4:], c.name)
    return c.name


def upsert(c, card_path, h=None):
    con = connect(h)
    try:
        with con:
            con.execute("INSERT OR REPLACE INTO card VALUES (?,?,?,?,?,?,?,?,?)", (
                c.id or os.path.abspath(card_path), _address(c), os.path.abspath(card_path),
                c.title, c.state(), c.meta.get("updated"), c.meta.get("parent"),
                (c.meta.get("x-wpk") or {}).get("project"),
                ",".join(map(str, c.meta.get("tags") or []))))
    finally:
        con.close()


def rows(h=None):
    con = connect(h)
    try:
        cur = con.execute("SELECT id, name, path, title, state, updated, parent, project, tags "
                          "FROM card ORDER BY updated DESC")
        keys = [d[0] for d in cur.description]
        return [dict(zip(keys, r)) for r in cur]
    finally:
        con.close()


def find(target, h=None):
    """The card path for a name, a unique name prefix, an id, or a path."""
    if os.path.isfile(target):
        return os.path.abspath(target)
    if os.path.isdir(target):
        p = cardmod.find_up(target)
        if p:
            return p
    rs = rows(h)
    for key in ("id", "name"):
        hit = [r for r in rs if r[key] == target]
        if len(hit) == 1:
            return hit[0]["path"]
    hit = [r for r in rs if r["name"].startswith(target) or r["id"].startswith(target)]
    if len(hit) == 1:
        return hit[0]["path"]
    if len(hit) > 1:
        raise LookupError("%s matches %s" % (target, ", ".join(r["name"] for r in hit[:6])))
    raise LookupError("no card named %r" % target)


def refresh(h=None):
    """Re-read every indexed card; drop the ones that are gone."""
    con = connect(h)
    gone = []
    try:
        for (cid, p) in con.execute("SELECT id, path FROM card").fetchall():
            if not os.path.isfile(p):
                gone.append(cid)
    finally:
        con.close()
    con = connect(h)
    with con:
        for cid in gone:
            con.execute("DELETE FROM card WHERE id = ?", (cid,))
    con.close()
    for r in rows(h):
        upsert(cardmod.load(r["path"]), r["path"], h)
    return gone
