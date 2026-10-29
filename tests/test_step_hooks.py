"""Step hooks (design E4): start/finish/stop around the harness runs, facts in meta.ext."""
import importlib.metadata
import json
import os

import pytest

from conftest import make_project
from test_plugins import _EP
from work_packet import executor, harness, hooks

CALLS = []


class Recorder:
    """Points the run at a 'proxy' and reports a total per finish."""
    name = "rec"

    def start(self, ctx):
        CALLS.append(("start", ctx.step, ctx.attempt, ctx.harness, dict(ctx.config)))
        ctx.env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9999"

    def finish(self, ctx, res):
        CALLS.append(("finish", os.path.isdir(ctx.step_dir)))
        return {"calls": len([c for c in CALLS if c[0] == "finish"]), "usd": 0.5}

    def stop(self, ctx):
        CALLS.append(("stop",))


class Broken:
    def start(self, ctx):
        raise RuntimeError("proxy would not start")

    def finish(self, ctx, res):
        CALLS.append(("broken-finish",))
        return {}

    def stop(self, ctx):
        CALLS.append(("broken-stop",))


@pytest.fixture
def hooked(tmp_path, fake, monkeypatch):
    eps = {hooks.GROUP: [_EP("rec", "acme.rec:Recorder", lambda: Recorder),
                         _EP("broken", "acme.rec:Broken", lambda: Broken())]}
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda group=None: eps.get(group, []))
    (tmp_path / "wpk-home").mkdir(exist_ok=True)
    (tmp_path / "wpk-home" / "config.toml").write_text('[plugins.rec]\nport = 9999\n')
    harness._reset()
    CALLS.clear()
    proj, root = make_project(tmp_path)
    yield proj, root
    harness._reset()


def _meta(root):
    return json.loads(open(os.path.join(root.step_dir(1), "meta.json")).read())


def test_hooks_around_a_step(hooked, monkeypatch):
    proj, root = hooked
    seen = {}
    real = executor._model

    def spy(pkt, st, h, spec, env, *a, **kw):
        seen.update(env)
        return real(pkt, st, h, spec, env, *a, **kw)
    monkeypatch.setattr(executor, "_model", spy)
    out = executor.step(proj)
    assert out.code == 0, out.msg
    assert seen["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9999"      # start changed the env
    assert CALLS[0] == ("start", 1, 1, "claude", {"port": 9999})
    assert ("finish", True) in CALLS and CALLS.count(("stop",)) == 1
    ext = _meta(root)["ext"]
    assert ext["rec"] == {"calls": 1, "usd": 0.5}
    assert ext["broken"]["error"] == "start: RuntimeError: proxy would not start"
    assert ("broken-finish",) not in CALLS and ("broken-stop",) in CALLS
    assert _meta(root)["route"]["host"] == "127.0.0.1"


def test_hooks_around_both_runs_of_a_nudge(hooked, fake):
    proj, root = hooked
    fake(fault="forgetful")
    out = executor.step(proj)
    assert out.code == 0, out.msg
    meta = _meta(root)
    assert meta["nudged"] and meta["ext"]["rec"]["calls"] == 2
    assert [c[0] for c in CALLS].count("start") == 1 and CALLS.count(("stop",)) == 1


def test_stop_even_when_the_run_raises(hooked, monkeypatch):
    proj, root = hooked

    def boom(*a, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(executor, "_model", boom)
    with pytest.raises(KeyboardInterrupt):
        executor.step(proj)
    assert CALLS.count(("stop",)) == 1 and ("broken-stop",) in CALLS


def test_disabled_hook_not_called(hooked, tmp_path):
    proj, root = hooked
    (tmp_path / "wpk-home" / "config.toml").write_text('[plugins]\ndisable = ["rec"]\n')
    harness._reset()
    assert executor.step(proj).code == 0
    assert not [c for c in CALLS if c[0] in ("start", "finish", "stop")]
    assert "rec" not in _meta(root)["ext"]


def test_finish_that_raises_is_recorded():
    class Bad:
        def finish(self, ctx, res):
            raise ValueError("no total")
    hs = hooks.Hooks.__new__(hooks.Hooks)
    hs.ext = {}
    hs.hooks = [["bad", Bad(), None]]
    assert hs.finish(None) == {"bad": {"error": "finish: ValueError: no total"}}
    hs.stop()
