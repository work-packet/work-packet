"""E7: ``prototype/sub`` with the real ``claude -p`` (Haiku). By hand only:

    WPK_LIVE=1 pytest -m live -s

Each run costs a few cents. Nothing here runs in CI.
"""

import json
import os

import pytest

from work_packet import project, registry, scheduler
from work_packet.check import check
from work_packet.packet import Packet

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("WPK_LIVE") != "1", reason="set WPK_LIVE=1"),
]

PROMPT = """\
If state/count.md exists, read the count; otherwise the count is zero.
Add one to the count and write it to state/count.md.
While the count is below 8, continue with this same instruction in the next step.
When the count reaches 8, spawn one child named hello whose instruction is to
write "Hello World" to state/p.md and finish, and mark this task done.
"""


def step_table(pdir):
    """Per-step cost and context (docs/context.md C1), printed for the status log."""
    print("  packet   step  carried  cost     calls  first   peak    write   read")
    for w in sorted(os.listdir(pdir)):
        steps = os.path.join(pdir, w, "steps")
        for n in sorted(os.listdir(steps)):
            if "." in n:
                continue
            with open(os.path.join(steps, n, "meta.json")) as fp:
                m = json.load(fp)
            c, t = m.get("context") or {}, m.get("tokens") or {}
            print("  %s %4s  %-7s  $%.4f  %5s  %6s  %6s  %6s  %6s" % (
                w[:8], n, "yes" if m.get("carried_from") else "", m.get("cost_usd") or 0,
                c.get("calls"), c.get("first"), c.get("peak"),
                t.get("cache_creation_input_tokens"), t.get("cache_read_input_tokens")))


@pytest.mark.parametrize("run", [1, 2, 3, "carry"])
def test_e7_prototype_sub_live(tmp_path, monkeypatch, run):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    if run == "carry":
        os.makedirs(str(tmp_path / "home"))
        (tmp_path / "home" / "config.toml").write_text("carry_session = true\n")
    monkeypatch.delenv("WPK_NOW", raising=False)
    monkeypatch.delenv("WPK_CLAUDE", raising=False)
    plan = project.new("live-sub", PROMPT, path=str(tmp_path / "live-sub"), tz="UTC")
    res = scheduler.tick(registry.entries(), jobs=1, until_idle=True, max_steps=20,
                         report=lambda r: print("  %s %s" % (r.due.wpid[:8], r.msg)))
    pdir = os.path.join(plan.path, "packets")
    root = Packet(os.path.join(pdir, plan.root))
    meta, _ = root.load_status()
    cost = sum(r.get("cost_usd", 0) for w in os.listdir(pdir)
               for r in Packet(os.path.join(pdir, w)).journal().records
               if r["type"] == "commit-end")
    step_table(pdir)
    print("run %s: %d steps, $%.4f, project kept at %s" % (run, len(res.ran), cost, plan.path))
    assert meta["state"] == "COMPLETED", meta
    assert open(os.path.join(root.state_dir, "count.md")).read().strip() == "8"
    assert len(meta["children"]) == 1
    child = Packet(os.path.join(pdir, meta["children"][0]))
    assert child.load_status()[0]["state"] == "COMPLETED"
    assert open(os.path.join(child.state_dir, "p.md")).read().strip() == "Hello World"
    assert sorted(os.listdir(pdir)) == sorted([plan.root, child.wpid])
    assert check(plan.path).issues == []
