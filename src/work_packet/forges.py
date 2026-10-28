"""Forges: where repos and issues come from (docs/starters-v1.md).

``config.toml`` lists them as ``[[forge]]`` tables (``name``, ``kind``,
``url``, ``token_env``, ``clone``). With none, GitHub is offered when a
token is found. Tokens are read from the environment (or ``gh auth token``)
when used, never stored.

Every request goes through ``_get`` so tests can replace it.
"""

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

KINDS = ("github", "forgejo")
GITHUB_API = "https://api.github.com"


class ForgeError(Exception):
    pass


def _get(url, headers, timeout=20):
    """GET ``url``: the decoded JSON. Raises ForgeError."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ForgeError("%s: HTTP %d %s" % (url.split("?")[0], e.code, e.reason)) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ForgeError("%s: %s" % (url.split("?")[0], e)) from None


def slug(text, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n].rstrip("-") or "x"


class Forge:
    kind = ""

    def __init__(self, name, url=None, token_env=None, clone="https"):
        self.name, self.url, self.token_env, self.clone = name, url, token_env, clone
        self._cache = {}

    # -- what a starter uses --------------------------------------------------------
    def repos(self, query="", limit=30):
        """[{full_name, description, clone_url, html_url}], the user's own first."""
        raise NotImplementedError

    def issues(self, repo, query="", limit=30, labels=()):
        """Open issues of ``repo`` ("owner/name") with all of ``labels``:
        [{number, title, url, state, labels}]."""
        raise NotImplementedError

    def issue(self, repo, number):
        """{number, title, body, url, state, user, labels, comments: [{user, body, created}]}."""
        raise NotImplementedError

    def repo(self, repo):
        """{full_name, description, clone_url, html_url, default_branch}."""
        raise NotImplementedError

    def owner_repos(self, owner):
        """Every repo of a user or org (not archived): ["owner/name"]."""
        raise NotImplementedError

    # -- helpers --------------------------------------------------------------------
    def token(self):
        return os.environ.get(self.token_env) if self.token_env else None

    def _json(self, path, **q):
        q = {k: v for k, v in q.items() if v not in (None, "")}
        url = self.api + path + ("?" + urllib.parse.urlencode(q) if q else "")
        h = {"Accept": "application/json", "User-Agent": "work-packet"}
        t = self.token()
        if t:
            h["Authorization"] = "token %s" % t
        return _get(url, h)

    def _cached(self, key, fn, ttl=120):
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        v = fn()
        self._cache[key] = (now, v)
        return v

    def _repo_out(self, r):
        return {"full_name": r["full_name"], "description": r.get("description") or "",
                "clone_url": r.get("ssh_url") if self.clone == "ssh" else r.get("clone_url"),
                "html_url": r.get("html_url") or "",
                "default_branch": r.get("default_branch") or ""}

    @staticmethod
    def _match(rows, query, key):
        q = (query or "").lower().split()
        return [r for r in rows if all(w in (r[key] or "").lower() for w in q)]


class GitHub(Forge):
    kind = "github"

    @property
    def api(self):
        u = (self.url or "").rstrip("/")
        return GITHUB_API if not u or u in ("https://github.com", GITHUB_API) else u + "/api/v3"

    @property
    def web(self):
        u = (self.url or "").rstrip("/")
        return "https://github.com" if not u or u == GITHUB_API else u

    def token(self):
        t = Forge.token(self) or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if t:
            return t
        try:
            r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                               timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() or None

    def repos(self, query="", limit=30):
        mine = self._cached("mine", lambda: [self._repo_out(r) for r in self._json(
            "/user/repos", per_page=100, sort="updated")] if self.token() else [])
        out = self._match(mine, query, "full_name")
        if query and len(out) < limit:
            have = {r["full_name"] for r in out}
            got = self._json("/search/repositories", q=query, per_page=limit)
            out += [self._repo_out(r) for r in got.get("items", [])
                    if r["full_name"] not in have]
        return out[:limit]

    def repo(self, repo):
        return self._repo_out(self._json("/repos/%s" % repo))

    def owner_repos(self, owner):
        return self._cached("owner:" + owner, lambda: [
            r["full_name"] for r in self._json("/users/%s/repos" % owner, per_page=100)
            if not r.get("archived")])

    def issues(self, repo, query="", limit=30, labels=()):
        if query:
            q = "repo:%s is:issue is:open %s" % (repo, query)
            q += "".join(' label:"%s"' % x for x in labels)
            got = self._json("/search/issues", q=q, per_page=limit).get("items", [])
        else:
            got = self._json("/repos/%s/issues" % repo, state="open", per_page=limit,
                             labels=",".join(labels))
        return [_brief(i) for i in got if "pull_request" not in i]

    def issue(self, repo, number):
        i = self._json("/repos/%s/issues/%d" % (repo, number))
        cs = self._json("/repos/%s/issues/%d/comments" % (repo, number), per_page=100) \
            if i.get("comments") else []
        return _issue_out(i, cs)


