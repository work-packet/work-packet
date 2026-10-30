"""The S2 exit check (docs/studio-plan.md §7) with the real model, scripted.

Worked example 1, part one: a regression CSV (30 nights x 12 tests, made here
with known flip counts), "which tests flip most?", a saved query (a table) and
a chart from the agent, a selection on the chart asked about (the rows go with
the question), both pinned, a screenshot, close. The answer is checked
against the counts. Use ``--model sonnet``: this is a hard case.

    python scripts/studio_s2_check.py [--dir DIR] [--model sonnet] [--shot out.png]
"""

import argparse
import datetime
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _studio_board import Board  # noqa: E402

TESTS = ["uart_tx_basic", "uart_rx_overrun", "uart_parity", "spi_loop", "spi_cs_glitch",
         "i2c_ack", "i2c_clock_stretch", "dma_burst", "dma_abort", "gpio_irq", "timer_wrap",
         "pll_lock"]
FLAKY = {"uart_rx_overrun": 0.45, "i2c_clock_stretch": 0.35, "dma_abort": 0.25,
         "spi_cs_glitch": 0.12, "timer_wrap": 0.05}


def nightly(nights=30, seed=1):
    """CSV text and {test: flips} (a flip: the status differs from the night before)."""
    rnd = random.Random(seed)
    day = datetime.date(2026, 9, 28)
    rows, last, flips = ["night,test,status,duration_s"], {}, {t: 0 for t in TESTS}
    for n in range(nights):
        d = day + datetime.timedelta(days=n)
        for t in TESTS:
            s = "FAIL" if rnd.random() < FLAKY.get(t, 0.0) else "PASS"
            if t in last and last[t] != s:
                flips[t] += 1
            last[t] = s
            rows.append("%s,%s,%s,%.1f" % (d.isoformat(), t, s, 20 + rnd.random() * 40))
    return "\n".join(rows) + "\n", flips


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="scratch folder (default: a new temp dir)")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--shot", help="where to write the studio screenshot (PNG)")
    a = ap.parse_args(argv)
    shot = os.path.abspath(a.shot) if a.shot else None
    b = Board(a.dir or tempfile.mkdtemp(prefix="wpk-s2-"), a.model, "s2check",
              "Find the flaky tests in the nightly regression (data/nightly.csv).")
    csv, flips = nightly()
    b.write("data/nightly.csv", csv)
    want = sorted(flips.items(), key=lambda kv: -kv[1])
    print("    expected flips:", ", ".join("%s %d" % kv for kv in want[:5]))
    check = b.check
    b.open()

    # 1. The question: a saved query and a chart.
    got = b.ask("Which tests flip most between PASS and FAIL from one night to the next in "
                "data/nightly.csv? Save the query as queries/flips.sql (one row per test, "
                "with its flip count, most first) and make a bar chart of it in "
                "charts/flips.vl.json that I can select bars on. Then tell me the top three.")
    tools = " ".join((x.get("what") or "") for x in got if x.get("k") == "tool")
    check("wpk studio query" in tools or "wpk studio exec" in tools,
          "the agent used the kernel (wpk studio query/exec)")
    say = " ".join(x.get("text") or "" for x in got if x.get("k") == "say")
    top3 = [t for t, _ in want[:3]]
    check(all(t in say for t in top3), "the reply names the top three (%s)" % ", ".join(top3))
    outs = {f["path"]: f for o in got if o.get("k") == "output" for f in o["files"]}
    check(outs.get("queries/flips.sql", {}).get("kind") == "table",
          "an output card for queries/flips.sql (a table)")
    check(outs.get("charts/flips.vl.json", {}).get("kind") == "chart",
          "an output card for charts/flips.vl.json (a chart)")

    # 2. The saved query as a table: the counts are right.
    r = b.get("/table", path="queries/flips.sql", limit=50)
    ok = check(r.status_code == 200, "queries/flips.sql runs as a table %s"
               % ("" if r.status_code == 200 else r.text[:200]))
    if ok:
        t = r.json()
        names = [c["name"] for c in t["columns"]]
        print("    table:", names, t["rows"][:4])
        rows = {next(v for v in row if isinstance(v, str)): next(
            (v for v in row if isinstance(v, (int, float)) and not isinstance(v, bool)), None)
            for row in t["rows"] if any(isinstance(v, str) for v in row)}
        check(all(rows.get(k) == v for k, v in want[:5]),
              "the flip counts match (top five: %s)" % {k: rows.get(k) for k, _ in want[:5]})
        first = next(v for v in t["rows"][0] if isinstance(v, str))
        check(first == want[0][0], "most first (%s)" % first)

    # 3. The chart draws, with a selection.
    r = b.get("/frame/chart", path="charts/flips.vl.json")
    check(r.status_code == 200 and "can't be drawn" not in r.text,
          "the chart can be drawn %s" % ("" if "can't be drawn" not in r.text else
                                          r.text.split("<ul>")[1].split("</ul>")[0][:300]))
    spec = {}
    try:
        spec = json.load(open(os.path.join(b.folder, "charts", "flips.vl.json")))
    except (OSError, ValueError):
        pass
    sels = [p for p in json.dumps(spec).split('"select"')[1:]]
    check(bool(sels), "the chart has a selection")
    b.post("/pin", {"path": "charts/flips.vl.json"})
    b.post("/pin", {"path": "queries/flips.sql"})
    b.post("/layout", {"mode": "two-up", "open": ["charts/flips.vl.json", "queries/flips.sql"]})
    if shot:
        b.shot(shot)

    # 4. Select the top two bars and ask about them.
    params = [p for p in spec.get("params", []) if isinstance(p, dict) and p.get("select")]
    enc = spec.get("encoding") or {}
    test_field = next((e.get("field") for e in enc.values() if isinstance(e, dict)
                       and e.get("type") in ("nominal", "ordinal")), None)
    if params and test_field:
        # The board turns any selection into rows the same way: the two top bars.
        sel = {"kind": "point", test_field: top3[:2]}
        got = b.ask("", path="/select", body={"path": "charts/flips.vl.json", "selection": sel,
                                              "text": "On which nights did these two flip? "
                                                      "Is there a pattern?"})
        from work_packet.studio import model
        cid = model.state(b.e, b.pkt.wpid)["session"]["conv"]
        asked = [x["text"] for x in b.agents.transcript(cid) if x["k"] == "ask"][-1]
        check(top3[0] in asked and "row" in asked and "|" in asked,
              "the question went with the selected rows")
        say = " ".join(x.get("text") or "" for x in got if x.get("k") == "say")
        check(any(x.get("k") == "end" and x.get("ok") for x in got), "the selection's turn ends ok")
        check(top3[0] in say or top3[1] in say, "the answer is about the selected tests")
    else:
        check(False, "a selection on the test field to ask about")

    b.close()
    return b.finish()


if __name__ == "__main__":
    sys.exit(main())
