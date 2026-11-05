"""The dash's vendored JavaScript (docs/studio-v2.md §7): what
``tools/vendor/build.mjs`` wrote under ``dash/vendor/<lib>/``, served by
``vendor/manifest.json`` (only the files it lists, with long cache headers and
the sha as the ETag). Too many files for ``app.STATIC``: Excalidraw's chunks
and fonts alone are ~200.

``dash/vendor/`` is build output, not committed: in a fresh checkout nothing
is built until ``ivpm update`` and ``node tools/vendor/build.mjs`` run, and
pages that need a library say so (``NOT_BUILT``) instead of failing.
"""

import functools
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "vendor")
MANIFEST = os.path.join(ROOT, "manifest.json")
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
         ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf",
         ".txt": "text/plain; charset=utf-8", ".json": "application/json",
         ".png": "image/png", ".svg": "image/svg+xml", ".wasm": "application/wasm"}
CACHE = "public, max-age=604800"
NOT_BUILT = ("the board's JavaScript is not built: run `ivpm update` and "
             "`node tools/vendor/build.mjs` in the wpk checkout")


@functools.lru_cache(maxsize=1)
def manifest(path=MANIFEST):
    """``{versions, budget, files: {path: {sha256, size}}}``; empty when not built."""
    try:
        with open(path, encoding="utf-8") as fp:
            m = json.load(fp)
    except (OSError, ValueError):
        return {"versions": {}, "budget": {}, "files": {}}
    m.setdefault("files", {})
    return m


def media_type(rel):
    return TYPES.get(os.path.splitext(rel)[1].lower())


def lookup(rel, m=None):
    """``(file path, media type, sha256)`` for a manifest path, else None."""
    m = m or manifest()
    ent = m["files"].get(rel)
    mt = media_type(rel)
    if ent is None or mt is None:
        return None
    return os.path.join(ROOT, *rel.split("/")), mt, ent["sha256"]


def built(lib, m=None):
    """True when ``lib`` (vega, draw, codemirror, term) is in the manifest."""
    return lib in libs(m)


def libs(m=None):
    m = m or manifest()
    return sorted({p.split("/", 1)[0] for p in m["files"]})


def sizes(m=None):
    """{lib: bytes} from the manifest."""
    out = {}
    for p, ent in (m or manifest())["files"].items():
        lib = p.split("/", 1)[0]
        out[lib] = out.get(lib, 0) + ent["size"]
    return out


def check(m=None, root=ROOT):
    """Problems with the built files: listed but missing or changed, there but
    not listed (a half-done rebuild), a type the dash cannot serve, or a
    library above its size budget (a warning). [(level, message)]."""
    m = m or manifest()
    out = []
    for rel, ent in sorted(m["files"].items()):
        if media_type(rel) is None:
            out.append(("error", "%s: no media type for it" % rel))
        p = os.path.join(root, *rel.split("/"))
        try:
            with open(p, "rb") as fp:
                sha = hashlib.sha256(fp.read()).hexdigest()
        except OSError:
            out.append(("error", "%s: listed but missing" % rel))
            continue
        if sha != ent["sha256"]:
            out.append(("error", "%s: changed since the manifest was written" % rel))
    for lib in libs(m):
        for dirpath, _, names in os.walk(os.path.join(root, lib)):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), root).replace(os.sep, "/")
                if rel not in m["files"]:
                    out.append(("error", "%s: not in the manifest" % rel))
    for lib, n in sorted(sizes(m).items()):
        cap = (m.get("budget") or {}).get(lib)
        if cap and n > cap:
            out.append(("warning", "%s: %d bytes, above its budget of %d" % (lib, n, cap)))
    return out
