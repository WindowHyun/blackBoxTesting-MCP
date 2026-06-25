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
        if CONFIG.browser_channel:
            launch_kwargs["channel"] = CONFIG.browser_channel  # real Chrome/Edge
        elif CONFIG.chromium_executable:
            launch_kwargs["executable_path"] = CONFIG.chromium_executable
        if CONFIG.stealth:
            launch_kwargs["args"] = ["--disable-blink-features=AutomationControlled"]
        self._browser = await browser_type.launch(**launch_kwargs)
        await self._new_context()
        log.info(
            "BrowserSession started (%s, headless=%s, channel=%s, stealth=%s)",
            CONFIG.browser, CONFIG.headless, CONFIG.browser_channel or "-", CONFIG.stealth,
        )

    async def _new_context(self) -> None:
        ctx_kwargs: dict = {}
        if CONFIG.stealth:
            ctx_kwargs.update(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                viewport={"width": 1280, "height": 800},
            )
        self._context = await self._browser.new_context(**ctx_kwargs)
        if CONFIG.stealth:
            # hide the most obvious automation signal
            await self._context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
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
    def is_alive(self) -> bool:
        """True if the browser is still connected (NFR crash detection)."""
        try:
            return self._browser is not None and self._browser.is_connected()
        except Exception:
            return False

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
    elif not _SESSION.is_alive():
        # Browser crashed/closed since last call — recover transparently (NFR).
        await _SESSION.restart()
    return _SESSION


async def close_session() -> None:
    """Close and drop the singleton (used by the server lifespan on shutdown)."""
    global _SESSION
    if _SESSION is not None:
        await _SESSION.close()
        _SESSION = None
