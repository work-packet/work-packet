"""Task templates: named shapes of work (docs/prompt-intake.md §4).

A template is ``<name>.wpt.md``: YAML front matter (the spec) and a Markdown
body, the prompt, which is a Jinja2 template. It names a starter and the
values to give it; rendering (T2) turns a template and its parameters into an
ordinary recipe. Templates live in ``$WPK_HOME/templates/`` (global) and
``$WPK_HOME/boards/<board>/templates/`` (the board's, which win by name).

This module finds, loads and checks them. Every problem names its file and line.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

from . import frontmatter, registry, schema

SUFFIX = ".wpt.md"
SPEC_KEYS = ("name", "title", "help", "starter", "board", "params", "recipe", "setup",
             "deliver", "inputs", "prompt")
PARAM_KEYS = ("kind", "required", "default", "ask", "help", "label", "choices")
KINDS = ("text", "textarea", "bool", "int", "choice", "repo", "issue", "project")
# What the rendering context has besides the parameters (§4.1).
CONTEXT = ("board", "date", "user")
# Recipe values a template may set besides its starter's own fields. ``objective``
# is the body; ``board`` is where it is started.
RECIPE_EXTRA = ("model", "harness", "hold")
DELIVER = ("push", "draft-pr", "pr")


class TemplateError(Exception):
    """A template that cannot be read at all; ``str()`` is ``path:line: msg``."""

    def __init__(self, path, line, msg):
        super().__init__("%s:%s: %s" % (path, line or 1, msg))
        self.path, self.line, self.msg = path, line or 1, msg


@dataclass
class Problem:
    line: int
    msg: str
    level: str = "error"     # error | warning


@dataclass
class Template:
    name: str
    path: str
    scope: str               # global | board
    spec: dict
    body: str
    body_line: int           # the file line the body starts on
    lines: dict = field(default_factory=dict)     # key path tuple -> file line
    owner: Optional[str] = None                   # the board whose directory it is in

    @property
    def title(self):
        return self.spec.get("title") or self.name

    @property
    def board(self):
        """The board it is offered on (``board:``), or None: everywhere."""
        return self.spec.get("board")

    @property
    def starter(self):
        return self.spec.get("starter") or "folder"

    @property
    def params(self):
        p = self.spec.get("params")
        return p if isinstance(p, dict) else {}

    def line(self, *path):
        """The file line of a key (the nearest enclosing one known)."""
        while path:
            if path in self.lines:
                return self.lines[path]
            path = path[:-1]
        return 1

    def prompt_path(self):
        p = self.spec.get("prompt")
        return os.path.join(os.path.dirname(self.path), p) if isinstance(p, str) and p else None

    def prompt_text(self):
        """The prompt's source: the body, or the ``prompt:`` file."""
        p = self.prompt_path()
        if p is None:
            return self.body
        with open(p, encoding="utf-8") as fp:
            return fp.read()

    def key_params(self):
        """The parameters asked for: required with no default, or ``ask: true``."""
        return [n for n, d in self.params.items() if isinstance(d, dict)
                and ((d.get("required") and "default" not in d) or d.get("ask"))]

    def as_dict(self):
        return {"name": self.name, "title": self.title, "help": self.spec.get("help"),
                "path": self.path, "scope": self.scope, "board": self.board,
                "starter": self.starter, "params": self.params, "key": self.key_params()}


# --- where they are ----------------------------------------------------------------

def global_dir(h=None):
    return os.path.join(h or registry.home(), "templates")


def board_dir(board, h=None):
    return os.path.join(registry.boards_dir(h), board, "templates")


def _files(d):
    try:
        names = sorted(os.listdir(d))
    except (FileNotFoundError, NotADirectoryError):
        return []
    return [os.path.join(d, n) for n in names if n.endswith(SUFFIX) and not n.startswith(".")]


def _dirs(board, h=None):
    out = [("global", None, global_dir(h))]
    if board:
        out.append(("board", board, board_dir(board, h)))
    return out


def scan(board=None, h=None):
    """``(templates, broken)`` offered on ``board`` (None: global only), the
    board's over the global ones by name. ``broken``: ``[TemplateError]``."""
    out, broken = {}, []
    for scope, owner, d in _dirs(board, h):
        for p in _files(d):
            try:
                t = load(p, scope, owner)
            except TemplateError as e:
                broken.append(e)
                continue
            if t.board and t.board != (board or registry.DEFAULT_BOARD):
                continue
            out[t.name] = t
    return sorted(out.values(), key=lambda t: t.name), broken


