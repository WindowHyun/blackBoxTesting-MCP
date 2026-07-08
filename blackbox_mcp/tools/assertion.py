"""CT-05: assert_ — five verification kinds.

Exposed to MCP as the tool name 'assert_' (assert is a Python keyword).
"""
from __future__ import annotations

from ..browser import get_session
from ..browser.locator import resolve
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
        loc = root.get_by_text(target)
        # "visible somewhere": tolerate multiple matches (no strict-mode throw).
        actual = await loc.count() > 0 and await loc.first.is_visible()
        passed = bool(actual)
    elif kind == "element_visible":
        # Full D2 chain (count-probed): "#form input" resolves as CSS while
        # visible text like "Order #123" still lands on the text tier.
        loc, _ = await resolve(root, target)
        actual = await loc.count() > 0 and await loc.first.is_visible()
        passed = bool(actual)
    elif kind == "url_is":
        actual = session.page.url
        passed = actual == target
    elif kind == "url_contains":
        actual = session.page.url
        passed = target in actual
    elif kind == "count":
        loc, _ = await resolve(root, target)
        actual = await loc.count()
        try:
            passed = expected is not None and actual == int(expected)
        except (TypeError, ValueError):
            passed = False
            actual = f"{actual} (expected not an int: {expected!r})"

    return {"passed": passed, "kind": kind, "target": target,
            "expected": expected, "actual": actual}
