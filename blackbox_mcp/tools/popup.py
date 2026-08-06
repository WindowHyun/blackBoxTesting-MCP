"""expect_popup — click something and wait for the popup/new tab it opens.

The session auto-follows new tabs, but that path is only as timely as the
``page`` event, which Chromium does not emit until the popup has COMMITTED its
navigation (measured: ~1.08s for a server that takes 1s to respond, while the
click itself returned in 75ms). So a bare click → assert against the popup
races the popup into existence and fails on any non-instant server.

Fixing that generically would mean making every click wait out a popup grace
window it usually doesn't need. Instead this follows the pattern already used
for the other things that must be armed *around* an action (expect_dialog,
expect_download): an explicit step that costs nothing when you don't use it and
is deterministic when you do.
"""
from __future__ import annotations

from ..browser import get_session
from ..browser.locator import resolve
from ..config import CONFIG
from ._registry import tool


@tool(description="Click a trigger and wait for the popup/new tab it opens, then "
                  "make that popup the active page. Use this instead of a bare click "
                  "whenever the next step asserts on the popup — a plain click can "
                  "race the popup into existence. expect_url (substring) asserts "
                  "which page opened. Use switch_tab to go back to the opener.")
async def expect_popup(trigger: str, expect_url: str | None = None,
                       timeout_ms: int = 30000) -> dict:
    session = await get_session()
    context = session._context
    if context is None:
        return {"passed": False, "error": "no active browser context"}

    locator, resolved_by = await resolve(session.root, trigger)

    clicked = False
    try:
        async with context.expect_page(timeout=timeout_ms) as info:
            await locator.click(timeout=CONFIG.selector_timeout_ms)
            clicked = True
        popup = await info.value
    except Exception as exc:
        # Disambiguate: a click that never landed is a selector problem, a click
        # that landed with no popup is an app problem. Same exception type.
        if not clicked:
            return {"passed": False, "resolved_by": resolved_by, "url": None,
                    "error": f"trigger click failed ({type(exc).__name__})"}
        return {"passed": False, "resolved_by": resolved_by, "url": None,
                "error": f"no popup opened within {timeout_ms}ms"}

    try:
        await popup.wait_for_load_state("domcontentloaded")
    except Exception:
        pass  # popup closed itself again, or never finished — report what we have

    # The context "page" listener already adopted it; do it explicitly too so
    # this tool is correct even in modes where auto-adoption is off (CDP).
    session._adopt_page(popup)
    await session.settle()

    url = popup.url
    try:
        title = await popup.title()
    except Exception:
        title = None

    ok = expect_url is None or expect_url in (url or "")
    return {"passed": ok, "resolved_by": resolved_by, "url": url, "title": title,
            "error": None if ok else f"popup url {url!r} does not contain {expect_url!r}"}
