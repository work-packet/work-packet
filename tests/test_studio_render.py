"""The render service (docs/studio-plan.md P0.4): unit tests against
``tests/fakechrome.py``, and ``live`` ones against the browser on this host."""

import os
import struct
import sys
import time
import zlib

import pytest

from work_packet.studio import render

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakechrome.py")


@pytest.fixture
def fakechrome(tmp_path, monkeypatch):
    """(path of a fake browser executable, its call log)."""
    exe = tmp_path / "fake-chrome"
    exe.write_text('#!/bin/sh\nexec %s %s "$@"\n' % (sys.executable, FAKE))
    exe.chmod(0o755)
    logf = tmp_path / "chrome.log"
    monkeypatch.setenv("FAKECHROME_LOG", str(logf))
    return str(exe), logf


def _calls(logf):
    return logf.read_text().splitlines() if logf.exists() else []


@pytest.fixture
def browser(fakechrome, tmp_path):
    b = render.Browser(exe=fakechrome[0], home=str(tmp_path / "home"), idle_s=60, timeout_s=10)
    yield b
    b.stop()


def test_find_browser(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "chromium"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(exe.parent))
    assert render.find_browser({"chrome": ""}) == str(exe)
    assert render.find_browser({"chrome": str(exe)}) == str(exe)
    assert render.find_browser({"chrome": "nosuch"}) is None
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert render.find_browser({"chrome": ""}) is None
    b = render.Browser(exe=None, home=str(tmp_path))
    b.exe = None
    assert not b.available
    with pytest.raises(render.RenderError, match="no browser"):
        b.render("about:blank")


def test_config_is_validated():
    from work_packet import schema
    assert not schema.validate_config({"studio": {"chrome": "/x", "render_idle_minutes": 5}})
    bad = schema.validate_config({"studio": {"chrome": 3, "render_idle_minutes": 0, "x": 1}})
    assert {p.field for p in bad} >= {"studio.chrome", "studio.render_idle_minutes"}


def test_render_png_pdf_value(browser, fakechrome, tmp_path):
    exe, logf = fakechrome
    png, pdf = str(tmp_path / "o" / "a.png"), str(tmp_path / "o" / "a.pdf")
    r = browser.render("http://x/page", png=png, pdf=pdf, script="1+1", width=800, height=600)
    assert r["ready"] and r["value"] == "value of 1+1" and r["size"] == (1200, 1600)
    assert open(png, "rb").read().startswith(b"\x89PNG") and open(pdf, "rb").read()[:5] == b"%PDF-"
    assert r["errors"] == ["fake error"]
    calls = _calls(logf)
    assert "Page.navigate http://x/page" in calls
    assert 'clip {"x": 0, "y": 0, "width": 1200, "height": 1600, "scale": 1}' in calls
    assert calls.index("Target.createTarget") < calls.index("Target.closeTarget")
    argv = [c for c in calls if c.startswith("argv ")][0]
    assert "--headless=new" in argv and "render-profile" in argv
    # One browser for many renders.
    browser.render("http://x/2")
    assert sum(1 for c in _calls(logf) if c.startswith("argv ")) == 1


def test_render_an_element(browser, fakechrome, tmp_path):
    exe, logf = fakechrome
    browser.render("http://x/", png=str(tmp_path / "e.png"), selector="#chart")
    assert 'clip {"x": 10, "y": 20, "width": 30, "height": 40, "scale": 1}' in _calls(logf)
    with pytest.raises(render.RenderError, match="no element"):
        browser.render("http://x/", png=str(tmp_path / "e.png"), selector="#none")


def test_errors(browser, monkeypatch, tmp_path):
    with pytest.raises(render.RenderError, match="ERR_FILE_NOT_FOUND"):
        browser.render("file:///missing.html")
    with pytest.raises(render.RenderError, match="Error: thrown"):
        browser.render("http://x/", script="throw 1")
    monkeypatch.setenv("FAKECHROME_NOT_READY", "1")
    browser.stop()                      # the next start sees the setting
    r = browser.render("http://x/", ready_timeout_s=0.2)
    assert r["ready"] is False


