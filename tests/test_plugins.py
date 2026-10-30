"""Plugin loading (design E1): entry-point groups, [plugins] enable/disable,
[plugins.<name>] tables, and the plugins in wpk doctor."""
import importlib.metadata

import pytest

from work_packet import harness, plugins, schema, setup, starters
from work_packet.sched import backends
from work_packet.sched import config as sched_config


class _Dist:
    name, version = "acme-wpk", "1.2"


class _EP:
    def __init__(self, name, value, load, dist=_Dist):
        self.name, self.value, self._load, self.dist = name, value, load, dist
        self.module = value.split(":")[0]

    def load(self):
        return self._load()


class Fake(harness.Harness):
    name = "fake"


class Mine:
    name = "mine"


class Gateway:
    help = "sign in to the gateway"

    def add_commands(self, parser):
        sub = parser.add_subparsers(dest="op", metavar="<op>")
        p = sub.add_parser("status", help="is the session good")
        p.add_argument("--json", action="store_true")
        p.set_defaults(run=lambda args, h: print("status", args.json, h) or 3)


class Clash:
    name = "check"

    def add_commands(self, parser):
        raise AssertionError("not called")


class Farm(backends.Backend):
    name = "farm"

    def __init__(self, cfg, h=None):
        self.cfg, self.h = cfg, h


def _boom():
    raise ImportError("no module named acme_budget")


def _objs():
    """One fake plugin per group (all from the acme-wpk distribution)."""
    out = {g: [_EP("acme", "acme.%s:Plugin" % g.split(".")[-1],
                   lambda g=g: ("obj", g))] for g in plugins.GROUPS}
    out["work_packet.harnesses"] = [_EP("fake", "acme.harness:Fake", lambda: Fake)]
    out["work_packet.cli"] += [_EP("gateway", "acme.gw:Gateway", lambda: Gateway),
                               _EP("clash", "acme.gw:Clash", lambda: Clash())]
    out["work_packet.sched_backends"].append(_EP("farm", "acme.farm:Farm", lambda: Farm))
    out["work_packet.sched_backends"].append(_EP("lsf", "acme.farm:Lsf", lambda: Farm))
    out["work_packet.starters"].append(_EP("mine", "acme.start:Mine", lambda: Mine))
    out["work_packet.budget"].append(_EP("broke", "acme.budget:Broke", _boom))
    out["work_packet.cost"].append(_EP("other", "other:Cost", lambda: "cost", dist=None))
    return out


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("WPK_HOME", str(tmp_path))
    eps = _objs()
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda group=None: eps.get(group, []))
    _reset()

    def config(text):
        (tmp_path / "config.toml").write_text(text)
        _reset()
    yield config
    _reset()


def _reset():
    harness._reset()
    starters._reset()


def test_every_group_loads(fake):
    for g in plugins.GROUPS:
        if g == "work_packet.harnesses":
            continue
        p = plugins.load(g)[0]
        assert (p.name, p.group, p.module, p.version, p.dist) == \
            ("acme", g, "acme." + g.split(".")[-1], "1.2", "acme-wpk")
        assert p.ok and p.obj == ("obj", g)
    assert plugins.loaded("work_packet.cost") == {"acme": ("obj", "work_packet.cost"),
                                                  "other": "cost"}
    assert len(plugins.everything()) == len(plugins.GROUPS) + 7


def test_loaded_once(fake, monkeypatch):
    first = plugins.load("work_packet.cli")
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda group=None: [])
    assert plugins.load("work_packet.cli") is first


def test_broken_plugin_is_kept(fake):
    b = [p for p in plugins.load("work_packet.budget") if p.name == "broke"][0]
    assert b.enabled and not b.ok and b.obj is None
    assert b.error == "ImportError: no module named acme_budget"
    assert "broke" not in plugins.loaded("work_packet.budget")


def test_disable_by_name_and_by_distribution(fake):
    fake('[plugins]\ndisable = ["other"]\n')
    assert plugins.loaded("work_packet.cost") == {"acme": ("obj", "work_packet.cost")}
    fake('[plugins]\ndisable = ["acme-wpk"]\n')
    assert plugins.loaded("work_packet.cost") == {"other": "cost"}
    assert harness.names() == ["claude", "codex"]       # fake comes from acme-wpk too
    assert harness.broken() == {}


