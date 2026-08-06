"""CT-05: assert_ — verification kinds.

Exposed to MCP as the tool name 'assert_' (assert is a Python keyword).

Two things beyond the original five kinds:

*Ordering.* ``text_sequence`` / ``order_asc`` / ``order_desc`` verify the
ORDER of a matched set. Without them a sort control that accepts the click,
fires ``change`` and reorders nothing looks perfectly healthy — the elements
are all still there, just in the wrong sequence.

*A presence probe on failure.* When an assertion does not hold, the result
carries whether the target exists in the DOM at all. That single fact is what
separates "the element was renamed" (absent → the test may be updated) from
"the element is right there but no longer behaves" (present → the app changed;
rewriting the assertion would delete the finding). See testing/diagnose.py.
"""
from __future__ import annotations

import re

from ..browser import get_session
from ..browser.locator import resolve, resolve_count_population
from ._registry import tool

_KINDS = {"text_visible", "element_visible", "url_is", "url_contains", "count",
          "text_sequence", "order_asc", "order_desc"}

# Kinds whose target is a URL/text rather than an element — no probe applies.
_NON_ELEMENT = {"url_is", "url_contains"}

_MAX_SEQUENCE = 50
# Leading currency/symbols and thousands separators, so "$1,299.00" sorts as a
# number instead of lexicographically after "$29.99".
_NUMERIC = re.compile(r"^\s*[^\d\-+]*([-+]?\d[\d,]*\.?\d*)\s*\D*$")


def _as_number(text: str) -> float | None:
    m = _NUMERIC.match(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


async def _texts(root, target: str) -> tuple[list[str], str | None]:
    """Ordered visible texts of everything the target matches."""
    loc, resolved_by = await resolve_count_population(root, target)
    raw = await loc.all_inner_texts()
    cleaned = [" ".join(t.split()) for t in raw[:_MAX_SEQUENCE]]
    return [t for t in cleaned if t], resolved_by


def _is_sorted(values: list, descending: bool) -> bool:
    pairs = zip(values, values[1:])
    return all(a >= b for a, b in pairs) if descending else all(a <= b for a, b in pairs)


async def _probe(root, target: str) -> dict:
    """Does the target exist at all, and is any of it visible?

    Deliberately counts hidden matches too: an element that is present but
    hidden (a badge that never un-hid) is the exact case that must NOT read as
    "renamed". Failure to probe returns None rather than a guess.
    """
    try:
        loc, _ = await resolve_count_population(root, target)
        total = await loc.count()
        visible = await loc.filter(visible=True).count() if total else 0
        return {"element_present": total > 0, "element_count": total,
                "visible_count": visible}
    except Exception:
        return {"element_present": None, "element_count": None,
                "visible_count": None}


@tool(name="assert_",
      description="Assert a condition. kind ∈ text_visible|element_visible|url_is|"
                  "url_contains|count|text_sequence|order_asc|order_desc. "
                  "target is text/selector/url. expected: a number for count; a "
                  "comma-separated list for text_sequence (the matched elements' "
                  "texts, in order); optional 'numeric'|'text' for order_asc/"
                  "order_desc (default: auto — numbers if every value parses as "
                  "one). Ordering kinds are how you verify a sort control actually "
                  "sorted rather than merely accepting the click.")
async def assert_(kind: str, target: str, expected: str | None = None) -> dict:
    if kind not in _KINDS:
        return {"passed": False, "kind": kind, "target": target,
                "expected": expected, "actual": f"unknown kind; expected {sorted(_KINDS)}"}

    session = await get_session()
    root = session.root
    passed = False
    actual: object = None
    extra: dict = {}

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
    elif kind == "text_sequence":
        texts, resolved_by = await _texts(root, target)
        wanted = [t.strip() for t in (expected or "").split(",") if t.strip()]
        extra["resolved_by"] = resolved_by
        if not wanted:
            passed, actual = False, "expected가 비었다 — 쉼표로 구분된 순서 목록이 필요"
        else:
            # Prefix comparison: asserting the first N of a longer list is the
            # common case ("cheapest three first"), and demanding the whole
            # page's order would make the assertion brittle for no gain.
            head = texts[:len(wanted)]
            passed = head == wanted
            actual = " | ".join(head) if head else "(매치 없음)"
    elif kind in ("order_asc", "order_desc"):
        texts, resolved_by = await _texts(root, target)
        extra["resolved_by"] = resolved_by
        mode = (expected or "auto").strip().lower()
        numbers = [_as_number(t) for t in texts]
        use_numeric = (mode == "numeric" or
                       (mode in ("auto", "") and texts and all(n is not None
                                                               for n in numbers)))
        if not texts:
            passed, actual = False, "(매치 없음)"
        elif use_numeric and any(n is None for n in numbers):
            passed = False
            actual = f"숫자로 읽을 수 없는 값: {[t for t, n in zip(texts, numbers) if n is None][:3]}"
        else:
            values = numbers if use_numeric else texts
            passed = _is_sorted(values, descending=(kind == "order_desc"))
            actual = " | ".join(texts[:10]) + ("…" if len(texts) > 10 else "")
            extra["compared_as"] = "numeric" if use_numeric else "text"

    result = {"passed": passed, "kind": kind, "target": target,
              "expected": expected, "actual": actual, **extra}

    # Presence probe, only when it can mean something: a failed element-based
    # assertion. This is what lets the classifier tell a rename from a
    # behaviour change instead of guessing.
    if not passed and kind not in _NON_ELEMENT:
        result["probe"] = await _probe(root, target)
    return result
