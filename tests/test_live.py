"""E7: ``prototype/sub`` with the real ``claude -p`` (Haiku). By hand only:

    WPK_LIVE=1 pytest -m live -s

Each run costs a few cents. Nothing here runs in CI.
"""

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


@pytest.mark.parametrize("run", [1, 2, 3])
def test_e7_prototype_sub_live(tmp_path, monkeypatch, run):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
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
    print("run %d: %d steps, $%.4f, project kept at %s" % (run, len(res.ran), cost, plan.path))
    assert meta["state"] == "COMPLETED", meta
    assert open(os.path.join(root.state_dir, "count.md")).read().strip() == "8"
    assert len(meta["children"]) == 1
    child = Packet(os.path.join(pdir, meta["children"][0]))
    assert child.load_status()[0]["state"] == "COMPLETED"
    assert open(os.path.join(child.state_dir, "p.md")).read().strip() == "Hello World"
    assert sorted(os.listdir(pdir)) == sorted([plan.root, child.wpid])
    assert check(plan.path).issues == []