def test_enable_lists_the_ones_used(fake):
    fake('[plugins]\nenable = ["other"]\n')
    assert plugins.loaded("work_packet.cost") == {"other": "cost"}
    assert plugins.loaded("work_packet.dash") == {}
    p = plugins.load("work_packet.dash")[0]
    assert not p.enabled and p.obj is None                # a disabled one is not imported
    assert "acme" not in starters.broken() and "mine" not in starters.names()


def test_starter_plugin(fake):
    assert "mine" in starters.names()
    assert "acme" in starters.broken()          # ("obj", group) is not a starter class


def test_plugin_table(fake):
    fake('[plugins.acme]\nportal = "https://portal"\nevery = 3\n')
    assert plugins.table("acme") == {"portal": "https://portal", "every": 3}
    assert plugins.table("nope") == {}


def test_bad_config_does_not_stop_loading(fake):
    fake("[plugins\n")
    assert plugins.config() == {}
    assert "acme" in plugins.loaded("work_packet.cli")


def test_schema():
    ok = {"plugins": {"enable": ["a"], "disable": [], "acme": {"x": 1}}}
    assert schema.validate_config(ok) == []
    bad = {"plugins": {"enable": "a", "acme": 3}}
    assert sorted(p.field for p in schema.validate_config(bad)) == \
        ["plugins.acme", "plugins.enable"]
    assert [p.field for p in schema.validate_config({"plugins": []})] == ["plugins"]


def test_harness_plugin_goes_through_plugins(fake):
    assert harness.names() == ["claude", "codex", "fake"]
    assert isinstance(harness.get("fake"), Fake)


def test_doctor_lists_plugins(fake):
    fake('[plugins]\ndisable = ["other"]\n')
    rows = {c.id: c for c in setup._tools() if c.id.startswith("tools.plugin.")}
    assert rows["tools.plugin.credentials.acme"].level == "ok"
    assert "acme.credentials:Plugin (acme-wpk 1.2)" in rows["tools.plugin.credentials.acme"].detail
    assert rows["tools.plugin.cli.gateway"].level == "ok"
    assert rows["tools.plugin.cli.acme"].level == "warn"      # no add_commands
    assert "is a wpk command" in rows["tools.plugin.cli.clash"].detail
    assert rows["tools.plugin.harnesses.fake"].level == "ok"
    assert rows["tools.plugin.budget.broke"].level == "warn"
    assert "no module named acme_budget" in rows["tools.plugin.budget.broke"].detail
    assert rows["tools.plugin.cost.other"].level == "info"
    assert rows["tools.plugin.cost.other"].title == "plugin other disabled"


def test_sched_backend_plugin(fake):
    assert backends.names() == ["farm", "local", "lsf", "slurm"]
    raw = {"sched": {"backend": "farm", "farm": {"queue": "big"}}}
    assert schema.validate_config(raw) == []
    cfg = sched_config.load(raw=raw)
    b = backends.get(cfg)
    assert isinstance(b, Farm) and b.cfg["farm"] == {"queue": "big"}
    # not a Backend subclass, or a built-in's name: broken, said in doctor
    assert set(backends.broken()) == {"acme", "lsf"}
    assert "built-in" in backends.broken()["lsf"]
    with pytest.raises(ValueError, match="did not load"):
        backends.get({"backend": "acme"})
    rows = {c.id: c for c in setup._tools()}
    assert rows["tools.sched_backend.acme"].level == "warn"
    assert "not a Backend subclass" in rows["tools.sched_backend.acme"].detail


def test_sched_backend_unknown(fake):
    fields = [p.field for p in schema.validate_config({"sched": {"backend": "nope", "nope": {}}})]
    assert fields == ["sched.backend"]
    fields = [p.field for p in schema.validate_config({"sched": {"backend": "lsf", "farm": {}}})]
    assert fields == ["sched.farm"]


def test_cli_group(fake, capsys, tmp_path):
    from work_packet import cli
    assert cli.main(["gateway", "status", "--json"]) == 3
    assert capsys.readouterr().out.strip() == "status True %s" % tmp_path
    assert cli.main(["gateway"]) == 2                       # no command: the group's help
    assert "status" in capsys.readouterr().err
    text = cli.build_parser().format_help()
    head, plug = text.split("plugin commands:")
    assert "gateway" not in head and "sign in to the gateway" in plug
    assert "check" in head and "clash" not in text
    with pytest.raises(SystemExit):
        cli.main(["acme"])
