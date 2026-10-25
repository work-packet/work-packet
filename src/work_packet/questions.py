"""Questions a step asks with ``ask:`` and the answers that come back (docs/interaction.md §2-3)."""

from . import schema

YES = ("yes", "y", "true", "ok", "approve", "approved", "grant", "granted")
QUESTION_FIELDS = ("id", "q", "recommend", "choices", "grants")


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
    return out


def _text(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    return None if v is None else str(v)


def normalise(ask):
    """``ask:`` as a list of ``{id, q, recommend, choices, grants}``; [] for None."""
    if ask is None:
        return []
    if isinstance(ask, str):
        return [{"id": "q1", "q": " ".join(ask.split()), "recommend": None, "choices": [],
                 "grants": []}]
    return [{"id": q["id"], "q": q["q"].strip(), "recommend": _text(q.get("recommend")),
             "choices": list(q.get("choices") or []), "grants": list(q.get("grants") or [])}
            for q in ask]


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


def grants(qs, answers):
    """Tools to allow: the ``grants`` of every question answered yes."""
    out = []
    for q in qs:
        if q["grants"] and is_yes(answers.get(q["id"])):
            out += [t for t in q["grants"] if t not in out]
    return out
