"""Fetch every dashboard page of a project, following its links (GET only).

Used to check that a project shows the same from the history store as
from its runs (docs/dash-history-v1.md, D4).
"""

import html
import re
import urllib.parse

HREF = re.compile(r'(?:href|src)="([^"#]*)')
PAGES = ("", "/tasks", "/steps", "/cost", "/settings")
# What may follow /p/<project>/: a project page or a packet id. Anything else
# is a relative link inside a report (to a repo file), not a page. The
# project file browser (doc) reads the project directory, not the runs.
FIRST = re.compile(r"^(tasks|steps|cost|settings|compose|[0-9a-f]{8}-[0-9a-f-]{27})$")


def _local(url, prefix):
    u = urllib.parse.urlsplit(html.unescape(url))
    if u.scheme or u.netloc or not u.path.startswith(prefix):
        return None
    rest = u.path[len(prefix):].strip("/")
    if rest and not FIRST.match(rest.split("/")[0]):
        return None
    return u.path + ("?" + u.query if u.query else "")


def crawl(client, name, limit=2000):
    """{url: (status, body)} for every page under ``/p/<name>`` reachable from
    the project's pages."""
    prefix = "/p/%s" % urllib.parse.quote(name)
    todo = [prefix + p for p in PAGES]
    seen = {}
    while todo and len(seen) < limit:
        url = todo.pop(0)
        if url in seen:
            continue
        r = client.get(url, follow_redirects=False)
        body = r.text if "text" in r.headers.get("content-type", "") else r.content
        seen[url] = (r.status_code, body)
        if isinstance(body, str) and "html" in r.headers.get("content-type", ""):
            for h in HREF.findall(body):
                u = _local(h, prefix)
                if u and u not in seen and u not in todo:
                    todo.append(u)
    return seen


def compare(before, after, subst=()):
    """Differences between two crawls: urls missing on either side, and
    pages whose status or body differs once each ``(new, old)`` in ``subst``
    (``new`` replaced by ``old``) is applied to ``after``."""
    probs = []
    for u in sorted(set(before) | set(after)):
        if u not in after:
            probs.append("%s: only before" % u)
            continue
        if u not in before:
            probs.append("%s: only after" % u)
            continue
        (s1, b1), (s2, b2) = before[u], after[u]
        for new, old in subst:
            if isinstance(b2, str):
                b2 = b2.replace(new, old)
            else:
                b2 = b2.replace(new.encode(), old.encode())
        if s1 != s2:
            probs.append("%s: status %s, then %s" % (u, s1, s2))
        elif b1 != b2:
            probs.append("%s: body differs" % u)
    return probs
