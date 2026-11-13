"""Parsed files are reused while they don't change (docs/cpu-plan.md P2)."""

import os

import pytest

from work_packet import frontmatter, fsutil, journal


@pytest.fixture(autouse=True)
def fresh():
    fsutil.cache_clear()
    yield
    fsutil.cache_clear()


def counting(parse):
    n = [0]

    def f(path):
        n[0] += 1
        return parse(path)
    return f, n


def test_an_unchanged_file_is_parsed_once_and_each_caller_gets_a_copy(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"k": [1]}')
    parse, n = counting(fsutil._load_json)
    a = fsutil.cached(str(p), parse, "t")
    a["k"].append(2)                                     # a caller changes its copy
    b = fsutil.cached(str(p), parse, "t")
    assert n[0] == 1 and b == {"k": [1]}


def test_a_change_of_the_same_size_is_seen(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"k": 1}')
    assert fsutil.load_json(str(p)) == {"k": 1}
    st = os.stat(p)
    with open(p, "w") as fp:                             # in place, same size
        fp.write('{"k": 2}')
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1000))
    assert fsutil.load_json(str(p)) == {"k": 2}


def test_an_atomic_replace_is_seen(tmp_path):
    p = str(tmp_path / "status.md")
    fsutil.atomic_write(p, frontmatter.dump({"state": "READY"}, "x"))
    assert frontmatter.load(p)[0]["state"] == "READY"
    fsutil.atomic_write(p, frontmatter.dump({"state": "ACTIVE"}, "x"))
    assert frontmatter.load(p)[0]["state"] == "ACTIVE"


def test_an_append_is_seen(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    journal.append(p, {"type": "a"})
    assert [r["type"] for r in journal.read(p).records] == ["a"]
    journal.append(p, {"type": "b"})
    assert [r["type"] for r in journal.read(p).records] == ["a", "b"]


def test_a_missing_file_or_a_bad_parse_is_not_kept(tmp_path):
    p = tmp_path / "a.json"
    with pytest.raises(OSError):
        fsutil.load_json(str(p))
    p.write_text("{not json")
    with pytest.raises(ValueError):
        fsutil.load_json(str(p))
    p.write_text('{"k": 1}')
    assert fsutil.load_json(str(p)) == {"k": 1}


def test_text_is_kept_without_copying(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("hello")
    parse, n = counting(fsutil.read_text)
    assert fsutil.cached(str(p), parse, "text", copy=False) == "hello"
    assert fsutil.cached(str(p), parse, "text", copy=False) == "hello" and n[0] == 1


def test_the_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(fsutil, "CACHE_MAX", 3)
    for i in range(5):
        p = tmp_path / ("%d.json" % i)
        p.write_text("{}")
        fsutil.load_json(str(p))
    assert len(fsutil._cache) == 3


def test_a_transcript_feed_reads_only_what_was_appended(tmp_path, monkeypatch):
    import json
    from work_packet.dash import data
    p = str(tmp_path / "transcript.jsonl")

    def say(text, nl=True):
        line = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": text}]}})
        with open(p, "a") as fp:
            fp.write(line + ("\n" if nl else ""))
    say("one")
    assert [e["label"] for e in data.activity(p)["events"]] == ["one"]
    say("two", nl=False)                                 # still being written
    assert [e["label"] for e in data.activity(p)["events"]] == ["one", "two"]
    with open(p, "a") as fp:
        fp.write("\n")
    seen = []
    real = data._feed_line
    monkeypatch.setattr(data, "_feed_line", lambda f, line: (seen.append(line), real(f, line)))
    say("three")
    assert [e["label"] for e in data.activity(p)["events"]] == ["one", "two", "three"]
    assert len(seen) == 2                                # "two" and "three", not "one"
    fsutil.atomic_write(p, "")                           # replaced: start over
    assert data.activity(p)["events"] == []
