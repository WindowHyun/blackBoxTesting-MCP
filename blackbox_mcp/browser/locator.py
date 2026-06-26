"""Selector resolution with the D2 fallback chain.

Priority (PRD decision D2):
  1. data-testid
  2. role + accessible name
  3. visible text
  4. CSS (last resort)

Callers pass a selector string that may carry an explicit prefix to force a
strategy, otherwise it is inferred:

    testid=submit            -> [data-testid="submit"]
    role=button name=로그인   -> get_by_role("button", name="로그인")
    text=다음                 -> get_by_text("다음")
    css=.btn.primary         -> CSS
    .btn / #id / div > a     -> inferred CSS (contains . # [ > etc.)
    로그인                    -> inferred role/text

Returns a Playwright Locator scoped to ``root`` (page or frame locator).
"""
from __future__ import annotations

import re

# CSS-looking: contains selector punctuation AND no whitespace (sentences with a
# trailing '.' shouldn't be mistaken for CSS).
_CSS_PUNCT = re.compile(r"[.#\[\]>]")


def _parse_role(rest: str) -> tuple[str, str | None]:
    """Parse 'button name=로그인' -> ('button', '로그인')."""
    m = re.match(r"\s*(\S+)\s*(?:name=(.+))?$", rest)
    if not m:
        return rest.strip(), None
    role = m.group(1)
    name = m.group(2).strip() if m.group(2) else None
    # Allow quoted names.
    if name and len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
        name = name[1:-1]
    return role, name


def _looks_like_css(s: str) -> bool:
    return bool(_CSS_PUNCT.search(s)) and not any(c.isspace() for c in s)


def _testid_selector(value: str) -> str:
    # escape quotes/backslashes so a testid with a quote doesn't break the CSS
    safe = value.strip().replace("\\", "\\\\").replace('"', '\\"')
    return f'[data-testid="{safe}"]'


def locate(root, selector: str):
    """Synchronous single-strategy resolution (explicit prefix or inference).

    Used where one deterministic strategy is fine. For the full fallback chain
    with which-strategy reporting, use ``resolve`` (async).
    """
    s = selector.strip()

    if s.startswith("testid="):
        return root.locator(_testid_selector(s[len("testid="):]))
    if s.startswith("role="):
        role, name = _parse_role(s[len("role="):])
        return root.get_by_role(role, name=name) if name else root.get_by_role(role)
    if s.startswith("text="):
        return root.get_by_text(s[len("text="):].strip())
    if s.startswith("css="):
        return root.locator(s[len("css="):].strip())

    if _looks_like_css(s):
        return root.locator(s)
    return root.get_by_text(s)


async def resolve(root, selector: str):
    """Resolve ``selector`` to ``(locator, resolved_by)`` using the D2 chain.

    Explicit prefixes (testid=/role=/text=/css=) pick that strategy directly.
    A bare, CSS-looking string is treated as CSS. A bare plain string tries the
    D2 order — data-testid → visible text — and returns the first strategy that
    matches at least one element (falling back to text so errors are sensible).
    ``resolved_by`` records which strategy won (feeds SM-06 report transparency).
    """
    s = selector.strip()

    if s.startswith("testid="):
        return root.locator(_testid_selector(s[len("testid="):])), "testid"
    if s.startswith("role="):
        role, name = _parse_role(s[len("role="):])
        loc = root.get_by_role(role, name=name) if name else root.get_by_role(role)
        return loc, "role"
    if s.startswith("text="):
        return root.get_by_text(s[len("text="):].strip()), "text"
    if s.startswith("css="):
        return root.locator(s[len("css="):].strip()), "css"

    if _looks_like_css(s):
        return root.locator(s), "css"

    # Bare plain string: try the chain in D2 priority, pick first with a match.
    candidates = [
        ("testid", root.locator(_testid_selector(s))),
        ("text", root.get_by_text(s)),
    ]
    for name, loc in candidates:
        try:
            if await loc.count() > 0:
                return loc, name
        except Exception:
            continue
    return root.get_by_text(s), "text"

