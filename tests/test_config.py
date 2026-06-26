"""Config / env parsing — HEADLESS toggle (BR-03) and friends."""
from __future__ import annotations

from blackbox_mcp.config import Config, _as_bool


def test_as_bool():
    assert _as_bool("false", True) is False
    assert _as_bool("0", True) is False
    assert _as_bool("true", False) is True
    assert _as_bool(None, True) is True


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
