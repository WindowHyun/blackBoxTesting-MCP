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
