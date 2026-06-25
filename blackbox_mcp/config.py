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


@dataclass(frozen=True)
class Config:
    headless: bool
    browser: str          # chromium (default) | firefox | webkit
    # Explicit browser binary path (executable_path). None => Playwright default.
    chromium_executable: str | None
    # Use an installed browser channel (e.g. "chrome", "msedge") instead of the
    # bundled Chromium — real UA reduces anti-bot false positives.
    browser_channel: str | None
    # Apply light anti-automation-fingerprint hardening for legitimate testing.
    stealth: bool
    report_dir: Path
    scenario_dir: Path
    # Per-step selector resolution budget (ms); the whole fallback chain must
    # finish within the MCP 30s tool timeout.
    selector_timeout_ms: int
    # Default navigation wait condition.
    default_wait_until: str

    @staticmethod
    def from_env() -> "Config":
        return Config(
            headless=_as_bool(os.getenv("HEADLESS"), True),
            browser=os.getenv("BROWSER", "chromium").strip().lower(),
            chromium_executable=_detect_chromium_executable(),
            browser_channel=(os.getenv("BROWSER_CHANNEL") or None),
            stealth=_as_bool(os.getenv("STEALTH"), False),
            report_dir=Path(os.getenv("REPORT_DIR", "./reports")).expanduser(),
            scenario_dir=Path(os.getenv("SCENARIO_DIR", "./scenarios")).expanduser(),
            selector_timeout_ms=int(os.getenv("SELECTOR_TIMEOUT_MS", "2000")),
            default_wait_until=os.getenv("DEFAULT_WAIT_UNTIL", "networkidle"),
        )


# Singleton config, loaded once at import.
CONFIG = Config.from_env()
