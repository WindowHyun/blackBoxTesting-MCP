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
