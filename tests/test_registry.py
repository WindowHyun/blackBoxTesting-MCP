"""Smoke tests for the tool registry and pure helpers (no browser needed)."""
from __future__ import annotations

import subprocess
import sys


def test_cli_path_does_not_pull_mcp_sdk():
    """The CI path (cli → testing.runner → action tools) advertises "no MCP
    client needed" — importing it must not drag in the MCP SDK. Guarded by the
    lazy imports in tools/__init__ (screenshot/generate are the mcp importers)."""
    code = ("import blackbox_mcp.testing.runner, blackbox_mcp.cli, sys;"
            "print(any(m == 'mcp' or m.startswith('mcp.') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_all_tools_registered():
    import blackbox_mcp.tools as tools
    tools._import_all()  # imports are lazy now (CLI must not pull the MCP SDK)
    from blackbox_mcp.tools._registry import _PENDING

    names = {p.name or p.fn.__name__ for p in _PENDING}
    expected = {
        "navigate", "snapshot", "screenshot", "interact", "assert_",
        "get_console_logs", "get_network_errors", "wait", "switch_frame",
        "reset_session", "run_scenario", "generate_scenario",
        "save_scenario", "load_scenario", "list_scenarios",
    }
    assert expected <= names


def test_register_all_is_idempotent():
    """Calling register_all twice must not double-register (FastMCP rejects
    duplicate names)."""
    import blackbox_mcp.tools as tools
    import blackbox_mcp.tools._registry as reg
    from mcp.server.fastmcp import FastMCP

    tools._import_all()          # populate _PENDING
    reg._REGISTERED = False       # simulate a fresh process
    m = FastMCP("x")
    n1 = reg.register_all(m)
    n2 = reg.register_all(m)      # no-op — would raise on duplicate binding otherwise
    assert n1 == n2 > 0


def test_prompts_registered():
    import blackbox_mcp.tools as tools
    tools._import_all()
    from blackbox_mcp.tools._registry import _PENDING_PROMPTS

    names = {p.name or p.fn.__name__ for p in _PENDING_PROMPTS}
    assert {"ui-test", "ui-scenario", "ui-generate", "ui-login", "ui-sync"} <= names


def test_prompt_primers_reference_real_tools():
    """The tool list & decision matrix inside the primers must only name tools
    that actually exist — a renamed tool must not leave stale prompt text."""
    import re

    import blackbox_mcp.tools as tools
    tools._import_all()
    from blackbox_mcp.tools import _prompts
    from blackbox_mcp.tools._registry import _PENDING

    real = {p.name or p.fn.__name__ for p in _PENDING}
    text = _prompts._ONLY + _prompts._MATRIX
    named = set(re.findall(r"`([a-z_]+)`", text)) | {
        t.strip() for t in re.findall(r"[:·] ([a-z_ ·]+)", _prompts._ONLY)
        for t in t.split("·")}
    step_fields = {"expect_status"}  # scenario step field, not a tool
    unknown = {n for n in named if n and " " not in n} - real - step_fields
    assert not unknown, f"prompts reference nonexistent tools: {unknown}"


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
