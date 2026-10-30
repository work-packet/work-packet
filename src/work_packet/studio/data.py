"""Tables and queries for the studio (docs/studio-plan.md S2.3-S2.5).

This runs in the studio's kernel (``kernel_main.py``), whose working
directory is the studio's folder, so a path in a query is a path in the
folder. It needs DuckDB and the standard library only: the kernel may run
in the packet's own Python.

Two kinds of connection:

- ``connect(sandbox=False)``: the agent's, for ``wpk studio exec|query``. It
  can read anything the user can (the same trust as a step's Bash).
- ``connect(sandbox=True)``: the viewers' and the person's SQL box. DuckDB
  may read only inside the folder (``allowed_directories``, external access
  off, the configuration locked), and the SQL it is given must be one
  SELECT (``check_select``), so nothing is written.

A table **source** is a file (``.csv .tsv .parquet .jsonl .ndjson``), a
table in a SQLite file (``.sqlite .sqlite3 .db``, with ``table``), a saved
query (``.sql``: one SELECT over the folder's files), or SQL text. Both
connections have ``history.steps``: the project's steps and their cost,
from ``.studio/history/steps.jsonl`` (written by wpk, ``kernel.export_history``).
"""

import datetime
import decimal
import fnmatch
import hashlib
import os
import uuid

HISTORY_FILE = os.path.join(".studio", "history", "steps.jsonl")
HISTORY_COLUMNS = {
    "packet": "VARCHAR", "step": "INTEGER", "attempt": "INTEGER", "worker": "VARCHAR",
    "failed": "BOOLEAN", "carried": "BOOLEAN", "harness": "VARCHAR", "model": "VARCHAR",
    "profile": "VARCHAR", "item": "VARCHAR", "cost": "DOUBLE", "calls": "INTEGER",
    "input_tokens": "BIGINT", "output_tokens": "BIGINT", "cache_read": "BIGINT",
    "cache_write": "BIGINT", "thinking_tokens": "BIGINT", "duration_s": "DOUBLE",
    "api_s": "DOUBLE", "end": "TIMESTAMP",
}
FILE_TABLES = ("*.csv", "*.tsv", "*.parquet", "*.jsonl", "*.ndjson")
SQLITE = ("*.sqlite", "*.sqlite3", "*.db")
SAVED = ("*.sql",)
ROWS_MAX = 1000             # one page of the table viewer, at most
CHART_ROWS = 20000          # rows a chart gets; more is cut (aggregate in SQL instead)


class DataError(Exception):
    """The query or source cannot be used; the message says why."""


def _duckdb():
    try:
        import duckdb
    except ImportError:
        raise DataError("DuckDB is not installed in the kernel's Python: "
                        "pip install 'work-packet[studio]' (or duckdb in the packet's venv)")
    return duckdb


def _is(name, pats):
    n = os.path.basename(name).lower()
    return any(fnmatch.fnmatchcase(n, p) for p in pats)


def is_table(path):
    return _is(path, FILE_TABLES + SQLITE + SAVED)


def _lit(s):
    return "'" + str(s).replace("'", "''") + "'"


def ident(s):
    return '"' + str(s).replace('"', '""') + '"'


def _rel(path):
    """``path`` as a relative path inside the folder (the cwd), or DataError."""
    p = str(path or "").replace("\\", "/")
    if not p or p.startswith("/") or os.path.isabs(p):
        raise DataError("a path in the studio's folder, not %r" % p)
    n = os.path.normpath(p)
    if n == ".." or n.startswith("../") or n.split("/")[0] in (".git", ".work-packet"):
        raise DataError("%s is outside the studio's folder" % p)
    return n


# --- connections ---------------------------------------------------------------

def connect(sandbox=False, folder=None):
    """A DuckDB connection for the studio in ``folder`` (default: the cwd)."""
    duckdb = _duckdb()
    folder = os.path.abspath(folder or os.getcwd())
    con = duckdb.connect(":memory:")
    try:
        con.execute("LOAD sqlite")
    except Exception:  # noqa: BLE001  (not installed and no network: SQLite files are refused)
        pass
    con.execute("CREATE SCHEMA history")
    cols = "{%s}" % ", ".join("%s: %s" % (_lit(k), _lit(v)) for k, v in HISTORY_COLUMNS.items())
    hist = os.path.join(folder, HISTORY_FILE)
    if not os.path.isfile(hist):
        os.makedirs(os.path.dirname(hist), exist_ok=True)
        open(hist, "a").close()
    con.execute("CREATE VIEW history.steps AS SELECT * FROM read_json(%s, "
                "format='newline_delimited', columns=%s)" % (_lit(hist), cols))
    if sandbox:
        con.execute("SET allowed_directories=[%s]" % _lit(folder.rstrip("/") + "/"))
        con.execute("SET enable_external_access=false")
        con.execute("SET lock_configuration=true")
    return con


