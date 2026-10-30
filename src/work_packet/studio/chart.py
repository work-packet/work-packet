"""Charts (docs/studio-plan.md S2.4): Vega-Lite specs in ``*.vl.json``.

A spec names its data by path, not inline: ``"data": {"url": "data/runs.csv"}``
(a table file or a saved ``.sql`` query), relative to the spec's own folder
like a link in a document. The board serves the rows (``/studio/data``), so a
chart follows its data. ``check`` says what is wrong with a spec; ``for_board``
rewrites its data URLs to the board's; ``theme`` is the studio's look, from
the dash's tokens (``base.html``), light and dark.
"""

import copy
import json
import os
import urllib.parse

from . import data

VIEWS = ("mark", "layer", "concat", "hconcat", "vconcat", "facet", "repeat", "spec")
MARKS = ("bar", "line", "point", "area", "tick", "rect", "arc", "circle", "square", "rule",
         "text", "boxplot", "errorbar", "trail")
SPEC_MAX = 1 << 20

# The dash's series colours (base.html --sp0..--sp7), light and dark: one
# palette for every chart on the board.
PALETTE = {
    "light": ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1",
              "#9c755f"],
    "dark": ["#6f9bd1", "#f5a04f", "#74bf69", "#ec7a7b", "#8fcfca", "#e9cf63", "#c596b9",
             "#b8927a"],
}
INK = {"light": ("#1d2330", "#667085", "#dde1e8", "#ffffff"),     # ink, muted, line, panel
       "dark": ("#e3e6ec", "#949bab", "#2c323d", "#1b1f27")}


class ChartError(Exception):
    pass


def load(path):
    """The spec in ``path``, or ChartError."""
    if os.path.getsize(path) > SPEC_MAX:
        raise ChartError("the spec is over 1 MB: keep the data in a file")
    try:
        with open(path, encoding="utf-8") as fp:
            spec = json.load(fp)
    except ValueError as ex:
        raise ChartError("not JSON: %s" % ex)
    if not isinstance(spec, dict):
        raise ChartError("a spec is a JSON object")
    return spec


