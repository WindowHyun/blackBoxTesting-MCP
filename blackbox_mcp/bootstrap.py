"""First-run bootstrap — D1: automatic Chromium installation.

The PRD requires `pip install` to be the only manual step. On first launch we
verify the Playwright browser binary exists and, if not, install it via the
Playwright CLI. If it is already present we return immediately.

In the MCP server this must NOT run before the stdio transport starts —
a ~150MB download would stall the `initialize` handshake past the client's
timeout and the server would look dead. So server startup no longer calls this
synchronously; instead ``BrowserSession.start`` invokes it lazily (via
``asyncio.to_thread`` so the sync Playwright CLI runs off the event loop) on the
first browser use, and the install is time-bounded (``INSTALL_TIMEOUT_S``) so a
throttled/hung download eventually gives up instead of blocking forever.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys

from .config import CONFIG, effective_browser

log = logging.getLogger(__name__)

# Upper bound on the first-run `playwright install`. A slow-trickle/throttled
# connection never trips Playwright's own 30s idle-socket timeout, so bound the
# whole install here — on expiry we log and continue (the launch will surface a
# clear error) rather than hang. ~10 min is generous for a ~150MB download.
INSTALL_TIMEOUT_S = 600


def _browser_installed(name: str) -> bool:
    """Best-effort check that the requested Playwright browser is available."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # pragma: no cover - playwright missing entirely
        return False

    try:
        with sync_playwright() as p:
            browser_type = getattr(p, name)
            # executable_path raises / is missing when the binary is absent.
            path = browser_type.executable_path
            return bool(path) and os.path.exists(path)
    except Exception:
        return False


def ensure_chromium() -> None:
    """Ensure a usable browser binary is available (D1).

    Resolution order:
      1. An explicit/pre-provisioned executable (CONFIG.chromium_executable) —
         used directly via executable_path, no download needed.
      2. Playwright's bundled binary if already installed.
      3. Otherwise attempt `playwright install`. If that fails (e.g. the browser
         CDN is blocked by network policy), log and continue rather than crash —
         the launch will surface a clear error if no binary is reachable.

    The install target is the COERCED browser name (config.effective_browser):
    BROWSER=chrome coerces to chromium at launch, so installing the raw value
    here would install the wrong thing (`playwright install chrome` = system
    Chrome channel) and leave the session's actual fallback target missing.
    """
    name = effective_browser(CONFIG.browser)
    if name != CONFIG.browser:
        log.warning("unknown BROWSER=%r — treating as chromium.", CONFIG.browser)

    if CONFIG.chromium_executable:
        if os.path.exists(CONFIG.chromium_executable):
            log.info("Using pre-provisioned browser: %s", CONFIG.chromium_executable)
            return
        log.warning(
            "CHROMIUM_EXECUTABLE set but missing: %s", CONFIG.chromium_executable
        )

    if CONFIG.cdp_url:
        # CDP mode attaches to the user's already-running browser and never
        # launches a bundled binary — skip the download. (A CDP-attach failure
        # falls back to a local launch, which will trigger the install then.)
        log.info("BROWSER_CDP set — skipping bundled browser install.")
        return

    if _browser_installed(name):
        log.debug("Playwright %s already installed.", name)
        return

    log.info("Playwright %s not found — installing (first run only)...", name)
    try:
        # stdout is the MCP JSON-RPC pipe once Claude Desktop spawns us —
        # install progress must never reach it. Time-bounded so a throttled
        # download can't block forever (the except below then continues).
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", name],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=INSTALL_TIMEOUT_S,
        )
        log.info("Playwright %s installed.", name)
    except Exception as exc:
        # Never let a failed/slow auto-install crash startup — the first browser
        # launch will surface a clear error if no binary is reachable. A
        # TimeoutExpired lands here too (bounded, not an unbounded hang).
        log.warning(
            "Could not install %s automatically (%s). If a browser is provided "
            "externally, set CHROMIUM_EXECUTABLE to its path.",
            name, exc,
        )