def check_select(sql):
    """``sql`` stripped, if it is exactly one SELECT; else DataError."""
    duckdb = _duckdb()
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise DataError("no SQL")
    try:
        st = duckdb.extract_statements(text)
    except Exception as ex:  # noqa: BLE001
        raise DataError("cannot parse the SQL: %s" % _short(ex))
    if len(st) != 1:
        raise DataError("one statement only (this has %d)" % len(st))
    if st[0].type != duckdb.StatementType.SELECT:
        raise DataError("a SELECT only here (this is %s)" % st[0].type.name)
    return text


def _short(ex):
    return str(ex).strip().split("\n")[0][:300]


def _sqlite_alias(path):
    return "sq_" + hashlib.sha1(path.encode()).hexdigest()[:10]


def base(con, src):
    """The SELECT for a table source ``{path, table?}`` or ``{sql}``."""
    if src.get("sql") is not None:
        return check_select(src["sql"])
    p = _rel(src.get("path"))
    if not os.path.isfile(p):
        raise DataError("no file %s" % p)
    low = p.lower()
    if _is(p, SAVED):
        with open(p, encoding="utf-8") as fp:
            return check_select(fp.read())
    if _is(p, SQLITE):
        alias = _sqlite_alias(p)
        try:
            con.execute("ATTACH IF NOT EXISTS %s AS %s (TYPE sqlite, READ_ONLY)"
                        % (_lit(p), alias))
        except Exception as ex:  # noqa: BLE001
            raise DataError("cannot open %s as SQLite: %s" % (p, _short(ex)))
        t = src.get("table") or (tables(con, src) or [None])[0]
        if t is None:
            raise DataError("%s has no tables" % p)
        if t not in tables(con, src):
            raise DataError("no table %s in %s" % (t, p))
        return "SELECT * FROM %s.%s" % (alias, ident(t))
    if low.endswith(".parquet"):
        return "SELECT * FROM read_parquet(%s)" % _lit(p)
    if low.endswith((".jsonl", ".ndjson")):
        return "SELECT * FROM read_json_auto(%s, format='newline_delimited')" % _lit(p)
    if low.endswith(".tsv"):
        return "SELECT * FROM read_csv_auto(%s, delim='\t')" % _lit(p)
    return "SELECT * FROM read_csv_auto(%s)" % _lit(p)


def tables(con, src):
    """The tables of a SQLite source (empty for other sources)."""
    p = _rel(src.get("path"))
    if not _is(p, SQLITE):
        return []
    alias = _sqlite_alias(p)
    con.execute("ATTACH IF NOT EXISTS %s AS %s (TYPE sqlite, READ_ONLY)" % (_lit(p), alias))
    got = con.execute("SELECT table_name FROM information_schema.tables "
                      "WHERE table_catalog = ? ORDER BY table_name", [alias]).fetchall()
    return [r[0] for r in got]


# --- results -------------------------------------------------------------------

def jsonable(v):
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, datetime.timedelta):
        return v.total_seconds()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    return str(v)


def columns(con, sql):
    """[{name, type}] of a SELECT."""
    try:
        got = con.execute("DESCRIBE SELECT * FROM (%s) t" % sql).fetchall()
    except Exception as ex:  # noqa: BLE001
        raise DataError(_short(ex))
    return [{"name": r[0], "type": r[1]} for r in got]


def _where(cols, filters):
    names = {c["name"] for c in cols}
    conds, params = [], []
    for k, v in (filters or {}).items():
        if k not in names:
            raise DataError("no column %s" % k)
        if v is None or str(v) == "":
            continue
        conds.append("CAST(%s AS VARCHAR) ILIKE ?" % ident(k))
        params.append("%" + str(v) + "%")
    return (" WHERE " + " AND ".join(conds) if conds else ""), params


def page(con, src, offset=0, limit=100, sort=None, desc=False, filters=None):
    """One page of a table: ``{columns, rows, total, offset}``; ``filters``
    ``{column: text}`` keep rows whose value contains the text."""
    sql = base(con, src)
    cols = columns(con, sql)
    where, params = _where(cols, filters)
    order = ""
    if sort:
        if sort not in {c["name"] for c in cols}:
            raise DataError("no column %s" % sort)
        order = " ORDER BY %s %s NULLS LAST" % (ident(sort), "DESC" if desc else "ASC")
    limit = max(1, min(int(limit or 100), ROWS_MAX))
    offset = max(0, int(offset or 0))
    try:
        total = con.execute("SELECT count(*) FROM (%s) t%s" % (sql, where), params).fetchone()[0]
        rows = con.execute("SELECT * FROM (%s) t%s%s LIMIT %d OFFSET %d"
                           % (sql, where, order, limit, offset), params).fetchall()
    except Exception as ex:  # noqa: BLE001
        raise DataError(_short(ex))
    return {"columns": cols, "rows": [[jsonable(v) for v in r] for r in rows],
            "total": total, "offset": offset}


