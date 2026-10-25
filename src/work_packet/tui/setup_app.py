"""``wpk setup``: the setup wizard (docs/setup.md §6).

Stages on the left (the check groups), the selected stage's checks and form
on the right, and a shell under them. The checks are ``setup.readiness``,
the same as ``wpk doctor``; every form writes through the same helpers.
After each command typed in the shell (bash's PROMPT_COMMAND touches
``.setup/tick``) the checks run again.
"""

import os
import shlex
import subprocess

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, RichLog, \
    Select, Static, TextArea

from .. import executor, project, schema, setup
from ..packet import Packet
from .terminal import Terminal

STAGES = (
    ("project", "Project", ("tools", "project")),
    ("work", "Work repos", ("work",)),
    ("inputs", "Inputs", ("inputs",)),
    ("instruction", "Instruction", ("instruction",)),
    ("limits", "Limits", ("limits",)),
    ("handoff", "Hand off", ()),
)
MARK = {"ok": "[green]✓[/]", "info": "[dim]·[/]", "warn": "[yellow]![/]",
        "missing": "[red]✗[/]", "none": "[dim]·[/]"}
LEVEL_ORDER = ("none", "ok", "info", "warn", "missing")


def _esc(text):
    return text.replace("[", r"\[")


def _stage_level(checks, groups):
    lv = "none"
    for c in checks:
        if c.group in groups:
            lvl = "ok" if c.level == "info" else c.level
            if LEVEL_ORDER.index(lvl) > LEVEL_ORDER.index(lv):
                lv = lvl
    return lv


def doable(cmd, check):
    """The wizard may run ``cmd`` for you: safe fixes, and helpers that only write
    inside the packet. Anything else (and anything that opens an editor, or has a
    ``<placeholder>``) is only inserted into the shell."""
    if "<" in cmd:
        return False
    if check.safe:
        return True
    return cmd.startswith("wpk ") and not cmd.startswith("wpk instruct")


