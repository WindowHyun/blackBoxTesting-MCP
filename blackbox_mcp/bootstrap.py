"""First-run bootstrap — D1: automatic Chromium installation.

The PRD requires `pip install` to be the only manual step. On first launch we
verify the Playwright browser binary exists and, if not, install it via the
Playwright CLI. If it is already present we return immediately.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading

from .config import CONFIG, effective_browser

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

    if _browser_installed(name):
        log.debug("Playwright %s already installed.", name)
        return

    log.info("Playwright %s not found — installing (first run only)...", name)
    try:
        # stdout is the MCP JSON-RPC pipe once Claude Desktop spawns us —
        # install progress must never reach it. stderr IS captured: sending it
        # to DEVNULL too meant a failed install (blocked CDN, full disk, proxy
        # rejection) left no reason anywhere, and the user only saw every later
        # tool call die on a missing browser.
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", name],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        log.info("Playwright %s installed.", name)
    except Exception as exc:
        # Never let a failed auto-install crash server startup — the first
        # browser launch will surface a clear error if no binary is reachable.
        log.warning(
            "Could not install %s automatically (%s).%s If a browser is provided "
            "externally, set CHROMIUM_EXECUTABLE to its path.",
            name, exc, _install_error_detail(exc),
        )


def _install_error_detail(exc: Exception) -> str:
    """The tail of the installer's stderr, when the failure carried one."""
    err = getattr(exc, "stderr", None)
    if not err:
        return ""
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    tail = err.strip()[-400:]
    return f" installer said: {tail}." if tail else ""


# ── background bootstrap (keeps the MCP handshake responsive) ─────
_BOOTSTRAP_DONE = threading.Event()
_BOOTSTRAP_STARTED = False
_BOOTSTRAP_LOCK = threading.Lock()


def start_background_bootstrap() -> None:
    """Run :func:`ensure_chromium` on a worker thread instead of inline at boot.

    An MCP client sends ``initialize`` immediately after spawning the server and
    gives up after a short timeout (~60s in Claude Desktop). A first run that
    downloads Chromium (~150MB) exceeds that on an ordinary connection, so doing
    the install before ``mcp.run()`` made the *recommended* install path (uvx,
    no clone) report "server failed to start": measured 45.6s to answer
    initialize against a 45s download, versus 0.6s once the browser is present.
    Starting the download here overlaps it with the handshake, and the first
    browser launch waits for it via :func:`await_bootstrap`.

    ``ensure_chromium`` uses Playwright's SYNC API, which refuses to run in a
    thread that owns a running asyncio loop. A worker thread owns none, so this
    stays within CLAUDE.md rule 2.
    """
    global _BOOTSTRAP_STARTED
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_STARTED:
            return
        _BOOTSTRAP_STARTED = True

    def _run() -> None:
        try:
            ensure_chromium()
        except Exception as exc:  # ensure_chromium swallows its own; belt & braces
            log.warning("background browser bootstrap failed: %s", exc)
        finally:
            _BOOTSTRAP_DONE.set()

    # daemon: a half-finished download must not hold up server shutdown.
    threading.Thread(target=_run, name="bbx-bootstrap", daemon=True).start()


async def await_bootstrap() -> None:
    """Wait for a background bootstrap to finish without blocking the event loop.

    No-op when none was started — the CLI calls ``ensure_chromium()``
    synchronously before its event loop exists, where blocking is correct.
    """
    if not _BOOTSTRAP_STARTED or _BOOTSTRAP_DONE.is_set():
        return
    log.info("waiting for the first-run browser install to finish...")
    await asyncio.to_thread(_BOOTSTRAP_DONE.wait)
