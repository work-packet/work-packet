"""Build the step prompt from ``prompts/step.md`` (stage1-plan §4 step 6)."""

import os
from string import Template

from . import schema

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "step.md")


def _ago(seconds):
    s = int(seconds)
    for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= n:
            k = s // n
            return "%d %s%s" % (k, unit, "" if k == 1 else "s")
    return "%d second%s" % (s, "" if s == 1 else "s")


def children_table(children):
    """``children``: list of (wpid, status meta or None, summary) in spawn order."""
    if not children:
        return "None."
    rows = ["| WPID | State | Step | Last summary |", "|---|---|---|---|"]
    for wpid, meta, summary in children:
        meta = meta or {}
        line = (summary or "").strip().splitlines()
        rows.append("| %s | %s | %s | %s |" % (
            wpid, meta.get("state", "?"), meta.get("step", "?"),
            (line[0] if line else "").replace("|", "\\|")))
    return "\n".join(rows)


FILE_MAX = 4096        # bytes of one state file shown in the prompt
TOTAL_MAX = 16384      # bytes of all state files shown in the prompt
LIST_MAX = 100         # state files named in the prompt


def _fence(text):
    run = longest = 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def state_files(state_dir):
    """The ``state/`` files as Markdown: small text files in full, others by size.

    Saves the model a Read (or a Glob) for each file it only needs to look at.
    """
    files = []
    for dirpath, dirnames, filenames in os.walk(state_dir):
        dirnames.sort()
        for n in sorted(filenames):
            p = os.path.join(dirpath, n)
            files.append((os.path.relpath(p, state_dir).replace(os.sep, "/"), p))
    if not files:
        return "`state/` is empty."
    out, shown, left = [], 0, TOTAL_MAX
    for rel, p in files[:LIST_MAX]:
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        text = None
        if size <= min(FILE_MAX, left) and not os.path.islink(p):
            try:
                with open(p, encoding="utf-8") as fp:
                    text = fp.read()
            except (OSError, UnicodeDecodeError):
                text = None
        if text is None:
            out.append("- `state/%s` (%d bytes, not shown)" % (rel, size))
            continue
        left -= size
        shown += 1
        f = _fence(text)
        out.append("- `state/%s`:\n\n%s\n%s%s\n" % (
            rel, f, text, f if text.endswith("\n") or not text else "\n" + f))
    if len(files) > LIST_MAX:
        out.append("- ... and %d more files" % (len(files) - LIST_MAX))
    return "\n".join(out).rstrip()


def build(*, status, last_summary, instruction, step, attempt, max_attempts,
          now, tz, children=(), agent_md=None, state_dir=None):
    """The prompt text. ``now`` is aware UTC; ``tz`` a tzinfo for local display."""
    wake_line = ""
    if status.get("state") == "SLEEPING" and status.get("wake_at"):
        due = schema.parse_timestamp(status["wake_at"])
        late = (now - due).total_seconds()
        wake_line = "- Woken by a timer (`%s`) due %s%s\n" % (
            status.get("resume_expr"), status["wake_at"],
            ", %s late" % _ago(late) if late >= 60 else "")
    agent = ""
    if agent_md:
        agent = "## Project notes (agent.md)\n\n%s\n\n" % agent_md.strip()
    with open(TEMPLATE, encoding="utf-8") as fp:
        tmpl = Template(fp.read())
    return tmpl.substitute(
        wpid=status["wpid"], project=status["project"], step=step, attempt=attempt,
        max_attempts=max_attempts, now=schema.format_timestamp(now),
        now_local=now.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z"),
        tz=getattr(tz, "key", None) or str(tz), wake_line=wake_line,
        last_summary=(last_summary or "").strip() or "None: this is the first step.",
        children=children_table(children), agent_md=agent,
        state=state_files(state_dir) if state_dir else "Not shown.",
        instruction=(instruction or "").strip())
