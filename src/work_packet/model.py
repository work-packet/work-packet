"""Run one model step: ``claude -p``, or ``$WPK_CLAUDE`` in its place."""

import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StepResult:
    exit_code: Optional[int] = None
    timed_out: bool = False
    is_error: bool = False
    got_result: bool = False         # the transcript has a ``result`` event
    subtype: Optional[str] = None
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None
    tokens: dict = field(default_factory=dict)
    duration_s: float = 0.0
    text: Optional[str] = None

    def failure(self):
        """Why the run failed, or None if it succeeded."""
        if self.timed_out:
            return "timeout"
        if self.exit_code != 0:
            return "model exited with status %s" % self.exit_code
        if not self.got_result:
            return "transcript has no result event"
        if self.is_error:
            return "model reported an error (%s)" % (self.subtype or "is_error")
        return None


def tool_names(allowed_tools):
    """Built-in tool names for ``--tools``: ``Bash(git *)`` is the ``Bash`` tool."""
    out = []
    for t in allowed_tools:
        name = t.split("(", 1)[0].strip()
        if name and name not in out:
            out.append(name)
    return out


def command(model, session_id, permission_mode, allowed_tools, budget_usd, add_dirs=()):
    """The ``claude -p`` command line for one step.

    A step sees only what the project allows: ``--tools`` loads just the
    allowed built-in tools, and the user's MCP servers, settings files and
    skills are left out. Besides isolating the step, this keeps Claude
    Code's own context small; on Haiku it took a one-step smoke run from
    $0.043 to $0.027 (stage1-plan status log, 2026-10-21).
    """
    exe = shlex.split(os.environ.get("WPK_CLAUDE") or "claude")
    argv = exe + ["-p", "--output-format", "stream-json", "--verbose",
                  "--model", model, "--session-id", session_id,
                  "--permission-mode", permission_mode,
                  "--max-budget-usd", "%.2f" % budget_usd,
                  "--tools", ",".join(tool_names(allowed_tools)),
                  "--strict-mcp-config", "--setting-sources", "",
                  "--disable-slash-commands"]
    if allowed_tools:
        argv += ["--allowedTools", ",".join(allowed_tools)]
    for d in add_dirs:
        argv += ["--add-dir", d]
    return argv


def parse_transcript(path, res):
    """Fill ``res`` from the last ``result`` event of a stream-json transcript."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            lines = fp.read().splitlines()
    except FileNotFoundError:
        return res
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("session_id") and not res.session_id:
            res.session_id = ev["session_id"]
        if ev.get("type") != "result":
            continue
        res.got_result = True
        res.is_error = bool(ev.get("is_error"))
        res.subtype = ev.get("subtype")
        res.session_id = ev.get("session_id") or res.session_id
        if isinstance(ev.get("total_cost_usd"), (int, float)):
            res.cost_usd = float(ev["total_cost_usd"])
        u = ev.get("usage")
        if isinstance(u, dict):
            res.tokens = {k: v for k, v in u.items() if isinstance(v, int)}
        if isinstance(ev.get("result"), str):
            res.text = ev["result"]
    return res


def run(argv, prompt, cwd, env, timeout_s, transcript_path, stderr_path):
    """Run the model with ``prompt`` on stdin. A timeout kills the process group."""
    res = StepResult()
    t0 = time.monotonic()
    with open(transcript_path, "wb") as out, open(stderr_path, "wb") as err:
        try:
            p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                 stdout=out, stderr=err, start_new_session=True)
        except OSError as e:
            err.write(("wpk: cannot run %s: %s\n" % (argv[0], e)).encode())
            res.exit_code = 127
            return res
        try:
            p.communicate(prompt.encode("utf-8"), timeout=timeout_s)
        except subprocess.TimeoutExpired:
            res.timed_out = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
        res.exit_code = p.returncode
    res.duration_s = round(time.monotonic() - t0, 3)
    return parse_transcript(transcript_path, res)
