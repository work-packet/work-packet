"""The setup wizard and its terminal pane (docs/setup.md §6, S5-S6)."""

import asyncio
import os
import subprocess
import time

import pytest

pytest.importorskip("textual")
pytest.importorskip("pyte")

from textual.app import App                                    # noqa: E402

from work_packet import project, setup                         # noqa: E402
from work_packet.tui.setup_app import SetupApp                 # noqa: E402
from work_packet.tui.terminal import Terminal                  # noqa: E402

from test_setup import git, home, source                       # noqa: E402,F401


@pytest.fixture
def bash(monkeypatch, tmp_path):
    """bash with an empty home, so no ~/.bashrc runs in the pane."""
    h = tmp_path / "h"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("PS1", "$ ")


async def stage(app, pilot, key):
    await app.show_stage(key)
    await pilot.pause(0.2)            # laid out, so clicks land


async def until(pilot, cond, limit=15.0):
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > limit:
            raise AssertionError("timed out")
        await pilot.pause(0.05)


def test_terminal_runs_a_shell(tmp_path):
    class T(App):
        def compose(self):
            yield Terminal(["/bin/sh"], cwd=str(tmp_path),
                           env=dict(os.environ, PS1="$ "))

    async def run():
        app = T()
        async with app.run_test(size=(80, 20)) as pilot:
            term = app.query_one(Terminal)
            await until(pilot, lambda: term.alive)
            term.write("echo hel''lo; pwd\r")
            await until(pilot, lambda: "\nhello" in term.text())
            assert str(tmp_path) in term.text()
            term.focus()
            await pilot.press("e", "x", "i", "t", "enter")
            await until(pilot, lambda: not term.alive)
    asyncio.run(run())


def label(app, key):
    return str(app.query_one("#lbl-" + key).render())


def test_wizard_end_to_end(home, source, bash):
    project.new("dvs")
    tg = setup.target("dvs")

    async def run():
        app = SetupApp("dvs")
        async with app.run_test(size=(130, 50)) as pilot:
            await until(pilot, lambda: app.checks)
            assert label(app, "instruction").startswith("✗")
            assert label(app, "work").startswith("!")          # no work repos yet
            # S6: clone by hand in the shell; the prompt hook rechecks.
            await until(pilot, lambda: app.term.alive and "[wpk:dvs]" in app.term.text())
            app.term.write("git clone -q %s work/dv-solve\r" % source)
            await until(pilot, lambda: label(app, "work").startswith("✓"))
            # Insert types without Enter.
            app.insert("echo not-run")
            await until(pilot, lambda: "echo not-run" in app.term.text())
            assert "\nnot-run" not in app.term.text()
            app.term.write("\x15")                               # ctrl+u: clear the line
            # The instruction, from the form.
            await stage(app, pilot, "instruction")
            await pilot.click("#t-load")
            await pilot.pause(0.1)
            ta = app.query_one("#instr")
            assert "work/dv-solve/ (branch wpk/dvs)" in ta.text
            await pilot.click("#t-save")
            await until(pilot, lambda: label(app, "instruction").startswith("✓"))
            assert "work/dv-solve" in open(tg.prompt_path).read()
            # Limits: a timeout and Bash.
            await stage(app, pilot, "limits")
            app.query_one("#l-step_timeout").value = "45m"
            app.query_one("#l-tools").value = "Read, Write, Edit, Glob, Grep, Bash"
            await pilot.click("#l-save")
            await until(pilot, lambda: tg.reload().toml.get("step_timeout") == "45m")
            assert "Bash" in tg.toml["permissions"]["allowed_tools"]
            # Hand off.
            await stage(app, pilot, "handoff")
            await until(pilot, lambda: not app.query_one("#handoff-btn").disabled)
            await pilot.click("#handoff-btn")
            await until(pilot, lambda: tg.status()["state"] == "RUNNABLE")
    asyncio.run(run())


def test_wizard_creates_a_project(home, bash, tmp_path):
    async def run():
        app = SetupApp()
        async with app.run_test(size=(130, 50)) as pilot:
            app.query_one("#p-name").value = "fresh"
            await pilot.click("#p-create")
            await until(pilot, lambda: app.tg is not None and app.checks)
            assert setup.held_for_setup(app.tg.status())
            assert app.stage == "work"
    asyncio.run(run())
