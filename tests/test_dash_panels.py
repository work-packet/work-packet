"""Dash panels and routes from plugins (design E7): the Overview, /sched and
settings slots, a per-plugin template loader over the board's own, owner-only by
default; routes under /x/<name>/; a failing panel shows its error. Also the
budget provider's reading on /sched (stage, url, notes, needs a login + renew)."""
import json
import os

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from jinja2 import DictLoader  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from work_packet import plugins  # noqa: E402
from work_packet.dash import panels  # noqa: E402
from work_packet.dash.app import create_app  # noqa: E402
from test_sched_dash import as_user, home, new  # noqa: E402,F401


class Portal:
    templates = DictLoader({
        "acme/head.html": "<p class=acme>spent {{ data.spent|money }} on {{ slot }}"
                          "{% if project %} for {{ project.name }}{% endif %}</p>",
        "acme/bad.html": "{{ nope.nope.nope }}"})

    def panels(self, slot, ctx):
        if slot == "settings":
            return [("Portal", "acme/head.html", {"spent": 12.5}),
                    ("Broken", "acme/bad.html", None)]
        return ("Portal", "acme/head.html", {"spent": 12.5})

    def routes(self):
        return [Route("/hello", lambda r: PlainTextResponse("hi " + r.method),
                      methods=["GET", "POST"])]


class Open(Portal):
    public = True

    def panels(self, slot, ctx):
        if slot == "sched":
            raise RuntimeError("portal down")
        return ("Open", "acme/head.html", {"spent": 1})


class _P:
    def __init__(self, name, obj):
        self.name, self.obj, self.module, self.ok = name, obj, "acme.dash:X", True


@pytest.fixture
def dash(monkeypatch, home):  # noqa: F811
    got = {"objs": {"portal": Portal}}
    monkeypatch.setattr(plugins, "load", lambda g: [_P(n, o) for n, o in got["objs"].items()]
                        if g == panels.GROUP else [])
    panels._made.clear()
    return got


def test_panels_on_each_slot_for_the_owner(dash, home):  # noqa: F811
    new("alpha")
    c = TestClient(create_app(home))
    for url in ("/", "/sched"):
        t = c.get(url).text
        assert "<h2 class=\"xpanel-title\">Portal</h2>" in t, url
        assert "<p class=acme>spent $12.50 on " in t
    t = c.get("/p/alpha/settings").text
    assert "spent $12.50 on settings for alpha" in t
    assert "Panel portal failed: UndefinedError" in t      # one bad panel, page still served


def test_panels_owner_only_unless_public(dash, home):  # noqa: F811
    new("alpha")
    c = TestClient(as_user(create_app(home), "bob@example.com", "tailnet"))
    assert "acme" not in c.get("/").text
    dash["objs"]["open"] = Open
    panels._made.clear()
    t = c.get("/").text
    assert "<h2 class=\"xpanel-title\">Open</h2>" in t and "Portal</h2>" not in t
    t = c.get("/sched").text
    assert "Panel open failed: portal down" in t


def test_routes_under_x_owner_only(dash, home):  # noqa: F811
    app = create_app(home)
    assert TestClient(app).get("/x/portal/hello").text == "hi GET"
    assert TestClient(app).post("/x/portal/hello").text == "hi POST"
    r = TestClient(as_user(app, "bob@example.com", "tailnet")).get("/x/portal/hello")
    assert r.status_code == 403 and "owner" in r.text
    dash["objs"] = {"open": Open}
    panels._made.clear()
    app = create_app(home)
    assert TestClient(as_user(app, "bob@example.com", "tailnet")).get("/x/open/hello").text == "hi GET"
    assert TestClient(app).get("/x/portal/hello").status_code == 404


def test_plugin_without_hooks_is_ignored(monkeypatch, home):  # noqa: F811
    monkeypatch.setattr(plugins, "load", lambda g: [_P("odd", ("obj", g))] if g == panels.GROUP else [])
    panels._made.clear()
    assert panels.mounts(home) == []
    assert TestClient(create_app(home)).get("/").status_code == 200


def test_provider_reading_on_sched(monkeypatch, home):  # noqa: F811
    from work_packet.sched import budget, config as sconfig

    class Portal:
        credential = "gateway"

    class Kind:
        renew = "wpk gateway login"
    loaded = {budget.GROUP: {"portal": Portal()}, "work_packet.credentials": {"gateway": Kind()}}
    monkeypatch.setattr(plugins, "loaded", lambda g: loaded.get(g, {}))
    os.makedirs(home, exist_ok=True)
    cfg = os.path.join(home, "config.toml")
    with open(cfg, "a") as fp:
        fp.write('\n[sched.budget]\nmeasure = "provider"\nprovider = "portal"\nperiod = "day"\n')
    os.makedirs(sconfig.sched_dir(home), exist_ok=True)
    r = {"amount": 100.0, "spent": 20.0, "period_start": "2026-10-21T00:00:00Z",
         "period_end": "2026-10-22T00:00:00Z", "tz": "UTC", "as_of": "2026-10-21T09:00:00Z",
         "stage": "80%", "blocked": False, "url": "https://portal.example.com/b", "notes": ["near cap"]}
    d = {"provider": "portal", "reading": r, "read_at": "2026-10-21T10:00:00Z",
         "error": "session expired", "needs_login": True}
    with open(os.path.join(sconfig.sched_dir(home), budget.READING), "w") as fp:
        json.dump(d, fp)
    t = TestClient(create_app(home)).get("/sched").text
    assert "From <code>portal</code>" in t
    assert "stage <b>80%</b>" in t and 'href="https://portal.example.com/b"' in t
    assert "near cap" in t
    assert "Needs a login: session expired; run <code>wpk gateway login</code>" in t
