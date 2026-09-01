"""Phase 3 — scenario runner + report (SM-01,02,03,04,06,08)."""
from __future__ import annotations

import dataclasses

import pytest
from conftest import fixture_url

from blackbox_mcp.testing import report, runner
from blackbox_mcp.tools.scenario import run_scenario


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    cfg = dataclasses.replace(report.CONFIG, report_dir=tmp_path)
    monkeypatch.setattr(report, "CONFIG", cfg)
    return tmp_path


def _login_steps():
    return [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "interact", "type": "type", "selector": "testid=email", "value": "u@x.com"},
        {"action": "interact", "type": "click", "selector": "testid=submit"},
        {"action": "assert", "kind": "text_visible", "target": "로그인됨"},
    ]


async def test_passing_scenario(session):
    res = await runner.run(_login_steps(), name="login")
    assert res["summary"]["total"] == 4
    assert res["summary"]["failed"] == 0
    assert res["summary"]["pass_rate"] == 1.0
    # resolved_by recorded on interact steps (SM-06)
    click = res["steps"][2]
    assert click["resolved_by"] == "testid"
    # meta present (SM-08)
    assert res["meta"]["playwright"] and res["meta"]["credentials_masked"] is True


async def test_stops_on_failure(session):
    steps = _login_steps() + [{"action": "assert", "kind": "text_visible", "target": "절대없음"}]
    # inject a failing assert in the middle
    steps = [steps[0], {"action": "assert", "kind": "text_visible", "target": "절대없음"}, steps[1]]
    res = await runner.run(steps, name="stop", continue_on_fail=False)
    assert res["summary"]["failed"] == 1
    # Execution stops after the failing step, but the un-run remainder is
    # reported as skipped instead of vanishing (total = whole scenario).
    assert res["summary"]["total"] == 3
    assert res["summary"]["skipped"] == 1
    assert res["steps"][2]["skipped"] is True
    bad = res["steps"][1]
    assert bad["passed"] is False
    assert bad["severity"] == "assertion"
    assert bad["ai_suggestion"]            # failure hint present (SM-05)
    assert bad["screenshot"] is None or bad["screenshot"].startswith("screenshots/")


async def test_continue_on_fail_runs_all(session):
    steps = [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "assert", "kind": "text_visible", "target": "절대없음"},
        {"action": "assert", "kind": "text_visible", "target": "로그인"},
    ]
    res = await runner.run(steps, name="cont", continue_on_fail=True)
    assert res["summary"]["total"] == 3
    assert res["summary"]["failed"] == 1


async def test_scenario_supports_extension_actions(session):
    # iframe with an inner button; scenario switches into it and asserts
    await session.page.set_content(
        "<iframe id='f' srcdoc=\"<button data-testid='inner'>안쪽</button>\"></iframe>"
    )
    await session.page.wait_for_timeout(100)
    steps = [
        {"action": "switch_frame", "selector": "#f"},
        {"action": "assert", "kind": "element_visible", "target": "testid=inner"},
        {"action": "screenshot"},
        {"action": "switch_frame", "selector": None},
    ]
    res = await runner.run(steps, name="frames", continue_on_fail=True)
    assert res["summary"]["failed"] == 0
    # the explicit screenshot step captured an image
    shot_step = next(s for s in res["steps"] if s["action"] == "screenshot")
    assert shot_step["screenshot"] is None or shot_step["screenshot"].startswith("screenshots/")


async def test_credentials_masked_in_report(session, report_dir):
    import os
    os.environ["TEST_PW"] = "supersecret"
    steps = [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "interact", "type": "type", "selector": "testid=password", "value": "${TEST_PW}"},
    ]
    res = await runner.run(steps, name="mask", continue_on_fail=True)
    raw_dump = str(res["steps"][1]["raw"])
    assert "supersecret" not in raw_dump   # masked / not resolved in report


async def test_report_writes_all_formats(session, report_dir):
    res = await run_scenario(_login_steps(), name="rep", report_format="all")
    files = res["report_files"]
    assert {"json", "md", "html"} <= set(files)
    htmls = list(report_dir.glob("*.html"))
    assert htmls and "PASS" in htmls[0].read_text(encoding="utf-8")


# ── P1-04: ${VAR} substitution across the whole step ─────────────────
def test_resolve_step_covers_every_string_field(monkeypatch):
    """Resolution used to run on navigate.url and interact.value only, so an
    assert target / wait selector / mock pattern kept the literal placeholder
    and could never match."""
    monkeypatch.setenv("BASE_URL", "https://shop.test")
    monkeypatch.setenv("ITEM", "widget")
    step = {"action": "assert", "kind": "url_contains",
            "target": "${BASE_URL}/orders", "expected": "${ITEM}",
            "timeout_ms": 4000}
    resolved, missing = runner._resolve_step(step)
    assert resolved["target"] == "https://shop.test/orders"
    assert resolved["expected"] == "widget"
    assert resolved["timeout_ms"] == 4000        # non-strings pass through
    assert missing == []


def test_resolve_step_does_not_mutate_the_original(monkeypatch):
    """The report's raw/selector_input are built from the original step, so the
    placeholder — not the resolved secret — is what reaches disk."""
    monkeypatch.setenv("PW_FOR_TEST", "s3cret")
    step = {"action": "interact", "type": "type", "selector": "#p",
            "value": "${PW_FOR_TEST}"}
    resolved, _ = runner._resolve_step(step)
    assert resolved["value"] == "s3cret"
    assert step["value"] == "${PW_FOR_TEST}"


def test_resolve_step_reports_unset_vars_once(monkeypatch):
    monkeypatch.delenv("NO_SUCH_VAR_A", raising=False)
    monkeypatch.delenv("NO_SUCH_VAR_B", raising=False)
    step = {"action": "assert", "kind": "url_is",
            "target": "${NO_SUCH_VAR_A}/x/${NO_SUCH_VAR_A}",
            "expected": "${NO_SUCH_VAR_B}"}
    resolved, missing = runner._resolve_step(step)
    assert missing == ["NO_SUCH_VAR_A", "NO_SUCH_VAR_B"]   # de-duplicated, ordered
    assert resolved["target"] == "${NO_SUCH_VAR_A}/x/${NO_SUCH_VAR_A}"


async def test_assert_target_resolves_env_var(session, monkeypatch):
    """End-to-end: the assert target now compares against the resolved URL."""
    url = fixture_url("basic.html")
    monkeypatch.setenv("BASE_PAGE", url)
    res = await runner.run(
        [{"action": "navigate", "url": "${BASE_PAGE}"},
         {"action": "assert", "kind": "url_contains", "target": "${BASE_PAGE}"}],
        name="env_in_assert", continue_on_fail=True)
    assert [s["passed"] for s in res["steps"]] == [True, True]
    # the report keeps the placeholder, never the resolved value
    assert res["steps"][1]["raw"]["target"] == "${BASE_PAGE}"


async def test_unset_var_is_flagged_on_any_field(session, monkeypatch):
    """A typo'd ${VAR} in a field other than url/value used to fail silently."""
    monkeypatch.delenv("TYPOED_VAR", raising=False)
    res = await runner.run(
        [{"action": "navigate", "url": fixture_url("basic.html")},
         {"action": "assert", "kind": "url_contains", "target": "${TYPOED_VAR}"}],
        name="env_typo", continue_on_fail=True)
    step = res["steps"][1]
    assert step["passed"] is False
    assert "TYPOED_VAR" in step["ai_suggestion"]
