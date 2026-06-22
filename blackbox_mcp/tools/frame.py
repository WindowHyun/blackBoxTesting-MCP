"""CT-09: switch_frame — enter an iframe context (or back to main)."""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


@tool(description="Switch into an iframe by CSS selector for subsequent tool calls. "
                  "Pass null/empty to return to the main page context.")
async def switch_frame(selector: str | None = None) -> dict:
    session = await get_session()
    session.set_frame(selector or None)
    return {"ok": True, "context": selector or "main"}
