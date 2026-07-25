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


async def test_dismiss_never_submits_a_form_on_a_bannerless_page(session):
    """The label list must not reach the page under test.

    Regression: names were matched as SUBSTRINGS page-wide, so a checkout page
    with an exact "확인" submit button (and no banner at all) had its order
    submitted by the consent helper the prompt matrix calls on every
    intercepted click.
    """
    await session.page.set_content(
        "<h1>주문 확인</h1>"
        "<form onsubmit=\"document.getElementById('out').textContent='SUBMITTED';"
        "return false\"><button type='submit'>확인</button></form>"
        "<div id='out'>not submitted</div>"
    )
    r = await dismiss_banners()
    assert r["dismissed"] == []
    assert await session.page.evaluate(
        "document.getElementById('out').textContent") == "not submitted"


async def test_dismiss_does_not_substring_match_business_actions(session):
    """Exact matching only: consent words are a prefix of real action labels."""
    await session.page.set_content(
        "<button onclick=\"log(this)\">주문 확인하기</button>"
        "<button onclick=\"log(this)\">Accept terms and place order</button>"
        "<button onclick=\"log(this)\">Continue to payment</button>"
        "<div id='out'></div><script>function log(b){"
        "document.getElementById('out').textContent += '['+b.textContent+']'}</script>"
    )
    r = await dismiss_banners()
    assert r["dismissed"] == []
    assert await session.page.evaluate(
        "document.getElementById('out').textContent") == ""


async def test_generic_label_clicked_only_inside_an_overlay(session):
    """"확인" is a real verb: allowed in a consent dialog, nowhere else."""
    await session.page.set_content(
        "<div role='dialog' id='cookie-notice'>쿠키를 사용합니다"
        "<button onclick=\"document.getElementById('cookie-notice').remove()\">"
        "확인</button></div>"
        "<button data-testid='real'>확인</button>"
    )
    r = await dismiss_banners()
    assert r["dismissed"] == ["button:확인"]
    assert r["overlays_seen"] >= 1
    # the dialog is gone; the identically-labelled page control is untouched
    assert (await assert_("element_visible", "#cookie-notice"))["passed"] is False
    assert (await assert_("element_visible", "testid=real"))["passed"] is True
