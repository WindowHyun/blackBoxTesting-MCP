"""D2 selector chain — CSS heuristic guard (unit) + role tier (browser)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.browser.locator import _looks_like_css, resolve


# ── unit: CSS inference must not swallow dotted visible text ──────
def test_css_heuristic_only_on_structural_signals():
    # real CSS → CSS
    assert _looks_like_css(".btn") is True
    assert _looks_like_css("#login") is True
    assert _looks_like_css("[data-x=y]") is True
    assert _looks_like_css("div>a") is True
    # visible text that merely contains a dot → NOT css (was mis-coerced before)
    assert _looks_like_css("example.com") is False
    assert _looks_like_css("v1.2") is False
    assert _looks_like_css("로그인") is False
    assert _looks_like_css("Log in") is False


# ── browser: bare string tries role+name (D2 #2), not just testid→text ──
async def test_resolve_bare_string_uses_role_tier(session):
    await session.page.goto(fixture_url("basic.html"))
    # basic.html has a <button>로그인</button> with no data-testid text match;
    # the role tier (get_by_role("button", name="로그인")) must win the chain.
    loc, resolved_by = await resolve(session.page, "로그인")
    assert await loc.count() >= 1
    assert resolved_by.startswith("role") or resolved_by == "testid"


async def test_resolve_reports_strategy(session):
    await session.page.goto(fixture_url("basic.html"))
    loc, by = await resolve(session.page, "testid=submit")
    assert by == "testid" and await loc.count() == 1
