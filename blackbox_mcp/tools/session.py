"""BR-04: reset_session — wipe context + buffers, fresh page."""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


@tool(description="Reset the browser context (cookies/session/storage + console "
                  "/network buffers) and start a fresh page. Recommended before "
                  "each scenario to avoid state bleed. NOTE: in real-browser modes "
                  "(use_real_browser / BROWSER_CDP) only the console/network "
                  "buffers are cleared — the logged-in session is preserved.")
async def reset_session() -> dict:
    session = await get_session()
    await session.reset()
    return {"ok": True, "message": "session reset"}
