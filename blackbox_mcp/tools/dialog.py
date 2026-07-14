"""CT-10: expect_dialog — wait for a browser dialog, verify text, accept/dismiss.

A dialog (alert/confirm/prompt/beforeunload) blocks JS until handled and, with no
listener, Playwright auto-dismisses it. So the robust, self-contained pattern is
to arm ``page.expect_event("dialog")`` *around* the action that triggers it.

Usage:
- Provide ``trigger`` (a selector) and the tool clicks it inside the dialog wait,
  captures the dialog, verifies ``expected_text``, and accept()/dismiss()es it.
- ``action`` ∈ accept | dismiss. ``accept_text`` fills a prompt on accept.
- If no dialog appears within the timeout, returns passed=False.
"""
from __future__ import annotations

from ..browser import get_session
from ..browser.locator import resolve
from ..config import CONFIG
from ._registry import tool


@tool(description="Trigger an action and handle the resulting browser dialog "
                  "(alert/confirm/prompt/beforeunload): verify its text and "
                  "accept or dismiss. action ∈ accept|dismiss; trigger is a "
                  "selector to click that raises the dialog.")
async def expect_dialog(action: str = "accept", expected_text: str | None = None,
                        trigger: str | None = None, accept_text: str | None = None) -> dict:
    session = await get_session()
    page = session.page

    if trigger is None:
        return {"passed": False, "error": "provide 'trigger' selector that raises the dialog"}

    # Normalize so "Accept"/"ACCEPT" don't silently fall through to dismiss.
    act = (action or "accept").strip().lower()
    if act not in ("accept", "dismiss"):
        return {"passed": False, "error": f"action must be accept|dismiss, got {action!r}"}

    locator, _ = await resolve(session.root, trigger)
    captured: dict = {}

    async def handler(dialog) -> None:
        captured["type"] = dialog.type
        captured["message"] = dialog.message
        try:
            if act == "accept":
                await (dialog.accept(accept_text) if accept_text is not None
                       else dialog.accept())
            else:
                await dialog.dismiss()
        except Exception:
            pass

    # One-shot handler avoids the expect_event deadlock (click blocks until the
    # dialog is handled, so the handler must run *during* the click).
    page.once("dialog", handler)
    try:
        await locator.click(timeout=CONFIG.selector_timeout_ms)
        await page.wait_for_timeout(50)  # let the handler settle
    except Exception as exc:
        if not captured:
            try:
                page.remove_listener("dialog", handler)
            except Exception:
                pass
            return {"passed": False, "dialog_type": None, "message": None,
                    "error": f"trigger failed ({type(exc).__name__})"}

    if not captured:
        try:
            page.remove_listener("dialog", handler)
        except Exception:
            pass
        return {"passed": False, "dialog_type": None, "message": None,
                "error": "no dialog appeared"}

    passed = expected_text is None or (expected_text in (captured.get("message") or ""))
    return {"passed": passed, "dialog_type": captured.get("type"),
            "message": captured.get("message"), "handled": act}
