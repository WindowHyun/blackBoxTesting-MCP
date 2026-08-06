"""Popups, explicit tab control, and nested iframes."""
from __future__ import annotations

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from blackbox_mcp.tools.assertion import assert_
from blackbox_mcp.tools.frame import switch_frame
from blackbox_mcp.tools.popup import expect_popup
from blackbox_mcp.tools.tabs import list_tabs, switch_tab

_SLOW_S = 0.6


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/slow"):
            time.sleep(_SLOW_S)
            body = b"<h1 data-testid=pop>POPUP READY</h1>"
        else:
            body = (b"<button id=b onclick=\"window.open('/slow')\">go</button>"
                    b"<div data-testid=opener>OPENER</div>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def slow_site():
    """A server that answers the popup slowly — the condition under which a
    bare click → assert races the popup into existence."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()


# ── popups ───────────────────────────────────────────────────────
@pytest.mark.browser
async def test_expect_popup_waits_for_a_slow_popup(session, slow_site):
    """Regression: Chromium does not emit the context "page" event until the
    popup has committed its navigation, so auto-adoption alone left the next
    assertion running against the opener."""
    await session.page.goto(slow_site)

    res = await expect_popup("css=#b", expect_url="/slow")
    assert res["passed"], res
    assert res["url"].endswith("/slow")
    # the popup is active AND parsed — assert immediately, no sleep
    assert (await assert_("element_visible", "testid=pop"))["passed"]


@pytest.mark.browser
async def test_expect_popup_reports_url_mismatch(session, slow_site):
    await session.page.goto(slow_site)
    res = await expect_popup("css=#b", expect_url="/nope")
    assert not res["passed"]
    assert "/slow" in res["error"]


@pytest.mark.browser
async def test_expect_popup_distinguishes_bad_trigger_from_no_popup(session, slow_site):
    await session.page.goto(slow_site)
    bad = await expect_popup("css=#does-not-exist")
    assert "trigger click failed" in bad["error"]

    none = await expect_popup("testid=opener", timeout_ms=800)
    assert "no popup opened" in none["error"]


# ── tabs ─────────────────────────────────────────────────────────
@pytest.mark.browser
async def test_switch_tab_returns_to_the_opener(session, slow_site):
    await session.page.goto(slow_site)
    await expect_popup("css=#b")

    tabs = await list_tabs()
    assert len(tabs) == 2
    assert tabs[1]["active"] is True and tabs[0]["active"] is False

    assert (await switch_tab(0))["ok"]
    # back on the opener, and able to assert on it
    assert (await assert_("element_visible", "testid=opener"))["passed"]
    assert (await list_tabs())[0]["active"] is True


@pytest.mark.browser
async def test_switch_tab_out_of_range_is_an_error_not_a_crash(session):
    res = await switch_tab(9)
    assert not res["ok"] and "out of range" in res["error"]
    assert res["tabs"]


# ── nested iframes ───────────────────────────────────────────────
async def _nested_frames(session):
    inner = "<button data-testid=deep>deep</button>"
    mid = f'<iframe id=inner srcdoc="{inner.replace(chr(34), "&quot;")}"></iframe>'
    await session.page.set_content(
        f'<iframe id=outer srcdoc="{mid.replace(chr(34), "&quot;")}"></iframe>')
    await session.page.wait_for_timeout(300)


async def test_nested_iframe_chain(session):
    """Regression: a selector string never crosses a frame boundary, so the old
    single-frame_locator context could not reach a nested iframe at all."""
    await _nested_frames(session)

    res = await switch_frame("#outer >>> #inner")
    assert res["ok"] and res["matched"] and res["depth"] == 2
    assert (await assert_("element_visible", "testid=deep"))["passed"]


async def test_nested_iframe_reports_which_hop_is_missing(session):
    await _nested_frames(session)
    res = await switch_frame("#outer >>> #typo")
    assert res["matched"] is False
    assert res["missing_at"] == {"depth": 1, "selector": "#typo"}


async def test_single_frame_still_works_and_main_resets(session):
    await _nested_frames(session)
    assert (await switch_frame("#outer"))["depth"] == 1
    assert session.frame_chain == ["#outer"]

    assert (await switch_frame(None))["context"] == "main"
    assert session.frame_chain == []
    assert session._frame_selector is None


async def test_set_frame_accepts_a_list(session):
    session.set_frame(["#outer", "#inner"])
    assert session.frame_chain == ["#outer", "#inner"]
    assert session._frame_selector == "#outer >>> #inner"


async def test_settle_is_a_noop_without_a_pending_popup(session):
    """Every tool call goes through settle(); it must cost nothing normally."""
    started = time.monotonic()
    await session.settle()
    assert time.monotonic() - started < 0.1
    assert session._page_ready is None


async def test_settle_survives_a_popup_that_never_loads(session):
    """A parked load task that fails must not raise into the next tool call."""
    async def never():
        await asyncio.sleep(30)

    task = asyncio.get_running_loop().create_task(never())
    session._page_ready = task
    from blackbox_mcp.browser import session as session_mod
    original, session_mod._POPUP_SETTLE_S = session_mod._POPUP_SETTLE_S, 0.1
    try:
        await session.settle()   # must return, not hang or raise
    finally:
        session_mod._POPUP_SETTLE_S = original
        task.cancel()
    assert session._page_ready is None
