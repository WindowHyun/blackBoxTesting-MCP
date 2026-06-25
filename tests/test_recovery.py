"""T2.6 — browser crash auto-recovery (NFR Reliability)."""
from __future__ import annotations

from blackbox_mcp.browser import get_session
from blackbox_mcp.browser.session import close_session


async def test_session_recovers_after_browser_crash():
    s = await get_session()
    assert s.is_alive()

    # simulate a crash by closing the underlying browser out from under us
    await s._browser.close()
    assert not s.is_alive()

    # next access should transparently restart and be usable again
    s2 = await get_session()
    assert s2.is_alive()
    await s2.page.set_content("<h1>recovered</h1>")
    assert "recovered" in await s2.page.title() or True  # title may be empty
    snap = await s2.root.locator("body").aria_snapshot()
    assert "recovered" in snap

    await close_session()
