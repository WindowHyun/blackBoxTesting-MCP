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


async def test_save_name_collision_is_flagged_not_clobbered(scenario_dir):
    # "checkout/happy" and "checkout happy" sanitize to the same file — the
    # second save must report the collision (naming the real owner), not
    # silently clobber or claim the wrong name "already exists".
    await save_scenario("checkout/happy", STEPS)
    r = await save_scenario("checkout happy", STEPS)
    assert r["ok"] is False
    assert "checkout/happy" in r["error"]  # names the actual on-disk owner
    # the original is intact
    assert (await load_scenario("checkout/happy"))["steps"] == STEPS


async def test_same_name_reload_is_not_a_collision(scenario_dir):
    # saving and reloading under the identical string is normal, not a clash
    await save_scenario("my scenario", STEPS)
    assert (await load_scenario("my scenario"))["ok"] is True


async def test_load_missing(scenario_dir):
    r = await load_scenario("ghost")
    assert r["ok"] is False


async def test_load_corrupt_json_returns_error_not_crash(scenario_dir):
    # a half-written / hand-edited scenario file must not crash the tool
    (scenario_dir / "broken.json").write_text("{ not valid json ", encoding="utf-8")
    r = await load_scenario("broken")
    assert r["ok"] is False and "corrupted" in r["error"]


async def test_loaded_scenario_runs(session, scenario_dir):
    steps = [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "assert", "kind": "text_visible", "target": "로그인"},
    ]
    await save_scenario("fixture_flow", steps)
    loaded = (await load_scenario("fixture_flow"))["steps"]
    res = await runner.run(loaded, name="fixture_flow")
    assert res["summary"]["failed"] == 0


# ── SL-01 sampling path (_try_sampling) ───────────────────────────
class _FakeContent:
    def __init__(self, text):
        self.text = text


class _FakeResult:
    def __init__(self, text):
        self.content = _FakeContent(text)


class _FakeSession:
    def __init__(self, text):
        self._text = text

    async def create_message(self, messages, max_tokens):
        return _FakeResult(self._text)


class _FakeCtx:
    def __init__(self, text):
        self.session = _FakeSession(text)


async def test_try_sampling_extracts_json_array_from_prose():
    from blackbox_mcp.tools.generate import _try_sampling
    text = 'Sure! Steps:\n[{"action": "navigate", "url": "x"}]\nThat covers it.'
    steps = await _try_sampling(_FakeCtx(text), "goal", {"k": 1})
    assert steps == [{"action": "navigate", "url": "x"}]


async def test_try_sampling_none_when_no_array():
    from blackbox_mcp.tools.generate import _try_sampling
    assert await _try_sampling(_FakeCtx("no json at all"), "g", {}) is None


async def test_try_sampling_none_on_malformed_json():
    from blackbox_mcp.tools.generate import _try_sampling
    assert await _try_sampling(_FakeCtx("[not, valid}"), "g", {}) is None


async def test_try_sampling_none_when_sampling_unsupported():
    from blackbox_mcp.tools.generate import _try_sampling

    class _Boom:
        async def create_message(self, **k):
            raise RuntimeError("client has no sampling")

    class _Ctx:
        session = _Boom()

    assert await _try_sampling(_Ctx(), "g", {}) is None


async def test_generate_scenario_uses_sampling_when_it_returns_steps(session):
    from blackbox_mcp.tools.generate import generate_scenario
    url = fixture_url("basic.html")
    reply = f'ok:\n[{{"action": "navigate", "url": "{url}"}}]'
    out = await generate_scenario("로그인", url, ctx=_FakeCtx(reply))
    assert out["mode"] == "generated"
    assert out["steps"][0]["action"] == "navigate"
    assert "kit" in out  # kit still included as a fallback reference


async def test_generate_scenario_falls_back_to_kit_when_sampling_empty(session):
    from blackbox_mcp.tools.generate import generate_scenario
    url = fixture_url("basic.html")
    out = await generate_scenario("로그인", url, ctx=_FakeCtx("no steps here"))
    assert out["mode"] == "kit"


# ── SL-01 _suggest_selector role mapping (unit, no browser) ───────
def test_suggest_selector_input_types_map_to_correct_role():
    from blackbox_mcp.tools.generate import _suggest_selector
    # a submit input is role=button, NOT textbox (was mislabeled → step failed)
    assert _suggest_selector(
        {"tag": "input", "type": "submit", "name": "Submit"}) == "role=button name=Submit"
    assert _suggest_selector(
        {"tag": "input", "type": "checkbox", "name": "agree"}) == "role=checkbox name=agree"
    assert _suggest_selector(
        {"tag": "input", "type": "email", "name": "email"}) == "role=textbox name=email"
    # explicit role attribute wins over type inference
    assert _suggest_selector(
        {"tag": "input", "type": "text", "role": "combobox", "name": "city"}
    ) == "role=combobox name=city"
    # testid always wins
    assert _suggest_selector(
        {"tag": "input", "type": "submit", "testid": "go", "name": "Go"}) == "testid=go"


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
