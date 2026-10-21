"""journal.jsonl: append records, read them back."""

import json
from dataclasses import dataclass, field
from typing import List

from . import fsutil


@dataclass
class Journal:
    records: List[dict] = field(default_factory=list)
    bad_lines: List[int] = field(default_factory=list)   # 1-based, not JSON
    truncated_tail: bool = False                         # last line has no newline


def append(path, rec):
    fsutil.append_line(path, json.dumps(rec, sort_keys=False, separators=(",", ":")))


def read(path):
    """Read every record. A torn last line (crash mid-append) is noted, not raised."""
    j = Journal()
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = fp.read()
    except FileNotFoundError:
        return j
    if not data:
        return j
    lines = data.split("\n")
    if lines[-1] == "":
        lines.pop()
    else:
        j.truncated_tail = True
    for i, line in enumerate(lines, 1):
        last = i == len(lines)
        try:
            rec = json.loads(line)
        except ValueError:
            if not (last and j.truncated_tail):
                j.bad_lines.append(i)
            continue
        if last and j.truncated_tail:
            # Parsed, but was never terminated: treat as not written.
            continue
        j.records.append(rec)
    return j
