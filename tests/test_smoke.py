"""Site-agnostic smoke checks — `ui-blackbox smoke <URL>`.

The fast-lane half pins the step synthesis and the noise-suppression logic; the
browser half runs the checks against fixtures that carry one planted defect each,
so a check that stops detecting (or starts over-reporting) fails here.
"""
from __future__ import annotations

import pytest

from blackbox_mcp.testing import runner, smoke
from blackbox_mcp.tools.assertion import HEALTH_KINDS, _ignored, assert_

from conftest import fixture_url

# ── fast lane: no browser ──────────────────────────────────────────────


def test_default_checks_exclude_console_noise():
    """console.error fires on almost every real site (ads, deprecation
    warnings), so it must not fail a default run — it is --strict only."""
    assert "no_console_errors" not in smoke.DEFAULT_CHECKS
    assert "no_console_errors" in smoke.STRICT_CHECKS
    assert "no_js_errors" in smoke.DEFAULT_CHECKS  # the headline signal stays on


def test_smoke_steps_shape():
    steps = smoke.smoke_steps("https://example.com/a")
    assert steps[0] == {"action": "navigate", "url": "https://example.com/a",
                        "tag": "SMOKE-LOAD", "priority": "high"}
    kinds = [s["kind"] for s in steps if s["action"] == "assert"]
    assert kinds == list(smoke.DEFAULT_CHECKS)
    assert steps[-1]["action"] == "screenshot"
    # No selector anywhere: that is the whole point — nothing to break when a
    # site renames a data-test attribute.
    assert not any("selector" in s or "target" in s for s in steps)


def test_smoke_steps_options():
    steps = smoke.smoke_steps("https://example.com/", checks=("no_js_errors",),
                              ignore=["analytics"], screenshot=False,
                              expect_status=200)
    assert steps[0]["expect_status"] == 200
    assert [s["action"] for s in steps] == ["navigate", "assert"]
    assert steps[1]["ignore"] == ["analytics"]


def test_scenario_name_is_filesystem_safe_and_stable():
    n = smoke.scenario_name("https://shop.example.com/cart?id=1#frag")
    assert n.startswith("smoke_") and "/" not in n and "?" not in n
    assert n == smoke.scenario_name("https://shop.example.com/cart?id=1#frag")
    # Distinct pages must not collapse onto one report name.
    assert smoke.scenario_name("https://a.com/x") != smoke.scenario_name("https://a.com/y")


def test_same_origin_never_leaves_the_site():
    seed = "https://shop.example.com/a/b.html"
    assert smoke.same_origin(seed, "https://shop.example.com/other") is True
    assert smoke.same_origin(seed, "https://evil.example.com/x") is False
    assert smoke.same_origin(seed, "http://shop.example.com/x") is False   # scheme
    assert smoke.same_origin(seed, "mailto:someone@example.com") is False
    assert smoke.same_origin(seed, "javascript:void(0)") is False


def test_same_origin_scopes_file_urls_to_their_directory():
    """file:// has no origin, so an origin compare would either match nothing
    or match the whole filesystem. Neither is acceptable for a crawl."""
    seed = "file:///srv/build/index.html"
    assert smoke.same_origin(seed, "file:///srv/build/about.html") is True
    assert smoke.same_origin(seed, "file:///srv/build/docs/x.html") is True
    assert smoke.same_origin(seed, "file:///etc/passwd") is False
    assert smoke.same_origin(seed, "file:///srv/other/x.html") is False


def test_ignore_patterns():
    assert _ignored("https://cdn.ads.com/x.js", ["ads%."]) is False
    assert _ignored("https://cdn.ads.com/x.js", [r"ads\."]) is True
    assert _ignored("https://app.local/api", [r"ads\."]) is False
    assert _ignored(None, [".*"]) is False       # nothing to match
    assert _ignored("anything", []) is False     # no patterns = suppress nothing


