"""CT-05: assert_ — five verification kinds.

Exposed to MCP as the tool name 'assert_' (assert is a Python keyword).
"""
from __future__ import annotations

from ..browser import get_session
from ..browser.locator import locate
from ._registry import tool

_KINDS = {"text_visible", "element_visible", "url_is", "url_contains", "count"}


@tool(name="assert_",
      description="Assert a condition. kind ∈ text_visible|element_visible|url_is|"
                  "url_contains|count. target is text/selector/url; expected used "
                  "by count (a number).")
async def assert_(kind: str, target: str, expected: str | None = None) -> dict:
    if kind not in _KINDS:
        return {"passed": False, "kind": kind, "target": target,
                "expected": expected, "actual": f"unknown kind; expected {sorted(_KINDS)}"}

    session = await get_session()
    root = session.root
    passed = False
    actual: object = None

    if kind == "text_visible":
        actual = await root.get_by_text(target).is_visible()
        passed = bool(actual)
    elif kind == "element_visible":
        actual = await locate(root, target).is_visible()
        passed = bool(actual)
    elif kind == "url_is":
        actual = session.page.url
        passed = actual == target
    elif kind == "url_contains":
        actual = session.page.url
        passed = target in actual
    elif kind == "count":
        actual = await locate(root, target).count()
        passed = expected is not None and actual == int(expected)

    return {"passed": passed, "kind": kind, "target": target,
            "expected": expected, "actual": actual}
