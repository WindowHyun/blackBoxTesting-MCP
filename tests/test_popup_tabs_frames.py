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


# ── P3-12 / P3-13: one tab index, one adoption ───────────────────────
def test_tab_indices_come_from_one_list():
    """list_pages() numbered the UNFILTERED context.pages while switch_page()
    indexed the filtered one, so the two disagreed as soon as a closed page
    was still present. Both now read open_pages()."""
    import inspect

    from blackbox_mcp.browser.session import BrowserSession

    for fn in (BrowserSession.list_pages, BrowserSession.switch_page,
               BrowserSession._on_page_closed):
        assert "open_pages()" in inspect.getsource(fn), fn.__name__


async def test_list_tabs_titles_line_up_with_switch_tab(session, tmp_path):
    from blackbox_mcp.tools.tabs import list_tabs, switch_tab

    a = tmp_path / "a.html"; a.write_text("<title>AAA</title>a", encoding="utf-8")
    b = tmp_path / "b.html"; b.write_text("<title>BBB</title>b", encoding="utf-8")
    await session.page.goto(a.as_uri())
    p2 = await session._context.new_page()
    await p2.goto(b.as_uri())

    tabs = await list_tabs()
    assert [t["title"] for t in tabs] == ["AAA", "BBB"]
    for tab in tabs:
        got = await switch_tab(tab["index"])
        assert got["ok"] is True
        assert got["url"] == tab["url"]
    await p2.close()


async def test_popup_is_adopted_once(session, tmp_path):
    """expect_popup adopts explicitly on top of the context listener; without a
    guard the same popup was adopted twice, parking a second _page_ready task
    that replaced — and orphaned — the first.

    Counts _await_page_ready instead of patching _adopt_page: the context
    listener holds a BOUND _adopt_page captured when the context was created,
    so a class-level patch of it would only see the explicit call.
    """
    from blackbox_mcp.browser import session as session_mod
    from blackbox_mcp.tools.navigate import navigate
    from blackbox_mcp.tools.popup import expect_popup

    target = tmp_path / "pop.html"
    target.write_text("<title>POP</title><h1>팝업</h1>", encoding="utf-8")
    opener = tmp_path / "opener.html"
    opener.write_text(
        f"<a id='go' href='{target.as_uri()}' target='_blank'>팝업 열기</a>",
        encoding="utf-8")

    parked: list = []
    real = session_mod.BrowserSession._await_page_ready

    async def counting(page):
        parked.append(page)
        return await real(page)

    session_mod.BrowserSession._await_page_ready = staticmethod(counting)
    try:
        await navigate(opener.as_uri(), wait_until="load")
        r = await expect_popup("팝업 열기", expect_url="pop.html")
    finally:
        session_mod.BrowserSession._await_page_ready = staticmethod(real)

    assert r["passed"] is True
    assert len(parked) == 1, f"popup adopted {len(parked)} times"
