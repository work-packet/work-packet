"""Controls, principals, the grant and the registry lock (docs/scheduler.md §6,
§14; plan Q1.2, Q1.3, Q1.15, Q1.15a)."""

import os
import threading

import pytest
import tomli_w

from work_packet import project, registry
from work_packet.cli import main
from work_packet.packet import Packet
from work_packet.sched import authz, config as sconfig, control, events
from work_packet.tomlio import load_toml

ME = authz.principal_cli()


@pytest.fixture
def home(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return os.environ["WPK_HOME"]


def new(name):
    plan = project.new(name, "Read state/count.md (0 if missing), add one.")
    return plan, Packet(os.path.join(plan.path, "packets", plan.root))


def evs(h, type):
    return [e for e in events.read(h) if e["type"] == type]


def write_config(h, d):
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "wb") as fp:
        tomli_w.dump(d, fp)


def test_modes_write_file_and_event(home):
    assert control.read_mode()["mode"] == "run"
    out = control.set_mode("drain", ME, "lunch")
    assert out.code == 0 and "halted" in out.msg
    d = load_toml(control.control_path())
    assert (d["mode"], d["by"], d["reason"]) == ("drain", ME, "lunch")
    e = evs(home, "mode")[-1]
    assert (e["mode"], e["by"], e["was"]) == ("drain", ME, "run")
    assert control.set_mode("stop", ME).code == 4            # stop needs a reason
    assert control.set_mode("resume", ME).code == 4          # not a mode
    assert control.set_mode("run", ME).code == 0
    assert control.read_mode()["mode"] == "run"
    assert os.path.islink(os.path.join(home, "events.jsonl"))


def test_start_mode_when_control_is_missing(home):
    write_config(home, {"sched": {"start_mode": "drain"}})
    assert control.read_mode()["mode"] == "drain"
    control.set_mode("run", ME)
    assert control.read_mode()["mode"] == "run"              # the file wins once written


def test_hold_release_prio_size_next(home):
    _, root = new("demo")
    write_config(home, {"sched": {"sizes": {"sim": {"cpus": 8, "mem": "32G"}}}})
    assert control.hold("demo", ME, "not this week").code == 0
    e = registry.get("demo")
    assert (e["sched"], e["sched_by"], e["sched_reason"]) == ("hold", ME, "not this week")
    assert control.release("demo", ME).code == 0
    assert "sched" not in registry.get("demo")
    assert control.set_prio("demo", "high", ME).code == 0
    assert control.set_prio(root.wpid[:8], "urgent", ME).code == 0
    assert control.set_size(root.wpid, "sim", ME).code == 0
    assert control.run_next(root.wpid[:10], ME).code == 0
    e = registry.get("demo")
    assert e["priority"] == "high"
    assert e["packets"][root.wpid] == {"priority": "urgent", "size": "sim", "next": True}
    assert control.set_prio(root.wpid, None, ME).code == 0
    assert control.set_size(root.wpid, None, ME).code == 0
    assert control.run_next(root.wpid, ME, on=False).code == 0
    assert "packets" not in registry.get("demo")             # emptied tables go
    for t in ("hold", "prio", "size", "next"):
        assert evs(home, t) and all(x["by"] == ME for x in evs(home, t))
    assert evs(home, "prio")[1]["wpid"] == root.wpid


def test_bad_class_or_size_is_refused(home):
    _, root = new("demo")
    assert control.set_prio("demo", "asap", ME).code == 4
    out = control.set_size("demo", "huge", ME)
    assert out.code == 4 and "look" in out.msg
    assert control.set_prio("nope", "high", ME).code == 4
    assert control.run_next("demo", ME).code == 4             # a project, not a packet
    assert main(["prio", "demo", "asap"]) == 4
    assert main(["prio", "demo", "low"]) == 0
    assert registry.get("demo")["priority"] == "low"
    assert main(["size", "demo", "huge"]) == 4


def test_by_is_required():
    with pytest.raises(TypeError):
        control.set_mode("drain")
    with pytest.raises(TypeError):
        control.hold("demo")
    with pytest.raises(TypeError):
        control.set_prio("demo", "high")


def test_a_denied_principal_changes_nothing(home, monkeypatch):
    new("demo")

    def deny(principal, action, target=None, h=None):
        raise authz.Denied("%s may not %s" % (principal, action))
    monkeypatch.setattr(authz, "check", deny)
    for out in (control.set_mode("drain", ME), control.hold("demo", ME),
                control.set_prio("demo", "high", ME), control.set_size("demo", "look", ME)):
        assert out.code == 4 and "not allowed" in out.msg
    assert control.read_mode()["mode"] == "run"
    assert not os.path.exists(control.control_path())
    assert "priority" not in registry.get("demo") and "sched" not in registry.get("demo")
    assert events.read(home) == []


