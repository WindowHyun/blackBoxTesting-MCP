"""list_tabs / switch_tab — explicit control over popups and new windows.

The session auto-follows a newly opened tab, which is right for the common
"click → popup → continue there" flow. But a real verification often needs the
opposite: check the popup, then go BACK to the opener and assert the parent
page updated. Auto-adoption alone gives no way back short of closing the popup.
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


@tool(description="List the open tabs/popups: index, url, title and which one is "
                  "active. Use with switch_tab to verify the opener page after a "
                  "popup flow.")
async def list_tabs() -> list[dict]:
    session = await get_session()
    tabs = session.list_pages()
    # Title needs a round-trip per page, so it is fetched here rather than in
    # the session accessor (which stays sync for use from event handlers).
    pages = session._context.pages if session._context is not None else []
    for tab in tabs:
        try:
            tab["title"] = await pages[tab["index"]].title()
        except Exception:
            tab["title"] = None
    return tabs


@tool(description="Make an open tab active by its index from list_tabs. Index 0 is "
                  "the oldest tab (usually the one the flow started in). Resets the "
                  "iframe context to the tab's main frame.")
async def switch_tab(index: int = 0) -> dict:
    session = await get_session()
    try:
        info = session.switch_page(index)
    except (IndexError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc), "tabs": session.list_pages()}
    return {"ok": True, **info}
