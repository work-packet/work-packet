"""Where a project keeps its runs (docs/run-binding-v1.md, stage A).

Two layouts share one engine:

- legacy (v0.2): the project directory holds ``project.toml`` and
  ``packets/<wpid>/``, and the card sits beside them;
- packet: the packet folder (usually a clone) holds the card
  ``<name>.wp.md`` and ``.work-packet/``, which is the project directory:
  ``project.toml``, ``runs/<wpid>/``, ``state/``, ``identity/``, ``.setup/``.

The project directory's own name tells them apart, so nothing needs reading.
"""

import os

DOT = ".work-packet"
LEGACY_RUNS = "packets"
RUNS = "runs"


def is_packet_layout(proj):
    return os.path.basename(os.path.normpath(proj)) == DOT


def runs_dir(proj):
    """The folder holding the project's run directories."""
    return os.path.join(proj, RUNS if is_packet_layout(proj) else LEGACY_RUNS)


def run_dir(proj, wpid):
    return os.path.join(runs_dir(proj), wpid)


def packet_folder(proj):
    """The folder the user sees: the packet folder for the packet layout, the
    project directory itself for a legacy project."""
    proj = os.path.normpath(proj)
    return os.path.dirname(proj) if is_packet_layout(proj) else proj


def card_path(proj, name):
    return os.path.join(packet_folder(proj), name + ".wp.md")


def project_of_runs(pdir):
    """The project directory owning runs folder ``pdir``, or None if ``pdir``
    is not one."""
    pdir = os.path.normpath(pdir)
    proj = os.path.dirname(pdir)
    b = os.path.basename(pdir)
    if b == LEGACY_RUNS and not is_packet_layout(proj):
        return proj
    if b == RUNS and is_packet_layout(proj):
        return proj
    return None
