"""Reading Claude Code and Codex session files (docs/vscode-monitor-plan.md S2)."""

import json
import os
import shutil

from work_packet import ide_sessions as s

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ide_sessions")
CLAUDE = os.path.join(DATA, "claude_vscode.jsonl")
CODEX = os.path.join(DATA, "codex_vscode.jsonl")


def _shown(st):
    """The state without its private bookkeeping (the ``_`` keys)."""
    return {k: v for k, v in st.items() if not k.startswith("_")}


def _feed(harness, recs):
    st = s.new_state(harness)
    for r in recs:
        s.FEED[harness](st, r)
    return st


def test_claude_fixture():
    st, cur = s.scan(CLAUDE, "claude")
    assert st["session_id"] == "7f3c1a2e-0b5d-4c6e-9f10-2a3b4c5d6e7f"
    assert st["entrypoint"] == "claude-vscode" and st["cwd"] == "/w/pkt"
    assert st["model"] == "claude-sonnet-5"                 # <synthetic> is skipped
    # msg_A counted once, with its last revision (30 out, not 1 + 30)
    assert st["usage"] == {"input_tokens": 18, "output_tokens": 48,
                           "cache_read_input_tokens": 600, "cache_creation_input_tokens": 20}
    assert s.total(st["usage"]) == 686 and st["usage_reported"]
    assert st["last_event"] == s.TURN_END and st["turn_state"] == s.FINISHED
    assert st["last_activity_t"] == s.epoch("2026-11-04T10:00:09.000Z")
    assert cur["offset"] == os.path.getsize(CLAUDE)


def test_claude_events_from_tool_names_only():
    rec = lambda name: {"type": "assistant", "message": {"id": name, "content": [
        {"type": "tool_use", "name": name, "input": {"x": "SENTINEL"}}]}}
    for name, ev in [("Read", s.READ), ("Grep", s.READ), ("Bash", s.SHELL),
                     ("Edit", s.EDIT), ("WebFetch", s.WEB), ("Agent", s.AGENT),
                     ("AskUserQuestion", s.ASK), ("mcp__secret_server__do", s.TOOL),
                     ("SomethingNew", s.TOOL)]:
        assert _feed("claude", [rec(name)])["last_event"] == ev, name
    assert _feed("claude", [rec("AskUserQuestion")])["turn_state"] == s.WAITING
    prompt = {"type": "user", "message": {"content": "hello"}}
    result = {"type": "user", "message": {"content": [{"type": "tool_result"}]}}
    meta = {"type": "user", "isMeta": True, "message": {"content": "caveat"}}
    assert _feed("claude", [prompt])["last_event"] == s.PROMPT
    assert _feed("claude", [rec("Bash"), result, meta])["last_event"] == s.SHELL


def test_claude_interleaved_revisions_and_many_ids():
    a1 = {"type": "assistant", "message": {"id": "A", "usage": {"output_tokens": 1}}}
    b = {"type": "assistant", "message": {"id": "B", "usage": {"output_tokens": 5}}}
    a2 = {"type": "assistant", "message": {"id": "A", "usage": {"output_tokens": 9}}}
    assert _feed("claude", [a1, b, a2])["usage"] == {"output_tokens": 14}
    many = [{"type": "assistant", "message": {"id": "m%d" % i, "usage": {"output_tokens": 1}}}
            for i in range(500)]
    st = _feed("claude", many + many[-10:])                 # late revisions of recent ids
    assert st["usage"] == {"output_tokens": 500} and len(st["_recent"]) == s.RECENT_IDS
    json.dumps(st)                                          # serializable


def test_claude_without_usage_or_model_is_unreported():
    st = _feed("claude", [{"type": "assistant", "message": {"id": "A", "content": [
        {"type": "text", "text": "x"}], "stop_reason": "end_turn"}}])
    assert st["usage"] == {} and not st["usage_reported"] and st["model"] is None
    assert st["last_event"] == s.TURN_END


def test_codex_fixture():
    st, _ = s.scan(CODEX, "codex")
    assert st["session_id"] == "019a4f2e-1c2d-7e3f-8a9b-0c1d2e3f4a5b"
    assert st["source"] == "vscode" and st["entrypoint"] == "codex-tui"
    assert st["model"] == "gpt-5.5-codex"
    # the latest cumulative snapshot, not the sum of them; null info skipped
    assert st["usage"] == {"input_tokens": 500, "cache_read_input_tokens": 2000,
                           "output_tokens": 90, "thinking_tokens": 40}
    assert s.total(st["usage"]) == 2590
    assert st["last_event"] == s.TURN_END and st["turn_state"] == s.FINISHED