def test_principals():
    assert authz.is_principal("unix:matt") and authz.is_principal("tailscale:m@x.com")
    assert not authz.is_principal("matt") and not authz.is_principal("unix:")
    authz.check(ME, "mode")
    authz.check("tailscale:someone@example.com", "prio")       # passed the Guard
    with pytest.raises(authz.Denied):
        authz.check("unix:somebody-else", "mode")
    with pytest.raises(authz.Denied):
        authz.check("matt", "mode")

    class Req:
        def __init__(self, state):
            self.scope = {"state": state}
    assert authz.principal_of(Req({"user": "m@x.com", "listener": "tailnet"})) == \
        "tailscale:m@x.com"
    assert authz.principal_of(Req({"user": "matt", "listener": "loopback"})) == "unix:matt"
    assert authz.principal_of(Req({})) == ME


def _grant(h, **kw):
    os.makedirs(sconfig.sched_dir(h), exist_ok=True)
    with open(sconfig.grant_path(h), "wb") as fp:
        tomli_w.dump(kw, fp)


def test_grant_lowers_never_raises(home):
    from work_packet import clock
    write_config(home, {"sched": {"cores": 16, "mem": "64G", "jobs": 8}})
    cfg = sconfig.load(home)
    now = clock.now()
    lim = sconfig.pool_limits(cfg, home, now)
    assert (lim.cores, lim.mem_mb, lim.jobs) == (16, 65536, 8)
    _grant(home, cores=4, mem="128G", by="frontdoor:ops", expires="2099-01-01T00:00:00Z")
    lim = sconfig.pool_limits(cfg, home, now)
    assert (lim.cores, lim.mem_mb, lim.jobs) == (4, 65536, 8) and lim.grant["by"] == \
        "frontdoor:ops"
    _grant(home, cores=64, jobs=100, expires="2099-01-01T00:00:00Z")
    lim = sconfig.pool_limits(cfg, home, now)
    assert (lim.cores, lim.jobs, lim.grant) == (16, 8, None)
    _grant(home, cores=2, by="frontdoor:ops", expires="2020-01-01T00:00:00Z")
    for _ in range(3):
        lim = sconfig.pool_limits(cfg, home, now)
        assert lim.cores == 16 and "expired" in lim.notes[0]
    assert len(evs(home, "grant_expired")) == 1
    _grant(home, cores="many")
    lim = sconfig.pool_limits(cfg, home, now)
    assert lim.cores == 16 and "ignored" in lim.notes[0]


def test_jobs_default_is_max_concurrent(home):
    from work_packet import clock
    write_config(home, {"max_concurrent": 3})
    assert sconfig.pool_limits(sconfig.load(home), home, clock.now()).jobs == 3
    assert sconfig.pool_limits(sconfig.load(home), home, clock.now(), jobs=5).jobs == 5


def test_registry_update_two_writers(home):
    new("demo")
    errors = []

    def writer(key):
        try:
            for i in range(30):
                registry.update("demo", lambda e: e.setdefault("packets", {}).setdefault(
                    "%08d-0000-4000-8000-%012d" % (i, key), {})
                    .update(priority="low"))
        except Exception as ex:          # noqa: BLE001
            errors.append(ex)
    ts = [threading.Thread(target=writer, args=(k,)) for k in (1, 2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    assert len(registry.get("demo")["packets"]) == 60
    assert not [n for n in os.listdir(registry.projects_dir()) if n.endswith(".lock")]


def test_registry_update_validates(home):
    new("demo")
    with pytest.raises(registry.ConfigError):
        registry.update("demo", lambda e: e.update(priority="asap"))
    assert "priority" not in registry.get("demo")
    with pytest.raises(registry.LookupFailed):
        registry.update("nope", lambda e: None)


def test_sched_cli(home, capsys):
    _, root = new("demo")
    assert main(["sched"]) == 0
    out = capsys.readouterr().out
    assert "pool: running" in out and "demo" in out and "starts next" in out
    assert main(["sched", "halt", "-m", "lunch"]) == 0
    assert main(["sched"]) == 0
    out = capsys.readouterr().out
    assert "HALTED" in out and "lunch" in out and "pool halted by %s" % ME in out
    assert main(["sched", "hold", "demo"]) == 0
    assert main(["sched", "stop"]) == 4                       # needs -m
    assert main(["sched", "resume"]) == 0
    assert main(["sched", "--json"]) == 0
    import json
    snap = json.loads(capsys.readouterr().out)
    assert snap["mode"]["mode"] == "run" and snap["holds"] == ["demo"]
    assert snap["queue"][0]["waiting"] == "hold"
    assert main(["sched", "release", "demo"]) == 0
    assert main(["sched", "jobs"]) == 0
    assert "no jobs" in capsys.readouterr().out
