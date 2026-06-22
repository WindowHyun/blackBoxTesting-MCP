"""CT-04: interact — click/type/hover/select/press via the D2 selector chain."""
from __future__ import annotations

from ..browser import get_session
from ..browser.locator import locate
from ..testing.secrets import resolve
from ._registry import tool

_ACTIONS = {"click", "type", "hover", "select", "press"}


@tool(description="Perform a UI action: action ∈ click|type|hover|select|press. "
                  "selector uses the priority chain testid= / role= / text= / css=. "
                  "value is required for type/select/press.")
async def interact(action: str, selector: str, value: str | None = None) -> dict:
    if action not in _ACTIONS:
        return {"ok": False, "action": action, "selector": selector,
                "detail": f"unknown action; expected one of {sorted(_ACTIONS)}"}

    session = await get_session()
    locator = locate(session.root, selector)
    resolved = resolve(value) if value is not None else None

    if action == "click":
        await locator.click()
        detail = "clicked"
    elif action == "hover":
        await locator.hover()
        detail = "hovered"
    elif action == "type":
        await locator.fill(resolved or "")
        detail = "typed"
    elif action == "select":
        await locator.select_option(resolved)
        detail = f"selected {resolved}"
    else:  # press
        await locator.press(resolved or "")
        detail = f"pressed {resolved}"

    return {"ok": True, "action": action, "selector": selector, "detail": detail}
