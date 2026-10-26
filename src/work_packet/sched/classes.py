"""Priority classes (docs/scheduler.md §3.1, §3.2)."""

from ..schema import SCHED_CLASSES as CLASSES

VALUE = {c: i for i, c in enumerate(CLASSES)}
DEFAULT = "normal"
AGE_CAP = "high"          # aging never lifts work above this


def packet_settings(entry, wpid):
    """The ``[packets.<wpid>]`` table of a registry entry, or {}."""
    t = (entry.get("packets") or {}).get(wpid)
    return t if isinstance(t, dict) else {}


def effective(entry, wpid):
    """(class, where it came from): the packet's override, the project's class,
    else ``normal``. Children inherit the project's class, not their parent's."""
    p = packet_settings(entry, wpid).get("priority")
    if p in VALUE:
        return p, "packet"
    p = entry.get("priority")
    if p in VALUE:
        return p, "project"
    return DEFAULT, "default"


def aged(cls, waited_s, age_after_s):
    """The class used for ordering after waiting ``waited_s``: one class up per
    ``age_after_s``, never above ``high``; ``urgent`` and ``high`` stay as they are."""
    v = VALUE[cls]
    cap = VALUE[AGE_CAP]
    if v <= cap or not age_after_s or waited_s <= 0:
        return cls
    steps = int(waited_s // age_after_s)
    return CLASSES[max(cap, v - steps)]
