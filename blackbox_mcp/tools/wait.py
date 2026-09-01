"""CT-08: wait — fixed delay or wait for an element/state change."""
from __future__ import annotations

import asyncio
import time

from ..browser import get_session
from ..browser.locator import is_single_strategy, resolve
from ._registry import tool

# Poll cadence. A bare-string selector re-runs the whole D2 chain each poll —
# CSS (conditionally) + testid + 10 roles + text, one driver round trip each —
# so a flat 100ms cost ~12 round trips every 100ms: measured 208 Locator.count()
# calls for a 2s wait (vs 21 for an explicit `css=` prefix). The first polls stay
# fast because most elements appear almost immediately; after that the interval
# ramps so a long wait on a slow/remote target does not spend its budget on IPC.
_POLL_MS = 100
_POLL_MAX_MS = 500
_POLL_GROWTH = 1.4


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
        single = is_single_strategy(selector)
        last_exc: Exception | None = None
        streak = 0  # consecutive polls failing with the IDENTICAL error
        delay_ms = float(_POLL_MS)
        while True:
            try:
                loc, _ = await resolve(session.root, selector, visible_only=True)
                if await loc.filter(visible=True).count() > 0:
                    return {"ok": True, "waited": f"selector:{selector}"}
                last_exc, streak = None, 0  # probe worked; element not there yet
            except Exception as exc:
                # Deterministic failures (a CSS parse error on an explicit
                # prefix/bare-CSS selector) repeat IDENTICALLY every poll —
                # fail fast with the real cause instead of spinning to the
                # deadline. Transient ones (TargetClosed when the active popup
                # closes mid-probe) do NOT repeat: the session swaps to a
                # surviving page and the next poll re-reads session.root — so
                # a single occurrence must never abort the wait.
                same = (last_exc is not None and type(exc) is type(last_exc)
                        and str(exc) == str(last_exc))
                streak = streak + 1 if same else 1
                last_exc = exc
                if single and streak >= 2:
                    return {"ok": False, "waited": f"selector:{selector}",
                            "error": f"selector failed ({type(exc).__name__})"}
            if time.monotonic() >= deadline:
                kind = type(last_exc).__name__ if last_exc is not None else "TimeoutError"
                return {"ok": False, "waited": f"selector:{selector}",
                        "error": f"not visible within {timeout_ms}ms ({kind})"}
            # asyncio.sleep, not page.wait_for_timeout: the sleep must not
            # itself raise when the page that started the wait just closed.
            # Never sleep past the deadline — the caller asked for timeout_ms.
            remaining = deadline - time.monotonic()
            await asyncio.sleep(min(delay_ms / 1000, max(remaining, 0)))
            delay_ms = min(_POLL_MAX_MS, delay_ms * _POLL_GROWTH)
    if ms is not None:
        await session.page.wait_for_timeout(ms)
        return {"ok": True, "waited": f"{ms}ms"}
    return {"ok": False, "waited": "noop", "error": "provide ms or selector"}
