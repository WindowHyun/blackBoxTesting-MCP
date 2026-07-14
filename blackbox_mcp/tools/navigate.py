"""CT-01: navigate."""
from __future__ import annotations

from typing import Literal

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ..browser import get_session
from ..config import CONFIG
from ._registry import tool

WaitUntil = Literal["load", "domcontentloaded", "networkidle", "commit"]


@tool(description="Navigate to a URL and wait for the page to settle. "
                  "wait_until ∈ load|domcontentloaded|networkidle|commit. Real "
                  "sites that never reach networkidle fall back to "
                  "domcontentloaded instead of hanging. Result: {ok, status, "
                  "title, url, settled, error}. ok=false only on a navigation "
                  "ERROR (DNS/refused/invalid URL) — an HTTP 4xx/5xx still "
                  "loads a page so ok=true with that status.")
async def navigate(url: str, wait_until: WaitUntil | None = None) -> dict:
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
    except PlaywrightError as exc:
        # DNS / connection refused / invalid URL: there is no page to inspect.
        # Return a structured failure (ok=false) instead of raising — a raise
        # surfaces as an opaque FastMCP isError and loses the url/context, and
        # is a *different* shape from the success/4xx case. scrub: the URL may
        # carry a resolved secret in the error text.
        from ..testing.secrets import scrub
        return {"ok": False, "title": None, "url": url, "status": None,
                "settled": False, "wait_until": wu,
                "error": scrub(f"{type(exc).__name__}: {exc}")}

    return {
        "ok": True,
        "title": await session.page.title(),
        "url": session.page.url,
        "status": response.status if response else None,
        "settled": settled,
        "wait_until": wu,
        "error": None,
    }
