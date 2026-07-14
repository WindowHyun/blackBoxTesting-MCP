"""CT-09: switch_frame — enter an iframe context (or back to main)."""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


@tool(description="Switch into an iframe by CSS selector for subsequent tool calls. "
                  "Pass null/empty to return to the main page context. Note: the "
                  "selector is a raw CSS iframe selector (not the D2 chain).")
async def switch_frame(selector: str | None = None) -> dict:
    session = await get_session()
    session.set_frame(selector or None)
    out: dict = {"ok": True, "context": selector or "main"}
    if selector:
        # Best-effort feedback: switching before the frame exists is valid
        # (navigate-then-switch), so this never fails — but a matched=False
        # flags a typo'd/missing selector instead of silently "succeeding"
        # and letting every later call time out with no hint.
        try:
            out["matched"] = await session.page.locator(selector).count() > 0
        except Exception:
            out["matched"] = False
    return out
