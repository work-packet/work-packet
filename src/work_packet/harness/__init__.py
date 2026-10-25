"""Harness adapters: how a step runs under a given agent CLI (harness.md §3).

Everything harness-specific lives in an adapter: the command line, extra
environment, reading the transcript, and the features it has (``Caps``).
The executor and the packet format do not depend on the harness.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Caps:
    system_slot: bool = False          # fixed text can go in the system prompt
    inject: bool = False               # a message can be added mid-step (context.md C3)
    resume: bool = False               # a session can be resumed by id (C4)
    fork: bool = False                 # ... under a new id
    set_session_id: bool = False       # the id can be chosen up front
    reports_cost: bool = False         # the output has a USD cost
    cost_is_chain_total: bool = False  # a resumed run reports the whole chain's cost


@dataclass
class StepSpec:
    """What the executor knows about one model run."""
    model: str
    session_id: str
    permission_mode: str
    allowed_tools: List[str]
    budget_usd: float
    add_dirs: List[str] = field(default_factory=list)
    system_file: Optional[str] = None   # protocol text for the system prompt
    context_limit: int = 0              # C3 soft limit; 0 = off
    marker: Optional[str] = None        # C3 hook's state file
    notes: Optional[tuple] = None       # (inbox, notes.seen) for mid-step notes
    resume_from: Optional[str] = None   # C4: session to resume


class Harness:
    name = "?"
    caps = Caps()

    def command(self, spec):
        raise NotImplementedError

    def env(self, spec):
        return {}

    def parse(self, transcript_path, res):
        """Fill ``res`` (a ``model.StepResult``) from the run's transcript."""
        raise NotImplementedError

    def models(self):
        """``[(model, label)]`` to offer when choosing one. Not a limit: the
        harness may take others (none of them can list what an account may use)."""
        return []


def names():
    return sorted(_REGISTRY)


def get(name):
    """The adapter for ``name``. Raises KeyError for an unknown harness."""
    return _REGISTRY[name]()


from .claude import Claude  # noqa: E402  (needs Harness above)

_REGISTRY = {"claude": Claude}

__all__ = ["Caps", "StepSpec", "Harness", "Claude", "get", "names"]
