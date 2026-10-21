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
  write-outside  also change state/ and memento.md directly
  bad-resume   resume: every monday
"""

import argparse
import importlib.util
import json
import os
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
    args = ap.parse_args()
    prompt = sys.stdin.read()
    fault = os.environ.get("WPK_FAKE_FAULT", "")
    emit({"type": "system", "subtype": "init", "session_id": args.session_id,
          "model": args.model, "cwd": os.getcwd()})
    if fault == "crash":
        sys.stderr.write("fake: crashing\n")
        return 1
    if fault == "hang":
        time.sleep(3600)
    name = os.environ.get("WPK_FAKE_BEHAVIOR", "add_one")
    spec = importlib.util.spec_from_file_location(
        "behavior_" + name, os.path.join(HERE, "behaviors", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = mod.run(prompt=prompt, fault=fault, model=args.model) or "done"
    emit({"type": "assistant", "session_id": args.session_id,
          "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})
    emit({"type": "result", "subtype": "error_during_execution" if fault == "error" else "success",
          "is_error": fault == "error", "session_id": args.session_id, "num_turns": 2,
          "duration_ms": 1234, "total_cost_usd": 0.0012, "result": text,
          "usage": {"input_tokens": 1500, "output_tokens": 120}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
