"""Smoke tests for the tool registry and pure helpers (no browser needed)."""
from __future__ import annotations


def test_all_tools_registered():
    from blackbox_mcp.tools._registry import _PENDING

    names = {p.name or p.fn.__name__ for p in _PENDING}
    expected = {
        "navigate", "snapshot", "screenshot", "interact", "assert_",
        "get_console_logs", "get_network_errors", "wait", "switch_frame",
        "reset_session", "run_scenario", "generate_scenario",
        "save_scenario", "load_scenario", "list_scenarios",
    }
    assert expected <= names


def test_prompts_registered():
    from blackbox_mcp.tools._registry import _PENDING_PROMPTS

    names = {p.name or p.fn.__name__ for p in _PENDING_PROMPTS}
    assert {"ui-test", "ui-scenario", "ui-generate"} <= names


def test_locator_prefix_parsing():
    from blackbox_mcp.browser import locator

    role, name = locator._parse_role("button name=로그인")
    assert role == "button"
    assert name == "로그인"


def test_secret_masking():
    from blackbox_mcp.testing.secrets import mask_step

    step = {"action": "interact", "selector": "testid=password", "value": "hunter2"}
    masked = mask_step(step)
    assert masked["value"] == "***"  # fully masked — no partial reveal
