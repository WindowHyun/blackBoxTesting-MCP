"""CT-01: navigate."""
from __future__ import annotations

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ..browser import get_session
from ..config import CONFIG
from ..testing.secrets import scrub
from ._registry import tool


@tool(description="Navigate to a URL and wait for the page to settle. "
                  "wait_until ∈ load|domcontentloaded|networkidle|commit. Real "
                  "sites that never reach networkidle fall back to "
                  "domcontentloaded instead of hanging.")
async def navigate(url: str, wait_until: str | None = None) -> dict:
    session = await get_session()
    # A top-level navigation invalidates any iframe we'd switched into.
    session.set_frame(None)
    wu = wait_until or CONFIG.default_wait_until

    settled = True
    try:
        response = await session.page.goto(
            url, wait_until=wu, timeout=CONFIG.nav_timeout_ms
        )
    except PlaywrightTimeoutError:
        # The navigation almost certainly committed (DOM is there); only the
        # "settled" condition (e.g. networkidle on an ad-heavy page) timed out.
        # Proceed with the current page state rather than failing the step.
        response = None
        settled = False
    except Exception as exc:
        # A hard navigation failure — DNS, refused connection, bad certificate,
        # proxy tunnel error: exactly the class of problem a closed corporate
        # network produces. Returning it as data (rather than raising) gives the
        # caller the reason and lets the runner mark the step failed; raising
        # here surfaced as an opaque MCP tool error with no page context.
        return {
            "title": None,
            "url": session.page.url,
            "status": None,
            "settled": False,
            "wait_until": wu,
            "error": scrub(f"{type(exc).__name__}: {exc}"),
        }

    return {
        "title": await session.page.title(),
        "url": session.page.url,
        "status": response.status if response else None,
        "settled": settled,
        "wait_until": wu,
        "error": None,
    }
