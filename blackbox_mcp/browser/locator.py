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
    .btn / #id / div>a       -> inferred CSS (structural signal, no whitespace)
    #form input / div > a    -> CSS signal with whitespace: resolve() probes it
                                as CSS first, then the bare-string chain — so
                                text like "Order #123" or "A > B" still lands
                                on the text tier when it matches nothing as CSS.
                                locate() (sync, can't probe) treats it as text.
    로그인                    -> inferred role/text

Returns a Playwright Locator scoped to ``root`` (page or frame locator).
"""
from __future__ import annotations

import re

# CSS only on UNAMBIGUOUS structural signals: an id (#), attribute ([..]), a
# combinator (>), or a leading class dot (.btn). A dotted word like a domain
# (example.com) or version (v1.2) is visible text, NOT a CSS selector — coercing
# it to CSS made bare text silently mis-target on real pages.
_CSS_STRONG = re.compile(r"[#\[\]>]|^\.")

# Common interactive roles tried (by accessible name) for a bare string — this
# is D2 priority #2 (role+name), which used to be skipped in the bare path.
_COMMON_ROLES = ("button", "link", "textbox", "checkbox", "radio",
                 "combobox", "tab", "menuitem", "option", "heading")


def _parse_role(rest: str) -> tuple[str, str | None]:
    """Parse 'button name=로그인' -> ('button', '로그인').

    A remainder without the name= prefix is still treated as the accessible
    name ('button submit' -> ('button', 'submit')) rather than degrading the
    whole string into a bogus role that Playwright rejects with a type error.
    """
    parts = rest.strip().split(None, 1)
    if not parts:
        return "", None
    role, name = parts[0], None
    if len(parts) == 2:
        tail = parts[1].strip()
        name = tail[len("name="):].strip() if tail.startswith("name=") else tail
    # Allow quoted names.
    if name and len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
        name = name[1:-1]
    return role, name or None


def _looks_like_css(s: str) -> bool:
    return bool(_CSS_STRONG.search(s)) and not any(c.isspace() for c in s)


def is_selector_like(s: str) -> bool:
    """True when the string is unambiguously a *selector* (explicit prefix or a
    structural CSS signal) rather than possibly-visible text. Callers whose
    semantics differ for text vs selectors (e.g. assert count) branch on this."""
    s = s.strip()
    return (s.startswith(("testid=", "role=", "text=", "css="))
            or bool(_CSS_STRONG.search(s)))


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

    # Sync path can't count-probe, so stay conservative: a structural signal
    # WITH whitespace is ambiguous ("#form input" is CSS, but "[필수] 약관" or
    # "Order #123" is visible text) — treat as text, like before. Async callers
    # that need the disambiguation use resolve(), which probes CSS first.
    if _looks_like_css(s):
        return root.locator(s)
    return root.get_by_text(s)


async def resolve(root, selector: str, *, visible_only: bool = False):
    """Resolve ``selector`` to ``(locator, resolved_by)`` using the D2 chain.

    Explicit prefixes (testid=/role=/text=/css=) pick that strategy directly.
    A bare, CSS-looking string is treated as CSS. A bare plain string tries the
    full D2 order — data-testid → role+name → visible text — and returns the
    first strategy that matches at least one element (falling back to text so
    errors are sensible). ``resolved_by`` records which strategy won (SM-06).

    ``visible_only=True`` makes the bare-string chain probe with
    ``filter(visible=True)`` — a *hidden* element (skeleton/template node whose
    data-testid happens to equal the asserted text) must not win a tier and
    shadow a visible match in a later tier. The returned locator is unfiltered;
    callers that need only visible matches apply their own filter.
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
    #   0) CSS, when the string carries a structural signal but has whitespace
    #      ("#form input", "div > a") — count-probed, so visible text that
    #      merely contains '>' still falls through to the text tier
    #   1) data-testid  2) role+name (common interactive roles)  3) visible text
    candidates = []
    if _CSS_STRONG.search(s):
        candidates.append(("css", root.locator(s)))
    candidates.append(("testid", root.locator(_testid_selector(s))))
    for r in _COMMON_ROLES:
        candidates.append((f"role={r}", root.get_by_role(r, name=s)))
    candidates.append(("text", root.get_by_text(s)))
    for name, loc in candidates:
        try:
            probe = loc.filter(visible=True) if visible_only else loc
            if await probe.count() > 0:
                return loc, name
        except Exception:
            continue
    return root.get_by_text(s), "text"

