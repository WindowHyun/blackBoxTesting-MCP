"""dismiss_banners — close common cookie/consent overlays that intercept clicks.

Real sites front-load GDPR/cookie banners and modals that cover the page, so a
click on the real target fails with "intercepts pointer events". This tries a
list of common accept/close labels (KO/EN) and clicks the first visible one.

This tool clicks buttons nobody asked it to click, on pages it knows nothing
about, so it is deliberately narrow on two axes:

1. **Whole-label match.** ``get_by_role(name=...)`` defaults to a
   case-insensitive *substring* match, which made "확인" match "주문 확인" —
   measured on a fixture, dismiss_banners submitted the order. Labels are
   matched as full strings (case-insensitive, whitespace-normalised) instead.
2. **Overlay scope only.** A candidate must sit inside something that behaves
   like an overlay (fixed/sticky, <dialog>, role=dialog/alertdialog,
   aria-modal, or a stacked non-static ancestor). An in-page form button is
   never a cookie banner, and clicking one can submit or delete something.

Affirmative *proceed* verbs are not in the list at all: "확인" is the default
Korean submit/confirm verb and "Continue" advances checkout wizards. Consent
banners have consent wording ("동의/수락/허용/Accept/Agree") or dismiss wording
("닫기/Close/Dismiss"), and those are what we match.

Candidates rejected by the overlay rule come back in ``skipped_not_overlay`` so
a genuine banner this misses is visible, not silent — click it explicitly with
``interact``.
"""
from __future__ import annotations

import re

from ..browser import get_session
from ._registry import tool

# Consent/close labels, matched as WHOLE accessible names (see module docstring).
_LABELS = [
    "모두 동의", "전체 동의", "모두 수락", "모두 허용", "동의", "동의합니다",
    "수락", "허용", "닫기",
    "Accept all", "Accept cookies", "Accept", "Agree", "I agree",
    "Allow all", "Allow", "Got it", "OK", "Close", "Dismiss",
]

# Is this control inside something that behaves like an overlay? Walks up to
# <body>: a cookie banner is fixed/sticky, a <dialog>, an ARIA dialog, or at
# least stacked above the page with a z-index.
_IN_OVERLAY_JS = """
(el) => {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    if (n.tagName === 'DIALOG') return true;
    const role = (n.getAttribute('role') || '').toLowerCase();
    if (role === 'dialog' || role === 'alertdialog') return true;
    if (n.getAttribute('aria-modal') === 'true') return true;
    const s = getComputedStyle(n);
    if (s.position === 'fixed' || s.position === 'sticky') return true;
    if (s.position !== 'static' && parseInt(s.zIndex || '0', 10) >= 100) return true;
  }
  return false;
}
"""


def _whole_label(label: str) -> re.Pattern:
    """Case-insensitive full-string matcher for an accessible name.

    A regex rather than ``exact=True``: exact matching is case-SENSITIVE, which
    would need an entry per capitalisation ("Accept All"/"Accept all"/"ACCEPT ALL").
    """
    return re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)


@tool(description="Close common cookie/consent banners and modals that intercept "
                  "clicks. Call this after navigate on real sites if a click fails "
                  "with 'intercepts pointer events'. Only clicks consent/close "
                  "labels that match a control's FULL name AND sit inside an "
                  "overlay (fixed/sticky/dialog), so it cannot fire an in-page "
                  "business button. Returns what it clicked, and in "
                  "skipped_not_overlay what it deliberately left alone.")
async def dismiss_banners() -> dict:
    session = await get_session()
    root = session.root
    dismissed: list[str] = []
    skipped: list[str] = []

    for label in _LABELS:
        for role in ("button", "link"):
            try:
                loc = root.get_by_role(role, name=_whole_label(label)).first
                if await loc.count() == 0 or not await loc.is_visible():
                    continue
                if not await loc.evaluate(_IN_OVERLAY_JS, timeout=1500):
                    # Right words, wrong place — an ordinary page control.
                    skipped.append(f"{role}:{label}")
                    continue
                await loc.click(timeout=1500)
                dismissed.append(f"{role}:{label}")
                break  # next label
            except Exception:
                continue
        if len(dismissed) >= 3:  # enough; avoid clicking unrelated controls
            break

    return {"ok": True, "dismissed": dismissed, "skipped_not_overlay": skipped}
