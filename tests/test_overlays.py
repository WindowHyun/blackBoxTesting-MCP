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


# ── negative-control guard (P1 regression) ────────────────────────
#
# get_by_role(name=...) matches by SUBSTRING, so the positive label "동의" also
# matches "동의하지 않음" and "Allow" matches "Don't allow". The sweep used to
# click those, reversing the consent it had just granted — and on a page with no
# banner at all, pressing an unrelated negative control — while reporting ok.

def test_is_negative_recognizes_refusals_and_drilldowns():
    from blackbox_mcp.tools.overlays import _is_negative

    for name in ("동의하지 않음", "동의 안 함", "허용 안 함", "허용안함", "비동의",
                 "거부", "쿠키 거절", "취소", "설정", "쿠키 설정", "상세 설정",
                 "Decline", "Reject all", "Don't allow", "Do Not Sell",
                 "No thanks", "Not now", "Manage preferences",
                 "Accept necessary only", "Only essential cookies"):
        assert _is_negative(name), name


def test_is_negative_passes_real_consent_labels():
    from blackbox_mcp.tools.overlays import _LABELS, _is_negative

    # every label the sweep searches for must itself be clickable
    for label in _LABELS:
        assert not _is_negative(label), label
    for name in ("모두 동의하기", "전체 동의", "동의합니다", "확인", "닫기",
                 "Accept all cookies", "I Agree", "Allow all", "Got it"):
        assert not _is_negative(name), name


async def test_does_not_click_the_decline_button(session):
    """The demonstrated defect: accept, then have '동의' hit '동의하지 않음'."""
    await session.page.set_content(
        "<div id='banner'><p>쿠키 사용에 동의하시겠습니까?</p>"
        "<button onclick=\"document.getElementById('out').textContent='DECLINED'\">"
        "동의하지 않음</button>"
        "<button onclick=\"document.getElementById('out').textContent='ACCEPTED'\">"
        "모두 동의</button></div><p id='out'>none</p>"
    )
    r = await dismiss_banners()

    assert r["dismissed"] == ["button:모두 동의"]
    assert any("동의하지 않음" in s for s in r["skipped"])
    # the consent granted by the accept click was NOT reversed
    assert await session.page.locator("#out").text_content() == "ACCEPTED"


async def test_never_clicks_a_refusal_only_banner(session):
    """No positive control present → click nothing, rather than the refusal."""
    await session.page.set_content(
        "<div id='banner'>"
        "<button onclick=\"document.getElementById('out').textContent='DECLINED'\">"
        "동의하지 않음</button>"
        "<button onclick=\"document.getElementById('out').textContent='SETTINGS'\">"
        "쿠키 설정</button></div><p id='out'>none</p>"
    )
    r = await dismiss_banners()

    assert r["dismissed"] == []
    assert await session.page.locator("#out").text_content() == "none"


async def test_does_not_click_the_same_control_twice(session):
    """'모두 동의' and '동의' resolve to ONE button — it is clicked once.

    The banner deliberately survives the click (a real one often needs a
    re-render tick), which is exactly when the broader label used to land a
    second click on whatever was underneath.
    """
    await session.page.set_content(
        "<div id='banner'><button onclick=\"window.__n=(window.__n||0)+1\">"
        "모두 동의</button></div>"
    )
    r = await dismiss_banners()

    assert r["dismissed"] == ["button:모두 동의"]
    assert await session.page.evaluate("() => window.__n") == 1


async def test_english_negation_is_not_clicked(session):
    await session.page.set_content(
        "<div><button onclick=\"document.getElementById('o').textContent='NO'\">"
        "Don't allow</button>"
        "<button onclick=\"document.getElementById('o').textContent='YES'\">"
        "Allow all</button></div><p id='o'>none</p>"
    )
    r = await dismiss_banners()

    assert r["dismissed"] == ["button:Allow all"]
    assert await session.page.locator("#o").text_content() == "YES"
