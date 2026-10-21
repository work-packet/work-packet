import pytest

from work_packet import frontmatter
from work_packet.frontmatter import FrontMatterError


@pytest.mark.parametrize("meta,body", [
    ({"a": 1}, "body\n"),
    ({}, "body only\n"),
    ({"a": 1}, ""),
    ({"updated": "2026-10-21T18:02:11Z", "wake_at": None}, "x"),
    ({"wpk": "0.2", "n": 0, "ok": True, "f": 1.5}, ""),
    ({"spawn": [{"name": "hello", "instruction": "line one\nline two\n",
                 "copy": ["*.md"]}]}, "Next.\n"),
    ({"reason": "it's: tricky # not a comment"}, "\n\nlead blank lines\n"),
    ({"ünï": "cødé"}, "---\nnot a fence inside the body\n---\n"),
])
def test_round_trip(meta, body):
    assert frontmatter.parse(frontmatter.dump(meta, body)) == (meta, body)


def test_timestamps_stay_strings():
    meta, _ = frontmatter.parse("---\nupdated: 2026-10-21T18:02:11Z\nd: 2026-10-21\n---\n")
    assert meta == {"updated": "2026-10-21T18:02:11Z", "d": "2026-10-21"}


def test_no_front_matter():
    assert frontmatter.parse("just text\n") == (None, "just text\n")
    assert frontmatter.dump(None, "just text\n") == "just text\n"


def test_empty_front_matter():
    assert frontmatter.parse("---\n---\nbody") == ({}, "body")


def test_crlf():
    assert frontmatter.parse("---\r\na: 1\r\n---\r\nbody\r\n") == ({"a": 1}, "body\n")


@pytest.mark.parametrize("text,why", [
    ("---\na: 1\nbody\n", "closing"),
    ("---\na: [1\n---\n", "YAML"),
    ("---\n- a\n- b\n---\n", "mapping"),
    ("---\njust a string\n---\n", "mapping"),
])
def test_errors(text, why):
    with pytest.raises(FrontMatterError, match=why):
        frontmatter.parse(text)
