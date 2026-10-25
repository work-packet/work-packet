"""wpk stats (docs/harness.md H4): figures, the short-step rule and advice."""

import json
import os

from conftest import make_project
from test_executor import set_project
from work_packet import executor, stats
from work_packet.cli import main

KEY = dict(project="p", wpid="w", harness="claude", model="m", profile="x@1")


def step(n, **kw):
    d = dict(KEY, step=n, attempt=1, failed=False, calls=5, base=10000, peak=12000,
             cost=0.02, output_tokens=1000, resume="now", diff_lines=10)
    d.update(kw)
    return stats.Step(**d)


def group(steps):
    return stats.groups(steps, [])[0]


def test_short_rule():
    assert stats.is_short(step(1, calls=3, diff_lines=2))
    assert not stats.is_short(step(1, calls=4, diff_lines=2))
    assert not stats.is_short(step(1, calls=2, diff_lines=9))
    assert not stats.is_short(step(1, calls=2, diff_lines=2, resume="in 1 hours"))
    assert not stats.is_short(step(1, calls=2, diff_lines=2, failed=True))


def test_no_advice_below_minimum():
    g = group([step(i, calls=2, diff_lines=0) for i in range(10)])
    assert g.figures()["short_rate"] == 1.0
    assert g.advice(min_steps=30) == []
    assert "needs 30 steps" in "\n".join(stats.report([g]))


def test_stops_early():
    g = group([step(i, calls=2, diff_lines=0) for i in range(20)] +
              [step(i) for i in range(20, 30)])
    (adv,) = g.advice()
    assert adv.startswith("Stops early: 67%") and "persistent" in adv


def test_runs_long_and_retries():
    ss = [step(i, hook=("soft",) if i < 10 else ()) for i in range(30)]
    ss += [step(i, failed=True, hook=("soft", "hard")) for i in range(5)]
    adv = group(ss).advice()
    assert any(a.startswith("Steps run long: the context hook fired on 33% of steps (5 hard)")
               for a in adv)
    assert any(a.startswith("14% of attempts failed") for a in adv)


def carried_e7(extra_factor=None):
    """E7's measured costs: fresh about $0.021; carried rises with peak/base."""
    ss = [step(i, cost=0.021) for i in range(25)]
    for i, (x, c) in enumerate([(1.31, 0.0117), (1.46, 0.0115), (1.60, 0.0119), (1.75, 0.0124),
                                (1.89, 0.0129), (2.03, 0.0133), (2.18, 0.0146)]):
        ss.append(step(100 + i, carried=True, peak=int(10000 * x), cost=c))
    if extra_factor:
        ss.append(step(200, carried=True, peak=int(10000 * extra_factor), cost=0.03))
    return group(ss)


def test_break_even_from_carried_costs():
    f = carried_e7().figures()
    assert 3.5 < f["break_even_factor"] < 5.0
    assert f["carried_n"] == 7 and f["cost_fresh_median"] == 0.021


def test_lower_carry_factor_when_carried_steps_cost_more():
    g = carried_e7(extra_factor=6.0)
    be = g.figures()["break_even_factor"]
    (adv,) = g.advice()
    assert adv.startswith("Carried steps above %.1fx base cost more" % be)


def test_report_and_json_via_cli(tmp_path, fake, capsys):
    proj, root = make_project(tmp_path)
    set_project(proj, carry_session=True)
    for _ in range(3):
        executor.step(proj)
    assert main(["stats", proj, "--json"]) == 0
    (g,) = json.loads(capsys.readouterr().out)
    assert (g["harness"], g["profile"]) == ("claude", "claude-haiku@1")
    f = g["figures"]
    assert f["steps"] == 3 and f["carried_n"] == 2 and f["calls_median"] == 2
    assert main(["stats", proj]) == 0
    out = capsys.readouterr().out
    assert out.startswith("claude / claude-haiku-4-5-20251001 / claude-haiku@1")
    assert main(["stats", str(tmp_path / "nope")]) != 0
    assert main(["stats", proj, "--since", "1x"]) != 0


