"""assert_ verification kinds, incl. multi-match strict-mode regression (CT-05)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate
from blackbox_mcp.tools.assertion import assert_


async def test_text_visible_multi_match_does_not_throw(session):
    # two elements contain "로그인" — must not raise strict-mode violation
    await session.page.set_content("<h1>로그인</h1><button>로그인</button>")
    r = await assert_("text_visible", "로그인")
    assert r["passed"] is True


async def test_text_visible_absent(session):
    await session.page.set_content("<p>hello</p>")
    r = await assert_("text_visible", "없는텍스트")
    assert r["passed"] is False


async def test_text_visible_hidden_first_match(session):
    # first match hidden, later one visible → "visible somewhere" must PASS
    # (regression: .first.is_visible() failed this, disagreeing with
    # element_visible on the same page).
    await session.page.set_content(
        "<span style='display:none'>로그인</span><button>로그인</button>")
    assert (await assert_("text_visible", "로그인"))["passed"] is True
    assert (await assert_("element_visible", "로그인"))["passed"] is True


async def test_text_visible_all_hidden(session):
    await session.page.set_content("<span style='display:none'>로그인</span>")
    assert (await assert_("text_visible", "로그인"))["passed"] is False


async def test_element_visible_by_testid(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    r = await assert_("element_visible", "testid=submit")
    assert r["passed"] is True


async def test_url_contains(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    r = await assert_("url_contains", "basic.html")
    assert r["passed"] is True


async def test_count(session):
    await session.page.set_content("<ul><li>a</li><li>b</li><li>c</li></ul>")
    r = await assert_("count", "css=li", "3")
    assert r["passed"] is True


async def test_count_non_int_expected(session):
    await session.page.set_content("<ul><li>a</li></ul>")
    r = await assert_("count", "css=li", "notanumber")
    assert r["passed"] is False
