#!/usr/bin/env python3
"""Stands in for ``claude -p --output-format stream-json`` in tests.

Runs the behaviour named by ``WPK_FAKE_BEHAVIOR`` (a module in
``behaviors/``) in the packet directory, then prints stream-json events.
``WPK_FAKE_FAULT`` makes it misbehave:

  crash        exit 1 after the init event, no result
  hang         sleep until killed
  error        a result event with is_error true
  bad-memento  write front matter that does not parse
  no-summary   skip .pending/summary.md
  no-report    skip .pending/report.md on resume: done or fail
  write-outside  also change state/ and memento.md directly
  bad-resume   resume: every monday
  forgetful    end the turn without writing .pending/, unless nudged
  silent       never write .pending/

Spend knobs (docs/scheduler-plan.md T-c): ``WPK_FAKE_COST`` is the result's
``total_cost_usd``; ``WPK_FAKE_QUOTA`` is JSON ``{"seven_day": [first, last,
resets_at], "five_hour": [...]}``, sent as two ``rate_limit_event``s.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def emit(ev):
    sys.stdout.write(json.dumps(ev) + "\n")
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", action="store_true")
    ap.add_argument("--output-format")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--session-id")
    ap.add_argument("--permission-mode")
    ap.add_argument("--max-budget-usd")
    ap.add_argument("--allowedTools")
    ap.add_argument("--add-dir", action="append", default=[])
    ap.add_argument("--tools")
    ap.add_argument("--strict-mcp-config", action="store_true")
    ap.add_argument("--setting-sources")
    ap.add_argument("--disable-slash-commands", action="store_true")
    ap.add_argument("--append-system-prompt-file")
    ap.add_argument("--settings")
    ap.add_argument("--resume")
    ap.add_argument("--fork-session", action="store_true")
    args = ap.parse_args()
    if os.environ.get("WPK_FAKE_ARGV"):              # for tests that check the flags
        with open(os.environ["WPK_FAKE_ARGV"], "a") as fp:
            fp.write(json.dumps(sys.argv[1:]) + "\n")
    prompt = sys.stdin.read()
    fault = os.environ.get("WPK_FAKE_FAULT", "")
    emit({"type": "system", "subtype": "init", "session_id": args.session_id,
          "model": args.model, "cwd": os.getcwd()})
    if fault == "crash":
        sys.stderr.write("fake: crashing\n")
        return 1
    if fault == "hang":
        time.sleep(3600)
    nudged = prompt.startswith("wpk: your turn ended")
    if fault == "silent" or (fault == "forgetful" and not nudged):
        emit({"type": "assistant", "session_id": args.session_id, "parent_tool_use_id": None,
              "message": {"id": "msg_bg", "role": "assistant", "content": [
                  {"type": "tool_use", "id": "tu_1", "name": "Bash",
                   "input": {"command": "make check", "run_in_background": True}},
                  {"type": "text", "text": "Waiting for the background job."}]}})
        emit({"type": "result", "subtype": "success", "is_error": False,
              "session_id": args.session_id, "total_cost_usd": 0.001,
              "result": "Waiting for the background job."})
        return 0
    name = os.environ.get("WPK_FAKE_BEHAVIOR", "add_one")
    spec = importlib.util.spec_from_file_location(
        "behavior_" + name, os.path.join(HERE, "behaviors", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = mod.run(prompt=prompt, fault=fault, model=args.model) or "done"
    hooked = post_tool_use(args.settings)
    if hooked:
        emit({"type": "user", "session_id": args.session_id, "fake_hook_context": hooked})
    quota = json.loads(os.environ.get("WPK_FAKE_QUOTA") or "{}")
    for i in (0, 1):
        if quota:
            emit({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {
                name: {"utilization": v[i], "resetsAt": v[2]} for name, v in quota.items()}}})
    usage = {"input_tokens": 10, "cache_creation_input_tokens": 1000,
             "cache_read_input_tokens": 9000, "output_tokens": 50}
    for i in range(2):
        emit({"type": "assistant", "session_id": args.session_id, "parent_tool_use_id": None,
              "message": {"id": "msg_%d" % i, "role": "assistant", "usage": dict(
                  usage, cache_read_input_tokens=9000 + 500 * i),
                  "content": [{"type": "text", "text": text}]}})
    emit({"type": "result", "subtype": "error_during_execution" if fault == "error" else "success",
          "is_error": fault == "error", "session_id": args.session_id, "num_turns": 2,
          "duration_ms": 1234, "total_cost_usd": float(os.environ.get("WPK_FAKE_COST") or 0.0012),
          "result": text,
          "usage": {"input_tokens": 1500, "output_tokens": 120}})
    return 0


def post_tool_use(settings):
    """Run the PostToolUse hooks once, as after a tool call; their added context.
    ``WPK_FAKE_NOTE`` first drops a note in the mailbox, as if sent mid-step."""
    if os.environ.get("WPK_FAKE_NOTE"):
        os.makedirs("mailbox", exist_ok=True)
        with open(os.path.join("mailbox", "20990101T000000-mid.json"), "w") as fp:
            json.dump({"id": "20990101T000000-mid", "t": "2099-01-01T00:00:00Z",
                       "by": "tester", "text": os.environ["WPK_FAKE_NOTE"]}, fp)
    try:
        hooks = json.loads(settings or "{}").get("hooks", {}).get("PostToolUse", [])
    except ValueError:
        return None
    out = []
    for h in hooks:
        for c in h.get("hooks", []):
            p = subprocess.run(c["command"], shell=True, capture_output=True, text=True,
                               input=json.dumps({"transcript_path": os.devnull}))
            if p.stdout.strip():
                out.append(json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"])
    return "\n".join(out) or None


if __name__ == "__main__":
    sys.exit(main())