class Forgejo(Forge):
    kind = "forgejo"

    @property
    def api(self):
        if not self.url:
            raise ForgeError("forge %s: no url" % self.name)
        return self.url.rstrip("/") + "/api/v1"

    @property
    def web(self):
        return self.url.rstrip("/")

    def repos(self, query="", limit=30):
        got = self._json("/repos/search", q=query, limit=limit, sort="updated", order="desc")
        return [self._repo_out(r) for r in got.get("data", [])]

    def repo(self, repo):
        return self._repo_out(self._json("/repos/%s" % repo))

    def owner_repos(self, owner):
        def fetch():
            try:
                got = self._json("/orgs/%s/repos" % owner, limit=50)
            except ForgeError:
                got = self._json("/users/%s/repos" % owner, limit=50)
            return [r["full_name"] for r in got if not r.get("archived")]
        return self._cached("owner:" + owner, fetch)

    def issues(self, repo, query="", limit=30, labels=()):
        got = self._json("/repos/%s/issues" % repo, state="open", type="issues", q=query,
                         limit=limit, labels=",".join(labels))
        return [_brief(i) for i in got]

    def issue(self, repo, number):
        i = self._json("/repos/%s/issues/%d" % (repo, number))
        cs = self._json("/repos/%s/issues/%d/comments" % (repo, number)) \
            if i.get("comments") else []
        return _issue_out(i, cs)


def _brief(i):
    return {"number": i["number"], "title": i["title"], "url": i["html_url"],
            "state": i["state"], "labels": [x["name"] for x in i.get("labels") or []]}


def _issue_out(i, comments):
    return {"number": i["number"], "title": i["title"], "body": i.get("body") or "",
            "url": i["html_url"], "state": i["state"],
            "user": (i.get("user") or {}).get("login", ""),
            "labels": [x["name"] for x in i.get("labels") or []],
            "comments": [{"user": (c.get("user") or {}).get("login", ""),
                          "body": c.get("body") or "", "created": c.get("created_at", "")}
                         for c in comments]}


_KIND = {"github": GitHub, "forgejo": Forgejo}


def forges(h=None):
    """The configured forges, in order: {name: Forge}."""
    from . import registry
    try:
        cfg = registry.load_config_file(h)
    except registry.ConfigError:
        cfg = {}
    out = {}
    for f in cfg.get("forge") or []:
        out[f["name"]] = _KIND[f["kind"]](f["name"], f.get("url"), f.get("token_env"),
                                          f.get("clone", "https"))
    if not out:
        g = GitHub("github")
        if g.token():
            out["github"] = g
    return out


def get(name, h=None):
    fs = forges(h)
    if name not in fs:
        raise ForgeError("no forge named %r; there are: %s (config.toml [[forge]])" % (
            name, ", ".join(fs) or "none"))
    return fs[name]


def parse(text, h=None):
    """A repo or issue as typed or pasted: ``forge:owner/repo[#n]``, or a web URL
    of a configured forge (``…/owner/repo``, ``…/owner/repo/issues/n``).
    Returns (forge name, "owner/repo", issue number or None), or None."""
    text = (text or "").strip()
    m = re.match(r"^([a-z0-9][a-z0-9_-]*):([\w.-]+/[\w.-]+?)(?:#(\d+))?$", text)
    if m:
        return m.group(1), m.group(2), int(m.group(3)) if m.group(3) else None
    for f in forges(h).values():
        web = f.web.rstrip("/") + "/"
        if text.startswith(web):
            m = re.match(r"^([\w.-]+/[\w.-]+?)(?:\.git)?(?:/issues/(\d+))?/?$", text[len(web):])
            if m:
                return f.name, m.group(1), int(m.group(2)) if m.group(2) else None
    return None
