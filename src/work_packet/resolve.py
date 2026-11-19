"""Question resolution: a fresh interactive session that walks the owner through a
packet's open questions and ends with ``wpk answer`` (docs/question-ux-plan.md §2)."""

import os

from . import layout, questions, schema

SYSTEM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "resolve.md")


def asking_step(pkt):
    """The folder of the last step that committed (its ``result.md`` holds the ``ask:``),
    or None."""
    try:
        names = os.listdir(pkt.steps_dir)
    except OSError:
        return None
    done = sorted(n for n, f in filter(None, map(schema.parse_step_dir, names)) if f is None)
    for n in reversed(done):
        d = pkt.step_dir(n)
        if os.path.exists(os.path.join(d, "result.md")):
            return d
    return None


def system_prompt():
    with open(SYSTEM, encoding="utf-8") as fp:
        return fp.read()


def brief(pkt, proj, wpk="wpk"):
    """The session's opening message: the questions in full, what the agent will do
    after the answer, and where to look. None when the packet has no open questions."""
    qs = questions.of_packet(pkt)
    if not qs:
        return None
    meta, _ = pkt.load_status()
    try:
        _, after = pkt.load_memento()
    except Exception:               # noqa: BLE001 - the questions are what matters
        after = ""
    folder = layout.packet_folder(proj)
    out = ["Packet `%s` (%s) is waiting for my answers to %s. Help me understand and "
           "answer %s." % (meta.get("project") or os.path.basename(proj), pkt.wpid[:8],
                           "this question" if len(qs) == 1 else "%d questions" % len(qs),
                           "it" if len(qs) == 1 else "them"),
           "", "## The questions, as the packet's agent asked them", ""]
    for q in qs:
        out += questions.as_text(q)
    if after.strip():
        out += ["", "## What the agent plans to do after the answers", "", after.strip()]
    out += ["", "## Where to look", "",
            "- Packet folder (the work): `%s`" % folder,
            "- The agent's notes and plan: `%s`" % pkt.state_dir]
    step = asking_step(pkt)
    if step:
        out.append("- The step that asked: `%s` (`summary.md`, `result.md`; its prompt is "
                   "`prompt.md`)" % step)
    out += ["- `%s show %s` prints where the packet stands." % (wpk, pkt.wpid[:8]),
            "", "## When we're done", "",
            "Record the answers with `%s answer %s id=answer ... --note-file -` "
            "(the note on stdin). Ids: %s." % (wpk, pkt.wpid, ", ".join(
                "`%s`" % q["id"] for q in qs))]
    return "\n".join(out) + "\n"


def harness(proj):
    """``(name, exe)``: the project's harness (claude or codex) and its path on the
    PATH, or None when it isn't there."""
    import shutil
    from . import registry
    from .tomlio import load_toml
    try:
        name = registry.load_config().get("harness") or "claude"
        name = load_toml(os.path.join(proj, "project.toml")).get("harness") or name
    except Exception:                   # noqa: BLE001
        name = "claude"
    name = name if name in ("claude", "codex") else "claude"
    return name, shutil.which(name)


def env(base, wpid):
    """The session's environment: ``base`` with the packet named, and not marked as
    running inside another Claude Code session."""
    out = dict(base, WPK_WPID=wpid)
    out.pop("CLAUDECODE", None)
    return out


def argv(exe, harness, pkt, proj, wpk="wpk"):
    """The command that starts the session, or None when there is nothing to resolve."""
    text = brief(pkt, proj, wpk)
    if text is None:
        return None
    if harness == "codex":          # no separate system prompt: put it first
        return [exe, system_prompt() + "\n---\n\n" + text]
    return [exe, "--append-system-prompt", system_prompt(), text]
