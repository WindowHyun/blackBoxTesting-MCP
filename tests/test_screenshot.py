"""T2.1 — screenshot returns valid PNG image content (CT-03)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate
from blackbox_mcp.tools.screenshot import screenshot


async def test_screenshot_returns_png(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    img = await screenshot(full_page=False)
    # mcp Image wraps raw bytes; check it carries a non-trivial PNG payload
    data = getattr(img, "data", None)
    assert data and len(data) > 100
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
