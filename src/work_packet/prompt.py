"""Build the step prompt from ``prompts/step.md`` (stage1-plan §4 step 6).

The fixed protocol, ``prompts/protocol.md``, goes in the system prompt
(``--append-system-prompt-file``), where it is cached with Claude Code's own
system prompt across steps (context.md C2).
"""

import json
import os
from string import Template

from . import notes as _notes, schema

PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
TEMPLATE = os.path.join(PROMPTS, "step.md")
PROTOCOL = os.path.join(PROMPTS, "protocol.md")


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
FIRST_MAX = 8192       # the same, for the FIRST files
TOTAL_MAX = 16384      # bytes of all state files shown in the prompt
LIST_MAX = 100         # state files named in the prompt
FIRST = ("env.md", "outline.md")   # shown before the rest (protocol "Working through a plan")
ARCHIVE = "archive"    # state/archive/: counted, never shown


def _fence(text):
    run = longest = 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def state_files(state_dir):
    """The ``state/`` files as Markdown: small text files at its top in full,
    others by size.

    Saves the model a Read (or a Glob) for each file it only needs to look at.
    Files in subfolders, such as ``notes/<item>.md``, are only named: the prompt
    is read again on every call, and a step needs one item's notes at most
    (fw-proto-axi-opus: the notes of finished items grew it from 3.7 to 18.5 KB).
    """
    files, archived = [], 0
    for dirpath, dirnames, filenames in os.walk(state_dir):
        dirnames.sort()
        if dirpath == state_dir and ARCHIVE in dirnames:
            dirnames.remove(ARCHIVE)
            archived = sum(len(f) for _, _, f in os.walk(os.path.join(state_dir, ARCHIVE)))
        for n in sorted(filenames):
            p = os.path.join(dirpath, n)
            files.append((os.path.relpath(p, state_dir).replace(os.sep, "/"), p))
    files.sort(key=lambda f: FIRST.index(f[0]) if f[0] in FIRST else len(FIRST))
    if not files and not archived:
        return "`state/` is empty."
    out, shown, left = [], 0, TOTAL_MAX
    for rel, p in files[:LIST_MAX]:
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        text = None
        if size <= min(FIRST_MAX if rel in FIRST else FILE_MAX, left) and "/" not in rel \
                and not os.path.islink(p):
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
    if archived:
        out.append("- `state/%s/`: %d file%s, not shown" % (ARCHIVE, archived, "" if archived == 1 else "s"))
    return "\n".join(out).rstrip()


def _zone_name(tz):
    return getattr(tz, "key", None) or str(tz)


def system(tz, harness="claude", sizing="bounded"):
    """The protocol text for the system prompt: the neutral protocol, the
    profile's step sizing (``prompts/sizing-<name>.md``), then the harness's
    notes (``prompts/harness-<name>.md``). Same for every step of a packet."""
    with open(PROTOCOL, encoding="utf-8") as fp:
        text = Template(fp.read()).substitute(tz=_zone_name(tz)).rstrip()
    for part in ("sizing-%s.md" % sizing, "harness-%s.md" % harness):
        path = os.path.join(PROMPTS, part)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fp:
                text += "\n\n" + fp.read().strip()
    return text + "\n"


LAST_CALLS = 25        # tool calls of a failed attempt listed for the retry
LAST_CALL_MAX = 160    # characters of each
LAST_TEXT_MAX = 1500   # characters of its last message
PENDING_MAX = 3000     # characters of each .pending file it left


def _clip(text, n):
    text = " ".join(text.split()) if "\n" not in text.strip() else text.strip()
    return text if len(text) <= n else text[:n - 1] + "…"


def attempt_trail(transcript_path, root=None):
    """(the main thread's tool calls as short lines, its last text) from a transcript."""
    calls, last = [], None
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fp:
            lines = fp.read().splitlines()
    except OSError:
        return calls, last
    rel = (lambda p: os.path.relpath(p, root) if root and os.path.isabs(p)
           and p.startswith(root + os.sep) else p)
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant" or ev.get("parent_tool_use_id"):
            continue
        for b in (ev.get("message") or {}).get("content") or ():
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                last = b["text"]
            if b.get("type") != "tool_use":
                continue
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            if b.get("name") == "Bash":
                c = "$ " + " ".join(str(inp.get("command", "")).split())
                if root:
                    c = c.replace(root + os.sep, "").replace(root, ".")
                if inp.get("run_in_background"):
                    c += " (in the background)"
            else:
                arg = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
                c = "%s %s" % (b.get("name"), rel(str(arg)))
            calls.append(_clip(c, LAST_CALL_MAX))
    return calls, last


