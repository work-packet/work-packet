"""Claude Code (``claude -p``), or ``$WPK_CLAUDE`` in its place."""

import json
import os
import shlex
import sys

from . import Caps, Harness, home_env

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(PKG, "ctxhook.py")
BGHOOK = os.path.join(PKG, "bghook.py")
PATHHOOK = os.path.join(PKG, "pathhook.py")


def tool_names(allowed_tools):
    """Built-in tool names for ``--tools``: ``Bash(git *)`` is the ``Bash`` tool."""
    out = []
    for t in allowed_tools:
        name = t.split("(", 1)[0].strip()
        if name and name not in out:
            out.append(name)
    return out


def _cmd(*args):
    return " ".join(shlex.quote(a) for a in (sys.executable,) + args)


def hook_settings(limit, marker, notes=None):
    """``--settings`` JSON with the hooks: one that refuses background Bash
    calls (``bghook.py``), one that refuses edits of the executor's files
    (``pathhook.py``) and, with a limit or a notes inbox (``notes``: the
    inbox and the step's ``notes.seen``), the PostToolUse hook that sends the
    context warning (context.md C3) and the owner's notes (interaction.md §6a)."""
    hooks = {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": _cmd(BGHOOK)}]},
        {"matcher": "Edit|Write|MultiEdit|NotebookEdit",
         "hooks": [{"type": "command", "command": _cmd(PATHHOOK)}]}]}
    if limit > 0 or notes:
        args = (str(max(limit, 0)), marker or os.devnull) + tuple(notes or ())
        hooks["PostToolUse"] = [
            {"matcher": "*", "hooks": [{"type": "command", "command": _cmd(HOOK, *args)}]}]
    return json.dumps({"hooks": hooks})


def context_tokens(usage):
    """The context one API call read: new input plus cache writes and reads."""
    if not isinstance(usage, dict):
        return None
    n = [usage.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                "cache_read_input_tokens")]
    n = [v for v in n if isinstance(v, int)]
    return sum(n) if n else None


def _add_quota(quota, info):
    """Note one ``rate_limit_event``: the subscription's use of each window
    (``five_hour``, ``seven_day``) as a fraction, first and last seen in the
    step. Undocumented; seen in Claude Code 2.1.280 stream-json."""
    if not isinstance(info, dict):
        return
    wins = info.get("unifiedWindows")
    if not isinstance(wins, dict):
        wins = {}
        if info.get("rateLimitType") and "utilization" in info:
            wins = {info["rateLimitType"]: info}
    for name, w in wins.items():
        if not isinstance(w, dict) or not isinstance(w.get("utilization"), (int, float)):
            continue
        q = quota.setdefault(name, {"first": w["utilization"]})
        q["last"] = w["utilization"]
        if isinstance(w.get("resetsAt"), (int, float)):
            q["resets_at"] = int(w["resetsAt"])


def _add_usage(tokens, u):
    """Add a ``result`` event's ``usage`` to ``tokens``: its counts, plus
    ``thinking_tokens`` and the cache writes split by TTL (``cache_write_1h``,
    ``cache_write_5m``), which are priced differently."""
    if not isinstance(u, dict):
        return
    for k, v in u.items():
        if isinstance(v, int) and not isinstance(v, bool):
            tokens[k] = tokens.get(k, 0) + v
    extra = {"thinking_tokens": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
             "cache_write_1h": (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens"),
             "cache_write_5m": (u.get("cache_creation") or {}).get("ephemeral_5m_input_tokens")}
    for k, v in extra.items():
        if isinstance(v, int):
            tokens[k] = tokens.get(k, 0) + v


# Offered in the board's New task form. Claude Code has no way to list the models
# an account may use (with a claude.ai login there is no API key for /v1/models),
# so this is a fixed list: the aliases `--model` takes, which follow the newest
# model, then full names. Update it when models change.
MODELS = (
    ("fable", "fable: the newest Fable"),
    ("opus", "opus: the newest Opus"),
    ("sonnet", "sonnet: the newest Sonnet"),
    ("haiku", "haiku: the newest Haiku"),
    ("claude-fable-5-1", "Fable 5.1"),
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-sonnet-5", "Sonnet 5"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5"),
)


