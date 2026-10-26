"""Who may change the pool: the one place for roles (docs/scheduler.md §14).

A principal is ``<scheme>:<name>``: ``unix:matt`` from the CLI or the
board's loopback listener, ``tailscale:matt@example.com`` from the tailnet
listener. Today every principal that got past the board's Guard may do
everything, and so may the home's own Unix user; a front door with roles
replaces ``check`` and nothing else.
"""

import getpass
import os
import pwd
import re

from .. import registry

_RX = re.compile(r"^[a-z][a-z0-9+.-]*:\S+$")
ACTIONS = ("mode", "hold", "prio", "size", "next", "cancel", "grant")
TRUSTED_SCHEMES = ("tailscale",)        # the Guard already checked them


class Denied(Exception):
    pass


def is_principal(v):
    return isinstance(v, str) and bool(_RX.match(v))


def _login():
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return str(os.getuid())


def principal_cli():
    """The principal of whoever runs this ``wpk`` command."""
    return "unix:%s" % _login()


def principal_of(request):
    """The principal of a board request: its Guard's identity. A request
    without one (an app built without the Guard, as in tests) is the local user."""
    st = request.scope.get("state") or {}
    user, kind = st.get("user"), st.get("listener")
    if not user:
        return principal_cli()
    if kind == "tailnet":
        return "tailscale:%s" % user
    return "unix:%s" % user


def home_owner(h=None):
    try:
        return pwd.getpwuid(os.stat(h or registry.home()).st_uid).pw_name
    except (OSError, KeyError):
        return _login()


def check(principal, action, target=None, h=None):
    """Raise Denied unless ``principal`` may do ``action`` on ``target``."""
    if not is_principal(principal):
        raise Denied("%r is not a principal (<scheme>:<name>)" % (principal,))
    if action not in ACTIONS:
        raise Denied("unknown action %r" % (action,))
    scheme, name = principal.split(":", 1)
    if scheme in TRUSTED_SCHEMES:
        return
    if scheme == "unix" and name in (home_owner(h), _login()):
        return
    raise Denied("%s may not %s here" % (principal, action))