class SetupApp(App):
    TITLE = "wpk setup"
    CSS = """
    #stages { width: 22; border-right: solid $primary-darken-2; }
    #right { width: 1fr; }
    #panel { height: 1fr; min-height: 8; padding: 0 1; }
    #checks, #form { height: auto; }
    #termbar { height: 1; background: $primary-darken-2; color: $text; padding: 0 1; }
    .term { height: 14; }
    #log { height: 4; border-top: solid $primary-darken-3; }
    .fix { height: auto; margin-left: 4; }
    .fix Static { width: 1fr; color: $text-muted; }
    .fix Button { min-width: 10; height: 1; border: none; margin-left: 1; }
    .row { height: auto; margin-top: 1; }
    .row Input { width: 1fr; }
    .row Button { margin-left: 1; }
    .detail { margin-left: 4; color: $text-muted; }
    .formhead { margin-top: 1; text-style: bold; }
    #instr { height: 16; }
    """
    BINDINGS = [
        Binding("ctrl+right_square_bracket", "toggle_focus", "shell/form", priority=True),
        Binding("f2", "full_shell", "full shell"),
        Binding("f4", "new_shell", "new shell"),
        Binding("f5", "recheck", "recheck"),
        Binding("ctrl+q", "quit", "quit", priority=True),
    ]

    def __init__(self, target=None, shell=None):
        super().__init__()
        self.tg = setup.target(target) if target else None
        self.shell = shell              # argv override (tests); default: setup.shell_argv
        self.stage = "project" if self.tg is None else "work"
        self.checks = []
        self.tools = None
        self._tick = None

    # --- layout -----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield ListView(*[ListItem(Label(name, id="lbl-" + key), id="st-" + key)
                             for key, name, _ in STAGES], id="stages")
            with Vertical(id="right"):
                yield VerticalScroll(Vertical(id="checks"), Vertical(id="form"), id="panel")
                yield RichLog(id="log", markup=True, wrap=True)
                yield Static("", id="termbar")
        yield Footer()

    async def on_mount(self):
        self._term = None
        self._mount_terminal()
        await self.show_stage(self.stage)
        self.recheck()
        self.set_interval(0.5, self._poll_tick)
        self.set_interval(10, self.recheck)

    def _shell_argv(self):
        if self.shell:
            return self.shell
        if self.tg is None:
            return [os.environ.get("SHELL") or "/bin/sh"]
        return setup.shell_argv(self.tg, prompt_hook="touch %s" % shlex.quote(self._tick_path()))

    def _tick_path(self):
        return os.path.join(self.tg.setup_dir, "tick")

    def _mount_terminal(self):
        if self._term is not None:
            self._term.remove()
        if self.tg is None:
            cwd, env = os.getcwd(), None
        else:
            os.makedirs(self.tg.setup_dir, exist_ok=True)
            names = self.tg.entries()
            cwd = setup.shell_dir(self.tg, names[0] if len(names) == 1 else None)
            env = setup.shell_env(self.tg)
        self.query_one("#termbar", Static).update(
            "shell: %s   [dim](ctrl+] to switch between the form and the shell)[/]"
            % _esc(setup.tilde(cwd)))
        self._term = Terminal(self._shell_argv(), cwd=cwd, env=env, classes="term")
        self.query_one("#right").mount(self._term)

    @property
    def term(self):
        return self._term

    def say(self, msg, style=""):
        self.query_one("#log", RichLog).write(("[%s]%s[/]" % (style, _esc(msg))) if style
                                              else _esc(msg))

    # --- checks --------------------------------------------------------------------

    def action_recheck(self):
        self.recheck()

    @work(thread=True, exclusive=True, group="recheck")
    def recheck(self):
        if self.tg is None:
            checks = []
        else:
            if self.tools is None:
                self.tools = setup._tools()
            checks = self.tools + setup.readiness(self.tg, tools=False)
        self.call_from_thread(self.show_checks, checks)

    def _poll_tick(self):
        if self.tg is None:
            return
        try:
            m = os.path.getmtime(self._tick_path())
        except OSError:
            return
        if m != self._tick:
            self._tick = m
            self.recheck()

    async def show_checks(self, checks):
        self.checks = checks
        for key, name, groups in STAGES:
            if key == "handoff":
                lv = "none" if not checks else ("missing" if setup.missing(checks) else "ok")
            elif key == "project" and self.tg is None:
                lv = "missing"
            else:
                lv = _stage_level(checks, groups)
            self.query_one("#lbl-" + key, Label).update("%s %s" % (MARK[lv], name))
        nm = len(setup.missing(checks))
        self.sub_title = (self.tg.name if self.tg else "new project") + \
            ("   %d missing" % nm if nm else "   ready" if checks else "")
        box = self.query_one("#checks", Vertical)
        await box.remove_children()
        groups = dict((k, g) for k, _, g in STAGES)[self.stage]
        rows = []
        for c in checks:
            if c.group not in groups:
                continue
            rows.append(Static("%s %s" % (MARK[c.level], _esc(c.title))))
            if c.detail and c.level in ("warn", "missing"):
                rows.append(Static(_esc(c.detail), classes="detail"))
            for f in c.fix:
                btns = [Static("$ " + _esc(f))]
                if doable(f, c):
                    b = Button("Do it", classes="doit", variant="primary")
                    b.fix_cmd = f
                    btns.append(b)
                b = Button("Insert", classes="insert")
                b.fix_cmd = f
                btns.append(b)
                rows.append(Horizontal(*btns, classes="fix"))
        if self.stage == "handoff":
            rows += self._handoff_rows(checks)
        await box.mount_all(rows)
        hb = self.query("#handoff-btn")
        if hb:
            hb.first().disabled = bool(setup.missing(checks)) or self.tg is None

    def _handoff_rows(self, checks):
        if self.tg is None:
            return [Static("Create the project first.")]
        miss = setup.missing(checks)
        out = [Static("[b]%d missing[/], %d warnings." % (
            len(miss), sum(1 for c in checks if c.level == "warn")))]
        for c in miss:
            out.append(Static("  %s %s" % (MARK["missing"], _esc(c.title))))
        return out

    # --- stages and forms ---------------------------------------------------------

    async def on_list_view_selected(self, event):
        key = (event.item.id or "st-").split("-", 1)[1]
        await self.show_stage(key)

    async def show_stage(self, key):
        self.stage = key
        idx = [k for k, _, _ in STAGES].index(key)
        lv = self.query_one("#stages", ListView)
        if lv.index != idx:
            lv.index = idx
        form = self.query_one("#form", Vertical)
        await form.remove_children()
        await form.mount_all(getattr(self, "_form_" + key)())
        if self.checks or self.tg is not None:
            await self.show_checks(self.checks)

    def _row(self, *widgets):
        return Horizontal(*widgets, classes="row")

    def _form_project(self):
        if self.tg is None:
            return [Static("New project", classes="formhead"),
                    self._row(Input(placeholder="name, e.g. dvs-enh", id="p-name")),
                    self._row(Input(placeholder="directory (default ./<name>)", id="p-dir")),
                    self._row(Input(placeholder="model (default from config.toml)",
                                    id="p-model"),
                              Button("Create", id="p-create", variant="primary"))]
        meta = self.tg.status() or {}
        out = [Static("[b]%s[/]  %s" % (self.tg.name, _esc(setup.tilde(self.tg.proj)))),
               Static("root packet %s   state %s%s" % (
                   _esc(setup.tilde(self.tg.packet.path)), meta.get("state"),
                   ": " + meta["reason"] if meta.get("reason") else ""), classes="detail"),
               Static("Set it up here: prompt.md, state/, identity/, work/. The root "
                      "packet is filled from them when a step starts.", classes="detail")]
        if meta.get("state") in ("RUNNABLE", "SLEEPING"):
            out.append(self._row(Static("The runner may start it while you set it up."),
                                 Button("Pause it", id="p-pause")))
        return out

    def _form_work(self):
        return [Static("Add to work/", classes="formhead"),
                Static("Clone in the shell below, or put any directory in work/. Your clone "
                       "stays yours; steps get a git worktree of it on branch wpk/%s, with "
                       "its untracked links (such as packages/) shared. Anything that is not "
                       "git, steps change in place."
                       % (self.tg.name if self.tg else "<project>"), classes="detail"),
                self._row(Input(placeholder="source: a local path or a URL", id="r-src"),
                          Input(placeholder="name (default: the source's)", id="r-name"),
                          Button("Insert git clone", id="r-add", variant="primary"))]

    def _form_inputs(self):
        return [Static("Inputs", classes="formhead"),
                Static("Plans and notes go in state/ (never in a repo): the project's until "
                       "the first step, which copies them into the root packet. Read-only "
                       "material is linked under identity/.", classes="detail"),
                self._row(Input(placeholder="file to copy into state/", id="i-file"),
                          Button("Copy", id="i-add", variant="primary")),
                self._row(Input(placeholder="directory to link read-only", id="i-dir"),
                          Button("Insert ln -s", id="i-link"))]

    def _form_instruction(self):
        body, where = "", "prompt.md"
        if self.tg is not None:
            try:
                body, where = setup.instruction(self.tg)
            except OSError:
                pass
        return [Static("The first instruction (%s)" % where, classes="formhead"),
                self._row(Select([(t, t) for t in setup.TEMPLATES], prompt="template",
                                 id="t-sel", value="outline"),
                          Button("Load template", id="t-load"),
                          Button("Save", id="t-save", variant="primary"),
                          Button("Edit in shell", id="t-shell")),
                TextArea(body, id="instr", soft_wrap=True)]

    def _form_limits(self):
        if self.tg is None:
            return []
        t = self.tg.toml
        perm = t.get("permissions", {})
        tools = perm.get("allowed_tools", schema.PERMISSION_DEFAULTS["allowed_tools"])

        def val(k):
            v = t.get(k)
            return "" if v is None else str(v)
        return [Static("Limits and permissions", classes="formhead"),
                Static("Empty means the default. Tools are comma-separated, e.g. "
                       "Bash or Bash(git commit *).", classes="detail"),
                self._row(Input(val("step_timeout"), placeholder="step_timeout, e.g. 60m",
                                id="l-step_timeout"),
                          Input(val("step_budget_usd"), placeholder="step_budget_usd",
                                id="l-step_budget_usd"),
                          Input(val("step_context_tokens"), placeholder="step_context_tokens",
                                id="l-step_context_tokens")),
                self._row(Input(val("model"), placeholder="model", id="l-model")),
                self._row(Input(", ".join(tools), placeholder="allowed tools", id="l-tools"),
                          Button("Save", id="l-save", variant="primary")),
                Static("Smoke commands", classes="formhead"),
                self._row(Input(placeholder="a build or test command, run in the work repo",
                                id="s-cmd"),
                          Button("Add", id="s-add"),
                          Button("Run smoke", id="s-run", variant="primary"))]

    def _form_handoff(self):
        if self.tg is None:
            return []
        return [Static("Hand off to the runner", classes="formhead"),
                self._row(Input(placeholder="a note for the first step (optional)",
                                id="h-note"),
                          Button("Hand off", id="handoff-btn", variant="success",
                                 disabled=True))]

    # --- actions --------------------------------------------------------------

    def _val(self, wid):
        return self.query_one("#" + wid, Input).value.strip()

    def _do(self, fn, *args, done=None):
        """Run a helper; log what it says; recheck."""
        try:
            msgs = fn(*args)
        except (setup.SetupError, project.ProjectError, OSError, ValueError) as e:
            self.say(str(e), "red")
            return False
        for m in msgs or []:
            self.say(m)
        if done:
            done()
        self.recheck()
        return True

    @work(thread=True)
    def _bg(self, label, fn, *args):
        self.call_from_thread(self.say, label + " ...", "dim")
        try:
            msgs = fn(*args)
        except (setup.SetupError, project.ProjectError, OSError, ValueError) as e:
            self.call_from_thread(self.say, str(e), "red")
            msgs = []
        for m in msgs or []:
            self.call_from_thread(self.say, m)
        self.call_from_thread(self.recheck)

    def on_button_pressed(self, event):
        b = event.button
        bid = b.id or ""
        if "doit" in b.classes:
            self._run_fix(b.fix_cmd)
        elif "insert" in b.classes:
            self.insert(b.fix_cmd)
        elif bid == "p-create":
            self._create()
        elif bid == "p-pause":
            self.say(executor.admin(self.tg.packet, "pause").msg)
            self.call_later(self.show_stage, "project")
            self.recheck()
        elif bid == "r-add" and self._val("r-src") and self.tg is not None:
            src = self._val("r-src")
            name = self._val("r-name") or os.path.basename(src.rstrip("/")).removesuffix(".git")
            self.insert("git clone %s %s" % (shlex.quote(src), setup.tilde(
                os.path.join(self.tg.work, name))))
        elif bid == "i-add" and self._val("i-file"):
            self._do(setup.add_input, self.tg, [self._val("i-file")])
        elif bid == "i-link" and self._val("i-dir") and self.tg is not None:
            self.insert(setup.link_commands(self.tg, {"from": self._val("i-dir")})[0])
        elif bid == "t-load":
            sel = self.query_one("#t-sel", Select).value
            if sel and sel != Select.BLANK:
                try:
                    self.query_one("#instr", TextArea).text = setup.template_text(self.tg, sel)
                    self.say("loaded the %s template: edit it, then Save" % sel)
                except setup.SetupError as e:
                    self.say(str(e), "red")
        elif bid == "t-save":
            self._do(setup.instruct, self.tg, self.query_one("#instr", TextArea).text)
        elif bid == "t-shell":
            self.insert("wpk instruct %s" % self.tg.name)
        elif bid == "l-save":
            self._save_limits()
        elif bid == "s-add" and self._val("s-cmd"):
            names = self.tg.entries()
            self._do(setup.add_smoke, self.tg, self._val("s-cmd"),
                     names[0] if len(names) == 1 else None)
        elif bid == "s-run":
            self._bg("running the smoke commands", self._smoke)
        elif bid == "handoff-btn":
            out = executor.admin(Packet(self.tg.packet.path), "handoff",
                                 note=self._val("h-note") or None)
            self.say(out.msg, "green" if out.code == 0 else "red")
            if out.code == 0:
                self.say("Handed off. `wpk tick` or the runner takes it from here; "
                         "ctrl+q quits.", "green")
            self.recheck()

    def _smoke(self):
        res = setup.run_smoke(self.tg, echo=lambda m: self.call_from_thread(self.say, m))
        return ["smoke %s" % ("passed" if res["ok"] else "FAILED")]

    def _save_limits(self):
        pairs = []
        for k in ("step_timeout", "step_budget_usd", "step_context_tokens", "model"):
            v = self._val("l-" + k)
            cur = self.tg.toml.get(k)
            if v != ("" if cur is None else str(cur)):
                if k in ("step_timeout", "model") and v:
                    v = '"%s"' % v.strip('"')
                pairs.append((k, v))
        want = [t.strip() for t in self._val("l-tools").split(",") if t.strip()]
        have = self.tg.toml.get("permissions", {}).get(
            "allowed_tools", schema.PERMISSION_DEFAULTS["allowed_tools"])
        by = executor._who()

        def save():
            out = []
            if pairs:
                out += project.set_values(self.tg.proj, pairs, by)
            add = [t for t in want if t not in have]
            rm = [t for t in have if t not in want]
            if add:
                out += project.allow(self.tg.proj, add, by)
            if rm:
                out += project.deny(self.tg.proj, rm, by)
            self.tg.reload()
            return out or ["nothing to change"]
        self._do(save)

    def _create(self):
        name = self._val("p-name")
        if not name:
            self.say("give the project a name", "red")
            return
        try:
            project.new(name, None, path=self._val("p-dir") or None,
                        model=self._val("p-model") or None)
            self.tg = setup.target(name)
        except (project.ProjectError, setup.SetupError, OSError) as e:
            self.say(str(e), "red")
            return
        self.say("created %s; the root is held for setup" % name, "green")
        self._mount_terminal()
        self.call_later(self.show_stage, "work")
        self.recheck()

    @work(thread=True)
    def _run_fix(self, cmd):
        self.call_from_thread(self.say, "$ " + cmd, "dim")
        r = setup.run_fix(cmd, cwd=self.tg.packet.path if self.tg else None)
        for line in (r.stdout + r.stderr).strip().splitlines()[-6:]:
            self.call_from_thread(self.say, line.replace("wpk: ", ""),
                                  "" if r.returncode == 0 else "red")
        self.call_from_thread(self.recheck)

    def insert(self, cmd):
        """Type ``cmd`` into the shell, without Enter, and give the shell the focus."""
        self.term.write(cmd)
        self.term.focus()

    def action_toggle_focus(self):
        if self.term.has_focus:
            first = self.query("#form Input, #form TextArea, #form Button")
            (first.first() if first else self.query_one("#stages")).focus()
        else:
            self.term.focus()

    def action_full_shell(self):
        cwd = self.term.cwd
        env = setup.shell_env(self.tg) if self.tg else None
        with self.suspend():
            print("wpk setup: a full shell in %s; exit to come back" % cwd)
            subprocess.call(self._shell_argv(), cwd=cwd, env=env)
        self.recheck()

    def action_new_shell(self):
        self._mount_terminal()

    def on_terminal_exited(self, event):
        self.say("the shell exited: F4 starts a new one, ctrl+q quits", "yellow")


def main(target=None):
    try:
        app = SetupApp(target)
    except setup.SetupError as e:
        import sys
        print("wpk: %s" % e, file=sys.stderr)
        return 4
    app.run()
    return 0
