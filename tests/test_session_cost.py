"""Interactive sessions on the Cost tab and Statistics (docs/session-cost-plan.md):
tokens by hour and model, a store that outlives the session list, model prices,
and runner + sessions side by side."""
import json
import os

import pytest

from conftest import NOW
from test_dash_tasks import _client, _new
from work_packet import cost, executor, ide_sessions as s, schema, session_usage
from work_packet.dash import data, tokens

T = s.epoch(NOW)
H = 3600


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _reply(mid, t, model, u, sid="7f3c1a2e-0b5d-4c6e-9f10-000000000001"):
    import datetime
    ts = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
    return json.dumps({"type": "assistant", "sessionId": sid, "timestamp": ts,
                       "message": {"id": mid, "model": model, "usage": u,
                                   "content": [{"type": "text", "text": "x"}]}})


def _sum(hours):
    out = {}
    for ms in hours.values():
        for u in ms.values():
            for k, v in u.items():
                out[k] = out.get(k, 0) + v
    return {k: v for k, v in out.items() if v}


def test_claude_tokens_go_to_the_hour_and_model_of_their_reply(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        _reply("m1", T, "claude-opus-5-5", {"input_tokens": 10, "output_tokens": 5}),
        _reply("m1", T + 1, "claude-opus-5-5", {"input_tokens": 10, "output_tokens": 50}),
        _reply("m2", T + 2 * H, "claude-sonnet-5", {
            "input_tokens": 1, "output_tokens": 2, "cache_creation_input_tokens": 300,
            "cache_creation": {"ephemeral_5m_input_tokens": 100,
                               "ephemeral_1h_input_tokens": 200}})]) + "\n")
    st, _ = s.scan(str(p), "claude")
    h0, h2 = s.hour_of(T), s.hour_of(T + 2 * H)
    # a revision replaces its first figures, in the same bucket
    assert st["hours"][h0] == {"claude-opus-5-5": {"input_tokens": 10, "output_tokens": 50}}
    assert st["hours"][h2]["claude-sonnet-5"]["cache_creation_1h_input_tokens"] == 200
    assert _sum(st["hours"]) == {k: v for k, v in st["usage"].items() if v}


def test_many_replies_fold_and_still_add_up(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(_reply("m%d" % i, T + i * 600, "claude-opus-5-5",
                                  {"input_tokens": 1, "output_tokens": i})
                           for i in range(s.RECENT_IDS * 2)) + "\n")
    st, _ = s.scan(str(p), "claude")
    assert st["_folded_hours"] and _sum(st["hours"]) == st["usage"]
    assert len(st["hours"]) > 10


def test_codex_snapshots_add_their_difference_to_the_hour(tmp_path):
    def tc(t, inp, out):
        import datetime
        ts = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()
        return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": inp, "cached_input_tokens": 0, "output_tokens": out}}}})
    p = tmp_path / "rollout-x.jsonl"
    p.write_text("\n".join([
        json.dumps({"timestamp": NOW, "type": "turn_context", "payload": {"model": "gpt-5.5"}}),
        tc(T, 100, 10), tc(T + 5, 150, 20), tc(T + 2 * H, 400, 60)]) + "\n")
    st, _ = s.scan(str(p), "codex")
    assert st["hours"][s.hour_of(T)]["gpt-5.5"] == {"input_tokens": 150, "output_tokens": 20}
    assert st["hours"][s.hour_of(T + 2 * H)]["gpt-5.5"] == {"input_tokens": 250,
                                                             "output_tokens": 40}
    assert _sum(st["hours"]) == {k: v for k, v in st["usage"].items() if v}


