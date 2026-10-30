"""Artifact kinds (docs/interactive-tasks.md §4, docs/studio-plan.md S1.2).

A kind says which files it is (``patterns``, matched on the name), which
viewer shows it, what a comment's ``where`` looks like (``anchor``), how it is
rendered for thumbnails (``render``) and what it exports to. The registry is
ordered: the first kind whose pattern matches wins, so a longer pattern
(``*.vl.json``) is registered before a shorter one that also matches
(``*.json``).
"""

import fnmatch
import os
from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class Kind:
    name: str
    patterns: Tuple[str, ...]
    viewer: str                      # the viewer module in dash/viewers/
    anchor: str = "region"           # the shape of a comment's ``where`` (S4.1)
    render: str = "page"             # how a thumbnail is made: page, image, none
    exports: Tuple[str, ...] = field(default_factory=tuple)
    icon: str = "file"

    def matches(self, path):
        name = os.path.basename(path).lower()
        return any(fnmatch.fnmatchcase(name, p) for p in self.patterns)


REGISTRY = []


def register(kind, before=None):
    """Add ``kind``; ``before``: the name of a kind it must be tried ahead of."""
    if any(k.name == kind.name for k in REGISTRY):
        raise ValueError("kind %s is registered already" % kind.name)
    if before is not None:
        i = [k.name for k in REGISTRY].index(before)
        REGISTRY.insert(i, kind)
    else:
        REGISTRY.append(kind)
    return kind


def get(name):
    for k in REGISTRY:
        if k.name == name:
            return k
    return None


def kind_of(path):
    """The kind of ``path``, or None for a file the studio has no viewer for."""
    for k in REGISTRY:
        if k.matches(path):
            return k
    return None


# S1: documents and images. Later phases add diagram, sketch, deck, page.
register(Kind("document", ("*.md", "*.markdown"), viewer="doc", anchor="text",
              render="page", exports=("html", "pdf", "docx"), icon="doc"))
register(Kind("image", ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg"),
              viewer="image", anchor="region", render="image", icon="image"))
# S2: charts (Vega-Lite) and tables (files DuckDB reads, SQLite, saved queries).
register(Kind("chart", ("*.vl.json",), viewer="chart", anchor="selection", render="page",
              exports=("svg", "png"), icon="chart"))
register(Kind("table", ("*.csv", "*.tsv", "*.parquet", "*.jsonl", "*.ndjson", "*.sql",
                        "*.sqlite", "*.sqlite3", "*.db"),
              viewer="table", anchor="cells", render="none", exports=("csv", "md"),
              icon="table"))
