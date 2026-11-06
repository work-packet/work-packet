"""Presence (docs/collaboration.md §4.2, §5.1): who is working on a project, from
heartbeat records, and the runner holding off while they are there."""

import json
import os

import pytest

from work_packet import presence

T = 1_800_000_000.0


def _ts(t):
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def test_beat_read_and_expire(tmp_path):
    proj = str(tmp_path)
    r = presence.beat(proj, "claude-s1", T, kind="claude", turn="working", session="s1",
                      prompt="SENTINEL never kept")
    assert r["since"] == T and r["beat"] == T and r["turn_since"] == T
    assert "prompt" not in json.load(open(presence.path(proj, "claude-s1")))
    presence.beat(proj, "claude-s1", T + 30, turn="working")
    r = presence.get(proj, "claude-s1")
    assert r["since"] == T and r["turn_since"] == T and r["beat"] == T + 30
    presence.beat(proj, "claude-s1", T + 60, turn="waiting")
    assert presence.get(proj, "claude-s1")["turn_since"] == T + 60
    assert [x["source"] for x in presence.records(proj, T + 60)] == ["claude-s1"]
    assert presence.records(proj, T + 60 + presence.TTL_S + 1) == []      # silent: gone
    assert len(presence.records(proj, T + 60 + presence.TTL_S + 1, ttl=None)) == 1


def test_end_and_cleanup(tmp_path):
    proj = str(tmp_path)
    presence.beat(proj, "shell-a", T, kind="shell")
    presence.end(proj, "shell-a", T + 5)
    assert presence.records(proj, T + 6) == []
    assert os.path.exists(presence.path(proj, "shell-a"))
    presence.records(proj, T + 5 + presence.KEEP_ENDED_S + 1)
    assert not os.path.exists(presence.path(proj, "shell-a"))
    # a new session under an old id starts afresh
    presence.beat(proj, "shell-b", T, kind="shell")
    presence.end(proj, "shell-b", T + 1)
    r = presence.beat(proj, "shell-b", T + 2, kind="shell")
    assert r["since"] == T + 2


def test_source_names_are_safe(tmp_path):
    p = presence.path(str(tmp_path), "../../etc/passwd")
    assert os.path.dirname(p) == os.path.join(str(tmp_path), "presence")


def test_a_web_tab_alone_counts_for_two_hours(tmp_path):
    proj = str(tmp_path)
    presence.beat(proj, "ide-web-k-t1", T, kind="ide-web", visible=False, attached=True)
    assert presence.attended(proj, T + 60) == (True, T)
    later = T + presence.ATTACH_CAP_S + 60
    presence.beat(proj, "ide-web-k-t1", later, visible=False)        # still attached, hidden
    assert presence.attended(proj, later) == (False, None)
    presence.beat(proj, "ide-web-k-t1", later + 1, visible=True, active=later + 1)
    assert presence.attended(proj, later + 2)[0]
    # or anything else beating: Claude in that tab
    presence.beat(proj, "ide-web-k-t1", later + 3, visible=False, active=None)
    presence.beat(proj, "claude-x", later + 3 + presence.ATTACH_CAP_S, kind="claude")
    assert presence.attended(proj, later + 4 + presence.ATTACH_CAP_S)[0]


def test_reap_ends_gone_processes(tmp_path):
    proj = str(tmp_path)
    presence.beat(proj, "claude-a", T, kind="claude", host="h1", pid=11)
    presence.beat(proj, "claude-b", T, kind="claude", host="h1", pid=12)
    presence.beat(proj, "claude-c", T, kind="claude", host="h2", pid=11)
    assert presence.reap(proj, "h1", T + 1, alive=lambda pid: pid == 12) == 1
    assert sorted(r["source"] for r in presence.records(proj, T + 2)) == ["claude-b", "claude-c"]


def test_where():
    recs = [{"kind": "ide-web", "via": "ide-web"},
            {"kind": "claude", "via": "ide-web", "turn": "blocked"},
            {"kind": "claude", "via": "ide-web", "turn": "working"}]
    assert presence.where(recs) == "VS Code (web) · Claude ×2 (1 blocked)"
    assert presence.where([{"kind": "claude", "via": "terminal", "turn": "waiting"}]) == \
        "a terminal · Claude ×1 (1 waiting)"


def test_find_project(tmp_path):
    folder = tmp_path / "pkt"
    (folder / ".work-packet").mkdir(parents=True)
    (folder / ".work-packet" / "project.toml").write_text("name = 'p'\n")
    (folder / "src" / "deep").mkdir(parents=True)
    assert presence.find_project(str(folder / "src" / "deep")) == str(folder / ".work-packet")
    legacy = tmp_path / "old"
    (legacy / "packets" / "w" / "work" / "repo").mkdir(parents=True)
    (legacy / "project.toml").write_text("name = 'o'\n")
    assert presence.find_project(str(legacy / "packets" / "w" / "work" / "repo")) == str(legacy)
    assert presence.find_project(str(tmp_path)) is None


def _journal(tmp_path, *recs):
    p = tmp_path / "journal.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return str(p)


@pytest.mark.parametrize("handoff,held", [
    (None, True),                                         # you came: it waits
    ({"defer": False, "dt": -600}, True),                 # handed off before you came
    ({"defer": False, "dt": 30}, False),                  # handed off while you were there
    ({"defer": True, "dt": 30}, True),                    # "after I leave"
])
def test_holds(tmp_path, handoff, held):
    proj = str(tmp_path / "proj")
    os.makedirs(proj)
    presence.beat(proj, "claude-s", T, kind="claude", via="ide-web")
    recs = [{"type": "admin", "op": "pause", "t": _ts(T - 900)}]
    if handoff:
        recs.append({"type": "handoff", "t": _ts(T + handoff["dt"]), "defer": handoff["defer"]})
    j = _journal(tmp_path, *recs)
    why = presence.holds(proj, [j], T + 60)
    assert bool(why) == held
    if held:
        assert "VS Code (web)" in why or "ide-web" in why
    assert presence.holds(proj, [j], T + 60 + presence.TTL_S + 1) is None   # you left


def test_a_resume_while_present_counts_as_a_go_ahead(tmp_path):
    proj = str(tmp_path / "proj")
    os.makedirs(proj)
    presence.beat(proj, "shell-1", T, kind="shell")
    j = _journal(tmp_path, {"type": "admin", "op": "resume", "t": _ts(T + 10), "defer": False})
    assert presence.holds(proj, [j], T + 20) is None
