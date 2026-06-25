"""CT-01: navigate."""
from __future__ import annotations

from ..browser import get_session
from ..config import CONFIG
from ._registry import tool


@tool(description="Navigate to a URL and wait for the page to settle. "
                  "wait_until ∈ load|domcontentloaded|networkidle|commit.")
async def navigate(url: str, wait_until: str | None = None) -> dict:
    session = await get_session()
    # A top-level navigation invalidates any iframe we'd switched into.
    session.set_frame(None)
    response = await session.page.goto(
        url, wait_until=wait_until or CONFIG.default_wait_until
    )
    return {
        "title": await session.page.title(),
        "url": session.page.url,
        "status": response.status if response else None,
    }
