"""OpenAI Codex CLI (``codex exec``), or ``$WPK_CODEX`` in its place.

UNVERIFIED: written from docs/harness.md §7 (Codex 0.147.0 ``--help`` and
docs, no model run); ``--skip-git-repo-check``, ``--add-dir`` and the
``usage`` field names are from memory. The command line is all in
``command()`` and the event names all in ``parse()``; check both against a
real ``--json`` transcript before relying on it.

What Codex lacks next to Claude Code, and so what the executor does without
(``Caps``): no system prompt slot (the protocol leads the prompt), no
mid-step messages (no context warning, no notes), no session id chosen up
front, no resume by the executor (no carry-over, no nudge), and no cost in
the output (cost comes from the profile's ``price``, item E5). Nor does it
take a tool list or a USD budget: the sandbox and the step timeout are the
limits.
"""

import json
import os
import shlex

from . import Caps, Harness, home_env

# A fixed list, as for Claude: Codex cannot list what an account may use.
MODELS = (
    ("gpt-5-codex", "gpt-5-codex"),
    ("gpt-5", "gpt-5"),
)

KEY_VARS = ("CODEX_API_KEY", "OPENAI_API_KEY")


class Codex(Harness):
    name = "codex"
    caps = Caps()
    base_url_var = "OPENAI_BASE_URL"

    def __init__(self):
        self.account = None

    def models(self):
        return list(MODELS)

    def command(self, spec):
        """``codex exec --json`` reading the prompt from stdin (``-``).

        ``bypassPermissions`` runs without the sandbox; any other mode runs
        in the ``workspace-write`` sandbox, the packet and ``add_dirs``
        writable. Approvals are off: nobody is there to give them."""
        exe = shlex.split(os.environ.get("WPK_CODEX") or "codex")
        argv = exe + ["exec", "--json", "--skip-git-repo-check", "--model", spec.model]
        if spec.permission_mode == "bypassPermissions":
            argv += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            argv += ["--sandbox", "workspace-write", "-c", 'approval_policy="never"']
        for d in spec.add_dirs:
            argv += ["--add-dir", d]
        return argv + ["-"]

    def env(self, spec):
        out = home_env(self.name)
        # How the run pays, for meta.json's route: an API key in the environment
        # is used over a ChatGPT login (a guess, as above).
        keyed = any(out.get(v) or os.environ.get(v) for v in KEY_VARS)
        self.account = "key" if keyed else "subscription"
        return out

    def parse(self, transcript_path, res):
        """Fill ``res`` from a ``--json`` transcript (JSONL events).

        ``thread.started`` gives the session id; each ``turn.completed`` adds
        its ``usage`` (``input_tokens``, ``cached_input_tokens``,
        ``output_tokens``, ``reasoning_output_tokens``) and is one context
        size; ``turn.failed`` and ``error`` mark the run failed; the last
        ``agent_message`` item is the text. A run is done when a turn ended.
        Cost is left unknown."""
        try:
            with open(transcript_path, encoding="utf-8", errors="replace") as fp:
                lines = fp.read().splitlines()
        except FileNotFoundError:
            return res
        tokens = {}
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            t = ev.get("type")
            if t == "thread.started" and ev.get("thread_id"):
                res.session_id = ev["thread_id"]
            elif t == "turn.completed":
                res.got_result = True
                u = ev.get("usage") or {}
                for k, v in u.items():
                    if isinstance(v, int) and not isinstance(v, bool):
                        tokens[k] = tokens.get(k, 0) + v
                n = u.get("input_tokens")
                if isinstance(n, int):      # OpenAI's input_tokens includes the cached part
                    res.context.append(n)
            elif t in ("turn.failed", "error"):
                res.got_result = res.got_result or t == "turn.failed"
                res.is_error = True
                err = ev.get("error") if isinstance(ev.get("error"), dict) else ev
                res.subtype = str(err.get("message") or t)[:200]
            elif t == "item.completed":
                item = ev.get("item") or {}
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    res.text = item["text"]
        if tokens:
            # Name the counts as Claude's are, so stats and pricing read them alike.
            if "cached_input_tokens" in tokens:
                c = tokens.pop("cached_input_tokens")
                tokens["cache_read_input_tokens"] = c
                tokens["input_tokens"] = max(tokens.get("input_tokens", 0) - c, 0)
            if "reasoning_output_tokens" in tokens:
                tokens["thinking_tokens"] = tokens.pop("reasoning_output_tokens")
            res.tokens = tokens
        res.account = res.account or self.account
        return res
