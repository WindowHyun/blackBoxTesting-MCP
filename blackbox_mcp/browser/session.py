"""BrowserSession singleton (BR-01, BR-03, BR-04) + crash recovery (NFR).

A single async Playwright browser context lives for the life of the process so
cookies / session / localStorage persist across tool calls. Using the *async*
Playwright API keeps us compatible with the async MCP event loop (the sync API
cannot run inside asyncio).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from ..config import CONFIG, effective_browser
from .listeners import EventBuffers, attach

log = logging.getLogger(__name__)


def _launch_attempts() -> list[dict]:
    """Launch-kwarg variants tried in order (mirrors _switch_to_persistent_impl):
    channel → explicit executable → bundled default.

    The explicit executable is only usable when the EFFECTIVE browser is
    chromium (it IS a chromium binary — handing it to firefox/webkit would
    launch the wrong browser; keying off the coerced name, not the raw env,
    keeps BROWSER=chrome from skipping a working binary) and only when the
    path actually exists: a stale CHROMIUM_EXECUTABLE must fall through to
    the bundled browser bootstrap may have installed, not brick every launch.
    """
    attempts: list[dict] = []
    if CONFIG.browser_channel:
        attempts.append({"channel": CONFIG.browser_channel})
    if (CONFIG.chromium_executable and effective_browser(CONFIG.browser) == "chromium"
            and os.path.exists(CONFIG.chromium_executable)):
        attempts.append({"executable_path": CONFIG.chromium_executable})
    attempts.append({})  # bundled default
    return attempts


class BrowserSession:
    """Owns the Playwright lifecycle and the current page/frame context."""

    def __init__(self) -> None:
        # Playwright objects, populated by start() (optional-init pattern —
        # typed Any so mypy doesn't pin them to None; liveness is guarded at
        # runtime by is_alive()/the page property, not the type system).
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._cdp = False          # attached to a user-owned browser via CDP
        self._persistent = False   # launched a real browser with a saved profile
        self._persistent_opts: dict | None = None
        # Current iframe context for CT-09; None == main page.
        self._frame_selector: str | None = None
        self.buffers = EventBuffers()
        # Serializes lifecycle mutations (reset / switch_to_persistent /
        # restart / close) against EACH OTHER, so two lifecycle ops can't tear
        # down each other's half-started state. Action tools don't take this
        # lock (single-tenant server): an action racing a reset may still see
        # its context close mid-use — that's the documented tenancy model.
        self._op_lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────
    async def start(self) -> None:
        from playwright.async_api import async_playwright

        # Lazy first-run browser install (moved off the server's stdio
        # handshake). Runs in a worker thread — the sync Playwright CLI can't
        # run on the event loop, but a thread with no loop is fine — and is
        # idempotent/fast once installed. Best-effort: a failure here just means
        # the launch below surfaces the clear "no binary" error.
        from ..bootstrap import ensure_chromium
        try:
            await asyncio.to_thread(ensure_chromium)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("lazy browser install skipped (%s)", exc)

        self._pw = await async_playwright().start()

        if CONFIG.cdp_url:
            # Attach to the user's already-running, logged-in browser. Reuse its
            # existing context/page so cookies/session/CAPTCHA state persist. If
            # nothing is listening (stale BROWSER_CDP), fall back to a normal
            # launch rather than bricking every tool call.
            try:
                self._browser = await self._pw.chromium.connect_over_cdp(CONFIG.cdp_url)
                self._cdp = True
                self._context = (self._browser.contexts[0] if self._browser.contexts
                                 else await self._browser.new_context())
                self._page = (self._context.pages[0] if self._context.pages
                              else await self._context.new_page())
                self._frame_selector = None
                self.buffers.clear()
                self._watch_page(self._page)
                self._track_pages()
                log.info("BrowserSession attached over CDP: %s", CONFIG.cdp_url)
                return
            except Exception as exc:
                self._cdp = False
                # A partial attach (connected, but new_context/new_page failed)
                # must not leak the open CDP connection for the process's life.
                if self._browser is not None:
                    try:
                        await self._browser.close()
                    except Exception:
                        pass
                self._browser = self._context = self._page = None
                log.warning("CDP connect to %s failed (%s) — launching a normal "
                            "browser instead.", CONFIG.cdp_url, exc)

        browser_name = effective_browser(CONFIG.browser)
        if browser_name != CONFIG.browser:
            log.warning("unknown BROWSER=%r — using chromium.", CONFIG.browser)
        browser_type = getattr(self._pw, browser_name)
        launch_kwargs: dict = {"headless": CONFIG.headless}
        if CONFIG.stealth:
            launch_kwargs["args"] = ["--disable-blink-features=AutomationControlled"]

        # Fallback chain: a channel that isn't installed or a stale executable
        # must not brick every launch when the bundled browser would work.
        used, last_err = None, None
        for extra in _launch_attempts():
            try:
                self._browser = await browser_type.launch(**launch_kwargs, **extra)
                used = extra.get("channel") or extra.get("executable_path") or "bundled"
                break
            except Exception as exc:
                last_err = exc
                log.warning("launch attempt %s failed: %s", extra or "bundled", exc)
        if self._browser is None:
            raise RuntimeError(f"failed to launch {CONFIG.browser}: {last_err}")
        await self._new_context()
        log.info(
            "BrowserSession started (%s via %s, headless=%s, stealth=%s)",
            CONFIG.browser, used, CONFIG.headless, CONFIG.stealth,
        )

    async def _new_context(self, storage_state: str | None = None) -> None:
        ctx_kwargs: dict = {}
        if storage_state is not None:
            # Restore cookies/localStorage exported by save_state — auth reuse
            # without a persistent profile (works headless/CI).
            ctx_kwargs["storage_state"] = storage_state
        if CONFIG.ignore_https_errors:
            ctx_kwargs["ignore_https_errors"] = True
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
        self._watch_page(self._page)
        self._track_pages()

    async def reset(self) -> None:
        """BR-04: wipe context (cookies/session/storage) + buffers, fresh page."""
        async with self._op_lock:
            await self._reset_impl()

    async def load_storage_state(self, path: str) -> None:
        """Replace the context with a fresh one seeded from a storage-state file
        (cookies + localStorage exported by ``save_state``).

        Only for browsers we own contexts in (bundled/channel): a CDP-attached
        or persistent-profile browser keeps its own auth — recreating its
        context would detach/lose the user's real session.
        """
        async with self._op_lock:
            if self._cdp or self._persistent:
                raise RuntimeError(
                    "load_state only applies to the bundled/channel browser — "
                    "real-browser modes (CDP/persistent profile) keep their own "
                    "login state.")
            if self._context is not None:
                await self._context.close()
            await self._new_context(storage_state=path)
            log.info("BrowserSession context reloaded from storage state.")

    async def _reset_impl(self) -> None:
        if self._cdp or self._persistent:
            # Don't wipe a real/logged-in browser — just clear our buffers.
            self.buffers.clear()
            log.info("BrowserSession reset (real browser: buffers only).")
            return
        if self._context is not None:
            await self._context.close()
        await self._new_context()
        log.info("BrowserSession reset.")

    async def switch_to_persistent(self, headless: bool = False,
                                   channel: str = "chrome") -> dict:
        """Switch the session to a real browser with a saved profile.

        Idempotent: if a real browser is already open and alive, reuse it (keeps
        the logged-in window — no new window, no re-login). Otherwise launch
        Chrome (real channel preferred, falling back to the bundled binary) with a
        persistent user-data-dir so login/cookies survive across runs.
        """
        async with self._op_lock:
            return await self._switch_to_persistent_impl(headless, channel)

    async def _switch_to_persistent_impl(self, headless: bool = False,
                                         channel: str = "chrome") -> dict:
        from pathlib import Path

        profile = str(Path.home() / "ui-blackbox" / "chrome-profile")

        # Already on a live real browser → reuse it, don't relaunch.
        if self._persistent and self.is_alive():
            log.info("BrowserSession reuse existing real browser (no relaunch).")
            return {"used": "existing", "profile": profile,
                    "headless": headless, "reused": True}

        from playwright.async_api import async_playwright
        if self._pw is None:
            self._pw = await async_playwright().start()
        await self._teardown_current()

        self._persistent_opts = {"headless": headless, "channel": channel}
        base = {"user_data_dir": profile, "headless": headless}
        if CONFIG.ignore_https_errors:
            base["ignore_https_errors"] = True

        attempts = []
        if channel:
            attempts.append({"channel": channel})
        if CONFIG.chromium_executable:
            attempts.append({"executable_path": CONFIG.chromium_executable})
        attempts.append({})  # bundled default

        used, last_err = None, None
        for extra in attempts:
            try:
                self._context = await self._pw.chromium.launch_persistent_context(**base, **extra)
                used = extra.get("channel") or extra.get("executable_path") or "bundled"
                break
            except Exception as exc:
                last_err = exc
                continue
        if self._context is None:
            raise RuntimeError(f"failed to launch real browser: {last_err}")

        self._browser = self._context.browser
        self._page = (self._context.pages[0] if self._context.pages
                      else await self._context.new_page())
        self._persistent, self._cdp, self._frame_selector = True, False, None
        self.buffers.clear()
        self._watch_page(self._page)
        self._track_pages()
        log.info("BrowserSession → real persistent browser (%s, profile=%s)", used, profile)
        return {"used": used, "profile": profile, "headless": headless, "reused": False}

    async def _teardown_current(self) -> None:
        """Close whatever browser is currently open, keeping Playwright running.

        Each close is attempted independently: a context whose close raises (a
        crashed renderer is exactly why we're switching browsers) must not skip
        browser.close() — unlike close(), the driver stays running here, so a
        skipped browser.close() orphans a live Chromium for the process's life.
        """
        if self._cdp:
            if self._browser is not None:
                try:
                    await self._browser.close()  # detaches; user's Chrome stays
                except Exception:
                    pass
        else:
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception as exc:
                    log.warning("context close failed (%s) — closing browser anyway.", exc)
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    pass
        self._browser = self._context = self._page = None
        self._cdp = self._persistent = False

    async def restart(self) -> None:
        """Recover from a browser crash (NFR Reliability, < 5s).

        Preserves the real-browser mode: if we were on a persistent profile,
        re-open it (cookies on disk → still logged in) instead of dropping back to
        a fresh bundled browser.
        """
        async with self._op_lock:
            log.warning("BrowserSession restarting after failure.")
            persistent = self._persistent
            opts = self._persistent_opts or {"headless": False, "channel": "chrome"}
            await self._close_impl()
            if persistent:
                await self._switch_to_persistent_impl(**opts)
            else:
                await self.start()

    async def close(self) -> None:
        # Same public-lock/_impl split as the other lifecycle ops: shutdown must
        # not stop the driver while a reset/switch holds the lock mid-operation.
        async with self._op_lock:
            await self._close_impl()

    async def _close_impl(self) -> None:
        try:
            try:
                if self._cdp:
                    # Detach only — the browser belongs to the user. Don't close it.
                    if self._browser is not None:
                        await self._browser.close()  # closes CDP connection, not Chrome
                elif self._persistent:
                    if self._context is not None:
                        await self._context.close()  # profile on disk persists
                else:
                    if self._context is not None:
                        await self._context.close()
                    if self._browser is not None:
                        await self._browser.close()
            except Exception as exc:
                # A crashed/disconnected browser can make close() raise — still
                # stop the Playwright driver below or its process leaks.
                log.warning("Browser close failed (%s) — stopping driver anyway.", exc)
            if self._pw is not None:
                await self._pw.stop()
        finally:
            self._pw = self._browser = self._context = self._page = None
            self._cdp = self._persistent = False

    # ── accessors ────────────────────────────────────────────────
    def is_alive(self) -> bool:
        """True if the browser is still usable (NFR crash detection).

        Checks the page first: ``context.browser`` is None when the context is
        created outside a normal browser (Android/Electron, per Playwright docs);
        checking ``page.is_closed()`` is robust to that and to version quirks, so
        we don't falsely think the session died → relaunch loop / new window.
        """
        try:
            if self._page is None or self._page.is_closed():
                return False
            # Page open. If we also hold a Browser, require it connected so a
            # real crash/disconnect is detected; a persistent context may expose
            # no Browser (None) — then the open page is our liveness signal.
            return self._browser is None or self._browser.is_connected()
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

    def _watch_page(self, page) -> None:
        """Attach event listeners + a close-fallback handler to a page we drive.

        Idempotent per page: every page that can become ``_page`` (initial page,
        persistent context's first page, adopted popups, close-fallback targets)
        must carry the close handler, or closing it strands the session on a
        dead page and the next tool call needlessly restarts the whole browser.
        Guarding repeat calls keeps attach() from double-buffering events.
        """
        if getattr(page, "_bbx_watched", False):
            return
        page._bbx_watched = True
        attach(page, self.buffers)
        page.on("close", lambda: self._on_page_closed(page))

    def _adopt_page(self, page) -> None:
        """Follow a popup/new tab so a flow that opens one keeps working.

        Real sites open new tabs (target=_blank, window.open, OAuth popups); the
        active page switches to the newest one and gets event listeners attached.
        """
        self._page = page
        self._frame_selector = None
        self._watch_page(page)
        log.info("Adopted new page/popup.")

    def _on_page_closed(self, page) -> None:
        """When the active page closes (popup done, tab closed), fall back to a
        still-open page so the flow continues instead of dying on a dead page."""
        if self._page is page and self._context is not None:
            others = [p for p in self._context.pages if not p.is_closed()]
            if others:
                # oldest remaining page = the original tab the flow came from
                self._page = others[0]
                self._frame_selector = None
                self._watch_page(self._page)  # CDP-mode tabs may be unwatched
                log.info("Active page closed → fell back to remaining page.")

    def _track_pages(self) -> None:
        """Follow popups in browsers we own. NOT in CDP mode — that's the user's
        real browser, where auto-adopting their background tabs would hijack the
        active page."""
        if self._context is not None and not self._cdp:
            self._context.on("page", self._adopt_page)


# ── module-level singleton (BR-01) ───────────────────────────────
_SESSION: BrowserSession | None = None
# Serializes singleton creation/recovery: without it two concurrent tool calls
# can both see a dead/absent session and launch two browsers (one leaks) or
# tear down each other's half-started state.
_SESSION_LOCK = asyncio.Lock()


async def get_session() -> BrowserSession:
    """Lazily create and start the single BrowserSession."""
    global _SESSION
    async with _SESSION_LOCK:
        if _SESSION is None:
            session = BrowserSession()
            try:
                await session.start()
            except Exception:
                await session.close()  # stop a half-started driver
                raise
            # Publish only after a successful start — a failed launch must not
            # leave a half-initialized singleton behind.
            _SESSION = session
        elif not _SESSION.is_alive():
            # Browser crashed/closed since last call — recover transparently (NFR).
            await _SESSION.restart()
        return _SESSION


async def close_session() -> None:
    """Close and drop the singleton (used by the server lifespan on shutdown)."""
    global _SESSION
    # Same lock get_session() takes (then close() takes _op_lock — consistent
    # _SESSION_LOCK → _op_lock ordering), so shutdown can't race a concurrent
    # create/restart and leave a half-torn-down session published.
    async with _SESSION_LOCK:
        if _SESSION is not None:
            await _SESSION.close()
            _SESSION = None
