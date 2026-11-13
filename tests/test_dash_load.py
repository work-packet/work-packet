"""The board is built once for every tab asking, off the event loop
(docs/cpu-plan.md P1.4)."""

import asyncio
import threading
import time

import pytest

from work_packet.dash import data


@pytest.fixture
def slow_board(monkeypatch):
    """``data.board`` takes ``delay`` seconds and counts its calls."""
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    state = {"n": 0, "delay": 0.3}
    lock = threading.Lock()

    def board(h=None, now=None, rows=None):
        with lock:
            state["n"] += 1
        time.sleep(state["delay"])
        return {c: [] for c in data.COLUMNS}, []
    monkeypatch.setattr(data, "board", board)
    return state


def _get_all(app, paths):
    import httpx

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://127.0.0.1") as c:
            async def one(p):
                t = time.monotonic()
                r = await c.get(p)
                return r.status_code, time.monotonic() - t
            return await asyncio.gather(*(one(p) for p in paths))
    return asyncio.run(go())


def test_tabs_asking_at_once_share_one_build(slow_board):
    from work_packet.dash.app import create_app
    got = _get_all(create_app(), ["/attention.json", "/attention.json", "/packets"])
    assert [s for s, _ in got] == [200, 200, 200]
    assert slow_board["n"] == 1


def test_a_build_is_not_kept_after(slow_board):
    from work_packet.dash.app import create_app
    app = create_app()
    _get_all(app, ["/attention.json"])
    _get_all(app, ["/attention.json"])
    assert slow_board["n"] == 2                          # a change from the CLI shows at once


def test_a_slow_board_does_not_hold_up_other_pages(slow_board):
    from work_packet.dash.app import create_app
    slow_board["delay"] = 1.5
    got = _get_all(create_app(), ["/attention.json", "/healthz"])
    assert got[0][1] >= 1.5 and got[1][1] < 0.5