def test_token_rollups():
    ss = [step(1, input_tokens=10, cache_write=90, cache_read=900, output_tokens=100,
               thinking_tokens=40, cost=1.0, end="2026-10-22T10:00:00Z"),
          step(2, input_tokens=10, cache_write=90, cache_read=900, output_tokens=100,
               thinking_tokens=60, cost=1.0, end="2026-10-23T10:00:00Z"),
          step(3, failed=True, attempt=1, input_tokens=0, cache_write=0, cache_read=1000,
               output_tokens=0, cost=0.5, end="2026-10-23T11:00:00Z", project="q")]
    f = stats.token_figures(ss)
    assert f["context_tokens"] == 3000 and abs(f["cache_hit"] - 2800 / 3000.0) < 1e-9
    assert f["thinking_share"] == 0.5 and abs(f["failed_share"] - 1 / 3.0) < 1e-9
    days = stats.rollup(ss, "day")
    assert [(k, n) for k, n, _ in days] == [("2026-10-22", 1), ("2026-10-23", 2)]
    assert [k for k, _, _ in stats.rollup(ss, "project")] == ["p", "q"]
    assert stats.rollup(ss, "step")[2][0] == "q/w/0003.1"
    assert "hit" in stats.rollup_report(days)[0]


def test_by_via_cli(tmp_path, fake, capsys):
    proj, root = make_project(tmp_path)
    executor.step(proj)
    assert main(["stats", proj, "--by", "packet", "--json"]) == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert row["steps"] == 1 and row["output_tokens"] == 120
    assert main(["stats", proj, "--by", "day"]) == 0
    assert "steps" in capsys.readouterr().out


def test_memento_item_is_tolerant():
    from work_packet import schema
    assert schema.memento_item({"item": " 2a "}) == "2a"
    assert schema.memento_item({"item": 3}) == "3"
    assert schema.memento_item({"item": ["1b", 2, None, {"x": 1}]}) == "1b, 2"
    for mm in ({}, {"item": None}, {"item": {"a": 1}}, {"item": True}, {"item": "  "}, None):
        assert schema.memento_item(mm) is None
    assert schema.validate_memento({"resume": "now", "item": "2a"}, "next") == []
    assert schema.validate_memento({"resume": "now", "item": {"odd": 1}}, "next") == []


def test_by_item_charges_failed_attempts_to_their_step(tmp_path):
    from work_packet.packet import Packet
    pkt = Packet(str(tmp_path / "w"))

    def put(name, memento=None, pending=None, cost=1.0):
        d = os.path.join(pkt.steps_dir, name)
        os.makedirs(d)
        with open(os.path.join(d, "meta.json"), "w") as fp:
            json.dump({"cost_usd": cost, "tokens": {"input_tokens": 10, "thinking_tokens": 0},
                       "context": {"calls": 1, "cache_breaks": 0}}, fp)
        for fn, item in (("result.md", memento), ("pending-memento.md", pending)):
            if item is not False:
                with open(os.path.join(d, fn), "w") as fp:
                    fp.write("---\nresume: now\n%s---\nnext\n"
                             % ("item: %s\n" % item if item else ""))
    put("0001", memento="1a", pending=False)
    put("0002.failed-1", memento=False, pending=False, cost=0.5)
    put("0002", memento="2a", pending=False)
    put("0003.failed-1", memento=False, pending="2b", cost=0.25)
    put("0003", memento=None, pending=False)                 # no item: tolerated
    ss = stats.packet_steps("p", pkt)
    assert [(s.step, s.failed, s.item) for s in ss] == [
        (1, False, "1a"), (2, False, "2a"), (2, True, "2a"), (3, False, None), (3, True, "2b")]
    rows = {k: (n, f["cost_usd"]) for k, n, f in stats.rollup(ss, "item")}
    assert rows == {"p/w 1a": (1, 1.0), "p/w 2a": (2, 1.5), "p/w 2b": (1, 0.25),
                    "p/w (no item)": (1, 1.0)}


def test_quota_used_and_latest():
    q = lambda f, l, r: {"seven_day": {"first": f, "last": l, "resets_at": r}}
    a = step(1, quota=q(0.30, 0.32, 2000), end="2026-10-24T10:00:00Z")
    b = step(2, quota=q(0.95, 0.01, 3000), end="2026-10-24T11:00:00Z")   # window reset
    c = step(3)
    assert abs(a.quota_used() - 0.02) < 1e-9
    assert b.quota_used() == 0.01
    assert c.quota_used() is None and a.quota_used("five_hour") is None
    assert abs(stats.token_figures([a, b, c])["quota_week"] - 0.03) < 1e-9
    assert stats.token_figures([c])["quota_week"] is None
    latest = stats.latest_quota([b, a, c], now=2500)["seven_day"]
    assert latest == {"used": 0.01, "resets_at": 3000, "at": b.end, "reset": False}
    assert stats.latest_quota([a], now=2500)["seven_day"]["reset"] is True
    assert stats.latest_quota([c]) == {}
