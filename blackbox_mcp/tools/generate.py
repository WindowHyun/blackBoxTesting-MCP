"""SL-01: generate_scenario — authoring kit (+ optional sampling).

The MCP server has no LLM. So this tool navigates + inspects the page and returns
a deterministic "authoring kit": the interactive elements with D2-resolved stable
selectors, the step JSON schema, and a worked example. Claude (the host) composes
the actual steps from the kit + the natural-language description, then calls
save_scenario.

If the client supports MCP sampling, the tool can additionally generate the steps
server-side via ctx.session.create_message and return them ready-to-run, falling
back to the kit when sampling is unavailable (Claude Desktop does not support it).
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import Context

from ..browser import get_session
from ..tools.navigate import navigate
from ._registry import tool

# Roles implied by tag/type, used to suggest a role-based selector.
_TAG_ROLE = {"button": "button", "a": "link", "select": "combobox", "textarea": "textbox"}

_COLLECT_JS = """
() => {
  const sel = 'button, a[href], input, select, textarea, [role=button], [role=link], [role=textbox]';
  return [...document.querySelectorAll(sel)].slice(0, 100).map(el => {
    const name = (el.getAttribute('aria-label') || el.textContent ||
                  el.getAttribute('placeholder') || el.value || '').trim().slice(0, 60);
    return {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || null,
      role: el.getAttribute('role') || null,
      testid: el.getAttribute('data-testid') || null,
      id: el.id || null,
      name: name,
    };
  });
}
"""

_STEP_SCHEMA = {
    "navigate": {"action": "navigate", "url": "<url>", "wait_until": "load"},
    "interact": {"action": "interact", "type": "click|type|hover|select|press",
                 "selector": "<D2 selector>", "value": "<for type/select/press>"},
    "assert": {"action": "assert", "kind": "text_visible|element_visible|url_is|"
                                           "url_contains|count", "target": "<...>",
               "expected": "<for count>"},
}


def _suggest_selector(el: dict) -> str:
    if el.get("testid"):
        return f"testid={el['testid']}"
    role = el.get("role") or _TAG_ROLE.get(el.get("tag"))
    if el.get("tag") == "input":
        role = "textbox"
    if role and el.get("name"):
        return f"role={role} name={el['name']}"
    if el.get("name"):
        return f"text={el['name']}"
    if el.get("id"):
        return f"css=#{el['id']}"
    return f"css={el.get('tag')}"


async def _try_sampling(ctx, description: str, kit: dict):
    """Best-effort server-side generation via MCP sampling; None on any failure."""
    try:
        from mcp.types import SamplingMessage, TextContent
    except Exception:
        return None
    prompt = (
        "You are generating a UI test scenario. Using ONLY the page kit below, "
        "return a JSON array of steps (no prose) that accomplishes this goal.\n"
        f"GOAL: {description}\n\nKIT:\n{json.dumps(kit, ensure_ascii=False)}"
    )
    try:
        res = await ctx.session.create_message(
            messages=[SamplingMessage(role="user",
                                      content=TextContent(type="text", text=prompt))],
            max_tokens=1200,
        )
        text = getattr(res.content, "text", "") or ""
        start, end = text.find("["), text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
    except Exception:
        return None
    return None


@tool(description="Inspect a page for a natural-language test goal and return an "
                  "authoring kit (interactive elements + D2-resolved selectors + step "
                  "schema + example) for composing a scenario. If the client supports "
                  "sampling, also returns generated steps.")
async def generate_scenario(description: str, url: str,
                            ctx: Context | None = None) -> dict:
    session = await get_session()
    await navigate(url)
    raw = await session.page.evaluate(_COLLECT_JS)

    elements = []
    for el in raw:
        if not (el.get("name") or el.get("testid") or el.get("id")):
            continue
        elements.append({**el, "suggested_selector": _suggest_selector(el)})

    kit = {
        "description": description,
        "url": url,
        "interactive_elements": elements,
        "step_schema": _STEP_SCHEMA,
        "example": [
            {"action": "navigate", "url": url, "wait_until": "load"},
            {"action": "interact", "type": "type", "selector": "testid=email", "value": "u@x.com"},
            {"action": "interact", "type": "click", "selector": "role=button name=로그인"},
            {"action": "assert", "kind": "url_contains", "target": "/dashboard"},
        ],
        "instructions": "Compose a steps[] array using suggested_selector values, "
                        "then call save_scenario(name, steps).",
    }

    if ctx is not None:
        steps = await _try_sampling(ctx, description, kit)
        if steps:
            return {"mode": "generated", "steps": steps, "kit": kit}

    return {"mode": "kit", "kit": kit}