def templates(board=None, h=None):
    return scan(board, h)[0]


def get(name, board=None, h=None):
    """The template called ``name`` on ``board``; None if there is none."""
    return next((t for t in templates(board, h) if t.name == name), None)


def every_file(h=None):
    """Every template file: the global ones and each board's, ``[(scope, owner, path)]``."""
    out = [("global", None, p) for p in _files(global_dir(h))]
    try:
        names = sorted(os.listdir(registry.boards_dir(h)))
    except FileNotFoundError:
        names = []
    for n in names:
        out += [("board", n, p) for p in _files(board_dir(n, h))]
    return out


# --- reading ------------------------------------------------------------------------

_FENCE = "---"


def _key_lines(node, base, path=()):
    """Map each mapping key's path to its file line (1-based)."""
    out = {}
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            if isinstance(k, yaml.ScalarNode):
                p = path + (k.value,)
                out[p] = base + k.start_mark.line
                out.update(_key_lines(v, base, p))
    return out


def load(path, scope="global", owner=None):
    """Read one template file. Raises TemplateError if it can't be read at all;
    what is wrong inside it is check()'s to say."""
    try:
        with open(path, encoding="utf-8") as fp:
            text = fp.read().replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as e:
        raise TemplateError(path, 1, "cannot read: %s" % e) from None
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != _FENCE:
        raise TemplateError(path, 1, "no front matter: a template starts with '---'")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == _FENCE), None)
    if end is None:
        raise TemplateError(path, 1, "front matter has no closing '---'")
    src = "\n".join(lines[1:end])
    try:
        spec = yaml.load(src, Loader=frontmatter._Loader)
        node = yaml.compose(src, Loader=frontmatter._Loader)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise TemplateError(path, 2 + mark.line if mark else 1,
                            "front matter is not valid YAML: %s" % (
                                getattr(e, "problem", None) or e)) from None
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise TemplateError(path, 2, "front matter is not a mapping")
    stem = os.path.basename(path)[:-len(SUFFIX)]
    return Template(name=spec.get("name") if isinstance(spec.get("name"), str) else stem,
                    path=path, scope=scope, spec=spec, body="\n".join(lines[end + 1:]),
                    body_line=end + 2, lines=_key_lines(node, 2), owner=owner)


# --- checking -----------------------------------------------------------------------

def _env():
    from jinja2.sandbox import SandboxedEnvironment
    from jinja2 import StrictUndefined
    return SandboxedEnvironment(undefined=StrictUndefined, autoescape=False,
                                trim_blocks=True, lstrip_blocks=True,
                                keep_trailing_newline=True)


def _jinja(env, src, known, line0, where, probs):
    """Check one Jinja source: syntax, and names that are neither parameters nor
    context. ``line0``: the file line its first line is on."""
    from jinja2 import TemplateSyntaxError, meta
    try:
        ast = env.parse(src)
    except TemplateSyntaxError as e:
        probs.append(Problem(line0 + (e.lineno or 1) - 1, "%s: %s" % (where, e.message)))
        return
    for n in sorted(meta.find_undeclared_variables(ast) - set(known)):
        rx = re.compile(r"\b%s\b" % re.escape(n))
        at = next((i for i, ln in enumerate(src.split("\n"))
                   if rx.search(ln) and ("{{" in ln or "{%" in ln)), 0)
        probs.append(Problem(line0 + at, "%s: {{ %s }} is not a parameter" % (where, n)))


def _strings(v, path=()):
    """Every string in a nested value, with its key path."""
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from _strings(x, path + (k,))
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x, path)


