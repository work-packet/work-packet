"""Task templates: find, load, check (docs/prompt-intake.md §4, T1)."""

import json
import os

import pytest

from work_packet import cli, registry, templates

from test_setup import home                                  # noqa: F401


GOOD = """\
---
name: regress-test
title: Reproduce a bug as a regression test
starter: clone

params:
  issue: {kind: text, required: true, help: issue number}
  fix:   {kind: bool, default: true, ask: true}
  repo:  {kind: repo, default: "@verilator"}
  branch: {kind: text, default: "wpk/issue-{{ issue }}"}

recipe:
  clone:  "{{ repo }}"
  branch: "{{ branch }}"
  model:  sonnet

setup:
  run: [make prep]

deliver:
  do:   draft-pr
  gate: "make t_{{ issue }}"
---
Reproduce issue #{{ issue }} as a test.
{% if fix %}
Then fix it.
{% endif %}
"""


def _write(d, name, text):
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name + templates.SUFFIX)
    with open(p, "w") as fp:
        fp.write(text)
    return p


def _board(name):
    registry.new_board(name)


def _msgs(t):
    return [(p.level, p.line, p.msg) for p in templates.check(t)]


def test_good_template_loads_and_checks(home):
    p = _write(templates.global_dir(), "regress-test", GOOD)
    t = templates.load(p)
    assert t.name == "regress-test" and t.starter == "clone"
    assert t.key_params() == ["issue", "fix"]
    assert t.body_line == 24 and t.body.startswith("Reproduce")
    assert t.line("deliver", "gate") == 22
    assert templates.check(t) == []


def test_board_wins_by_name_and_board_key_limits(home):
    _board("vl")
    _write(templates.global_dir(), "a", GOOD.replace("regress-test", "a"))
    _write(templates.global_dir(), "only-vl",
           GOOD.replace("regress-test", "only-vl").replace("starter: clone",
                                                           "starter: clone\nboard: vl"))
    _write(templates.board_dir("vl"), "a",
           GOOD.replace("regress-test", "a").replace("Reproduce a bug", "Board A"))
    assert [t.name for t in templates.templates()] == ["a"]
    on_vl = templates.templates("vl")
    assert [(t.name, t.scope) for t in on_vl] == [("a", "board"), ("only-vl", "global")]
    assert templates.get("a", "vl").title.startswith("Board A")
    assert templates.get("only-vl", "main") is None


def test_yaml_error_names_the_line(home):
    p = _write(templates.global_dir(), "bad", "---\nname: bad\nparams: [unclosed\n---\nx\n")
    with pytest.raises(templates.TemplateError) as e:
        templates.load(p)
    assert str(e.value).startswith(p + ":") and "YAML" in e.value.msg


def test_no_front_matter(home):
    p = _write(templates.global_dir(), "bare", "just text\n")
    with pytest.raises(templates.TemplateError, match="no front matter"):
        templates.load(p)
    ts, broken = templates.scan()
    assert ts == [] and len(broken) == 1


@pytest.mark.parametrize("edit, line, frag", [
    (("{{ issue }} as a test", "{{ isue }} as a test"), 24, "{{ isue }} is not a parameter"),
    (("gate: \"make t_{{ issue }}\"", "gate: \"make t_{{ issue \""), 22, "deliver.gate"),
    (("{% endif %}", ""), 26, "Unexpected end of template"),
    (("  model:  sonnet", "  model:  sonnet\n  colour: red"), 16, "takes no 'colour'"),
    (("  model:  sonnet", "  model:  sonnet\n  objective: hi"), 16, "objective is the"),
    (("kind: bool,", "kind: boolean,"), 8, "kind 'boolean'"),
    (("do:   draft-pr", "do:   merge"), 21, "deliver.do"),
    (("starter: clone", "starter: nope"), 4, "no starter 'nope'"),
    (("name: regress-test", "name: other"), 2, "not the file's"),
    (("run: [make prep]", "run: make prep"), 18, "setup.run"),
])
def test_errors_name_their_line(home, edit, line, frag):
    p = _write(templates.global_dir(), "regress-test", GOOD.replace(*edit))
    probs = [(lv, ln, m) for lv, ln, m in _msgs(templates.load(p)) if lv == "error"]
    assert any(ln == line and frag in m for _, ln, m in probs), probs


def test_default_may_use_only_earlier_params(home):
    text = GOOD.replace('  issue: {kind: text, required: true, help: issue number}\n', '') \
               .replace('  repo:  {kind: repo, default: "@verilator"}',
                        '  repo:  {kind: repo, default: "@verilator"}\n'
                        '  issue: {kind: text, required: true}')
    p = _write(templates.global_dir(), "regress-test", text)
    msgs = [m for _, _, m in _msgs(templates.load(p))]
    assert any("params.branch.default" in m for m in msgs) is False   # issue is before branch
    text2 = text.replace('  branch: {kind: text, default: "wpk/issue-{{ issue }}"}\n', '') \
                .replace('  fix:   {kind: bool, default: true, ask: true}',
                         '  fix:   {kind: bool, default: true, ask: true}\n'
                         '  branch: {kind: text, default: "wpk/issue-{{ issue }}"}')
    p = _write(templates.global_dir(), "regress-test", text2)
    msgs = [m for _, _, m in _msgs(templates.load(p))]
    assert any("params.branch.default: {{ issue }}" in m for m in msgs), msgs


