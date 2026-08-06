"""Static validation of the shipped example scenarios.

These target a live site, so they cannot be executed in CI. What CAN be checked
offline is that every step matches the contract runner._dispatch actually
implements — a typo'd action verb or a missing required field would otherwise
only surface as a failed step on someone else's machine, in a file we shipped
as "ready to run".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from blackbox_mcp.tools.assertion import _KINDS as ASSERT_KINDS
from blackbox_mcp.tools.interact import _ACTIONS as INTERACT_ACTIONS

EXAMPLES = Path(__file__).parent.parent / "examples" / "saucedemo"

# Mirrors the action verbs runner._dispatch handles.
KNOWN_ACTIONS = {
    "navigate", "interact", "assert", "assert_", "snapshot", "wait",
    "switch_frame", "switch_tab", "expect_popup", "expect_download",
    "reset_session", "save_state", "load_state", "mock_route", "unmock_route",
    "screenshot", "expect_dialog",
}
REQUIRED = {
    "navigate": ["url"],
    "interact": ["selector", "type"],
    "assert": ["kind", "target"],
    "expect_popup": ["trigger"],
    "expect_download": ["trigger"],
    "mock_route": ["pattern"],
}


def _scenario_files():
    files = sorted(EXAMPLES.glob("*.json"))
    assert files, f"no example scenarios found in {EXAMPLES}"
    return files


@pytest.mark.parametrize("path", _scenario_files(), ids=lambda p: p.stem)
def test_example_scenario_is_well_formed(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("name"), f"{path.name}: missing name"
    assert data.get("description"), f"{path.name}: missing description"

    steps = data["steps"]
    assert steps, f"{path.name}: no steps"

    for i, step in enumerate(steps, start=1):
        where = f"{path.name} step {i}"
        action = step.get("action")
        assert action in KNOWN_ACTIONS, f"{where}: unknown action {action!r}"

        for field in REQUIRED.get(action, []):
            assert field in step, f"{where}: '{action}' requires {field!r}"

        if action == "interact":
            assert step["type"] in INTERACT_ACTIONS, \
                f"{where}: unknown interact type {step['type']!r}"
            if step["type"] in {"type", "select", "press", "upload"}:
                assert "value" in step, f"{where}: '{step['type']}' requires a value"

        if action in ("assert", "assert_"):
            assert step["kind"] in ASSERT_KINDS, \
                f"{where}: unknown assert kind {step['kind']!r}"
            if step["kind"] == "count":
                assert str(step.get("expected", "")).isdigit(), \
                    f"{where}: count needs an integer 'expected'"

        if action == "wait":
            assert step.get("ms") or step.get("selector"), \
                f"{where}: wait needs ms or selector"


@pytest.mark.parametrize("path", _scenario_files(), ids=lambda p: p.stem)
def test_example_scenario_externalizes_the_password(path):
    """The site's demo password is public, but the examples must still model
    the right habit: credentials come from env as ${VAR}, never inline."""
    raw = path.read_text(encoding="utf-8")
    assert "secret_sauce" not in raw, f"{path.name}: password hardcoded"
    if "#password" in raw:
        data = json.loads(raw)
        pw_steps = [s for s in data["steps"] if s.get("selector") == "#password"]
        # the negative-login scenario deliberately types a wrong literal
        assert any(s.get("value", "").startswith("${") for s in pw_steps), \
            f"{path.name}: no ${{VAR}}-injected password step"


def test_password_var_is_treated_as_sensitive():
    """SAUCE_PASSWORD must trip the masking heuristic, or the report would
    print it verbatim — the examples double as the masking demo."""
    from blackbox_mcp.testing import secrets
    assert secrets.is_sensitive_name("SAUCE_PASSWORD")


@pytest.mark.browser
async def test_wait_timeout_is_forwarded_by_the_runner(session):
    """Regression: the runner dropped a wait step's timeout_ms, so every wait
    was pinned to the 10s default — a slow-by-design page (or a sluggish
    intranet server) could not be given a longer budget, and a deliberately
    short wait could not fail fast. Found while writing the
    performance_glitch_user scenario."""
    import time

    from blackbox_mcp.testing import runner

    await session.page.set_content("<div>nothing here</div>")
    started = time.monotonic()
    result = await runner.run(
        [{"action": "wait", "selector": "testid=never-appears", "timeout_ms": 500}],
        name="wait-timeout")
    elapsed = time.monotonic() - started

    step = result["steps"][0]
    assert not step["passed"]
    assert elapsed < 5, f"honoured the 10s default instead of 500ms ({elapsed:.1f}s)"
    assert step["ai_suggestion"]
