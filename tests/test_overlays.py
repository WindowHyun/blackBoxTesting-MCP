"""dismiss_banners — consent/cookie overlay handling (real-site robustness)."""
from __future__ import annotations

from blackbox_mcp.tools.overlays import dismiss_banners
from blackbox_mcp.tools.assertion import assert_


async def test_dismiss_clicks_consent_button(session):
    await session.page.set_content(
        "<div id='banner'>쿠키 사용 동의"
        "<button onclick=\"document.getElementById('banner').remove()\">모두 동의</button>"
        "</div><button data-testid='real'>로그인</button>"
    )
    r = await dismiss_banners()
    assert any("동의" in d for d in r["dismissed"])
    # the banner is gone, the real control remains
    assert (await assert_("element_visible", "#banner"))["passed"] is False
    assert (await assert_("element_visible", "testid=real"))["passed"] is True


async def test_dismiss_noop_when_no_banner(session):
    await session.page.set_content("<button data-testid='x'>hi</button>")
    r = await dismiss_banners()
    assert r["ok"] is True
    assert r["dismissed"] == []
