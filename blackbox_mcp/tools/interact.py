"""CT-04: interact — click/type/hover/select/press via the D2 selector chain."""
from __future__ import annotations

from typing import Literal

from ..browser import get_session
from ..browser.locator import resolve
from ..config import CONFIG
from ..testing.secrets import mask_value, resolve as resolve_env, scrub
from ._registry import tool

_ACTIONS = {"click", "type", "hover", "select", "press"}
Action = Literal["click", "type", "hover", "select", "press"]


@tool(description="Perform a UI action: action ∈ click|type|hover|select|press. "
                  "selector uses the priority chain testid= / role= / text= / css=. "
                  "value is required for type/select/press.")
async def interact(action: Action, selector: str, value: str | None = None) -> dict:
    if action not in _ACTIONS:
        return {"ok": False, "action": action, "selector": selector,
                "detail": f"unknown action; expected one of {sorted(_ACTIONS)}"}
    if action in ("type", "select", "press") and value is None:
        return {"ok": False, "action": action, "selector": selector,
                "error": f"'{action}' requires a value"}

    session = await get_session()
    locator, resolved_by = await resolve(session.root, selector)
    value_resolved = resolve_env(value) if value is not None else None
    # never echo secrets back in the result detail
    value_shown = mask_value(value_resolved) if value_resolved else value_resolved

    t = CONFIG.selector_timeout_ms
    try:
        if action == "click":
            await locator.click(timeout=t)
            detail = "clicked"
        elif action == "hover":
            await locator.hover(timeout=t)
            detail = "hovered"
        elif action == "type":
            await locator.fill(value_resolved or "", timeout=t)
            detail = "typed"
        elif action == "select":
            await locator.select_option(value_resolved, timeout=t)
            detail = f"selected {value_shown}"
        else:  # press
            await locator.press(value_resolved or "", timeout=t)
            detail = f"pressed {value_shown}"
    except Exception as exc:
        # scrub: Playwright error text can echo the awaited value (press/select)
        return {"ok": False, "action": action, "selector": selector,
                "resolved_by": resolved_by,
                "error": scrub(f"{type(exc).__name__}: {exc}")}

    return {"ok": True, "action": action, "selector": selector,
            "resolved_by": resolved_by, "detail": detail}

