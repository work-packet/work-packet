"""What burns context inside a step: attribution by tool (docs/token-dashboard.md,
view 5).

Every call reads the whole context so far, so a step's context tokens (the sum
over its calls) split exactly into what each piece of the context costs: its
size times the calls that read it. A tool result added before call ``k`` of
``n`` is read ``n - k`` times; that product is its *carried* cost.

Sizes are measured, not guessed: the growth in context from one call to the
next is shared among the tool results that arrived in between, by length, at
no more than ``CHARS_PER_TOKEN`` (fitted on dvs-enh: 2.35 characters a token
for tool output). What is left of the growth is the model's own turn:
thinking, text, tool calls and hook messages. The first call's context is the
prompt and system prompt.

Reads Claude Code's stream-json transcript; other harnesses give no
attribution (``attribute`` returns None).
"""

import json
import os
import re
import shlex

CHARS_PER_TOKEN = 2.35
PROMPT, TURNS = "(prompt)", "(model turns)"

_PATH_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead")


def _chars(c):
    if isinstance(c, str):
        return len(c)
    if isinstance(c, list):
        return sum(len(b.get("text") or "") if isinstance(b, dict) and b.get("type") == "text"
                   else len(json.dumps(b)) for b in c)
    return len(json.dumps(c)) if c is not None else 0


def _rel(p, cwd):
    if isinstance(p, str) and cwd and p.startswith(cwd.rstrip("/") + "/"):
        return p[len(cwd.rstrip("/")) + 1:]
    return p if isinstance(p, str) else ""


_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")


def command_kind(cmd):
    """The program a shell command runs, for grouping: ``pytest``,
    ``python -m pytest``, ``grep``. Leading ``cd X &&`` and ``VAR=x`` are
    skipped."""
    cmd = re.sub(r"\\\n", " ", (cmd or "").strip())   # join continued lines
    for part in _SPLIT.split(cmd.splitlines()[0] if cmd else ""):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        while words and _ENV.match(words[0]):
            words = words[1:]
        if not words or words[0] in ("cd", "export", "set", "source", ".", "timeout", "time"):
            if words and words[0] in ("timeout", "time") and len(words) > 1:
                words = words[2:] if words[0] == "timeout" else words[1:]
            else:
                continue
        if not words:
            continue
        head = os.path.basename(words[0])
        if re.match(r"^python[\d.]*$", head) and len(words) > 2 and words[1] == "-m":
            return "python -m " + words[2]
        if head in ("uv", "poetry", "pipenv") and len(words) > 2 and words[1] == "run":
            return "%s run %s" % (head, os.path.basename(words[2]))
        return head
    return ""


def target(name, inp, cwd=None):
    """What a tool call acted on: a file, a pattern, a command, an agent's task."""
    inp = inp if isinstance(inp, dict) else {}
    if name in _PATH_TOOLS:
        return _rel(inp.get("file_path") or inp.get("notebook_path"), cwd)
    if name in ("Grep", "Glob"):
        p = inp.get("pattern") or ""
        return p + (" in " + _rel(inp["path"], cwd) if inp.get("path") else "")
    if name == "Bash":
        lines = (inp.get("command") or "").strip().splitlines()
        return lines[0] + (" ..." if len(lines) > 1 else "") if lines else ""
    if name in ("Agent", "Task"):
        return inp.get("description") or inp.get("subagent_type") or ""
    if name in ("WebFetch", "WebSearch"):
        return inp.get("url") or inp.get("query") or ""
    for k in ("bash_id", "task_id", "shell_id", "skill", "query"):
        if inp.get(k):
            return str(inp[k])
    return ""


