"""Step hooks (design E4): plugin code around a harness run.

A hook comes from the ``work_packet.step_hooks`` entry-point group (a class or
an instance) and may have any of::

    start(ctx)          # before the run; may change ctx.env, start a helper
    finish(ctx, res)    # after each run; a dict for meta.json["ext"][name]
    stop(ctx)           # always, once, after the last run

A hook that raises does not fail the step: the error goes in
``meta["ext"][name]["error"]`` and that hook is not called again, except stop.
"""
import dataclasses
import sys
from typing import Any, Dict

from . import plugins

GROUP = "work_packet.step_hooks"


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
