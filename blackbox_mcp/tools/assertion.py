"""CT-05: assert_ — five verification kinds.

Exposed to MCP as the tool name 'assert_' (assert is a Python keyword).
"""
from __future__ import annotations

from typing import Literal

from ..browser import get_session
from ..browser.locator import resolve, resolve_count_population
from ._registry import tool

_KINDS = {"text_visible", "element_visible", "url_is", "url_contains", "count"}
Kind = Literal["text_visible", "element_visible", "url_is", "url_contains", "count"]


@tool(name="assert_",
      description="Assert a condition. kind ∈ text_visible|element_visible|url_is|"
                  "url_contains|count. target is text/selector/url; expected used "
                  "by count (a number — accepts 3 or \"3\").")
async def assert_(kind: Kind, target: str, expected: str | int | None = None) -> dict:
    if kind not in _KINDS:
        return {"passed": False, "kind": kind, "target": target,
                "expected": expected, "actual": f"unknown kind; expected {sorted(_KINDS)}"}

    session = await get_session()
    root = session.root
    passed = False
    actual: object = None

    if kind == "text_visible":
        # "visible somewhere": a VISIBLE match must exist. filter(visible=True)
        # (not .first.is_visible()) so a hidden first match doesn't mask a
        # visible later one — and so this agrees with element_visible on the
        # same page instead of contradicting it.
        loc = root.get_by_text(target)
        actual = await loc.filter(visible=True).count() > 0
        passed = bool(actual)
    elif kind == "element_visible":
        # Full D2 chain, probed for VISIBLE matches: "#form input" resolves as
        # CSS, visible text like "Order #123" lands on the text tier, and a
        # hidden testid that shares the asserted text can't win a tier and
        # shadow the visible match behind it.
        loc, _ = await resolve(root, target, visible_only=True)
        actual = await loc.filter(visible=True).count() > 0
        passed = bool(actual)
    elif kind == "url_is":
        actual = session.page.url
        passed = actual == target
    elif kind == "url_contains":
        url = session.page.url
        actual = url
        passed = target in url
    elif kind == "count":
        # count's verdict depends on WHICH population is counted — see
        # resolve_count_population: selectors count their strategy, everything
        # else counts text matches, and a colliding testid/role name never
        # silently switches the population.
        loc, _ = await resolve_count_population(root, target)
        actual = await loc.count()
        try:
            passed = expected is not None and actual == int(expected)
        except (TypeError, ValueError):
            passed = False
            actual = f"{actual} (expected not an int: {expected!r})"

    return {"passed": passed, "kind": kind, "target": target,
            "expected": expected, "actual": actual}