@pytest.mark.parametrize("kind", HEALTH_KINDS)
def test_health_kinds_need_no_target(kind):
    """A health step without `target` must dispatch, not be rejected as
    malformed — the runner's required-field guard is kind-aware."""
    assert runner.missing_fields({"action": "assert", "kind": kind}) == []


def test_targeted_kind_still_requires_target():
    assert runner.missing_fields({"action": "assert", "kind": "text_visible"}) == ["target"]
    assert runner.missing_fields({"action": "assert"}) == ["kind"]
    assert runner.missing_fields(
        {"action": "assert", "kind": "text_visible", "target": "x"}) == []


async def test_unknown_kind_is_reported_not_raised():
    res = await assert_("no_such_kind", "x")
    assert res["passed"] is False and "unknown kind" in res["actual"]


# ── browser lane ───────────────────────────────────────────────────────
# Marked automatically by conftest: every test below takes the `session`
# fixture, so the fast lane (-m "not browser") skips them.


async def _run(url, **kw):
    return await runner.run(smoke.smoke_steps(url, **kw), name="smoke",
                            continue_on_fail=True)


def _by_kind(result):
    return {s["expected"]: s for s in result["steps"] if s.get("action") == "assert"}


async def test_clean_page_passes_every_check(session):
    res = await _run(fixture_url("smoke_clean.html"), checks=smoke.STRICT_CHECKS)
    failed = [s for s in res["steps"] if not s["passed"]]
    assert not failed, failed
    assert res["summary"]["failed"] == 0


async def test_broken_page_trips_each_check(session):
    res = await _run(fixture_url("smoke_broken.html"), checks=smoke.STRICT_CHECKS)
    steps = _by_kind(res)
    assert steps["no_js_errors"]["passed"] is False
    assert "uncaught boom" in steps["no_js_errors"]["actual"]
    assert steps["no_console_errors"]["passed"] is False
    assert steps["no_broken_images"]["passed"] is False
    assert "definitely-missing-image" in steps["no_broken_images"]["actual"]
    # The page itself does render — a broken subresource must not be reported
    # as a white screen.
    assert steps["page_rendered"]["passed"] is True


async def test_white_screen_is_caught_though_http_is_fine(session):
    """The SPA that 200s and paints nothing. A status-code check calls this
    green; page_rendered is the reason smoke is worth more than curl."""
    res = await _run(fixture_url("smoke_blank.html"))
    steps = _by_kind(res)
    assert steps["page_rendered"]["passed"] is False
    assert "painted=0" in steps["page_rendered"]["actual"]


async def test_errors_are_scoped_to_the_page_that_caused_them(session):
    """Buffers accumulate across a session, so without per-navigate marks a
    clean page checked after a broken one inherits its failures."""
    bad = await _run(fixture_url("smoke_broken.html"))
    assert bad["summary"]["failed"] > 0
    good = await _run(fixture_url("smoke_clean.html"))
    assert good["summary"]["failed"] == 0, _by_kind(good)


async def test_ignore_url_suppresses_matched_noise_only(session):
    """Third-party noise can be filtered without blinding the real signal."""
    res = await _run(fixture_url("smoke_broken.html"),
                     ignore=["definitely-missing"])
    steps = _by_kind(res)
    assert steps["no_failed_requests"]["passed"] is True
    assert steps["no_broken_images"]["passed"] is True
    assert steps["no_js_errors"]["passed"] is False  # genuine defect survives


async def test_failed_step_carries_an_actionable_hint(session):
    res = await _run(fixture_url("smoke_blank.html"))
    hint = _by_kind(res)["page_rendered"]["ai_suggestion"]
    assert hint and "target" not in hint  # no target exists to "verify"


async def test_same_origin_links_are_discovered_and_bounded(session):
    from blackbox_mcp.tools.navigate import navigate

    url = fixture_url("smoke_clean.html")
    await navigate(url)
    links = await smoke.same_origin_links(session, url, 5)
    assert any("smoke_clean_two.html" in u for u in links)
    assert url not in links                      # never re-check the seed
    assert await smoke.same_origin_links(session, url, 0) == []
