"""Time what `wpk serve` does over and over, on the real home (docs/cpu-plan.md P0).

    packages/python/bin/python scripts/cpu_probe.py [-n 5]

Prints, per piece, the first (cold) and the best of ``n`` (warm) times. Read-only:
it builds what the pages and the scheduler build, and writes nothing.
"""

import argparse
import time


def timed(fn, n):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return out[0], min(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=5)
    a = ap.parse_args()
    from work_packet import archived, registry, scheduler
    from work_packet.dash import data, tokens
    from work_packet.sched import jobs

    ents = registry.entries()
    cols, _ = data.board()
    side = [b["name"] for b in registry.boards()]
    rows = [
        ("data.board", lambda: data.board()),
        ("tokens.board (7 days)", lambda: tokens.board(archived.entries(), days=7, on=side)),
        ("registry.entries", registry.entries),
        ("scheduler.next_wake", lambda: scheduler.next_wake(ents)),
        ("scheduler.due", lambda: scheduler.due(ents)),
        ("jobs.all", jobs.all),
    ]
    print("%d cards, %d projects, %d repeats" % (sum(len(v) for v in cols.values()),
                                                  len(ents), a.n))
    print("%-24s %10s %10s" % ("", "cold ms", "warm ms"))
    for name, fn in rows:
        try:
            cold, warm = timed(fn, a.n)
        except Exception as e:                  # noqa: BLE001: report and go on
            print("%-24s %s" % (name, e))
            continue
        print("%-24s %10.1f %10.1f" % (name, cold * 1e3, warm * 1e3))


if __name__ == "__main__":
    main()
