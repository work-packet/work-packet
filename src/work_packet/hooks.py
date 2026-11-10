"""Step hooks (design E4): plugin code around a harness run.

A hook comes from the ``work_packet.step_hooks`` entry-point group (a class or
an instance) and may have any of::

    start(ctx)          # before the run; may change ctx.env, start a helper
    finish(ctx, res)    # after each run; a dict for meta.json["ext"][name]
    stop(ctx)           # always, once, after the last run

A hook that raises does not fail the step: the error goes in
``meta["ext"][name]["error"]`` and that hook is not called again, except stop.

Launch hooks (``work_packet.launch_hooks``, ``prepare_env``) are called for
every harness launch, a scheduled step's and the board's (Studio and console
chat, the scribe's and brief's model calls). Each gets the environment prepared
for that one child, after the harness configuration and before the launch (on
a step, before the step hooks' ``start``)::

    prepare(ctx)        # may change ctx.env; ctx is a LaunchContext
"""
import dataclasses
import sys
from typing import Any, Dict, Optional

from . import plugins

GROUP = "work_packet.step_hooks"
LAUNCH_GROUP = "work_packet.launch_hooks"


@dataclasses.dataclass
class StepContext:
    step_dir: str
    wpid: str
    step: int
    attempt: int
    harness: str
    model: str
    env: Dict[str, str]                         # the run's environment (mutable)
    config: Dict[str, Any] = dataclasses.field(default_factory=dict)  # [plugins.<name>]


def _err(e):
    return "%s: %s" % (type(e).__name__, e)


class Hooks:
    """The loaded hooks of one step; each with its own ctx (same env dict)."""

    def __init__(self, step_dir, wpid, step, attempt, harness, model, env):
        self.hooks = []         # [name, obj, ctx]
        self.ext = {}           # name -> facts (or {"error": ...})
        for name, obj in plugins.loaded(GROUP).items():
            try:
                h = obj() if isinstance(obj, type) else obj
            except Exception as e:      # noqa: BLE001
                self.ext[name] = {"error": "init: " + _err(e)}
                continue
            ctx = StepContext(step_dir, wpid, step, attempt, harness, model, env,
                              plugins.table(name))
            self.hooks.append([name, h, ctx])

    def _live(self):
        return [x for x in self.hooks if "error" not in self.ext.get(x[0], {})]

    def _call(self, name, fn, *args):
        try:
            return fn(*args), True
        except Exception as e:          # noqa: BLE001  a hook must not fail the step
            self.ext[name] = {"error": "%s: %s" % (fn.__name__, _err(e))}
            print("wpk: step hook %s: %s" % (name, self.ext[name]["error"]), file=sys.stderr)
            return None, False

    def start(self):
        for name, h, ctx in self._live():
            if hasattr(h, "start"):
                self._call(name, h.start, ctx)

    def finish(self, res):
        """Call each hook's finish; the ``ext`` dict for meta.json."""
        for name, h, ctx in self._live():
            if hasattr(h, "finish"):
                out, ok = self._call(name, h.finish, ctx, res)
                if ok and out is not None:
                    self.ext[name] = out if isinstance(out, dict) else {"value": out}
        return dict(self.ext)

    def stop(self):
        for name, h, ctx in self.hooks:
            if hasattr(h, "stop"):
                try:
                    h.stop(ctx)
                except Exception as e:  # noqa: BLE001
                    print("wpk: step hook %s: stop: %s" % (name, _err(e)), file=sys.stderr)


# --- launch hooks: the child's environment, for every harness launch ----------------------

@dataclasses.dataclass
class LaunchContext:
    harness: str
    purpose: str                                # "step", "studio", "console" or "model-call"
    env: Dict[str, str]                         # this child's environment (mutable)
    wpid: Optional[str] = None
    project_dir: Optional[str] = None
    cwd: Optional[str] = None
    config: Dict[str, Any] = dataclasses.field(default_factory=dict)  # [plugins.<name>]


def prepare_env(harness, purpose, env, **facts):
    """Give each enabled launch hook ``env``, the environment of one child about to
    start, to change in place; returns ``env``. A hook that raises is skipped with
    a line on stderr naming it and the error's type, never a value of ``env``:
    the launch goes ahead without what it would have added."""
    for name, obj in plugins.loaded(LAUNCH_GROUP).items():
        try:
            h = obj() if isinstance(obj, type) else obj
            fn = getattr(h, "prepare", None) or h
            fn(LaunchContext(harness, purpose, env, config=plugins.table(name), **facts))
        except Exception as e:          # noqa: BLE001  a hook must not stop the launch
            print("wpk: launch hook %s: %s" % (name, type(e).__name__), file=sys.stderr)
    return env