def test_codex_thread_usage_wins_and_is_never_added_to_token_count():
    tc = lambda n: {"type": "event_msg", "payload": {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": n, "cached_input_tokens": 0,
                              "output_tokens": 1}}}}
    tr = lambda n: {"type": "token_usage_record", "payload": {"thread_token_usage": {
        "input_tokens": n, "cached_input_tokens": 0, "output_tokens": 1}}}
    st = _feed("codex", [tc(100), tr(120), tc(999)])
    assert st["usage"] == {"input_tokens": 120, "cache_read_input_tokens": 0,
                           "output_tokens": 1}
    assert _feed("codex", [tc(100), tc(150)])["usage"]["input_tokens"] == 150
    st = _feed("codex", [{"type": "event_msg", "payload": {"type": "token_count",
                                                            "info": None}}])
    assert not st["usage_reported"]


def test_codex_events():
    ev = lambda t, **p: {"type": "event_msg", "payload": dict(p, type=t)}
    fc = lambda n: {"type": "response_item", "payload": {"type": "function_call", "name": n,
                                                         "arguments": "SENTINEL"}}
    for recs, want in [([ev("task_started")], s.TURN_START),
                       ([ev("user_message", message="SENTINEL")], s.PROMPT),
                       ([fc("shell")], s.SHELL), ([fc("exec_command")], s.SHELL),
                       ([fc("apply_patch")], s.EDIT), ([fc("update_plan")], s.PLAN),
                       ([fc("")], s.TOOL), ([ev("exec_approval_request")], s.ASK),
                       ([ev("apply_patch_approval_request")], s.ASK),
                       ([ev("turn_aborted")], s.TURN_ABORT),
                       ([ev("task_complete")], s.TURN_END)]:
        assert _feed("codex", recs)["last_event"] == want, recs
    st = _feed("codex", [{"type": "session_meta", "payload": {"id": "x" * 12,
                                                              "source": {"subagent": "y"}}}])
    assert st["source"] == "subagent"


def test_no_sentinel_in_any_state():
    for path, h in ((CLAUDE, "claude"), (CODEX, "codex")):
        st, cur = s.scan(path, h)
        assert "SENTINEL" not in json.dumps([st, cur]), h


def test_partial_lines_wait_and_garbage_is_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    lines = open(CLAUDE, "rb").read().splitlines(keepends=True)
    p.write_bytes(b"".join(lines[:6]) + lines[6][:20])        # torn mid-line
    st, cur = s.scan(str(p), "claude")
    assert st["usage"] == {"input_tokens": 10, "output_tokens": 1,
                           "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20}
    with open(p, "ab") as fp:
        fp.write(lines[6][20:] + b"{not json\n" + b"".join(lines[7:]))
    st, cur = s.scan(str(p), "claude", st, cur)
    whole, _ = s.scan(CLAUDE, "claude")
    assert _shown(st) == dict(_shown(whole), bad_lines=1)


def test_truncation_and_rotation_start_over(tmp_path):
    p = str(tmp_path / "t.jsonl")
    shutil.copy(CLAUDE, p)
    st, cur = s.scan(p, "claude")
    first = _shown(st)
    with open(p, "r+b") as fp:                              # truncated: read again
        fp.truncate(100)
    st, cur = s.scan(p, "claude", st, cur)
    assert st["usage"] == {} and cur["offset"] <= 100
    os.unlink(p)                                            # replaced: a new inode
    shutil.copy(CLAUDE, p + ".new")
    os.rename(p + ".new", p)
    st, cur = s.scan(p, "claude", st, cur)
    assert _shown(st) == first


def test_a_big_backlog_catches_up_in_bounded_passes(tmp_path):
    p = tmp_path / "big.jsonl"
    rec = {"type": "assistant", "message": {"id": None, "usage": {"output_tokens": 1}}}
    with open(p, "w") as fp:
        for i in range(3000):
            rec["message"]["id"] = "m%d" % i
            fp.write(json.dumps(rec) + "\n")
        fp.write(json.dumps({"type": "user", "message": {"content": "x" * 5000}}) + "\n")
        rec["message"]["id"] = "last"
        fp.write(json.dumps(rec) + "\n")
    st, cur, passes = None, None, 0
    while cur is None or cur["offset"] < os.path.getsize(p):
        st, cur = s.scan(str(p), "claude", st, cur, max_bytes=4096)
        passes += 1
        assert passes < 100
    assert st["usage"] == {"output_tokens": 3001} and passes > 10


def test_an_overlong_line_is_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    ok = json.dumps({"type": "assistant", "message": {"id": "A", "usage": {"output_tokens": 2}}})
    p.write_text(json.dumps({"type": "user", "message": {"content": "x" * 10000}}) + "\n" +
                 ok + "\n")
    st, cur = None, None
    for _ in range(10):
        st, cur = s.scan(str(p), "claude", st, cur, max_bytes=1024)
    assert st["usage"] == {"output_tokens": 2} and st["bad_lines"] == 0
