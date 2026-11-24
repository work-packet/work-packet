"""What a behaviour can do: read the packet, write .pending/, and the faults."""

import os

import yaml


def read(path, default=None):
    try:
        with open(path) as fp:
            return fp.read()
    except FileNotFoundError:
        return default


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fp:
        fp.write(text)


def instruction():
    """The committed memento's body: this step's instruction."""
    text = read("memento.md", "")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[end + 5:]
    return text


def finish(meta, body, summary, fault=""):
    """Write .pending/memento.md and summary.md, applying a fault if asked."""
    if fault == "bad-resume":
        meta = dict(meta, resume="every monday")
    if fault == "bad-memento":
        write(".pending/memento.md", "---\nresume: [now\n---\n" + body)
    else:
        write(".pending/memento.md",
              "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n" + body)
    if fault != "no-summary":
        write(".pending/summary.md", summary)
    if meta.get("resume") in ("done", "fail") and fault != "no-report":
        write(".pending/report.md", report(summary))
    if fault == "write-outside":
        write("state/count.md", "999\n")
        write("state/extra.md", "not allowed\n")
        write("memento.md", "hijacked\n")
    if fault in ("session-hook", "write-journal", "both-journal"):
        # what wpk appends from outside a step (hookcmd, the board), or a record
        # only the runner may write, as a model's Bash `>>` would add it
        import json
        lines = []
        if fault in ("session-hook", "both-journal"):
            lines.append({"type": "session-start", "t": "2026-10-21T18:00:00Z",
                          "by": "you", "session": "s-you", "source": "compact",
                          "actor": {"kind": "claude", "via": "terminal", "session": "s-you"}})
        if fault in ("write-journal", "both-journal"):
            lines.append({"type": "commit-end", "t": "2026-10-21T18:00:00Z", "step": 99})
        with open("journal.jsonl", "a") as fp:
            fp.write("".join(json.dumps(r) + "\n" for r in lines))


def report(outcome, deliverables=()):
    """A completion report (docs/completion-report.md) with ``outcome`` and
    ``deliverables``: (path, what) pairs."""
    meta = {"outcome": outcome.strip().splitlines()[0],
            "deliverables": [{"path": p, "what": w} for p, w in deliverables]}
    return ("---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n"
            "## Outcome\n%s\n\n## Decisions\nnone\n\n## Deliverables\n\n"
            "## Open items\nnone\n" % outcome.strip())