class Claude(Harness):
    name = "claude"
    caps = Caps(system_slot=True, inject=True, resume=True, fork=True, set_session_id=True,
                reports_cost=True, cost_is_chain_total=True)

    def models(self):
        return list(MODELS)

    def command(self, spec):
        """The ``claude -p`` command line for one step.

        A step sees only what the project allows: ``--tools`` loads just the
        allowed built-in tools, and the user's MCP servers, settings files and
        skills are left out. Besides isolating the step, this keeps Claude
        Code's own context small; on Haiku it took a one-step smoke run from
        $0.043 to $0.027 (stage1-plan status log, 2026-10-21).

        The system file is appended to the system prompt; the settings add
        the hooks that refuse background Bash calls and edits outside
        ``.pending/`` and, with a context
        limit, the context budget hook; ``resume_from`` forks that session
        under this step's id (context.md).
        """
        exe = shlex.split(os.environ.get("WPK_CLAUDE") or "claude")
        argv = exe + ["-p", "--output-format", "stream-json", "--verbose",
                      "--model", spec.model, "--session-id", spec.session_id,
                      "--permission-mode", spec.permission_mode,
                      "--max-budget-usd", "%.2f" % spec.budget_usd,
                      "--tools", ",".join(tool_names(spec.allowed_tools)),
                      "--strict-mcp-config", "--setting-sources", "",
                      "--disable-slash-commands"]
        if spec.allowed_tools:
            argv += ["--allowedTools", ",".join(spec.allowed_tools)]
        for d in spec.add_dirs:
            argv += ["--add-dir", d]
        if spec.system_file:
            argv += ["--append-system-prompt-file", spec.system_file]
        argv += ["--settings", hook_settings(spec.context_limit, spec.marker, spec.notes)]
        if spec.resume_from:
            argv += ["--resume", spec.resume_from, "--fork-session"]
        return argv

    def env(self, spec):
        # Steps already get the 1-hour cache; pin it, since carry-over relies on it.
        out = {"CLAUDE_CODE_PROMPT_CACHE_TTL": os.environ.get(
            "CLAUDE_CODE_PROMPT_CACHE_TTL", "1h")}
        out.update(home_env(self.name))
        return out

    def parse(self, transcript_path, res):
        """Fill ``res`` from a stream-json transcript.

        The last ``result`` event gives the outcome and the cost. Token counts are
        the sum over every ``result`` event (a nudged step has two): Claude Code's
        ``usage`` there covers that run only, even on a resumed session, while
        ``total_cost_usd`` and ``modelUsage`` cover the chain (probed 2026-10-23).
        Each main-thread ``assistant`` message gives one call's context size; a
        message split over several events is counted once, and subagent calls are
        left out. A call that reads less than half the previous call's context
        from the cache is a cache break (the cache expired or the prefix changed).

        A run killed before its ``result`` (a timeout, a crash) reports no
        usage, so the ``assistant`` messages after the last ``result``, subagent
        calls included, are added up instead and ``tokens["unreported_calls"]``
        counts them. That gives the input side only: a message's
        ``output_tokens`` is the count when its stream began (189 over the 19
        calls of a timed-out Opus step), so output, thinking and cost stay unknown.
        """
        try:
            with open(transcript_path, encoding="utf-8", errors="replace") as fp:
                lines = fp.read().splitlines()
        except FileNotFoundError:
            return res
        seen = set()
        tokens, api_ms = {}, None
        tail = {}           # message id -> usage, since the last result event
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("session_id") and not res.session_id:
                res.session_id = ev["session_id"]
            if ev.get("type") == "assistant" and isinstance((ev.get("message") or {}).get("usage"), dict):
                msg = ev["message"]
                tail[msg.get("id") or len(tail)] = msg["usage"]
            if ev.get("type") == "assistant" and not ev.get("parent_tool_use_id"):
                msg = ev.get("message") or {}
                mid = msg.get("id")
                n = context_tokens(msg.get("usage"))
                if n is not None and (mid is None or mid not in seen):
                    u = msg["usage"]
                    if res.context and (u.get("cache_read_input_tokens") or 0) < res.context[-1] / 2:
                        res.cache_breaks += 1
                        res.cache_rewrite += u.get("cache_creation_input_tokens") or 0
                    res.context.append(n)
                    seen.add(mid)
            if ev.get("type") == "rate_limit_event":
                _add_quota(res.quota, ev.get("rate_limit_info"))
            if ev.get("type") != "result":
                continue
            res.got_result = True
            tail = {}
            res.is_error = bool(ev.get("is_error"))
            res.subtype = ev.get("subtype")
            res.session_id = ev.get("session_id") or res.session_id
            if isinstance(ev.get("total_cost_usd"), (int, float)):
                res.cost_usd = float(ev["total_cost_usd"])
            _add_usage(tokens, ev.get("usage"))
            if isinstance(ev.get("duration_api_ms"), (int, float)):
                api_ms = (api_ms or 0) + ev["duration_api_ms"]
            if isinstance(ev.get("result"), str):
                res.text = ev["result"]
        for u in tail.values():
            for k in ("input_tokens", "cache_creation_input_tokens",
                      "cache_read_input_tokens"):
                if isinstance(u.get(k), int):
                    tokens[k] = tokens.get(k, 0) + u[k]
            w = (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens")
            if isinstance(w, int):
                tokens["cache_write_1h"] = tokens.get("cache_write_1h", 0) + w
        if tail:
            tokens["unreported_calls"] = len(tail)
        if tokens:
            res.tokens = tokens
        if api_ms is not None:
            res.api_s = round(api_ms / 1000.0, 3)
        return res
