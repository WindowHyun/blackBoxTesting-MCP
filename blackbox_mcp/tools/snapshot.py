"""CT-02: snapshot — page understanding for Claude.

a11y mode uses locator.aria_snapshot() (YAML); accessibility.snapshot() is
deprecated. dom mode returns a brief tag/role/text outline.

Q1 (snapshot size for large SPAs) is measured in Phase 1; trimming knobs
(max_chars / focus) are introduced here as the policy is finalized.
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool

# Conservative cap until Q1 is measured against real pages.
_MAX_CHARS = 20000


@tool(description="Return a textual snapshot of the page. mode='a11y' yields the "
                  "ARIA (accessibility) tree as YAML; mode='dom' a brief outline.")
async def snapshot(mode: str = "a11y", focus: str | None = None) -> str:
    session = await get_session()
    root = session.root
    target = root.locator(focus) if focus else root.locator("body")

    if mode == "a11y":
        text = await target.aria_snapshot()
    else:
        # Brief DOM outline; refined in Phase 1 alongside Q1.
        text = await target.inner_text()

    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + f"\n... [truncated at {_MAX_CHARS} chars — use focus=]"
    return text
