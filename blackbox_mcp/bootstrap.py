"""First-run bootstrap — D1: automatic Chromium installation.

The PRD requires `pip install` to be the only manual step. On first launch we
verify the Playwright browser binary exists and, if not, install it via the
Playwright CLI. If it is already present we return immediately.
"""
from __future__ import annotations

import logging
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
    """Ensure the configured browser binary is installed (D1)."""
    name = CONFIG.browser
    if _browser_installed(name):
        log.debug("Playwright %s already installed.", name)
        return

    log.info("Playwright %s not found — installing (first run only)...", name)
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", name],
        check=True,
    )
    log.info("Playwright %s installed.", name)
