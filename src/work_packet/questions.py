"""Questions a step asks with ``ask:`` and the answers that come back (docs/interaction.md §2-3)."""

from . import schema

YES = ("yes", "y", "true", "ok", "approve", "approved", "grant", "granted")
QUESTION_FIELDS = ("id", "q", "recommend", "choices", "grants", "request", "sets")
SETS_KEYS = ("step_budget_usd", "step_timeout", "step_context_tokens")


def validate(ask):
    """Problems with an ``ask:`` value: a non-empty string or a list of questions."""
    P = schema.Problem
    if isinstance(ask, str):
        return [] if ask.strip() else [P("ask", "must be a non-empty string (the question)")]
    if not isinstance(ask, list) or not ask:
        return [P("ask", "must be a non-empty string (the question) or a list of questions")]
    out, seen = [], set()
    for i, q in enumerate(ask):
        w = "ask[%d]" % i
        if not isinstance(q, dict):
            out.append(P(w, "must be a mapping with id and q"))
            continue
        for k in q:
            if k not in QUESTION_FIELDS:
                out.append(P("%s.%s" % (w, k), "unknown key"))
        qid = q.get("id")
        if not schema.is_name(qid):
            out.append(P(w + ".id", "required; must match [a-z0-9][a-z0-9_-]*"))
        elif qid in seen:
            out.append(P(w + ".id", "duplicate id %r" % qid))
        else:
            seen.add(qid)
        if not isinstance(q.get("q"), str) or not q["q"].strip():
            out.append(P(w + ".q", "required; the question as a non-empty string"))
        if "recommend" in q and not isinstance(q["recommend"], (str, int, float, bool)):
            out.append(P(w + ".recommend", "must be a string"))
        for k in ("choices", "grants"):
            v = q.get(k)
            if v is not None and not (isinstance(v, list) and v and
                                      all(isinstance(x, str) and x.strip() for x in v)):
                out.append(P("%s.%s" % (w, k), "must be a non-empty list of strings"))
        if "request" in q and not schema.is_name(q["request"]):
            out.append(P(w + ".request", "must name a brief, state/requests/<id>.md"))
        if "sets" in q:
            out += _validate_sets(q["sets"], q.get("choices"), w + ".sets")
    return out


def _by_choice(sets, choices):
    """True when ``sets`` is keyed by answers (``{choice: {key: value}}``)."""
    return (isinstance(sets, dict) and bool(sets) and isinstance(choices, list)
            and all(k in choices and isinstance(v, dict) for k, v in sets.items()))


def _validate_sets(sets, choices, w):
    """``sets``: settings a yes applies, ``{key: value}``, or ``{choice: {key: value}}``
    applied when that choice is the answer. Keys: ``SETS_KEYS``."""
    P = schema.Problem
    if not isinstance(sets, dict) or not sets:
        return [P(w, "must be a mapping of settings, or of choices to settings")]
    out = []
    for when, vals in (sets.items() if _by_choice(sets, choices) else [(None, sets)]):
        at = w if when is None else "%s.%s" % (w, when)
        if not vals:
            out.append(P(at, "must set something"))
        for k in vals:
            if k not in SETS_KEYS:
                out.append(P("%s.%s" % (at, k), "cannot be set by an answer; settable: %s"
                             % ", ".join(SETS_KEYS)))
        out += [P("%s.%s" % (at, p.field), p.msg)
                for p in schema._validate_limits({k: v for k, v in vals.items()
                                                  if k in SETS_KEYS})]
    return out


def _text(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    return None if v is None else str(v)


def normalise(ask):
    """``ask:`` as a list of ``{id, q, recommend, choices, grants, request, sets}``; []
    for None. ``sets`` becomes ``{answer: {key: value}}``, with ``"yes"`` for a plain
    mapping."""
    if ask is None:
        return []
    if isinstance(ask, str):
        return [{"id": "q1", "q": " ".join(ask.split()), "recommend": None, "choices": [],
                 "grants": [], "request": None, "sets": {}}]
    return [{"id": q["id"], "q": q["q"].strip(), "recommend": _text(q.get("recommend")),
             "choices": list(q.get("choices") or []), "grants": list(q.get("grants") or []),
             "request": q.get("request"), "sets": _sets(q.get("sets"), q.get("choices"))}
            for q in ask]


def _sets(sets, choices):
    if not sets:
        return {}
    if _by_choice(sets, choices):
        return {k: dict(v) for k, v in sets.items()}
    return {"yes": dict(sets)}


def summary(qs):
    """The one-line ``status.reason`` for a list of questions."""
    first = " ".join(qs[0]["q"].split())
    return first if len(qs) == 1 else "%d questions: %s" % (len(qs), first)


def is_yes(text):
    return isinstance(text, str) and text.strip().lower().rstrip(".!") in YES


def of_packet(pkt):
    """The open questions of a ``NEEDS_INPUT`` packet, from its committed memento; else []."""
    from . import frontmatter
    try:
        meta, _ = pkt.load_status()
        if meta.get("state") != "NEEDS_INPUT":
            return []
        fm, _ = pkt.load_memento()
    except (OSError, frontmatter.FrontMatterError):
        return []
    qs = normalise((fm or {}).get("ask"))
    if not qs and meta.get("reason"):          # asked by an older wpk: the reason is the question
        qs = normalise(meta["reason"])
    return qs


def fill(qs, answers, take_recommendations=False):
    """``answers`` with every unanswered question filled from its recommendation, if asked."""
    out = {k: v for k, v in (answers or {}).items() if isinstance(v, str) and v.strip()}
    if take_recommendations:
        for q in qs:
            if q["id"] not in out and q.get("recommend"):
                out[q["id"]] = q["recommend"]
    return out


def requests(qs, answers):
    """Request ids to send: the ``request`` of every question answered yes
    (docs/delegation.md §3)."""
    return [q["request"] for q in qs if q.get("request") and is_yes(answers.get(q["id"]))]


def sets(qs, answers):
    """Settings to apply: for every question, the ``sets`` entry its answer picks
    (``"yes"``: any yes; else the choice, ignoring case). Later questions win."""
    out = {}
    for q in qs:
        a = answers.get(q["id"])
        if not isinstance(a, str):
            continue
        for when, vals in (q.get("sets") or {}).items():
            if (is_yes(a) if when == "yes" else a.strip().lower() == when.strip().lower()):
                out.update(vals)
    return out


def describe_sets(q):
    """``sets`` as text for the owner: ``step_budget_usd 5.0`` or
    ``"raise budget" sets step_budget_usd 5.0``."""
    def kv(vals):
        return ", ".join("%s %s" % (k, v) for k, v in vals.items())
    s = q.get("sets") or {}
    if list(s) == ["yes"] and "yes" not in (q.get("choices") or []):
        return "yes sets " + kv(s["yes"])
    return "; ".join('"%s" sets %s' % (w, kv(v)) for w, v in s.items())


def grants(qs, answers):
    """Tools to allow: the ``grants`` of every question answered yes."""
    out = []
    for q in qs:
        if q["grants"] and is_yes(answers.get(q["id"])):
            out += [t for t in q["grants"] if t not in out]
    return out