def test_required_starter_field(home):
    p = _write(templates.global_dir(), "regress-test",
               GOOD.replace('  clone:  "{{ repo }}"\n', ''))
    assert any("needs Repo" in m for _, _, m in _msgs(templates.load(p)))


def test_prompt_file(home):
    d = templates.global_dir()
    text = GOOD.split("---\n", 2)
    spec = "---\n" + text[1].rstrip("\n") + "\nprompt: p.md.j2\n---\n"
    p = _write(d, "regress-test", spec)
    with open(os.path.join(d, "p.md.j2"), "w") as fp:
        fp.write("Fix {{ issue }}\nand {{ nope }}\n")
    t = templates.load(p)
    assert t.prompt_text().startswith("Fix")
    msgs = _msgs(t)
    assert any("p.md.j2" in m and "{{ nope }}" in m for _, _, m in msgs), msgs
    p = _write(d, "regress-test", spec + "a body too\n")
    assert any("one or the other" in m for _, _, m in _msgs(templates.load(p)))


def test_board_key_mismatch_warns(home):
    _board("vl")
    p = _write(templates.board_dir("vl"), "x",
               GOOD.replace("regress-test", "x").replace("starter: clone",
                                                         "starter: clone\nboard: other"))
    t = templates.load(p, "board", "vl")
    assert any(lv == "warning" and "never offered" in m for lv, _, m in _msgs(t))


# --- CLI ---------------------------------------------------------------------------

def _run(capsys, *argv):
    rc = cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_list_show_check(home, capsys):
    _write(templates.global_dir(), "regress-test", GOOD)
    rc, out, _ = _run(capsys, "template", "list")
    assert rc == 0 and "regress-test" in out and "asks: issue, fix" in out
    rc, out, _ = _run(capsys, "template", "list", "--json")
    d = json.loads(out)
    assert d["board"] == "main" and d["templates"][0]["key"] == ["issue", "fix"]
    rc, out, _ = _run(capsys, "template", "show", "regress-test")
    assert rc == 0 and "* issue" in out and "Reproduce issue #{{ issue }}" in out
    rc, out, _ = _run(capsys, "template", "show", "regress-test", "--json")
    assert json.loads(out)["spec"]["recipe"]["model"] == "sonnet"
    rc, out, err = _run(capsys, "template", "show", "nope")
    assert rc == 2 and "there are: regress-test" in err
    rc, out, _ = _run(capsys, "template", "check")
    assert rc == 0 and "1 template checked: no errors" in out


def test_cli_check_fails_with_file_and_line(home, capsys):
    p = _write(templates.global_dir(), "regress-test", GOOD.replace("{{ issue }} as", "{{ x }} as"))
    rc, out, _ = _run(capsys, "template", "check")
    assert rc == 1 and ("%s:24: error:" % p) in out
    rc, out, _ = _run(capsys, "template", "check", p)
    assert rc == 1


def test_cli_empty(home, capsys):
    rc, out, _ = _run(capsys, "template")
    assert rc == 0 and "No templates" in out


def test_unknown_name_points_at_its_line(home):
    p = _write(templates.global_dir(), "regress-test",
               GOOD.replace("Then fix it.", "Then fix {{ thing }}."))
    assert any(ln == 26 and "{{ thing }}" in m for _, ln, m in _msgs(templates.load(p)))


# --- T2: rendering -------------------------------------------------------------------

from test_setup import source                                # noqa: F401,E402

FIX = """\
---
title: Fix an issue
starter: clone
params:
  repo:  {kind: repo, required: true}
  issue: {kind: int, required: true}
  tests: {kind: bool, default: true, ask: true}
  area:  {kind: choice, choices: [core, sim], default: core}
  branch: {kind: text, default: "wpk/issue-{{ issue }}"}
recipe:
  clone: "{{ repo }}"
  branch: "{{ branch }}"
  name: "{{ repo.name }}-{{ issue }}"
deliver: {do: push, gate: "make t{{ issue }}"}
inputs:
  why.md: "Issue {{ issue }} on {{ board }}\\n"
---
{% include "_head.md" %}
Fix issue #{{ issue }} in {{ repo.name }} ({{ area }}).
{% if tests %}
Add a regression test first.
{% endif %}
Done.
"""


def _repo_config(source):
    h = registry.home()
    os.makedirs(h, exist_ok=True)
    with open(os.path.join(h, "config.toml"), "a") as fp:
        fp.write('\n[[repo]]\nname = "dvs"\nurl = "%s"\n' % source)


