"""Site-agnostic smoke checks — point the runner at any URL, author nothing.

Every other way to drive this tool needs a scenario, and a scenario needs
selectors, and selectors are site-specific: the saucedemo suite broke on one
`data-test` value that the site had renamed. So the checks here deliberately
use **no site knowledge at all** — they read the event buffers (uncaught
exceptions, console errors, 4xx/5xx) and the DOM's own load state (did
anything paint, did the images load). That is the subset of "is this page
broken" which is true of every site, and it is worth the narrower scope
because it runs on a URL alone.

A smoke run is an ordinary scenario built on the fly, so reports, JUnit,
retention, secret scrubbing and trace-on-failure all apply unchanged.
"""
from __future__ import annotations

import re
from urllib.parse import urldefrag, urlparse

from ..tools.assertion import HEALTH_KINDS

# console.error is the noisiest signal on real sites (ads, analytics, browser
# deprecation warnings) and uncaught exceptions are already covered by
# no_js_errors — so it is opt-in via --strict rather than a default failure.
DEFAULT_CHECKS = tuple(k for k in HEALTH_KINDS if k != "no_console_errors")
STRICT_CHECKS = tuple(HEALTH_KINDS)

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def scenario_name(url: str) -> str:
    """A stable, filesystem-safe scenario name derived from the URL."""
    p = urlparse(url)
    stem = f"{p.netloc}{p.path}".strip("/") or p.netloc or "page"
    return "smoke_" + (_UNSAFE.sub("_", stem)[:80] or "page")


def smoke_steps(url: str, *, checks: tuple[str, ...] = DEFAULT_CHECKS,
                ignore: list[str] | None = None,
                screenshot: bool = True,
                expect_status: int | None = None) -> list[dict]:
    """The step list for one page.

    Ordered so the cheapest, most diagnostic check reports first: if the page
    never painted, `page_rendered` says so before a wall of console noise.
    """
    nav: dict = {"action": "navigate", "url": url, "tag": "SMOKE-LOAD",
                 "priority": "high"}
    if expect_status is not None:
        nav["expect_status"] = expect_status
    steps: list[dict] = [nav]
    for kind in checks:
        step: dict = {"action": "assert", "kind": kind, "tag": f"SMOKE-{kind}"}
        if ignore:
            step["ignore"] = list(ignore)
        steps.append(step)
    if screenshot:
        steps.append({"action": "screenshot", "name": "page", "tag": "SMOKE-SHOT"})
    return steps


# `a.href` resolves relative links to absolute for us. Filtering happens in
# Python rather than here because `location.origin` is the string "null" on
# file:// pages — a JS-side origin compare silently finds nothing when smoke
# is pointed at a local static build.
_LINKS_JS = "() => [...document.querySelectorAll('a[href]')].map(a => a.href)"


def same_origin(seed_url: str, href: str) -> bool:
    """True when `href` belongs to the same site as `seed_url`.

    Cross-origin links are somebody else's site: crawling them tests the wrong
    app and sends traffic its operator never agreed to. file:// has no origin,
    so it is scoped to the seed's own directory instead — enough for a local
    build, and it cannot wander up into the rest of the filesystem.
    """
    s, h = urlparse(seed_url), urlparse(href)
    if h.scheme != s.scheme or h.scheme not in ("http", "https", "file"):
        return False
    if h.scheme == "file":
        base = s.path.rsplit("/", 1)[0]
        return h.path.startswith(f"{base}/")
    return h.netloc == s.netloc


async def same_origin_links(session, seed_url: str, limit: int) -> list[str]:
    """Up to `limit` distinct same-origin links on the current page."""
    if limit <= 0:
        return []
    try:
        hrefs = await session.page.evaluate(_LINKS_JS)
    except Exception:
        return []
    seed = urldefrag(seed_url)[0]
    seen = {seed}
    out: list[str] = []
    for href in hrefs:
        clean = urldefrag(href)[0]
        if clean in seen or not same_origin(seed, clean):
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= limit:
            break
    return out