def test_a_state_from_before_hours_is_read_again(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(_reply("m1", T, "claude-opus-5-5", {"input_tokens": 7}) + "\n")
    st, cur = s.scan(str(p), "claude")
    del st["hours"]                      # what an older wpk kept
    st, cur = s.scan(str(p), "claude", st, cur)
    assert st["hours"] and st["usage"] == {"input_tokens": 7}


def test_the_store_outlives_the_session_list(tmp_path):
    home = str(tmp_path)
    s.write(home, {"harness": "claude", "session_id": "7f3c1a2e-0b5d-4c6e-9f10-000000000001",
                   "project": "a", "wpid": "W", "last_activity_t": T - 90 * 86400,
                   "usage": {"input_tokens": 5},
                   "hours": {s.hour_of(T): {"claude-opus-5-5": {"input_tokens": 5}},
                             "bad": {"m": {"input_tokens": 1}}}})
    s.prune(home, keep_days=30, now=T)
    assert s.records(home) == []
    got = session_usage.records(home)
    assert len(got) == 1 and got[0]["project"] == "a"
    assert got[0]["hours"] == {s.hour_of(T): {"claude-opus-5-5": {"input_tokens": 5}}}
    assert "usage" not in got[0]                    # only who, where and when


def test_model_prices(tmp_path, monkeypatch):
    assert cost.model_price("claude-opus-5-5")["input"] == 4.0      # before claude-opus-5*
    assert cost.model_price("claude-opus-5")["input"] == 5.0
    assert cost.model_price("gpt-5.5") is None
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('[prices."gpt-5*"]\ninput = 1.0\noutput = 8.0\n'
                                      'cache_read = 0.1\n')
    assert cost.model_price("gpt-5.5", str(home))["output"] == 8.0
    p = cost.model_price("claude-opus-5-5")
    usd = cost.session_usd({"input_tokens": 1e6, "output_tokens": 1e6,
                            "cache_creation_input_tokens": 3e6,
                            "cache_creation_1h_input_tokens": 1e6,
                            "cache_read_input_tokens": 10e6}, p)
    assert usd == pytest.approx(4 + 20 + 2 * 5 + 8 + 10 * 0.2)
    assert schema.validate_config({"prices": {"x*": {"input": 1, "output": 2}}}) == []
    errs = schema.validate_config({"prices": {"x*": {"input": -1, "bogus": 1}}})
    assert {e.field for e in errs} >= {"prices.x*.input", "prices.x*.bogus", "prices.x*.output"}


def _session(home, project, wpid, t, model="claude-opus-5-5", **u):
    session_usage.put(home, {"harness": "claude", "session_id": "sess-%s-%d-%s" % (project, t, model[:6]),
                             "project": project, "wpid": wpid, "client": "vscode-ext"},
                      {s.hour_of(t): {model: u or {"input_tokens": 1000000,
                                                   "output_tokens": 100000}}})


def test_cost_tab_and_statistics_show_runner_and_sessions(fake):
    e, pkt = _new("a")
    assert executor.step(e["path"]).code == 0
    home = os.environ["WPK_HOME"]
    _session(home, "a", pkt.wpid, T)                                 # $4 + $2 = $6
    _session(home, "a", pkt.wpid, T - 40 * 86400)                    # outside 14 days
    _session(home, "a", None, T, model="gpt-5.5")                    # no price
    tk = tokens.project(e, home=home)
    runner = tk["spend"]["window"]["runner"]
    assert runner > 0
    assert tk["spend"]["window"]["sessions"]["usd"] == pytest.approx(6.0)
    assert tk["spend"]["all"]["sessions"]["usd"] == pytest.approx(12.0)
    assert tk["spend"]["window"]["total"] == pytest.approx(runner + 6.0)
    assert tk["spend"]["window"]["sessions"]["unpriced"] == 1100000
    assert tk["sess_by_task"] == {pkt.wpid: pytest.approx(12.0)}
    assert len(tk["sessions"]) == 3
    c = _client()
    page = c.get("/p/a/cost").text
    assert "Spend: runner and your sessions" in page and "Your sessions" in page
    assert "$6.00" in page and "Spend per day" in page and "gpt-5.5" in page
    st = c.get("/stats?days=7").text
    assert "+ your sessions" in st and "$6.00" in st
    burn = tokens.board([e], days=7, home=home, sessions=True)
    assert burn["split"]["total"] == pytest.approx(runner + 6.0)
    assert burn["rows"][0]["total_usd"] == pytest.approx(runner + 6.0)
    # without sessions (a viewer who isn't the owner): as before
    assert tokens.project(e, home=home, sessions=False)["spend"] is None
    assert tokens.board([e], days=7, home=home)["split"] is None


def test_a_project_with_only_sessions(fake):
    e, pkt = _new("b")
    home = os.environ["WPK_HOME"]
    _session(home, "b", pkt.wpid, T)
    tk = tokens.project(e, home=home)
    assert tk["steps"] == 0 and tk["spend"]["all"]["total"] == pytest.approx(6.0)
    page = _client().get("/p/b/cost").text
    assert "Your sessions" in page and "No token counts yet" not in page
    burn = tokens.board([e], days=7, home=home, sessions=True)
    assert burn["rows"][0]["name"] == "b" and burn["rows"][0]["sess_usd"] == pytest.approx(6.0)
    assert "+ your sessions" in _client().get("/stats").text
    assert data.session_spend(home, T)["tokens"] == 1100000


def test_backfill_reads_ended_sessions_again(tmp_path, monkeypatch):
    """Sessions recorded before tokens had times get their hours from their
    transcripts, all of them, in chunks."""
    home = str(tmp_path / "home")
    sid = "7f3c1a2e-0b5d-4c6e-9f10-000000000001"
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(_reply("m%d" % i, T + i * 60, "claude-opus-5-5",
                                  {"input_tokens": 1, "output_tokens": 1}, sid)
                           for i in range(300)) + "\n")
    s.write(home, {"harness": "claude", "session_id": sid, "project": "a",
                   "usage": {"input_tokens": 300}})
    s._save_cur(home, "claude", sid, {"files": {str(p): {"st": None, "cur": None}}})
    monkeypatch.setattr(s, "MAX_READ", 4096)
    monkeypatch.setattr(s.scan, "__defaults__", (None, None, 4096))
    assert s.backfill_usage(home) == 1
    got = session_usage.records(home)[0]
    assert _sum(got["hours"]) == {"input_tokens": 300, "output_tokens": 300}
    assert s.backfill_usage(home) == 0                  # once
