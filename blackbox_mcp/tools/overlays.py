"""dismiss_banners — close common cookie/consent overlays that intercept clicks.

Real sites front-load GDPR/cookie banners and modals that cover the page, so a
click on the real target fails with "intercepts pointer events". This tries a
list of common accept/close labels (KO/EN) and clicks the first visible one.
Safe: short per-try timeout, never errors if nothing matches.

Matching is deliberately guarded. ``get_by_role(name=...)`` matches by
SUBSTRING, so a positive label also matches its own negation — name="동의"
matches "동의하지 않음", name="Allow" matches "Don't allow". Clicking that
reverses the consent just granted, or presses an unrelated negative control on
a page that has no banner at all. So every candidate's real accessible name is
read and checked against _NEGATIVE before it is clicked, and a control one
label already clicked is not clicked again under a broader label.
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool

# Common consent/close button labels (substring, case-insensitive via get_by_role).
_LABELS = [
    "모두 동의", "전체 동의", "모두 수락", "모두 허용", "동의", "수락", "허용",
    "확인", "닫기",
    "Accept all", "Accept All", "Accept", "Agree", "I agree", "I Agree",
    "Allow all", "Allow", "Got it", "OK", "Close", "Dismiss", "Continue",
]

# A matched element whose accessible name contains any of these is NOT clicked,
# however well it matched a positive label above. Two families:
#   - refusals ("동의하지 않음", "Don't allow", "Reject all") — clicking them
#     undoes the consent, which is worse than leaving the banner up;
#   - drill-downs ("설정", "Manage preferences") — they open a sub-dialog
#     instead of dismissing, so the overlay is still there and now deeper.
_NEGATIVE = (
    # KO
    "동의하지", "동의 안", "비동의", "거부", "거절", "허용 안", "허용하지",
    "사용 안", "사용하지", "수락 안", "취소", "나중에", "선택 동의",
    "설정", "상세", "관리",
    # EN
    "decline", "reject", "deny", "disagree", "refuse", "don't", "do not",
    "dont", "no thanks", "not now", "later", "cancel", "opt out", "opt-out",
    "manage", "settings", "preferences", "customize", "customise", "options",
    "necessary only", "essential only", "only necessary", "only essential",
    "required only", "only required",
)

# Stop after this many DISTINCT controls: stacked overlays (cookie banner +
# newsletter modal) are real, an endless sweep is not.
_MAX_CLICKS = 3
# Matches inspected per (label, role). The first match can legitimately be the
# refusal button sitting before the accept button in DOM order, so looking at
# only .first would skip the control we actually want.
_MAX_CANDIDATES = 3
# Per-probe budget. Reading a name must never cost the selector timeout.
_PROBE_MS = 500


def _is_negative(name: str) -> bool:
    """True when an accessible name reads as a refusal or a settings drill-down.

    Checked both whitespace-normalized and whitespace-stripped so "허용 안 함"
    and "허용안함" are both caught.
    """
    low = " ".join(str(name or "").split()).lower()
    if not low:
        return False
    tight = low.replace(" ", "")
    return any(k in low or k.replace(" ", "") in tight for k in _NEGATIVE)


async def _name_of(element) -> str:
    """The element's accessible name as the user reads it (aria-label, else text).

    An empty string means "could not tell" — the caller treats that as
    non-negative so an icon-only close button still gets clicked, exactly as
    before this guard existed.
    """
    try:
        aria = await element.get_attribute("aria-label", timeout=_PROBE_MS)
        if aria and aria.strip():
            return " ".join(aria.split())
        text = await element.inner_text(timeout=_PROBE_MS)
        return " ".join((text or "").split())
    except Exception:
        return ""


async def _click_label(root, label: str, clicked: set[str],
                       skipped: list[str]) -> str | None:
    """Click the first safe visible control matching ``label``; return its tag."""
    for role in ("button", "link"):
        loc = root.get_by_role(role, name=label)
        try:
            count = await loc.count()
        except Exception:
            continue
        for i in range(min(count, _MAX_CANDIDATES)):
            element = loc.nth(i)
            try:
                if not await element.is_visible():
                    continue
                name = await _name_of(element) or label
                if _is_negative(name):
                    note = f"{role}:{name}"
                    if note not in skipped:
                        skipped.append(note)
                    continue
                if name in clicked:
                    continue  # the same control a broader label already hit
                await element.click(timeout=1500)
                clicked.add(name)
                return f"{role}:{name}"
            except Exception:
                continue
    return None


@tool(description="Close common cookie/consent banners and modals that intercept "
                  "clicks. Call this after navigate on real sites if a click fails "
                  "with 'intercepts pointer events'. Returns which controls it "
                  "clicked, and in 'skipped' the refusal/settings controls that "
                  "matched a consent label but were deliberately NOT clicked.")
async def dismiss_banners() -> dict:
    session = await get_session()
    root = session.root
    dismissed: list[str] = []
    skipped: list[str] = []
    clicked: set[str] = set()

    for label in _LABELS:
        if len(dismissed) >= _MAX_CLICKS:
            break
        hit = await _click_label(root, label, clicked, skipped)
        if hit:
            dismissed.append(hit)

    return {"ok": True, "dismissed": dismissed, "skipped": skipped}
