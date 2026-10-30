"""Cost with a basis (design E5): harness, priced from the profile, or a cost plugin."""
import importlib.metadata
import json
import os

import pytest

from conftest import make_project
from test_plugins import _EP
from work_packet import cost, executor, harness

PRICE = {"input": 1.0, "output": 5.0, "cache_write": 2.0, "cache_read": 0.1}
TOKENS = {"input_tokens": 1000, "output_tokens": 2000, "cache_creation_input_tokens": 3000,
          "cache_read_input_tokens": 10000, "thinking_tokens": 500}


class Gateway:
    def cost(self, meta, step_dir):
        got = (meta.get("ext") or {}).get("proxy")
        return {"usd": got["usd"], "basis": "gateway", "source": "site-gateway"} if got else None


@pytest.fixture
def eps(monkeypatch):
    found = {}
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda group=None: found.get(group, []))
    harness._reset()
    yield found
    harness._reset()


def test_priced():
    assert cost.priced(TOKENS, PRICE) == round((1000 + 10000 + 6000 + 1000) / 1e6, 6)
    assert cost.priced(TOKENS, None) is None and cost.priced({}, PRICE) is None


def test_harness_basis_without_price(eps):
    m = cost.settle({"cost_usd": 0.25, "tokens": TOKENS, "harness": "claude"}, None, "/x")
    assert m["cost_usd"] == 0.25
    assert m["cost"] == {"usd": 0.25, "basis": "harness", "source": "claude", "harness_usd": 0.25}


def test_priced_beats_harness(eps):
    m = cost.settle({"cost_usd": 0.25, "tokens": TOKENS, "harness": "codex"}, PRICE, "/x")
    assert m["cost"]["basis"] == "priced" and m["cost_usd"] == cost.priced(TOKENS, PRICE)
    assert m["cost"]["harness_usd"] == 0.25


def test_plugin_beats_priced_and_bad_ones_skipped(eps):
    def boom():
        raise RuntimeError("down")

    class Raises:
        def cost(self, meta, step_dir):
            boom()
    eps[cost.GROUP] = [_EP("none", "a:N", lambda: type("N", (), {"cost": lambda s, m, d: None})),
                       _EP("raises", "a:R", lambda: Raises),
                       _EP("junk", "a:J", lambda: type("J", (), {"cost": lambda s, m, d: "x"})),
                       _EP("gw", "a:G", lambda: Gateway())]
    m = {"cost_usd": 0.25, "tokens": TOKENS, "harness": "claude", "ext": {"proxy": {"usd": 0.4}}}
    cost.settle(m, PRICE, "/x")
    assert m["cost"] == {"usd": 0.4, "basis": "gateway", "source": "site-gateway",
                         "harness_usd": 0.25}
    assert m["cost_usd"] == 0.4
    m = cost.settle({"cost_usd": 0.25, "tokens": TOKENS}, None, "/x")      # no answer
    assert m["cost"]["basis"] == "harness"


def test_plain_number_answer_is_named_for_the_plugin(eps):
    eps[cost.GROUP] = [_EP("flat", "a:F", lambda: type("F", (), {"cost": lambda s, m, d: 1}))]
    m = cost.settle({"cost_usd": None}, None, "/x")
    assert m["cost"] == {"usd": 1.0, "basis": "flat", "source": "flat", "harness_usd": None}


def _step(tmp_path, eps, profile_extra=""):
    (tmp_path / "wpk-home").mkdir(exist_ok=True)
    (tmp_path / "wpk-home" / "config.toml").write_text(
        '[profiles.priced]\nversion = 1\nharness = "claude"\nmodels = ["*"]\n'
        'sizing = "bounded"\n' + profile_extra)
    harness._reset()
    proj, root = make_project(tmp_path)
    out = executor.step(proj)
    assert out.code == 0, out.msg
    return json.loads(open(os.path.join(root.step_dir(1), "meta.json")).read())


def test_step_meta_harness_basis(tmp_path, fake, eps):
    m = _step(tmp_path, eps)
    assert m["cost"]["basis"] == "harness" and m["cost_usd"] == m["cost"]["harness_usd"]


def test_step_meta_priced(tmp_path, fake, eps):
    m = _step(tmp_path, eps, 'price = { input = 1.0, output = 5.0, cache_write = 2.0, '
                             'cache_read = 0.1 }\n')
    assert m["profile"] == "priced@1" and m["tokens"]
    assert m["cost"]["basis"] == "priced" and m["cost"]["source"] == "profile"
    assert m["cost_usd"] == cost.priced(m["tokens"], PRICE)
