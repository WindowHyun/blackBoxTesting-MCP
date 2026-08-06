"""Report readability (targeted masking) and the widened interact vocabulary."""
from __future__ import annotations

import pytest

from blackbox_mcp.testing import secrets
from blackbox_mcp.tools.interact import _display_value, interact


# ── masking is targeted, not blanket ─────────────────────────────
def test_ordinary_values_are_shown():
    """Regression: masking was unconditional, so every step read
    "selected ***" / "pressed ***" and a reviewer could not tell what was
    chosen — the report lost its evidentiary value."""
    assert _display_value("testid=city", "select", "부산") == "부산"
    assert _display_value("testid=search", "press", "Enter") == "Enter"


@pytest.mark.parametrize("selector", [
    "testid=password", "css=#user_pw", "role=textbox[name='비밀번호']",
    "testid=api_token", "testid=otp",
])
def test_credential_targets_are_masked(selector):
    assert _display_value(selector, "type", "hunter2") == "***"


def test_resolved_secret_is_swapped_for_its_placeholder(monkeypatch):
    """Even on a non-sensitive-looking field, a value that came from a
    ${SECRET} must never be echoed verbatim."""
    monkeypatch.setenv("APP_TOKEN", "tok-abc123")
    resolved = secrets.resolve("${APP_TOKEN}")
    assert resolved == "tok-abc123"
    assert _display_value("testid=q", "type", resolved) == "${APP_TOKEN}"


def test_empty_value_passes_through():
    assert _display_value("testid=x", "type", "") == ""
    assert _display_value("testid=x", "type", None) is None


# ── widened action vocabulary ────────────────────────────────────
async def test_select_by_visible_label(session):
    """QA writes what it sees on screen, not the value attribute."""
    await session.page.set_content(
        "<select data-testid=city>"
        "<option value=v1>서울</option><option value=v2>부산</option></select>")

    res = await interact("select", "testid=city", "부산")
    assert res["ok"] and res["detail"] == "selected 부산"
    assert await session.page.locator("select").input_value() == "v2"


async def test_check_and_uncheck(session):
    await session.page.set_content("<input data-testid=agree type=checkbox>")
    assert (await interact("check", "testid=agree"))["ok"]
    assert await session.page.locator("input").is_checked()
    assert (await interact("uncheck", "testid=agree"))["ok"]
    assert not await session.page.locator("input").is_checked()


async def test_clear_empties_a_field(session):
    await session.page.set_content("<input data-testid=q value='기존값'>")
    assert (await interact("clear", "testid=q"))["ok"]
    assert await session.page.locator("input").input_value() == ""


async def test_dblclick(session):
    await session.page.set_content(
        "<div id=out></div><button data-testid=b "
        "ondblclick=\"document.getElementById('out').textContent='DBL'\">x</button>")
    assert (await interact("dblclick", "testid=b"))["ok"]
    assert await session.page.locator("#out").inner_text() == "DBL"


async def test_scroll_into_view(session):
    await session.page.set_content(
        "<div style='height:3000px'></div><button data-testid=far>far</button>")
    assert (await interact("scroll_into_view", "testid=far"))["ok"]


async def test_unknown_action_lists_the_supported_ones(session):
    res = await interact("teleport", "testid=x")
    assert not res["ok"] and "upload" in res["detail"]
