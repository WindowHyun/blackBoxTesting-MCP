"""CT-04: interact — UI actions via the D2 selector chain."""
from __future__ import annotations

import os

from ..browser import get_session
from ..browser.locator import resolve
from ..config import CONFIG
from ..testing.secrets import is_sensitive_name, mask_value, resolve as resolve_env, scrub
from ._registry import tool

# Actions needing no value.
_NO_VALUE = {"click", "dblclick", "hover", "check", "uncheck", "focus",
             "clear", "scroll_into_view"}
# Actions requiring a value.
_NEEDS_VALUE = {"type", "select", "press", "upload"}
_ACTIONS = _NO_VALUE | _NEEDS_VALUE


def _display_value(selector: str, action: str, value: str | None) -> str | None:
    """What to echo back for ``value`` in results and reports.

    Masking used to be unconditional, which turned every step into
    "selected ***" / "pressed ***" and made reports unreadable — the reviewer
    could not tell which option was chosen. Mask only what is actually
    sensitive: a credential-looking target field, or a value that came from a
    resolved ${SECRET} (scrub swaps those back to their placeholder).
    """
    if not value:
        return value
    if is_sensitive_name(selector) or is_sensitive_name(action):
        return mask_value(value)
    return scrub(value)


def _upload_paths(value: str) -> tuple[list[str], str | None]:
    """Split a comma-separated file list and verify each path exists."""
    paths = [p.strip() for p in value.split(",") if p.strip()]
    if not paths:
        return [], "no file path given"
    expanded = [os.path.expanduser(p) for p in paths]
    missing = [p for p in expanded if not os.path.isfile(p)]
    if missing:
        return [], f"file(s) not found: {', '.join(missing)}"
    return expanded, None


@tool(description="Perform a UI action: action ∈ click|dblclick|type|hover|select|"
                  "press|check|uncheck|clear|focus|scroll_into_view|upload. "
                  "selector uses the priority chain testid= / role= / text= / css=. "
                  "value is required for type/select/press/upload (upload takes one "
                  "or more comma-separated local file paths).")
async def interact(action: str, selector: str, value: str | None = None) -> dict:
    if action not in _ACTIONS:
        return {"ok": False, "action": action, "selector": selector,
                "detail": f"unknown action; expected one of {sorted(_ACTIONS)}"}
    if action in _NEEDS_VALUE and value is None:
        return {"ok": False, "action": action, "selector": selector,
                "error": f"'{action}' requires a value"}

    session = await get_session()
    locator, resolved_by = await resolve(session.root, selector)
    value_resolved = resolve_env(value) if value is not None else None
    value_shown = _display_value(selector, action, value_resolved)

    t = CONFIG.selector_timeout_ms
    try:
        if action == "click":
            await locator.click(timeout=t)
            detail = "clicked"
        elif action == "dblclick":
            await locator.dblclick(timeout=t)
            detail = "double-clicked"
        elif action == "hover":
            await locator.hover(timeout=t)
            detail = "hovered"
        elif action == "focus":
            await locator.focus(timeout=t)
            detail = "focused"
        elif action == "check":
            await locator.check(timeout=t)
            detail = "checked"
        elif action == "uncheck":
            await locator.uncheck(timeout=t)
            detail = "unchecked"
        elif action == "clear":
            await locator.clear(timeout=t)
            detail = "cleared"
        elif action == "scroll_into_view":
            await locator.scroll_into_view_if_needed(timeout=t)
            detail = "scrolled into view"
        elif action == "type":
            await locator.fill(value_resolved or "", timeout=t)
            detail = "typed"
        elif action == "select":
            # A bare string matches by value OR label, so "부산" and "v2" both
            # work on <option value="v2">부산</option> — QA writes what it sees.
            await locator.select_option(value_resolved, timeout=t)
            detail = f"selected {value_shown}"
        elif action == "upload":
            paths, err = _upload_paths(value_resolved or "")
            if err:
                return {"ok": False, "action": action, "selector": selector,
                        "resolved_by": resolved_by, "error": err}
            await locator.set_input_files(paths, timeout=t)
            detail = f"uploaded {len(paths)} file(s): " + ", ".join(
                os.path.basename(p) for p in paths)
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
