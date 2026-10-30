"""The S1 exit check (docs/studio-plan.md §6) with the real model, scripted.

A board on a scratch home (``_studio_board.Board``), a project with some
test-run notes, and the real ``claude`` (the packet's model, haiku by
default; sonnet for the content to be right). It opens a studio, asks for a
findings document, comments on a sentence through the markup route, asks the
agent to resolve it, edits the file from outside (as VS Code would),
screenshots the studio, closes with the drafted summary, and checks the
recorded step. Prints what it saw; exits 1 on a failed check.

    python scripts/studio_s1_check.py [--dir DIR] [--model haiku] [--shot out.png]
"""

import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _studio_board import Board  # noqa: E402

RUNS = """\
nightly 2026-10-20: uart_tx_basic PASS, uart_rx_overrun FAIL (timeout 50us), spi_loop PASS
nightly 2026-10-21: uart_tx_basic PASS, uart_rx_overrun PASS, spi_loop PASS
nightly 2026-10-22: uart_tx_basic FAIL (seed 81122, parity mismatch), uart_rx_overrun FAIL (timeout 50us), spi_loop PASS
nightly 2026-10-23: uart_tx_basic PASS, uart_rx_overrun FAIL (timeout 50us), spi_loop PASS
nightly 2026-10-24: uart_tx_basic PASS, uart_rx_overrun PASS, spi_loop PASS
nightly 2026-10-25: uart_tx_basic PASS, uart_rx_overrun FAIL (timeout 50us), spi_loop PASS
nightly 2026-10-26: uart_tx_basic PASS, uart_rx_overrun FAIL (timeout 50us), spi_loop FAIL (license)
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="scratch folder (default: a new temp dir)")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--shot", help="where to write the studio screenshot (PNG)")
    a = ap.parse_args(argv)
    shot = os.path.abspath(a.shot) if a.shot else None
    b = Board(a.dir or tempfile.mkdtemp(prefix="wpk-s1-"), a.model, "s1check",
              "Find out why the UART tests are flaky; the nightly results are in "
              "notes/runs.txt.")
    b.write("notes/runs.txt", RUNS)
    check = b.check

    # 1. Open.
    b.open()
    check(b.pkt.load_status()[0].get("taken_by") == "me", "the packet is taken (IN STUDIO)")

    # 2. A findings document.
    got = b.ask("Write a one-page findings document at docs/findings.md from notes/runs.txt: "
                "which tests are flaky, how often, and what to look at next.")
    path = os.path.join(b.folder, "docs", "findings.md")
    check(os.path.exists(path), "docs/findings.md written")
    outs = [x for x in got if x.get("k") == "output"]
    check(any(f["path"] == "docs/findings.md" for o in outs for f in o["files"]),
          "an output card for docs/findings.md")
    if not os.path.exists(path):
        return b.finish()

    # 3. It renders on the canvas.
    st, j = b.post("/pin", {"path": "docs/findings.md"})
    check(st == 200, "pin it")
    b.post("/layout", {"open": ["docs/findings.md"]})
    r = b.get("/frame/doc", path="docs/findings.md")
    check(r.status_code == 200 and "<h1" in r.text, "the document renders in its frame")

    # 4. Comment on a sentence (as the markup UI would post it: the block's
    # source lines, 0-based and end-exclusive, as markdown-it maps them).
    lines = open(path).read().split("\n")
    i = next(k for k, ln in enumerate(lines) if ln.strip() and not ln.startswith("#")
             and not ln.startswith(("-", "*", "|", ">")) and len(ln.split()) > 4)
    sel = " ".join(lines[i].split()[:4])
    sha = r.text.split('data-sha="')[1].split('"')[0]
    st, j = b.post("/markup", {"path": "docs/findings.md", "sha": sha, "op": "comment",
                               "lines": "%d-%d" % (i, i + 1), "sel": sel, "at": 0,
                               "text": "Give the exact number of failures for each test here."})
    check(st == 200, "comment on %r (line %d) %s" % (sel, i + 1, "" if st == 200 else j))
    check("{>>" in open(path).read(), "the comment is in the file")

    # 5. The agent resolves it.
    b.ask("Resolve the comments in docs/findings.md: make the change each asks for, then "
          "remove the comment markup.")
    text = open(path).read()
    check("{>>" not in text, "the comment is resolved (no {>> <<} left)")
    check(any(ch.isdigit() for ch in text), "the document has the counts")

    # 6. An outside edit (VS Code) shows on the canvas.
    n = len(b.events)
    with open(path, "a") as fp:
        fp.write("\nEdited outside the studio.\n")
    end, ch = time.time() + 10, None
    while time.time() < end and ch is None:
        ch = next((x for x in b.events[n:] if x.get("k") == "changed"
                   and x.get("path") == "docs/findings.md"), None)
        time.sleep(0.2)
    check(ch is not None and ch.get("by") == "outside",
          "a changed event for the outside edit (by %s)" % (ch or {}).get("by"))

    # 7. Screenshot, then close.
    if shot:
        b.shot(shot)
    b.close()
    return b.finish()


if __name__ == "__main__":
    sys.exit(main())
