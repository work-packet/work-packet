"""One-off model calls (the focus brief, the scribe, Studio's summary) get the
Claude harness settings as a step does, and say why they failed."""
import json
import os
import shlex
import sys

from work_packet import brief, briefagent, registry, scribe

FAKE = r'''
import json, os, sys
sys.stdin.read()
if os.environ.get("ACME_SETTING") != "plain":     # a gateway that wants the setting
    print(json.dumps({"is_error": True, "result": "Invalid API key: set ACME_SETTING",
                      "total_cost_usd": 0}))
    sys.exit(1)
print(json.dumps({"is_error": False, "result": "hello", "total_cost_usd": 0.01}))
'''


def _fake(tmp_path, monkeypatch, env_file=True):
    exe = tmp_path / "claude_fake.py"
    exe.write_text(FAKE)
    monkeypatch.setenv("WPK_CLAUDE", "%s %s" % (shlex.quote(sys.executable), shlex.quote(str(exe))))
    monkeypatch.delenv("ACME_SETTING", raising=False)
    h = registry.home()
    assert h.startswith(str(tmp_path))      # never the real home
    os.makedirs(h, exist_ok=True)
    if env_file:
        p = os.path.join(h, "claude.env")
        with open(p, "w") as fp:
            fp.write("ACME_SETTING=plain\n")
        os.chmod(p, 0o600)
        with open(os.path.join(h, "config.toml"), "a") as fp:
            fp.write('\n[harnesses.claude]\nenv_file = "claude.env"\n')
    return h


def test_a_model_call_gets_the_harness_env_file(tmp_path, fake, monkeypatch):
    h = _fake(tmp_path, monkeypatch)
    assert scribe.call_model("hi", h) == ("hello", 0.01, None)
    assert scribe.ask_model("hi", h) == ("hello", 0.01)


def test_a_failed_model_call_says_why(tmp_path, fake, monkeypatch):
    h = _fake(tmp_path, monkeypatch, env_file=False)
    text, cost, err = scribe.call_model("hi", h)
    assert text == "" and err == "claude exited 1: Invalid API key: set ACME_SETTING"
    monkeypatch.setenv("WPK_CLAUDE", "/nonexistent/claude")
    assert scribe.call_model("hi", h)[2].startswith("claude could not start")


def test_the_brief_shows_why_the_model_failed(tmp_path, fake, monkeypatch):
    from test_dash_tasks import _client
    h = _fake(tmp_path, monkeypatch, env_file=False)
    monkeypatch.setattr(briefagent, "ask", lambda prompt, **kw: (
        "", 0.0, "claude exited 1: Invalid API key"))
    b = brief.build(h)
    assert b["agent_error"] == "claude exited 1: Invalid API key"
    page = _client().get("/brief").text
    assert "The model&#39;s brief failed" in page or "The model's brief failed" in page
    assert "Invalid API key" in page


def test_a_crash_in_the_brief_thread_is_noted(tmp_path, fake, monkeypatch):
    h = _fake(tmp_path, monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("gather broke")
    monkeypatch.setattr(brief, "_take", boom)
    monkeypatch.setattr(briefagent, "ask", lambda prompt, **kw: (json.dumps({"headline": "x"}), 0.0))
    monkeypatch.setattr(briefagent, "validate", lambda d, bundle: {"headline": "x", "focus": []})
    assert brief.build_soon(h)
    for _ in range(200):
        if brief.writing() is None:
            break
        import time
        time.sleep(0.05)
    b = brief.load(h, brief.datetime.now().date().isoformat())
    assert b["agent_error"] == "RuntimeError: gather broke"
