"""A step's cost and where it came from (design E5).

``meta.json`` keeps ``cost_usd`` (the best figure) and gains ``cost``::

    {"usd": 0.4123, "basis": "gateway", "source": "site-gateway", "harness_usd": 0.4571}

``basis`` is ``harness`` (the harness's own figure), ``priced`` (tokens times
the profile's ``price``, USD per million) or a ``work_packet.cost`` plugin's.
Best: a plugin's answer, else ``priced`` if the profile has a price, else
``harness``.

A cost plugin (a class or an instance) has ``cost(meta, step_dir)``: ``meta``
is the meta.json about to be written (``tokens``, ``model``, ``route``,
``ext`` from step hooks...). It returns None (no answer), a number of USD, or
a dict with ``usd`` and optionally ``basis`` and ``source``. Plugins are asked
in entry-point order; the first answer wins. One that raises is skipped.
"""
import os
import sys

from . import plugins

GROUP = "work_packet.cost"

# price key -> the token counts it applies to (harnesses normalise to these)
_PRICED = {"input": ("input_tokens",),
           "output": ("output_tokens",),
           "cache_write": ("cache_creation_input_tokens",),
           "cache_read": ("cache_read_input_tokens",)}


def priced(tokens, price):
    """USD for ``tokens`` at ``price`` (per million); None without either."""
    if not price or not tokens:
        return None
    total = 0.0
    for key, names in _PRICED.items():
        total += sum(tokens.get(n) or 0 for n in names) * float(price.get(key, 0.0))
    return round(total / 1e6, 6)


# --- the sessions people drive (docs/session-cost-plan.md S3) ------------------------

PRICES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.toml")
_builtin = []


def price_tables(home=None):
    """``[(glob, price)]``: config.toml's ``[prices]`` first, then the built-ins."""
    from . import registry
    from .tomlio import load_toml
    if not _builtin:
        try:
            _builtin.append(list((load_toml(PRICES).get("prices") or {}).items()))
        except (OSError, ValueError):
            _builtin.append([])
    try:
        mine = registry.load_config_file(home).get("prices") or {}
    except Exception:                   # noqa: BLE001  a bad config: the built-ins
        mine = {}
    return [(g, p) for g, p in mine.items() if isinstance(p, dict)] + _builtin[0]


def model_price(model, home=None, tables=None):
    """The price of ``model`` (the first glob that matches), or None."""
    import fnmatch
    if not model:
        return None
    for glob, p in tables if tables is not None else price_tables(home):
        if fnmatch.fnmatchcase(model, glob):
            return p
    return None


def session_usd(usage, price):
    """USD for a session's ``usage`` at ``price``; None without a price. The part of
    the cache writes made for an hour is priced at ``cache_write_1h``."""
    if not price or not usage:
        return None
    one_h = usage.get("cache_creation_1h_input_tokens") or 0
    five_m = max((usage.get("cache_creation_input_tokens") or 0) - one_h, 0)
    w5 = float(price.get("cache_write", price.get("input", 0.0)))
    usd = ((usage.get("input_tokens") or 0) * float(price.get("input", 0.0))
           + (usage.get("output_tokens") or 0) * float(price.get("output", 0.0))
           + five_m * w5 + one_h * float(price.get("cache_write_1h", w5))
           + (usage.get("cache_read_input_tokens") or 0) * float(price.get("cache_read", 0.0)))
    return round(usd / 1e6, 6)


def _ask(meta, step_dir):
    for name, obj in plugins.loaded(GROUP).items():
        try:
            p = obj() if isinstance(obj, type) else obj
            ans = p.cost(meta, step_dir)
        except Exception as e:          # noqa: BLE001  a cost plugin must not fail the step
            print("wpk: cost plugin %s: %s: %s" % (name, type(e).__name__, e), file=sys.stderr)
            continue
        if ans is None:
            continue
        if isinstance(ans, (int, float)) and not isinstance(ans, bool):
            return {"usd": float(ans), "basis": name, "source": name}
        if isinstance(ans, dict) and isinstance(ans.get("usd"), (int, float)):
            return {"usd": float(ans["usd"]), "basis": str(ans.get("basis") or name),
                    "source": str(ans.get("source") or name)}
        print("wpk: cost plugin %s: answer is not a number or {usd: ...}" % name,
              file=sys.stderr)
    return None


def settle(meta, price, step_dir, priced_usd=None):
    """Set ``meta["cost"]`` and ``meta["cost_usd"]`` (the best figure).
    ``meta["cost_usd"]`` comes in as the harness's figure. ``priced_usd``:
    the priced figure if the caller has it (a nudged step's two runs),
    else it is priced from ``meta["tokens"]``."""
    harness_usd = meta.get("cost_usd")
    if priced_usd is None:
        priced_usd = priced(meta.get("tokens"), price)
    c = _ask(meta, step_dir)
    if c is None and priced_usd is not None:
        c = {"usd": priced_usd, "basis": "priced", "source": "profile"}
    if c is None:
        c = {"usd": harness_usd, "basis": "harness", "source": meta.get("harness")}
    c["harness_usd"] = harness_usd
    meta["cost"] = c
    meta["cost_usd"] = c["usd"]
    return meta
