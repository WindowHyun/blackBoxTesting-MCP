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


@dataclass(frozen=True)
class Config:
    headless: bool
    browser: str          # chromium (default) | firefox | webkit
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
            report_dir=Path(os.getenv("REPORT_DIR", "./reports")).expanduser(),
            scenario_dir=Path(os.getenv("SCENARIO_DIR", "./scenarios")).expanduser(),
            selector_timeout_ms=int(os.getenv("SELECTOR_TIMEOUT_MS", "2000")),
            default_wait_until=os.getenv("DEFAULT_WAIT_UNTIL", "networkidle"),
        )


# Singleton config, loaded once at import.
CONFIG = Config.from_env()
