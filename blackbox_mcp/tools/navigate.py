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
    page = session.page

    # Did the browser actually commit a new document? A goto() timeout covers
    # two opposite outcomes — "the DOM is there, only networkidle timed out"
    # (fine, proceed) and "the server never answered, we are still on the old
    # page" (the site is down) — and they are indistinguishable from the
    # exception alone. Reporting the second as a pass meant a scenario went
    # green against a dead server, with the report itself printing
    # "navigated to about:blank".
    #
    # framenavigated on the MAIN frame is the commit signal: it fires exactly
    # when a new document is committed, so it stays right where comparing URLs
    # does not (re-navigating to the URL already loaded, redirects, hash-only
    # navigations). Sub-frame events say nothing about the top-level document.
    committed = False

    def _on_frame_navigated(frame) -> None:
        nonlocal committed
        if frame is page.main_frame:
            committed = True

    page.on("framenavigated", _on_frame_navigated)

    settled = True
    try:
        response = await page.goto(url, wait_until=wu, timeout=CONFIG.nav_timeout_ms)
    except PlaywrightTimeoutError:
        response = None
        settled = False
        if not committed:
            return {
                "title": None,
                "url": page.url,
                "status": None,
                "settled": False,
                "wait_until": wu,
                "error": scrub(
                    f"navigation did not commit within {CONFIG.nav_timeout_ms}ms — "
                    f"no response from the server (still at {page.url})"),
            }
        # Committed: the DOM is there and only the settle condition (e.g.
        # networkidle on an ad-heavy page) ran out. Proceed with the page.
    except Exception as exc:
        # A hard navigation failure — DNS, refused connection, bad certificate,
        # proxy tunnel error: exactly the class of problem a closed corporate
        # network produces. Returning it as data (rather than raising) gives the
        # caller the reason and lets the runner mark the step failed; raising
        # here surfaced as an opaque MCP tool error with no page context.
        return {
            "title": None,
            "url": page.url,
            "status": None,
            "settled": False,
            "wait_until": wu,
            "error": scrub(f"{type(exc).__name__}: {exc}"),
        }
    finally:
        # Never leave the probe attached: navigate runs on every step of every
        # scenario, and the listeners would pile up on the same page.
        try:
            page.remove_listener("framenavigated", _on_frame_navigated)
        except Exception:
            pass

    return {
        "title": await page.title(),
        "url": page.url,
        "status": response.status if response else None,
        "settled": settled,
        "wait_until": wu,
        "error": None,
    }