def check(t):
    """What is wrong with template ``t``: ``[Problem]`` (errors and warnings)."""
    from . import starters
    probs = []
    s = t.spec

    def err(path, msg):
        probs.append(Problem(t.line(*path), msg))

    def warn(path, msg):
        probs.append(Problem(t.line(*path), msg, "warning"))

    stem = os.path.basename(t.path)[:-len(SUFFIX)]
    for k in s:
        if k not in SPEC_KEYS:
            err((k,), "unknown key %r; a template has: %s" % (k, ", ".join(SPEC_KEYS)))
    if "name" in s and s["name"] != stem:
        err(("name",), "name %r is not the file's (%s%s)" % (s["name"], stem, SUFFIX))
    if t.name in starters.names():
        warn(("name",), "%s is also a starter's name: `wpk start %s` makes that starter's "
             "packet, not this template's" % (t.name, t.name))
    if not schema.is_name(t.name):
        err(("name",), "%r is not a template name; use [a-z0-9][a-z0-9_-]*" % (t.name,))
    for k in ("title", "help"):
        if k in s and not isinstance(s[k], str):
            err((k,), "%s is text" % k)
    if "board" in s:
        if not schema.is_name(s["board"]):
            err(("board",), "board: a board name")
        elif t.owner and s["board"] != t.owner:
            warn(("board",), "board %r, but the file is in board %s's templates: it is "
                 "never offered" % (s["board"], t.owner))
        elif registry.board(s["board"]) is None:
            warn(("board",), "there is no board %r" % s["board"])

    # The starter and what it takes.
    starter = None
    try:
        starter = starters.get(t.starter)
    except starters.StartError as e:
        err(("starter",), str(e))

    # Parameters.
    params = s.get("params", {})
    if not isinstance(params, dict):
        err(("params",), "params: a mapping of name to {kind, required, default, ...}")
        params = {}
    env = _env()
    known = list(CONTEXT)
    for n, d in params.items():
        at = ("params", n)
        if not schema.is_name(n) or "-" in n:
            err(at, "%r is not a parameter name; use [a-z0-9_]" % (n,))
        if n in CONTEXT:
            err(at, "%r is set by wpk; call the parameter something else" % n)
        if not isinstance(d, dict):
            err(at, "%s: a mapping {kind, required, default, ...}" % n)
            known.append(n)
            continue
        for k in d:
            if k not in PARAM_KEYS:
                err(at + (k,), "%s: unknown key %r; a parameter has: %s"
                    % (n, k, ", ".join(PARAM_KEYS)))
        kind = d.get("kind", "text")
        if kind not in KINDS:
            err(at + ("kind",), "%s: kind %r; one of: %s" % (n, kind, ", ".join(KINDS)))
        for k in ("required", "ask"):
            if k in d and not isinstance(d[k], bool):
                err(at + (k,), "%s: %s is true or false" % (n, k))
        if kind == "choice":
            ch = d.get("choices")
            if not (isinstance(ch, list) and ch and all(isinstance(c, (str, int)) for c in ch)):
                err(at + ("choices",), "%s: a choice needs choices: [a, b, ...]" % n)
            elif "default" in d and d["default"] not in ch:
                err(at + ("default",), "%s: default %r is not one of the choices"
                    % (n, d["default"]))
        elif "choices" in d:
            warn(at + ("choices",), "%s: choices only mean something for kind: choice" % n)
        if "default" in d:
            dv = d["default"]
            if kind == "bool" and not isinstance(dv, bool):
                err(at + ("default",), "%s: default is true or false" % n)
            elif kind == "int" and (isinstance(dv, bool) or not isinstance(dv, int)):
                err(at + ("default",), "%s: default is a whole number" % n)
            elif isinstance(dv, str):    # a default may use the parameters before it
                _jinja(env, dv, known, t.line(*at, "default"), "params.%s.default" % n, probs)
        known.append(n)

    # Recipe: the starter's values.
    recipe = s.get("recipe", {})
    if not isinstance(recipe, dict):
        err(("recipe",), "recipe: a mapping of the starter's values")
        recipe = {}
    if starter is not None:
        ok = {f.key for f in starter.all_fields()} | set(RECIPE_EXTRA)
        ok.discard("objective")
        for k in recipe:
            if k == "objective":
                err(("recipe", k), "the objective is the template's prompt (its body), "
                    "not a recipe value")
            elif k == "board":
                err(("recipe", k), "board: a packet goes on the board it is started from")
            elif k not in ok:
                err(("recipe", k), "starter %s takes no %r; it takes: %s"
                    % (starter.name, k, ", ".join(sorted(ok))))
        for f in starter.fields:
            if f.required and f.key not in recipe and f.key not in params:
                err(("recipe",), "starter %s needs %s: set recipe.%s, or a parameter %s"
                    % (starter.name, f.label, f.key, f.key))

    # Setup, delivery, inputs: shapes only (T4, T5 act on them).
    setup = s.get("setup")
    if setup is not None:
        if not isinstance(setup, dict) or set(setup) - {"run"}:
            err(("setup",), "setup: {run: [command, ...]}")
        elif not (isinstance(setup.get("run"), list)
                  and all(isinstance(c, str) and c.strip() for c in setup["run"])):
            err(("setup", "run"), "setup.run: a list of commands")
    dl = s.get("deliver")
    if dl is not None:
        if isinstance(dl, str):
            dl = {"do": dl}
        if not isinstance(dl, dict) or set(dl) - {"do", "gate"}:
            err(("deliver",), "deliver: push, draft-pr or pr, or {do, gate}")
        else:
            if dl.get("do") not in DELIVER:
                err(("deliver", "do"), "deliver.do: one of %s" % ", ".join(DELIVER))
            if "gate" in dl and not (isinstance(dl["gate"], str) and dl["gate"].strip()):
                err(("deliver", "gate"), "deliver.gate: a command")
    inputs = s.get("inputs")
    if inputs is not None and not (isinstance(inputs, dict) and all(
            schema.is_name(k.replace(".", "-")) and isinstance(v, str)
            for k, v in inputs.items())):
        err(("inputs",), "inputs: a mapping of file name to text")

    # Jinja in every string of the spec, and in the prompt.
    for key in ("recipe", "setup", "deliver", "inputs"):
        for path, v in _strings(s.get(key), (key,)):
            _jinja(env, v, known, t.line(*path), ".".join(path), probs)
    pp = t.prompt_path()
    if pp is not None:
        if t.body.strip():
            err(("prompt",), "prompt: names a file, but the template has a body too; "
                "use one or the other")
        try:
            src = t.prompt_text()
        except (OSError, UnicodeDecodeError) as e:
            err(("prompt",), "prompt: cannot read %s: %s" % (pp, e))
        else:
            n0 = len(probs)
            _jinja(env, src, known, 1, "prompt", probs)
            for p in probs[n0:]:      # lines in the prompt file, said so
                p.msg = "%s line %d: %s" % (os.path.basename(pp), p.line, p.msg)
                p.line = t.line("prompt")
    elif "prompt" in s:
        err(("prompt",), "prompt: a file name next to the template")
    else:
        _jinja(env, t.body, known, t.body_line, "prompt", probs)
        if not t.body.strip():
            warn((), "the prompt is empty: the packet is held for you to write it")
    return sorted(probs, key=lambda p: p.line)


