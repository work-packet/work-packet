import json
import os

import pytest

from work_packet import card
from work_packet.card import Card, Entry

EXAMPLE = """\
---
packet: 1
id: 01JBF3K8Q2V7N0WZ3T5Y6R9M4C
name: uart-overrun
title: UART overrun flag not cleared after LSR read
by: matt
to: runner
origin: gh:featherweight-ip/fw-uart16550#41
work: git:~/work/fw-uart16550@uart-overrun
inputs:
- blob:sha256:9c1e4a
repro: dfm run uart.test_overrun
budget: 5 USD
state: done
updated: '2026-10-27 11:40:12Z'
---
test_overrun fails at 41/67: OE stays set after LSR is read.

## sent · matt · 2026-10-27 09:12:03Z

Brief-Sha: 4be1c0

## accepted · runner · 2026-10-27 09:12:40Z

Working in your clone on branch uart-overrun.

## question q1 · runner · 2026-10-27 10:02:51Z

Clear OE on every LSR read, or only when the FIFO is empty?

Recommend: on every read
Choices: on every read | only when empty

## answer q1 · matt · 2026-10-27 10:30:17Z

On every read.

## result · runner · 2026-10-27 11:40:12Z

OE now clears on every LSR read. Added a read-while-full test; 67/67 pass.

### Detail

```
## note · not · 2026-01-01 00:00:00Z
```

Outcome: done
Deliverable: git:~/work/fw-uart16550@a1b2c3d the fix and the test
Cost: 1.84 USD
Record: run:01JBF3K8Q2V7N0WZ3T5Y6R9M4C@7d3e2a1
"""


def test_example_round_trips_byte_for_byte():
    c = card.parse(EXAMPLE)
    assert c.problems == []
    assert card.render(c) == EXAMPLE
    assert [e.kind for e in c.entries] == ["sent", "accepted", "question", "answer", "result"]
    r = c.entries[-1]
    assert r.get("Outcome") == "done"
    assert r.all("Deliverable") == ["git:~/work/fw-uart16550@a1b2c3d the fix and the test"]
    assert "## note · not" in r.body          # inside a fence: not an entry
    assert c.state() == "done"
    assert c.entries[2].arg == "q1"


def test_smallest_card():
    c = card.parse("---\ntitle: Survey\n---\nFind what's published.\n")
    assert c.title == "Survey" and c.brief == "Find what's published."
    assert c.state() == "draft"
    assert card.check(c) == []


@pytest.mark.parametrize("text", [
    "", "no front matter at all\n", "---\ntitle: x\n", "---\n: : :\n---\nbody",
    "---\ntitle: x\n---\n## sent · a · 2026-10-27 09:12:03Z\n```\nunclosed",
    "## bogus · a · 2026-10-27 09:12:03Z\nhi\n",
])
def test_reader_never_raises(text):
    c = card.parse(text)
    card.render(c)
    json.dumps(c.to_json())


def test_problems_are_listed():
    c = card.parse("---\ntitle: x\n---\nbrief\n\n## sent · a · yesterday\n")
    assert c.entries == [] and c.problems


@pytest.mark.parametrize("body,trailers", [
    ("Outcome: this is body text", []),
    ("Plan: looks like a trailer\nCost: too", [("Cost", "1 USD")]),
    ("## sent · x · 2026-10-27 09:12:03Z", []),
    ("", [("Brief-Sha", "abc")]),
    ("line\n\n\nmore", []),
])
def test_writer_is_canonical(body, trailers):
    c = Card(meta={"title": "t"}, brief="b",
             entries=[Entry("note", "me", "2026-10-27 09:12:03Z", body, trailers)])
    text = card.render(c)
    again = card.parse(text)
    assert card.render(again) == text
    assert again.entries[0].trailers == trailers
    assert len(again.entries) == 1


def test_brief_heading_is_escaped():
    c = Card(meta={"title": "t"}, brief="## sent · x · 2026-10-27 09:12:03Z")
    assert card.parse(card.render(c)).entries == []


def test_states():
    def st(*kinds):
        es = []
        for i, k in enumerate(kinds):
            kind, _, arg = k.partition(" ")
            es.append(Entry(kind, "w", "2026-10-27 09:12:%02dZ" % i, arg=arg or None,
                            trailers=[("Outcome", "failed")] if k == "result-f" else []))
            if k == "result-f":
                es[-1].kind = "result"
        return card.derive_state(es)
    assert st() == "draft"
    assert st("sent") == "open"
    assert st("sent", "accepted") == "working"
    assert st("sent", "accepted", "question a") == "needs-input"
    assert st("sent", "accepted", "question a", "answer a") == "working"
    assert st("sent", "accepted", "result") == "done"
    assert st("sent", "accepted", "result-f") == "failed"
    assert st("sent", "accepted", "result", "request") == "open"
    assert st("sent", "accepted", "result", "closed") == "closed"
    assert st("sent", "declined") == "declined"
    assert st("sent", "cancelled") == "cancelled"


def test_append_is_idempotent_and_refreshes(tmp_path, monkeypatch):
    monkeypatch.setenv("WPK_HOME", str(tmp_path / "home"))
    p = tmp_path / "x.wp.md"
    p.write_text("---\ntitle: X\n---\nDo it.\n")
    e = Entry("sent", "me", "2026-10-27 09:12:03Z")
    card.append(str(p), e)
    c = card.append(str(p), e, Entry("accepted", "runner", "2026-10-27 09:13:00Z"))
    assert [x.kind for x in c.entries] == ["sent", "accepted"]
    on_disk = card.load(str(p))
    assert on_disk.meta["state"] == "working"
    assert on_disk.meta["updated"] == "2026-10-27 09:13:00Z"
    assert card.check(on_disk, p.read_text()) == []


def test_merge_is_a_union():
    a = card.parse(EXAMPLE)
    b = card.parse(EXAMPLE)
    b.entries.append(Entry("closed", "matt", "2026-10-28 00:00:00Z"))
    m = card.merge(a, b)
    assert len(m.entries) == 6 and m.state() == "closed"


def test_ulid():
    a, b = card.new_id(1000), card.new_id(2000)
    assert len(a) == 26 and a < b


def test_find_up(tmp_path):
    d = tmp_path / "uart" / "fw-uart16550" / "src"
    d.mkdir(parents=True)
    (tmp_path / "uart" / "uart.wp.md").write_text("---\ntitle: t\n---\n")
    assert card.find_up(str(d)) == str(tmp_path / "uart" / "uart.wp.md")
    assert card.find_up(str(tmp_path)) is None


def test_check_flags():
    c = card.parse("---\nname: Bad_Name\nstate: done\n---\n\n## question · a · 2026-10-27 09:12:03Z\n")
    msgs = " ".join(m for _, m in card.check(c))
    assert "no title" in msgs and "Bad_Name" in msgs and "no id" in msgs and "cached state" in msgs
