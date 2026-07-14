"""Regression guards for code-review fixes."""
from __future__ import annotations


from blackbox_mcp.tools.console import get_console_logs
from blackbox_mcp.tools.interact import interact
from blackbox_mcp.tools.wait import wait
from blackbox_mcp.browser.locator import _testid_selector
from blackbox_mcp.testing import runner


# C1 — console "warn" must match Playwright's "warning"
async def test_console_warn_level_matches_warning(session):
    await session.page.set_content("<script>console.warn('heads up')</script>")
    await session.page.wait_for_timeout(100)
    warns = (await get_console_logs(level="warn"))["logs"]
    assert any("heads up" in w["text"] for w in warns)


# C2 — wait(selector) honors timeout instead of hanging 30s
async def test_wait_selector_times_out_fast(session):
    await session.page.set_content("<div></div>")
    r = await wait(selector="testid=never", timeout_ms=300)
    assert r["ok"] is False and "not visible" in r["error"]


# C3 — interact type/select/press require a value
async def test_interact_requires_value(session):
    await session.page.set_content("<input data-testid='i'>")
    r = await interact("type", "testid=i", None)
    assert r["ok"] is False and "requires a value" in r["error"]


# C6 — testid selector escapes embedded quotes
def test_testid_selector_escapes_quotes():
    assert _testid_selector('a"b') == '[data-testid="a\\"b"]'


# C4 — malformed scenario step gives a clear error, not a raw KeyError
async def test_runner_reports_missing_field(session):
    steps = [{"action": "assert", "target": "x"}]  # missing 'kind'
    res = await runner.run(steps, name="bad", continue_on_fail=True)
    step = res["steps"][0]
    assert step["passed"] is False
    assert "missing required field" in step["actual"]
    assert "kind" in step["actual"]