def _fix(home):
    d = templates.global_dir()
    _write(d, "fix", FIX)
    with open(os.path.join(d, "_head.md"), "w") as fp:
        fp.write("Read the notes first.\n")


def test_render_recipe(home, source, tmp_path):
    _repo_config(source)
    _fix(home)
    r = templates.recipe("fix", {"repo": "@dvs", "issue": "#12", "tests": "no",
                                 "dir": str(tmp_path)})
    assert r["name"] == "dvs-12"
    assert r["clone"] == {"url": str(source), "branch": "wpk/issue-12"}
    assert r["objective"] == ("Read the notes first.\nFix issue #12 in dvs (core).\n"
                              "Done.\n")
    assert r["deliver"] == {"do": "push", "gate": "make t12"}
    assert r["inputs"] == [{"name": "why.md", "text": "Issue 12 on main\n"}]
    assert r["origin"]["template"] == "fix" and r["origin"]["registry"] == "dvs"
    r = templates.recipe("fix", {"repo": "@dvs", "issue": 3, "area": "sim",
                                 "branch": "mine", "name": "x", "dir": str(tmp_path)})
    assert r["name"] == "x" and r["clone"]["branch"] == "mine"
    assert "Add a regression test first.\n" in r["objective"] and "(sim)" in r["objective"]


@pytest.mark.parametrize("given, frag", [
    ({"repo": "@dvs"}, "needs issue"),
    ({}, "needs repo, issue"),
    ({"repo": "@dvs", "issue": "x"}, "issue: a whole number"),
    ({"repo": "@dvs", "issue": 1, "tests": "maybe"}, "tests: yes or no"),
    ({"repo": "@dvs", "issue": 1, "area": "gui"}, "area: one of core, sim"),
    ({"repo": "@dvs", "issue": 1, "colour": "red"}, "no parameter colour"),
])
def test_render_refusals(home, source, tmp_path, given, frag):
    _repo_config(source)
    _fix(home)
    with pytest.raises(templates.RenderError, match=frag):
        templates.recipe("fix", dict(given, dir=str(tmp_path)))


def test_render_refuses_a_broken_template(home):
    _write(templates.global_dir(), "b", "---\nstarter: folder\n---\n{{ nope }}\n")
    with pytest.raises(templates.RenderError, match="(?s)has errors.*nope"):
        templates.recipe("b", {})


def test_param_fills_starter_field(home, source, tmp_path):
    _write(templates.global_dir(), "c", "---\nstarter: clone\nparams:\n"
           "  clone: {kind: repo, required: true}\n---\nWork.\n")
    r = templates.recipe("c", {"clone": str(source), "dir": str(tmp_path)})
    assert r["clone"]["url"] == str(source) and r["objective"] == "Work.\n"


def test_cli_start_from_template(home, source, tmp_path, capsys):
    from work_packet.tomlio import load_toml
    _repo_config(source)
    _fix(home)
    rc, out, err = _run(capsys, "start", "fix", "repo=@dvs", "issue=7",
                        "dir=%s" % tmp_path, "--dry-run", "--json")
    assert rc == 0, err
    assert json.loads(out)["recipe"]["origin"]["template"] == "fix"
    rc, out, err = _run(capsys, "start", "fix", "repo=@dvs", "dir=%s" % tmp_path)
    assert rc == 4 and "needs issue" in err
    rc, out, err = _run(capsys, "start", "fix", "repo=@dvs", "issue=7", "dir=%s" % tmp_path)
    assert rc == 0, err
    assert "from template fix" in out
    e = registry.get("dvs-7")
    o = load_toml(os.path.join(e["path"], "project.toml"))["origin"]
    assert o["template"] == "fix"
    rc, out, _ = _run(capsys, "start", "--list")
    assert "Templates" in out and "fix" in out


def test_batch_with_templates(home, source, tmp_path, monkeypatch, capsys):
    _repo_config(source)
    _fix(home)
    items = [{"template": "fix", "repo": "@dvs", "issue": n, "dir": str(tmp_path)}
             for n in (1, 2)]
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(items)))
    rc, out, err = _run(capsys, "start", "--recipes", "-", "--dry-run", "--json")
    assert rc == 0, err
    assert [x["recipe"]["name"] for x in json.loads(out)] == ["dvs-1", "dvs-2"]


def test_board_template_and_shadow_warning(home, tmp_path):
    registry.new_board("vl")
    _write(templates.board_dir("vl"), "b", "---\nstarter: folder\n---\nOn {{ board }}.\n")
    r = templates.recipe("b", {"dir": str(tmp_path), "name": "bb"}, board="vl")
    assert r["objective"] == "On vl.\n" and r["board"] == "vl"
    p = _write(templates.global_dir(), "clone", "---\nstarter: folder\n---\nx\n")
    assert any(lv == "warning" and "starter's name" in m
               for lv, _, m in _msgs(templates.load(p)))