def _datas(spec):
    """Every ``data`` object with a ``url`` in the spec (nested views too)."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            d = x.get("data")
            if isinstance(d, dict) and "url" in d:
                out.append(d)
            for k, v in x.items():
                if k != "data":
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(spec)
    return out


def resolve(rel, url):
    """The folder path a spec at ``rel`` means by ``url``, or ChartError."""
    u = str(url)
    if "://" in u or u.startswith(("/", "data:")):
        raise ChartError("data.url %s: name a file in the studio's folder" % u)
    p = os.path.normpath(os.path.join(os.path.dirname(rel), u)).replace(os.sep, "/")
    if p == ".." or p.startswith("../"):
        raise ChartError("data.url %s is outside the studio's folder" % u)
    return p


def check(spec, rel, folder):
    """What is wrong with ``spec`` (a list of messages; empty when fine)."""
    out = []
    if not isinstance(spec, dict):
        return ["a spec is a JSON object"]
    if not any(k in spec for k in VIEWS):
        out.append("no view: a spec needs a mark (or layer, concat, facet, repeat)")
    m = spec.get("mark")
    mt = m.get("type") if isinstance(m, dict) else m
    if mt is not None and mt not in MARKS:
        out.append("unknown mark %r" % mt)
    for d in _datas(spec):
        try:
            p = resolve(rel, d["url"])
        except ChartError as ex:
            out.append(str(ex))
            continue
        if not data.is_table(p):
            out.append("data.url %s: not a table file (.csv .parquet .jsonl .sql ...)" % p)
        elif not os.path.isfile(os.path.join(folder, p)):
            out.append("data.url %s: no such file" % p)
    if "data" in spec and isinstance(spec["data"], dict) and "values" in spec["data"]:
        n = len(spec["data"]["values"]) if isinstance(spec["data"]["values"], list) else 0
        if n > 200:
            out.append("%d inline values: put the data in a file and name it" % n)
    return out


def for_board(spec, rel, data_url):
    """A copy of ``spec`` whose data URLs are the board's: ``data_url(path)``,
    rows as JSON (any CSV or TSV format options are dropped; ``parse`` stays)."""
    s = copy.deepcopy(spec)
    for d in _datas(s):
        d["url"] = data_url(resolve(rel, d["url"]))
        fmt = d.get("format") if isinstance(d.get("format"), dict) else {}
        d["format"] = dict({"type": "json"}, **({"parse": fmt["parse"]} if "parse" in fmt
                                                else {}))
    return s


def first_source(spec, rel):
    """The folder path of the spec's main data (for a selection's rows)."""
    top = spec.get("data")
    if isinstance(top, dict) and "url" in top:
        return resolve(rel, top["url"])
    got = _datas(spec)
    return resolve(rel, got[0]["url"]) if got else None


def data_url(base, path):
    return "%s/data?path=%s" % (base, urllib.parse.quote(path))


def theme(mode="light"):
    """A Vega-Lite ``config`` in the dash's look (``mode``: light or dark)."""
    ink, muted, line, panel = INK[mode]
    font = "system-ui, -apple-system, Segoe UI, sans-serif"
    axis = {"labelColor": muted, "titleColor": ink, "gridColor": line, "domainColor": line,
            "tickColor": line, "labelFont": font, "titleFont": font, "titleFontWeight": 600}
    return {
        "background": panel,
        "font": font,
        "view": {"stroke": "transparent"},
        "range": {"category": PALETTE[mode]},
        "mark": {"color": PALETTE[mode][0]},
        "bar": {"color": PALETTE[mode][0], "cornerRadiusEnd": 2},
        "line": {"strokeWidth": 2},
        "point": {"filled": True, "size": 40},
        "axis": axis,
        "axisX": {"grid": False},
        "legend": {"labelColor": muted, "titleColor": ink, "labelFont": font,
                   "titleFont": font},
        "title": {"color": ink, "font": font, "fontSize": 14, "fontWeight": 600,
                  "anchor": "start"},
        "header": {"labelColor": muted, "titleColor": ink},
    }


def summary(spec):
    """The spec panel's fields: mark, x/y/color field and type, title (None
    for a spec the panel does not edit: layers, concatenation, facets)."""
    if any(k in spec for k in VIEWS if k != "mark") or "mark" not in spec:
        return None
    m = spec["mark"]
    enc = spec.get("encoding") or {}
    out = {"mark": m.get("type") if isinstance(m, dict) else m,
           "title": spec.get("title") if isinstance(spec.get("title"), str) else ""}
    for ch in ("x", "y", "color"):
        e = enc.get(ch) or {}
        out[ch] = {"field": e.get("field") or "", "type": e.get("type") or "",
                   "aggregate": e.get("aggregate") or ""}
    return out


def apply(spec, panel):
    """``spec`` with the spec panel's fields set (``summary``'s shape)."""
    s = copy.deepcopy(spec)
    mark = panel.get("mark")
    if mark:
        if mark not in MARKS:
            raise ChartError("unknown mark %r" % mark)
        if isinstance(s.get("mark"), dict):
            s["mark"]["type"] = mark
        else:
            s["mark"] = mark
    if "title" in panel:
        if panel["title"]:
            s["title"] = str(panel["title"])
        else:
            s.pop("title", None)
    enc = s.setdefault("encoding", {})
    for ch in ("x", "y", "color"):
        f = panel.get(ch)
        if not isinstance(f, dict):
            continue
        if not f.get("field") and not f.get("aggregate"):
            enc.pop(ch, None)
            continue
        e = dict(enc.get(ch) or {})
        for k in ("field", "type", "aggregate"):
            if f.get(k):
                e[k] = str(f[k])
            else:
                e.pop(k, None)
        if e.get("type") not in (None, "quantitative", "nominal", "ordinal", "temporal"):
            raise ChartError("unknown type %r" % e["type"])
        enc[ch] = e
    return s