def report(t, probs):
    """``path:line: level: msg`` lines."""
    return ["%s:%d: %s: %s" % (t.path, p.line, p.level, p.msg) for p in probs]


# --- rendering (T2) -----------------------------------------------------------------

# Values given with a template that are not its parameters: the ones every
# starter takes (docs/starters-v1.md), which override the template's.
OVERRIDES = ("name", "dir", "board", "from", "model", "harness", "hold", "deliver", "gate",
             "inputs")
_TRUE, _FALSE = ("1", "true", "yes", "on", "y"), ("0", "false", "no", "off", "n", "")


class RenderError(Exception):
    pass


class RepoValue(str):
    """A ``repo`` parameter: renders as what was given (``@verilator``, a URL),
    with ``.name``, ``.url`` and ``.ref`` from ``[[repo]]`` when it names one."""

    def __new__(cls, text, board=None, h=None):
        v = super().__new__(cls, text)
        entry = registry.repo(text[1:], board, h) if text.startswith("@") else None
        v.url = (entry or {}).get("url") or text
        v.ref = (entry or {}).get("ref") or ""
        v.name = (entry or {}).get("name") or os.path.basename(
            v.url.rstrip("/")).removesuffix(".git")
        return v


def _coerce(t, n, d, v):
    kind = d.get("kind", "text")
    if kind == "bool":
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in _TRUE or s in _FALSE:
            return s in _TRUE
        raise RenderError("%s: yes or no, not %r" % (n, v))
    if kind == "int":
        try:
            if isinstance(v, bool):
                raise ValueError
            return int(str(v).strip().lstrip("#"))
        except ValueError:
            raise RenderError("%s: a whole number, not %r" % (n, v)) from None
    s = v if isinstance(v, str) else str(v)
    if kind != "textarea":
        s = s.strip()
    if kind == "choice" and s not in [str(c) for c in d.get("choices") or ()]:
        raise RenderError("%s: one of %s, not %r" % (
            n, ", ".join(str(c) for c in d.get("choices") or ()), s))
    return s


def _jenv(t, h=None):
    """The environment for ``t``: its board's templates directory, then the global
    one, for ``{% include %}`` and ``{% extends %}``."""
    from jinja2 import FileSystemLoader
    env = _env()
    dirs = [os.path.dirname(t.path)]
    if t.owner:
        dirs.append(board_dir(t.owner, h))
    dirs.append(global_dir(h))
    env.loader = FileSystemLoader(list(dict.fromkeys(dirs)))
    return env


def _render(env, src, ctx, where):
    from jinja2 import TemplateError as JError
    try:
        return env.from_string(src).render(ctx)
    except JError as e:
        raise RenderError("%s: %s" % (where, e)) from None


