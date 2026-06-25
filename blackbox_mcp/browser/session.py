"""BrowserSession singleton (BR-01, BR-03, BR-04) + crash recovery (NFR).

A single async Playwright browser context lives for the life of the process so
cookies / session / localStorage persist across tool calls. Using the *async*
Playwright API keeps us compatible with the async MCP event loop (the sync API
cannot run inside asyncio).
"""
from __future__ import annotations

import logging

from ..config import CONFIG
from .listeners import EventBuffers, attach

log = logging.getLogger(__name__)


class BrowserSession:
    """Owns the Playwright lifecycle and the current page/frame context."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        # Current iframe context for CT-09; None == main page.
        self._frame_selector: str | None = None
        self.buffers = EventBuffers()

    # ── lifecycle ────────────────────────────────────────────────
    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        browser_type = getattr(self._pw, CONFIG.browser)
        launch_kwargs = {"headless": CONFIG.headless}
        if CONFIG.chromium_executable:
            launch_kwargs["executable_path"] = CONFIG.chromium_executable
        self._browser = await browser_type.launch(**launch_kwargs)
        await self._new_context()
        log.info(
            "BrowserSession started (%s, headless=%s, executable=%s)",
            CONFIG.browser, CONFIG.headless, CONFIG.chromium_executable or "bundled",
        )

    async def _new_context(self) -> None:
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        self._frame_selector = None
        self.buffers.clear()
        attach(self._page, self.buffers)

    async def reset(self) -> None:
        """BR-04: wipe context (cookies/session/storage) + buffers, fresh page."""
        if self._context is not None:
            await self._context.close()
        await self._new_context()
        log.info("BrowserSession reset.")

    async def restart(self) -> None:
        """Recover from a browser crash (NFR Reliability, < 5s)."""
        log.warning("BrowserSession restarting after failure.")
        await self.close()
        await self.start()

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
        finally:
            self._pw = self._browser = self._context = self._page = None

    # ── accessors ────────────────────────────────────────────────
    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("BrowserSession not started.")
        return self._page

    @property
    def root(self):
        """Active root for actions: the current frame locator, or the page."""
        if self._frame_selector is None:
            return self._page
        return self._page.frame_locator(self._frame_selector)

    def set_frame(self, selector: str | None) -> None:
        """CT-09: switch into an iframe (or back to main with None)."""
        self._frame_selector = selector


# ── module-level singleton (BR-01) ───────────────────────────────
_SESSION: BrowserSession | None = None


async def get_session() -> BrowserSession:
    """Lazily create and start the single BrowserSession."""
    global _SESSION
    if _SESSION is None:
        _SESSION = BrowserSession()
        await _SESSION.start()
    return _SESSION


async def close_session() -> None:
    """Close and drop the singleton (used by the server lifespan on shutdown)."""
    global _SESSION
    if _SESSION is not None:
        await _SESSION.close()
        _SESSION = None
