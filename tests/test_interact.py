"""T2.3 / T2.2 — interact actions + D2 chain resolution (CT-04, D2)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate
from blackbox_mcp.tools.interact import interact
from blackbox_mcp.tools.assertion import assert_


async def test_type_and_click_flow(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    await interact("type", "testid=email", "user@example.com")
    r = await interact("click", "testid=submit")
    assert r["ok"] is True
    assert r["resolved_by"] == "testid"
    # the click handler flips the status text
    assert (await assert_("text_visible", "로그인됨"))["passed"] is True


async def test_chain_resolves_bare_text(session):
    await session.page.set_content("<button>다음</button>")
    r = await interact("click", "다음")        # no prefix -> chain -> text
    assert r["ok"] is True
    assert r["resolved_by"] == "text"


async def test_chain_prefers_testid(session):
    await session.page.set_content('<button data-testid="go">갈래</button>')
    r = await interact("click", "go")           # bare -> testid match wins
    assert r["ok"] is True
    assert r["resolved_by"] == "testid"


async def test_hover_select_press(session):
    await session.page.set_content(
        "<select data-testid='s'><option value='a'>A</option>"
        "<option value='b'>B</option></select>"
        "<input data-testid='inp'>"
        "<a data-testid='link' href='#'>hi</a>"
    )
    assert (await interact("hover", "testid=link"))["ok"] is True
    assert (await interact("select", "testid=s", "b"))["ok"] is True
    r = await interact("press", "testid=inp", "a")
    assert r["ok"] is True
    assert (await assert_("element_visible", "testid=s"))["passed"] is True


async def test_unknown_action_is_structured(session):
    r = await interact("frobnicate", "testid=x")
    assert r["ok"] is False


async def test_missing_element_returns_error_not_raise(session):
    await session.page.set_content("<p>nothing here</p>")
    r = await interact("click", "testid=nope", None)
    assert r["ok"] is False
    assert "error" in r
