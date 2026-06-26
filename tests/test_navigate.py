"""T1.3 — navigate integration + event buffers (CT-01, CT-06, CT-07, BR-02)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate
from blackbox_mcp.tools.console import get_console_logs
from blackbox_mcp.tools.network import get_network_errors


async def test_navigate_returns_title_and_url(session):
    result = await navigate(fixture_url("basic.html"), wait_until="load")
    assert result["title"] == "Blackbox Fixture"
    assert result["url"].endswith("basic.html")
    # file:// yields either no status or 200 depending on the engine
    assert result["status"] in (None, 200)


async def test_console_buffer_captures_error(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    errors = await get_console_logs(level="error")
    assert any("fixture console error" in e["text"] for e in errors)


async def test_network_buffer_captures_failed_request(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    net = await get_network_errors()
    # the missing image should surface as a failed request
    assert any("does-not-exist.png" in e["url"] for e in net)


async def test_navigate_resets_frame_context(session):
    # a stale iframe context must not survive a top-level navigation
    session.set_frame("#some-frame")
    await navigate(fixture_url("basic.html"), wait_until="load")
    assert session._frame_selector is None
