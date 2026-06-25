"""CT-02: snapshot — page understanding for Claude.

a11y mode uses locator.aria_snapshot() (YAML); accessibility.snapshot() is
deprecated. dom mode returns a brief tag/role/text outline.

Q1 finding (Phase 1, measured against synthetic DOM on Playwright 1.60):
- Plain ``aria_snapshot()`` is already concise and is the default.
- ``depth`` only takes effect when paired with ``mode="ai"``; on its own it is
  ignored. So when a caller passes ``depth`` we switch to the AI-mode snapshot
  (which also carries element refs useful for follow-up interaction) and trim by
  depth. Example: a 30-section DOM was 2317 chars by default vs 684 chars at
  ``mode="ai", depth=1``.
- ``_MAX_CHARS`` remains a final safety net regardless of mode.
Use ``focus`` to scope to a subtree when a page is large.
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool

# Final safety net against context-blowing snapshots (chars).
_MAX_CHARS = 20000


@tool(description="Return a textual snapshot of the page. mode='a11y' yields the "
                  "ARIA (accessibility) tree as YAML; mode='dom' a brief outline. "
                  "focus=<css> scopes to a subtree; depth=<n> trims deep trees.")
async def snapshot(mode: str = "a11y", focus: str | None = None,
                   depth: int | None = None) -> str:
    session = await get_session()
    root = session.root
    target = root.locator(focus) if focus else root.locator("body")

    if mode == "dom":
        text = await target.inner_text()
    elif depth is not None:
        # depth requires AI mode to have any effect (Q1 finding).
        text = await target.aria_snapshot(mode="ai", depth=depth)
    else:
        text = await target.aria_snapshot()

    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + (
            f"\n... [truncated at {_MAX_CHARS} chars — narrow with focus= or depth=]"
        )
    return text