def last_attempt_section(attempt, why, transcript_path, root=None, pending=(), earlier=(),
                         folders=()):
    """What the failed attempt before this one did, so the retry need not
    rediscover it. ``pending``: (name, text) of the ``.pending/`` files it left;
    ``earlier``: (attempt, why) of the failed attempts before it; ``folders``:
    every failed attempt's folder, relative to the packet."""
    calls, last = attempt_trail(transcript_path, root)
    out = ["## Last attempt", "",
           "Attempt %d of this step failed: %s. Nothing it wrote to `.pending/` was "
           "kept, but anything it changed elsewhere (such as `work/`) is still there: "
           "check that before redoing it." % (attempt, why), ""]
    if earlier:
        out += ["Earlier attempts at this step:", ""]
        out += ["- Attempt %d failed: %s" % (k, w) for k, w in earlier]
        out.append("")
    if calls:
        shown = calls[-LAST_CALLS:]
        out.append("Its tool calls%s:" % (
            ", the last %d of %d" % (len(shown), len(calls)) if len(shown) < len(calls) else ""))
        out.append("")
        f = _fence("\n".join(shown))
        out += [f] + shown + [f, ""]
    if last:
        f = _fence(last)
        out += ["Its last message:", "", f, _clip(last, LAST_TEXT_MAX), f, ""]
    for name, text in pending:
        f = _fence(text)
        out += ["The `.pending/%s` it left:" % name, "", f, _clip(text, PENDING_MAX), f, ""]
    if folders:
        out += ["The full record of %s in %s: `transcript.jsonl` has every call and "
                "its result. Grep it for what you need; do not read it whole, it is "
                "large." % ("that attempt is" if len(folders) == 1 else "each failed attempt is",
                            ", ".join("`%s/`" % f for f in folders)), ""]
    return "\n".join(out) + "\n"


def handoff_section(handoffs):
    """``handoffs``: the ``handoff`` journal records since the last commit, oldest first."""
    if not handoffs:
        return ""
    out = ["## Hand-off", ""]
    for r in handoffs:
        out.append("Handed back to the runner by %s at %s." % (r.get("by", "?"), r.get("t", "?")))
        if r.get("batch"):
            out += ["", "**New work (batch %d).** The previous instruction is finished, or "
                    "set aside: \"Last step's summary\" below is where it stopped. The instruction "
                    "below is new. `state/` still holds what earlier steps wrote%s." % (
                        r["batch"], "; the old outline is now `%s`, so start a new one if "
                        "the work needs it" % r["outline"] if r.get("outline") else "")]
        for repo, lines in sorted((r.get("commits") or {}).items()):
            out += ["", "They committed %d change%s in `work/%s` since the last step:" % (
                len(lines), "" if len(lines) == 1 else "s", repo), ""]
            out += ["- `%s`" % ln for ln in lines]
        qs, answers = r.get("questions") or [], r.get("answers") or {}
        if qs and (len(qs) > 1 or answers):
            out += ["", "The last step asked, and the answers:", ""]
            for i, q in enumerate(qs, 1):
                a = answers.get(q.get("id"))
                out.append("%d. `%s`: %s" % (i, q.get("id"), q.get("q")))
                out.append("   - Answer: %s" % (a if a else "(no answer)"))
        elif r.get("asked"):
            out.append("")
            out.append("The last step asked: %s" % r["asked"])
        out.append("")
        out.append("Their note:" if r.get("note") else "They left no note.")
        if r.get("note"):
            f = _fence(r["note"])
            out += ["", f, r["note"].rstrip("\n"), f]
        out.append("")
    return "\n".join(out) + "\n"


def build(*, status, last_summary, instruction, step, attempt, max_attempts,
          now, tz, children=(), agent_md=None, state_dir=None, handoffs=(),
          last_attempt="", notes=(), sizes=(), requests=""):
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
        wake_line=wake_line,
        handoff=handoff_section(handoffs) + _notes.section(notes) + requests,
        last_attempt=last_attempt,
        last_summary=(last_summary or "").strip() or "None: this is the first step.",
        children=children_table(children), agent_md=agent,
        state=state_files(state_dir) if state_dir else "Not shown.",
        sizes=sizes_section(sizes), instruction=(instruction or "").strip())


def sizes_section(sizes):
    """The job sizes the next step may ask for (docs/scheduler.md §5.2), or ""
    when the project allows only one. ``sizes``: ``sched.config.Size`` list."""
    if len(sizes) < 2:
        return ""
    out = ["## Job sizes", "",
           "Each step runs in a job of one size. To give the next step a different "
           "one, add `size: <name>` to the memento; it holds for that step only. Ask "
           "for a big job only when the next step will build or simulate.", ""]
    for z in sizes:
        out.append("- `%s`: %s" % (z.name, z.describe()))
    return "\n".join(out) + "\n\n"