def test_does_not_start(fakechrome, tmp_path, monkeypatch):
    monkeypatch.setattr(render, "START_TIMEOUT_S", 5)
    monkeypatch.setenv("FAKECHROME_NO_START", "1")
    b = render.Browser(exe=fakechrome[0], home=str(tmp_path))
    with pytest.raises(render.RenderError, match="did not start"):
        b.render("http://x/")


def test_reaped_when_idle_and_restarted(browser, fakechrome):
    exe, logf = fakechrome
    browser.render("http://x/")
    assert browser.running and not browser.reap()
    assert browser.reap(now=time.monotonic() + 61) and not browser.running
    browser.render("http://x/")
    assert browser.running
    assert sum(1 for c in _calls(logf) if c.startswith("argv ")) == 2


def test_queue_runs_only_the_newest(browser, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKECHROME_SLOW", "0.5")
    q = render.Queue(browser)
    first = q.submit("chart", "http://x/1", png=str(tmp_path / "1.png"))
    time.sleep(0.3)                     # it is running now
    second = q.submit("chart", "http://x/2", png=str(tmp_path / "2.png"))
    third = q.submit("chart", "http://x/3", png=str(tmp_path / "3.png"))
    other = q.submit("doc", "http://x/doc", png=str(tmp_path / "d.png"))
    assert first.result(10)["png"].endswith("1.png")
    assert second.result(10) is None            # superseded before it ran
    assert third.result(10)["png"].endswith("3.png")
    assert other.result(10)["png"].endswith("d.png")
    assert q.last("chart")["png"].endswith("3.png")
    bad = q.submit("chart", "file:///missing.html")
    with pytest.raises(render.RenderError):
        bad.result(10)
    assert q.last("chart")["png"].endswith("3.png")   # the last good one is kept


# --- live: the browser on this host ------------------------------------------------

def _png_pixel(path, x, y):
    """(r, g, b) at ``x, y`` of an 8-bit RGB or RGBA, non-interlaced PNG."""
    data = open(path, "rb").read()
    pos, idat, w = 8, b"", None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype in (2, 6)
            bpp = 3 if ctype == 2 else 4
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = w * bpp
    prev = bytearray(stride)
    rows = []
    for r in range(y + 1):
        f = raw[r * (stride + 1)]
        line = bytearray(raw[r * (stride + 1) + 1:(r + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    px = rows[y][x * bpp:x * bpp + 3]
    return tuple(px), (w, h)


live = pytest.mark.skipif(os.environ.get("WPK_LIVE") != "1" or not render.find_browser({}),
                          reason="set WPK_LIVE=1, with a browser on PATH")


@pytest.mark.live
@live
def test_live_png_and_pdf(tmp_path):
    page = tmp_path / "p.html"
    page.write_text("<!doctype html><html><body style='margin:0;background:#ff0000'>"
                    "<div id='box' style='width:120px;height:60px;background:#0000ff'></div>"
                    "<div style='height:1500px'></div>"
                    "<script>window.__studioReady = false;"
                    "setTimeout(() => { window.__studioReady = true; }, 100)</script>"
                    "</body></html>")
    b = render.Browser(home=str(tmp_path / "home"))
    try:
        r = b.render("file://%s" % page, png=str(tmp_path / "a.png"), pdf=str(tmp_path / "a.pdf"),
                     width=400, height=300, script="document.querySelectorAll('div').length")
        assert r["ready"] and r["value"] == 2 and r["errors"] == []
        px, size = _png_pixel(str(tmp_path / "a.png"), 10, 10)
        assert px == (0, 0, 255) and size[0] == 400 and size[1] >= 1500   # the whole page
        assert _png_pixel(str(tmp_path / "a.png"), 200, 10)[0] == (255, 0, 0)
        assert open(tmp_path / "a.pdf", "rb").read()[:5] == b"%PDF-"
        assert os.path.getsize(tmp_path / "a.pdf") > 500
        b.render("file://%s" % page, png=str(tmp_path / "e.png"), selector="#box")
        px, size = _png_pixel(str(tmp_path / "e.png"), 5, 5)
        assert px == (0, 0, 255) and size == (120, 60)
    finally:
        b.stop()
