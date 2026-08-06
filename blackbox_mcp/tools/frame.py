"""CT-09: switch_frame — enter an iframe context (or back to main).

Nested iframes (legacy intranet apps love them) need a *chain* of
frame_locator() calls: a selector string never crosses a frame boundary, so
``#outer >> #inner`` matches nothing. Write the chain with ``>>>`` instead.
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


@tool(description="Switch into an iframe by CSS selector for subsequent tool calls. "
                  "For a NESTED iframe, chain the selectors with '>>>' "
                  "(e.g. '#outer >>> #inner') — outermost first. Pass null/empty "
                  "to return to the main page context. Note: selectors here are "
                  "raw CSS (not the D2 chain).")
async def switch_frame(selector: str | None = None) -> dict:
    session = await get_session()
    session.set_frame(selector or None)
    chain = session.frame_chain
    out: dict = {"ok": True, "context": session._frame_selector or "main",
                 "depth": len(chain)}
    if chain:
        # Best-effort feedback: switching before the frame exists is valid
        # (navigate-then-switch), so this never fails — but a matched=False
        # flags a typo'd/missing selector instead of silently "succeeding"
        # and letting every later call time out with no hint.
        #
        # Probed hop by hop so a nested chain reports WHICH hop is missing;
        # "#outer >>> #inenr" is otherwise indistinguishable from a frame that
        # simply hasn't rendered yet.
        matched, node = True, session.page
        for depth, sel in enumerate(chain):
            try:
                if await node.locator(sel).count() == 0:
                    matched = False
                    out["missing_at"] = {"depth": depth, "selector": sel}
                    break
                node = node.frame_locator(sel)
            except Exception:
                matched = False
                out["missing_at"] = {"depth": depth, "selector": sel}
                break
        out["matched"] = matched
    return out
