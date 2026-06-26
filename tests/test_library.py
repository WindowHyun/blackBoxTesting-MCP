"""Phase 5 — scenario library + generate_scenario kit (SL-01~04)."""
from __future__ import annotations

import dataclasses

import pytest
from conftest import fixture_url

from blackbox_mcp.testing import library as lib_store
from blackbox_mcp.tools.library import save_scenario, load_scenario, list_scenarios
from blackbox_mcp.tools.generate import generate_scenario
from blackbox_mcp.testing import runner


@pytest.fixture
def scenario_dir(tmp_path, monkeypatch):
    cfg = dataclasses.replace(lib_store.CONFIG, scenario_dir=tmp_path)
    monkeypatch.setattr(lib_store, "CONFIG", cfg)
    return tmp_path


STEPS = [
    {"action": "navigate", "url": "https://example.com", "wait_until": "load"},
    {"action": "assert", "kind": "url_contains", "target": "example"},
]


async def test_save_load_list_roundtrip(scenario_dir):
    r = await save_scenario("login", STEPS)
    assert r["ok"] and r["steps"] == 2

    loaded = await load_scenario("login")
    assert loaded["ok"] and loaded["steps"] == STEPS

    listing = await list_scenarios()
    assert any(s["name"] == "login" and s["steps"] == 2 for s in listing)


async def test_save_no_overwrite_without_flag(scenario_dir):
    await save_scenario("dup", STEPS)
    r = await save_scenario("dup", STEPS)            # no overwrite
    assert r["ok"] is False and r["exists"] is True
    r2 = await save_scenario("dup", STEPS, overwrite=True)
    assert r2["ok"] is True


async def test_load_missing(scenario_dir):
    r = await load_scenario("ghost")
    assert r["ok"] is False


async def test_loaded_scenario_runs(session, scenario_dir):
    steps = [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "assert", "kind": "text_visible", "target": "로그인"},
    ]
    await save_scenario("fixture_flow", steps)
    loaded = (await load_scenario("fixture_flow"))["steps"]
    res = await runner.run(loaded, name="fixture_flow")
    assert res["summary"]["failed"] == 0


# ── SL-01 generate_scenario kit ───────────────────────────────────
async def test_generate_returns_kit(session):
    out = await generate_scenario("로그인 흐름 테스트", fixture_url("basic.html"))
    assert out["mode"] == "kit"
    kit = out["kit"]
    # the fixture's testid'd controls should be discovered with selectors
    selectors = [e["suggested_selector"] for e in kit["interactive_elements"]]
    assert any("testid=submit" in s for s in selectors)
    assert any("testid=email" in s for s in selectors)
    assert kit["step_schema"] and kit["example"]


async def test_generate_kit_steps_are_runnable(session):
    """A scenario composed from kit selectors actually runs."""
    out = await generate_scenario("이메일 입력 후 제출", fixture_url("basic.html"))
    assert out["mode"] == "kit"
    steps = [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "interact", "type": "type", "selector": "testid=email", "value": "u@x.com"},
        {"action": "interact", "type": "click", "selector": "testid=submit"},
        {"action": "assert", "kind": "text_visible", "target": "로그인됨"},
    ]
    res = await runner.run(steps, name="from_kit")
    assert res["summary"]["failed"] == 0
