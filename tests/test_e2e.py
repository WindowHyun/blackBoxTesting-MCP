"""End-to-end smoke across Phase 1+2 tools in one realistic flow.

Proves the integrated surface (navigate → snapshot → interact → assert →
screenshot → logs/network) works together, not just in isolation.
"""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate
from blackbox_mcp.tools.snapshot import snapshot
from blackbox_mcp.tools.interact import interact
from blackbox_mcp.tools.assertion import assert_
from blackbox_mcp.tools.screenshot import screenshot
from blackbox_mcp.tools.console import get_console_logs
from blackbox_mcp.tools.network import get_network_errors


async def test_login_flow_end_to_end(session):
    nav = await navigate(fixture_url("basic.html"), wait_until="load")
    assert nav["title"] == "Blackbox Fixture"

    assert "로그인" in await snapshot()

    assert (await interact("type", "testid=email", "u@x.com"))["ok"]
    click = await interact("click", "testid=submit")
    assert click["ok"] and click["resolved_by"] == "testid"

    # click handler flips status text
    assert (await assert_("text_visible", "로그인됨"))["passed"]

    img = await screenshot()
    assert img.data[:8] == b"\x89PNG\r\n\x1a\n"

    # fixture intentionally logs a console error and loads a missing image
    assert any("fixture console error" in e["text"] for e in await get_console_logs("error"))
    assert any("does-not-exist.png" in e["url"] for e in await get_network_errors())
