"""CT-08: wait — fixed delay or wait for an element/state change."""
from __future__ import annotations

from ..browser import get_session
from ..browser.locator import locate
from ._registry import tool


@tool(description="Wait: pass ms for a fixed delay, or selector to wait until that "
                  "element appears (up to timeout_ms, default 10000). Used for "
                  "time-based UI (auto-play sliders, lazy content, etc.).")
async def wait(ms: int | None = None, selector: str | None = None,
               timeout_ms: int = 10000) -> dict:
    session = await get_session()
    if selector is not None:
        try:
            await locate(session.root, selector).wait_for(
                state="visible", timeout=timeout_ms)
        except Exception as exc:
            return {"ok": False, "waited": f"selector:{selector}",
                    "error": f"not visible within {timeout_ms}ms ({type(exc).__name__})"}
        return {"ok": True, "waited": f"selector:{selector}"}
    if ms is not None:
        await session.page.wait_for_timeout(ms)
        return {"ok": True, "waited": f"{ms}ms"}
    return {"ok": False, "waited": "noop", "error": "provide ms or selector"}