def attribute(path):
    """The context of the step whose transcript is ``path``, split by what put
    it there: {calls, context, prompt, turns, results}. ``prompt`` and ``turns``
    are {tokens, carried}; ``results`` is a list of {tool, target, kind,
    tokens, carried, reads, error, call}. None when there is no transcript."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            lines = fp.read().splitlines()
    except OSError:
        return None
    cwd, uses, seen = None, {}, set()
    ctx, pending, results, turns = [], [], [], []   # turns: [call, tokens]
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("parent_tool_use_id"):
            continue
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            cwd = ev.get("cwd")
        elif t == "assistant":
            msg = ev.get("message") or {}
            for b in msg.get("content") or ():
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    uses[b.get("id")] = (b.get("name") or "?", b.get("input"))
            u = msg.get("usage")
            if not isinstance(u, dict) or (msg.get("id") and msg["id"] in seen):
                continue
            seen.add(msg.get("id"))
            n = sum(u.get(k) or 0 for k in ("cache_read_input_tokens",
                                             "cache_creation_input_tokens", "input_tokens"))
            k = len(ctx)
            grow = n - ctx[-1] if ctx else 0
            if ctx and grow > 0:
                want = sum(c for _, c in pending) / CHARS_PER_TOKEN
                scale = min(1.0, grow / want) if want else 0.0
                given = 0
                for r, c in pending:
                    r["tokens"] = int(round(c / CHARS_PER_TOKEN * scale))
                    r["call"] = k
                    given += r["tokens"]
                    results.append(r)
                turns.append([k, max(grow - given, 0)])
            else:
                for r, _ in pending:          # compaction or the first call: unsized
                    r["tokens"], r["call"] = 0, k
                    results.append(r)
            pending = []
            ctx.append(n)
        elif t == "user":
            content = (ev.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue
                name, inp = uses.get(b.get("tool_use_id"), ("?", None))
                tg = target(name, inp, cwd)
                kind = command_kind((inp or {}).get("command") or "") if name == "Bash" else tg
                r = {"tool": name, "target": tg, "kind": kind}
                if name == "Read" and isinstance(inp, dict):
                    o = inp.get("offset") if isinstance(inp.get("offset"), int) else 1
                    lim = inp.get("limit") if isinstance(inp.get("limit"), int) else 2000
                    r["lines"] = [o, o + lim]
                r["error"] = bool(b.get("is_error"))
                pending.append((r, _chars(b.get("content"))))
    if not ctx:
        return None
    n = len(ctx)
    for r in results:
        r["reads"] = n - r["call"]
        r["carried"] = r["tokens"] * r["reads"]
    carried_turns = sum(tok * (n - k) for k, tok in turns)
    return {"calls": n, "context": sum(ctx),
            "prompt": {"tokens": ctx[0], "carried": ctx[0] * n},
            "turns": {"tokens": sum(tok for _, tok in turns), "carried": carried_turns},
            "results": results}


def of_step(sd):
    return attribute(os.path.join(sd, "transcript.jsonl"))


BY = ("tool", "kind", "target")


def rollup(attrs, by="tool"):
    """Rows over several steps' attributions, biggest carried cost first:
    [{label, tool, n, errors, tokens, carried, share}]. ``by`` is ``tool``,
    ``kind`` (a Bash command's program, else the target) or ``target``. The
    prompt and the model's turns are rows of their own when ``by`` is tool."""
    rows, total = {}, 0
    for a in attrs:
        if not a:
            continue
        total += a["context"]
        if by == "tool":
            for label, part in ((PROMPT, a["prompt"]), (TURNS, a["turns"])):
                r = rows.setdefault((label, ""), {"label": label, "tool": "", "n": 0,
                                                  "errors": 0, "tokens": 0, "carried": 0})
                r["n"] += 1
                r["tokens"] += part["tokens"]
                r["carried"] += part["carried"]
        for x in a["results"]:
            label = x["tool"] if by == "tool" else x[by] or "(none)"
            key = (label, "" if by == "tool" else x["tool"])
            r = rows.setdefault(key, {"label": label, "tool": key[1], "n": 0, "errors": 0,
                                      "tokens": 0, "carried": 0})
            r["n"] += 1
            r["errors"] += x["error"]
            r["tokens"] += x["tokens"]
            r["carried"] += x["carried"]
    out = sorted(rows.values(), key=lambda r: (-r["carried"], r["label"]))
    for r in out:
        r["share"] = r["carried"] / float(total) if total else None
    return out


def _overlaps(x, earlier):
    a = x.get("lines") or [1, 1 << 30]
    return any(max(a[0], b[0]) < min(a[1], b[1])
               for b in (e.get("lines") or [1, 1 << 30] for e in earlier))


def repeats(attrs):
    """Files read again within a step, over lines already read: [{target,
    steps, n, carried}], counting only the reads that overlap an earlier one."""
    rows = {}
    for a in attrs:
        if not a:
            continue
        got = {}
        for x in a["results"]:
            if x["tool"] in ("Read", "NotebookRead") and x["target"]:
                got.setdefault(x["target"], []).append(x)
        for tg, xs in got.items():
            again = [x for i, x in enumerate(xs) if _overlaps(x, xs[:i])]
            if not again:
                continue
            r = rows.setdefault(tg, {"target": tg, "steps": 0, "n": 0, "carried": 0})
            r["steps"] += 1
            r["n"] += len(again)
            r["carried"] += sum(x["carried"] for x in again)
    return sorted(rows.values(), key=lambda r: -r["carried"])


def top(attrs, n=10):
    """The ``n`` single tool results with the biggest carried cost; each has the
    ``label`` of its attribution as ``step``."""
    xs = [dict(x, step=a.get("label")) for a in attrs if a for x in a["results"]]
    return sorted(xs, key=lambda x: -x["carried"])[:n]


def report(attrs, by="tool", top_n=10):
    """Lines for ``wpk stats --tools``."""
    from .stats import _k
    rows = rollup(attrs, by)
    if not rows:
        return []
    w = min(max([20] + [len(r["label"]) for r in rows]), 60)
    lines = ["%-*s %-6s %6s %5s %8s %9s %6s" % (w, by, "" if by == "tool" else "tool", "calls",
                                                "err", "size", "carried", "share")]
    for r in rows:
        lines.append("%-*s %-6s %6d %5s %8s %9s %6s" % (
            w, r["label"][-w:], r["tool"][:6], r["n"], r["errors"] or "", _k(r["tokens"]), _k(r["carried"]),
            "%d%%" % round(100 * r["share"]) if r["share"] is not None else "-"))
    rep = repeats(attrs)
    if rep:
        lines += ["", "Lines read again in the same step:"]
        wr = min(max(len(r["target"]) for r in rep[:top_n]), 70)
        for r in rep[:top_n]:
            lines.append("  %-*s %3d more in %d step%s, %s carried" % (
                wr, r["target"][-wr:], r["n"], r["steps"], "" if r["steps"] == 1 else "s",
                _k(r["carried"])))
    return lines
