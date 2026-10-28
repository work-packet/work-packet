"""Marking up a Markdown file from its rendered view (docs/doc-markup.md).

The markup is CriticMarkup, written into the file itself. Rendering: a
markdown-it inline rule for it, and ``data-src`` line ranges on blocks. Editing:
a selection made on the rendered page is found in the source by projecting the
block's source to the characters the page shows, then the markup is spliced in.
"""

import hashlib
import html
import os
import re
import tempfile

# opening delimiter -> (kind, closing delimiter)
DELIMS = {"{++": ("ins", "++}"), "{--": ("del", "--}"), "{==": ("mark", "==}"),
          "{>>": ("comment", "<<}"), "{~~": ("sub", "~~}")}
TAGS = {"ins": "ins", "del": "del", "mark": "mark", "comment": "span", "sub": "span"}
SPAN = re.compile(r"\{\+\+.*?\+\+\}|\{--.*?--\}|\{==.*?==\}|\{>>.*?<<\}|\{~~.*?~~\}", re.S)

# What the page does not show, or shows differently, and is left out of matching
# on both sides (the selection, and the projected source).
IGNORE = re.compile(r"[\s*_`~\[\]|\\<>]")
_HIDDEN = [
    re.compile(r"\{\+\+|\+\+\}|\{--|--\}|\{==|==\}|\{>>|<<\}|\{~~|~~\}|~>"),
    re.compile(r"\]\([^)\n]*\)"),                                 # a link's target
    re.compile(r"^[ \t]*(?:```|~~~).*$", re.M),                   # a fence line
    re.compile(r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$", re.M),
    re.compile(r"^(?:[ \t]*(?:#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+(?:\[[ xX]\][ \t]+)?"
               r"|\d+[.)][ \t]+))+", re.M),                       # line-start syntax
]
OPS = ("comment", "insert", "delete", "replace")


class MarkupError(Exception):
    """The edit cannot be made; the message says why."""


class Stale(MarkupError):
    """The file changed since the page was rendered."""


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- rendering ------------------------------------------------------------------

def plugin(m, lines=False):
    """CriticMarkup in inline text on markdown-it ``m``; with ``lines``, every block
    element gets ``data-src="<first>-<end>"`` (0-based, end exclusive)."""
    m.inline.ruler.before("emphasis", "critic", _critic)
    m.core.ruler.push("critic_n", _number)
    if lines:
        m.core.ruler.push("src_lines", _lines)
    return m


def _critic(state, silent):
    src, pos = state.src, state.pos
    if src[pos] != "{" or src[pos:pos + 3] not in DELIMS:
        return False
    kind, close = DELIMS[src[pos:pos + 3]]
    end = src.find(close, pos + 3, state.posMax)
    if end < 0:
        return False
    if not silent:
        tok = state.push("critic_open", TAGS[kind], 1)
        tok.attrSet("class", "cm cm-" + kind)
        tok.meta = {"raw": src[pos:end + 3], "kind": kind}
        if kind == "sub":
            mid = src.find("~>", pos + 3, end)
            mid = end if mid < 0 else mid
            state.push("critic_part_open", "del", 1)
            _inline(state, pos + 3, mid)
            state.push("critic_part_close", "del", -1)
            state.push("critic_part_open", "ins", 1)
            _inline(state, min(mid + 2, end), end)
            state.push("critic_part_close", "ins", -1)
        else:
            _inline(state, pos + 3, end)
        state.push("critic_close", TAGS[kind], -1)
    state.pos = end + 3
    return True


def _inline(state, a, b):
    keep = state.posMax
    state.pos, state.posMax = a, b
    state.md.inline.tokenize(state)
    state.posMax = keep


def _number(state):
    """Number each item among the items with the same raw text, in document order,
    which is the order str.find meets them in the source (apply_item)."""
    seen = {}
    for tok in state.tokens:
        for t in tok.children or ():
            if t.type == "critic_open":
                raw = t.meta["raw"]
                t.attrSet("data-cm", raw)
                t.attrSet("data-n", str(seen.get(raw, 0)))
                seen[raw] = seen.get(raw, 0) + 1


def _lines(state):
    for tok in state.tokens:
        if tok.nesting == 1 and tok.map:
            tok.attrSet("data-src", "%d-%d" % tuple(tok.map))


# --- finding a selection in the source --------------------------------------------

def _visible(src, start, end):
    """Indices in src[start:end] of the characters matching compares."""
    hide = bytearray(end - start)
    seg = src[start:end]
    for rx in _HIDDEN:
        for mo in rx.finditer(seg):
            a = mo.start() + (1 if mo.group().startswith("](") else 0)
            hide[a:mo.end()] = b"\1" * (mo.end() - a)
    return [start + i for i, ch in enumerate(seg) if not hide[i] and not IGNORE.match(ch)]


def _block(src, lines):
    a, b = lines
    starts = [0] + [m.end() for m in re.finditer("\n", src)]
    if not 0 <= a < b or a >= len(starts):
        raise MarkupError("no such block (lines %d-%d)" % (a, b))
    return starts[a], (starts[b] if b < len(starts) else len(src))


def locate(src, lines, text, at=0):
    """(start, end) in ``src`` of ``text``, selected on the page inside the block
    of source ``lines`` (a, b), ``at`` matched characters into that block."""
    want = IGNORE.sub("", text or "")
    if not want:
        raise MarkupError("select some text first")
    start, end = _block(src, lines)
    vis = _visible(src, start, end)
    proj = "".join(src[i] for i in vis)
    hits, i = [], proj.find(want)
    while i >= 0:
        hits.append(i)
        i = proj.find(want, i + 1)
    if not hits:
        raise MarkupError("could not find the selection in the source; "
                          "select plain text within one paragraph")
    h = min(hits, key=lambda x: abs(x - at))
    s, e = _snap(src, vis[h], vis[h + len(want) - 1] + 1, text, start, end)
    for mo in SPAN.finditer(src, start, end):
        # apart from an item, or around all of it; never part of one or inside it
        if not (e <= mo.start() or s >= mo.end() or (s <= mo.start() and mo.end() <= e)):
            raise MarkupError("the selection overlaps existing markup; resolve that first")
    if "\n\n" in src[s:e] or re.search(r"\n[ \t]*\n", src[s:e]):
        raise MarkupError("select within one paragraph")
    return s, e


def _snap(src, s, e, text, start, end):
    """Widen [s, e) over the syntax around it (``**``, a backtick, a link's
    brackets and target) as far as it still renders to the selected text alone,
    so the markup wraps whole Markdown; [s, e) as it is if no widening does."""
    lefts = [s]
    while lefts[-1] > start and src[lefts[-1] - 1] in "*_~`[" and len(lefts) < 4:
        lefts.append(lefts[-1] - 1)
    rights, k = [e], e
    while k < end and len(rights) < 4:
        mo = re.match(r"\]\([^)\n]*\)|[*_~`\]]", src[k:end])
        if not mo:
            break
        k += mo.end()
        rights.append(k)
    want = " ".join(text.split())
    for a, b in sorted(((a, b) for a in lefts for b in rights),
                       key=lambda ab: (s - ab[0]) + (ab[1] - e), reverse=True):
        if _shown(src[a:b]) == want:
            return a, b
    return s, e


_TAG = re.compile(r"<[^>]*>")
_MD = []


def _shown(span):
    """The text ``span`` of inline Markdown renders to, whitespace collapsed."""
    if not _MD:
        from markdown_it import MarkdownIt
        _MD.append(MarkdownIt("commonmark", {"html": False}).enable(["strikethrough"]))
    return " ".join(html.unescape(_TAG.sub("", _MD[0].renderInline(span))).split())


def _clean(text, close):
    t = " ".join((text or "").split())
    if close in t or "~>" in t and close == "~~}":
        raise MarkupError("the text cannot contain %r" % close)
    return t


def mark(src, lines, sel, at, op, text=""):
    """``src`` with ``op`` applied to the selection ``sel``."""
    if op not in OPS:
        raise MarkupError("unknown markup %r" % op)
    s, e = locate(src, lines, sel, at)
    span = src[s:e]
    if op == "comment":
        c = _clean(text, "<<}")
        if not c:
            raise MarkupError("write a comment")
        new = "{==%s==}{>> %s <<}" % (span, c)
    elif op == "insert":
        t = _clean(text, "++}")
        if not t:
            raise MarkupError("write the text to insert")
        new = "%s{++ %s ++}" % (span, t)
    elif op == "delete":
        new = "{--%s--}" % span
    else:
        t = _clean(text, "~~}")
        new = "{~~%s~>%s~~}" % (span, t)
    return src[:s] + new + src[e:]


# --- resolving an item --------------------------------------------------------------

def _inner(raw):
    return raw[3:-3]


def resolve(src, raw, n, accept):
    """``src`` with the ``n``th item whose markup is ``raw`` accepted or rejected.
    A comment is removed either way, with the highlight it belongs to."""
    if raw[:3] not in DELIMS or not SPAN.fullmatch(raw):
        raise MarkupError("not CriticMarkup: %r" % raw[:40])
    pos = -1
    for _ in range(int(n) + 1):
        pos = src.find(raw, pos + 1)
        if pos < 0:
            raise Stale("that markup is no longer in the file")
    kind, inner = DELIMS[raw[:3]][0], _inner(raw)
    a, b = pos, pos + len(raw)
    if kind == "ins":
        out = inner.strip() if accept else ""
    elif kind == "del":
        out = "" if accept else inner
    elif kind == "sub":
        old, _, new = inner.partition("~>")
        out = new if accept else old
    elif kind == "mark":
        out = inner
    else:
        out = ""
        k = src.rfind("{==", 0, a)
        if k >= 0 and src.endswith("==}", 0, a) and src.find("==}", k) == a - 3:
            a, out = k, src[k + 3:a - 3]
    if kind == "ins" and accept and out and a > 0 and not src[a - 1].isspace() \
            and inner[:1].isspace():
        out = " " + out
    if not out and a > 0 and src[a - 1] == " " and src[b:b + 1] in (" ", "\n", ".", ",", ""):
        a -= 1
    return src[:a] + out + src[b:]


# --- the file ------------------------------------------------------------------------

def edit(path, want_sha, fn):
    """Apply ``fn(text) -> text`` to the file at ``path`` if it still has
    ``want_sha``; atomically. Returns the new sha."""
    with open(path, encoding="utf-8", newline="") as fp:
        text = fp.read()
    if want_sha and sha(text) != want_sha:
        raise Stale("the file changed since this page was loaded; reload and try again")
    out = fn(text)
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".markup-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fp:
            fp.write(out)
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return sha(out)
