"""Config / env parsing — HEADLESS toggle (BR-03) and friends."""
from __future__ import annotations

from blackbox_mcp.config import Config, _as_bool, _as_int


def test_as_bool():
    assert _as_bool("false", True) is False
    assert _as_bool("0", True) is False
    assert _as_bool("true", False) is True
    assert _as_bool(None, True) is True


def test_as_int_tolerates_malformed_values():
    assert _as_int("2500", 2000) == 2500
    assert _as_int(" 2500 ", 2000) == 2500
    assert _as_int(None, 2000) == 2000
    # a typo in the client env block must not crash server boot
    assert _as_int("2000ms", 2000) == 2000


def test_malformed_timeout_env_does_not_crash_boot(monkeypatch):
    monkeypatch.setenv("SELECTOR_TIMEOUT_MS", "fast")
    monkeypatch.setenv("NAV_TIMEOUT_MS", "30s")
    cfg = Config.from_env()
    assert cfg.selector_timeout_ms == 2000
    assert cfg.nav_timeout_ms == 30000


def test_headless_toggle(monkeypatch):
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("BROWSER", "chromium")
    cfg = Config.from_env()
    assert cfg.headless is False
    assert cfg.browser == "chromium"


def test_headless_default_true(monkeypatch):
    monkeypatch.delenv("HEADLESS", raising=False)
    cfg = Config.from_env()
    assert cfg.headless is True
