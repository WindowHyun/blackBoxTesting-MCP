"""CT-08: wait — fixed delay or wait for an element/state change."""
from __future__ import annotations

import time

from ..browser import get_session
from ..browser.locator import resolve
from ._registry import tool

_POLL_MS = 100


@tool(description="Wait: pass ms for a fixed delay, or selector to wait until that "
                  "element appears (up to timeout_ms, default 10000). Used for "
                  "time-based UI (auto-play sliders, lazy content, etc.).")
async def wait(ms: int | None = None, selector: str | None = None,
               timeout_ms: int = 10000) -> dict:
    session = await get_session()
    if selector is not None:
        # Re-resolve every poll: the whole point of wait is that the element
        # is NOT there yet, so a single resolve() at call time would probe all
        # tiers empty and lock onto the text fallback — a spaced CSS selector
        # ("#results .row") appearing later would then never be seen. Polling
        # the chain until the deadline picks the right tier whenever the
        # element materializes (Playwright's own auto-waiting also polls).
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            try:
                loc, _ = await resolve(session.root, selector, visible_only=True)
                if await loc.filter(visible=True).count() > 0:
                    return {"ok": True, "waited": f"selector:{selector}"}
            except Exception:
                pass  # e.g. mid-navigation context loss — retry until deadline
            if time.monotonic() >= deadline:
                return {"ok": False, "waited": f"selector:{selector}",
                        "error": f"not visible within {timeout_ms}ms (TimeoutError)"}
            await session.page.wait_for_timeout(_POLL_MS)
    if ms is not None:
        await session.page.wait_for_timeout(ms)
        return {"ok": True, "waited": f"{ms}ms"}
    return {"ok": False, "waited": "noop", "error": "provide ms or selector"}
