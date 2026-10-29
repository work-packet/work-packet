"""The site config layer under config.toml (design E8.1)."""

import os

import pytest

from work_packet import registry
from work_packet.sched import config as sconfig
from work_packet.sched import doctor


def _w(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fp:
        fp.write(text)


SITE = """
max_concurrent = 3
[site]
locked = ["sched.lsf.project", "plugins.disable"]
[plugins]
disable = ["noisy"]
[sched]
backend = "lsf"
[sched.lsf]
queue = "normal"
project = "chip"
[sched.sizes.large]
cpus = 4
"""


@pytest.fixture
def site(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("WPK_HOME", str(h))
    p = str(tmp_path / "etc" / "config.toml")
    _w(p, SITE)
    monkeypatch.setenv("WPK_SITE_CONFIG", p)
    return str(h)


def test_path(monkeypatch, tmp_path):
    monkeypatch.setenv("WPK_HOME", str(tmp_path))
    monkeypatch.delenv("WPK_SITE_CONFIG")
    assert registry.site_config_path() == "/etc/wpk/config.toml"
    monkeypatch.setenv("WPK_SITE_CONFIG", "")
    assert registry.site_config_path() is None
    assert registry.load_config_file() == {}


def test_site_alone(site):
    cfg = registry.load_config_file()
    assert cfg["max_concurrent"] == 3 and cfg["sched"]["lsf"]["queue"] == "normal"
    s = sconfig.load()
    assert s["backend"] == "lsf" and s["sizes"]["large"]["cpus"] == 4
    assert "look" in s["sizes"]                     # built-in sizes kept
    assert s["max_concurrent"] == 3


def test_user_overrides_key_by_key(site):
    _w(os.path.join(site, "config.toml"),
       'max_concurrent = 5\n[sched.lsf]\nqueue = "short"\n[sched.sizes.large]\nmem = "64G"\n')
    s = sconfig.load()
    assert s["max_concurrent"] == 5
    assert s["lsf"] == dict(s["lsf"], queue="short", project="chip")
    assert s["sizes"]["large"]["cpus"] == 4 and s["sizes"]["large"]["mem"] == "64G"
    assert registry.overridden_locks() == []


def test_locked_keys_keep_site_value(site):
    _w(os.path.join(site, "config.toml"),
       '[site]\nlocked = []\n[plugins]\ndisable = []\n[sched.lsf]\nproject = "mine"\n')
    cfg = registry.load_config_file()
    assert cfg["sched"]["lsf"]["project"] == "chip"
    assert cfg["plugins"]["disable"] == ["noisy"]
    assert cfg["site"]["locked"] == ["sched.lsf.project", "plugins.disable"]
    assert registry.overridden_locks() == ["sched.lsf.project", "plugins.disable"]
    rows = doctor.run(site, probe=False)
    assert any(c.level == "ok" and c.title.startswith("site config: ") for c in rows)
    assert any(c.level == "warn" and "sched.lsf.project" in c.title for c in rows)


def test_locked_unset_in_site_stays_unset(site, tmp_path):
    p = os.environ["WPK_SITE_CONFIG"]
    _w(p, '[site]\nlocked = ["sched.lsf.bin"]\n')
    _w(os.path.join(site, "config.toml"), '[sched.lsf]\nbin = "/my/bin"\nqueue = "q"\n')
    cfg = registry.load_config_file()
    assert cfg["sched"]["lsf"] == {"queue": "q"}


def test_bad_site_config(site):
    _w(os.environ["WPK_SITE_CONFIG"], '[site]\nlocked = "sched"\n')
    with pytest.raises(registry.ConfigError, match="site.locked"):
        registry.load_config_file()


def test_bad_user_key_names_user_file(site):
    _w(os.path.join(site, "config.toml"), '[sched.sizes.large]\nmem_gb = 1\n')
    with pytest.raises(registry.ConfigError, match="home/config.toml: sched.sizes.large.mem_gb"):
        registry.load_config_file()
