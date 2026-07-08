"""Runtime configuration sourced from environment variables.

All behavior knobs live here so the rest of the code reads typed values
instead of touching os.environ directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    """Tolerant int parsing: a typo like "2000ms" in the client's env block must
    not crash the server at import (the user only sees a dead MCP server)."""
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        import sys
        print(f"[blackbox-mcp] invalid int {value!r} — using {default}",
              file=sys.stderr)
        return default


# Well-known location of a pre-provisioned browser in some managed/CI
# environments (e.g. Claude Code web). Used when the matching Playwright build
# cannot be downloaded (network policy) — we launch this binary via
# executable_path instead.
_PREINSTALLED_CHROMIUM = "/opt/pw-browsers/chromium"


def _detect_chromium_executable() -> str | None:
    explicit = os.getenv("CHROMIUM_EXECUTABLE")
    if explicit:
        return explicit
    if os.path.exists(_PREINSTALLED_CHROMIUM):
        return _PREINSTALLED_CHROMIUM
    return None  # let Playwright resolve its bundled browser normally


def _resolve_dir(value: str | None, default_name: str) -> Path:
    """Absolute output dir. When unset, default under the user's home — NOT the
    cwd, which is unpredictable when the server is spawned by Claude Desktop and
    is often not writable (e.g. system32)."""
    if value:
        return Path(value).expanduser().resolve()
    return (Path.home() / "ui-blackbox" / default_name).resolve()


@dataclass(frozen=True)
class Config:
    headless: bool
    browser: str          # chromium (default) | firefox | webkit
    # Explicit browser binary path (executable_path). None => Playwright default.
    chromium_executable: str | None
    # Use an installed browser channel (e.g. "chrome", "msedge") instead of the
    # bundled Chromium — real UA reduces anti-bot false positives.
    browser_channel: str | None
    # Attach to an already-running browser via CDP (chrome --remote-debugging-port).
    # When set, we connect to the user's real, logged-in browser instead of
    # launching one. e.g. http://localhost:9222
    cdp_url: str | None
    # Apply light anti-automation-fingerprint hardening for legitimate testing.
    stealth: bool
    report_dir: Path
    scenario_dir: Path
    # Per-step selector resolution budget (ms); the whole fallback chain must
    # finish within the MCP 30s tool timeout. Raise for slow real sites.
    selector_timeout_ms: int
    # Default navigation wait condition.
    default_wait_until: str
    # Navigation timeout (ms). Real sites that never reach networkidle fall back
    # to domcontentloaded rather than hanging.
    nav_timeout_ms: int
    # Accept invalid TLS certs (staging with self-signed/expired certs).
    ignore_https_errors: bool
    # Keep at most N report runs (per format set) in REPORT_DIR; 0 = unlimited.
    # Prevents unbounded growth of ~/ui-blackbox/reports on long-lived setups.
    report_retention: int

    @staticmethod
    def from_env() -> "Config":
        return Config(
            headless=_as_bool(os.getenv("HEADLESS"), True),
            browser=os.getenv("BROWSER", "chromium").strip().lower(),
            chromium_executable=_detect_chromium_executable(),
            browser_channel=(os.getenv("BROWSER_CHANNEL") or None),
            cdp_url=(os.getenv("BROWSER_CDP") or None),
            stealth=_as_bool(os.getenv("STEALTH"), False),
            report_dir=_resolve_dir(os.getenv("REPORT_DIR"), "reports"),
            scenario_dir=_resolve_dir(os.getenv("SCENARIO_DIR"), "scenarios"),
            selector_timeout_ms=_as_int(os.getenv("SELECTOR_TIMEOUT_MS"), 2000),
            default_wait_until=os.getenv("DEFAULT_WAIT_UNTIL", "networkidle"),
            nav_timeout_ms=_as_int(os.getenv("NAV_TIMEOUT_MS"), 30000),
            ignore_https_errors=_as_bool(os.getenv("IGNORE_HTTPS_ERRORS"), False),
            report_retention=_as_int(os.getenv("REPORT_RETENTION"), 100),
        )


# Singleton config, loaded once at import.
CONFIG = Config.from_env()

_BROWSER_TYPES = ("chromium", "firefox", "webkit")


def effective_browser(raw: str | None = None) -> str:
    """The browser name coerced to a real Playwright browser type.

    An unknown value (BROWSER=chrome is a plausible misconfig for "use real
    Chrome") falls back to chromium. Single source for session launch,
    bootstrap install target, doctor, and report metadata — keying different
    layers off the raw value made bootstrap install one thing and start()
    launch another. Callers pass their module-local CONFIG.browser so tests
    that monkeypatch a module's CONFIG see consistent coercion.
    """
    raw = CONFIG.browser if raw is None else raw
    return raw if raw in _BROWSER_TYPES else "chromium"
