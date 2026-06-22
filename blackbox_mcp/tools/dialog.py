"""CT-10: expect_dialog — stub (Phase 4).

Arms a handler / page.expect_event("dialog"), verifies message()/type(), then
accept(prompt_text)/dismiss(). Missing dialog within timeout => passed=False.
A dialog must always be accepted/dismissed or the page freezes.
"""
from __future__ import annotations

from ._registry import tool


@tool(description="Wait for the next browser dialog (alert/confirm/prompt/beforeunload), "
                  "verify its text, and accept or dismiss it.")
async def expect_dialog(action: str, expected_text: str | None = None) -> dict:
    raise NotImplementedError("expect_dialog lands in Phase 4.")
