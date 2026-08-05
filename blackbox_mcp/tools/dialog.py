"""CT-10: expect_dialog — wait for a browser dialog, verify text, accept/dismiss.
Plus get_dialogs — every dialog the page raised, expected or not.

A dialog (alert/confirm/prompt/beforeunload) blocks JS until handled. The
session installs an always-on recorder (browser/listeners.attach) that logs
every dialog and dismisses the ones nobody asked for — so an unexpected alert
on page load is visible instead of silently auto-dismissed by Playwright.

expect_dialog does NOT register its own listener. It installs a one-shot
*override* in the shared buffers for the duration of the triggering action:
Playwright runs every registered listener, so a second listener would race the
recorder and the recorder (registered first) would dismiss the dialog before
this tool could accept it.

Usage:
- ``trigger`` (a selector) is clicked inside the armed window; the dialog is
  captured, ``expected_text`` verified, and accept()/dismiss() applied.
- ``action`` ∈ accept | dismiss. ``accept_text`` fills a prompt on accept.
- If no dialog appears within the timeout, returns passed=False.
"""
from __future__ import annotations

import time

from ..browser import get_session
from ..browser.listeners import DialogEntry
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
        handled = act
        try:
            if act == "accept":
                await (dialog.accept(accept_text) if accept_text is not None
                       else dialog.accept())
            else:
                await dialog.dismiss()
        except Exception:
            handled = "unhandled"
        # Log it like any other dialog, flagged as one we were waiting for.
        session.buffers.add_dialog(DialogEntry(
            type=dialog.type, message=dialog.message, handled=handled,
            expected=True, ts=time.time()))

    session.buffers.dialog_handler = handler
    try:
        try:
            await locator.click(timeout=CONFIG.selector_timeout_ms)
            await page.wait_for_timeout(50)  # let the handler settle
        except Exception as exc:
            if not captured:
                return {"passed": False, "dialog_type": None, "message": None,
                        "error": f"trigger failed ({type(exc).__name__})"}
    finally:
        # Always hand control back to the always-on recorder, even if the click
        # raised — a leaked override would swallow every later dialog.
        session.buffers.dialog_handler = None

    if not captured:
        return {"passed": False, "dialog_type": None, "message": None,
                "error": "no dialog appeared"}

    passed = expected_text is None or (expected_text in (captured.get("message") or ""))
    return {"passed": passed, "dialog_type": captured.get("type"),
            "message": captured.get("message"), "handled": act}


@tool(description="List every native dialog (alert/confirm/prompt/beforeunload) the "
                  "page raised since the last reset, including UNEXPECTED ones that "
                  "were auto-dismissed. expected=false marks a dialog no expect_dialog "
                  "was armed for — usually a bug or a missed step.")
async def get_dialogs(unexpected_only: bool = False) -> list[dict]:
    session = await get_session()
    return [d.__dict__ for d in session.buffers.dialogs
            if not unexpected_only or not d.expected]
