"""The /wpk-checkpoint skill (docs/session-checkpoint.md §4.1)."""

import os

from work_packet import frontmatter, skills


def test_dirs_follow_the_harness_homes(tmp_path):
    import importlib
    real = importlib.reload(skills)         # the real dirs(), not conftest's
    try:
        assert real.dirs({"WPK_SKILLS_DIRS": "/a" + os.pathsep + "/b"}) == ["/a", "/b"]
        got = real.dirs({"CLAUDE_CONFIG_DIR": "/c", "CODEX_HOME": "/x"})
        assert got == ["/c/skills", "/x/skills"]
        home = os.path.expanduser("~")
        assert real.dirs({}) == [os.path.join(home, ".claude", "skills"),
                                 os.path.join(home, ".codex", "skills")]
    finally:
        importlib.reload(skills)


def test_install(tmp_path, monkeypatch):
    d = [str(tmp_path / "claude"), str(tmp_path / "codex")]
    monkeypatch.setattr(skills, "dirs", lambda environ=None: d)
    got = skills.install()
    assert got == [os.path.join(x, "wpk-checkpoint", "SKILL.md") for x in d]
    meta, body = frontmatter.load(got[0])
    assert meta["name"] == "wpk-checkpoint" and "WPK_WPID" in body
    assert "checkpoint -m" in body and skills.MARK in body
    assert skills.install() == []                       # already current
    with open(got[1], "w") as fp:                       # someone made it their own
        fp.write("mine\n")
    with open(got[0], "a") as fp:                       # ours, but changed
        fp.write("old\n")
    assert skills.install() == [got[0]]
    assert open(got[1]).read() == "mine\n"


def test_opening_an_editor_installs_it(tmp_path, fake, monkeypatch):
    from test_dash_tasks import _new
    from work_packet import ide
    monkeypatch.chdir(tmp_path)
    _new("a")
    ide.resolve("a")
    assert all(os.path.isfile(os.path.join(x, "wpk-checkpoint", "SKILL.md"))
               for x in skills.dirs())
