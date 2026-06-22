"""CT-08: wait — fixed delay or wait for an element/state change."""
from __future__ import annotations

from ..browser import get_session
from ..browser.locator import locate
from ._registry import tool


@tool(description="Wait: pass ms for a fixed delay, or selector to wait until that "
                  "element appears. Used for time-based UI (auto-play sliders, etc.).")
async def wait(ms: int | None = None, selector: str | None = None) -> dict:
    session = await get_session()
    if selector is not None:
        await locate(session.root, selector).wait_for(state="visible")
        return {"ok": True, "waited": f"selector:{selector}"}
    if ms is not None:
        await session.page.wait_for_timeout(ms)
        return {"ok": True, "waited": f"{ms}ms"}
    return {"ok": False, "waited": "noop", "error": "provide ms or selector"}
