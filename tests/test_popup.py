"""Popup / new-tab tracking (real-site robustness)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate


async def test_popup_follow_and_fallback(session):
    await session.page.set_content(
        "<button id='b' onclick=\"window.open('about:blank')\">open</button>"
    )
    original = session.page

    # opening a new tab → session follows it
    await session.page.click("#b")
    await original.wait_for_timeout(300)
    popup = session.page
    assert popup is not original

    # the adopted popup is now the active page and is drivable
    await navigate(fixture_url("basic.html"), wait_until="load")
    assert "로그인" in await session.root.locator("body").aria_snapshot()

    # when the popup closes (e.g. OAuth done), fall back to the original tab
    await popup.close()
    await original.wait_for_timeout(200)
    assert session.page is original
    assert not session.page.is_closed()


# ── switch_page: adoption is reversible (2026-07) ────────────────

async def test_switch_page_returns_to_the_original_tab(session):
    """An adopted popup used to be a one-way trip.

    Every new page the context opens becomes active — needed for OAuth, but an
    ad popunder is adopted just as eagerly and every later step then ran against
    it, unrecoverable without throwing away the session.
    """
    from blackbox_mcp.tools.pages import switch_page

    await session.page.set_content(
        "<a id='pop' href='about:blank' target='_blank'>open</a>")
    original = session.page.url
    async with session._context.expect_page():
        await session.page.click("#pop")
    assert session.page is not None

    listing = await switch_page()
    assert listing["ok"] and listing["count"] >= 2

    back = await switch_page(index=0)
    assert back["ok"] is True
    assert back["index"] == 0
    assert session.page.url == original


async def test_switch_page_rejects_a_bad_index(session):
    from blackbox_mcp.tools.pages import switch_page

    res = await switch_page(index=99)
    assert res["ok"] is False
    assert "out of range" in res["error"]
    assert res["pages"], "listing should still be returned for recovery"
