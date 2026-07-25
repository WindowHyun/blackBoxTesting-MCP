"""dismiss_banners — close common cookie/consent overlays that intercept clicks.

Real sites front-load GDPR/cookie banners and modals that cover the page, so a
click on the real target fails with "intercepts pointer events".

**Blast radius (2026-07).** The first version matched labels with Playwright's
DEFAULT accessible-name matching, which is a *substring* match, and searched the
whole page. On a page with no banner at all that clicked real controls: ``확인``
matched "주문 확인하기", ``Accept`` matched "Accept terms and place order",
``Continue`` matched "Continue to payment" — a consent helper that submitted
orders. The prompt matrix tells the agent to call this whenever a click is
intercepted, so a false positive always lands on the page under test. Two rules
now bound it:

1. Names match **exactly** (``exact=True``) — never as substrings.
2. Labels are split by ambiguity:
   - :data:`_CONSENT_LABELS` ("모두 동의", "Accept all", …) name a consent action
     and nothing else, so they may be clicked anywhere on the page.
   - :data:`_GENERIC_LABELS` ("확인", "OK", "Continue", …) are ordinary UI verbs;
     they are only clicked **inside a detected overlay container**, so a bare
     "확인" submit button on the page under test is never touched.

Trading a few exotic banners for never firing a business action is the right
side of that bet.
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool

# Phrases that mean "dismiss this consent notice" and nothing else — safe to
# click anywhere on the page.
_CONSENT_LABELS = [
    "모두 동의", "모두 동의하기", "전체 동의", "모두 수락", "전체 수락",
    "모두 허용", "전체 허용", "쿠키 동의", "쿠키 허용", "동의하고 계속",
    "Accept all", "Accept All", "Accept all cookies", "Accept All Cookies",
    "Allow all", "Allow All", "Allow all cookies", "Accept cookies",
    "I agree", "I Agree", "Agree and continue", "Got it", "Dismiss",
]

# Ordinary UI verbs that a consent banner also happens to use. Only clicked
# inside an overlay container (below) — on their own they are just as likely to
# be the submit button of the form under test.
_GENERIC_LABELS = [
    "동의", "수락", "허용", "확인", "닫기",
    "Accept", "Agree", "Allow", "OK", "Close", "Continue",
]

# What counts as "an overlay": an explicit dialog role, or a container whose
# id/class names it as consent/cookie/banner/modal furniture.
_OVERLAY_CONTAINER = ", ".join((
    "[role=dialog]", "[role=alertdialog]", "[aria-modal=true]",
    '[id*="cookie" i]', '[class*="cookie" i]',
    '[id*="consent" i]', '[class*="consent" i]',
    '[id*="gdpr" i]', '[class*="gdpr" i]',
    '[id*="banner" i]', '[class*="banner" i]',
    '[id*="modal" i]', '[class*="modal" i]',
    '[id*="popup" i]', '[class*="popup" i]',
))

# Enough to clear a stacked banner + modal; the cap keeps a pathological page
# from turning this into a click storm.
_MAX_CLICKS = 3


async def _click_exact(scope, label: str) -> str | None:
    """Click the first visible button/link whose accessible name IS ``label``.

    Returns the ``role:label`` tag that was clicked, or None when nothing
    matched. Never raises — a banner helper must not fail the flow it unblocks.
    """
    for role in ("button", "link"):
        try:
            loc = scope.get_by_role(role, name=label, exact=True).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=1500)
                return f"{role}:{label}"
        except Exception:
            continue
    return None


@tool(description="Close common cookie/consent banners and modals that intercept "
                  "clicks. Call this after navigate on real sites if a click fails "
                  "with 'intercepts pointer events'. Accessible names are matched "
                  "EXACTLY, and ambiguous labels (확인/OK/Continue) are only clicked "
                  "inside a consent/dialog container — a real submit button on the "
                  "page under test is never pressed. Returns what it clicked.")
async def dismiss_banners() -> dict:
    session = await get_session()
    root = session.root
    overlays = root.locator(_OVERLAY_CONTAINER)

    try:
        overlays_seen = await overlays.count()
    except Exception:
        overlays_seen = 0

    dismissed: list[str] = []

    # 1) Unambiguous consent phrases — page-wide.
    for label in _CONSENT_LABELS:
        if len(dismissed) >= _MAX_CLICKS:
            break
        hit = await _click_exact(root, label)
        if hit:
            dismissed.append(hit)

    # 2) Ambiguous verbs — only within a detected overlay container.
    if overlays_seen:
        for label in _GENERIC_LABELS:
            if len(dismissed) >= _MAX_CLICKS:
                break
            hit = await _click_exact(overlays, label)
            if hit:
                dismissed.append(hit)

    return {"ok": True, "dismissed": dismissed, "overlays_seen": overlays_seen}
