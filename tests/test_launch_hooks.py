"""Launch hooks (brief-request.md, docs/sites.md §1.3b): a site plugin prepares the
child's environment for every harness launch, a scheduled step's and Studio's,
after the harness configuration and before the step hooks."""
import importlib.metadata
import os
import shlex
import sys
import time
import warnings

import pytest

from conftest import make_project
from test_dash_tasks import _new
from test_plugins import _EP
from work_packet import executor, harness, hooks, plugins, registry

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "fakemodel", "gate_claude.py")
VAR = "ACME_GATEWAY_HEADERS"
SENTINEL = "X-Acme-Token: SENTINEL-7f3c\nX-Acme-User: SENTINEL-matt"
STEP_CALLS = []


class Credentials:
    """The site's loader: a multi-line value from a private file."""

    def prepare(self, ctx):
        with open(ctx.config["file"], encoding="utf-8") as fp:
            ctx.env[VAR] = fp.read()


class Telemetry:
    """The site's existing step hook: it sees the credential, and a step's context."""

    def start(self, ctx):
        STEP_CALLS.append((ctx.wpid, ctx.step, ctx.attempt, ctx.env.get(VAR) == SENTINEL))


class Broken:
    def prepare(self, ctx):
        raise RuntimeError("leaked " + ctx.env.get(VAR, ""))


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def site(tmp_path, fake, monkeypatch):
    """The parent has neither the setting nor the credential; config.toml sets the
    one by env_file, a launch hook adds the other from a private file."""
    monkeypatch.delenv(VAR, raising=False)
    monkeypatch.delenv("ACME_SETTING", raising=False)
    monkeypatch.setenv("WPK_CLAUDE", "%s %s" % (shlex.quote(sys.executable), shlex.quote(GATE)))
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    cred = private / "headers"
    cred.write_text(SENTINEL)
    cred.chmod(0o600)
    home = tmp_path / "wpk-home"
    home.mkdir(exist_ok=True)
    env_file = home / "claude.env"
    env_file.write_text("ACME_SETTING=plain\n")
    env_file.chmod(0o600)
    (home / "config.toml").write_text(
        '[harnesses.claude]\nenv_file = "claude.env"\n\n[plugins.creds]\nfile = "%s"\n' % cred)
    monkeypatch.setenv("GATE_EXPECT", str(cred))
    monkeypatch.setenv("GATE_RESULT", str(tmp_path / "gate.txt"))
    eps = {hooks.LAUNCH_GROUP: [_EP("broken", "acme.creds:Broken", lambda: Broken()),
                                _EP("creds", "acme.creds:Credentials", lambda: Credentials)],
           hooks.GROUP: [_EP("telemetry", "acme.hooks:Telemetry", lambda: Telemetry)]}
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda group=None: eps.get(group, []))
    plugins._reset()
    harness._reset()
    STEP_CALLS.clear()
    yield tmp_path
    plugins._reset()
    harness._reset()


def _gate(tmp_path):
    p = tmp_path / "gate.txt"
    return p.read_text().split() if p.exists() else []


def _no_sentinel(*roots):
    for root in roots:
        for d, _, files in os.walk(root):
            for n in files:
                with open(os.path.join(d, n), "rb") as fp:
                    data = fp.read()
                assert b"SENTINEL" not in data, os.path.join(d, n)


def test_a_step_and_a_studio_chat_both_get_the_credential(site, fake, capsys):
    tmp_path = site
    # a scheduled step
    proj, root = make_project(tmp_path / "step")
    out = executor.step(proj)
    assert out.code == 0, out.msg
    assert _gate(tmp_path) == ["pass"]
    assert STEP_CALLS == [(root.wpid, 1, 1, True)]      # the step hook: after, with its step
    # a Studio chat through the board
    from starlette.testclient import TestClient
    from work_packet.dash.agent import Agents
    from work_packet.dash.app import create_app
    from work_packet.dash.guard import Guard, csrf_token
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    fake("studio")
    e, pkt = _new("a")
    e = registry.get("a")
    ag = Agents(os.environ["WPK_HOME"])
    secret, base_url = b"k" * 32, "http://127.0.0.1:7878"
    g = Guard(create_app(agents=ag), "loopback", secret, local_user="alice")
    tok = csrf_token(secret)
    base = "/p/a/%s/studio" % pkt.wpid
    with TestClient(g, base_url=base_url, client=("127.0.0.1", 50000)) as c:
        c.post(base + "/open", data={"csrf": tok}, headers={"origin": base_url},
               follow_redirects=False)
        r = c.post(base + "/ask", json={"text": "write docs/findings.md"},
                   headers={"origin": base_url, "x-csrf-token": tok})
        assert r.status_code == 200 and r.json()["asked"]
        cid = r.json()["conv"]
        end = time.time() + 20
        while len(_gate(tmp_path)) < 2 and time.time() < end:
            time.sleep(0.05)
        ag.wait(cid)
    assert _gate(tmp_path) == ["pass", "pass"]
    assert len(STEP_CALLS) == 1                         # no step hook on the Studio path
    # the parents never had it; nothing written down has it
    assert VAR not in os.environ and "ACME_SETTING" not in os.environ
    _no_sentinel(os.environ["WPK_HOME"], proj, e["path"])
    err = capsys.readouterr().err
    assert "SENTINEL" not in err and "launch hook broken: RuntimeError" in err


def test_each_launch_gets_its_own_environment(site):
    a, b = {"X": "1"}, {"X": "2"}
    hooks.prepare_env("claude", "model-call", a)
    assert a[VAR] == SENTINEL and VAR not in b and VAR not in os.environ
    plugins._cache[hooks.LAUNCH_GROUP] = []             # none enabled: nothing changes
    assert hooks.prepare_env("claude", "studio", b) == {"X": "2"}


def test_console_chat_gets_the_harness_settings_too(site):
    """Console chat applies [harnesses.claude] env_file, as a step and Studio do,
    and then the launch hooks."""
    from work_packet.dash.agent import Agents
    tmp_path = site
    ag = Agents(os.environ["WPK_HOME"])
    meta = ag.new({"kind": "home"}, str(tmp_path), "matt")
    ag.ask(meta["id"], "hello", "matt", "the primer")
    ag.wait(meta["id"])
    assert _gate(tmp_path) == ["pass"]
    assert not STEP_CALLS and "ACME_SETTING" not in os.environ