def _render_all(env, v, ctx, where):
    if isinstance(v, str):
        return _render(env, v, ctx, where)
    if isinstance(v, dict):
        return {k: _render_all(env, x, ctx, "%s.%s" % (where, k)) for k, x in v.items()}
    if isinstance(v, list):
        return [_render_all(env, x, ctx, where) for x in v]
    return v


def answers(t, given, board=None, h=None):
    """The parameters' values: what was given (coerced to each kind), else the
    default (rendered with the ones before it). Missing key parameters are named
    together; an unknown one is refused. Returns the rendering context."""
    import datetime
    import getpass
    probs = check(t)
    errs = [p for p in probs if p.level == "error"]
    if errs:
        raise RenderError("template %s has errors; `wpk template check %s`:\n  %s" % (
            t.name, t.path, "\n  ".join("line %d: %s" % (p.line, p.msg) for p in errs)))
    unknown = sorted(set(given) - set(t.params))
    if unknown:
        raise RenderError("template %s has no parameter %s; it has: %s" % (
            t.name, ", ".join(unknown), ", ".join(t.params) or "none"))
    try:
        user = getpass.getuser()
    except Exception:                   # noqa: BLE001
        user = ""
    ctx = {"board": board or registry.DEFAULT_BOARD,
           "date": datetime.date.today().isoformat(), "user": user}
    def given_(n, kind):
        return n in given and not (given[n] in ("", None) and kind != "textarea")

    missing = [n for n, d in t.params.items() if d.get("required") and "default" not in d
               and not given_(n, d.get("kind", "text"))]
    if missing:                         # all of them at once, before any default is rendered
        raise RenderError("template %s needs %s" % (t.name, ", ".join(missing)))
    env = _jenv(t, h)
    for n, d in t.params.items():
        kind = d.get("kind", "text")
        if given_(n, kind):
            v = _coerce(t, n, d, given[n])
        elif "default" in d:
            dv = d["default"]
            v = _coerce(t, n, d, _render(env, dv, ctx, "params.%s.default" % n)
                        if isinstance(dv, str) else dv)
        else:
            v = False if kind == "bool" else ""
        if kind == "repo" and v:
            v = RepoValue(v, board, h)
        ctx[n] = v
    return ctx


def recipe(t, given, board=None, h=None):
    """The recipe template ``t`` makes from ``given`` (parameters, and any of
    OVERRIDES). Goes through the starter as ``wpk start`` does."""
    from . import starters
    if isinstance(t, str):
        name = t
        t = get(name, board, h)
        if t is None:
            raise RenderError("no template %r on board %s" % (
                name, board or registry.DEFAULT_BOARD))
    given = dict(given)
    over = {k: given.pop(k) for k in OVERRIDES if k in given and k not in t.params}
    board = over.get("board") or board
    ctx = answers(t, given, board, h)
    env = _jenv(t, h)
    vals = _render_all(env, t.spec.get("recipe") or {}, ctx, "recipe")
    try:
        fields = {f.key for f in starters.get(t.starter).all_fields()}
    except starters.StartError as e:
        raise RenderError(str(e)) from None
    for n in t.params:                  # a parameter named for a starter field fills it
        if n in fields and n not in vals and n != "objective" and ctx[n] not in ("", None):
            vals[n] = str(ctx[n])
    vals = {k: (v if isinstance(v, (str, bool)) else str(v)) for k, v in vals.items()}
    objective = _render(env, t.prompt_text(), ctx, "prompt").strip()
    if objective:
        vals["objective"] = objective + "\n"
    dl = t.spec.get("deliver")
    if dl is not None and "deliver" not in over:
        dl = {"do": dl} if isinstance(dl, str) else _render_all(env, dl, ctx, "deliver")
        vals["deliver"] = dl["do"]
        if dl.get("gate"):
            vals["gate"] = dl["gate"]
    vals.update({k: v for k, v in over.items() if k != "inputs"})
    if board:
        vals["board"] = board
    r = starters.from_values(t.starter, vals, h)
    ins = _render_all(env, t.spec.get("inputs") or {}, ctx, "inputs")
    if ins or over.get("inputs"):
        r["inputs"] = (r.get("inputs") or []) + [{"name": k, "text": v}
                                                 for k, v in ins.items()]
        if over.get("inputs"):
            r["inputs"] += starters.read_inputs(over["inputs"])
    r["origin"] = dict(r.get("origin") or {}, template=t.name)
    r.setdefault("origin", {}).setdefault("kind", "template")
    return starters.check(r)
