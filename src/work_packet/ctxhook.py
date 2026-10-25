"""PostToolUse hook: tell the model when a step's context grows too large,
and pass on notes from the owner.

Claude Code runs this after each tool call (``harness.claude.hook_settings``),
with the hook input as JSON on stdin. It reads the context size of the last
main-thread call from the session transcript and, the first time that
passes the limit (and again at 1.2 times it), adds a message telling the
model to wrap up (context.md C3). A limit of 0 turns that off.

When ``$WPK_WARN_AT`` (epoch seconds) has passed, it says once how many
minutes are left before ``$WPK_DEADLINE``, when the executor kills the
step and its work is lost: step 27 of the dv-solve trial ran the full test
suite four times and was killed at 30 minutes with no warning.

With a notes inbox, it also sends each note there that the step hasn't
seen yet, and records it in the step's ``notes.seen`` (``notes.py``,
docs/interaction.md §6a).

Standalone on purpose: it runs as a file, without the package on the path.
Any error is ignored; a hook must never break the step.

    ctxhook.py <limit> <marker file> [<notes inbox> <notes.seen>]
"""

import json
import os
import sys
import time

TAIL = 1 << 20          # bytes of the transcript searched for the last call

SOFT = ("wpk: this step's context is now about %d tokens (limit %d). Finish the "
        "item in hand without starting another, then write .pending/summary.md and .pending/memento.md "
        "with `resume: now` and an instruction for the remaining work, and stop.")
HARD = ("wpk: this step's context is now about %d tokens, well over the limit of "
        "%d. Stop now: write .pending/summary.md and .pending/memento.md with "
        "`resume: now`, and end the step.")
TIME = ("wpk: about %d of this step's %d minutes are left; at the end the step "
        "is killed and all its work is lost. Finish the item in hand without "
        "starting another long command, then write .pending/summary.md and "
        ".pending/memento.md with `resume: now` and an instruction for the "
        "remaining work, and stop.")


def last_context(path):
    """Context size of the last main-thread assistant message, or None."""
    with open(path, "rb") as fp:
        fp.seek(0, os.SEEK_END)
        fp.seek(max(0, fp.tell() - TAIL))
        lines = fp.read().splitlines()
    for line in reversed(lines):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant" or ev.get("isSidechain"):
            continue
        u = (ev.get("message") or {}).get("usage")
        if isinstance(u, dict):
            return sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                "cache_read_input_tokens"))
    return None


def message(n, limit, fired):
    """(level, text) to send now, or None. ``fired``: levels already sent."""
    if n >= limit * 6 // 5 and "hard" not in fired:
        return "hard", HARD % (n, limit)
    if n >= limit and not fired & {"soft", "hard"}:
        return "soft", SOFT % (n, limit)
    return None


NOTE = ("wpk: a note from the task's owner (%s, %s), sent while this step runs. "
        "It takes precedence over your instruction where they differ; act on it now if "
        "it bears on the work in hand, and record anything that should last:\n\n%s")


def _fired(marker):
    try:
        with open(marker, encoding="utf-8") as fp:
            return set(fp.read().split())
    except FileNotFoundError:
        return set()


def _fire(marker, level):
    with open(marker, "a", encoding="utf-8") as fp:
        fp.write(level + "\n")


def context_message(limit, marker, transcript):
    if limit <= 0:
        return None
    n = last_context(transcript)
    if n is None:
        return None
    out = message(n, limit, _fired(marker))
    if out is None:
        return None
    _fire(marker, out[0])
    return out[1]


def time_message(marker, env, now):
    """The time warning, once, after ``WPK_WARN_AT``; or None."""
    try:
        warn, end = float(env["WPK_WARN_AT"]), float(env["WPK_DEADLINE"])
        start = float(env["WPK_STARTED_AT"])
    except (KeyError, ValueError):
        return None
    if now < warn or "time" in _fired(marker):
        return None
    _fire(marker, "time")
    return TIME % (max(round((end - now) / 60), 1), round((end - start) / 60))


def new_notes(inbox, seen_path):
    """The notes in ``inbox`` not yet in ``seen_path``, oldest first; marks them seen."""
    try:
        names = sorted(n for n in os.listdir(inbox) if n.endswith(".json"))
    except OSError:
        return []
    try:
        with open(seen_path, encoding="utf-8") as fp:
            seen = {ln.split()[0] for ln in fp if ln.split()}
    except FileNotFoundError:
        seen = set()
    out = []
    for name in names:
        try:
            with open(os.path.join(inbox, name), encoding="utf-8") as fp:
                note = json.load(fp)
        except (OSError, ValueError):
            continue
        if not isinstance(note, dict) or not isinstance(note.get("text"), str):
            continue
        note.setdefault("id", name[:-5])
        if note["id"] not in seen:
            out.append(note)
    if out:
        t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(seen_path, "a", encoding="utf-8") as fp:
            for note in out:
                fp.write("%s hook %s\n" % (note["id"], t))
    return [NOTE % (n.get("by") or "the owner", n.get("t") or "", n["text"]) for n in out]


def main(argv):
    limit, marker = int(argv[1]), argv[2]
    hook = json.load(sys.stdin)
    msgs = []
    try:
        m = context_message(limit, marker, hook["transcript_path"])
        if m:
            msgs.append(m)
    except Exception:       # noqa: BLE001 - the notes still go
        pass
    try:
        m = time_message(marker, os.environ, time.time())
        if m:
            msgs.append(m)
    except Exception:       # noqa: BLE001
        pass
    if len(argv) >= 5:
        msgs += new_notes(argv[3], argv[4])
    if not msgs:
        return
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": "\n\n".join(msgs)}}))


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception:       # noqa: BLE001 - never break the step
        pass
    sys.exit(0)
