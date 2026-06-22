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

_CSS_HINT = re.compile(r"[.#\[\]>]|^[a-zA-Z]+\[")


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


def locate(root, selector: str):
    """Resolve ``selector`` against ``root`` and return a Locator."""
    s = selector.strip()

    if s.startswith("testid="):
        return root.locator(f'[data-testid="{s[len("testid="):].strip()}"]')
    if s.startswith("role="):
        role, name = _parse_role(s[len("role="):])
        return root.get_by_role(role, name=name) if name else root.get_by_role(role)
    if s.startswith("text="):
        return root.get_by_text(s[len("text="):].strip())
    if s.startswith("css="):
        return root.locator(s[len("css="):].strip())

    # No prefix: infer. CSS-looking strings go to CSS; plain text to get_by_text.
    if _CSS_HINT.search(s):
        return root.locator(s)
    return root.get_by_text(s)
