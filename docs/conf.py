# Sphinx configuration for the work-packet site, published at
# https://dvkit.org/work-packet/work-packet/ by .forgejo/workflows/docs.yml.
#
# docs/ is mostly design notes and build plans, which are not published. Only
# the pages in include_patterns are part of the site: add a page there and to
# the toctree in index.md together.

import os
import re
import sys

project = "work-packet"
author = "Matthew Ballance"
copyright = "2026, Matthew Ballance"

_about = open(os.path.join(os.path.dirname(__file__), "..", "src",
                           "work_packet", "__about__.py")).read()
release = ".".join(re.search(r"^version_info = \((.*)\)$", _about, re.M)
                   .group(1).replace(" ", "").split(","))
version = release

extensions = ["myst_parser"]
source_suffix = {".md": "markdown"}

include_patterns = [
    "index.md",
    "collaboration-guide.md",
    "sched-guide.md",
    "studio-guide.md",
    "writing-a-starter.md",
    "spec.md",
]
exclude_patterns = ["_build"]

myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

html_theme = "furo"
html_title = "work-packet " + release
