"""CT-05: assert_ — targeted verification kinds plus site-agnostic health kinds.

Exposed to MCP as the tool name 'assert_' (assert is a Python keyword).

Two families live here:

- **Targeted** (text_visible, element_visible, url_is, url_contains, count) need
  a ``target`` and therefore knowledge of the page's markup.
- **Health** (page_rendered, no_js_errors, no_console_errors,
  no_failed_requests, no_broken_images) take no target: they read the event
  buffers and the DOM's own load state, so the same check runs against any site
  without authoring. These are what `ui-blackbox smoke` is built from, but they
  are ordinary assert kinds — hand-written scenarios can use them too.
"""
from __future__ import annotations

import re

from ..browser import get_session
from ..browser.locator import resolve, resolve_count_population
from ._registry import tool

_TARGETED_KINDS = {"text_visible", "element_visible", "url_is", "url_contains", "count"}
# No target: evaluated against the session's event buffers / the DOM itself.
HEALTH_KINDS = ("page_rendered", "no_js_errors", "no_console_errors",
                "no_failed_requests", "no_broken_images")
_KINDS = _TARGETED_KINDS | set(HEALTH_KINDS)

# A page is "blank" past this floor only if nothing paints at all — kept
# deliberately low so a legitimately sparse page (a redirect stub, a login
# form) is not called broken.
_RENDER_JS = """
() => {
  const b = document.body;
  if (!b) return {body: false, text: 0, elements: 0, painted: 0, media: 0};
  const all = [...b.querySelectorAll('*')];
  const painted = all.filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  const media = painted.filter(el =>
    ['IMG', 'SVG', 'CANVAS', 'VIDEO', 'PICTURE'].includes(el.tagName));
  return {body: true, text: (b.innerText || '').trim().length,
          elements: all.length, painted: painted.length, media: media.length};
}
"""

# `complete && naturalWidth === 0` is the only reliable "this <img> failed"
# signal: a still-loading or lazy offscreen image reports complete === false
# and is therefore not counted.
_BROKEN_IMG_JS = """
() => [...document.images]
  .filter(im => im.complete && im.naturalWidth === 0 && (im.currentSrc || im.src))
  .map(im => im.currentSrc || im.src)
  .slice(0, 20)
"""


def _ignored(value: str | None, patterns: list[str]) -> bool:
    """True when a URL/location matches any caller-supplied ignore regex.

    Real sites are noisy in ways that say nothing about the app under test
    (analytics beacons 4xx-ing, third-party ad scripts throwing). Without a
    suppression hook the health kinds would be unusable on "any site" — the
    point of them — so callers pass patterns instead of disabling the check."""
    if not value or not patterns:
        return False
    return any(re.search(p, value) for p in patterns)


async def assert_health(kind: str, marks: dict | None = None,
                        ignore: list[str] | None = None) -> dict:
    """Evaluate a site-agnostic health kind.

    ``marks`` scopes the buffer slice to the current page: the runner records
    the buffer lengths at the last navigate step, so a crawl of five pages
    attributes each error to the page that produced it rather than blaming
    every page for the first one's exception. Omitted (the MCP path) means
    "everything buffered in this session"."""
    session = await get_session()
    buf = session.buffers
    m = marks or {}
    pats = ignore or []
    detail: object
    passed = False

    if kind == "no_js_errors":
        hits = [c for c in buf.console[m.get("console", 0):]
                if c.source == "pageerror" and not _ignored(c.location, pats)]
        passed = not hits
        detail = ("없음" if passed else
                  f"{len(hits)}건: " + " | ".join(c.text[:120] for c in hits[:5]))
    elif kind == "no_console_errors":
        # Disjoint from no_js_errors on purpose: one uncaught exception should
        # fail one check, not two, so the report points at a single cause.
        hits = [c for c in buf.console[m.get("console", 0):]
                if c.level == "error" and c.source == "console"
                and not _ignored(c.location, pats)]
        passed = not hits
        detail = ("없음" if passed else
                  f"{len(hits)}건: " + " | ".join(c.text[:120] for c in hits[:5]))
    elif kind == "no_failed_requests":
        bad = [n for n in buf.network[m.get("network", 0):]
               if ((n.status or 0) >= 400 or n.failure) and not _ignored(n.url, pats)]
        passed = not bad
        detail = ("없음" if passed else
                  f"{len(bad)}건: " + " | ".join(
                      f"{n.status or n.failure} {n.url[:100]}" for n in bad[:5]))
    elif kind == "page_rendered":
        info = await session.page.evaluate(_RENDER_JS)
        # Painted box + (text or media): catches the white-screen SPA crash
        # without failing an image-only or text-only page.
        passed = bool(info.get("body") and info.get("painted")
                      and (info.get("text") or info.get("media")))
        detail = (f"elements={info.get('elements')} painted={info.get('painted')} "
                  f"text={info.get('text')} media={info.get('media')}")
    elif kind == "no_broken_images":
        broken = [u for u in await session.page.evaluate(_BROKEN_IMG_JS)
                  if not _ignored(u, pats)]
        passed = not broken
        detail = ("없음" if passed else
                  f"{len(broken)}건: " + " | ".join(u[:100] for u in broken[:5]))
    else:
        detail = f"unknown health kind; expected {sorted(HEALTH_KINDS)}"

    return {"passed": passed, "kind": kind, "target": None,
            "expected": kind, "actual": detail}


@tool(name="assert_",
      description="Assert a condition. Targeted kinds (need target): text_visible|"
                  "element_visible|url_is|url_contains|count. Site-agnostic health "
                  "kinds (no target): page_rendered|no_js_errors|no_console_errors|"
                  "no_failed_requests|no_broken_images. expected is used by count.")
async def assert_(kind: str, target: str | None = None,
                  expected: str | None = None) -> dict:
    if kind in HEALTH_KINDS:
        return await assert_health(kind)
    if kind not in _KINDS:
        return {"passed": False, "kind": kind, "target": target,
                "expected": expected, "actual": f"unknown kind; expected {sorted(_KINDS)}"}
    if target is None:
        return {"passed": False, "kind": kind, "target": None, "expected": expected,
                "actual": f"kind '{kind}' requires a target"}

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
