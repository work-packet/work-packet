"""Quick capture (docs/collaboration.md §9.6): a line of text, from the Desk, the
phone, ``wpk todo`` or ``/wpk-todo`` in a session, kept until you make it a packet
or drop it. One file per item in ``$WPK_HOME/inbox/``.
"""

import json
import os
import re
import time
import uuid

from . import fsutil

TEXT_MAX = 2000
_ID = re.compile(r"^[0-9a-f]{12}$")


def _dir(home):
    return os.path.join(home, "inbox")


def add(home, text, by=None, source=None, project=None, board=None, now=None):
    """Capture ``text``. ``source``: where it came from (board, cli, session, phone);
    ``project``: the packet it was captured from, if any. Returns the item."""
    text = " ".join((text or "").split()) if "\n" not in (text or "") else (text or "").strip()
    if not text:
        raise ValueError("nothing to capture")
    if len(text) > TEXT_MAX:
        raise ValueError("over %d characters" % TEXT_MAX)
    item = {"id": uuid.uuid4().hex[:12], "t": time.time() if now is None else now,
            "text": text, "by": by, "source": source, "project": project, "board": board}
    os.makedirs(_dir(home), mode=0o700, exist_ok=True)
    fsutil.atomic_write(os.path.join(_dir(home), item["id"] + ".json"),
                        json.dumps(item) + "\n")
    return item


def items(home):
    """Every captured item, oldest first."""
    out = []
    try:
        names = os.listdir(_dir(home))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json") or not _ID.match(n[:-5]):
            continue
        try:
            with open(os.path.join(_dir(home), n)) as fp:
                d = json.load(fp)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("text"):
            out.append(d)
    return sorted(out, key=lambda d: d.get("t") or 0)


def get(home, iid):
    return next((d for d in items(home) if d["id"] == iid), None)


def drop(home, iid):
    """Remove an item (made into a packet, or dropped). True if it was there."""
    if not _ID.match(iid or ""):
        return False
    try:
        os.unlink(os.path.join(_dir(home), iid + ".json"))
        return True
    except OSError:
        return False
