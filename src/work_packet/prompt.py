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


def build(*, status, last_summary, instruction, step, attempt, max_attempts,
          now, tz, children=(), agent_md=None):
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
        instruction=(instruction or "").strip())
