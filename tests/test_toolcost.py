"""What burns context inside a step (docs/token-dashboard.md, view 5)."""

import json
import os

from work_packet import toolcost
from work_packet.cli import main


def call(i, ctx, *uses):
    return {"type": "assistant", "parent_tool_use_id": None,
            "message": {"id": "m%d" % i, "content": [
                {"type": "tool_use", "id": u, "name": n, "input": inp} for u, n, inp in uses],
                "usage": {"cache_read_input_tokens": ctx - 10, "cache_creation_input_tokens": 10,
                          "input_tokens": 0}}}


def result(u, text, error=False):
    return {"type": "user", "parent_tool_use_id": None, "message": {"content": [
        {"type": "tool_result", "tool_use_id": u, "content": text, "is_error": error}]}}


def write(path, evs):
    with open(path, "w") as fp:
        for e in evs:
            fp.write(json.dumps(e) + "\n")


def transcript(path):
    # 1000 prompt; a 2350-char read (1000 tokens) and a 235-char command (100);
    # each turn adds 50 of its own; the same lines are read again later.
    write(path, [
        {"type": "system", "subtype": "init", "cwd": "/w"},
        call(0, 1000, ("a", "Read", {"file_path": "/w/src/x.c"}),
             ("b", "Bash", {"command": "cd /w && FOO=1 python -m pytest -q \\\n  tests"})),
        result("a", "x" * 2350), result("b", "y" * 235, error=True),
        call(1, 2150, ("c", "Read", {"file_path": "/w/src/x.c", "offset": 10, "limit": 5})),
        result("c", "z" * 235),
        {"type": "assistant", "parent_tool_use_id": "sub", "message": {"id": "s", "content": [],
                                                                      "usage": {"input_tokens": 9999}}},
        call(2, 2300),
    ])


def test_attribution_splits_the_context_exactly(tmp_path):
    p = str(tmp_path / "transcript.jsonl")
    transcript(p)
    a = toolcost.attribute(p)
    assert a["calls"] == 3 and a["context"] == 1000 + 2150 + 2300
    read, bash, again = a["results"]
    assert (read["tool"], read["target"], read["tokens"], read["reads"]) == ("Read", "src/x.c", 1000, 2)
    assert (bash["kind"], bash["error"], bash["tokens"], bash["carried"]) == \
        ("python -m pytest", True, 100, 200)
    assert (again["tokens"], again["call"], again["carried"]) == (100, 2, 100)
    assert a["prompt"] == {"tokens": 1000, "carried": 3000}
    assert a["turns"] == {"tokens": 100, "carried": 150}
    carried = a["prompt"]["carried"] + a["turns"]["carried"] + sum(x["carried"] for x in a["results"])
    assert carried == a["context"]
    assert [r["label"] for r in toolcost.rollup([a])] == ["(prompt)", "Read", "Bash", "(model turns)"]
    (rep,) = toolcost.repeats([a])
    assert (rep["target"], rep["n"], rep["carried"]) == ("src/x.c", 1, 100)
    assert toolcost.attribute(str(tmp_path / "none")) is None


def test_growth_smaller_than_the_text_caps_the_results(tmp_path):
    p = str(tmp_path / "t.jsonl")
    write(p, [call(0, 100, ("a", "Bash", {"command": "ls"})), result("a", "q" * 2350),
              call(1, 600)])
    (r,) = toolcost.attribute(p)["results"]
    assert r["tokens"] == 500


def test_command_kind():
    k = toolcost.command_kind
    assert k("cd /x && make -j8 2>&1 | tail") == "make"
    assert k("timeout 60 uv run pytest -x") == "uv run pytest"
    assert k("A=1 B=2 /usr/bin/python3.12 -m pip install x") == "python -m pip"
    assert k("") == ""


def test_stats_tools_cli(tmp_path, capsys, fake):
    from conftest import make_project
    from work_packet import executor
    proj, root = make_project(tmp_path)
    assert executor.step(proj).code == 0
    transcript(os.path.join(root.step_dir(1), "transcript.jsonl"))
    assert main(["stats", proj, "--tools"]) == 0
    out = capsys.readouterr().out
    assert "(prompt)" in out and "Lines read again" in out and "src/x.c" in out
    assert main(["stats", proj, "--tools", "kind", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert "python -m pytest" in [r["label"] for r in rows]