def stats(con, src):
    """Per column: type, count, nulls (percent), min, max, distinct (approx)."""
    sql = base(con, src)
    try:
        cur = con.execute("SUMMARIZE SELECT * FROM (%s) t" % sql)
        names = [d[0] for d in cur.description]
        got = [dict(zip(names, r)) for r in cur.fetchall()]
    except Exception as ex:  # noqa: BLE001
        raise DataError(_short(ex))
    return [{"name": r["column_name"], "type": r["column_type"], "count": jsonable(r["count"]),
             "nulls": jsonable(r["null_percentage"]), "min": jsonable(r["min"]),
             "max": jsonable(r["max"]), "distinct": jsonable(r["approx_unique"])} for r in got]


def records(con, src, cap=CHART_ROWS):
    """The rows as a list of dicts (for a chart): ``(records, truncated)``."""
    sql = base(con, src)
    try:
        cur = con.execute("SELECT * FROM (%s) t LIMIT %d" % (sql, cap + 1))
        names = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except Exception as ex:  # noqa: BLE001
        raise DataError(_short(ex))
    out = [{n: jsonable(v) for n, v in zip(names, r)} for r in rows[:cap]]
    return out, len(rows) > cap


def selected(con, src, selection, cap=50):
    """The rows a chart selection picks. ``selection``: ``{field: [lo, hi]}``
    (an interval: a brush) or ``{field: [v, ...]}`` with ``"kind": "point"``.
    Numbers on a date or timestamp column are epoch milliseconds (Vega's)."""
    sql = base(con, src)
    cols = {c["name"]: c["type"] for c in columns(con, sql)}
    point = selection.get("kind") == "point"
    conds, params = [], []
    for k, v in selection.items():
        if k == "kind":
            continue
        if k not in cols:
            raise DataError("no column %s" % k)
        vals = v if isinstance(v, list) else [v]
        temporal = cols[k].startswith(("DATE", "TIMESTAMP"))

        def val(x):
            if temporal and isinstance(x, (int, float)) and not isinstance(x, bool):
                return datetime.datetime.fromtimestamp(x / 1000.0, datetime.timezone.utc
                                                       ).replace(tzinfo=None)
            return x
        if point:
            conds.append("%s IN (%s)" % (ident(k), ", ".join("?" for _ in vals)))
            params += [val(x) for x in vals]
        else:
            if len(vals) != 2:
                raise DataError("an interval is [low, high]")
            conds.append("%s BETWEEN ? AND ?" % ident(k))
            params += [val(vals[0]), val(vals[1])]
    where = " WHERE " + " AND ".join(conds) if conds else ""
    try:
        total = con.execute("SELECT count(*) FROM (%s) t%s" % (sql, where), params).fetchone()[0]
        cur = con.execute("SELECT * FROM (%s) t%s LIMIT %d" % (sql, where, cap), params)
        names = [d[0] for d in cur.description]
        rows = [[jsonable(x) for x in r] for r in cur.fetchall()]
    except Exception as ex:  # noqa: BLE001
        raise DataError(_short(ex))
    return {"columns": names, "rows": rows, "total": total, "where": where.strip(),
            "params": [jsonable(p) for p in params]}


def datasets(con, files, limit=30):
    """[{path, table?, columns, rows?, error?}] for the table files in ``files``
    (relative paths), then ``history.steps``."""
    out = []
    for f in sorted(f for f in files if is_table(f))[:limit]:
        srcs = [{"path": f}]
        try:
            if _is(f, SQLITE):
                srcs = [{"path": f, "table": t} for t in tables(con, {"path": f})[:10]]
            for s in srcs:
                sql = base(con, s)
                d = dict(s, columns=columns(con, sql))
                if os.path.getsize(f) <= (64 << 20):
                    d["rows"] = con.execute("SELECT count(*) FROM (%s) t" % sql).fetchone()[0]
                out.append(d)
        except (DataError, OSError) as ex:
            out.append({"path": f, "error": str(ex)})
    try:
        out.append({"path": "history.steps", "columns": columns(con, "SELECT * FROM history.steps"),
                    "rows": con.execute("SELECT count(*) FROM history.steps").fetchone()[0]})
    except DataError:
        pass
    return out


def text_table(names, rows, total=None, width=40):
    """A plain-text table for the agent (``wpk studio query``)."""
    cells = [[_cell(v, width) for v in r] for r in rows]
    w = [max([len(str(n))] + [len(r[i]) for r in cells]) for i, n in enumerate(names)]
    line = lambda r: " | ".join(s.ljust(w[i]) for i, s in enumerate(r)).rstrip()  # noqa: E731
    out = [line([str(n) for n in names]), "-+-".join("-" * x for x in w)]
    out += [line(r) for r in cells]
    if total is not None and total > len(rows):
        out.append("(%d of %d rows)" % (len(rows), total))
    return "\n".join(out)


def _cell(v, width):
    s = "NULL" if v is None else str(jsonable(v))
    s = s.replace("\n", " ")
    return s if len(s) <= width else s[:width - 1] + "…"
