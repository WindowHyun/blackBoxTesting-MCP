"""First-run bootstrap — D1: automatic Chromium installation.

The PRD requires `pip install` to be the only manual step. On first launch we
verify the Playwright browser binary exists and, if not, install it via the
Playwright CLI. If it is already present we return immediately.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys

from .config import CONFIG

log = logging.getLogger(__name__)


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
            import os

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
    """
    name = CONFIG.browser

    if CONFIG.chromium_executable:
        if os.path.exists(CONFIG.chromium_executable):
            log.info("Using pre-provisioned browser: %s", CONFIG.chromium_executable)
            return
        log.warning(
            "CHROMIUM_EXECUTABLE set but missing: %s", CONFIG.chromium_executable
        )

    if _browser_installed(name):
        log.debug("Playwright %s already installed.", name)
        return

    log.info("Playwright %s not found — installing (first run only)...", name)
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", name],
            check=True,
        )
        log.info("Playwright %s installed.", name)
    except subprocess.CalledProcessError as exc:
        log.warning(
            "Could not install %s automatically (%s). If a browser is provided "
            "externally, set CHROMIUM_EXECUTABLE to its path.",
            name, exc,
        )
