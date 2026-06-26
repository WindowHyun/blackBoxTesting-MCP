"""dismiss_banners — close common cookie/consent overlays that intercept clicks.

Real sites front-load GDPR/cookie banners and modals that cover the page, so a
click on the real target fails with "intercepts pointer events". This tries a
list of common accept/close labels (KO/EN) and clicks the first visible one.
Safe: short per-try timeout, never errors if nothing matches.
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


@tool(description="Close common cookie/consent banners and modals that intercept "
                  "clicks. Call this after navigate on real sites if a click fails "
                  "with 'intercepts pointer events'. Returns which labels it clicked.")
async def dismiss_banners() -> dict:
    session = await get_session()
    root = session.root
    dismissed: list[str] = []

    for label in _LABELS:
        for role in ("button", "link"):
            try:
                loc = root.get_by_role(role, name=label).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=1500)
                    dismissed.append(f"{role}:{label}")
                    break  # next label
            except Exception:
                continue
        if len(dismissed) >= 3:  # enough; avoid clicking unrelated controls
            break

    return {"ok": True, "dismissed": dismissed}
