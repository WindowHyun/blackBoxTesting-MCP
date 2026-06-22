"""CT-03: screenshot — returns MCP image content for visual verification."""
from __future__ import annotations

from mcp.server.fastmcp import Image

from ..browser import get_session
from ._registry import tool


@tool(description="Capture a screenshot and return it as an image for visual checks.")
async def screenshot(full_page: bool = False) -> Image:
    session = await get_session()
    data = await session.page.screenshot(full_page=full_page)
    return Image(data=data, format="png")
