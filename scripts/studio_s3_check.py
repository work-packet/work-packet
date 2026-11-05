"""The S3 exit check (docs/studio-plan.md §8) with the real model, scripted.

Worked example 1, complete: the nightly regression from the S2 check; three
charts tried, two kept (pinned, their version marked Keep) and one dropped; a
one-page document; a change to a chart, so two versions of it can be flipped
(their renders differ); and a chart given a title far too long, which the
agent should catch by looking at its render (``wpk studio look``) and fix
without being told. Use ``--model sonnet``.

    python scripts/studio_s3_check.py [--dir DIR] [--model sonnet] [--shot out.png]
"""

import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _studio_board import Board  # noqa: E402
from studio_s2_check import nightly  # noqa: E402

LONG = ("Nightly regression flip counts per test across thirty nights of the UART, SPI, "
        "I2C, DMA, GPIO, timer and PLL suites, showing which tests are flakiest and should "
        "be looked at first by the verification team")


def wait_renders(b, timeout=120):
    """Until every render the versions name is made; the versions."""
    end = time.time() + timeout
    while time.time() < end:
        vs = b.versions()
        if all(c["ready"] for v in vs for c in v["changed"] if c["key"]):
            return vs
        time.sleep(1)
    return b.versions()


def key_at(vs, n, path):
    """The render key of ``path`` as it was at version ``n``."""
    k = None
    for v in vs:
        if v["n"] > n:
            break
        for c in v["changed"]:
            if c["path"] == path:
                k = c["key"]
    return k


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="scratch folder (default: a new temp dir)")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--shot", help="where to write the studio screenshot (PNG)")
    a = ap.parse_args(argv)
    shot = os.path.abspath(a.shot) if a.shot else None
    b = Board(a.dir or tempfile.mkdtemp(prefix="wpk-s3-"), a.model, "s3check",
              "Find the flaky tests in the nightly regression (data/nightly.csv) and write "
              "up what to look at first.")
    csv, flips = nightly()
    b.write("data/nightly.csv", csv)
    check = b.check
    check(b.renders.available() is None, "the renderer is available (%s)"
          % (b.renders.available() or "on"))
    b.open()
    vs = b.versions()
    check(len(vs) == 1 and vs[0]["note"] == "at open", "a version of the folder at open")

    # 1. Three charts tried.
    got = b.ask("Try three charts of how flaky each test is in data/nightly.csv: "
                "charts/flips-bar.vl.json (flips per test, as bars), charts/flips-dots.vl.json "
                "(the same as a dot plot) and charts/fail-heatmap.vl.json (failures by night "
                "and test). Use saved queries for the data.")
    charts = ["charts/flips-bar.vl.json", "charts/flips-dots.vl.json",
              "charts/fail-heatmap.vl.json"]
    check(all(os.path.isfile(os.path.join(b.folder, c)) for c in charts), "three charts written")
    check("wpk studio look" in b.tools(got), "the agent looked at what it made")
    vs = wait_renders(b)
    tried = vs[-1]
    check(tried["by"] == "agent" and all(c in [x["path"] for x in tried["changed"]]
                                         for c in charts), "a version with the three charts")
    check(all(x["ready"] for x in tried["changed"] if x["key"]),
          "their renders are made (thumbnails for the strip)")
    for x in tried["changed"]:
        if x["checks"]:
            print("    flagged %s: %s" % (x["path"], x["checks"]))

    # 2. Two kept, one dropped.
    for c in charts[:2]:
        b.post("/pin", {"path": c})
    st, j = b.post("/keep", {"n": tried["n"], "keep": True})
    check(st == 200 and j["version"]["keep"], "the version with the charts is marked Keep")
    b.ask("Drop the heatmap: delete charts/fail-heatmap.vl.json (and its query if nothing "
          "else uses it).")
    check(not os.path.exists(os.path.join(b.folder, charts[2])), "the heatmap is gone")
    vs = b.versions()
    check(charts[2] in vs[-1]["deleted"], "its deletion is a version")

    # 3. A change, then flip between the two versions of the chart.
    before = vs[-1]["n"]
    b.ask("In charts/flips-bar.vl.json, colour the bars by whether the test flipped more "
          "than 10 times.")
    vs = wait_renders(b)
    after = vs[-1]["n"]
    k1, k2 = key_at(vs, before, charts[0]), key_at(vs, after, charts[0])
    check(after > before and k1 and k2 and k1 != k2,
          "two versions of the bar chart to flip between (v%d, v%d)" % (before, after))
    if k1 and k2:
        r1 = b.get("/render/%s/full.png" % k1)
        r2 = b.get("/render/%s/full.png" % k2)
        check(r1.status_code == 200 and r2.status_code == 200 and r1.content != r2.content,
              "their pictures differ")

    # 4. A one-page document.
    b.ask("Write a one-page findings document, docs/findings.md: which tests to look at "
          "first and why, with the flip counts, and point to the two charts.")
    doc = os.path.join(b.folder, "docs", "findings.md")
    check(os.path.isfile(doc), "docs/findings.md written")
    b.post("/pin", {"path": "docs/findings.md"})

    # 5. The overflowing title, caught by looking.
    got = b.ask('Set the title of charts/flips-dots.vl.json to "%s".' % LONG)
    tools, say = b.tools(got), b.says(got)
    check("wpk studio look" in tools and "flips-dots" in tools,
          "the agent looked at the chart after changing it")
    spec = json.load(open(os.path.join(b.folder, charts[1])))
    title = spec.get("title")
    as_given = title == LONG or (isinstance(title, dict) and title.get("text") == LONG
                                 and not title.get("limit"))
    vs = wait_renders(b)
    k = key_at(vs, vs[-1]["n"], charts[1])
    from work_packet.studio import renders
    inf = renders.info(b.e, b.pkt.wpid, k) if k else None
    flags = [c for c in (inf or {}).get("checks", []) if c["check"] in ("overflow", "clipped-text")]
    print("    title now: %s" % json.dumps(title)[:300])
    print("    the agent said: %s" % say[:500].replace("\n", " "))
    fixed = not as_given and not flags
    named = any(w in say.lower() for w in ("clip", "overflow", "cut off", "runs off",
                                           "too long", "doesn't fit", "does not fit"))
    check(fixed or named, "the agent caught the long title by looking (%s)" % (
        "fixed it" if fixed else "reported it" if named else "missed it: %s" % flags))

    # 6. The strip, a screenshot, close.
    b.post("/layout", {"mode": "two-up", "open": [charts[0], "docs/findings.md"]})
    if shot:
        b.shot(shot)
    b.close()
    return b.finish()


if __name__ == "__main__":
    sys.exit(main())
